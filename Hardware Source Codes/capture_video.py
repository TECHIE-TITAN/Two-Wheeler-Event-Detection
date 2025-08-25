import cv2
from ultralytics import YOLO

# Load YOLOv8 Nano model
model = YOLO("yolov8n.pt")

# Open Pi Camera
cap = cv2.VideoCapture(0)

# Previous vertical position
prev_y = None

# Threshold for vertical change (pixels)
THRESHOLD = 10  # adjust experimentally

while True:
    ret, frame = cap.read()
    if not ret:
        break

    # Run YOLO detection
    results = model(frame)
    annotated_frame = results[0].plot()

    # Find the first detected vehicle (class 2 = car in COCO)
    for det in results[0].boxes:
        cls = int(det.cls[0])  # class index
        if cls == 2:  # car
            x1, y1, x2, y2 = map(int, det.xyxy[0])
            bottom_y = y2  # bottom of bounding box

            # Compare with previous vertical position
            if prev_y is not None:
                delta = bottom_y - prev_y
                if delta < -THRESHOLD:
                    print("Bump ahead!")
                elif delta > THRESHOLD:
                    print("Pothole ahead!")

            prev_y = bottom_y
            break  # only track the first detected vehicle

    # Display annotated frame
    cv2.imshow("YOLO Detection", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
