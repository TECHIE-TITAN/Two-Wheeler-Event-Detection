import time
import csv
import os
import threading
import mpu_utils
import gps_utils
import speed_limit_utils
import firebase_uploader
from enum import Enum
import glob  # added for image lookup

# === SYSTEM CONFIGURATION ===
TARGET_HZ = 30
BATCH_SIZE = TARGET_HZ  # 1-second batches
SAMPLE_INTERVAL = 1.0 / TARGET_HZ
SPEED_LIMIT_MIN_INTERVAL_S = 10.0  # throttle speed limit lookups
USER_ID = "WlDdtoNgVNc3pEEHzWkKthuTLXF2"
CONTROL_POLL_INTERVAL_S = 0.5
CSV_FILENAME = "sensor_data.csv"
OLA_MAPS_API_KEY = "50c25aHLICdWQ4JbXp2MZwgmliGxvqJ8os1MOYe3"  # restored API key constant
GPS_TIMEOUT_SECONDS = 5.0
IMAGE_DIR = "captured_images"  # added for image matching

# === STATE MACHINE ===
class RideState(Enum):
    IDLE = 0
    ACTIVE = 1

ride_state = RideState.IDLE
prev_is_active_flag = False  # for edge detection on control flags

# === SHARED DATA (thread-safe) ===
data_lock = threading.Lock()
latest_mpu = (None, None, None, None, None, None)
latest_gps = (None, None, None)
latest_speed_limit = None
last_speed_limit_fetch = 0.0
stop_event = threading.Event()

# Firebase ride context
ride_id = None
start_time_ms = None
end_time_ms = None

# Raw buffered rows (entire ride, uploaded after ride ends)
raw_rows_buffer = []
raw_buffer_lock = threading.Lock()

# Per-batch accumulation
batch_rows = []

# Accel-based speed estimation state
accel_buffer = []
current_speed_ms = 0.0
speed_calculation_lock = threading.Lock()
gps_last_update_time = 0.0

# Control flags cache
current_is_active_flag = False
current_calculate_model_flag = False
last_control_poll_wall = 0.0

# ================== SPEED / FALLBACK LOGIC ==================

def add_accel_to_buffer(acc_x):
    global accel_buffer
    with speed_calculation_lock:
        accel_ms2 = acc_x * 9.81 if acc_x is not None else 0.0
        if abs(accel_ms2) < 0.5:
            accel_ms2 = 0.0
        accel_buffer.append(accel_ms2)
        if len(accel_buffer) > TARGET_HZ:
            accel_buffer = accel_buffer[-TARGET_HZ:]

def calculate_speed_from_accel():
    global current_speed_ms, accel_buffer
    with speed_calculation_lock:
        if not accel_buffer:
            return current_speed_ms
        avg_accel_ms2 = sum(accel_buffer) / len(accel_buffer)
        if abs(avg_accel_ms2) < 0.3:
            avg_accel_ms2 = 0.0
            current_speed_ms *= 0.95  # decay when near zero
        time_period = len(accel_buffer) / TARGET_HZ
        new_speed_ms = current_speed_ms + avg_accel_ms2 * time_period
        if abs(new_speed_ms) < 0.5:
            new_speed_ms = 0.0
        new_speed_ms = max(0.0, min(55.6, new_speed_ms))  # clamp ~200 km/h
        current_speed_ms = new_speed_ms
        return current_speed_ms

def get_final_speed_kmh():
    global latest_gps, current_speed_ms, gps_last_update_time
    now = time.time()
    with data_lock:
        gps_data = latest_gps
        last_gps_update = gps_last_update_time
    gps_is_stale = (now - last_gps_update) > GPS_TIMEOUT_SECONDS
    # Force fallback by clearing speed if stale but keep last lat/lon
    if gps_is_stale and gps_data and gps_data[2] is not None:
        with data_lock:
            latest_gps = (gps_data[0], gps_data[1], None)
            gps_data = latest_gps
    gps_speed_kmh = None
    if gps_data and gps_data[2] is not None and not gps_is_stale:
        gps_speed_kmh = gps_data[2]
        if gps_speed_kmh < 0 or gps_speed_kmh > 300:
            gps_speed_kmh = None
    if gps_speed_kmh is not None:
        with speed_calculation_lock:
            current_speed_ms = gps_speed_kmh / 3.6
        return gps_speed_kmh, "GPS"
    # Fallback to accel integration
    accel_speed_ms = calculate_speed_from_accel()
    accel_speed_kmh = accel_speed_ms * 3.6
    return accel_speed_kmh, "ACCEL (GPS_STALE)" if gps_is_stale else "ACCEL"

# ================== SENSOR THREADS ==================

def mpu_thread():
    global latest_mpu
    while not stop_event.is_set():
        data = mpu_utils.get_mpu_data()
        with data_lock:
            latest_mpu = data
        if data and data[0] is not None:
            add_accel_to_buffer(data[0])
        time.sleep(0.005)

