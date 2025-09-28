# Two-Wheeler-Event-Detection

Tasks Distribution:
  - Vansh Goyal: MPU 6500, GPS Neo-6M Module, LDR Sensor
  - Naman Aggarwal: SD Card Configuration
  - Shivek Gupta: Pi Cam Module 3 Config
  - Samarth Singla: LiDAR Sensor

To activate environment use:

```bash
source .venv/bin/activate
```

Also install RPi.GPIO in your global system using:

```bash
sudo apt install python3-rpi.gpio
```

To install libraries, run:

```bash
pip install -r requirements.txt
```

---

Usage (Pi telemetry and Firebase integration)

Overview

This repository contains code for a Raspberry Pi-based two-wheeler telemetry and event-capture system. The Pi reads MPU/GPS data, logs it to `sensor_data.csv`, and pushes telemetry to Firebase Realtime Database. It can also upload a full ride's CSV and images when triggered remotely.

Key files

- `Hardware Source Codes/main2.py`: primary data collector and Firebase uploader.
- `Hardware Source Codes/firebase_uploader.py`: helper functions for Firebase authentication and read/write operations.

Control flags and ride-scoped model

Rides are stored under `users/<user_id>/rides/<ride_id>/...`. Ride IDs are auto-incremented integers; if no rides exist the first ride ID will be `0`.

Primary DB paths used by the Pi:

- `users/<user_id>/rides/<ride_id>/rider_control/ride_status`:
  - `is_active` (bool) — when true Pi collects and uploads telemetry
  - `calculate_model` (bool) — when true Pi uploads CSV+images for that ride
- `users/<user_id>/rides/<ride_id>/ride_data` (PUT) — full array of CSV rows
- `users/<user_id>/rides/<ride_id>/ride_images/<image_key>` — base64-encoded images with metadata

Legacy paths (kept for backwards compatibility):

- `users/<user_id>/rider_control/ride_status`
- `users/<user_id>/rider_data`
- `users/<user_id>/ride_data`

Running

1. Install requirements:

```bash
pip3 install -r requirements.txt
```

2. Run the collector on the Pi:

```bash
python3 "Hardware Source Codes/main2.py"
```

Notes

- Images are uploaded as base64 to Realtime DB; consider using Firebase Storage for production to avoid large DB growth.
- CSV rows are uploaded via `csv.DictReader` (string values). Ask me to convert fields to numeric types if required.

If you'd like, I can update the code to use Firebase Storage for images, or add typed CSV parsing and a small viewer for uploaded rides.

---

# Firebase uploader analysis

This section documents a comprehensive analysis of `Hardware Source Codes/firebase_uploader.py` and how `Hardware Source Codes/main2.py` interacts with it. It lists data points uploaded, DB paths, example JSON shapes, sources of values, edge cases, and recommended improvements.

## What the uploader does

- Authenticates to Firebase using email/password (Identity Toolkit) and manages token refresh.
- Writes telemetry and control flags to Firebase Realtime Database via REST API (`requests`).
- Uploads full ride CSV data and images (images are stored as base64 blobs in the database).

## Data points written to Firebase (detailed)

1) Rider data summary (PATCH -> `/users/{user_id}/rider_data`)
- `current_speed`: number (float) — `spd` from GPS
- `speed_limit`: number or null — `latest_speed_limit` from `speed_limit_utils.get_speed_limit`
- `active_warnings_list`: object (map) — result of `build_speeding_warning(speed, speed_limit)`; empty object when no warnings
- `mpu`: nested object (written by `update_rider_mpu`):
  - `acc_x`, `acc_y`, `acc_z`: float
  - `gyro_x`, `gyro_y`, `gyro_z`: float
  - `timestamp`: integer (ms)

Notes: `update_rider_speed` and `update_rider_mpu` both PATCH to the same `rider_data` node.

2) Ride control status (ride-scoped preferred)
- Path: `/users/{user_id}/rides/{ride_id}/rider_control/ride_status` (PATCH/GET)
- Keys:
  - `is_active`: boolean
  - `start_timestamp`: integer (ms)
  - `calculate_model`: boolean

3) Top-level ride control status (preferred top-level path)
- Path: `/{user_id}/ride_control/ride_status` (GET/PATCH fallback)
- Same keys as above.

4) Ride list and `ride_data`
- Path for ride list: `/users/{user_id}/rides` (GET)
- Path for ride rows upload: `/users/{user_id}/rides/{ride_id}/ride_data` (PUT)
  - Value: array of row objects (replaces existing node)
  - Row fields (from CSV via `main2.py`):
    - `timestamp`: string (ms) — normalized in `model_calculation`
    - `image_path`: string (original local path written to CSV)
    - `image_db_ref`: optional string pointing to ride image DB path (added by `model_calculation` after uploading image)
    - `base64`: optional string note `(stored under ride_images_base64)` when ride-scoped image uploaded
    - `acc_x`, `acc_y`, `acc_z`, `gyro_x`, `gyro_y`, `gyro_z`: float
    - `latitude`, `longitude`: float or null
    - `speed`: float or null
    - `speed_limit`: float or null

