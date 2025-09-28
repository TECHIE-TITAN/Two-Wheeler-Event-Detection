import smbus2
import time
import math

# MPU6500 Registers
MPU_ADDR = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B
GYRO_XOUT_H = 0x43

bus = smbus2.SMBus(1)

# Global variables for storing zero-error bias
# They will be populated during calibration.
accel_bias = (0.0, 0.0, 0.0)
gyro_bias = (0.0, 0.0, 0.0)

def _read_raw_data(addr):
    """Reads raw 16-bit data from a given register address."""
    high = bus.read_byte_data(MPU_ADDR, addr)
    low = bus.read_byte_data(MPU_ADDR, addr + 1)
    value = ((high << 8) | low)
    if value > 32768:
        value -= 65536
    return value

def get_mpu_data_raw():
    """Reads a single raw accelerometer and gyroscope reading."""
    try:
        acc_x = _read_raw_data(ACCEL_XOUT_H)
        acc_y = _read_raw_data(ACCEL_XOUT_H + 2)
        acc_z = _read_raw_data(ACCEL_XOUT_H + 4)
        gyro_x = _read_raw_data(GYRO_XOUT_H)
        gyro_y = _read_raw_data(GYRO_XOUT_H + 2)
        gyro_z = _read_raw_data(GYRO_XOUT_H + 4)
        return (acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z)
    except Exception as e:
        print(f"Error reading raw MPU6500 data: {e}")
        return None

def calibrate_mpu():
    """
    Calculates the zero-error bias for the MPU6500 by averaging readings
    over the first second of operation.
    """
    global accel_bias, gyro_bias
    
    print("Calibrating MPU6500. Please keep the sensor still for 1 second...")
    
    acc_sum = [0.0, 0.0, 0.0]
    gyro_sum = [0.0, 0.0, 0.0]
    reading_count = 0
    start_time = time.time()
    
    while time.time() - start_time < 1.0:
        raw_data = get_mpu_data_raw()
        if raw_data:
            acc_sum[0] += raw_data[0]
            acc_sum[1] += raw_data[1]
            acc_sum[2] += raw_data[2]
            gyro_sum[0] += raw_data[3]
            gyro_sum[1] += raw_data[4]
            gyro_sum[2] += raw_data[5]
            reading_count += 1
            time.sleep(0.01) # Small delay to avoid overwhelming the bus

    if reading_count > 0:
        # Calculate the average (bias) and convert to standard units
        accel_bias = (
            (acc_sum[0] / reading_count) / 16384.0,
            (acc_sum[1] / reading_count) / 16384.0,
            (acc_sum[2] / reading_count) / 16384.0
        )
        gyro_bias = (
            (gyro_sum[0] / reading_count) / 131.0,
            (gyro_sum[1] / reading_count) / 131.0,
            (gyro_sum[2] / reading_count) / 131.0
        )
        print("Calibration complete.")
        print(f"Accel Bias: {accel_bias}")
        print(f"Gyro Bias: {gyro_bias}")
    else:
        print("Calibration failed: No readings found.")

def init_mpu():
    """Initializes the MPU6500 sensor and performs calibration."""
    try:
        bus.write_byte_data(MPU_ADDR, PWR_MGMT_1, 0)
        print("MPU6500 Initialized")
        calibrate_mpu()
    except Exception as e:
        print(f"Error initializing MPU6500: {e}")

def get_mpu_data():
    """
    Reads and returns a 6-tuple of MPU6500 accelerometer and gyroscope data.
    The values are converted to standard units (g and rad/s) and have the
    zero-error bias subtracted.
    """
    try:
        # Read and scale the raw data
        acc_x = _read_raw_data(ACCEL_XOUT_H) / 16384.0
        acc_y = _read_raw_data(ACCEL_XOUT_H + 2) / 16384.0
        acc_z = _read_raw_data(ACCEL_XOUT_H + 4) / 16384.0
        gyro_x = _read_raw_data(GYRO_XOUT_H) / 131.0
        gyro_y = _read_raw_data(GYRO_XOUT_H + 2) / 131.0
        gyro_z = _read_raw_data(GYRO_XOUT_H + 4) / 131.0
        
        # Subtract the calculated bias
        accel_data_calibrated = (
            acc_x - accel_bias[0],
            acc_y - accel_bias[1],
            acc_z - accel_bias[2]
        )
        gyro_data_calibrated = (
            gyro_x - gyro_bias[0],
            gyro_y - gyro_bias[1],
            gyro_z - gyro_bias[2]
        )
        
        return accel_data_calibrated + gyro_data_calibrated
    except Exception as e:
        print(f"Error reading MPU6500 data: {e}")
        return (None, None, None, None, None, None)
