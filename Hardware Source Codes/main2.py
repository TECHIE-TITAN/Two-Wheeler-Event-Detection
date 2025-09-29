import time
import csv
import os
import threading
import glob
import mpu_utils  # type: ignore
import gps_utils  # type: ignore
import speed_limit_utils  # type: ignore
import firebase_uploader  # type: ignore

TARGET_HZ = 30
SAMPLE_INTERVAL = 1.0 / TARGET_HZ
OLA_MAPS_API_KEY = "50c25aHLICdWQ4JbXp2MZwgmliGxvqJ8os1MOYe3"
SPEED_LIMIT_REFRESH_S = 1.0
FIREBASE_PUSH_INTERVAL_S = 1.0
USER_ID = "WlDdtoNgVNc3pEEHzWkKthuTLXF2"
CONTROL_POLL_INTERVAL_S = 0.5

IMAGE_DIR = "captured_images/"
CSV_FILENAME = "sensor_data.csv"

data_lock = threading.Lock()
latest_mpu = (None, None, None, None, None, None)
latest_gps = (None, None, None)
latest_speed_limit = None
last_speed_limit_fetch = 0.0
stop_event = threading.Event()

# Enable/disable sensor reads without killing threads
collecting_enabled = threading.Event()
collecting_enabled.clear()

# Speed calculation buffers and state
accel_buffer = []
current_speed_ms = 0.0
speed_calculation_lock = threading.Lock()
gps_last_update_time = 0.0
GPS_TIMEOUT_SECONDS = 5.0


def add_accel_to_buffer(acc_x):
    """Add acceleration data to buffer and maintain 1-second window (30 samples)"""
    global accel_buffer
    with speed_calculation_lock:
        # Convert from g to m/s² (assuming acc_x is in g units)
        accel_ms2 = acc_x * 9.81 if acc_x is not None else 0.0
        
        accel_buffer.append(accel_ms2)
        
        # Keep only last 30 samples (1 second at 30Hz)
        if len(accel_buffer) > TARGET_HZ:
            accel_buffer = accel_buffer[-TARGET_HZ:]


def calculate_speed_from_accel():
    """Calculate speed using average acceleration over 1 second and v = u + at"""
    global current_speed_ms, accel_buffer
    
    with speed_calculation_lock:
        if len(accel_buffer) == 0:
            return current_speed_ms
        
        # Calculate average acceleration over the buffer period
        avg_accel_ms2 = sum(accel_buffer) / len(accel_buffer)
        
        # Apply deadband to filter out noise (ignore very small accelerations)
        deadband_threshold = 0.2  # m/s² - adjust based on sensor noise
        if abs(avg_accel_ms2) < deadband_threshold:
            avg_accel_ms2 = 0.0
        
        # Time period: buffer size / sampling rate
        time_period = len(accel_buffer) / TARGET_HZ  # seconds
        
        # Apply kinematic equation: v = u + at
        new_speed_ms = current_speed_ms + (avg_accel_ms2 * time_period)
        
        # Ensure speed doesn't go negative
        new_speed_ms = max(0.0, new_speed_ms)
        
        # Apply reasonable speed limits (max ~200 km/h = ~55.6 m/s)
        new_speed_ms = min(55.6, new_speed_ms)
        
        current_speed_ms = new_speed_ms
        
        return current_speed_ms


