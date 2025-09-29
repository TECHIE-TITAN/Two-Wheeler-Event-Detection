# GPS Troubleshooting Guide

## Overview
This guide helps you diagnose and fix GPS issues in your Two-Wheeler Event Detection system.

## Quick Test
1. **Run the GPS test script first:**
   ```bash
   cd "Hardware Source Codes"
   python3 test_gps.py
   ```

2. **Or test with specific parameters:**
   ```bash
   python3 test_gps.py --port /dev/serial0 --duration 60 --parsed
   ```

## Common Issues and Solutions

### 1. "Could not open serial port" Error
**Problem:** GPS module not accessible via serial port.

**Solutions:**
- Check physical connections to GPS module
- Try alternative ports:
  ```bash
  python3 test_gps.py --port /dev/ttyAMA0
  python3 test_gps.py --port /dev/ttyUSB0
  ```
- Enable serial interface:
  ```bash
  sudo raspi-config
  # Navigate to: Interface Options > Serial Port
  # Enable serial port hardware: Yes
  # Enable serial console: No (for Raspberry Pi)
  ```
- Fix permissions:
  ```bash
  sudo usermod -a -G dialout $USER
  # Logout and login again
  ```

### 2. "No GPS data received" 
**Problem:** Port opens but no NMEA sentences received.

**Solutions:**
- Check GPS module power (usually 3.3V or 5V)
- Verify wiring:
  - GPS TX → Raspberry Pi RX
  - GPS RX → Raspberry Pi TX  
  - GPS GND → Raspberry Pi GND
  - GPS VCC → Raspberry Pi 3.3V/5V
- Check baud rate (try 4800, 9600, 38400)

### 3. "No valid GPS fixes" (Status: V instead of A)
**Problem:** GPS receives data but can't get satellite fix.

**Solutions:**
- **Move outdoors** with clear sky view
- **Wait longer** - initial fix can take 5-15 minutes
- Check GPS antenna connection
- Avoid interference from WiFi/Bluetooth

### 4. Intermittent GPS readings
**Problem:** GPS works sometimes but not consistently.

**Solutions:**
- Check loose connections
- Add decoupling capacitors near GPS module
- Use shielded cables for long connections
- Check power supply stability

## Hardware Debugging

### Check Serial Port Availability
```bash
ls -la /dev/tty* | grep -E "(serial|AMA|USB)"
```

### Monitor Raw Serial Data
```bash
sudo minicom -b 9600 -o -D /dev/serial0
# or
sudo screen /dev/serial0 9600
```

### Test with Different Baud Rates
```bash
python3 test_gps.py --baud 4800
python3 test_gps.py --baud 38400
```

## Understanding GPS Output

### GPRMC Sentence Format
```
$GPRMC,hhmmss.ss,A,ddmm.mm,N,dddmm.mm,E,x.x,x.x,ddmmyy,x.x,E*hh
```
- `A` = Valid fix, `V` = Invalid
- Position in degrees and minutes format
- Speed in knots
- Must have clear format for parsing

### Expected Behavior
- **Cold start:** 5-15 minutes for first fix
- **Warm start:** 30 seconds - 2 minutes  
- **Hot start:** 5-30 seconds
- Update rate: Usually 1Hz (1 reading per second)

## Testing Steps

1. **Hardware Test:**
   ```bash
   python3 test_gps.py --raw --duration 60
   ```
   Should show NMEA sentences.

2. **Parsing Test:**
   ```bash
   python3 test_gps.py --parsed --duration 120
   ```
   Should show parsed coordinates.

3. **Standalone Logging:**
   ```bash
   python3 gps_team_2_code.py
   ```

4. **Full System Test:**
   ```bash
   python3 main2.py
   ```

## File Descriptions

- **`gps_utils.py`** - Core GPS utilities with improved error handling
- **`test_gps.py`** - Comprehensive GPS testing script  
- **`gps_team_2_code.py`** - Standalone GPS logger with diagnostics
- **`main2.py`** - Main application with GPS integration

## Getting Help

If GPS still doesn't work after following this guide:

1. Run the test script and save output:
   ```bash
   python3 test_gps.py --raw --duration 60 > gps_debug.txt 2>&1
   ```

2. Check system logs:
   ```bash
   dmesg | grep -i serial
   dmesg | grep -i gps
   ```

3. Verify hardware with multimeter:
   - Check power voltage
   - Test continuity of connections
   - Verify ground connections
