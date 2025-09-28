#!/usr/bin/env python3
"""
Debug script for GPS speed issue.
Run this on your Raspberry Pi to diagnose the constant 7.xx speed problem.
"""

import gps_utils
import time

def main():
    print("GPS Speed Debug Tool")
    print("===================")
    print("This tool will help diagnose why GPS speed shows constant 7.xx value")
    print()
    
    try:
        # Initialize GPS
        print("Initializing GPS...")
        gps_serial = gps_utils.init_gps()
        print("GPS initialized successfully!")
        print()
        
        # Run debug analysis
        print("Step 1: Analyzing raw speed values from GPS...")
        gps_utils.debug_speed_issue(gps_serial, readings=20)
        
        print("\nStep 2: Testing live GPS readings for 30 seconds...")
        print("Move the device around to see if speed changes...")
        
        start_time = time.time()
        reading_count = 0
        
        while (time.time() - start_time) < 30:
            gps_data = gps_utils.get_gps_data(gps_serial)
            if gps_data and gps_data != (None, None, None):
                lat, lon, speed = gps_data
                reading_count += 1
                print(f"Live reading #{reading_count}: Speed = {speed:.3f} km/h")
                time.sleep(2)  # Read every 2 seconds
        
        print("\nDebug completed!")
        print("\nIf speed values are always the same:")
        print("1. Check if GPS module is in demo/test mode")
        print("2. Ensure good satellite reception (go outdoors)")
        print("3. Try moving the device at different speeds")
        print("4. Check GPS module documentation for speed calculation settings")
        
    except Exception as e:
        print(f"Error: {e}")
        print("\nThis is expected when running on non-Raspberry Pi systems")
        print("Run this script on your actual Raspberry Pi hardware")
    
    finally:
        try:
            gps_serial.close()
        except:
            pass

if __name__ == "__main__":
    main()
