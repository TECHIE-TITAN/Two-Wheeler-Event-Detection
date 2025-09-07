import time
import board
import digitalio
import adafruit_vl53l0x
import busio

# --- Sensor and I2C Configuration ---

print("Initializing I2C for VL53L0X sensors...")
print("Note: GPIO 2 & 3 are occupied by MPU sensor, using alternative pins for VL53L0X")

# Since GPIO 2 & 3 are used by MPU, we MUST use software I2C on different pins
# Let's use GPIO 5 (SCL) and GPIO 6 (SDA) for the VL53L0X sensors

i2c = None

try:
    # Try software I2C with bitbangio first (most reliable for custom pins)
    print("Attempting software I2C with bitbangio on GPIO 5/6...")
    try:
        import bitbangio
        scl_pin = board.D5   # GPIO 5 (Physical Pin 29)
        sda_pin = board.D6   # GPIO 6 (Physical Pin 31)
        i2c = bitbangio.I2C(scl_pin, sda_pin, frequency=100000, timeout=5)
        print("SUCCESS: Using software I2C (bitbangio) on GPIO 5 (SCL, Pin 29) and GPIO 6 (SDA, Pin 31)")
        
    except ImportError:
        print("bitbangio not available, trying alternative approach...")
        
        # Alternative: Try GPIO 13 and 19 (these are also free)
        try:
            print("Trying GPIO 13 (SCL) and GPIO 19 (SDA)...")
            scl_pin = board.D13  # GPIO 13 (Physical Pin 33)
            sda_pin = board.D19  # GPIO 19 (Physical Pin 35)
            import busio
            # Force software I2C by using non-hardware pins
            i2c = busio.I2C(scl_pin, sda_pin, frequency=50000)  # Lower frequency for stability
            print("SUCCESS: Using I2C on GPIO 13 (SCL, Pin 33) and GPIO 19 (SDA, Pin 35)")
            
        except Exception as e2:
            print(f"GPIO 13/19 failed: {e2}")
            
            # Try GPIO 26 and 20
            try:
                print("Trying GPIO 26 (SCL) and GPIO 20 (SDA)...")
                scl_pin = board.D26  # GPIO 26 (Physical Pin 37)
                sda_pin = board.D20  # GPIO 20 (Physical Pin 38)
                i2c = busio.I2C(scl_pin, sda_pin, frequency=50000)
                print("SUCCESS: Using I2C on GPIO 26 (SCL, Pin 37) and GPIO 20 (SDA, Pin 38)")
                
            except Exception as e3:
                print(f"All alternative pins failed: {e3}")
                print("ERROR: Cannot initialize I2C on alternative pins")
                print("Please ensure GPIO 2 & 3 are available or check wiring")
                exit(1)
                
except Exception as e:
    print(f"I2C initialization completely failed: {e}")
    exit(1)

# Add a small delay and check I2C bus
time.sleep(0.5)

# Scan for I2C devices to debug
print("Scanning I2C bus for devices...")
while not i2c.try_lock():
    pass

try:
    devices = i2c.scan()
    print(f"I2C devices found: {[hex(device) for device in devices]}")
    if not devices:
        print("WARNING: No I2C devices detected! Check wiring.")
    else:
        print(f"Found {len(devices)} I2C device(s)")
        
    # Check specifically for VL53L0X default address
    if 0x29 in devices:
        print("✓ VL53L0X sensor detected at default address 0x29")
    else:
        print("✗ No VL53L0X sensor found at default address 0x29")
        print("Common I2C devices:")
        print("  0x68 = MPU6050/MPU6500 (Accelerometer/Gyroscope)")
        print("  0x29 = VL53L0X (LIDAR)")
        print("  0x76/0x77 = BMP280/BME280 (Pressure/Humidity)")
        
finally:
    i2c.unlock()

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
print("\nInitializing 2 sensors...")
print("VL53L0X wiring (MPU sensor uses GPIO 2&3, so VL53L0X uses different pins):")
print("VL53L0X -> Raspberry Pi")
print("VCC -> 3.3V (Pin 1 or 17)")
print("GND -> Ground (Pin 6, 9, 14, etc.)")
print("SCL -> GPIO 5 (Pin 29) [SOFTWARE I2C - different from MPU]")
print("SDA -> GPIO 6 (Pin 31) [SOFTWARE I2C - different from MPU]")
print("XSHUT1 -> GPIO 18 (Pin 12)")
print("XSHUT2 -> GPIO 22 (Pin 15)")
print()
print("MPU sensor continues to use GPIO 2 (SDA) and GPIO 3 (SCL)")
print()

for i, shutdown_pin in enumerate(shutdown_pins):
    print(f"Attempting to initialize sensor {i+1}...")
    
    # Make sure all sensors are initially off
    for sp in shutdown_pins:
        sp.value = False
    time.sleep(0.1)
    
    # Turn on only the current sensor by setting its XSHUT pin high
    shutdown_pin.value = True
    time.sleep(0.2)  # Give the sensor more time to wake up
    
    # Scan again to see if sensor appears
    while not i2c.try_lock():
        pass
    try:
        devices_after = i2c.scan()
        print(f"  I2C devices after enabling sensor {i+1}: {[hex(device) for device in devices_after]}")
        if 0x29 in devices_after:
            print(f"  ✓ Sensor {i+1} detected at 0x29")
        else:
            print(f"  ✗ Sensor {i+1} not detected at 0x29")
    finally:
        i2c.unlock()

    try:
        # Create a sensor instance with the default I2C address
        print(f"  Creating VL53L0X instance for sensor {i+1}...")
        sensor = adafruit_vl53l0x.VL53L0X(i2c)
        
        # Change the I2C address of the sensor
        new_address = new_addresses[i]
        print(f"  Changing sensor {i+1} address to {hex(new_address)}...")
        sensor.set_address(new_address)
        
        # Add the configured sensor to our list
        sensors.append(sensor)
        print(f"  ✓ Sensor {i+1} initialized successfully with address {hex(new_address)}")
        
    except Exception as e:
        print(f"  ✗ Failed to initialize sensor {i+1}: {e}")
        print(f"  Check wiring for sensor {i+1}:")
        print(f"    - Is VCC connected to 3.3V?")
        print(f"    - Is GND connected?")
        print(f"    - Are SDA/SCL connected to the correct pins?")
        print(f"    - Is XSHUT{i+1} connected to GPIO {xshut_pins[i]}?")
        print("  Continuing without this sensor...")

# Check if any sensors were initialized
if len(sensors) == 0:
    print("\n❌ No sensors were initialized successfully!")
    print("Please check your wiring and try again.")
    exit(1)
elif len(sensors) < len(xshut_pins):
    print(f"\n⚠️  Only {len(sensors)} out of {len(xshut_pins)} sensors initialized.")
    print("Continuing with available sensors...")
else:
    print(f"\n✅ All {len(sensors)} sensors initialized successfully!")

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