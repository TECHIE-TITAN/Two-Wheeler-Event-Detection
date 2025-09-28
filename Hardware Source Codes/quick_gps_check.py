#!/usr/bin/env python3
"""
Quick GPS Check - Minimal script to quickly verify GPS functionality
"""

import serial
import time
import sys

def quick_gps_check(port="/dev/serial0", baud=9600, timeout_seconds=30):
    """Quick check to see if GPS is working"""
    print(f"Quick GPS Check on {port} at {baud} baud")
    print(f"Will run for maximum {timeout_seconds} seconds...")
    print("Looking for valid GPS fixes (GPRMC sentences with status 'A')")
    print("-" * 50)
    
    try:
        with serial.Serial(port, baud, timeout=1) as ser:
            start_time = time.time()
            sentences = 0
            gprmc_sentences = 0
            valid_fixes = 0
            
            while (time.time() - start_time) < timeout_seconds:
                try:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    if line:
                        sentences += 1
                        
                        if line.startswith("$GPRMC"):
                            gprmc_sentences += 1
                            parts = line.split(",")
                            
                            if len(parts) >= 10:
                                status = parts[2]
                                if status == 'A':  # Valid fix
                                    valid_fixes += 1
                                    lat_raw = parts[3]
                                    lat_dir = parts[4] 
                                    lon_raw = parts[5]
                                    lon_dir = parts[6]
                                    speed = parts[7]
                                    
                                    print(f"✅ VALID GPS FIX #{valid_fixes}:")
                                    print(f"   Raw: {lat_raw}{lat_dir}, {lon_raw}{lon_dir}, {speed} knots")
                                    
                                    if valid_fixes >= 3:  # Got enough samples
                                        print(f"\n🎉 SUCCESS! GPS is working properly.")
                                        print(f"   Received {valid_fixes} valid fixes out of {gprmc_sentences} GPRMC sentences")
                                        return True
                                        
                                elif gprmc_sentences % 10 == 0:  # Status update every 10 GPRMC
                                    elapsed = time.time() - start_time
                                    print(f"⏳ Waiting for GPS fix... ({elapsed:.1f}s, status: {status})")
                        
                        # General status update
                        if sentences % 100 == 0:
                            elapsed = time.time() - start_time
                            print(f"📡 Status: {sentences} sentences, {gprmc_sentences} GPRMC, {valid_fixes} fixes ({elapsed:.1f}s)")
                            
                except UnicodeDecodeError:
                    continue  # Skip malformed data
                    
            # Timeout reached
            elapsed = time.time() - start_time
            print(f"\n⏰ Timeout reached ({elapsed:.1f}s)")
            print(f"Results: {sentences} sentences, {gprmc_sentences} GPRMC, {valid_fixes} valid fixes")
            
            if sentences == 0:
                print("❌ PROBLEM: No data received from GPS module")
                print("   Check connections and power")
                return False
            elif gprmc_sentences == 0:
                print("❌ PROBLEM: No GPRMC sentences found")
                print("   GPS module may be misconfigured")
                return False
            elif valid_fixes == 0:
                print("⚠️  WARNING: GPS module working but no satellite fix")
                print("   Try outdoors with clear sky view and wait longer")
                return False
            else:
                print(f"✅ GPS working but slow ({valid_fixes} fixes in {elapsed:.1f}s)")
                return True
                
    except serial.SerialException as e:
        print(f"❌ ERROR: Cannot open serial port {port}")
        print(f"   Error: {e}")
        print("   Try: sudo usermod -a -G dialout $USER")
        print("   Or try different port: /dev/ttyAMA0, /dev/ttyUSB0")
        return False
    
    except Exception as e:
        print(f"❌ ERROR: Unexpected problem: {e}")
        return False

if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/serial0"
    
    success = quick_gps_check(port)
    
    if success:
        print("\n🎯 GPS CHECK PASSED - You can now run main2.py")
    else:
        print("\n🚨 GPS CHECK FAILED - Fix GPS issues before running main application")
        print("\nNext steps:")
        print("1. Run: python3 test_gps.py --raw --duration 60")
        print("2. Check GPS_TROUBLESHOOTING.md for detailed help")
        print("3. Verify hardware connections")
        
    sys.exit(0 if success else 1)
