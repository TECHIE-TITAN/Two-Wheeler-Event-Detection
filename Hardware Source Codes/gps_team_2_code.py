import serial
import csv
import time
from datetime import datetime
import subprocess
import os

# Replace with your serial port (usually /dev/serial0 or /dev/ttyAMA0)
GPS_PORT = "/dev/serial0"
GPS_BAUD = 9600

# Output CSV file
csv_file = f"data/gps_{datetime.now().strftime('%m%d_%H%M%S')}.csv"

# Ensure data folder exists
os.makedirs("data", exist_ok=True)

# Conversion constants
KNOTS_TO_KMH = 1.852

def enable_gps_port():
    """Enable GPS port with proper permissions"""
    try:
        subprocess.run(['sudo', 'chmod', '666', '/dev/ttyS0'], check=True)
        print("✅ GPS port permissions enabled")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to enable GPS port: {e}")
        return False

def check_port_exists():
    """Check if GPS port exists and is accessible"""
    return os.path.exists('/dev/ttyS0')

def parse_lat_lon(coord_str, direction):
    """Convert GPS coordinate from DDMM.MMMM format to decimal degrees"""
    if not coord_str or not direction:
        return None
    
    try:
        # DDMM.MMMM format - first 2 or 3 digits are degrees, rest are minutes
        if len(coord_str) >= 7:  # Minimum: DD MM.MMM
            if coord_str.find('.') > 4:  # Longitude: DDDMM.MMMM
                degrees = int(coord_str[:3])
                minutes = float(coord_str[3:])
            else:  # Latitude: DDMM.MMMM
                degrees = int(coord_str[:2])
                minutes = float(coord_str[2:])
            
            decimal_deg = degrees + minutes / 60.0
            
            # Apply direction
            if direction in ['S', 'W']:
                decimal_deg = -decimal_deg
            
            return round(decimal_deg, 6)  # 6 decimal places for good precision
    except (ValueError, IndexError):
        pass
    
    return None

print(f"Starting GPS logger with coordinate conversion...")
print(f"Port: {GPS_PORT}")
print(f"Baud: {GPS_BAUD}")
print(f"Output: {csv_file}")
print("="*50)

