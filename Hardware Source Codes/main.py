# This is the main script that integrates all sensor data and prints the combined object.

import time
import threading
import queue
import csv
import os
# import camera_utils # Commented out
import mpu_utils
import gps_utils
# import lidar_utils # Commented out
import ldr_utils
# import cv2 # Commented out
import RPi.GPIO as GPIO

# Global data object and lock for thread-safe access
sensor_data = {
    "image_matrix": None,
    "mpu_data": None,
    "gps_data": None,
    "lidar_data": None,
    "ldr_status": None
}
data_lock = threading.Lock()

# Threading events to control sensor reading frequency
read_event = threading.Event()
stop_event = threading.Event()

def sensor_thread(func, key, *args):
    """
    A generic function for a sensor thread.
    It waits for a signal and then reads data from the sensor.
    """
    while not stop_event.is_set():
        if read_event.wait(timeout=0.1):
            with data_lock:
                try:
                    sensor_data[key] = func(*args)
                except Exception as e:
                    print(f"Error in {key} thread: {e}")
            read_event.clear()

def main():
    """
    Initializes all sensors and enters a continuous loop to
    read data, create a data object, and print it.
    """
    
    # Initialize all sensor systems
    mpu_utils.init_mpu()
    gps_serial = gps_utils.init_gps()
    # lidar_sensor = lidar_utils.init_lidar() # Commented out
    ldr_utils.init_ldr()

    # Create and start a thread for each sensor
    threads = [
        # threading.Thread(target=sensor_thread, args=(camera_utils.get_camera_image_matrix, "image_matrix")), # Commented out
        threading.Thread(target=sensor_thread, args=(mpu_utils.get_mpu_data, "mpu_data")),
        threading.Thread(target=sensor_thread, args=(gps_utils.get_gps_data, "gps_data", gps_serial)),
        # threading.Thread(target=sensor_thread, args=(lidar_utils.get_lidar_data, "lidar_data", lidar_sensor)), # Commented out
        threading.Thread(target=sensor_thread, args=(ldr_utils.get_ldr_status, "ldr_status")),
    ]

    for t in threads:
        t.start()

    # Setup CSV file for writing
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    csv_filename = f"sensor_data_{timestamp}.csv"
    file_exists = os.path.isfile(csv_filename)

    with open(csv_filename, 'a', newline='') as csvfile:
        fieldnames = ['timestamp', 'acc_x', 'acc_y', 'acc_z', 'gyro_x', 'gyro_y', 'gyro_z', 'latitude', 'longitude', 'ldr_status']
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        if not file_exists:
            writer.writeheader()

        try:
            while True:
                # Signal all threads to take a reading
                read_event.set()

                # Wait for all threads to finish their reading cycle
                time.sleep(1)
                
                # Use a lock to safely access the global data dictionary
                with data_lock:
                    # Print the integrated object to the console
                    current_data = sensor_data.copy()
                    print(current_data)

                    # Prepare data for CSV
                    row_data = {
                        'timestamp': time.time(),
                        'acc_x': current_data.get('mpu_data', (None, None, None, None, None, None))[0],
                        'acc_y': current_data.get('mpu_data', (None, None, None, None, None, None))[1],
                        'acc_z': current_data.get('mpu_data', (None, None, None, None, None, None))[2],
                        'gyro_x': current_data.get('mpu_data', (None, None, None, None, None, None))[3],
                        'gyro_y': current_data.get('mpu_data', (None, None, None, None, None, None))[4],
                        'gyro_z': current_data.get('mpu_data', (None, None, None, None, None, None))[5],
                        'latitude': current_data.get('gps_data', (None, None))[0],
                        'longitude': current_data.get('gps_data', (None, None))[1],
                        'ldr_status': current_data.get('ldr_status')
                    }
                    writer.writerow(row_data)
                
                # Implement a sleep mechanism to save power
                # The sensors read once every 5 seconds.
                time.sleep(4)

        except KeyboardInterrupt:
            print("Program terminated by user.")
        finally:
            # Signal all threads to stop and wait for them to join
            stop_event.set()
            for t in threads:
                t.join()
            
            # Cleanup resources
            if gps_serial:
                gps_serial.close()
            GPIO.cleanup()
            # cv2.destroyAllWindows() # Commented out

main()