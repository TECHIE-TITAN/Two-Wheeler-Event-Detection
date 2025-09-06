import smbus2
import time
import math

# MPU6500 Registers
MPU_ADDR = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B
GYRO_XOUT_H = 0x43

bus = smbus2.SMBus(1)

def init_mpu():
    """Initializes the MPU6500 sensor."""
    try:
        bus.write_byte_data(MPU_ADDR, PWR_MGMT_1, 0)
        print("MPU6500 Initialized")
    except Exception as e:
        print(f"Error initializing MPU6500: {e}")

def _read_raw_data(addr):
    """Reads raw 16-bit data from a given register address."""
    high = bus.read_byte_data(MPU_ADDR, addr)
    low = bus.read_byte_data(MPU_ADDR, addr + 1)
    value = ((high << 8) | low)
    if value > 32768:
        value -= 65536
    return value

def get_mpu_data():
    """
    Reads and returns a 6-tuple of MPU6500 accelerometer and gyroscope data.
    The values are converted to standard units (g and rad/s).
    """
    try:
        acc_x = _read_raw_data(ACCEL_XOUT_H) / 16384.0
        acc_y = _read_raw_data(ACCEL_XOUT_H + 2) / 16384.0
        acc_z = _read_raw_data(ACCEL_XOUT_H + 4) / 16384.0
        gyro_x = _read_raw_data(GYRO_XOUT_H) / 131.0
        gyro_y = _read_raw_data(GYRO_XOUT_H + 2) / 131.0
        gyro_z = _read_raw_data(GYRO_XOUT_H + 4) / 131.0
        return (acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z)
    except Exception as e:
        print(f"Error reading MPU6500 data: {e}")
        return (None, None, None, None, None, None)
