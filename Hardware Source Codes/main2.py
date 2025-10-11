import time
import csv
import os
import threading
import glob
from collections import deque  # Added for fixed-size acceleration buffer
from datetime import datetime  # Added for readable timestamp formatting
import mpu_utils  # type: ignore
import gps_utils  # type: ignore
import speed_limit_utils  # type: ignore
import firebase_uploader  # type: ignore

TARGET_HZ = 100
SAMPLE_INTERVAL = 1.0 / TARGET_HZ
OLA_MAPS_API_KEY = "50c25aHLICdWQ4JbXp2MZwgmliGxvqJ8os1MOYe3"
SPEED_LIMIT_REFRESH_S = 50.0 
FIREBASE_PUSH_INTERVAL_S = 7.0
USER_ID = "OYFNMBRHiPduTdplwnSIa2dxdwx1"
CONTROL_POLL_INTERVAL_S = 10.0

IMAGE_DIR = "captured_images/"
CSV_FILENAME = "sensor_data.csv"

data_lock = threading.Lock()
latest_mpu = (None, None, None, None, None, None)
latest_gps = (None, None, None)
latest_speed_limit = None
last_speed_limit_fetch = 0.0
stop_event = threading.Event()
last_control_poll = 0.0
current_is_active = False  # Only remaining control flag
latest_speed_source = "UNKNOWN"  # Track whether speed from GPS or ACCEL fallback
last_accel_decimals = 3  # Track decimal precision of last acceleration reading

# Speed calculation state
last_accel_ms2 = 0.0  # Store latest acceleration in m/s^2
last_speed_calc_ts = None  # High-resolution time anchor (perf_counter)
current_speed_ms = 0.0  # Current speed in m/s
speed_calculation_lock = threading.Lock()
gps_last_update_time = 0.0  # Track when GPS was last successfully updated
GPS_TIMEOUT_SECONDS = 5.0  # Consider GPS stale after 5 seconds without update

def calculate_speed_from_accel():
    """Update and return speed using latest acceleration and time since last calculation.
    Note: This function no longer updates last_speed_calc_ts. The caller should update it.
    """
    global current_speed_ms, last_accel_ms2, last_speed_calc_ts, last_accel_decimals
    with speed_calculation_lock:
        # If we don't have a previous timestamp, cannot integrate yet
        if last_speed_calc_ts is None:
            return current_speed_ms
        now = time.perf_counter()
        dt = max(0.0, now - last_speed_calc_ts)
        # Deadband to suppress noise
        accel = last_accel_ms2
        if abs(accel) < 0.2:
            accel = 0.0
        current_speed_ms += accel * dt
        if current_speed_ms < 0.0:
            current_speed_ms = 0.0
        current_speed_ms = round(current_speed_ms, last_accel_decimals)
        return current_speed_ms

def get_final_speed_kmh():
    """
    Get final speed in km/h using priority system:
    1. GPS speed (if available and fresh)
    2. Accelerometer-based calculation (fallback)
    """
    global latest_gps, current_speed_ms, gps_last_update_time, last_speed_calc_ts, latest_speed_source

    current_time_wall = time.time()
    current_time_perf = time.perf_counter()

    with data_lock:
        gps_data = latest_gps
        last_gps_update = gps_last_update_time

    # Check if GPS data is stale
    gps_is_stale = (current_time_wall - last_gps_update) > GPS_TIMEOUT_SECONDS

    # Extract GPS speed (assuming it's in km/h)
    gps_speed_kmh = None
    if gps_data and len(gps_data) >= 3 and gps_data[2] is not None and not gps_is_stale:
        gps_speed_kmh = gps_data[2]
        # Validate GPS speed (reasonable range)
        if gps_speed_kmh < 0 or gps_speed_kmh > 300:
            gps_speed_kmh = None

    if gps_speed_kmh is not None:
        # Use GPS speed and sync our accelerometer-based speed to it
        with speed_calculation_lock:
            current_speed_ms = gps_speed_kmh / 3.6
            last_speed_calc_ts = current_time_perf  # refresh anchor even with GPS
        latest_speed_source = "GPS"
        return gps_speed_kmh, "GPS"
    else:
        # Use accelerometer-based speed calculation
        accel_speed_ms = calculate_speed_from_accel()
        accel_speed_kmh = accel_speed_ms * 3.6
        # Refresh time anchor after using fallback based on perf counter
        with speed_calculation_lock:
            last_speed_calc_ts = current_time_perf
        latest_speed_source = "ACCEL (GPS_STALE)" if gps_is_stale and gps_data != (None, None, None) else "ACCEL"
        if gps_is_stale and gps_data != (None, None, None):
            return accel_speed_kmh, "ACCEL (GPS_STALE)"
        else:
            return accel_speed_kmh, "ACCEL"

