import atexit
import time
import supervision as sv
from inference.models.utils import get_model
from picamera2 import Picamera2 # The RPi camera library
import cv2 # Still needed for font/color definitions
import json

# --- 1. Define Your Variables ---
API_KEY = "rRFoNCvmMJDVJrriVS1o"
MODEL_ID = "potholes-and-speed-bumps-detection/1" # Your new single model

# --- 2. Load the SINGLE Model ---
print(f"Loading combined model: {MODEL_ID}...")
model = get_model(model_id=MODEL_ID, api_key=API_KEY)

# --- 3. Set up Pi Camera (picamera2) ---
WARNING_FILE_PATH = "camera_warnings.json"
print("Configuring Pi Camera...")
picam2 = Picamera2()
# Set a very low resolution for fast processing
config = picam2.create_preview_configuration(main={"size": (320, 240)})
picam2.configure(config)
picam2.start()

# --- NEW: Function to write warnings to the shared file ---
def write_warnings(pothole_val, bump_val):
    """Writes the current detection state to the JSON file."""
    data = {
        "pothole": pothole_val,
        "bump": bump_val,
        "timestamp": time.time() # So the other script knows if we are "stale"
    }
    try:
        with open(WARNING_FILE_PATH, 'w') as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error writing to warning file: {e}")

# --- NEW: Cleanup function to run on exit ---
@atexit.register
def cleanup_on_exit():
    """Clear warnings when this script stops."""
    print("Cleaning up warning file...")
    write_warnings(0, 0) # Write 0s so warnings stop
    picam2.stop()
    print("Camera stopped.")

print("--- Starting Live Detection ---")
print("Writing detections to camera_warnings.json")
print("Press Ctrl+C in the terminal to quit.")

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
        pothole_val = 1 if potholes_found else 0
        bump_val = 1 if speedbumps_found else 0
        
        if potholes_found:
            print("POTHOLE DETECTED!")
        
        if speedbumps_found:
            print("SPEEDBUMP DETECTED!")
        
        if not potholes_found and not speedbumps_found:
            print("Clear")

        # --- Write detections to JSON file ---
        write_warnings(pothole_val, bump_val)

        # Calculate and print FPS
        end_time = time.time()
        if (end_time - start_time) > 0:
            fps = 1 / (end_time - start_time)
            print(f"FPS: {fps:.2f}")

except KeyboardInterrupt:
    print("Keyboard interrupt received.")
    # The @atexit function will handle cleanup