def get_final_speed_kmh():
    """
    Get final speed in km/h using priority system:
    1. GPS speed (if available and fresh)
    2. Accelerometer-based calculation (fallback)
    """
    global latest_gps, current_speed_ms, gps_last_update_time
    
    current_time = time.time()
    
    with data_lock:
        gps_data = latest_gps
        last_gps_update = gps_last_update_time
    
    # Check if GPS data is stale
    gps_is_stale = (current_time - last_gps_update) > GPS_TIMEOUT_SECONDS
    
    # Extract GPS speed (assuming it's in km/h)
    gps_speed_kmh = None
    if gps_data and len(gps_data) >= 3 and gps_data[2] is not None and not gps_is_stale:
        gps_speed_kmh = gps_data[2]
        
        # Validate GPS speed (reasonable range)
        if gps_speed_kmh < 0 or gps_speed_kmh > 300:  # 300 km/h max
            gps_speed_kmh = None
    
    if gps_speed_kmh is not None:
        # Use GPS speed and sync our accelerometer-based speed to it
        with speed_calculation_lock:
            current_speed_ms = gps_speed_kmh / 3.6  # Convert km/h to m/s
        return gps_speed_kmh, "GPS"
    else:
        # Use accelerometer-based speed calculation
        accel_speed_ms = calculate_speed_from_accel()
        accel_speed_kmh = accel_speed_ms * 3.6  # Convert m/s to km/h
        
        # Indicate why accelerometer is being used
        if gps_is_stale and gps_data != (None, None, None):
            return accel_speed_kmh, "ACCEL (GPS_STALE)"
        else:
            return accel_speed_kmh, "ACCEL"


def mpu_thread():
    global latest_mpu
    while not stop_event.is_set():
        if not collecting_enabled.is_set():
            time.sleep(0.02)
            continue
        data = mpu_utils.get_mpu_data()
        with data_lock:
            latest_mpu = data
        
        # Add acceleration data to buffer for speed calculation
        if data and len(data) >= 1 and data[0] is not None:
            add_accel_to_buffer(data[0])  # Use acc_x for speed calculation
            
        time.sleep(0.005)


def gps_thread(gps_serial):
    global latest_gps, gps_last_update_time
    last_valid_gps_time = 0
    gps_read_count = 0
    valid_gps_count = 0
    consecutive_errors = 0
    max_consecutive_errors = 5  # Reset GPS data after 5 consecutive errors
    
    print("GPS thread started...")
    
    while not stop_event.is_set():
        if not collecting_enabled.is_set():
            time.sleep(0.1)
            continue
        try:
            gps_data = gps_utils.get_gps_data(gps_serial)
            gps_read_count += 1
            
            if gps_data and gps_data != (None, None, None):
                valid_gps_count += 1
                last_valid_gps_time = time.time()
                consecutive_errors = 0  # Reset error counter on successful read
                
                with data_lock:
                    if len(gps_data) == 3:
                        latest_gps = gps_data
                        gps_last_update_time = time.time()  # Update GPS timestamp
                    else:
                        latest_gps = (gps_data[0], gps_data[1], None)
                        gps_last_update_time = time.time()  # Update GPS timestamp even without speed
                
                # Print GPS data every 10 valid readings for debugging
                if valid_gps_count % 10 == 1:
                    lat, lon, speed = gps_data
                    print(f"GPS Update #{valid_gps_count}: Lat={lat:.6f}, Lon={lon:.6f}, Speed={speed:.2f} km/h")
            else:
                # GPS data is None or invalid - reset GPS data to force accelerometer fallback
                with data_lock:
                    latest_gps = (latest_gps[0], latest_gps[1], None)
                
                # Print status every 50 failed attempts
                if gps_read_count % 50 == 0:
                    time_since_last_fix = time.time() - last_valid_gps_time if last_valid_gps_time > 0 else 0
                    print(f"GPS Status: {gps_read_count} attempts, {valid_gps_count} valid readings. "
                          f"Last fix: {time_since_last_fix:.1f}s ago")
                    
        except Exception as e:
            print(f"GPS thread error: {e}")
            consecutive_errors += 1
            
            # Immediately reset GPS data on any I/O error to force accelerometer fallback
            with data_lock:
                latest_gps = (latest_gps[0], latest_gps[1], None)

            # After multiple consecutive errors, warn user
            if consecutive_errors >= max_consecutive_errors:
                print(f"GPS: {consecutive_errors} consecutive errors - using accelerometer speed calculation")
            
        time.sleep(0.2)
    
    print("GPS thread stopped.")