def mpu_thread():
    global latest_mpu, last_accel_ms2, last_accel_decimals
    while not stop_event.is_set():
        data = mpu_utils.get_mpu_data()
        with data_lock:
            latest_mpu = data
        # Update latest acceleration and precision directly (no buffer)
        if data and len(data) >= 1 and data[0] is not None:
            with speed_calculation_lock:
                acc_x = data[0]
                last_accel_ms2 = acc_x * 9.81
                raw_str = f"{acc_x:.10f}".rstrip('0').rstrip('.')
                if '.' in raw_str:
                    decs = len(raw_str.split('.')[1])
                    if decs > 0:
                        last_accel_decimals = min(decs, 10)
        time.sleep(0.001)

def gps_thread(gps_serial):
    # Simplified: no consecutive error counting; always fallback to accel-derived speed on failure
    global latest_gps, gps_last_update_time, latest_speed_source, last_accel_decimals
    last_valid_gps_time = 0
    gps_read_count = 0
    valid_gps_count = 0

    print("GPS thread started...")

    while not stop_event.is_set():
        try:
            gps_data = gps_utils.get_gps_data(gps_serial)
            gps_read_count += 1

            if gps_data and gps_data != (None, None, None):
                valid_gps_count += 1
                last_valid_gps_time = time.time()
                with data_lock:
                    if len(gps_data) == 3:
                        # Round GPS speed to match acceleration decimals if present
                        spd_val = gps_data[2]
                        if spd_val is not None:
                            spd_val = round(spd_val, last_accel_decimals)
                        latest_gps = (gps_data[0], gps_data[1], spd_val)
                        gps_last_update_time = time.time()
                        latest_speed_source = "GPS"
                    else:
                        # Partial data (lat, lon only) -> compute fallback speed from acceleration
                        accel_speed_ms = calculate_speed_from_accel()
                        # Caller updates time anchor after using fallback
                        with speed_calculation_lock:
                            last_speed_calc_ts = time.perf_counter()
                        accel_speed_kmh = accel_speed_ms * 3.6
                        accel_speed_kmh = round(accel_speed_kmh, last_accel_decimals)
                        latest_gps = (gps_data[0], gps_data[1], accel_speed_kmh)
                        gps_last_update_time = time.time()
                        latest_speed_source = "ACCEL"
            else:
                # Invalid reading: keep last lat/lon, compute speed from accelerometer
                with data_lock:
                    prev_lat, prev_lon, _prev_speed = latest_gps
                accel_speed_ms = calculate_speed_from_accel()
                # Caller updates time anchor after using fallback
                with speed_calculation_lock:
                    last_speed_calc_ts = time.perf_counter()
                accel_speed_kmh = accel_speed_ms * 3.6
                accel_speed_kmh = round(accel_speed_kmh, last_accel_decimals)
                with data_lock:
                    latest_gps = (prev_lat, prev_lon, accel_speed_kmh)
                    gps_last_update_time = time.time()
                    latest_speed_source = "ACCEL"
        except Exception as e:
            # On any exception: fallback speed using accelerometer; preserve last lat/lon
            print(f"GPS thread error (fallback to accel): {e}")
            with data_lock:
                prev_lat, prev_lon, _prev_speed = latest_gps
            accel_speed_ms = calculate_speed_from_accel()
            # Caller updates time anchor after using fallback
            with speed_calculation_lock:
                last_speed_calc_ts = time.perf_counter()
            accel_speed_kmh = accel_speed_ms * 3.6
            accel_speed_kmh = round(accel_speed_kmh, last_accel_decimals)
            with data_lock:
                latest_gps = (prev_lat, prev_lon, accel_speed_kmh)
                gps_last_update_time = time.time()
                latest_speed_source = "ACCEL"
        time.sleep(1.0)

    print("GPS thread stopped.")

