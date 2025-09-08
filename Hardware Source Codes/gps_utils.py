import serial
import pynmea2

def init_gps(port="/dev/serial0", baudrate=9600):
    """Initializes and returns a serial connection for the GPS module."""
    try:
        return serial.Serial(port, baudrate=baudrate, timeout=1)
    except Exception as e:
        print(f"Error initializing GPS: {e}")
        return None

def get_gps_data(gps_serial):
    """
    Reads and returns a 3-tuple of GPS latitude, longitude, and speed (in km/h if available).
    Returns None if no valid data is found.
    """
    if not gps_serial:
        return None
    try:
        gps_data = gps_serial.readline().decode('ascii', errors='replace')
        if gps_data.startswith("$GPGGA") or gps_data.startswith("$GPRMC"):
            msg = pynmea2.parse(gps_data)
            latitude = msg.latitude
            longitude = msg.longitude
            # Speed is only available in GPRMC messages (in knots)
            speed = None
            if hasattr(msg, 'spd_over_grnd') and msg.spd_over_grnd is not None:
                try:
                    speed = float(msg.spd_over_grnd) * 1.852  # Convert knots to km/h
                except Exception:
                    speed = None
            return (latitude, longitude, speed)
    except Exception as e:
        pass
    return None
