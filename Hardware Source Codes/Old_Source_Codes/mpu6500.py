import smbus2
import time
import math

# MPU6500 Registers
MPU_ADDR = 0x68
PWR_MGMT_1 = 0x6B
ACCEL_XOUT_H = 0x3B
GYRO_XOUT_H  = 0x43

bus = smbus2.SMBus(1)

def init_mpu():
    # Wake up MPU6500
    bus.write_byte_data(MPU_ADDR, PWR_MGMT_1, 0)
    print("MPU6500 Initialized")

def read_raw_data(addr):
    # Read two bytes of data
    high = bus.read_byte_data(MPU_ADDR, addr)
    low = bus.read_byte_data(MPU_ADDR, addr+1)
    value = ((high << 8) | low)
    if value > 32768:  # Convert to signed
        value -= 65536
    return value

def get_accel_gyro():
    # Accelerometer
    acc_x = read_raw_data(ACCEL_XOUT_H) / 16384.0
    acc_y = read_raw_data(ACCEL_XOUT_H+2) / 16384.0
    acc_z = read_raw_data(ACCEL_XOUT_H+4) / 16384.0

    # Gyroscope
    gyro_x = read_raw_data(GYRO_XOUT_H) / 131.0
    gyro_y = read_raw_data(GYRO_XOUT_H+2) / 131.0
    gyro_z = read_raw_data(GYRO_XOUT_H+4) / 131.0

    return {
        "accel": (acc_x, acc_y, acc_z),
        "gyro": (gyro_x, gyro_y, gyro_z)
    }

if __name__ == "__main__":
    init_mpu()
    while True:
        data = get_accel_gyro()
        print(f"Accel: {data['accel']}  Gyro: {data['gyro']}")
        time.sleep(0.5)