def speed_limit_thread():
    """Background thread to periodically fetch speed limit using latest GPS coords.
    Respects SPEED_LIMIT_REFRESH_S interval. Safe to run even without GPS (it will idle)."""
    global latest_speed_limit, last_speed_limit_fetch
    while not stop_event.is_set():
        try:
            with data_lock:
                gps = latest_gps
            lat, lon, _ = gps
            if lat is not None and lon is not None:
                now = time.time()
                if (latest_speed_limit is None) or (now - last_speed_limit_fetch >= SPEED_LIMIT_REFRESH_S):
                    sl = speed_limit_utils.get_speed_limit(lat, lon, OLA_MAPS_API_KEY)
                    with data_lock:
                        latest_speed_limit = sl
                        last_speed_limit_fetch = now
        except Exception as e:
            # Silent or minimal logging to avoid spamming
            print(f"Speed limit thread error: {e}")
        # Sleep a short amount; main gating is interval check above
        time.sleep(0.2)

def get_latest_image_for_timestamp(target_timestamp_ms):
    # List all image files in IMAGE_DIR
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

def wait_until_active(ride_id: str | None = None, poll_interval: float = 0.5):
    """Obtain (if needed) the next ride_id and block until remote activates it.
    If ride_id is None, fetch from Firebase (get_next_ride_id) and increment for next time.
    Returns the ride_id used. Sets global current_is_active to True once activated or until stop_event set.
    """
    global current_is_active, last_control_poll

    print("Waiting for ride to be activated remotely...")
    while not stop_event.is_set() and not current_is_active:
        # Acquire ride id if not supplied
        try:
            ride_id = firebase_uploader.get_next_ride_id(USER_ID)
            print(f"Starting ride id: {ride_id}")
        except Exception as e:
            print(f"Firebase ride init failed: {e}")
            ride_id = "0"

        if current_is_active:
            return ride_id
        
        try:
            is_active, _calc = firebase_uploader.get_control_flags_for_ride(USER_ID, ride_id)
            if is_active:
                current_is_active = True
                print("Ride activated. Beginning logging.")
                break
        except Exception:
            pass
        time.sleep(poll_interval)
        last_control_poll = time.time()
    return ride_id

