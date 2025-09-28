import serial
import csv
import time
from datetime import datetime

# Replace with your serial port (usually /dev/serial0 or /dev/ttyAMA0)
GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600

# Output CSV file
csv_file = f"data/gps_{datetime.now().strftime('%m%d_%H%M%S')}.csv"

# Ensure data folder exists
import os
os.makedirs("data", exist_ok=True)

with serial.Serial(GPS_PORT, GPS_BAUD, timeout=2) as ser, open(csv_file, "w", newline="") as f:
    writer = csv.writer(f)
    # Write headers
    writer.writerow(["UTC Time", "Latitude", "N/S", "Longitude", "E/W", "Speed(knots)", "Course(deg)", "Date", "Valid"])

    print(f"Logging GPS data to {csv_file}... (Ctrl+C to stop)")
    
    # Clear any old data in buffer first
    ser.reset_input_buffer()
    
    gps_data_count = 0
    no_data_counter = 0
    max_no_data = 100  # Maximum consecutive empty reads before warning

    try:
        while True:
            try:
                # Check if data is available
                if ser.in_waiting == 0:
                    time.sleep(0.1)
                    no_data_counter += 1
                    if no_data_counter % max_no_data == 0:
                        print(f"No GPS data for {no_data_counter * 0.1:.1f} seconds...")
                    continue
                
                no_data_counter = 0  # Reset counter when data is available
                line = ser.readline().decode("ascii", errors="ignore").strip()
                
                if not line:
                    continue
                
                # Debug: print any GPS sentence received
                if line.startswith("$GP") or line.startswith("$GN"):
                    print(f"Debug GPS: {line[:60]}...")
                
                if line.startswith("$GPRMC"):
                    parts = line.split(",")
                    
                    # Ensure we have enough parts
                    if len(parts) < 10:
                        print(f"Incomplete GPRMC sentence: {len(parts)} parts")
                        continue
                    
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
                    
                    gps_data_count += 1
                    if gps_data_count % 10 == 0:
                        print(f"GPS data logged: {gps_data_count} records")
                        
            except UnicodeDecodeError as e:
                print(f"Unicode decode error: {e}")
                continue
            except Exception as e:
                print(f"Error processing GPS data: {e}")
                continue
                
    except KeyboardInterrupt:
        print("\nStopped logging.")