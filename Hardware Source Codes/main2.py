import time
import csv
import os
import threading
import glob
from collections import deque
from datetime import datetime
from queue import Queue, Empty
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
IMAGE_REFRESH_INTERVAL_S = 1.0  # Refresh image directory listing every 1 second
CSV_BATCH_SIZE = 10  # Write CSV in batches for better performance
PRINT_INTERVAL = 100  # Print every N samples (1 Hz at 100 Hz sampling)

IMAGE_DIR = "captured_images/"
CSV_FILENAME = "sensor_data.csv"

# Queues for async I/O
csv_write_queue = Queue(maxsize=2000)  # Buffer up to 2000 samples
firebase_push_queue = Queue(maxsize=100)
print_queue = Queue(maxsize=100)  # For console output
control_poll_queue = Queue(maxsize=1)  # For control flag updates

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
            print(f"Image cache update error: {e}")
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

def firebase_worker_thread():
    """Background thread to handle Firebase pushes."""
    while not stop_event.is_set():
        try:
            task = firebase_push_queue.get(timeout=0.1)
            if task['type'] == 'mpu':
                firebase_uploader.update_rider_mpu(
                    task['user_id'], task['ax'], task['ay'], task['az'],
                    task['gx'], task['gy'], task['gz'], task['ts']
                )
            elif task['type'] == 'speed':
                firebase_uploader.update_rider_speed(
                    task['user_id'], task['speed'], task['limit'], task['warnings']
                )
        except Empty:
            continue
        except Exception as e:
            print(f"Firebase worker error: {e}")

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
    
    # Start utility threads
    threads.append(threading.Thread(target=speed_limit_thread, daemon=True))
    threads.append(threading.Thread(target=update_image_cache, daemon=True))
    threads.append(threading.Thread(target=print_worker_thread, daemon=True))
    threads.append(threading.Thread(target=firebase_worker_thread, daemon=True))
    threads.append(threading.Thread(target=control_poll_thread, daemon=True))
    
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

        print(f"Logging at {TARGET_HZ} Hz to {csv_filename}. Press Ctrl+C to stop.")
        next_sample_time = time.perf_counter()
        last_fb_push = 0.0
        sample_count = 0
        
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
                    lat, lon, gps_speed = latest_gps  # Unpack directly
                    speed_limit = latest_speed_limit

                # Compute speed inline (avoid function call overhead)
                # Use GPS if available, otherwise use accelerometer
                t_wall = time.time()
                gps_is_stale = (t_wall - gps_last_update_time) > GPS_TIMEOUT_SECONDS
                
                if gps_speed is not None and not gps_is_stale and 0 <= gps_speed <= 300:
                    spd = gps_speed
                    speed_source = "GPS"
                else:
                    # Accelerometer fallback (simplified inline)
                    with speed_calculation_lock:
                        if last_speed_calc_ts is not None:
                            dt = time.perf_counter() - last_speed_calc_ts
                            accel = last_accel_ms2 if abs(last_accel_ms2) >= 0.2 else 0.0
                            current_speed_ms_local = max(0.0, current_speed_ms + accel * dt)
                            current_speed_ms = current_speed_ms_local
                        last_speed_calc_ts = time.perf_counter()
                        spd = current_speed_ms * 3.6
                    speed_source = "ACCEL"

                # Get timestamp (raw integer - formatting done in CSV writer)
                timestamp_ms = int(t_wall * 1000)
                
                # Image path lookup - do in background or skip for performance
                # For 100 Hz, we skip this in main loop and handle in CSV writer if needed
                img_path = None  # Set to None for max speed; CSV writer can lookup if needed

                # Pack data as tuple (much faster than dict construction)
                row_tuple = (timestamp_ms, img_path, mpu, lat, lon, spd, speed_limit, speed_source)

                # Check if ride is still active (control poll thread updates this)
                if not current_is_active:
                    # Ride has ended - wait for queue to drain, then upload
                    print(f"\nRide {ride_id} ended. Flushing data...")
                    
                    # Wait for CSV queue to empty (with timeout)
                    timeout = time.time() + 5.0
                    while not csv_write_queue.empty() and time.time() < timeout:
                        time.sleep(0.1)
                    
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
                    
                    # Break out of the inner loop to start new ride
                    break

                # Queue CSV write (non-blocking, fast)
                try:
                    csv_write_queue.put_nowait(row_tuple)
                except:
                    pass  # Queue full, skip this sample

                # Increment sample counter
                sample_count += 1
                
                # Queue console output much less frequently (1 Hz at 100 Hz sampling)
                if sample_count % print_interval == 0:
                    readable_ts = datetime.fromtimestamp(timestamp_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                    msg = (f"[{sample_count}] Time={readable_ts} Acc=({mpu[0]:.4f},{mpu[1]:.4f},{mpu[2]:.4f}) "
                           f"Speed={spd:.2f} km/h Src={speed_source}")
                    try:
                        print_queue.put_nowait(msg)
                    except:
                        pass

                # Queue Firebase push periodically
                if (t_wall - last_fb_push) >= fb_interval:
                    if all(v is not None for v in mpu):
                        try:
                            firebase_push_queue.put_nowait({
                                'type': 'mpu',
                                'user_id': USER_ID,
                                'ax': mpu[0], 'ay': mpu[1], 'az': mpu[2],
                                'gx': mpu[3], 'gy': mpu[4], 'gz': mpu[5],
                                'ts': target_timestamp_ms
                            })
                        except:
                            pass
                    
                    try:
                        warnings = firebase_uploader.build_speeding_warning(spd, speed_limit)
                        firebase_push_queue.put_nowait({
                            'type': 'speed',
                            'user_id': USER_ID,
                            'speed': spd,
                            'limit': speed_limit,
                            'warnings': warnings
                        })
                    except:
                        pass
                    last_fb_push = t_wall

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
