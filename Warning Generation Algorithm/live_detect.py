import time
import supervision as sv
from inference.models.utils import get_model
from picamera2 import Picamera2 # The RPi camera library
import cv2 # Still needed for font/color definitions

# --- 1. Define Your Variables ---
API_KEY = "rRFoNCvmMJDVJrriVS1o"
MODEL_ID = "potholes-and-speed-bumps-detection/1" # Your new single model

# --- 2. Load the SINGLE Model ---
print(f"Loading combined model: {MODEL_ID}...")
model = get_model(model_id=MODEL_ID, api_key=API_KEY)

# --- 3. Set up Pi Camera (picamera2) ---
print("Configuring Pi Camera...")
picam2 = Picamera2()
# Set a very low resolution for fast processing
config = picam2.create_preview_configuration(main={"size": (320, 240)})
picam2.configure(config)
picam2.start()

print("--- Starting Live Detection ---")
print("Press Ctrl+C in the terminal to quit.")

# --- 4. Start the Simplified Live Loop ---
try:
    while True:
        start_time = time.time()
        
        # Read a new frame
        frame = picam2.capture_array()
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # --- 5. Run ONE inference call for ALL objects ---
        results = model.infer(frame_bgr)[0]
        detections = sv.Detections.from_inference(results)

        # --- 6. This is your "Return Statement" logic ---
        potholes_found = False
        speedbumps_found = False

        # Loop through all detections in this frame
        if len(detections) > 0:
            for class_name in detections.data['class_name']:
                if 'pothole' in class_name.lower(): # Use .lower() to be safe
                    potholes_found = True
                if 'speed' in class_name.lower(): # 'speed' will catch "Speed-Bump"
                    speedbumps_found = True

        # Now print the results for this frame
        if potholes_found:
            print("POTHOLE DETECTED!")
        
        if speedbumps_found:
            print("SPEEDBUMP DETECTED!")
        
        if not potholes_found and not speedbumps_found:
            print("Clear")

        # Calculate and print FPS
        end_time = time.time()
        if (end_time - start_time) > 0:
            fps = 1 / (end_time - start_time)
            print(f"FPS: {fps:.2f}")

except KeyboardInterrupt:
    print("Keyboard interrupt received.")

finally:
    # --- 7. Clean up ---
    print("--- Stopping Camera ---")
    picam2.stop()