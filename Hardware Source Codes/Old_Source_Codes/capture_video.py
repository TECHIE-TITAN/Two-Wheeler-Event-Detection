import cv2
from ultralytics import YOLO
from picamera2 import Picamera2

# Initialize Pi Camera
picam2 = Picamera2()
# Configure the camera for a lower resolution to improve performance
config = picam2.create_preview_configuration(main={"size": (640, 480)})
picam2.configure(config)
picam2.start()

# Load YOLOv8 Nano model, the smallest and fastest model
model = YOLO("yolov8n.pt")

# Previous vertical position of the detected car's bottom edge
prev_y = None

# Threshold for vertical change in pixels (you'll need to tune this)
THRESHOLD = 10 

while True:
    # Capture a frame from the Pi Camera
    frame = picam2.capture_array()
    
    # Run YOLOv8 detection on the frame
    results = model(frame)
    annotated_frame = results[0].plot()

    # Find the first detected vehicle (class 2 is 'car' in the COCO dataset)
    detected_car = False
    for det in results[0].boxes:
        cls = int(det.cls[0])  # Get class index
        if cls == 2:  # Found a car
            x1, y1, x2, y2 = map(int, det.xyxy[0])
            bottom_y = y2  # Use the bottom of the bounding box as the reference

            # Compare with the previous frame's vertical position
            if prev_y is not None:
                delta = bottom_y - prev_y
                
                # Check for significant upward movement (a bump)
                if delta < -THRESHOLD:
                    print("Bump ahead!")
                # Check for significant downward movement (a pothole)
                elif delta > THRESHOLD:
                    print("Pothole ahead!")
            
            prev_y = bottom_y
            detected_car = True
            break  # Process only the first car found

    # If no car was detected in this frame, reset prev_y
    if not detected_car:
        prev_y = None

    # Display the annotated frame
    cv2.imshow("Road Condition Detection", annotated_frame)

    # Exit the loop if 'q' is pressed
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Clean up
cv2.destroyAllWindows()
picam2.stop()