def gps_thread(gps_serial):
    global latest_gps, gps_last_update_time
    consecutive_errors = 0
    max_consecutive_errors = 5
    print("GPS thread started...")
    while not stop_event.is_set():
        try:
            gps_data = gps_utils.get_gps_data(gps_serial)
            if gps_data and gps_data != (None, None, None):
                with data_lock:
                    latest_gps = gps_data
                    gps_last_update_time = time.time()
                consecutive_errors = 0
            else:
                # Preserve last lat/lon but force speed None
                with data_lock:
                    latest_gps = (latest_gps[0], latest_gps[1], None)
            consecutive_errors = 0
        except Exception as e:
            print(f"GPS thread error: {e}")
            consecutive_errors += 1
            if consecutive_errors >= max_consecutive_errors:
                print("GPS multiple errors - relying on accelerometer fallback")
        time.sleep(0.2)
    print("GPS thread stopped.")

# === IMAGE MATCHING (simple latest <= timestamp) ===
def get_latest_image_for_timestamp(target_ts_ms):
    try:
        pattern = os.path.join(IMAGE_DIR, "frame_*.jpg")
        candidates = glob.glob(pattern)
        best = None
        best_diff = 1e18
        for path in candidates:
            name = os.path.basename(path)
            try:
                ts_part = name.split('_')[1].split('.')[0]
                ts = int(ts_part)
            except Exception:
                continue
            diff = target_ts_ms - ts
            if 0 <= diff < best_diff:
                best_diff = diff
                best = path
        return best
    except Exception:
        return None

# ================== CONTROL FLAG POLLING ==================

def poll_control_flags():
    global current_is_active_flag, current_calculate_model_flag, last_control_poll_wall
    try:
        is_active, calc_model = firebase_uploader.get_control_flags_for_ride(USER_ID, ride_id)
        current_is_active_flag = is_active
        current_calculate_model_flag = calc_model
    except Exception as e:
        print(f"Control flag poll error: {e}")
    last_control_poll_wall = time.time()

# ================== RIDE WORKFLOW HELPERS ==================

def start_new_ride():
    global ride_id, start_time_ms, raw_rows_buffer, batch_rows
    ride_id = firebase_uploader.get_next_ride_id(USER_ID)
    start_time_ms = int(time.time()*1000)
    firebase_uploader.init_ride_for_ride(USER_ID, ride_id, start_time_ms)
    print(f"Ride {ride_id} started @ {start_time_ms}")
    with raw_buffer_lock:
        raw_rows_buffer = []
    batch_rows = []


def end_ride_process():
    global end_time_ms
    end_time_ms = int(time.time()*1000)
    print(f"Ride {ride_id} ended @ {end_time_ms}")
    if current_calculate_model_flag:
        # Snapshot and process
        with raw_buffer_lock:
            snapshot = list(raw_rows_buffer)
        try:
            ok = firebase_uploader.upload_raw_data(USER_ID, ride_id, snapshot)
            print(f"Raw upload status: {ok}")
            summary = firebase_uploader.process_model_placeholder(snapshot)
            firebase_uploader.write_processed_summary(USER_ID, ride_id, summary)
        except Exception as e:
            print(f"Post-process error: {e}")
    # Set end time then finalize (always set end time even if no model)
    firebase_uploader.set_ride_end_time(USER_ID, ride_id, end_time_ms)
    firebase_uploader.finalize_ride(USER_ID, ride_id)

# ================== BATCH HANDLING ==================

def flush_batch(writer):
    global batch_rows, latest_speed_limit, last_speed_limit_fetch
    if not batch_rows:
        return
    # Append batch to global raw buffer
    with raw_buffer_lock:
        raw_rows_buffer.extend(batch_rows)
    # Write batch to CSV
    writer.writerows(batch_rows)
    # Force flush to reduce loss risk
    writer_file = writer.writerows.__self__  # underlying file object
    try:
        writer_file.flush()
    except Exception:
        pass
    # Warnings & realtime push using last row
    last_row = batch_rows[-1]
    speed = last_row['speed']
    speed_limit = last_row['speed_limit']
    warnings = firebase_uploader.build_speeding_warning(speed, speed_limit)
    # Push combined realtime update
    firebase_uploader.push_realtime_batch(USER_ID, speed, speed_limit, warnings, (
        last_row['acc_x'], last_row['acc_y'], last_row['acc_z'],
        last_row['gyro_x'], last_row['gyro_y'], last_row['gyro_z']
    ), last_row['timestamp'])
    # Attempt throttled speed limit refresh ONLY at batch boundary
    if last_row['latitude'] is not None and last_row['longitude'] is not None:
        now = time.time()
        if (latest_speed_limit is None) or (now - last_speed_limit_fetch >= SPEED_LIMIT_MIN_INTERVAL_S):
            def refresh_speed_limit(lat, lon):
                global latest_speed_limit, last_speed_limit_fetch
                try:
                    latest_speed_limit = speed_limit_utils.get_speed_limit(lat, lon, OLA_MAPS_API_KEY)
                    last_speed_limit_fetch = time.time()
                except Exception as e:
                    print(f"Speed limit refresh error: {e}")
            threading.Thread(target=refresh_speed_limit, args=(last_row['latitude'], last_row['longitude']), daemon=True).start()
    # Clear batch
    batch_rows = []