def get_latest_image_for_timestamp(target_timestamp_ms):
    # Keep local image path for CSV only; never upload
    image_files = glob.glob(os.path.join(IMAGE_DIR, "frame_*.jpg"))
    if not image_files:
        return None

    # Extract timestamp from filenames and find closest before or at target_timestamp_ms
    best_image = None
    smallest_diff = float('inf')

    for filepath in image_files:
        filename = os.path.basename(filepath)
        try:
            ts_part = filename.split('_')[1].split('.')[0]
            image_ts = int(ts_part)
            time_diff = target_timestamp_ms - image_ts
            if 0 <= time_diff < smallest_diff:
                smallest_diff = time_diff
                best_image = filepath
        except (IndexError, ValueError):
            continue

    return best_image


# Dummy processor: compute basic stats from rows and upload to processed

def dummy_process_and_upload(user_id: str, ride_id: str, rows: list):
    try:
        speeds = []
        for r in rows:
            try:
                speeds.append(float(r.get('speed') or 0))
            except Exception:
                pass
        processed = {
            "samples": len(rows),
            "avg_speed": (sum(speeds) / len(speeds)) if speeds else 0.0,
            "max_speed": max(speeds) if speeds else 0.0,
            "generated_at": int(time.time() * 1000),
        }
        firebase_uploader.upload_ride_processed_for_ride(user_id, ride_id, processed)
    except Exception as e:
        print(f"dummy_process_and_upload error: {e}")


# Helper: strip image_path from rows before uploading to Firebase

def _strip_image_path(rows: list) -> list:
    cleaned = []
    for r in rows:
        if isinstance(r, dict):
            r2 = dict(r)
            r2.pop('image_path', None)
            cleaned.append(r2)
    return cleaned


