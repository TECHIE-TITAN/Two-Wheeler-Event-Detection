import serial
import pynmea2

def setup(port="/dev/serial0", baudrate=9600):
    return serial.Serial(port, baudrate=baudrate, timeout=1)

def get_gps_data(gps_serial):
    try:
        gps_data = gps_serial.readline().decode('ascii', errors='replace')
        if gps_data.startswith("$GPGGA") or gps_data.startswith("$GPRMC"):
            msg = pynmea2.parse(gps_data)
            return {
                "latitude": msg.latitude,
                "longitude": msg.longitude
            }
    except Exception:
        pass
    return None
