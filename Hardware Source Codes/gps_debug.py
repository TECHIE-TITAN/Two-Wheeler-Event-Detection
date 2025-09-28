#!/usr/bin/env python3
"""
GPS Debug and Testing Utility

This script helps diagnose GPS connection issues and test GPS functionality.
Run this before your main application to verify GPS is working properly.
"""

import serial
import time
import glob
import os
import gps_utils

def list_serial_ports():
    """List all available serial ports."""
    ports = []
    
    # Common serial port patterns
    patterns = ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyS*", "/dev/ttyAMA*", "/dev/serial*"]
    
    for pattern in patterns:
        ports.extend(glob.glob(pattern))
    
    # Filter existing ports
    existing_ports = [port for port in ports if os.path.exists(port)]
    
    return existing_ports

def test_serial_port(port, baud=9600, test_duration=5):
    """Test if a serial port has GPS data."""
    print(f"\n--- Testing {port} at {baud} baud ---")
    
    try:
        ser = serial.Serial(port, baud, timeout=1)
        print(f"✓ Successfully opened {port}")
        
        print(f"Testing for {test_duration} seconds...")
        start_time = time.time()
        lines_received = 0
        gps_lines = 0
        
        while time.time() - start_time < test_duration:
            try:
                if ser.in_waiting > 0:
                    line = ser.readline().decode('ascii', errors='ignore').strip()
                    lines_received += 1
                    
                    if line.startswith('$GP') or line.startswith('$GN'):
                        gps_lines += 1
                        print(f"GPS: {line}")
                        
                        # Check for specific GPS sentences
                        if line.startswith('$GPRMC') or line.startswith('$GNRMC'):
                            parts = line.split(',')
                            if len(parts) > 2:
                                status = parts[2]
                                if status == 'A':
                                    print("✓ GPS has satellite fix!")
                                elif status == 'V':
                                    print("⚠ GPS no satellite fix (searching...)")
                else:
                    time.sleep(0.1)
                    
            except Exception as e:
                print(f"Error reading from {port}: {e}")
                break
        
        ser.close()
        
        print(f"Results for {port}:")
        print(f"  Lines received: {lines_received}")
        print(f"  GPS sentences: {gps_lines}")
        
        if gps_lines > 0:
            print(f"✓ {port} appears to be a GPS device")
            return True
        else:
            print(f"✗ {port} does not appear to be a GPS device")
            return False
            
    except serial.SerialException as e:
        print(f"✗ Could not open {port}: {e}")
        return False

def check_permissions():
    """Check serial port permissions."""
    import pwd
    import grp
    
    username = pwd.getpwuid(os.getuid()).pw_name
    groups = [grp.getgrgid(gid).gr_name for gid in os.getgroups()]
    
    print(f"\nCurrent user: {username}")
    print(f"User groups: {', '.join(groups)}")
    
    # Check if user is in dialout group (needed for serial port access)
    if 'dialout' in groups:
        print("✓ User is in 'dialout' group")
    else:
        print("⚠ User is NOT in 'dialout' group")
        print("  Run: sudo usermod -a -G dialout $USER")
        print("  Then logout and login again")

def main():
    print("=== GPS Debug and Testing Utility ===\n")
    
    # Check permissions
    check_permissions()
    
    # List available ports
    ports = list_serial_ports()
    print(f"\nAvailable serial ports: {ports}")
    
    if not ports:
        print("No serial ports found!")
        print("Possible issues:")
        print("1. GPS module not connected")
        print("2. GPS module not powered")
        print("3. USB GPS dongle not plugged in")
        print("4. GPIO UART not enabled (for Pi GPIO GPS modules)")
        return
    
    # Test each port
    working_ports = []
    for port in ports:
        if test_serial_port(port):
            working_ports.append(port)
    
    print(f"\n=== Summary ===")
    if working_ports:
        print(f"GPS devices found on: {working_ports}")
        print(f"Recommended port for main application: {working_ports[0]}")
    else:
        print("No GPS devices found!")
        print("\nTroubleshooting steps:")
        print("1. Check GPS module power/connections")
        print("2. For Pi GPIO GPS: Enable UART in raspi-config")
        print("3. For USB GPS: Check if device shows up in 'lsusb'")
        print("4. Check if GPS module needs time to get satellite fix (go outside)")
    
    # Test gps_utils functions
    if working_ports:
        print(f"\n=== Testing gps_utils with {working_ports[0]} ===")
        try:
            gps_serial = gps_utils.init_gps(working_ports[0])
            print("✓ gps_utils.init_gps() successful")
            
            # Test a few readings
            for i in range(5):
                data = gps_utils.get_gps_data(gps_serial)
                print(f"Reading {i+1}: {data}")
                time.sleep(1)
            
            gps_serial.close()
            
        except Exception as e:
            print(f"✗ Error testing gps_utils: {e}")

if __name__ == "__main__":
    main()
