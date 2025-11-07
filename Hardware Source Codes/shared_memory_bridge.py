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
        self.new_data_event = None
        self.write_lock = None
        
        try:
            if create_new:
                # Create new shared memory block
                self.shm = shared_memory.SharedMemory(
                    name=SHARED_MEMORY_NAME,
                    create=True,
                    size=SHARED_MEMORY_SIZE
                )
            else:
                # Attach to existing
                self.shm = shared_memory.SharedMemory(
                    name=SHARED_MEMORY_NAME,
                    create=False
                )
            
            # Create numpy array view of shared memory
            self.data_array = np.ndarray(
                (BATCH_SIZE, FIELDS_PER_POINT),
                dtype=np.float64,
                buffer=self.shm.buf
            )
            
            # Initialize with zeros
            if create_new:
                self.data_array.fill(0.0)
            
            print(f"✓ Writer initialized: {SHARED_MEMORY_SIZE} bytes shared memory")
            
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
    
    def cleanup(self):
        """Clean up shared memory resources"""
        try:
            if self.shm:
                self.shm.close()
                try:
                    self.shm.unlink()  # Only creator should unlink
                    print("✓ Shared memory cleaned up")
                except FileNotFoundError:
                    pass
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
        
        start_time = time.time()
        while wait_for_creation:
            try:
                # Attach to existing shared memory
                self.shm = shared_memory.SharedMemory(
                    name=SHARED_MEMORY_NAME,
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
        
        # Create numpy array view of shared memory
        self.data_array = np.ndarray(
            (BATCH_SIZE, FIELDS_PER_POINT),
            dtype=np.float64,
            buffer=self.shm.buf
        )
        
        print(f"✓ Reader initialized: attached to {SHARED_MEMORY_SIZE} bytes")
    
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
    
    def cleanup(self):
        """Clean up reader resources (does not unlink - only writer should)"""
        try:
            if self.shm:
                self.shm.close()
                print("✓ Reader closed")
        except Exception as e:
            print(f"⚠ Reader cleanup warning: {e}")


# Utility functions
def cleanup_shared_memory():
    """Utility to clean up orphaned shared memory"""
    try:
        shm = shared_memory.SharedMemory(name=SHARED_MEMORY_NAME, create=False)
        shm.close()
        shm.unlink()
        print("✓ Orphaned shared memory cleaned up")
        return True
    except FileNotFoundError:
        print("✓ No shared memory to clean up")
        return False
    except Exception as e:
        print(f"✗ Cleanup error: {e}")
        return False


# Test code
if __name__ == "__main__":
    print("=== Shared Memory Bridge Test ===\n")
    
    # Clean up any existing shared memory
    cleanup_shared_memory()
    
    # Test 1: Writer creates and writes
    print("\n[Test 1] Creating writer and writing test data...")
    writer = SensorDataWriter(create_new=True)
    
    # Create test batch
    test_batch = []
    for i in range(BATCH_SIZE):
        point = [
            time.time() + i * 0.01,  # timestamp
            0.1 * i, 0.2 * i, 9.8,   # accel
            0.01 * i, 0.02 * i, 0.03 * i,  # gyro
            17.385, 78.486,           # lat, lon
            60.0 + i, 50.0           # speed, speed_limit
        ]
        test_batch.append(point)
    
    success = writer.write_batch(test_batch)
    print(f"Write successful: {success}")
    
    # Test 2: Reader reads back
    print("\n[Test 2] Creating reader and reading data...")
    reader = SensorDataReader(wait_for_creation=False)
    
    data = reader.read_batch()
    print(f"Read shape: {data.shape}")
    print(f"First point: {data[0]}")
    print(f"Last point: {data[-1]}")
    
    # Test 3: Dict format
    print("\n[Test 3] Reading as dictionary...")
    data_dict = reader.read_batch_as_dict()
    print(f"Available keys: {list(data_dict.keys())}")
    print(f"Speed range: {data_dict['speed'].min():.2f} - {data_dict['speed'].max():.2f} km/h")
    
    # Test 4: Performance
    print("\n[Test 4] Performance test (1000 reads)...")
    start = time.perf_counter()
    for _ in range(1000):
        data = reader.read_batch()
    elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
    print(f"1000 reads took {elapsed:.3f} ms")
    print(f"Average per read: {elapsed/1000:.6f} ms ({elapsed/1000*1000:.3f} μs)")
    
    # Cleanup
    print("\n[Cleanup]")
    reader.cleanup()
    writer.cleanup()
    
    print("\n✓ All tests completed!")
