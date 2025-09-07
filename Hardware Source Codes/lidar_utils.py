import time
import board
import digitalio
import adafruit_vl53l0x
import busio

# --- Sensor and I2C Configuration ---

print("Initializing I2C for VL53L0X sensors...")

# Try to use I2C-1 interface which uses different pins
# I2C-1 typically uses GPIO 2 (SDA) and GPIO 3 (SCL) on Pi 4
# But we can also try I2C-3 or other interfaces

try:
    # Method 1: Try using board.I2C() with port 1
    import board
    
    # Check if board has multiple I2C interfaces
    if hasattr(board, 'I2C'):
        # Try different I2C buses
        try:
            # For Raspberry Pi, try I2C-3 which might use different pins
            # GPIO 2 and 3 are I2C-1, let's try to use I2C-3 (if available)
            print("Trying alternative I2C interface...")
            
            # Create I2C using explicit pins that are known to work
            # Use GPIO 5 (SCL) and GPIO 6 (SDA) - these are less commonly used
            import busio
            scl_pin = board.D5   # GPIO 5 (Physical Pin 29)
            sda_pin = board.D6   # GPIO 6 (Physical Pin 31)
            
            # Try to create I2C with lower frequency to avoid issues
            i2c = busio.I2C(scl_pin, sda_pin, frequency=100000)
            print("SUCCESS: Using I2C on GPIO 5 (SCL, Pin 29) and GPIO 6 (SDA, Pin 31)")
            
        except Exception as e1:
            print(f"GPIO 5/6 failed: {e1}")
            
            # Try GPIO 8 (SCL) and GPIO 9 (SDA)
            try:
                scl_pin = board.D8   # GPIO 8 (Physical Pin 24)
                sda_pin = board.D9   # GPIO 9 (Physical Pin 21) 
                i2c = busio.I2C(scl_pin, sda_pin, frequency=100000)
                print("SUCCESS: Using I2C on GPIO 8 (SCL, Pin 24) and GPIO 9 (SDA, Pin 21)")
                
            except Exception as e2:
                print(f"GPIO 8/9 failed: {e2}")
                
                # Final fallback - use default pins
                print("Falling back to default I2C pins...")
                i2c = board.I2C()  # GPIO 2 (SDA) and GPIO 3 (SCL)
                print("WARNING: Using default I2C - GPIO 2 (SDA, Pin 3) and GPIO 3 (SCL, Pin 5)")
                
except Exception as e:
    print(f"I2C initialization failed: {e}")
    exit(1)

# Define the GPIO pins connected to the XSHUT pin of each sensor
# Keep these the same as they work fine
xshut_pins = [
    board.D18,  # Pin for sensor 1 (GPIO 18, Physical Pin 12)
    board.D22   # Pin for sensor 2 (GPIO 22, Physical Pin 15)
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
new_addresses = [0x30, 0x31]

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

print("All sensors initialized successfully!")

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

if __name__ == "__main__":
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