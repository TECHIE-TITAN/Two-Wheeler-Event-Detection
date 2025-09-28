"""GPS utility functions for initializing and reading GPS data.

This module handles communication with a serial GPS device, specifically
parsing the $GPRMC NMEA sentence to extract latitude, longitude, and speed.
"""

import serial
import time

# === CONFIGURATION ===
GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600
KNOTS_TO_KMH = 1.852
DEBUG_GPS = True

def init_gps(port=GPS_PORT, baud=GPS_BAUD):
    """Initializes and opens the serial connection to the GPS module."""
    try:
        gps_serial = serial.Serial(port, baud, timeout=1)
        print(f"GPS serial port {port} opened successfully.")
        
        time.sleep(2)
        gps_serial.flushInput()
        
        return gps_serial
    except serial.SerialException as e:
        print(f"Error: Could not open serial port {port}: {e}")
        print("Possible solutions:")
        print("1. Check if GPS module is properly connected")
        print("2. Try alternative ports: /dev/ttyAMA0, /dev/ttyUSB0")
        print("3. Check if serial is enabled: sudo raspi-config")
        print("4. Check permissions: sudo usermod -a -G dialout $USER")
        raise

def _parse_lat_lon(coord_str, direction):
    """Parses a NMEA coordinate string (DDMM.MMMM or DDDMM.MMMM) into decimal degrees."""
    if not coord_str or not direction:
        return None

    try:
        coord_float = float(coord_str)
        
        if direction in ['N', 'S']:
            degrees = int(coord_float // 100)
            minutes = coord_float - (degrees * 100)
        else:
            degrees = int(coord_float // 100)
            minutes = coord_float - (degrees * 100)

        decimal_degrees = degrees + (minutes / 60.0)

        if direction in ['S', 'W']:
            decimal_degrees *= -1

        return decimal_degrees
    except (ValueError, IndexError) as e:
        if DEBUG_GPS:
            print(f"Error parsing coordinate '{coord_str}' '{direction}': {e}")
        return None

def get_gps_data(gps_serial):
    """Reads the GPS serial port, finds a valid $GPRMC sentence, and returns parsed data.
    
    Returns:
        A tuple (latitude, longitude, speed_kmh) or (None, None, None) if no valid data is found.
    """
    try:
        lines_read = 0
        max_lines = 10
        
        while lines_read < max_lines:
            if gps_serial.in_waiting == 0:
                time.sleep(0.1)
                lines_read += 1
                continue
                
            line = gps_serial.readline().decode("ascii", errors="ignore").strip()
            lines_read += 1
            
            if DEBUG_GPS and line:
                print(f"GPS Raw: {line}")

            if line.startswith("$GPRMC"):
                parts = line.split(",")
                
                if DEBUG_GPS:
                    print(f"GPRMC parts count: {len(parts)}")
                    if len(parts) > 2:
                        print(f"GPS Status: {parts[2]} (A=Active, V=Void)")
                
                if len(parts) >= 10:
                    utc_time = parts[1]
                    status = parts[2]
                    lat_raw = parts[3]
                    lat_dir = parts[4]
                    lon_raw = parts[5]
                    lon_dir = parts[6]
                    speed_knots = parts[7]
                    course = parts[8]
                    date = parts[9]
                    
                    if DEBUG_GPS:
                        print(f"GPS Data - Status: {status}, Lat: {lat_raw}{lat_dir}, Lon: {lon_raw}{lon_dir}, Speed: {speed_knots}kn")
                    
                    if status == 'A' and lat_raw and lon_raw and lat_dir and lon_dir:
                        latitude = _parse_lat_lon(lat_raw, lat_dir)
                        longitude = _parse_lat_lon(lon_raw, lon_dir)
                        speed_kmh = float(speed_knots) * KNOTS_TO_KMH if speed_knots else 0.0

                        if latitude is not None and longitude is not None:
                            if DEBUG_GPS:
                                print(f"GPS Parsed - Lat: {latitude:.6f}, Lon: {longitude:.6f}, Speed: {speed_kmh:.2f} km/h")
                            return (latitude, longitude, speed_kmh)
                    elif status == 'V':
                        if DEBUG_GPS:
                            print("GPS Status: No valid fix (searching for satellites...)")
                    else:
                        if DEBUG_GPS:
                            print(f"GPS Status: Invalid data - Status: {status}, Lat: {lat_raw}, Lon: {lon_raw}")

        if DEBUG_GPS:
            print(f"No valid GPS data found after reading {lines_read} lines")
        return (None, None, None)

    except (serial.SerialException, ValueError, IndexError) as e:
        print(f"Error reading or parsing GPS data: {e}")
        return (None, None, None)

def test_gps_connection(port=GPS_PORT, baud=GPS_BAUD, duration=30):
    """Test GPS connection and print raw data for debugging."""
    print(f"Testing GPS connection on {port} at {baud} baud for {duration} seconds...")
    print("This will show raw NMEA sentences from GPS module.")
    print("Look for $GPRMC sentences with status 'A' for valid fixes.")
    print("-" * 60)
    
    try:
        with serial.Serial(port, baud, timeout=1) as gps_serial:
            start_time = time.time()
            sentence_count = 0
            gprmc_count = 0
            valid_fixes = 0
            
            while (time.time() - start_time) < duration:
                try:
                    line = gps_serial.readline().decode("ascii", errors="ignore").strip()
                    if line:
                        sentence_count += 1
                        print(f"[{sentence_count:3d}] {line}")
                        
                        if line.startswith("$GPRMC"):
                            gprmc_count += 1
                            parts = line.split(",")
                            if len(parts) >= 3 and parts[2] == 'A':
                                valid_fixes += 1
                                print(f"      *** VALID FIX #{valid_fixes} ***")
                                
                except UnicodeDecodeError:
                    print("     [Unicode decode error - skipping line]")
                    
            print("-" * 60)
            print(f"Test completed:")
            print(f"Total sentences received: {sentence_count}")
            print(f"GPRMC sentences: {gprmc_count}")
            print(f"Valid GPS fixes: {valid_fixes}")
            
            if sentence_count == 0:
                print("ERROR: No data received from GPS module!")
                print("Check connections and power.")
            elif gprmc_count == 0:
                print("ERROR: No GPRMC sentences found!")
                print("GPS module may not be configured correctly.")
            elif valid_fixes == 0:
                print("WARNING: No valid GPS fixes!")
                print("GPS may need more time to acquire satellites.")
                print("Try testing outdoors with clear sky view.")
                
    except serial.SerialException as e:
        print(f"ERROR: Could not open serial port: {e}")
        print("Check if GPS module is connected and port is correct.")
