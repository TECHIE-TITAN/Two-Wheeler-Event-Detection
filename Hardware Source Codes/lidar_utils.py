import time
import board
import digitalio
import adafruit_vl53l0x
import bitbangio  # Import the bitbangio library

# --- Sensor and I2C Configuration ---

# V V V V V V V V V V V V V V V V V V V V V V
# -- THIS IS THE ONLY SECTION THAT CHANGES --

# Define the custom GPIO pins for our new software I2C bus
scl_pin = board.D24
sda_pin = board.D23

# Initialize the software I2C bus on our chosen pins
i2c = bitbangio.I2C(scl_pin, sda_pin)

# -- END OF CHANGED SECTION --
# ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^ ^


# Define the GPIO pins connected to the XSHUT pin of each sensor
# The rest of the code remains exactly the same!
xshut_pins = [
    board.D4,   # Pin for sensor 1
    board.D17,  # Pin for sensor 2
    board.D27   # Pin for sensor 3
]

# Create a list to hold the sensor objects
sensors = []

# --- Sensor Initialization ---

# Create a digitalio object for each XSHUT pin and set it to output
shutdown_pins = []
for pin in xshut_pins:
    shutdown_pin = digitalio.DigitalInOut(pin)
    shutdown_pin.direction = digitalio.Direction.OUTPUT
    shutdown_pin.value = False
    shutdown_pins.append(shutdown_pin)

# New I2C addresses for the sensors
new_addresses = [0x30, 0x31, 0x32]

# Sequentially enable each sensor and change its I2C address
print("Initializing sensors on software I2C bus...")
for i, shutdown_pin in enumerate(shutdown_pins):
    shutdown_pin.value = True
    time.sleep(0.1)

    try:
        sensor = adafruit_vl53l0x.VL53L0X(i2c)
        sensor.set_address(new_addresses[i])
        sensors.append(sensor)
        print(f"Sensor {i+1} initialized with new address {hex(new_addresses[i])}")
        
    except Exception as e:
        print(f"Failed to initialize sensor {i+1}: {e}")
        exit()

if len(sensors) != len(xshut_pins):
    print("Not all sensors were initialized. Exiting.")
    exit()


# --- Main Loop ---
def get_all_distances():
    readings = []
    for i, sensor in enumerate(sensors):
        try:
            distance = sensor.range
            readings.append(distance)
        except Exception as e:
            print(f"Error reading from sensor {i+1}: {e}")
            readings.append(-1)
    return readings

try:
    print("\nStarting measurements. Press Ctrl+C to stop.")
    while True:
        distances_tuple = tuple(get_all_distances())
        print(f"Distances (mm): {distances_tuple}")
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopping measurements.")