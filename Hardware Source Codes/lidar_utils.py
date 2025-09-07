import time
import board
import digitalio
import adafruit_vl53l0x

# --- Sensor and I2C Configuration ---

# Define the I2C bus
i2c = board.I2C()

# Define the GPIO pins connected to the XSHUT pin of each sensor
xshut_pins = [
    board.D4,   # Pin for sensor 1
    board.D17   # Pin for sensor 2
    # board.D27 has been removed
]

# Create a list to hold the sensor objects
sensors = []

# --- Sensor Initialization ---

# Create a digitalio object for each XSHUT pin and set it to output
shutdown_pins = []
for pin in xshut_pins:
    shutdown_pin = digitalio.DigitalInOut(pin)
    shutdown_pin.direction = digitalio.Direction.OUTPUT
    shutdown_pin.value = False  # Set to low/off
    shutdown_pins.append(shutdown_pin)

# New I2C addresses for the sensors
new_addresses = [0x30, 0x31] # Address for Sensor 3 (0x32) has been removed

# Sequentially enable each sensor and change its I2C address
print("Initializing 2 sensors...")
for i, shutdown_pin in enumerate(shutdown_pins):
    # Turn on the current sensor by setting its XSHUT pin high
    shutdown_pin.value = True
    time.sleep(0.1)  # Give the sensor time to wake up

    try:
        # Create a sensor instance with the default I2C address
        sensor = adafruit_vl53l0x.VL53L0X(i2c)
        
        # Change the I2C address of the sensor
        new_address = new_addresses[i]
        sensor.set_address(new_address)
        
        # Add the configured sensor to our list
        sensors.append(sensor)
        print(f"Sensor {i+1} initialized with new address {hex(new_address)}")
        
    except Exception as e:
        print(f"Failed to initialize sensor {i+1}: {e}")
        exit()

# Check if all sensors were initialized
if len(sensors) != len(xshut_pins):
    print("Not all sensors were initialized. Exiting.")
    exit()


# --- Main Loop ---
def get_all_distances():
    """Reads distance from all sensors and returns them in a list."""
    readings = []
    for i, sensor in enumerate(sensors):
        try:
            distance = sensor.range
            readings.append(distance)
        except Exception as e:
            print(f"Error reading from sensor {i+1}: {e}")
            readings.append(-1) # Use -1 to indicate an error
    return readings

try:
    print("\nStarting measurements. Press Ctrl+C to stop.")
    while True:
        # Get the distances from all sensors as a list
        distances_list = get_all_distances()
        
        # Convert the list to a tuple
        distances_tuple = tuple(distances_list)
        
        # Print the tuple of readings
        print(f"Distances (mm): {distances_tuple}")
        
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopping measurements.")