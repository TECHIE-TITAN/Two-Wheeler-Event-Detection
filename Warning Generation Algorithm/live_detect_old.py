import time
import supervision as sv
from inference.models.utils import get_model
from picamera2 import Picamera2
import cv2
import json # --- NEW IMPORT ---
import atexit # --- NEW IMPORT for cleanup ---

# --- 1. Define Your Variables ---
API_KEY = "rRFoNCvmMJDVJrriVS1o"
POTHOLE_MODEL_ID = "pothole-xjwqu/3"
SPEEDBUMP_MODEL_ID = "speedbump-tkb8k/9"

# --- NEW: Define the shared file path ---
WARNING_FILE_PATH = "camera_warnings.json"

# --- 2. Load BOTH Models ---
print(f"Loading pothole model: {POTHOLE_MODEL_ID}...")
pothole_model = get_model(model_id=POTHOLE_MODEL_ID, api_key=API_KEY)

print(f"Loading speedbump model: {SPEEDBUMP_MODEL_ID}...")
speedbump_model = get_model(model_id=SPEEDBUMP_MODEL_ID, api_key=API_KEY)

# --- 3. Set up Pi Camera (picamera2) ---
print("Configuring Pi Camera...")
picam2 = Picamera2()
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

# --- 4. Start the Live Loop ---
frame_counter = 0 
try:
    while True:
        start_time = time.time()
        frame_counter += 1
        
        frame = picam2.capture_array()
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

        # --- 5. Run inference on ONLY ONE model per frame ---
        
        pothole_found = 0
        speedbump_found = 0

        if frame_counter % 2 == 0:
            # On even frames, check for potholes
            results = pothole_model.infer(frame_bgr)[0]
            detections = sv.Detections.from_inference(results)
            if len(detections) > 0:
                print("POTHOLE DETECTED!")
                pothole_found = 1
            
        else:
            # On odd frames, check for speedbumps
            results = speedbump_model.infer(frame_bgr)[0]
            detections = sv.Detections.from_inference(results)
            if len(detections) > 0:
                print("SPEEDBUMP DETECTED!")
                speedbump_found = 1
        
        if not pothole_found and not speedbump_found:
            print("Clear")

        # --- 6. NEW: Write detections to the file ---
        # We write every loop. If no pothole was detected, pothole_found is 0.
        # This will alternate:
        # Loop 1 (Pothole): {"pothole": 1, "bump": 0}
        # Loop 2 (Bump):    {"pothole": 0, "bump": 1}
        # Loop 3 (Clear):   {"pothole": 0, "bump": 0}
        write_warnings(pothole_found, speedbump_found)

        # Calculate and print FPS
        end_time = time.time()
        if (end_time - start_time) > 0:
            fps = 1 / (end_time - start_time)
            print(f"FPS: {fps:.2f}")

except KeyboardInterrupt:
    print("\nKeyboard interrupt received.")
    # The @atexit function will handle cleanup