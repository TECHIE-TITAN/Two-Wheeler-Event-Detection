"""GPS utility functions for initializing and reading GPS data.

This module handles communication with a serial GPS device, specifically
parsing the $GPRMC NMEA sentence to extract latitude, longitude, and speed.
"""

import serial

# Configuration
GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600
KNOTS_TO_KMH = 1.852


def init_gps(port=GPS_PORT, baud=GPS_BAUD):
    """Initializes and opens the serial connection to the GPS module."""
    try:
        gps_serial = serial.Serial(port, baud, timeout=0.5)
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
        # Try reading a few lines to find a valid one
        for _ in range(5):
            line = gps_serial.readline().decode("ascii", errors="ignore").strip()

            if line.startswith("$GPRMC"):
                parts = line.split(",")
                # Check for basic validity: enough parts and 'A' status
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

        # If no valid $GPRMC sentence was found after trying
        return (None, None, None)

    except (serial.SerialException, ValueError, IndexError) as e:
        print(f"Error reading or parsing GPS data: {e}")
        return (None, None, None)
