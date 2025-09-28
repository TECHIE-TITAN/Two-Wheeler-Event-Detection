#!/usr/bin/env python3
"""
GPS Test Script
This script tests your GPS module and helps diagnose connection issues.
Run this before using the main application to ensure GPS is working.
"""

import sys
import time
import argparse
sys.path.append('.')  # Add current directory to path
import gps_utils

def test_raw_gps(port="/dev/serial0", baud=9600, duration=30):
    """Test raw GPS connection and show NMEA sentences"""
    print("="*60)
    print("GPS RAW DATA TEST")
    print("="*60)
    gps_utils.test_gps_connection(port, baud, duration)

def test_parsed_gps(port="/dev/serial0", baud=9600, duration=30):
    """Test parsed GPS data using gps_utils functions"""
    print("="*60)
    print("GPS PARSED DATA TEST")
    print("="*60)
    
    try:
        # Initialize GPS
        print(f"Initializing GPS on {port} at {baud} baud...")
        gps_serial = gps_utils.init_gps(port, baud)
        
        print(f"Testing parsed GPS data for {duration} seconds...")
        print("Ctrl+C to stop early")
        print("-" * 40)
        
        start_time = time.time()
        attempt_count = 0
        success_count = 0
        last_success_time = 0
        
        while (time.time() - start_time) < duration:
            try:
                attempt_count += 1
                gps_data = gps_utils.get_gps_data(gps_serial)
                
                if gps_data and gps_data != (None, None, None):
                    success_count += 1
                    last_success_time = time.time()
                    lat, lon, speed = gps_data
                    
                    print(f"[{success_count:3d}] SUCCESS: Lat={lat:10.6f}, Lon={lon:11.6f}, Speed={speed:6.2f} km/h")
                else:
                    if attempt_count % 10 == 0:  # Print status every 10 attempts
                        elapsed = time.time() - start_time
                        print(f"[{attempt_count:3d}] Waiting for GPS fix... ({elapsed:.1f}s elapsed)")
                
                time.sleep(1)  # Wait 1 second between attempts
                
            except KeyboardInterrupt:
                print("\nTest interrupted by user.")
                break
                
        elapsed = time.time() - start_time
        success_rate = (success_count / attempt_count * 100) if attempt_count > 0 else 0
        
        print("-" * 40)
        print(f"Test Results:")
        print(f"Duration: {elapsed:.1f} seconds")
        print(f"Attempts: {attempt_count}")
        print(f"Successes: {success_count}")
        print(f"Success Rate: {success_rate:.1f}%")
        
        if success_count == 0:
            print("\n❌ ERROR: No GPS data received!")
            print("Troubleshooting steps:")
            print("1. Check GPS module power and connections")
            print("2. Ensure GPS module has clear view of sky")
            print("3. Wait longer for satellite acquisition (may take 5-15 minutes)")
            print("4. Try different serial port (/dev/ttyAMA0, /dev/ttyUSB0)")
        elif success_rate < 50:
            print(f"\n⚠️  WARNING: Low success rate ({success_rate:.1f}%)")
            print("GPS signal may be weak or intermittent.")
        else:
            print(f"\n✅ SUCCESS: GPS is working with {success_rate:.1f}% success rate")
        
        gps_serial.close()
        
    except Exception as e:
        print(f"❌ ERROR: GPS test failed: {e}")
        print("\nTroubleshooting:")
        print("1. Check if GPS module is connected")
        print("2. Verify serial port permissions: sudo usermod -a -G dialout $USER")
        print("3. Enable serial interface: sudo raspi-config > Interface Options > Serial")
        print("4. Try different ports: /dev/ttyAMA0, /dev/ttyUSB0, /dev/ttyS0")

def main():
    parser = argparse.ArgumentParser(description='Test GPS module functionality')
    parser.add_argument('--port', default='/dev/serial0', help='Serial port (default: /dev/serial0)')
    parser.add_argument('--baud', type=int, default=9600, help='Baud rate (default: 9600)')
    parser.add_argument('--duration', type=int, default=30, help='Test duration in seconds (default: 30)')
    parser.add_argument('--raw', action='store_true', help='Show raw NMEA sentences')
    parser.add_argument('--parsed', action='store_true', help='Show parsed GPS data')
    
    args = parser.parse_args()
    
    if not args.raw and not args.parsed:
        # Run both tests by default
        args.raw = True
        args.parsed = True
    
    print("GPS Test Script")
    print(f"Port: {args.port}")
    print(f"Baud: {args.baud}")
    print(f"Duration: {args.duration} seconds")
    print()
    
    try:
        if args.raw:
            test_raw_gps(args.port, args.baud, args.duration)
            print()
            
        if args.parsed:
            test_parsed_gps(args.port, args.baud, args.duration)
            
    except KeyboardInterrupt:
        print("\nTest interrupted by user.")
    except Exception as e:
        print(f"Test failed with error: {e}")

if __name__ == "__main__":
    main()
