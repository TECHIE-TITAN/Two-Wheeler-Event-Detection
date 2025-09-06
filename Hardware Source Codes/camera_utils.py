import cv2

def get_camera_image_matrix():
    """
    Captures a frame from the camera and returns it as a grayscale 2D matrix.
    """
    try:
        cap = cv2.VideoCapture(0)
        ret, frame = cap.read()
        cap.release()
        if ret:
            resized_frame = cv2.resize(frame, (64, 64))
            gray_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2GRAY)
            return gray_frame.tolist()
    except Exception as e:
        print(f"Error capturing camera image: {e}")
    return None