try:
    # Initial port setup
    if not enable_gps_port():
        raise Exception("Cannot enable GPS port")
    
    with serial.Serial(GPS_PORT, GPS_BAUD, timeout=1) as ser, open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        # Updated headers with decimal coordinates and km/h speed
        writer.writerow(["UTC Time", "Latitude_DD", "Longitude_DD", "Speed_KMH", "Course_Deg", "Date", "Valid", "Raw_Data"])

        print(f"Logging GPS data to {csv_file}... (Ctrl+C to stop)")
        print("Waiting for GPS data...")
        print("-"*50)

        sentence_count = 0
        gprmc_count = 0
        valid_count = 0
        start_time = time.time()
        port_retry_count = 0
        max_port_retries = 5

        try:
            while True:
                try:
                    line = ser.readline().decode("ascii", errors="ignore").strip()
                    port_retry_count = 0  # Reset retry count on successful read
                    
                    if line:
                        sentence_count += 1
                        
                        # Print all NMEA sentences for debugging (optional)
                        if sentence_count <= 20:  # Show first 20 sentences
                            print(f"[{sentence_count:3d}] {line}")
                        
                        if line.startswith("$GPRMC"):
                            gprmc_count += 1
                            parts = line.split(",")
                            
                            # Ensure we have enough parts
                            if len(parts) >= 10:
                                # GPRMC fields
                                utc_time = parts[1] if parts[1] else "N/A"
                                valid = parts[2] if parts[2] else "V"
                                lat_raw = parts[3] if parts[3] else ""
                                lat_dir = parts[4] if parts[4] else ""
                                lon_raw = parts[5] if parts[5] else ""
                                lon_dir = parts[6] if parts[6] else ""
                                speed_knots = parts[7] if parts[7] else "0"
                                course = parts[8] if parts[8] else "0"
                                date = parts[9] if parts[9] else "N/A"

                                # Convert coordinates to decimal degrees
                                latitude_dd = parse_lat_lon(lat_raw, lat_dir)
                                longitude_dd = parse_lat_lon(lon_raw, lon_dir)
                                
                                # Convert speed from knots to km/h
                                try:
                                    speed_kmh = float(speed_knots) * KNOTS_TO_KMH if speed_knots else 0.0
                                    speed_kmh = round(speed_kmh, 2)  # Round to 2 decimal places
                                except ValueError:
                                    speed_kmh = 0.0

                                # Count valid fixes
                                if valid == 'A':
                                    valid_count += 1

                                # Print to terminal with converted values
                                status_symbol = "✅" if valid == 'A' else "❌"
                                elapsed = time.time() - start_time
                                
                                lat_str = f"{latitude_dd:.6f}" if latitude_dd is not None else "N/A"
                                lon_str = f"{longitude_dd:.6f}" if longitude_dd is not None else "N/A"
                                
                                print(f"{status_symbol} [{gprmc_count:3d}] {utc_time} Lat:{lat_str} Lon:{lon_str} Speed:{speed_kmh:.2f}km/h Course:{course}° Valid:{valid} ({elapsed:.1f}s)")

                                # Save to CSV with converted values
                                writer.writerow([
                                    utc_time,
                                    latitude_dd if latitude_dd is not None else "",
                                    longitude_dd if longitude_dd is not None else "", 
                                    speed_kmh,
                                    course,
                                    date,
                                    valid,
                                    line
                                ])
                                
                                # Flush every 10 valid readings
                                if valid_count % 10 == 0:
                                    f.flush()
                            else:
                                print(f"⚠️  Incomplete GPRMC sentence: {line}")
                
                    # Print status every 100 sentences
                    if sentence_count > 0 and sentence_count % 100 == 0:
                        elapsed = time.time() - start_time
                        print(f"Status: {sentence_count} total, {gprmc_count} GPRMC, {valid_count} valid fixes ({elapsed:.1f}s)")

                except serial.SerialException as e:
                    print(f"⚠️ Serial error: {e}")
                    
                    if port_retry_count < max_port_retries:
                        port_retry_count += 1
                        print(f"🔄 Attempting to re-enable port (attempt {port_retry_count}/{max_port_retries})")
                        
                        # Close current connection
                        try:
                            ser.close()
                        except:
                            pass
                        
                        time.sleep(2)  # Wait before retry
                        
                        # Re-enable port and reconnect
                        if enable_gps_port():
                            try:
                                ser.open()
                                print("✅ GPS port reconnected successfully")
                                continue
                            except Exception as reconnect_error:
                                print(f"❌ Reconnection failed: {reconnect_error}")
                        else:
                            print("❌ Failed to re-enable port")
                    else:
                        print("❌ Maximum port retry attempts exceeded")
                        raise e

        except KeyboardInterrupt:
            elapsed = time.time() - start_time
            print(f"\n{'='*50}")
            print("Logging stopped by user.")
            print(f"Statistics:")
            print(f"  Duration: {elapsed:.1f} seconds")
            print(f"  Total sentences: {sentence_count}")
            print(f"  GPRMC sentences: {gprmc_count}")
            print(f"  Valid GPS fixes: {valid_count}")
            print(f"  Success rate: {(valid_count/gprmc_count*100):.1f}%" if gprmc_count > 0 else "  Success rate: 0%")
            print(f"  Output file: {csv_file}")
            
            if valid_count == 0:
                print(f"\n⚠️  WARNING: No valid GPS fixes received!")
                print("Possible issues:")
                print("  - GPS needs more time to acquire satellites")
                print("  - GPS module needs clear view of sky")
                print("  - GPS module may not be properly connected")
            
except serial.SerialException as e:
    print(f"❌ Error opening serial port {GPS_PORT}: {e}")
    
    # Try to fix port permissions and retry once
    print("🔄 Attempting to fix port permissions...")
    if enable_gps_port():
        print("✅ Port permissions fixed. Please restart the program.")
    else:
        print("❌ Could not fix port permissions")
        
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    
print("GPS logger finished.")