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
USER_ID = "ocadXHESmIZ8TUHfzN2ZYKV51os2"
CONTROL_POLL_INTERVAL_S = 0.5

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

# Speed calculation buffers and state
accel_buffer = []  # Buffer to store 1 second of acceleration data (30 samples)
current_speed_ms = 0.0  # Current speed in m/s
speed_calculation_lock = threading.Lock()
gps_last_update_time = 0.0  # Track when GPS was last successfully updated
GPS_TIMEOUT_SECONDS = 5.0  # Consider GPS stale after 5 seconds without update

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
        # new_speed_ms = min(55.6, new_speed_ms)
        
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
        data = mpu_utils.get_mpu_data()
        with data_lock:
            latest_mpu = data
        
        # Add acceleration data to buffer for speed calculation
        if data and len(data) >= 1 and data[0] is not None:
            add_accel_to_buffer(data[0])  # Use acc_x for speed calculation
            
        time.sleep(0.005)

def gps_thread(gps_serial):
    # Simplified: no consecutive error counting; always fallback to accel-derived speed on failure
    global latest_gps, gps_last_update_time
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
                        latest_gps = gps_data  # (lat, lon, speed_kmh)
                        gps_last_update_time = time.time()
                    else:
                        # Partial data (lat, lon only) -> compute fallback speed from acceleration
                        accel_speed_ms = calculate_speed_from_accel()
                        accel_speed_kmh = accel_speed_ms * 3.6
                        latest_gps = (gps_data[0], gps_data[1], accel_speed_kmh)
                        gps_last_update_time = time.time()
                # if valid_gps_count % 10 == 1:
                #     lat, lon, speed = latest_gps
                #     print(f"GPS Update #{valid_gps_count}: Lat={lat:.6f}, Lon={lon:.6f}, Speed={speed:.2f} km/h")
            else:
                # Invalid reading: keep last lat/lon, compute speed from accelerometer
                with data_lock:
                    prev_lat, prev_lon, _prev_speed = latest_gps
                accel_speed_ms = calculate_speed_from_accel()
                accel_speed_kmh = accel_speed_ms * 3.6
                with data_lock:
                    latest_gps = (prev_lat, prev_lon, accel_speed_kmh)
                    gps_last_update_time = time.time()
                # if gps_read_count % 50 == 0:
                #     time_since_last_fix = time.time() - last_valid_gps_time if last_valid_gps_time > 0 else 0
                #     print(f"GPS Status: {gps_read_count} attempts, {valid_gps_count} valid. Last fix: {time_since_last_fix:.1f}s ago (ACCEL fallback {accel_speed_kmh:.2f} km/h)")
        except Exception as e:
            # On any exception: fallback speed using accelerometer; preserve last lat/lon
            print(f"GPS thread error (fallback to accel): {e}")
            with data_lock:
                prev_lat, prev_lon, _prev_speed = latest_gps
            accel_speed_ms = calculate_speed_from_accel()
            accel_speed_kmh = accel_speed_ms * 3.6
            with data_lock:
                latest_gps = (prev_lat, prev_lon, accel_speed_kmh)
                gps_last_update_time = time.time()
        time.sleep(0.2)

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

def wait_until_active(ride_id: str, poll_interval: float = 0.5):
    """Block in an inactive state until remote re-activates the ride or stop_event set.
    Periodically polls Firebase for the is_active flag.
    """
    global current_is_active, last_control_poll
    while not stop_event.is_set() and not current_is_active:
        try:
            is_active = firebase_uploader.get_control_flags_for_ride(USER_ID, ride_id)
            if is_active:
                current_is_active = True
                print("Ride re-activated. Resuming logging.")
                break
        except Exception:
            pass
        time.sleep(0.5)
        last_control_poll = time.time()

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

    # Determine ride id (auto-increment) and initialize ride-scoped control
    try:
        ride_id = firebase_uploader.get_next_ride_id(USER_ID)
        print(f"Starting ride id: {ride_id}")
    except Exception as e:
        print(f"Firebase ride init failed: {e}")
        ride_id = "0"

    # Wait for remote to set is_active True before starting
    wait_until_active(ride_id)

    # Prepare CSV
    csv_filename = CSV_FILENAME
    fieldnames = [
        'timestamp', 'image_path', 'acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z',
        'latitude', 'longitude', 'speed', 'speed_limit'
    ]
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

                lat, lon, spd = gps
                # """--------------------- Change this logic ---------------------"""
                # # Calculate final speed using our priority system
                # spd, speed_source = get_final_speed_kmh()
                # """-------------------------------------------------------------"""
                target_timestamp_ms = int(time.time() * 1000)
                img_path = get_latest_image_for_timestamp(target_timestamp_ms)

                row = {
                    'timestamp': target_timestamp_ms,
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
                        current_is_active = firebase_uploader.get_control_flags_for_ride(USER_ID, ride_id)
                    except Exception:
                        pass  # retain previous state on failure
                    last_control_poll = t_wall

                # If not active, skip sampling/pushing but keep polling
                if not current_is_active:
                    # Enter inactive waiting state (blocking until re-activated)
                    wait_until_active(ride_id)
                    # Reset timing anchor after idle to avoid large sleep adjustments
                    next_sample_time = time.perf_counter() + SAMPLE_INTERVAL
                    continue

                writer.writerow(row)
                # if int(row['timestamp']) % 5 == 0:
                #     f.flush()
                # if int(row['timestamp']) % 5 == 0:
                #     f.flush()

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
        finally:
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
