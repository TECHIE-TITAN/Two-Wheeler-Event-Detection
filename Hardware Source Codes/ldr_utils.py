"""LDR (Light Dependent Resistor) utility functions.

This module provides functions to initialize and read from an LDR sensor
to detect ambient light conditions.
"""

import RPi.GPIO as GPIO
import time

# Configuration
LDR_PIN = 18  # GPIO pin connected to LDR (change as needed)

def init_ldr():
    """Initialize the LDR sensor."""
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(LDR_PIN, GPIO.IN)
        print("LDR sensor initialized successfully")
    except Exception as e:
        print(f"Error initializing LDR: {e}")

def get_ldr_status():
    """
    Read the LDR status.
    
    Returns:
        str: "LIGHT" or "DARK" based on LDR reading, or None if error
    """
    try:
        # Read the digital value from LDR
        ldr_value = GPIO.input(LDR_PIN)
        
        # Return status based on reading
        # Note: This assumes LDR circuit outputs HIGH in light, LOW in dark
        # Adjust logic based on your specific circuit
        if ldr_value == 1:
            return "LIGHT"
        else:
            return "DARK"
    except Exception as e:
        print(f"Error reading LDR: {e}")
        return None

def cleanup_ldr():
    """Clean up GPIO resources."""
    try:
        GPIO.cleanup()
    except Exception as e:
        print(f"Error cleaning up LDR GPIO: {e}")