# ================== MAIN LOOP ==================

def main():
    global ride_state, prev_is_active_flag, current_is_active_flag, current_calculate_model_flag
    global latest_speed_limit, last_speed_limit_fetch, batch_rows

    # Firebase auth
    try:
        firebase_uploader.init_auth()
    except Exception as e:
        print(f"Firebase auth init failed: {e}")

    # Init sensors
    print("Initializing sensors...")
    mpu_utils.init_mpu()
    print("MPU ready.")
    print("Initializing GPS...")
    try:
        gps_serial = gps_utils.init_gps()
    except Exception as e:
        print(f"GPS init failed: {e}")
        gps_serial = None

    # Start threads
    threads = [threading.Thread(target=mpu_thread, daemon=True)]
    if gps_serial:
        threads.append(threading.Thread(target=gps_thread, args=(gps_serial,), daemon=True))
    for t in threads:
        t.start()
    print(f"Threads started: {len(threads)}")

    # Prepare CSV (reduced columns per new raw data spec + image_path)
    fieldnames = ['timestamp','image_path','acc_x','acc_y','acc_z','gyro_x','gyro_y','gyro_z','latitude','longitude','speed','speed_limit']
    file_exists = os.path.isfile(CSV_FILENAME)
    csv_file = open(CSV_FILENAME, 'a', newline='')
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    if not file_exists:
        writer.writeheader()

    print("System entering IDLE. Awaiting is_active flag...")
    next_sample_time = time.perf_counter()
    sample_counter = 0
    last_rate_t0 = time.time()

    try:
        while not stop_event.is_set():
            # Timing control
            now = time.perf_counter()
            if now < next_sample_time:
                time.sleep(next_sample_time - now)
            next_sample_time += SAMPLE_INTERVAL

            # Poll control flags periodically
            wall_now = time.time()
            if (wall_now - last_control_poll_wall) >= CONTROL_POLL_INTERVAL_S:
                threading.Thread(target=poll_control_flags, daemon=True).start()

            # State transitions
            if ride_state == RideState.IDLE:
                if current_is_active_flag and not prev_is_active_flag:
                    start_new_ride()
                    ride_state = RideState.ACTIVE
                prev_is_active_flag = current_is_active_flag
                continue  # no sampling while idle

            if ride_state == RideState.ACTIVE:
                # Detect end of ride
                if (not current_is_active_flag) and prev_is_active_flag:
                    # Flush partial batch before ending
                    flush_batch(writer)
                    end_ride_process()
                    ride_state = RideState.IDLE
                    prev_is_active_flag = current_is_active_flag
                    continue
                prev_is_active_flag = current_is_active_flag

            # === Active sampling ===
            with data_lock:
                mpu = latest_mpu
                gps = latest_gps
            lat, lon, _ = gps
            final_speed_kmh, source = get_final_speed_kmh()

            # Build row
            ts_ms = int(time.time()*1000)
            img_path = get_latest_image_for_timestamp(ts_ms) if ride_state == RideState.ACTIVE else None
            row = {
                'timestamp': ts_ms,
                'image_path': img_path or '',
                'acc_x': mpu[0], 'acc_y': mpu[1], 'acc_z': mpu[2],
                'gyro_x': mpu[3], 'gyro_y': mpu[4], 'gyro_z': mpu[5],
                'latitude': lat, 'longitude': lon,
                'speed': final_speed_kmh,
                'speed_limit': latest_speed_limit
            }
            batch_rows.append(row)

            # Batch full?
            if len(batch_rows) >= BATCH_SIZE:
                flush_batch(writer)

            # Sampling rate monitor every 5s
            sample_counter += 1
            if (wall_now - last_rate_t0) >= 5.0:
                actual_rate = sample_counter / (wall_now - last_rate_t0)
                print(f"Rate: {actual_rate:.1f} Hz | Speed {final_speed_kmh:.2f} km/h ({source}) | State {ride_state.name}")
                sample_counter = 0
                last_rate_t0 = wall_now

    except KeyboardInterrupt:
        print("Keyboard interrupt - shutting down")
    finally:
        print("Final flush & shutdown...")
        flush_batch(writer)
        csv_file.close()
        stop_event.set()
        for t in threads:
            t.join(timeout=0.5)
        if gps_serial:
            try:
                gps_serial.close()
            except Exception:
                pass
        # If ride still active mark end gracefully
        if ride_state == RideState.ACTIVE:
            end_ride_process()
        print("Shutdown complete.")

if __name__ == '__main__':
    main()