def main():
    global latest_speed_limit, last_speed_limit_fetch, current_is_active, last_control_poll

    # Initialize and Authenticate Firebase
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

    # Start sensor threads
    threads = [
        threading.Thread(target=mpu_thread, daemon=True)
    ]
    
    # Only start GPS thread if GPS is available
    if gps_serial:
        threads.append(threading.Thread(target=gps_thread, args=(gps_serial,), daemon=True))
    else:
        print("Warning: GPS thread not started due to initialization failure")
    
    # Start speed limit fetcher thread always (it self-idles without GPS)
    threads.append(threading.Thread(target=speed_limit_thread, daemon=True))
    
    for t in threads:
        t.start()
    print(f"Started {len(threads)} sensor threads.")

    # Main ride loop - handles multiple rides
    fieldnames = [
        'timestamp', 'image_path', 'acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z',
        'latitude', 'longitude', 'speed', 'speed_limit'
    ]
    
    while not stop_event.is_set():
        # Wait for remote to set is_active True before starting (also acquires ride_id)
        ride_id = wait_until_active()

        # Prepare CSV with ride_id in filename
        csv_filename = f"rawdata_{ride_id}.csv"
        file_exists = os.path.isfile(csv_filename)
        
        with open(csv_filename, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()

            print(f"Logging at {TARGET_HZ} Hz to {csv_filename}. Press Ctrl+C to stop.")
            next_sample_time = time.perf_counter()
            last_fb_push = 0.0

            try:
                while not stop_event.is_set():                
                    now = time.perf_counter()
                    # To sleep through a cycle if 30 iterations finish early
                    if now < next_sample_time:
                        time.sleep(next_sample_time - now)
                    next_sample_time += SAMPLE_INTERVAL

                    # Acquire latest sensor & speed limit snapshot atomically
                    with data_lock:
                        mpu = latest_mpu
                        gps = latest_gps
                        speed_limit = latest_speed_limit
                        # speed_source will be determined by get_final_speed_kmh below

                    # Compute speed each cycle (uses GPS if fresh, else fallback via accel)
                    spd, speed_source = get_final_speed_kmh()
                    with data_lock:
                        lat, lon, _ = latest_gps

                    target_timestamp_ms = int(time.time() * 1000)
                    img_path = get_latest_image_for_timestamp(target_timestamp_ms)
                    readable_timestamp = datetime.fromtimestamp(target_timestamp_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]

                    row = {
                        'timestamp': readable_timestamp,
                        'image_path': img_path or '',
                        'acc_x': mpu[0], 'acc_y': mpu[1], 'acc_z': mpu[2],
                        'gyro_x': mpu[3], 'gyro_y': mpu[4], 'gyro_z': mpu[5],
                        'latitude': lat, 'longitude': lon,
                        'speed': spd,
                        'speed_limit': speed_limit
                    }

                    # Poll only is_active flag at CONTROL_POLL_INTERVAL_S
                    t_wall = time.time()
                    if (t_wall - last_control_poll) >= CONTROL_POLL_INTERVAL_S:
                        try:
                            is_active, _calc = firebase_uploader.get_control_flags_for_ride(USER_ID, ride_id)
                            current_is_active = is_active
                        except Exception:
                            pass  # retain previous state on failure
                        last_control_poll = t_wall

                    # If not active, skip sampling/pushing but keep polling
                    if not current_is_active:
                        # Ride has ended - flush CSV and upload to Firebase
                        print(f"\nRide {ride_id} ended. Uploading raw data to Firebase...")
                        f.flush()  # Ensure all data is written to file
                        
                        try:
                            # Upload the CSV file to Firebase
                            upload_success = firebase_uploader.upload_raw_data_to_firebase(
                                USER_ID, ride_id, csv_filename
                            )
                            if upload_success:
                                print(f"Raw data successfully uploaded for ride {ride_id}")
                            else:
                                print(f"Failed to upload raw data for ride {ride_id}")
                        except Exception as e:
                            print(f"Error uploading raw data: {e}")
                        
                        # Break out of the inner loop to close file and start new ride
                        break

                    writer.writerow(row)
                    # Choose precision: more decimals for fallback ACCEL speed
                    if speed_source == "ACCEL":
                        speed_str = f"{row['speed']:.{last_accel_decimals}f}"
                    else:
                        speed_str = f"{row['speed']:.{last_accel_decimals}f}"
                    print(f"Logged: Time={row['timestamp']} Acc=({row['acc_x']},{row['acc_y']},{row['acc_z']}) Gyro=({row['gyro_x']},{row['gyro_y']},{row['gyro_z']}) "
                          f"Lat={row['latitude']} Lon={row['longitude']} Speed={speed_str} km/h "
                          f"SpeedLimit={row['speed_limit']} Src={speed_source} Image={os.path.basename(row['image_path']) if row['image_path'] else 'None'}")

                    if (time.time() - last_fb_push) >= FIREBASE_PUSH_INTERVAL_S:
                        try:
                            # Push latest MPU data if available
                            if all(v is not None for v in mpu):
                                firebase_uploader.update_rider_mpu(
                                    USER_ID,
                                    mpu[0], mpu[1], mpu[2],
                                    mpu[3], mpu[4], mpu[5],
                                    target_timestamp_ms
                                )
                            warnings = firebase_uploader.build_speeding_warning(spd, speed_limit)
                            firebase_uploader.update_rider_speed(USER_ID, spd, speed_limit, warnings)
                        except Exception as e:
                            print(f"Firebase push error: {e}")
                        last_fb_push = time.time()

            except KeyboardInterrupt:
                print("\nStopping logging...")
                break  # Break out of the ride loop
    
    # Cleanup on exit
    stop_event.set()
    for t in threads:
        t.join(timeout=0.5)
    if gps_serial:
        try:
            gps_serial.close()
        except Exception:
            pass
    print("Log complete.")
            
if __name__ == '__main__':
    main()
