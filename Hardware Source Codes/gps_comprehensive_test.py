#!/usr/bin/env python3
"""
Comprehensive GPS Testing Script

This script will help diagnose GPS issues and test both your gps_utils.py 
and the team 2 code approach.
"""

import os
import sys
import time
import subprocess

def check_permissions():
    """Check if user has proper serial permissions."""
    import pwd
    import grp
    
    username = pwd.getpwuid(os.getuid()).pw_name
    groups = [grp.getgrgid(gid).gr_name for gid in os.getgroups()]
    
    print(f"Current user: {username}")
    print(f"User groups: {', '.join(groups)}")
    
    if 'dialout' in groups:
        print("✓ User has serial port permissions")
        return True
    else:
        print("✗ User lacks serial port permissions")
        print("  Run: sudo usermod -a -G dialout $USER")
        print("  Then logout and login again")
        return False

def test_gps_team2_approach():
    """Test the team 2 GPS approach."""
    print("\n=== Testing Team 2 GPS Approach ===")
    
    try:
        import serial
        
        # Try the default GPS port
        gps_port = "/dev/serial0"
        
        print(f"Attempting to open {gps_port}...")
        
        try:
            with serial.Serial(gps_port, 9600, timeout=2) as ser:
                print(f"✓ Successfully opened {gps_port}")
                
                print("Reading GPS data for 10 seconds...")
                start_time = time.time()
                lines_received = 0
                gprmc_count = 0
                
                while time.time() - start_time < 10:
                    try:
                        line = ser.readline().decode("ascii", errors="ignore").strip()
                        if line:
                            lines_received += 1
                            
                            if line.startswith("$GPRMC"):
                                gprmc_count += 1
                                parts = line.split(",")
                                status = parts[2] if len(parts) > 2 else "?"
                                
                                print(f"GPRMC #{gprmc_count}: Status={status}")
                                if len(parts) > 9:
                                    print(f"  Time: {parts[1]}")
                                    print(f"  Lat: {parts[3]} {parts[4]}")
                                    print(f"  Lon: {parts[5]} {parts[6]}")
                                    print(f"  Speed: {parts[7]} knots")
                                
                            elif line.startswith("$GP") or line.startswith("$GN"):
                                print(f"GPS sentence: {line[:50]}...")
                    
                    except Exception as e:
                        print(f"Error reading line: {e}")
                        break
                
                print(f"\nResults: {lines_received} lines, {gprmc_count} GPRMC sentences")
                
        except serial.SerialException as e:
            print(f"✗ Could not open {gps_port}: {e}")
            
            # Try alternative ports
            alt_ports = ["/dev/ttyS0", "/dev/ttyAMA0", "/dev/ttyUSB0"]
            for port in alt_ports:
                if os.path.exists(port):
                    print(f"Trying alternative port {port}...")
                    try:
                        with serial.Serial(port, 9600, timeout=1) as ser:
                            print(f"✓ {port} opened successfully")
                            return port
                    except:
                        print(f"✗ {port} failed")
            
            return None
            
    except ImportError:
        print("✗ pyserial not installed. Run: pip install pyserial")
        return None

def test_gps_utils():
    """Test the gps_utils.py module."""
    print("\n=== Testing gps_utils.py ===")
    
    try:
        import gps_utils
        
        print("Attempting to initialize GPS...")
        try:
            gps_serial = gps_utils.init_gps()
            print("✓ GPS initialized successfully")
            
            print("Testing GPS data reading...")
            for i in range(5):
                data = gps_utils.get_gps_data(gps_serial)
                print(f"Reading {i+1}: {data}")
                time.sleep(2)
            
            gps_serial.close()
            
        except Exception as e:
            print(f"✗ GPS initialization failed: {e}")
            
    except ImportError as e:
        print(f"✗ Could not import gps_utils: {e}")

def check_raspberry_pi_config():
    """Check Raspberry Pi specific configuration."""
    print("\n=== Checking Raspberry Pi Configuration ===")
    
    # Check if running on Raspberry Pi
    try:
        with open("/proc/device-tree/model", "r") as f:
            model = f.read().strip()
            if "Raspberry Pi" in model:
                print(f"✓ Running on: {model}")
                
                # Check UART configuration
                try:
                    result = subprocess.run(["raspi-config", "nonint", "get_serial"], 
                                          capture_output=True, text=True)
                    if result.returncode == 0:
                        if result.stdout.strip() == "0":
                            print("✓ UART is enabled")
                        else:
                            print("✗ UART is disabled")
                            print("  Enable with: sudo raspi-config -> Interface Options -> Serial Port")
                except:
                    print("? Could not check UART status (raspi-config not available)")
                    
            else:
                print(f"? Not a Raspberry Pi: {model}")
                
    except FileNotFoundError:
        print("? Not running on Raspberry Pi")

def main():
    print("=== Comprehensive GPS Testing ===\n")
    
    # Check permissions first
    if not check_permissions():
        print("\n⚠ Serial permissions issue detected!")
        print("   Fix permissions first, then run this script again.")
        return
    
    # Check Pi configuration
    check_raspberry_pi_config()
    
    # Test Team 2 approach
    working_port = test_gps_team2_approach()
    
    # Test gps_utils
    test_gps_utils()
    
    print("\n=== Recommendations ===")
    
    if working_port:
        print(f"✓ GPS appears to be working on {working_port}")
        print("  Make sure your code uses this port")
    else:
        print("✗ No working GPS port found")
        print("  Check GPS module connections and power")
        print("  For Pi GPIO GPS: Enable UART in raspi-config")
        print("  For USB GPS: Check with 'lsusb' command")

if __name__ == "__main__":
    main()
