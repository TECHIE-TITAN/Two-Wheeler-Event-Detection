Firebase Realtime Database Schema for Two-Wheeler-Event-Detection

This document maps every Firebase Realtime Database node the RPi code reads or writes,
including HTTP method used (PUT/PATCH/GET), expected payload shapes, and examples.

Base DB URL: `https://wheeler-event-detection-default-rtdb.asia-southeast1.firebasedatabase.app`

Top-level user paths (legacy and new ride-scoped):
- Legacy (older writers): `/users/{user_id}/...`
- Preferred ride-scoped: `/users/{user_id}/rides/{ride_id}/...`

1) Auth/state helpers
- Clients call Identity/securetoken endpoints; not part of RTDB schema.

2) Rider realtime overview (legacy)
- Path: `PATCH /users/{user_id}/rider_data.json`
- Purpose: store quick-access latest rider telemetry.
- Payload example:
  {
    "current_speed": 15.2,
    "speed_limit": 15.0,
    "active_warnings_list": { "warning_1234567890": { "type": "speed_limit", "message": "Speed Limit Exceeded!", "timestamp": 1234567890 } }
  }
- Writer: `firebase_uploader.update_rider_speed()` (PATCH)

3) Latest MPU snapshot (legacy)
- Path: `PATCH /users/{user_id}/rider_data.json`
- Payload example:
  { "mpu": { "acc_x": 0.1, "acc_y": 0.0, "acc_z": 9.8, "gyro_x": 0.01, "gyro_y": 0.02, "gyro_z": 0.0, "timestamp": 1694784000000 } }
- Writer: `firebase_uploader.update_rider_mpu()` (PATCH)

4) Control flags (ride start/stop and model trigger)
- Legacy (top-level): `PATCH /{user_id}/ride_control/ride_status.json`
  - Example payload: { "is_active": true, "start_timestamp": 1694784000000, "calculate_model": false }
- Legacy fallback: `PATCH /users/{user_id}/rider_control/ride_status.json`
- Ride-scoped (preferred): `PATCH /users/{user_id}/rides/{ride_id}/rider_control/ride_status.json`
  - Writer: `init_ride_for_ride()` (on ride start)
  - Readers/writers: `get_control_flags_for_ride()`, `set_control_flag()` and `toggle_calculate_model_off()`
- GET readers: `get_control_flags_for_ride()` (GET)

5) Ride auto-increment listing
- Path: `GET /users/{user_id}/rides.json`
- Purpose: list existing rides and compute next numeric `ride_id`.
- Reader: `get_next_ride_id()` (GET)

6) Full ride CSV upload (JSON array)
- Path (ride-scoped): `PUT /users/{user_id}/rides/{ride_id}/ride_data.json`
  - Method: PUT (replaces node with the provided array)
  - Payload: JSON list of rows (as read by `csv.DictReader`). Each row is a JSON object with fields like:
    - timestamp (string from CSV), image_path (path on Pi), acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, latitude, longitude, speed, speed_limit
  - Additional fields set during upload:
    - `image_db_ref`: string (e.g., "users/{user_id}/rides/{ride_id}/ride_images_base64/{timestamp_key}") when image uploaded
    - `base64`: short marker string "(stored under ride_images_base64)"
  - Writer: `upload_ride_data_for_ride()` called by `model_calculation()` in `main2.py` after reading CSV and uploading images.
- Legacy path: `PUT /users/{user_id}/ride_data.json`

7) Ride image base64 store (two variants)
- Legacy single-image path (non-ride-scoped):
  - `PUT /users/{user_id}/ride_images/{image_key}.json`
  - Payload: { "filename": "frame_169...jpg", "content_type": "image/jpeg", "uploaded_at": 169..., "data_base64": "..." }
  - Writer: `upload_ride_image_base64()` with `ride_id=None`
  - DB ref returned: `users/{user_id}/ride_images/{image_key}`

- Ride-scoped (preferred per latest changes):
  - `PUT /users/{user_id}/rides/{ride_id}/ride_images/{timestamp_key}.json`
    - Note: older helper used `/ride_images/` for ride-scoped; this exists but we now use `ride_images_base64` (see below) in `model_calculation()`.
  - `PUT /users/{user_id}/rides/{ride_id}/ride_images_base64/{timestamp_key}.json`
    - Payload: { "content_type": "image/jpeg", "uploaded_at": 169..., "data_base64": "..." }
    - Writer: `upload_ride_image_base64_for_ride(user_id, ride_id, timestamp_key, file_path)`
    - DB ref returned to caller: `users/{user_id}/rides/{ride_id}/ride_images_base64/{timestamp_key}`
  - `model_calculation()` uploads images using `timestamp_key = row['timestamp']` (or current ms timestamp if missing), then sets `row['image_db_ref']` to the returned DB ref.

Notes and conventions
- Timestamps:
  - `init_ride_for_ride()` writes `start_timestamp` (ms since epoch, int)
  - `update_rider_mpu()` uses `timestamp_ms` (ms int)
  - CSV `timestamp` field is normalized by `main2.py` to an integer millisecond timestamp (ms since epoch) and stored as a string in the uploaded JSON. Use these integer-ms strings as image keys.

- Data types:
  - CSV values are uploaded as strings via `csv.DictReader`. If consumers expect numbers, perform casting before upload.

- Safety and performance:
  - Storing base64 image bytes in Realtime DB can quickly grow the DB and exceed size/throughput limits. For production, prefer Firebase Storage and store secure download URLs in DB.

- Example ride_data payload (array with 2 rows):
  [
    {
      "timestamp": "1694784012000",
      "image_path": "captured_images/frame_1694784012000.jpg",
      "acc_x": "0.1",
      "acc_y": "0.0",
      "acc_z": "9.8",
      "gyro_x": "0.01",
      "gyro_y": "0.02",
      "gyro_z": "0.0",
      "latitude": "12.34",
      "longitude": "56.78",
      "speed": "14.2",
      "speed_limit": "15.0",
      "image_db_ref": "users/WlD.../rides/0/ride_images_base64/1694784012000",
      "base64": "(stored under ride_images_base64)"
    }
  ]

Mapping: function -> DB node summary
- `update_rider_speed()` -> `PATCH /users/{user_id}/rider_data.json`
- `update_rider_mpu()` -> `PATCH /users/{user_id}/rider_data.json`
- `init_ride_for_ride()` -> `PATCH /users/{user_id}/rides/{ride_id}/rider_control/ride_status.json`
- `get_control_flags_for_ride()` -> `GET` on ride path or fallbacks
- `get_next_ride_id()` -> `GET /users/{user_id}/rides.json`
- `set_control_flag()` / `toggle_calculate_model_off()` -> `PATCH` ride/status or fallbacks
- `upload_ride_data_for_ride()` -> `PUT /users/{user_id}/rides/{ride_id}/ride_data.json` (or legacy path)
- `upload_ride_image_base64_for_ride()` -> `PUT /users/{user_id}/rides/{ride_id}/ride_images_base64/{timestamp_key}.json`

Recommended next steps
- Normalize CSV timestamps to integer ms and use those consistently as the keys for images.
- Replace base64 image storage with Firebase Storage and store URLs in `image_db_ref`.
- Cast CSV numeric fields to numbers before uploading ride_data to simplify downstream processing.
- Add a small test mode or mock to simulate `get_control_flags_for_ride()` changes for offline testing.

