import time
import csv
import os
import threading
import mpu_utils # type: ignore  # noqa
import gps_utils # type: ignore  # noqa
import speed_limit_utils # type: ignore  # noqa
import camera_utils # type: ignore  # noqa
import firebase_uploader # type: ignore  # noqa

TARGET_HZ = 1
SAMPLE_INTERVAL = 1.0 / TARGET_HZ
OLA_MAPS_API_KEY = "50c25aHLICdWQ4JbXp2MZwgmliGxvqJ8os1MOYe3"
SPEED_LIMIT_REFRESH_S = 1.0  
FIREBASE_PUSH_INTERVAL_S = 1.0
USER_ID = "demo_user_123"

data_lock = threading.Lock()
latest_mpu = (None, None, None, None, None, None)
latest_gps = (None, None, None)  # lat, lon, speed(km/h)
latest_image_path = None
latest_speed_limit = None
last_speed_limit_fetch = 0.0
stop_event = threading.Event()


def mpu_thread():
    global latest_mpu
    while not stop_event.is_set():
        data = mpu_utils.get_mpu_data()
        with data_lock:
            latest_mpu = data
        time.sleep(0.005)


def gps_thread(gps_serial):
    global latest_gps
    while not stop_event.is_set():
        gps_data = gps_utils.get_gps_data(gps_serial)
        if gps_data:
            with data_lock:
                if len(gps_data) == 3:
                    latest_gps = gps_data
                else:
                    latest_gps = (gps_data[0], gps_data[1], None)
        time.sleep(0.2)


def camera_thread(camera_manager):
    global latest_image_path
    while not stop_event.is_set():
        path = camera_utils.capture_image(camera_manager)
        if path:
            with data_lock:
                latest_image_path = path
        time.sleep(SAMPLE_INTERVAL)


def main():
    global latest_speed_limit, last_speed_limit_fetch
    try:
        firebase_uploader.init_auth()
    except Exception as e:
        print(f"Firebase auth init failed: {e}")

    # Initialize sensors
    mpu_utils.init_mpu()
    gps_serial = gps_utils.init_gps()
    camera_manager = None
    try:
        camera_manager = camera_utils.init_camera()
    except Exception as e:
        print(f"Camera init failed: {e}")

    # Start sensor threads
    threads = [
        threading.Thread(target=mpu_thread, daemon=True),
        threading.Thread(target=gps_thread, args=(gps_serial,), daemon=True),
    ]
    if camera_manager:
        threads.append(threading.Thread(target=camera_thread, args=(camera_manager,), daemon=True))

    for t in threads:
        t.start()

    # Initialize Firebase ride
    try:
        firebase_uploader.init_ride(USER_ID, int(time.time() * 1000))
    except Exception as e:
        print(f"Firebase ride init failed: {e}")

    csv_filename = "sensor_stream.csv"
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
                if now < next_sample_time:
                    time.sleep(next_sample_time - now)
                next_sample_time += SAMPLE_INTERVAL

                with data_lock:
                    mpu = latest_mpu
                    gps = latest_gps
                    img_path = latest_image_path

                lat, lon, spd = gps

                if lat is not None and lon is not None:
                    t_now = time.time()
                    if (latest_speed_limit is None) or (t_now - last_speed_limit_fetch >= SPEED_LIMIT_REFRESH_S):
                        latest_speed_limit = speed_limit_utils.get_speed_limit(lat, lon, OLA_MAPS_API_KEY)
                        last_speed_limit_fetch = t_now

                row = {
                    'timestamp': time.time(),
                    'image_path': img_path or '',
                    'acc_x': mpu[0], 'acc_y': mpu[1], 'acc_z': mpu[2],
                    'gyro_x': mpu[3], 'gyro_y': mpu[4], 'gyro_z': mpu[5],
                    'latitude': lat, 'longitude': lon,
                    'speed': spd,
                    'speed_limit': latest_speed_limit
                }
                writer.writerow(row)
                if int(row['timestamp']) % 5 == 0:
                    f.flush()

                if (time.time() - last_fb_push) >= FIREBASE_PUSH_INTERVAL_S:
                    try:
                        warnings = firebase_uploader.build_speeding_warning(spd, latest_speed_limit)
                        firebase_uploader.update_rider_speed(USER_ID, spd, latest_speed_limit, warnings)
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
            if camera_manager:
                try:
                    camera_manager.close()
                except Exception:
                    pass
            print("Log complete.")


if __name__ == '__main__':
    main()