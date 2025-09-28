import serial
import csv
from datetime import datetime

# Replace with your serial port (usually /dev/serial0 or /dev/ttyAMA0)
GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600

# Output CSV file
csv_file = f"data/gps_{datetime.now().strftime('%m%d_%H%M%S')}.csv"

# Ensure data folder exists
import os
os.makedirs("data", exist_ok=True)

with serial.Serial(GPS_PORT, GPS_BAUD, timeout=1) as ser, open(csv_file, "w", newline="") as f:
    writer = csv.writer(f)
    # Write headers
    writer.writerow(["UTC Time", "Latitude", "N/S", "Longitude", "E/W", "Speed(knots)", "Course(deg)", "Date", "Valid"])

    print(f"Logging GPS data to {csv_file}... (Ctrl+C to stop)")

    try:
        while True:
            line = ser.readline().decode("ascii", errors="ignore").strip()
            if line.startswith("$GPRMC"):
                parts = line.split(",")
                # GPRMC fields
                utc_time = parts[1]
                valid = parts[2]
                latitude = parts[3]
                ns = parts[4]
                longitude = parts[5]
                ew = parts[6]
                speed = parts[7]
                course = parts[8]
                date = parts[9]

                # Print to terminal
                print(f"{utc_time} {latitude}{ns} {longitude}{ew} {speed}kn {course}deg Valid:{valid}")

                # Save to CSV
                writer.writerow([utc_time, latitude, ns, longitude, ew, speed, course, date, valid])
                f.flush()
    except KeyboardInterrupt:
        print("\nStopped logging.")