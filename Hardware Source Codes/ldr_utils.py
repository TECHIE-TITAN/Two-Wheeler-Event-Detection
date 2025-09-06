import RPi.GPIO as GPIO
import time

LDR_PIN = 18

def init_ldr():
    """Initializes the GPIO for the LDR sensor."""
    try:
        GPIO.setmode(GPIO.BCM)
    except Exception as e:
        print(f"Error initializing LDR GPIO: {e}")

def _rc_time(pin=LDR_PIN):
    """Measures the light level using the RC time circuit."""
    try:
        count = 0
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, False)
        time.sleep(0.1)
        GPIO.setup(pin, GPIO.IN)
        while GPIO.input(pin) == GPIO.LOW:
            count += 1
        return count
    except Exception as e:
        print(f"Error measuring light level: {e}")
        return None

def get_ldr_status():
    """
    Returns a string indicating "Day" or "Night" based on light level.
    """
    light_level = _rc_time()
    if light_level is None:
        return "Unknown"
    
    # The threshold of 500 is a placeholder and should be calibrated.
    if light_level < 500:
        return "Day"
    else:
        return "Night"