5) Ride images (base64 stored inside Realtime DB)
- Ride-scoped path (preferred): `/users/{user_id}/rides/{ride_id}/ride_images_base64/{timestamp_key}` (PUT)
  - Object saved:
    - `content_type`: string (e.g., image/jpeg)
    - `uploaded_at`: integer (ms)
    - `data_base64`: string (base64 binary)
- Legacy non-ride-scoped: `/users/{user_id}/ride_images/{image_key}` (PUT)
  - Object saved:
    - `filename`
    - `content_type`
    - `uploaded_at`
    - `data_base64`

6) Control helper operations (read-only or small writes)
- `get_control_flags_for_ride` reads either ride-scoped or top-level path and returns `(is_active, calculate_model)` booleans.
- `set_control_flag` writes a single boolean field under `ride_status` at the appropriate path.
- `toggle_calculate_model_off` sets `calculate_model` to False.

## Example JSON shapes

Rider data (`/users/{user_id}/rider_data`):

{
  "current_speed": 45.2,
  "speed_limit": 40.0,
  "active_warnings_list": {
    "warning_1700000000000": {
      "type": "speed_limit",
      "message": "Speed Limit Exceeded!",
      "timestamp": 1700000000000
  }
},
  "mpu": {
    "acc_x": 0.123,
    "acc_y": -0.010,
    "acc_z": 9.810,
    "gyro_x": 0.001,
    "gyro_y": 0.002,
    "gyro_z": 0.000,
    "timestamp": 1700000000000
  }
}

Ride data (ride-scoped, `/users/{user_id}/rides/{ride_id}/ride_data`):

[
  {
    "timestamp": "1700000000000",
    "image_path": "captured_images/frame_1700000000000.jpg",
    "image_db_ref": "users/uid/rides/0/ride_images_base64/1700000000000",
    "base64": "(stored under ride_images_base64)",
    "acc_x": 0.123,
    "acc_y": -0.010,
    "acc_z": 9.810,
    "gyro_x": 0.001,
    "gyro_y": 0.002,
    "gyro_z": 0.000,
    "latitude": 12.345678,
    "longitude": 98.765432,
    "speed": 45.2,
    "speed_limit": 40.0
  }
]

Ride image (ride-scoped): `/users/{user_id}/rides/{ride_id}/ride_images_base64/1700000000000`:

{
  "content_type": "image/jpeg",
  "uploaded_at": 1700000000000,
  "data_base64": "/9j/4AAQ..."
}

## Where values come from in the code

- `main2.py` constructs CSV rows and calls uploader functions.
- GPS values (latitude, longitude, speed) come from `gps_utils.get_gps_data()` and are stored in `latest_gps`.
- MPU values (acc_x..gyro_z) come from `mpu_utils.get_mpu_data()` and are stored in `latest_mpu`.
- `speed_limit` is retrieved by `speed_limit_utils.get_speed_limit(lat, lon, OLA_MAPS_API_KEY)`.
- `model_calculation` reads CSV rows, uploads images (via `upload_ride_image_base64_for_ride`), replaces `image_path` with `image_db_ref`, and then uploads the full `ride_data` array via `upload_ride_data_for_ride`.

## Edge cases and notes

- Many numeric fields can be `None` (e.g., when GPS has no fix). Realtime DB will store `null` when a JSON `null` is sent.
- `update_rider_mpu` is only called when all MPU values are present.
- `upload_ride_data_for_ride` uses PUT and will overwrite the existing `ride_data` node.
- Images are stored directly as base64 in Realtime DB (can be large). Consider using Firebase Storage and storing only URLs.
- `get_next_ride_id` assumes ride keys under `/users/{user_id}/rides` are numeric strings.

## Recommendations

1. Use Firebase Storage for images instead of saving base64 in Realtime DB. Store download URL or a short DB ref.
2. Standardize timestamps as integer ms everywhere (avoid mixing string vs numeric timestamps).
3. Decide on a single canonical control path (ride-scoped is recommended) and simplify fallbacks if not required.
4. Optionally filter out `None` fields before writing to DB to keep nodes smaller and cleaner.
5. When uploading `ride_data`, consider chunked uploads or an incremental append approach (push keys) if rides can be very large — PUTting the entire array may become slow or exceed DB limits.

## Next steps I can take (optional)
- Convert image uploading to Firebase Storage and return URLs instead of writing base64 to Realtime DB.
- Add a small wrapper that normalizes timestamps and drops `None` fields before writes.
- Add unit tests or small smoke scripts to validate each DB path (requires Firebase credentials).

---

Analysis produced from `Hardware Source Codes/firebase_uploader.py` and `Hardware Source Codes/main2.py`.

If you'd like, I can commit code changes to implement any recommendations.