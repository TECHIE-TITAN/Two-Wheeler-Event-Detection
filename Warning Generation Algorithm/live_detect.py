import time
import supervision as sv
from inference.models.utils import get_model
from picamera2 import Picamera2 # The RPi camera library
import cv2 # Still needed for font/color definitions

# --- 1. Define Your Variables ---
API_KEY = "rRFoNCvmMJDVJrriVS1o"
POTHOLE_MODEL_ID = "pothole-xjwqu/3"
SPEEDBUMP_MODEL_ID = "speed-bumps-detection-61eef/7"

# --- 2. Load BOTH Models ---
print(f"Loading pothole model: {POTHOLE_MODEL_ID}...")
pothole_model = get_model(model_id=POTHOLE_MODEL_ID, api_key=API_KEY)

print(f"Loading speedbump model: {SPEEDBUMP_MODEL_ID}...")
speedbump_model = get_model(model_id=SPEEDBUMP_MODEL_ID, api_key=API_KEY)

# --- 3. Set up Pi Camera (picamera2) ---
print("Configuring Pi Camera...")
picam2 = Picamera2()

# *** THIS IS YOUR FIX ***
# Set a very low resolution for fast processing
config = picam2.create_preview_configuration(main={"size": (320, 240)})
picam2.configure(config)
picam2.start()

print("--- Starting Live Detection ---")
print("Press Ctrl+C in the terminal to quit.")

# --- 4. Start the Live Loop ---
frame_counter = 0 # <-- We need this to alternate
try:
    while True:
        start_time = time.time()
        frame_counter += 1
        
        # Read a new frame
        frame = picam2.capture_array()
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # --- 5. Run inference on ONLY ONE model per frame ---
        
        if frame_counter % 2 == 0:
            # On even frames, check for potholes
            #print("Checking for POTHOLE...")
            results = pothole_model.infer(frame_bgr)[0]
            detections = sv.Detections.from_inference(results)
            if len(detections) > 0:
                print("POTHOLE DETECTED!")
            
        else:
            # On odd frames, check for speedbumps
            #print("Checking for SPEEDBUMP...")
            results = speedbump_model.infer(frame_bgr)[0]
            detections = sv.Detections.from_inference(results)
            if len(detections) > 0:
                print("SPEEDBUMP DETECTED!")
        
        if len(detections) == 0:
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