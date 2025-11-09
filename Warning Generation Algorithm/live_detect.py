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
# Set a low resolution for fast processing. 640x480 is good.
config = picam2.create_preview_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()

print("--- Starting Live Detection ---")
print("Press Ctrl+C in the terminal to quit.")

# --- 4. Start the Live Loop ---
try:
    while True:
        start_time = time.time()
        
        # Read a new frame from the Pi Camera
        # This gives us a NumPy array, just like cv2.VideoCapture
        frame = picam2.capture_array()
        
        # The model.infer() expects BGR, but picam2 gives RGB.
        # We must convert the color space.
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # --- 5. Run inference on BOTH models ---
        pothole_results = pothole_model.infer(frame_bgr)[0]
        speedbump_results = speedbump_model.infer(frame_bgr)[0]

        # Convert results to supervision Detections
        pothole_detections = sv.Detections.from_inference(pothole_results)
        speedbump_detections = sv.Detections.from_inference(speedbump_results)

        # --- 6. This is your "Return Statement" logic ---
        potholes_found = len(pothole_detections) > 0
        speedbumps_found = len(speedbump_detections) > 0

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
    # This block will run when you press Ctrl+C
    print("Keyboard interrupt received.")

finally:
    # --- 7. Clean up ---
    print("--- Stopping Camera ---")
    picam2.stop()