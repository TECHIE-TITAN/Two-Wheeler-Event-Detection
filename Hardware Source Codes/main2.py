import time
import csv
import os
import threading
import glob
import numpy as np
from collections import deque
from datetime import datetime
from queue import Queue, Empty
import mpu_utils  # type: ignore
import gps_utils  # type: ignore
import speed_limit_utils  # type: ignore
import firebase_uploader  # type: ignore
import shared_memory_bridge  # type: ignore

TARGET_HZ = 104
SAMPLE_INTERVAL = 1.0 / TARGET_HZ
OLA_MAPS_API_KEY = "50c25aHLICdWQ4JbXp2MZwgmliGxvqJ8os1MOYe3"
SPEED_LIMIT_REFRESH_S = 50.0 
FIREBASE_PUSH_INTERVAL_S = 7.0
USER_ID = "OYFNMBRHiPduTdplwnSIa2dxdwx1"
CONTROL_POLL_INTERVAL_S = 10.0
IMAGE_REFRESH_INTERVAL_S = 1.0  # Refresh image directory listing every 1 second
CSV_BATCH_SIZE = 10  # Write CSV in batches for better performance
PRINT_INTERVAL = 100  # Print every N samples (1 Hz at 100 Hz sampling)

IMAGE_DIR = "captured_images/"
CSV_FILENAME = "sensor_data.csv"

# Queues for async I/O
csv_write_queue = Queue(maxsize=2000)  # Buffer up to 2000 samples
print_queue = Queue(maxsize=100)  # For console output
control_poll_queue = Queue(maxsize=1)  # For control flag updates
# Note: Firebase push logic moved to Warning_Generate.py

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

# Image cache
image_files_cache = []
image_cache_lock = threading.Lock()
last_image_cache_update = 0.0

# Speed calculation state
last_accel_ms2 = 0.0  # Store latest acceleration in m/s^2
last_speed_calc_ts = None  # High-resolution time anchor (perf_counter)
current_speed_ms = 0.0  # Current speed in m/s
speed_calculation_lock = threading.Lock()
gps_last_update_time = 0.0  # Track when GPS was last successfully updated
GPS_TIMEOUT_SECONDS = 5.0  # Consider GPS stale after 5 seconds without update

# Calibrated parameters from calibration analysis (calibrate_accel_to_speed.py)
OPTIMAL_BIAS = 0.117588  # g - systematic accelerometer bias
DEADBAND_G = 0.02  # g - suppress noise below this threshold
G_TO_MS2 = 9.81  # m/s² - gravity constant for conversion

# Shared memory for warning system communication
shm_writer = None
batch_buffer = []  # Accumulate 104 points before writing to shared memory
batch_buffer_lock = threading.Lock()

def calculate_speed_from_accel():
    """Integrate x-axis acceleration to estimate forward speed (m/s).
    Uses calibrated bias correction and deadband filtering based on real-world data.
    
    Calibrated Formula (from calibrate_accel_to_speed.py):
    1. Remove systematic bias: accel_corrected = acc_x - 0.117588 g
    2. Apply deadband: if |accel_corrected| < 0.02g, set to 0
    3. Integrate: speed += accel_corrected * 9.81 * dt
    4. Clamp to realistic range
    
    Returns current speed estimate in m/s.
    """
    global current_speed_ms, last_accel_ms2, last_speed_calc_ts, last_accel_decimals
    with speed_calculation_lock:
        now = time.perf_counter()
        # Initialize anchor on first call
        if last_speed_calc_ts is None:
            last_speed_calc_ts = now
            return current_speed_ms

        dt = max(0.0, now - last_speed_calc_ts)
        last_speed_calc_ts = now  # Update anchor

        # Convert m/s² back to g for bias correction
        accel_g = last_accel_ms2 / G_TO_MS2
        
        # Apply calibrated bias correction
        accel_corrected_g = accel_g - OPTIMAL_BIAS
        
        # Apply deadband to suppress noise (in g units)
        if abs(accel_corrected_g) < DEADBAND_G:
            accel_corrected_g = 0.0
        
        # Convert back to m/s² for integration
        accel_corrected_ms2 = accel_corrected_g * G_TO_MS2

        # Integrate acceleration (v = ∫a dt)
        current_speed_ms += accel_corrected_ms2 * dt

        # Clamp to non-negative and suppress tiny drift
        # if current_speed_ms < 0.0:
        #     current_speed_ms = 0.0
        # elif abs(accel_corrected_ms2) < 0.05 and current_speed_ms < 0.05:
        #     # When nearly no accel and speed tiny, snap to zero
        #     current_speed_ms = 0.0

        # Optional hard cap to reject outliers (~300 km/h)
        if current_speed_ms > 83.3333:
            current_speed_ms = 83.3333

        return current_speed_ms

