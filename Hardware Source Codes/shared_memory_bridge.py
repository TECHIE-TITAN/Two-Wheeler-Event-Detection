"""
Shared Memory Bridge for High-Speed Data Transfer
Enables zero-copy communication between main2.py and Warning_Generate.py

Architecture:
- Shared memory buffer holds one batch of 104 sensor data points
- Each point has 11 fields: timestamp, acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, lat, lon, speed, speed_limit
- Writer (main2.py) writes batch when complete
- Reader (Warning_Generate.py) reads on notification

Latency: ~0.01ms (sub-millisecond)
"""

import numpy as np
from multiprocessing import shared_memory, Lock, Event
import struct
import time

# Configuration
BATCH_SIZE = 104
FIELDS_PER_POINT = 11  # timestamp, acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, lat, lon, speed, speed_limit
SHARED_MEMORY_NAME = "two_wheeler_sensor_data"
SHARED_MEMORY_SIZE = BATCH_SIZE * FIELDS_PER_POINT * 8  # 8 bytes per float64 = 9152 bytes

# Ride control flag shared memory
RIDE_FLAG_MEMORY_NAME = "two_wheeler_ride_flag"
RIDE_FLAG_SIZE = 16  # 8 bytes for ride_active flag + 8 bytes for ride_id

# Field indices for data access
FIELD_TIMESTAMP = 0
FIELD_ACC_X = 1
FIELD_ACC_Y = 2
FIELD_ACC_Z = 3
FIELD_GYRO_X = 4
FIELD_GYRO_Y = 5
FIELD_GYRO_Z = 6
FIELD_LAT = 7
FIELD_LON = 8
FIELD_SPEED = 9
FIELD_SPEED_LIMIT = 10


