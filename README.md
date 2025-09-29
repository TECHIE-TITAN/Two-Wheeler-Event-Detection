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

This repository contains code for a Raspberry Pi-based two-wheeler telemetry and event-capture system. The Pi reads MPU/GPS data, logs it to `sensor_data.csv`, and pushes telemetry to Firebase Realtime Database. When a ride is deactivated remotely, the Pi uploads the ride's CSV rows as raw_data and computes a simple processed summary. Images are stored locally and not uploaded.

Key files

- `Hardware Source Codes/main2.py`: primary data collector and Firebase uploader.
- `Hardware Source Codes/firebase_uploader.py`: helper functions for Firebase authentication and read/write operations.

Control flags and ride-scoped model

Rides are stored under `users/<user_id>/rides/<ride_id>/...`. Ride IDs are auto-incremented integers; if no rides exist the first ride ID will be `0`.

Primary DB paths used by the Pi:

- `users/<user_id>/rides/<ride_id>/ride_control`:
  - `is_active` (bool) — when true Pi collects and uploads telemetry; when it flips to false the Pi uploads raw_data and a processed summary.
- `users/<user_id>/rides/<ride_id>/raw_data` (PUT) — full array of CSV rows (no `image_path` field)
- `users/<user_id>/rider_data` (PATCH) — current telemetry snapshot for dashboard

Legacy paths (kept for backwards compatibility):

- `users/<user_id>/rider_control`
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

- Local CSV rows include an `image_path` for frames saved on disk. This field is stripped and not uploaded to Firebase.
- CSV rows are uploaded via `csv.DictReader` (string values). Ask me to convert fields to numeric types if required.

---

# Firebase uploader analysis

This section documents a comprehensive analysis of `Hardware Source Codes/firebase_uploader.py` and how `Hardware Source Codes/main2.py` interacts with it. It lists data points uploaded, DB paths, example JSON shapes, sources of values, edge cases, and recommended improvements.

## What the uploader does

- Authenticates to Firebase using email/password (Identity Toolkit) and manages token refresh.
- Writes telemetry and control flags to Firebase Realtime Database via REST API (`requests`).
- Uploads full ride CSV data; images are not uploaded by the Pi in the current configuration.

## Data points written to Firebase (detailed)

1) Rider data summary (PATCH -> `/users/{user_id}/rider_data`)
- `speed`: number (float) — current speed estimate (GPS preferred, accel fallback)
- `speed_limit`: number or null — `latest_speed_limit` from `speed_limit_utils.get_speed_limit`
- `active_warnings`: object (map) — result of `build_speeding_warning(speed, speed_limit)`; empty object when no warnings
- `mpu`: nested object (written by `update_rider_mpu`):
  - `acc_x`, `acc_y`, `acc_z`: float
  - `gyro_x`, `gyro_y`, `gyro_z`: float
  - `timestamp`: integer (ms)

2) Ride control status (ride-scoped)
- Path: `/users/{user_id}/rides/{ride_id}/ride_control` (PATCH/GET)
- Keys:
  - `is_active`: boolean
  - `start_time`: integer (ms)

3) Ride raw data
- Path for ride rows upload: `/users/{user_id}/rides/{ride_id}/raw_data` (PUT)
  - Value: array of row objects (replaces existing node)
  - Row fields (from CSV via `main2.py`), with `image_path` stripped before upload:
    - `timestamp` (ms), `acc_x`, `acc_y`, `acc_z`, `gyro_x`, `gyro_y`, `gyro_z`, `latitude`, `longitude`, `speed`, `speed_limit`

## Example JSON shapes

Rider data (`/users/{user_id}/rider_data`):

{
  "speed": 45.2,
  "speed_limit": 40.0,
  "active_warnings": {
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

Ride data (ride-scoped, `/users/{user_id}/rides/{ride_id}/raw_data`):

[
  {
    "timestamp": "1700000000000",
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

## Where values come from in the code

- `main2.py` constructs CSV rows (including local `image_path`) and calls uploader functions.
- GPS values (latitude, longitude, speed) come from `gps_utils.get_gps_data()` and are stored in `latest_gps`.
- MPU values (acc_x..gyro_z) come from `mpu_utils.get_mpu_data()` and are stored in `latest_mpu`.
- `speed_limit` is retrieved by `speed_limit_utils.get_speed_limit(lat, lon, OLA_MAPS_API_KEY)`.
- On `is_active` -> `false`, `main2.py` reads the CSV, strips `image_path`, uploads to `/raw_data` and sends a processed summary.

## Edge cases and notes

- Many numeric fields can be `None` (e.g., when GPS has no fix). Realtime DB will store `null` when a JSON `null` is sent.
- `update_rider_mpu` is only called when all MPU values are present.
- `upload_ride_raw_data_for_ride` uses PUT and will overwrite the existing `raw_data` node.