def main():
    global latest_speed_limit, last_speed_limit_fetch
    try:
        firebase_uploader.init_auth()
    except Exception as e:
        print(f"Firebase auth init failed: {e}")

    # Initialize sensors
    print("Initializing sensors...")
    mpu_utils.init_mpu()
    print("MPU initialized successfully.")
    
    print("Initializing GPS...")
    try:
        gps_serial = gps_utils.init_gps()
        print("GPS initialized successfully.")
    except Exception as e:
        print(f"GPS initialization failed: {e}")
        print("Continuing without GPS (GPS data will be None)")
        gps_serial = None

    threads = [threading.Thread(target=mpu_thread, daemon=True)]
    if gps_serial:
        threads.append(threading.Thread(target=gps_thread, args=(gps_serial,), daemon=True))
    else:
        print("Warning: GPS thread not started due to initialization failure")
    
    for t in threads:
        t.start()
    print(f"Started {len(threads)} sensor threads.")

    fieldnames = [
        'timestamp', 'image_path', 'acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z',
        'latitude', 'longitude', 'speed', 'speed_limit'
    ]

    active_logging = False
    ride_id = None
    last_fb_push = 0.0
    next_sample_time = time.perf_counter()

    print("Supervisor: waiting for latest ride is_active to become True...")

    while not stop_event.is_set():
        # Resolve latest ride id from next_ride_id
        latest_ride_id = firebase_uploader.get_current_ride_id(USER_ID)
        if latest_ride_id is None:
            time.sleep(0.5)
            continue

        # If ride switched while active, finalize previous
        if active_logging and ride_id and ride_id != latest_ride_id:
            print(f"Ride switched {ride_id} -> {latest_ride_id}. Finalizing previous ride...")
            try:
                rows = []
                if os.path.isfile(CSV_FILENAME):
                    with open(CSV_FILENAME, 'r', newline='') as f:
                        rows = list(csv.DictReader(f))
                firebase_uploader.upload_ride_raw_data_for_ride(USER_ID, ride_id, _strip_image_path(rows))
                dummy_process_and_upload(USER_ID, ride_id, rows)
                firebase_uploader.set_ride_end_time(USER_ID, ride_id, int(time.time() * 1000))
            except Exception as e:
                print(f"Finalize previous ride failed: {e}")
            active_logging = False
            collecting_enabled.clear()
            try:
                if os.path.exists(CSV_FILENAME):
                    os.remove(CSV_FILENAME)
            except Exception:
                pass

        ride_id = latest_ride_id
        is_active = firebase_uploader.get_is_active_for_ride(USER_ID, ride_id)

        if not active_logging and is_active:
            print(f"Ride {ride_id} active. Starting collection...")
            # Prepare new CSV (keep image_path locally)
            with open(CSV_FILENAME, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
            active_logging = True
            collecting_enabled.set()
            last_fb_push = 0.0
            next_sample_time = time.perf_counter()

        if active_logging and not is_active:
            print(f"Ride {ride_id} deactivated. Uploading raw_data and processed...")
            try:
                rows = []
                if os.path.isfile(CSV_FILENAME):
                    with open(CSV_FILENAME, 'r', newline='') as f:
                        rows = list(csv.DictReader(f))
                # Do not upload image_path
                firebase_uploader.upload_ride_raw_data_for_ride(USER_ID, ride_id, _strip_image_path(rows))
                dummy_process_and_upload(USER_ID, ride_id, rows)
                firebase_uploader.set_ride_end_time(USER_ID, ride_id, int(time.time() * 1000))
            except Exception as e:
                print(f"Upload on stop failed: {e}")
            active_logging = False
            collecting_enabled.clear()
            time.sleep(0.5)
            continue

        if not active_logging:
            time.sleep(0.2)
            continue

        # Active sampling
        now = time.perf_counter()
        if now < next_sample_time:
            time.sleep(max(0, next_sample_time - now))
        next_sample_time += SAMPLE_INTERVAL

        with data_lock:
            mpu = latest_mpu
            gps = latest_gps

        lat, lon, spd = gps
        final_speed_kmh, speed_source = get_final_speed_kmh()
        spd = final_speed_kmh

        # Debug speed every ~10s
        if (time.time() % 10) < SAMPLE_INTERVAL:
            print(f"Speed: {spd:.2f} km/h (Source: {speed_source})")

        # Speed limit refresh
        if lat is not None and lon is not None:
            t_now = time.time()
            if (latest_speed_limit is None) or (t_now - last_speed_limit_fetch >= SPEED_LIMIT_REFRESH_S):
                latest_speed_limit = speed_limit_utils.get_speed_limit(lat, lon, OLA_MAPS_API_KEY)
                last_speed_limit_fetch = t_now
        else:
            if (int(time.time()) % 30 == 0) and (int(time.time() * 10) % 10 == 0):
                print(f"No GPS - Speed: {spd:.2f} km/h ({speed_source})")

        target_timestamp_ms = int(time.time() * 1000)
        img_path = get_latest_image_for_timestamp(target_timestamp_ms)

        row = {
            'timestamp': target_timestamp_ms,
            'image_path': img_path or '',  # kept only in local CSV
            'acc_x': mpu[0], 'acc_y': mpu[1], 'acc_z': mpu[2],
            'gyro_x': mpu[3], 'gyro_y': mpu[4], 'gyro_z': mpu[5],
            'latitude': lat, 'longitude': lon,
            'speed': spd,
            'speed_limit': latest_speed_limit,
        }

        file_exists = os.path.isfile(CSV_FILENAME)
        with open(CSV_FILENAME, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)

        if (time.time() - last_fb_push) >= FIREBASE_PUSH_INTERVAL_S:
            try:
                if all(v is not None for v in mpu):
                    firebase_uploader.update_rider_mpu(
                        USER_ID,
                        mpu[0], mpu[1], mpu[2],
                        mpu[3], mpu[4], mpu[5],
                        target_timestamp_ms,
                    )
                warnings = firebase_uploader.build_speeding_warning(spd, latest_speed_limit)
                firebase_uploader.update_rider_speed(USER_ID, spd, latest_speed_limit, warnings)
            except Exception as e:
                print(f"Firebase push error: {e}")
            last_fb_push = time.time()

    # Cleanup
    for t in threads:
        t.join(timeout=0.5)
    if gps_serial:
        try:
            gps_serial.close()
        except Exception:
            pass
    print("Supervisor stopped.")


if __name__ == '__main__':
    main()
