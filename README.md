# Two-Wheeler-Event-Detection

Tasks Distribution:
  - Vansh Goyal: MPU 6500, GPS Neo-6M Module, LDR Sensor
  - Naman Aggarwal: SD Card Configuration
  - Shivek Gupta: Pi Cam Module 3 Config
  - Samarth Singla: LiDAR Sensor

To activate environment use:

  ```source .venv/bin/activate```

Also install RPi.GPIO in your global system using:

  ```sudo apt install python3-rpi.gpio```

To install libraries, run:

  ``` pip install -r requirements.txt```

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