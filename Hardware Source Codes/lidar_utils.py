# Import necessary libraries
import time
import board
import adafruit_vl53l0x

# --- Initialization ---
# Initialize the I2C bus on the Raspberry Pi
# board.I2C() creates an I2C object using the default SCL and SDA pins
i2c = board.I2C()

# Create a VL53L0X sensor object, passing it the I2C bus object
# This object is our interface to the sensor
try:
    vl53 = adafruit_vl53l0x.VL53L0X(i2c)
    print("VL53L0X sensor initialized.")
except Exception as e:
    print(f"Error initializing sensor: {e}")
    print("Please check wiring and I2C connection.")
    exit()

# You can optionally adjust the timing budget. A higher budget means
# more accurate measurements but a slower read time.
# The default is 33ms. Options: 20, 33, 50, 100, 200, 500 (in ms)
# vl53.measurement_timing_budget = 200000 # 200ms budget for high accuracy

# --- Main Loop ---
# This loop will run forever, continuously taking measurements
try:
    print("Starting distance measurements. Press Ctrl+C to stop.")
    while True:
        # Get the distance measurement. The .range property returns the
        # distance in millimeters (mm).
        distance = vl53.range

        # Print the result
        print(f"Range: {distance} mm")

        # Wait a short period (e.g., 0.1 seconds) before the next reading
        time.sleep(0.1)

# This except block catches the KeyboardInterrupt exception, which is
# raised when you press Ctrl+C to stop the script.
except KeyboardInterrupt:
    print("\nStopping measurements.")