"""GPS utility functions for initializing and reading GPS data.

This module handles communication with a serial GPS device, specifically
parsing the $GPRMC NMEA sentence to extract latitude, longitude, and speed.
"""

import serial
import time
import subprocess
import os

# Configuration
GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600
KNOTS_TO_KMH = 1.852

# Debug flag - set to True for verbose output
DEBUG_GPS = True


def enable_gps_port():
    """Enable GPS port with proper permissions"""
    try:
        subprocess.run(['sudo', 'chmod', '666', '/dev/ttyS0'], check=True)
        if DEBUG_GPS:
            print("✅ GPS port permissions enabled")
        return True
    except subprocess.CalledProcessError as e:
        if DEBUG_GPS:
            print(f"❌ Failed to enable GPS port: {e}")
        return False


def init_gps_with_recovery(port=GPS_PORT, baud=GPS_BAUD, max_retries=10):
    """Initialize GPS with automatic port recovery"""
    for attempt in range(max_retries):
        try:
            # Enable port permissions before attempting connection
            if not enable_gps_port():
                print(f"⚠️ Could not enable port permissions (attempt {attempt + 1}/{max_retries})")
            
            gps_serial = serial.Serial(port, baud, timeout=1)
            if DEBUG_GPS:
                print(f"✅ GPS serial connection established on {port}")
            
            # Give GPS module time to initialize
            time.sleep(2)
            gps_serial.flushInput()
            return gps_serial
            
        except (serial.SerialException, OSError) as e:
            print(f"⚠️ GPS connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                print("🔄 Retrying in 2 seconds...")
                time.sleep(2)
    
    print("❌ Failed to establish GPS connection after all retries")
    return None


def _parse_lat_lon(coord_str, direction):
    """
    Parses a NMEA coordinate string (DDMM.MMMM or DDDMM.MMMM) into decimal degrees.
    """
    if not coord_str or not direction:
        return None

    try:
        coord_float = float(coord_str)
        
        # For latitude: DDMM.MMMM (degrees in first 2 digits)
        # For longitude: DDDMM.MMMM (degrees in first 3 digits)
        if direction in ['N', 'S']:  # Latitude
            degrees = int(coord_float // 100)
            minutes = coord_float - (degrees * 100)
        else:  # Longitude (E, W)
            degrees = int(coord_float // 100)
            minutes = coord_float - (degrees * 100)

        # Calculate decimal degrees
        decimal_degrees = degrees + (minutes / 60.0)

        # Apply direction (S or W are negative)
        if direction in ['S', 'W']:
            decimal_degrees *= -1

        return decimal_degrees
    except (ValueError, IndexError) as e:
        if DEBUG_GPS:
            print(f"Error parsing coordinate '{coord_str}' '{direction}': {e}")
        return None


def get_gps_data_with_recovery(gps_serial, retry_count=0, max_retries=3):
    """Enhanced GPS data reading with automatic port recovery"""
    try:
        if gps_serial.in_waiting == 0:
            return (None, None, None)
        
        lines_read = 0
        max_lines = 5
        
        while lines_read < max_lines and gps_serial.in_waiting > 0:
            line = gps_serial.readline().decode("ascii", errors="ignore").strip()
            lines_read += 1
            
            if line.startswith("$GPRMC"):
                parts = line.split(",")
                if len(parts) >= 10:
                    status = parts[2]
                    lat_raw = parts[3]
                    lat_dir = parts[4]
                    lon_raw = parts[5]
                    lon_dir = parts[6]
                    speed_knots = parts[7]
                    
                    if status == 'A' and lat_raw and lon_raw and lat_dir and lon_dir:
                        latitude = _parse_lat_lon(lat_raw, lat_dir)
                        longitude = _parse_lat_lon(lon_raw, lon_dir)
                        speed_kmh = float(speed_knots) * KNOTS_TO_KMH if speed_knots else 0.0

                        if latitude is not None and longitude is not None:
                            return (latitude, longitude, speed_kmh)
        
        return (None, None, None)

    except (serial.SerialException, OSError) as e:
        if DEBUG_GPS:
            print(f"⚠️ GPS serial error: {e}")
        
        if retry_count < max_retries:
            print(f"🔄 Attempting GPS recovery (attempt {retry_count + 1}/{max_retries})")
            
            # Try to re-enable port and reconnect
            if enable_gps_port():
                try:
                    gps_serial.close()
                    time.sleep(1)
                    gps_serial.open()
                    print("✅ GPS port reconnected successfully")
                    
                    # Recursive call with incremented retry count
                    return get_gps_data_with_recovery(gps_serial, retry_count + 1, max_retries)
                    
                except Exception as reconnect_error:
                    if DEBUG_GPS:
                        print(f"❌ GPS reconnection failed: {reconnect_error}")
            
        return (None, None, None)
    
    except Exception as e:
        if DEBUG_GPS:
            print(f"GPS read error: {e}")
        return (None, None, None)


def init_gps(port=GPS_PORT, baud=GPS_BAUD):
    """Legacy function - now uses recovery version"""
    return init_gps_with_recovery(port, baud)


def get_gps_data(gps_serial):
    """Legacy function - now uses recovery version"""
    return get_gps_data_with_recovery(gps_serial)


def test_gps_connection(port=GPS_PORT, baud=GPS_BAUD, duration=30):
    """
    Test GPS connection and print raw data for debugging.
    Run this function to diagnose GPS issues.
    """
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
