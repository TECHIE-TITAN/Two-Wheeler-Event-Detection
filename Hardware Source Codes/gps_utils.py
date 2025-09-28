"""GPS utility functions for initializing and reading GPS data.

This module handles communication with a serial GPS device, specifically
parsing the $GPRMC NMEA sentence to extract latitude, longitude, and speed.
"""

import serial
import glob
import os

# Configuration
GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600
KNOTS_TO_KMH = 1.852


def find_gps_port():
    """Try to find available GPS serial ports."""
    possible_ports = [
        "/dev/serial0",    # Raspberry Pi GPIO UART
        "/dev/ttyS0",      # Standard serial port
        "/dev/ttyAMA0",    # Raspberry Pi UART
        "/dev/ttyUSB0",    # USB GPS dongles
        "/dev/ttyUSB1",
        "/dev/ttyACM0",    # Some GPS modules
        "/dev/ttyACM1"
    ]
    
    available_ports = []
    for port in possible_ports:
        if os.path.exists(port):
            available_ports.append(port)
    
    # Also check for any other USB serial devices
    usb_ports = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    for port in usb_ports:
        if port not in available_ports:
            available_ports.append(port)
    
    return available_ports


def init_gps(port=None, baud=GPS_BAUD):
    """Initializes and opens the serial connection to the GPS module."""
    if port is None:
        # Try to find available ports
        available_ports = find_gps_port()
        if not available_ports:
            print("No serial ports found for GPS")
            raise serial.SerialException("No serial ports available")
        
        print(f"Available serial ports: {available_ports}")
        
        # Try each port
        for test_port in available_ports:
            try:
                print(f"Trying GPS on port {test_port}...")
                gps_serial = serial.Serial(test_port, baud, timeout=1.0)
                
                # Test if we can read some data
                test_data = None
                for _ in range(5):
                    try:
                        line = gps_serial.readline().decode("ascii", errors="ignore").strip()
                        if line.startswith("$GP") or line.startswith("$GN"):
                            test_data = line
                            break
                    except:
                        continue
                
                if test_data:
                    print(f"GPS found on port {test_port}")
                    print(f"Sample GPS data: {test_data[:50]}...")
                    return gps_serial
                else:
                    print(f"No GPS data on {test_port}, trying next port...")
                    gps_serial.close()
                    
            except serial.SerialException as e:
                print(f"Could not open {test_port}: {e}")
                continue
        
        raise serial.SerialException("GPS not found on any available port")
    else:
        # Use specified port
        try:
            gps_serial = serial.Serial(port, baud, timeout=1.0)
            print(f"GPS serial port {port} opened successfully.")
            return gps_serial
        except serial.SerialException as e:
            print(f"Error: Could not open serial port {port}: {e}")
            raise


def _parse_lat_lon(coord_str, direction):
    """
    Parses a NMEA coordinate string (DDMM.MMMM) into decimal degrees.
    """
    if not coord_str:
        return None

    try:
        # Get the degrees part
        degrees = float(coord_str[:2]) if len(coord_str) > 2 else float(coord_str)
        # Get the minutes part
        minutes = float(coord_str[2:]) if len(coord_str) > 2 else 0.0

        # Calculate decimal degrees
        decimal_degrees = degrees + (minutes / 60.0)

        # Apply direction (S or W are negative)
        if direction in ['S', 'W']:
            decimal_degrees *= -1

        return decimal_degrees
    except (ValueError, IndexError):
        return None


def get_gps_data(gps_serial):
    """
    Reads the GPS serial port, finds a valid $GPRMC sentence, and returns
    parsed data.

    Returns:
        A tuple (latitude, longitude, speed_kmh) or (None, None, None) if
        no valid data is found.
    """
    try:
        if not gps_serial.is_open:
            print("GPS serial port is closed")
            return (None, None, None)
            
        # Check if data is available
        if gps_serial.in_waiting == 0:
            # No data waiting, return None instead of blocking
            return (None, None, None)
        
        # Try reading a few lines to find a valid one
        lines_read = 0
        max_lines = 10  # Limit to prevent infinite loops
        
        while lines_read < max_lines and gps_serial.in_waiting > 0:
            try:
                line = gps_serial.readline().decode("ascii", errors="ignore").strip()
                lines_read += 1
                
                if not line:  # Empty line
                    continue
                    
                # Look for GPRMC or GNRMC sentences (more common in modern GPS modules)
                if line.startswith("$GPRMC") or line.startswith("$GNRMC"):
                    parts = line.split(",")
                    # Check for basic validity: enough parts and 'A' status (active)
                    if len(parts) > 9 and parts[2] == 'A':
                        lat_raw = parts[3]
                        lat_dir = parts[4]
                        lon_raw = parts[5]
                        lon_dir = parts[6]
                        speed_knots = parts[7]

                        # Parse coordinates and speed
                        latitude = _parse_lat_lon(lat_raw, lat_dir)
                        longitude = _parse_lat_lon(lon_raw, lon_dir)
                        speed_kmh = float(speed_knots) * KNOTS_TO_KMH if speed_knots else 0.0

                        if latitude is not None and longitude is not None:
                            # Return the first valid data found
                            return (latitude, longitude, speed_kmh)
                    elif len(parts) > 2 and parts[2] == 'V':
                        # GPS fix not available (V = void, A = active)
                        # This is normal when GPS doesn't have satellite lock
                        pass
                        
                # Debug: print other GPS sentences occasionally
                elif line.startswith("$GP") or line.startswith("$GN"):
                    # Uncomment next line for debugging GPS sentences
                    # print(f"GPS debug: {line[:60]}...")
                    pass
                    
            except UnicodeDecodeError:
                # Skip lines that can't be decoded
                continue
            except Exception as e:
                print(f"Error processing GPS line: {e}")
                continue

        # If no valid $GPRMC/$GNRMC sentence was found
        return (None, None, None)

    except serial.SerialException as e:
        print(f"GPS Serial error: {e}")
        return (None, None, None)
    except Exception as e:
        print(f"Error reading or parsing GPS data: {e}")
        return (None, None, None)
