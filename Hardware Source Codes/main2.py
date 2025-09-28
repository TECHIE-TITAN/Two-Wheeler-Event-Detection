import time
import csv
import os
import threading
import math
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

# Estimator state (accelerometer-based)
_est_speed_m_s = 0.0                 # estimated speed in m/s (integrated from accel)
_last_mpu_timestamp_ms = None       # last timestamp used to integrate accel
_est_speed_lock = threading.Lock()  # protect estimated speed shared state

# Running bias estimate to remove accel DC bias (in m/s^2)
_accel_bias_m_s2 = 0.0
# Parameters for bias estimator and deadband
_BIAS_ALPHA = 0.0005      # very slow low-pass to capture DC bias
_DEADBAND_ACCEL = 0.02    # m/s^2 threshold to treat tiny accel as zero
_MIN_SPEED_FOR_SYNC = 0.1  # m/s: only sync estimator to GPS if speed reasonably > this


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


def _normalize_gps_speed_to_kmh(gps_speed_raw, speed_from_position_m_s=None):
    """
    Normalize GPS speed to km/h with simple heuristics.
    The GPS speed field can be in m/s or km/h depending on module/library.

    Returns: float (km/h) or None if cannot parse.
    """
    if gps_speed_raw is None:
        return None

    try:
        s = float(gps_speed_raw)
    except Exception:
        return None

    if s < 0.0:
        return None

    # Two candidates:
    # candidate_m_s = s (m/s) -> km/h = s * 3.6
    # candidate_kmh = s (already km/h)
    cand_kmh_from_m_s = s * 3.6
    cand_kmh_raw = s

    # Heuristic: if raw number is > 50, it's probably km/h already (e.g., 80 km/h)
    if s > 50.0:
        return cand_kmh_raw

    # If we have a position-based speed (m/s) compare and pick the candidate closer to that
    if speed_from_position_m_s is not None:
        pos_kmh = speed_from_position_m_s * 3.6
        if abs(cand_kmh_raw - pos_kmh) < abs(cand_kmh_from_m_s - pos_kmh):
            return cand_kmh_raw
        else:
            return cand_kmh_from_m_s

    # Otherwise prefer the m/s->km/h conversion for reasonable-looking values
    return cand_kmh_from_m_s


def _update_estimated_speed_from_accel(accel_tuple, timestamp_ms):
    """
    Integrate longitudinal acceleration to estimate speed when GPS is unavailable.

    - accel_tuple: (acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z)
    - accelerations are assumed to be in 'g' per your repo: convert to m/s^2 by *9.81.
    - Uses a slow running bias estimator to remove DC bias and a deadband to reduce drift.
    """
    global _est_speed_m_s, _last_mpu_timestamp_ms, _accel_bias_m_s2

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
        acc_x_m_s2_raw = float(acc_x_g) * 9.81
    except Exception:
        return

    # Update timestamp bookkeeping
    if _last_mpu_timestamp_ms is None:
        _last_mpu_timestamp_ms = timestamp_ms
        # update bias estimate once so subsequent dt is computed
        _accel_bias_m_s2 = (1 - _BIAS_ALPHA) * _accel_bias_m_s2 + _BIAS_ALPHA * acc_x_m_s2_raw
        return

    dt_s = max(0.0, (timestamp_ms - _last_mpu_timestamp_ms) / 1000.0)
    _last_mpu_timestamp_ms = timestamp_ms
    if dt_s <= 0.0:
        # still update bias
        _accel_bias_m_s2 = (1 - _BIAS_ALPHA) * _accel_bias_m_s2 + _BIAS_ALPHA * acc_x_m_s2_raw
        return

    # Very slow running estimate of bias (low-pass filter)
    _accel_bias_m_s2 = (1 - _BIAS_ALPHA) * _accel_bias_m_s2 + _BIAS_ALPHA * acc_x_m_s2_raw

    # Remove bias
    acc_x_m_s2 = acc_x_m_s2_raw - _accel_bias_m_s2

    # Deadband to avoid tiny noisy values accumulating
    if abs(acc_x_m_s2) < _DEADBAND_ACCEL:
        acc_x_m_s2 = 0.0

    # Integrate to update velocity (m/s)
    delta_v = acc_x_m_s2 * dt_s
    with _est_speed_lock:
        new_speed = _est_speed_m_s + delta_v
        # Small deadband on velocity too
        if abs(new_speed) < 0.02:
            new_speed = 0.0
        # clamp to non-negative (we assume forward axis only)
        _est_speed_m_s = max(0.0, new_speed)


def get_current_estimated_speed_m_s():
    with _est_speed_lock:
        return _est_speed_m_s


