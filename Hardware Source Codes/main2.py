import time
import csv
import os
import threading
import glob
import mpu_utils  # type: ignore
import gps_utils  # type: ignore
import speed_limit_utils  # type: ignore
import firebase_uploader  # type: ignore

TARGET_HZ = 1
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

# Extras for speed estimation fallback when GPS is unavailable
_est_speed_m_s = 0.0                 # estimated speed in m/s (integrated from accel)
_last_mpu_timestamp_ms = None       # last timestamp we used to integrate accel
_est_speed_lock = threading.Lock()  # protect estimated speed shared state


def sensor_thread(func, key, *args):
    """
    Generic sensor thread that periodically calls `func` and stores the result
    into the appropriate global variable keyed by `key`.
    """
    global latest_mpu, latest_gps
    while True:
        try:
            val = func(*args)
        except Exception as e:
            val = None
            print(f"Sensor thread for {key} exception: {e}")

        with data_lock:
            if key == "mpu_data":
                # Expect a 6-tuple: (acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z)
                latest_mpu = val if val is not None else latest_mpu
            elif key == "gps_data":
                # Expect a tuple like (lat, lon, speed) or None
                latest_gps = val if val is not None else latest_gps
            else:
                pass

        time.sleep(SAMPLE_INTERVAL)


def _update_estimated_speed_from_accel(accel_tuple, timestamp_ms):
    """
    Integrate longitudinal acceleration to estimate speed when GPS is unavailable.

    - accel_tuple: (acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z)
    - accelerations are in g (per repository scaling); we convert g -> m/s^2 by *9.81.
    - This function treats acc_x (index 0) as the forward longitudinal acceleration.
    """
    global _est_speed_m_s, _last_mpu_timestamp_ms
    if accel_tuple is None:
        return

    try:
        acc_x_g = accel_tuple[0]
    except Exception:
        return

    if acc_x_g is None:
        return

    # Convert from g to m/s^2
    try:
        acc_x_m_s2 = float(acc_x_g) * 9.81
    except Exception:
        return

    if _last_mpu_timestamp_ms is None:
        _last_mpu_timestamp_ms = timestamp_ms
        return

    dt_s = max(0.0, (timestamp_ms - _last_mpu_timestamp_ms) / 1000.0)
    _last_mpu_timestamp_ms = timestamp_ms

    if dt_s <= 0.0:
        return

    delta_v = acc_x_m_s2 * dt_s

    with _est_speed_lock:
        new_speed = _est_speed_m_s + delta_v
        # small deadband to reduce drift from tiny noisy accelerations
        if abs(new_speed) < 0.02:
            new_speed = 0.0
        # clamp to non-negative
        _est_speed_m_s = max(0.0, new_speed)


def get_current_estimated_speed():
    with _est_speed_lock:
        return _est_speed_m_s


def main():
    global latest_speed_limit, last_speed_limit_fetch, _est_speed_m_s

    # Start sensor threads
    threads = [
        threading.Thread(target=sensor_thread, args=(mpu_utils.get_mpu_data, "mpu_data")),
        threading.Thread(target=sensor_thread, args=(gps_utils.get_gps_data, "gps_data")),
    ]
    for t in threads:
        t.daemon = True
        t.start()

    # Setup CSV file for writing
    file_exists = os.path.isfile(CSV_FILENAME)
    with open(CSV_FILENAME, "a", newline="") as csvfile:
        fieldnames = ['timestamp', 'acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z',
                      'latitude', 'longitude', 'speed', 'speed_limit']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        try:
            while True:
                target_timestamp_ms = int(time.time() * 1000)

                # Copy latest sensor values under lock
                lat = None
                lon = None
                gps_speed = None
                with data_lock:
                    mpu = latest_mpu
                    gps = latest_gps
                    if gps:
                        if len(gps) >= 2:
                            lat = gps[0]
                            lon = gps[1]
                        if len(gps) >= 3:
                            gps_speed = gps[2]

                # Refresh speed limit if GPS available
                if lat is not None and lon is not None:
                    t_now = time.time()
                    if (latest_speed_limit is None) or (t_now - last_speed_limit_fetch >= SPEED_LIMIT_REFRESH_S):
                        try:
                            latest_speed_limit = speed_limit_utils.get_speed_limit(lat, lon, OLA_MAPS_API_KEY)
                        except Exception as e:
                            print(f"Speed limit fetch error: {e}")
                        last_speed_limit_fetch = t_now

                # Update estimated speed from accelerometer
                try:
                    _update_estimated_speed_from_accel(mpu, target_timestamp_ms)
                except Exception as e:
                    print(f"Error updating estimated speed from accel: {e}")

                # Decide which speed to use (GPS preferred)
                est_speed_m_s = get_current_estimated_speed()
                if gps_speed is not None:
                    # If your GPS gives speed in km/h, convert to m/s: gps_speed_m_s = float(gps_speed) / 3.6
                    # Many GPS modules report speed in m/s; adapt if needed.
                    try:
                        gps_speed_m_s = float(gps_speed)
                    except Exception:
                        gps_speed_m_s = est_speed_m_s
                    speed_to_use_m_s = gps_speed_m_s

                    # synchronize estimator to GPS to reduce drift
                    with _est_speed_lock:
                        _est_speed_m_s = speed_to_use_m_s
                else:
                    speed_to_use_m_s = est_speed_m_s

                # Prepare CSV row
                row = {
                    'timestamp': target_timestamp_ms / 1000.0,
                    'acc_x': mpu[0] if mpu else None,
                    'acc_y': mpu[1] if mpu else None,
                    'acc_z': mpu[2] if mpu else None,
                    'gyro_x': mpu[3] if mpu else None,
                    'gyro_y': mpu[4] if mpu else None,
                    'gyro_z': mpu[5] if mpu else None,
                    'latitude': lat,
                    'longitude': lon,
                    'speed': speed_to_use_m_s,
                    'speed_limit': latest_speed_limit
                }
                writer.writerow(row)
                csvfile.flush()

                # Upload to Firebase:
                # 1) Push speed (preferred)
                try:
                    # update_rider_speed(user_id, speed, speed_limit)
                    firebase_uploader.update_rider_speed(USER_ID, speed_to_use_m_s, latest_speed_limit or 0.0)
                except Exception as e:
                    print(f"Failed to push speed to Firebase: {e}")

                # 2) Push latest MPU data (so server has raw sensor context)
                try:
                    acc_x = mpu[0] if (mpu and len(mpu) >= 1) else None
                    acc_y = mpu[1] if (mpu and len(mpu) >= 2) else None
                    acc_z = mpu[2] if (mpu and len(mpu) >= 3) else None
                    gyro_x = mpu[3] if (mpu and len(mpu) >= 4) else None
                    gyro_y = mpu[4] if (mpu and len(mpu) >= 5) else None
                    gyro_z = mpu[5] if (mpu and len(mpu) >= 6) else None
                    firebase_uploader.update_rider_mpu(
                        USER_ID,
                        acc_x,
                        acc_y,
                        acc_z,
                        gyro_x,
                        gyro_y,
                        gyro_z,
                        timestamp_ms=target_timestamp_ms
                    )
                except Exception as e:
                    print(f"Failed to push MPU data to Firebase: {e}")

                time.sleep(SAMPLE_INTERVAL)

        except KeyboardInterrupt:
            print("Program terminated by user.")
        finally:
            pass


if __name__ == "__main__":
    main()
