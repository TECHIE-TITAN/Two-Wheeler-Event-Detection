import cv2

cap = cv2.VideoCapture(0)  # Pi Camera

while True:
    ret, frame = cap.read()
    if not ret:
        break

    cv2.imshow("Camera", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()

prev_y = None

if prev_y is not None:
    delta = y - prev_y
    if delta < -threshold:
        print("Bump ahead!")
    elif delta > threshold:
        print("Pothole ahead!")

prev_y = y
