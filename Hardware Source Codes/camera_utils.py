import time
import os
import cv2
from picamera2 import Picamera2

DEFAULT_SAVE_DIRECTORY = "captured_images"

class CameraManager:
    def __init__(self, resolution=(160, 120), save_dir=DEFAULT_SAVE_DIRECTORY, capture_interval=0.5):
        self.save_dir = save_dir
        self.capture_interval = capture_interval  # Capture every 0.5 seconds (2 Hz)
        self.last_capture_time = 0
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
        self.picam2 = Picamera2()
        # Much lower resolution to reduce processing overhead
        config = self.picam2.create_preview_configuration(main={"size": resolution})
        self.picam2.configure(config)
        self.picam2.start()
        time.sleep(0.01)

    def should_capture(self):
        """Check if enough time has passed since last capture"""
        current_time = time.time()
        if current_time - self.last_capture_time >= self.capture_interval:
            self.last_capture_time = current_time
            return True
        return False

    def capture_image_lightweight(self, prefix="frame"):
        """Lightweight capture that skips file I/O when not needed"""
        if not self.should_capture():
            return None, None
            
        try:
            image_array = self.picam2.capture_array()
            timestamp_ms = int(time.time() * 1000)
            
            # Skip expensive operations during high-frequency periods
            # Only save every nth image or during specific events
            filename = f"{prefix}_{timestamp_ms}.jpg"
            filepath = os.path.join(self.save_dir, filename)
            
            # Reduce color conversion overhead by saving directly
            bgr_image = cv2.cvtColor(image_array, cv2.COLOR_RGB2BGR)
            cv2.imwrite(filepath, bgr_image, [cv2.IMWRITE_JPEG_QUALITY, 70])  # Lower quality for speed
            
            return filepath, timestamp_ms
        except Exception as e:
            print(f"Camera capture error: {e}")
            return None, None

    def close(self):
        try:
            self.picam2.stop()
        except Exception:
            pass


def init_camera(resolution=(640, 480), save_dir=DEFAULT_SAVE_DIRECTORY):
    return CameraManager(resolution=resolution, save_dir=save_dir)


def capture_image(camera_manager):
    if camera_manager is None:
        return None, None
    return camera_manager.capture_image_lightweight()


def close(camera_manager):
    if camera_manager:
        camera_manager.close()


if __name__ == '__main__':
    """
    Optimized camera loop that won't interfere with sensor readings
    """
    print("--- Running Optimized Camera Test ---")

    # Initialize with lower resolution and controlled frequency
    cam_manager = init_camera(resolution=(160, 120))

    if cam_manager:
        try:
            print(f"\nCapturing images every {cam_manager.capture_interval} seconds to minimize system load.")
            image_count = 0
            
            while True:
                # Non-blocking check - only capture when interval has passed
                filepath, timestamp = cam_manager.capture_image_lightweight()
                
                if filepath:
                    image_count += 1
                    print(f"  [Image {image_count}] saved to: {filepath}")
                
                # Very short sleep to prevent CPU spinning
                time.sleep(0.01)  # 1ms sleep instead of 2 seconds

        except KeyboardInterrupt:
            print("\n\nStopping capture...")
        except Exception as e:
            print(f"An error occurred during capture: {e}")
        finally:
            print("\nClosing camera...")
            cam_manager.close()
            print("\n--- Camera Test Finished ---")
    else:
        print("Could not start camera manager. Exiting test.")

