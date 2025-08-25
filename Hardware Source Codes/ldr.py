import RPi.GPIO as GPIO
import time

LDR_PIN = 18  # Change if you use another pin

def setup():
    GPIO.setmode(GPIO.BCM)

def rc_time(pin=LDR_PIN):
    count = 0
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, False)
    time.sleep(0.1)

    GPIO.setup(pin, GPIO.IN)
    while GPIO.input(pin) == GPIO.LOW:
        count += 1
    return count

def get_light_status():
    light_level = rc_time()
    if light_level < 500:   # Adjust threshold
        return "Daytime"
    else:
        return "Nighttime"

def cleanup():
    GPIO.cleanup()