class SensorDataWriter:
    """Writer side - used by main2.py to write sensor data batches"""
    
    def __init__(self, create_new=True):
        """
        Initialize shared memory writer
        
        Args:
            create_new: If True, creates new shared memory (use for main process)
                       If False, attaches to existing (use for testing)
        """
        self.batch_size = BATCH_SIZE
        self.fields_per_point = FIELDS_PER_POINT
        self.shm = None
        self.data_array = None
        self.flag_shm = None
        self.flag_array = None
        
        try:
            if create_new:
                # Create new shared memory block for data
                self.shm = shared_memory.SharedMemory(
                    name=SHARED_MEMORY_NAME,
                    create=True,
                    size=SHARED_MEMORY_SIZE
                )
                # Create new shared memory block for ride flag
                self.flag_shm = shared_memory.SharedMemory(
                    name=RIDE_FLAG_MEMORY_NAME,
                    create=True,
                    size=RIDE_FLAG_SIZE
                )
            else:
                # Attach to existing
                self.shm = shared_memory.SharedMemory(
                    name=SHARED_MEMORY_NAME,
                    create=False
                )
                self.flag_shm = shared_memory.SharedMemory(
                    name=RIDE_FLAG_MEMORY_NAME,
                    create=False
                )
            
            # Create numpy array view of shared memory
            self.data_array = np.ndarray(
                (BATCH_SIZE, FIELDS_PER_POINT),
                dtype=np.float64,
                buffer=self.shm.buf
            )
            
            # Create flag array: [ride_active (0 or 1), ride_id]
            self.flag_array = np.ndarray(
                2,  # [ride_active, ride_id]
                dtype=np.int64,
                buffer=self.flag_shm.buf
            )
            
            # Initialize with zeros
            if create_new:
                self.data_array.fill(0.0)
                self.flag_array[0] = 0  # ride_active = 0 (inactive)
                self.flag_array[1] = 0  # ride_id = 0
            
            print(f"✓ Writer initialized: {SHARED_MEMORY_SIZE} bytes data + {RIDE_FLAG_SIZE} bytes flag")
            
        except FileExistsError:
            print("⚠ Shared memory already exists. Cleaning up and recreating...")
            self.cleanup()
            self.__init__(create_new=True)
        except Exception as e:
            print(f"✗ Writer initialization error: {e}")
            raise
    
    def write_batch(self, batch_data):
        """
        Write a batch of 104 sensor data points to shared memory
        
        Args:
            batch_data: List of 104 tuples/lists, each with 11 values:
                       (timestamp, acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, 
                        latitude, longitude, speed, speed_limit)
        
        Returns:
            bool: True if write successful
        """
        try:
            if len(batch_data) != BATCH_SIZE:
                print(f"⚠ Warning: Batch size {len(batch_data)} != {BATCH_SIZE}")
                return False
            
            # Write data directly to shared memory array
            for i, point in enumerate(batch_data):
                if len(point) != FIELDS_PER_POINT:
                    print(f"⚠ Warning: Point {i} has {len(point)} fields, expected {FIELDS_PER_POINT}")
                    continue
                self.data_array[i] = point
            
            return True
            
        except Exception as e:
            print(f"✗ Write error: {e}")
            return False
    
    def write_batch_from_arrays(self, timestamps, acc_x, acc_y, acc_z, 
                                gyro_x, gyro_y, gyro_z, 
                                latitudes, longitudes, speeds, speed_limits):
        """
        Write batch from separate numpy arrays (more efficient)
        
        Args:
            All args are numpy arrays of length 104
        """
        try:
            self.data_array[:, FIELD_TIMESTAMP] = timestamps
            self.data_array[:, FIELD_ACC_X] = acc_x
            self.data_array[:, FIELD_ACC_Y] = acc_y
            self.data_array[:, FIELD_ACC_Z] = acc_z
            self.data_array[:, FIELD_GYRO_X] = gyro_x
            self.data_array[:, FIELD_GYRO_Y] = gyro_y
            self.data_array[:, FIELD_GYRO_Z] = gyro_z
            self.data_array[:, FIELD_LAT] = latitudes
            self.data_array[:, FIELD_LON] = longitudes
            self.data_array[:, FIELD_SPEED] = speeds
            self.data_array[:, FIELD_SPEED_LIMIT] = speed_limits
            return True
        except Exception as e:
            print(f"✗ Array write error: {e}")
            return False
    
    def set_ride_active(self, ride_id):
        """
        Set ride as active with given ride_id
        
        Args:
            ride_id: Integer ride identifier
        """
        try:
            self.flag_array[0] = 1  # ride_active = 1
            self.flag_array[1] = int(ride_id)
            return True
        except Exception as e:
            print(f"✗ Set ride active error: {e}")
            return False
    
    def set_ride_inactive(self):
        """Set ride as inactive (pauses Warning_Generate.py processing)"""
        try:
            self.flag_array[0] = 0  # ride_active = 0
            return True
        except Exception as e:
            print(f"✗ Set ride inactive error: {e}")
            return False
    
    def cleanup(self):
        """Clean up shared memory resources"""
        try:
            if self.shm:
                self.shm.close()
                try:
                    self.shm.unlink()  # Only creator should unlink
                except FileNotFoundError:
                    pass
            if self.flag_shm:
                self.flag_shm.close()
                try:
                    self.flag_shm.unlink()
                except FileNotFoundError:
                    pass
            print("✓ Shared memory cleaned up")
        except Exception as e:
            print(f"⚠ Cleanup warning: {e}")


