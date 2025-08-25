# Connections (I²C):

# VCC → 3.3V (or 5V, but use 3.3V if possible for logic compatibility)

# GND → GND

# SDA → GPIO 2 (pin 3, SDA)

# SCL → GPIO 3 (pin 5, SCL)

# XSHUT → Any GPIO (used to change addresses when you have multiple sensors)

# For 3 sensors (Front, Left, Right) you’ll connect:

# SDA + SCL shared between all sensors (I²C bus).

# Each sensor’s XSHUT pin → separate GPIO (so you can bring them out of reset one by one to assign new addresses).

import time
import board
import busio
import digitalio
import adafruit_vl53l0x

# I2C setup
i2c = busio.I2C(board.SCL, board.SDA)

# XSHUT pins for 3 sensors (GPIO17, GPIO27, GPIO22 for example)
from gpiozero import OutputDevice
xshut_pins = [OutputDevice(17), OutputDevice(27), OutputDevice(22)]

# Shut down all sensors
for x in xshut_pins:
    x.off()

time.sleep(0.5)

sensors = []
addresses = [0x30, 0x31, 0x32]  # new I2C addresses for front, left, right

# Power up each sensor one by one, assign new I2C address
for i, x in enumerate(xshut_pins):
    x.on()
    time.sleep(0.5)
    sensor = adafruit_vl53l0x.VL53L0X(i2c)
    sensor.set_address(addresses[i])
    sensors.append(sensor)

print("All sensors initialized!")

# ---------------------------------------------------
# SAFETY CHECK LOGIC
# ---------------------------------------------------
def check_braking_safety(front_dist):
    SAFE_DISTANCE_MM = 1500  # 1.5 m threshold, tune experimentally
    if front_dist < SAFE_DISTANCE_MM:
        return "UNSAFE: Too Close!"
    else:
        return "SAFE: Proper Distance"

# ---------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------
while True:
    # Read all sensors
    distances = [s.range for s in sensors]  # [front, left, right]
    
    braking = True  # <-- Replace this with IMU flag from teammate like braking = imu_detects_braking()
    
    if braking:
        status = check_braking_safety(distances[0])  # check front only
        print(f"Front: {distances[0]} mm | {status}")
    else:
        print(f"Front: {distances[0]} mm | Left: {distances[1]} mm | Right: {distances[2]} mm")
    
    time.sleep(0.1)
