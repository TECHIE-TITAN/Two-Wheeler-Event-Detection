import subprocess
import time
import sys
import os

# Paths to environments and scripts
MY_ENV = os.path.expanduser("~/Desktop/Two-Wheeler-Event-Detection/my_env/bin/python")
VENV = os.path.expanduser("~/Desktop/Two-Wheeler-Event-Detection/.venv/bin/python")

MAIN_SCRIPT = os.path.expanduser("~/Desktop/Two-Wheeler-Event-Detection/Hardware_code/main.py")
CAMERA_SCRIPT = os.path.expanduser("~/Desktop/Two-Wheeler-Event-Detection/Hardware_code/camera_utils.py")

def main():
    # Start both processes
    main_proc = subprocess.Popen([MY_ENV, MAIN_SCRIPT], stdout=subprocess.PIPE, text=True)
    cam_proc = subprocess.Popen([VENV, CAMERA_SCRIPT], stdout=subprocess.PIPE, text=True)

    try:
        while True:
            # Read one line from each process
            main_line = main_proc.stdout.readline().strip()
            cam_line = cam_proc.stdout.readline().strip()

            # Synchronize output
            print("\n==== Combined Data (every 2 sec) ====")
            print(f"[main.py]   {main_line}")
            print(f"[camera.py] {cam_line}")
            print("====================================\n")

            time.sleep(2)

    except KeyboardInterrupt:
        print("Stopping orchestrator...")
    finally:
        main_proc.terminate()
        cam_proc.terminate()

if __name__ == "__main__":
    main()
