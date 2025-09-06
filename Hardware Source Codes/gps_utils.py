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
    Reads and returns a 2-tuple of GPS latitude and longitude.
    Returns None if no valid data is found.
    """
    if not gps_serial:
        return None
    try:
        gps_data = gps_serial.readline().decode('ascii', errors='replace')
        if gps_data.startswith("$GPGGA") or gps_data.startswith("$GPRMC"):
            msg = pynmea2.parse(gps_data)
            return (msg.latitude, msg.longitude)
    except Exception as e:
        pass
    return None