def haversine_m(lat1, lon1, lat2, lon2):
    """Return meters between two lat/lon points (great-circle)."""
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main():
    global latest_speed_limit, last_speed_limit_fetch, _est_speed_m_s

    # For position-based fallback (in case GPS speed field missing)
    last_gps_fix = (None, None)
    last_gps_fix_time = None

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
        # final speed is in km/h; we also include estimator-only and raw gps for debugging
        fieldnames = [
            'timestamp', 'acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z',
            'latitude', 'longitude', 'gps_speed_raw', 'est_speed_kmh', 'speed_kmh', 'speed_limit'
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        try:
            while True:
                loop_time_s = time.time()
                target_timestamp_ms = int(loop_time_s * 1000)

                # Copy latest sensor values under lock
                lat = None
                lon = None
                gps_speed_raw = None
                with data_lock:
                    mpu = latest_mpu
                    gps = latest_gps
                    if gps:
                        if len(gps) >= 2:
                            lat = gps[0]
                            lon = gps[1]
                        if len(gps) >= 3:
                            gps_speed_raw = gps[2]

                # Refresh speed limit if GPS available
                if lat is not None and lon is not None:
                    t_now = time.time()
                    if (latest_speed_limit is None) or (t_now - last_speed_limit_fetch >= SPEED_LIMIT_REFRESH_S):
                        try:
                            latest_speed_limit = speed_limit_utils.get_speed_limit(lat, lon, OLA_MAPS_API_KEY)
                        except Exception as e:
                            print(f"Speed limit fetch error: {e}")
                        last_speed_limit_fetch = t_now

                # Update estimated speed from accelerometer (always run)
                try:
                    _update_estimated_speed_from_accel(mpu, target_timestamp_ms)
                except Exception as e:
                    print(f"Error updating estimated speed from accel: {e}")

                # Compute position-derived speed if lat/lon available and have previous fix
                speed_from_position_m_s = None
                if lat is not None and lon is not None:
                    t_now = time.time()
                    if last_gps_fix_time is not None and last_gps_fix[0] is not None:
                        dt_pos = max(1e-6, t_now - last_gps_fix_time)
                        try:
                            dist_m = haversine_m(lat, lon, last_gps_fix[0], last_gps_fix[1])
                            speed_from_position_m_s = dist_m / dt_pos
                        except Exception:
                            speed_from_position_m_s = None
                    last_gps_fix = (lat, lon)
                    last_gps_fix_time = t_now

                # Normalize GPS speed field to km/h (if present)
                gps_speed_kmh = _normalize_gps_speed_to_kmh(gps_speed_raw, speed_from_position_m_s)

                # Estimator-only speed in km/h (for debug/logging)
                est_speed_m_s = get_current_estimated_speed_m_s()
                est_speed_kmh = est_speed_m_s * 3.6

                # Decide final speed_kmh:
                # Priority: gps_speed_kmh (if available) -> position-derived -> estimator-only
                final_speed_kmh = est_speed_kmh
                source = "EST"

                if gps_speed_kmh is not None:
                    # Light sync: blend estimator towards GPS to remove accumulated drift
                    with _est_speed_lock:
                        gps_m_s = gps_speed_kmh / 3.6
                        # Only sync if GPS speed is above tiny threshold to avoid syncing noise at zero
                        if gps_m_s > _MIN_SPEED_FOR_SYNC or est_speed_m_s > _MIN_SPEED_FOR_SYNC:
                            alpha = 0.9  # trust GPS mostly
                            _est_speed_m_s = max(0.0, alpha * gps_m_s + (1.0 - alpha) * _est_speed_m_s)
                        else:
                            # If both near zero keep estimator near zero
                            _est_speed_m_s = 0.0
                        final_speed_kmh = gps_speed_kmh
                        source = "GPS"
                elif speed_from_position_m_s is not None:
                    # Use position-derived speed (convert to km/h) and sync estimator lightly
                    pos_kmh = speed_from_position_m_s * 3.6
                    with _est_speed_lock:
                        alpha = 0.8
                        _est_speed_m_s = max(0.0, alpha * speed_from_position_m_s + (1.0 - alpha) * _est_speed_m_s)
                    final_speed_kmh = pos_kmh
                    source = "POS"
                else:
                    # No GPS -> estimator-only (already computed)
                    final_speed_kmh = est_speed_kmh
                    source = "EST"

                # Prepare CSV row
                row = {
                    'timestamp': target_timestamp_ms / 1000.0,
                    'acc_x': mpu[0] if (mpu and len(mpu) >= 1) else None,
                    'acc_y': mpu[1] if (mpu and len(mpu) >= 2) else None,
                    'acc_z': mpu[2] if (mpu and len(mpu) >= 3) else None,
                    'gyro_x': mpu[3] if (mpu and len(mpu) >= 4) else None,
                    'gyro_y': mpu[4] if (mpu and len(mpu) >= 5) else None,
                    'gyro_z': mpu[5] if (mpu and len(mpu) >= 6) else None,
                    'latitude': lat,
                    'longitude': lon,
                    'gps_speed_raw': gps_speed_raw,
                    'est_speed_kmh': round(est_speed_kmh, 3),
                    'speed_kmh': round(final_speed_kmh, 3),
                    'speed_limit': latest_speed_limit
                }
                writer.writerow(row)
                csvfile.flush()

                # Upload to Firebase: push speed (in km/h) and speed_limit unchanged
                try:
                    # NOTE: we're sending km/h here — change to m/s if your backend expects m/s
                    firebase_uploader.update_rider_speed(USER_ID, final_speed_kmh, latest_speed_limit or 0.0)
                except Exception as e:
                    print(f"Failed to push speed to Firebase: {e}")

                # Push latest MPU data (so server has raw sensor context)
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

                # optional simple console log for debugging
                # print(f"time={target_timestamp_ms} src={source} speed_kmh={final_speed_kmh:.2f}")

                time.sleep(SAMPLE_INTERVAL)

        except KeyboardInterrupt:
            print("Program terminated by user.")
        finally:
            pass


if __name__ == "__main__":
    main()
