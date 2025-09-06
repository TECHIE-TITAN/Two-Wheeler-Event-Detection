import time
import board
import busio
import adafruit_vl53l0x

def init_lidar():
    """Initializes and returns a single Lidar sensor object."""
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        sensor = adafruit_vl53l0x.VL53L0X(i2c)
        return sensor
    except Exception as e:
        print(f"Error initializing Lidar: {e}")
        return None

def get_lidar_data(lidar_sensor):
    """
    Reads and returns the distance from the Lidar sensor in millimeters.
    Returns None if the reading fails.
    """
    if not lidar_sensor:
        return None
    try:
        return float(lidar_sensor.range)
    except Exception as e:
        print(f"Error reading Lidar data: {e}")
        return None
