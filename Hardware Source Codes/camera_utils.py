import time
import os
import cv2 # We need OpenCV to save the array as an image
from picamera2 import Picamera2

# --- Configuration ---
SAVE_DIRECTORY = "captured_images"

# --- Initialization ---
# 1. Create the directory for saving images if it doesn't exist
if not os.path.exists(SAVE_DIRECTORY):
    os.makedirs(SAVE_DIRECTORY)
    print(f"Directory '{SAVE_DIRECTORY}' created.")

# Standard camera setup
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()
print("Camera initialized. Starting capture every 2 seconds...")
time.sleep(1) 

# --- Main Loop ---
try:
    while True:
        # Capture the image data as a NumPy array (this is the 2D/3D array)
        image_array = picam2.capture_array()

        # --- Requirement 1: Display the image as an array on the terminal ---
        print("\n--- Image Array Data ---")
        # Note: This will be a large output!
        print(image_array)
        print("------------------------")

        # --- Requirement 2: Save the image to the 'captured_images' folder ---
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"capture_{timestamp}.jpg"
        # Create the full path to the file
        filepath = os.path.join(SAVE_DIRECTORY, filename)
        
        # Picamera2 captures in RGB format, but OpenCV saves in BGR format.
        # We need to convert the color channels before saving.
        bgr_image = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
        cv2.imwrite(filepath, bgr_image)
        
        print(f"Image saved: {filepath}")
        
        # Wait for 2 seconds before the next capture
        time.sleep(2)

except KeyboardInterrupt:
    # This block runs when you press Ctrl+C in the terminal
    print("\nCapture stopped by user.")

finally:
    # Cleanly stop the camera
    picam2.stop()
    print("Camera stopped.")
