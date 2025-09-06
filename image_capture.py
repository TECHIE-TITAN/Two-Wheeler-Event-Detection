import time
from picamera2 import Picamera2

# --- Initialization ---
picam2 = Picamera2()
config = picam2.create_preview_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()
print("Camera initialized. Starting capture every 2 seconds...")
# Give the camera a moment to adjust to light levels
time.sleep(1) 

# Main Loop

try:
    while True:
        # Create a unique filename based on the current date and time
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"capture_{timestamp}.jpg"
        
        # Capture the image and save it to a file
        picam2.capture_file(filename)
        
        print(f"Image saved: {filename}")
        
        # Wait for 2 seconds before the next capture
        time.sleep(2)

except KeyboardInterrupt:
    # This block runs when you press Ctrl+C in the terminal
    print("\nCapture stopped by user.")

finally:
    # Cleanly stop the camera
    picam2.stop()
    print("Camera stopped.")