def mpu_thread():
    global latest_mpu, last_accel_ms2, last_accel_decimals
    while not stop_event.is_set():
        data = mpu_utils.get_mpu_data()
        with data_lock:
            latest_mpu = data
        # Update latest acceleration and precision directly (no buffer)
        updated_accel = False
        if data and len(data) >= 1 and data[0] is not None:
            with speed_calculation_lock:
                acc_x = data[0]
                # Convert from g to m/s^2 if MPU returns g-units
                last_accel_ms2 = acc_x * 9.81
                raw_str = f"{acc_x:.10f}".rstrip('0').rstrip('.')
                if '.' in raw_str:
                    decs = len(raw_str.split('.')[1])
                    if decs > 0:
                        last_accel_decimals = min(decs, 10)
            updated_accel = True

        # Integrate at sensor rate for smoother fallback speed
        if updated_accel:
            calculate_speed_from_accel()

        time.sleep(0.001)

def gps_thread(gps_serial):
    """GPS thread - reads GPS data and handles speed fallback before updating global variable.
    Uses calibrated accelerometer integration when GPS speed is unavailable, invalid, or zero.
    """
    global latest_gps, gps_last_update_time, latest_speed_source
    
    print("GPS thread started...")
    
    # Number of samples for averaging fallback speed
    FALLBACK_SAMPLES = 104  # One batch worth of samples

    while not stop_event.is_set():
        try:
            gps_data = gps_utils.get_gps_data(gps_serial)
            
            if gps_data and gps_data != (None, None, None):
                lat, lon, gps_speed = gps_data
                
                # Check if GPS speed is valid (must be non-zero and within realistic range)
                if gps_speed is not None and 0.5 < gps_speed <= 300.0:
                    # Valid GPS speed - use it directly and anchor integrator
                    final_speed = gps_speed
                    speed_src = "GPS"
                    try:
                        with speed_calculation_lock:
                            # Anchor integrator to GPS speed (m/s) and reset time anchor
                            current_speed_ms = max(0.0, min(83.3333, gps_speed / 3.6))
                            last_speed_calc_ts = time.perf_counter()
                    except Exception:
                        pass
                elif gps_speed is not None and abs(gps_speed) < 0.5:
                    # GPS reports zero or near-zero speed - use fallback calculation
                    # This handles cases where GPS is available but reports 0 (stationary or GPS error)
                    speed_samples = []
                    for _ in range(FALLBACK_SAMPLES):
                        accel_speed_ms = calculate_speed_from_accel()
                        speed_samples.append(accel_speed_ms)
                        time.sleep(1.0 / TARGET_HZ)  # Sample at target rate
                    
                    # Calculate average speed and convert to km/h
                    avg_speed_ms = sum(speed_samples) / len(speed_samples)
                    final_speed = avg_speed_ms * 3.6
                    speed_src = "ACCEL"
                else:
                    # GPS speed unavailable or invalid - calculate average from multiple samples
                    speed_samples = []
                    for _ in range(FALLBACK_SAMPLES):
                        accel_speed_ms = calculate_speed_from_accel()
                        speed_samples.append(accel_speed_ms)
                        time.sleep(1.0 / TARGET_HZ)  # Sample at target rate
                    
                    # Calculate average speed and convert to km/h
                    avg_speed_ms = sum(speed_samples) / len(speed_samples)
                    final_speed = avg_speed_ms * 3.6
                    speed_src = "ACCEL"
                
                # Update global with final speed (either GPS or fallback)
                with data_lock:
                    latest_gps = (lat, lon, final_speed)
                    gps_last_update_time = time.time()
                    latest_speed_source = speed_src
            else:
                # GPS read failed completely - calculate average from multiple samples
                speed_samples = []
                for _ in range(FALLBACK_SAMPLES):
                    accel_speed_ms = calculate_speed_from_accel()
                    speed_samples.append(accel_speed_ms)
                    time.sleep(1.0 / TARGET_HZ)  # Sample at target rate
                
                # Calculate average speed and convert to km/h
                avg_speed_ms = sum(speed_samples) / len(speed_samples)
                final_speed = avg_speed_ms * 3.6
                
                with data_lock:
                    latest_gps = (None, None, final_speed)
                    gps_last_update_time = time.time()
                    latest_speed_source = "ACCEL"
                    
        except Exception as e:
            print(f"GPS thread error: {e}")
            # On exception - calculate average from multiple samples
            speed_samples = []
            for _ in range(FALLBACK_SAMPLES):
                accel_speed_ms = calculate_speed_from_accel()
                speed_samples.append(accel_speed_ms)
                time.sleep(1.0 / TARGET_HZ)  # Sample at target rate
            
            # Calculate average speed and convert to km/h
            avg_speed_ms = sum(speed_samples) / len(speed_samples)
            final_speed = avg_speed_ms * 3.6
            
            with data_lock:
                latest_gps = (None, None, final_speed)
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

