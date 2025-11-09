import cv2
import supervision as sv
from inference.models.utils import get_model
import time # Added to calculate FPS

# --- 1. Define Your Variables ---

# Switch between your models here
MODEL_ID = "pothole-xjwqu/3"
# MODEL_ID = "speed-bumps-detection-61eef/7"

API_KEY = "rRFoNCvmMJDVJrriVS1o"

# --- 2. Load the Model (only happens once) ---
print(f"Loading model {MODEL_ID}...")
model = get_model(model_id=MODEL_ID, api_key=API_KEY)

# --- 3. Set up Camera and Annotators ---
# 0 is your laptop's built-in webcam
cap = cv2.VideoCapture(0) 

# Check if webcam opened successfully
if not cap.isOpened():
    print("Error: Could not open webcam.")
    exit()

bounding_box_annotator = sv.BoundingBoxAnnotator()
label_annotator = sv.LabelAnnotator()

print("--- Starting Live Detection ---")
print("Press 'q' in the popup window to quit.")

# --- 4. Start the Live Loop ---
while True:
    start_time = time.time() # For FPS calculation

    # Read a new frame
    ret, frame = cap.read()
    if not ret:
        print("Failed to grab frame")
        break

    # Run inference
    results = model.infer(frame)[0]
    detections = sv.Detections.from_inference(results)

    # --- 5. This is your "Return Statement" ---
    if len(detections) > 0:
        print("OBJECT DETECTED!")
    else:
        print("Clear")

    # --- 6. (Optional) Show the video window ---
    annotated_frame = bounding_box_annotator.annotate(scene=frame, detections=detections)
    annotated_frame = label_annotator.annotate(scene=annotated_frame, detections=detections)

    # Calculate and display FPS
    end_time = time.time()
    fps = 1 / (end_time - start_time)
    cv2.putText(annotated_frame, f"FPS: {int(fps)}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)

    cv2.imshow("Live Detection", annotated_frame)

    # Check if the 'q' key was pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# --- 7. Clean up ---
print("--- Stopping ---")
cap.release()
cv2.destroyAllWindows()