class SensorDataReader:
    """Reader side - used by Warning_Generate.py to read sensor data batches"""
    
    def __init__(self, wait_for_creation=True, timeout=10.0):
        """
        Initialize shared memory reader
        
        Args:
            wait_for_creation: If True, waits for writer to create shared memory
            timeout: Maximum seconds to wait for shared memory creation
        """
        self.batch_size = BATCH_SIZE
        self.fields_per_point = FIELDS_PER_POINT
        self.shm = None
        self.data_array = None
        self.flag_shm = None
        self.flag_array = None
        
        start_time = time.time()
        while wait_for_creation:
            try:
                # Attach to existing shared memory
                self.shm = shared_memory.SharedMemory(
                    name=SHARED_MEMORY_NAME,
                    create=False
                )
                self.flag_shm = shared_memory.SharedMemory(
                    name=RIDE_FLAG_MEMORY_NAME,
                    create=False
                )
                break
            except FileNotFoundError:
                if time.time() - start_time > timeout:
                    raise TimeoutError(f"Shared memory not created after {timeout}s")
                print("⏳ Waiting for shared memory creation...")
                time.sleep(0.5)
        
        if not wait_for_creation:
            self.shm = shared_memory.SharedMemory(
                name=SHARED_MEMORY_NAME,
                create=False
            )
            self.flag_shm = shared_memory.SharedMemory(
                name=RIDE_FLAG_MEMORY_NAME,
                create=False
            )
        
        # Create numpy array view of shared memory
        self.data_array = np.ndarray(
            (BATCH_SIZE, FIELDS_PER_POINT),
            dtype=np.float64,
            buffer=self.shm.buf
        )
        
        # Create flag array view
        self.flag_array = np.ndarray(
            2,  # [ride_active, ride_id]
            dtype=np.int64,
            buffer=self.flag_shm.buf
        )
        
        print(f"✓ Reader initialized: attached to {SHARED_MEMORY_SIZE} bytes data + {RIDE_FLAG_SIZE} bytes flag")
    
    def read_batch(self):
        """
        Read current batch from shared memory
        
        Returns:
            numpy array of shape (104, 11)
        """
        try:
            # Return a copy to avoid race conditions
            return self.data_array.copy()
        except Exception as e:
            print(f"✗ Read error: {e}")
            return None
    
    def read_batch_as_dict(self):
        """
        Read batch and return as dictionary of arrays
        
        Returns:
            dict with keys: timestamps, accel_x, accel_y, accel_z, angular_x, 
                           angular_y, angular_z, latitude, longitude, speed, speed_limit
        """
        try:
            data = self.data_array.copy()
            return {
                'timestamps': data[:, FIELD_TIMESTAMP],
                'accel_x': data[:, FIELD_ACC_X],
                'accel_y': data[:, FIELD_ACC_Y],
                'accel_z': data[:, FIELD_ACC_Z],
                'angular_x': data[:, FIELD_GYRO_X],
                'angular_y': data[:, FIELD_GYRO_Y],
                'angular_z': data[:, FIELD_GYRO_Z],
                'latitude': data[:, FIELD_LAT],
                'longitude': data[:, FIELD_LON],
                'speed': data[:, FIELD_SPEED],
                'speed_limit': data[:, FIELD_SPEED_LIMIT]
            }
        except Exception as e:
            print(f"✗ Read dict error: {e}")
            return None
    
    def is_ride_active(self):
        """
        Check if ride is currently active
        
        Returns:
            bool: True if ride is active, False otherwise
        """
        try:
            return bool(self.flag_array[0])
        except Exception as e:
            print(f"✗ Read flag error: {e}")
            return False
    
    def get_ride_id(self):
        """
        Get current ride ID
        
        Returns:
            int: Current ride ID
        """
        try:
            return int(self.flag_array[1])
        except Exception as e:
            print(f"✗ Read ride_id error: {e}")
            return 0
    
    def cleanup(self):
        """Clean up reader resources (does not unlink - only writer should)"""
        try:
            if self.shm:
                self.shm.close()
            if self.flag_shm:
                self.flag_shm.close()
            print("✓ Reader closed")
        except Exception as e:
            print(f"⚠ Reader cleanup warning: {e}")


# Utility functions
def cleanup_shared_memory():
    """Utility to clean up orphaned shared memory"""
    success = True
    try:
        shm = shared_memory.SharedMemory(name=SHARED_MEMORY_NAME, create=False)
        shm.close()
        shm.unlink()
        print("✓ Orphaned data shared memory cleaned up")
    except FileNotFoundError:
        print("✓ No data shared memory to clean up")
    except Exception as e:
        print(f"✗ Data memory cleanup error: {e}")
        success = False
    
    try:
        flag_shm = shared_memory.SharedMemory(name=RIDE_FLAG_MEMORY_NAME, create=False)
        flag_shm.close()
        flag_shm.unlink()
        print("✓ Orphaned flag shared memory cleaned up")
    except FileNotFoundError:
        print("✓ No flag shared memory to clean up")
    except Exception as e:
        print(f"✗ Flag memory cleanup error: {e}")
        success = False
    
    return success