def update_image_cache():
    """Periodically update the cached image file list."""
    global image_files_cache, last_image_cache_update
    while not stop_event.is_set():
        try:
            files = glob.glob(os.path.join(IMAGE_DIR, "frame_*.jpg"))
            with image_cache_lock:
                image_files_cache = files
                last_image_cache_update = time.time()
        except Exception as e:
            # print(f"Image cache update error: {e}")
            pass
        time.sleep(IMAGE_REFRESH_INTERVAL_S)

def get_latest_image_for_timestamp(target_timestamp_ms):
    """Fast image lookup using cached file list."""
    with image_cache_lock:
        image_files = image_files_cache.copy()
    
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

def csv_writer_thread(csv_filename, fieldnames):
    """Background thread to write CSV rows from queue with batching and formatting."""
    file_exists = os.path.isfile(csv_filename)
    
    with open(csv_filename, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        
        batch = []
        while not stop_event.is_set():
            try:
                # row is now a tuple: (timestamp_ms, img_path, mpu_tuple, lat, lon, spd, speed_limit, speed_source)
                row_data = csv_write_queue.get(timeout=0.1)
                
                # Unpack tuple
                timestamp_ms, img_path, mpu, lat, lon, spd, speed_limit, speed_source = row_data
                
                # Format timestamp here (not in main loop)
                readable_timestamp = datetime.fromtimestamp(timestamp_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                
                # Build dict for CSV
                row = {
                    'timestamp': readable_timestamp,
                    'image_path': img_path or '',
                    'acc_x': mpu[0], 'acc_y': mpu[1], 'acc_z': mpu[2],
                    'gyro_x': mpu[3], 'gyro_y': mpu[4], 'gyro_z': mpu[5],
                    'latitude': lat, 'longitude': lon,
                    'speed': spd,
                    'speed_limit': speed_limit
                }
                
                batch.append(row)
                
                # Write in batches for better I/O performance
                if len(batch) >= CSV_BATCH_SIZE:
                    writer.writerows(batch)
                    f.flush()
                    batch.clear()
                    
            except Empty:
                # Flush any remaining batch when queue is empty
                if batch:
                    writer.writerows(batch)
                    f.flush()
                    batch.clear()
                continue
            except Exception as e:
                print(f"CSV writer error: {e}")
        
        # Final flush on exit
        if batch:
            writer.writerows(batch)
            f.flush()

def print_worker_thread():
    """Background thread to handle console output."""
    while not stop_event.is_set():
        try:
            msg = print_queue.get(timeout=0.1)
            print(msg)
        except Empty:
            continue

def control_poll_thread():
    """Background thread to periodically poll control flags."""
    global current_is_active, last_control_poll
    
    while not stop_event.is_set():
        time.sleep(CONTROL_POLL_INTERVAL_S)
        
        # Get current ride_id from queue (non-blocking)
        ride_id = None
        try:
            ride_id = control_poll_queue.get_nowait()
            # Put it back for next iteration
            control_poll_queue.put_nowait(ride_id)
        except Empty:
            continue
        
        if ride_id:
            try:
                is_active, _calc = firebase_uploader.get_control_flags_for_ride(USER_ID, ride_id)
                current_is_active = is_active
                last_control_poll = time.time()
            except Exception as e:
                pass  # Retain previous state on failure

def wait_until_active(ride_id: str | None = None, poll_interval: float = 0.5):
    """Obtain (if needed) the next ride_id and block until remote activates it.
    If ride_id is None, fetch from Firebase (get_next_ride_id) and increment for next time.
    Returns the ride_id used. Sets global current_is_active to True once activated or until stop_event set.
    """
    global current_is_active, last_control_poll
    print("--------------------------------------------")
    print("Waiting for ride to be activated remotely...")
    print("--------------------------------------------")
    while not stop_event.is_set() and not current_is_active:
        # Acquire ride id if not supplied
        try:
            ride_id = firebase_uploader.get_next_ride_id(USER_ID)
            print("--------------------------------------------")
            print(f"Starting ride id: {ride_id}")
            print("--------------------------------------------")
        except Exception as e:
            print(f"Firebase ride init failed: {e}")
            ride_id = "0"

        if current_is_active:
            return ride_id
        
        try:
            is_active, _calc = firebase_uploader.get_control_flags_for_ride(USER_ID, ride_id)
            if is_active:
                current_is_active = True
                print("--------------------------------------------")
                print("Ride activated. Beginning logging.")
                print("--------------------------------------------")
                break
        except Exception:
            pass
        time.sleep(poll_interval)
        last_control_poll = time.time()
    return ride_id

def main():
    global latest_speed_limit, last_speed_limit_fetch, current_is_active, last_control_poll, shm_writer

    # Initialize shared memory writer for warning system
    try:
        shm_writer = shared_memory_bridge.SensorDataWriter(create_new=True)
        print("Shared memory bridge initialized for warning system")
    except Exception as e:
        print(f"Shared memory init failed: {e}")
        print("Warning system will not receive data")
        shm_writer = None

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
    
    # Start utility threads
    threads.append(threading.Thread(target=speed_limit_thread, daemon=True))
    threads.append(threading.Thread(target=update_image_cache, daemon=True))
    threads.append(threading.Thread(target=print_worker_thread, daemon=True))
    threads.append(threading.Thread(target=control_poll_thread, daemon=True))
    # Note: Firebase worker thread removed - now handled by Warning_Generate.py
    
    for t in threads:
        t.start()
    print(f"Started {len(threads)} threads (sensors + workers).")

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
        
        # Start CSV writer thread for this ride
        csv_thread = threading.Thread(target=csv_writer_thread, args=(csv_filename, fieldnames), daemon=True)
        csv_thread.start()
        
        # Put ride_id in control poll queue
        try:
            control_poll_queue.put_nowait(ride_id)
        except:
            pass

        print("--------------------------------------------")
        print(f"Logging at {TARGET_HZ} Hz to {csv_filename}.")
        print("--------------------------------------------")
        next_sample_time = time.perf_counter()
        last_fb_push = 0.0
        sample_count = 0
        
        # Reset batch buffer for this ride
        with batch_buffer_lock:
            batch_buffer.clear()
        
        # Set ride active flag in shared memory
        if shm_writer is not None:
            ride_id_num = int(ride_id) if ride_id.isdigit() else 0
            shm_writer.set_ride_active(ride_id_num)
            print("--------------------------------------------")
            print(f"Ride {ride_id} activated in shared memory")
            print("--------------------------------------------")
            time.sleep(0.1)  # Give Warning_Generate.py time to detect

        # Reset speed integrator at the start of each ride
        with speed_calculation_lock:
            current_speed_ms = 0.0
            last_speed_calc_ts = None
        
        # Pre-allocate variables to avoid lookups
        sample_interval = SAMPLE_INTERVAL
        fb_interval = FIREBASE_PUSH_INTERVAL_S
        print_interval = PRINT_INTERVAL

        try:
            while not stop_event.is_set():                
                # Sleep until next sample time (tight timing loop)
                now = time.perf_counter()
                sleep_time = next_sample_time - now
                if sleep_time > 0.0001:  # Only sleep if > 0.1ms
                    time.sleep(sleep_time)
                
                # Update next sample time
                next_sample_time += sample_interval

                # CRITICAL SECTION: Single atomic read - minimize lock time
                with data_lock:
                    mpu = latest_mpu  # Tuple copy (fast)
                    lat, lon, spd = latest_gps  # Unpack directly (speed already handled by GPS thread)
                    speed_limit = latest_speed_limit
                    speed_source = latest_speed_source  # Read speed source set by GPS thread

                # Get timestamp
                timestamp_ms = int(time.time() * 1000)
                t_wall = time.time()  # For Firebase timing
                
                # Image path lookup - do in background or skip for performance
                # For 100 Hz, we skip this in main loop and handle in CSV writer if needed
                img_path = None  # Set to None for max speed; CSV writer can lookup if needed

                # Pack data as tuple (much faster than dict construction)
                row_tuple = (timestamp_ms, img_path, mpu, lat, lon, spd, speed_limit, speed_source)

                # Check if ride is still active (control poll thread updates this)
                if not current_is_active:
                    # Ride has ended - wait for queue to drain, then upload
                    print("--------------------------------------------")
                    print(f"Ride {ride_id} ended. Flushing data...")
                    print("--------------------------------------------")
                    
                    # Set ride inactive flag in shared memory
                    if shm_writer is not None:
                        shm_writer.set_ride_inactive()
                        print("--------------------------------------------")
                        print("Ride deactivated in shared memory")
                        print("--------------------------------------------")
                    
                    # Wait for CSV queue to empty (with timeout)
                    timeout = time.time() + 5.0
                    while not csv_write_queue.empty() and time.time() < timeout:
                        time.sleep(0.1)
                    
                    # Wait a bit for Warning_Generate.py to finish writing its CSV
                    time.sleep(2.0)
                    
                    try:
                        # Upload the CSV file to Firebase
                        upload_success = firebase_uploader.upload_raw_data_to_firebase(
                            USER_ID, ride_id, f'warnings_{ride_id}.csv'
                        )
                        if upload_success:
                            print("--------------------------------------------")
                            print(f"Raw data successfully uploaded for ride {ride_id}")
                            print("--------------------------------------------")
                        else:
                            print(f"Failed to upload raw data for ride {ride_id}")
                    except Exception as e:
                        print(f"Error uploading raw data: {e}")
                    
                    # Break out of the inner loop to start new ride
                    break

                # Queue CSV write (non-blocking, fast)
                try:
                    csv_write_queue.put_nowait(row_tuple)
                except:
                    pass  # Queue full, skip this sample

                # Add to batch buffer for shared memory (warning system)
                if shm_writer is not None:
                    with batch_buffer_lock:
                        # Store point as tuple: (timestamp, acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, lat, lon, speed, speed_limit)
                        batch_point = (
                            timestamp_ms / 1000.0,  # Convert to seconds for consistency
                            mpu[0], mpu[1], mpu[2],  # accelerations
                            mpu[3], mpu[4], mpu[5],  # gyroscope
                            lat if lat is not None else 0.0,
                            lon if lon is not None else 0.0,
                            spd,
                            speed_limit if speed_limit is not None else 0.0
                        )
                        batch_buffer.append(batch_point)
                        
                        # When we have 104 points, write to shared memory
                        if len(batch_buffer) >= 104:
                            success = shm_writer.write_batch(batch_buffer[:104])
                            if success:
                                # Keep only the overflow points (should be 0 or very few)
                                batch_buffer[:] = batch_buffer[104:]
                            else:
                                # On write failure, clear buffer to avoid memory buildup
                                batch_buffer.clear()

                # Increment sample counter
                sample_count += 1
                
                # Queue console output much less frequently (1 Hz at 100 Hz sampling)
                # if sample_count % print_interval == 0:
                #     readable_ts = datetime.fromtimestamp(timestamp_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                #     msg = (f"[{sample_count}] Time={readable_ts} Acc=({mpu[0]:.4f},{mpu[1]:.4f},{mpu[2]:.4f}) "
                #            f"Speed={spd:.2f} km/h Src={speed_source}")
                #     try:
                #         print_queue.put_nowait(msg)
                #     except:
                #         pass
                
                # Note: Firebase push logic moved to Warning_Generate.py

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
    
    # Cleanup shared memory
    if shm_writer:
        try:
            shm_writer.cleanup()
            print("Shared memory cleaned up")
        except Exception as e:
            print(f"Shared memory cleanup warning: {e}")
    
    print("Log complete.")
            
if __name__ == '__main__':
    main()