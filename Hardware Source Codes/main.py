import time
import ldr
import gps

def main():
    # Setup sensors
    ldr.setup()
    gps_serial = gps.setup()

    try:
        while True:
            # LDR status
            light_status = ldr.get_light_status()

            # GPS data
            gps_info = gps.get_gps_data(gps_serial)
            if gps_info:
                print(f"{light_status} | Lat: {gps_info['latitude']} | Lon: {gps_info['longitude']}")
            else:
                print(f"{light_status} | Waiting for GPS fix...")

            time.sleep(1)

    except KeyboardInterrupt:
        pass
    finally:
        ldr.cleanup()
        gps_serial.close()

if __name__ == "__main__":
    main()
