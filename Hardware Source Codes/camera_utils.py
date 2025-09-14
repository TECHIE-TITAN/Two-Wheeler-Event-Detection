import time
import os
import cv2
from picamera2 import Picamera2

DEFAULT_SAVE_DIRECTORY = "captured_images"

class CameraManager:
    """Wrapper around Picamera2 to provide single-frame capture API."""
    def __init__(self, resolution=(640, 480), save_dir=DEFAULT_SAVE_DIRECTORY):
        self.save_dir = save_dir
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.picam2 = Picamera2()
        config = self.picam2.create_preview_configuration(main={"size": resolution})
        self.picam2.configure(config)
        self.picam2.start()
        time.sleep(0.2)  # small warm-up

    def capture_image(self, prefix="frame"):
        """Captures a frame, stores it as JPEG, returns filepath."""
        try:
            image_array = self.picam2.capture_array()
            timestamp = time.time()
            filename = f"{prefix}_{int(timestamp*1000)}.jpg"
            filepath = os.path.join(self.save_dir, filename)
            bgr_image = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
            cv2.imwrite(filepath, bgr_image)
            return filepath
        except Exception as e:
            print(f"Camera capture error: {e}")
            return None

    def close(self):
        try:
            self.picam2.stop()
        except Exception:
            pass

def init_camera(resolution=(640,480), save_dir=DEFAULT_SAVE_DIRECTORY):
    """Initializes and returns a CameraManager instance."""
    return CameraManager(resolution=resolution, save_dir=save_dir)

def capture_image(camera_manager):
    """Helper to match previous style; captures and returns image filepath."""
    if camera_manager is None:
        return None
    return camera_manager.capture_image()

if __name__ == '__main__':
    """
    This block runs when the script is executed directly.
    It serves as a simple test to verify camera functionality.
    """
    print("--- Running Camera Test ---")

    # 1. Initialize the camera
    cam_manager = init_camera()

    if cam_manager:
        try:
            # 2. Continuously capture images until stopped
            print("\nContinuously capturing images every 2 seconds. Press Ctrl+C to stop.")
            image_count = 0
            while True:
                image_count += 1
                filepath = capture_image(cam_manager)
                if filepath:
                    print(f"  [Image {image_count}] saved to: {filepath}")
                else:
                    print(f"  [Image {image_count}] Failed to capture.")
                time.sleep(2)  # Wait 2 seconds between captures

        except KeyboardInterrupt:
            print("\n\nStopping capture...")
        except Exception as e:
            print(f"An error occurred during capture: {e}")
        finally:
            # 3. Clean up and close the camera
            print("\nClosing camera...")
            cam_manager.close()
            print("\n--- Camera Test Finished ---")
    else:
        print("Could not start camera manager. Exiting test.")

