import threading
import time
import numpy as np
from dataclasses import dataclass
from typing import List
import tensorflow as tf
from tensorflow import keras

# Global data structure
@dataclass
class SensorData:
    timestamp: float
    accel_x: float
    accel_y: float
    accel_z: float
    angular_x: float
    angular_y: float
    angular_z: float
    latitude: float
    longitude: float
    speed: float
    speed_limit: float

# Global variables - batch of 104 data points
BATCH_SIZE = 104
current_data_batch: List[SensorData] = []
data_lock = threading.Lock()

# Warning tuple: [overspeeding, bump, pothole, car_distance, speedy_turns, harsh_braking, sudden_accel]
warning_state = [0, 0, 0, 0, 0, 0, 0]
warning_lock = threading.Lock()

# LSTM model - load from same folder
try:
    lstm_model = keras.models.load_model('lstm_model.h5')
    print("LSTM model loaded successfully")
except Exception as e:
    print(f"Error loading LSTM model: {e}")
    lstm_model = None

# Configuration parameters
SPEEDY_TURN_THRESHOLD = 0.5  # rad/s
HARSH_BRAKE_THRESHOLD = -4.0  # m/s^2
SUDDEN_ACCEL_THRESHOLD = 3.5  # m/s^2
CAR_DISTANCE_THRESHOLD = 2.0  # meters
SPEED_BUFFER = 5.0  # km/h buffer for overspeeding
POTHOLE_Z_THRESHOLD = 2.5  # m/s^2 vertical acceleration spike


def update_warning(index: int, value: int):
    """Thread-safe warning update"""
    with warning_lock:
        warning_state[index] = value


def get_current_data_batch() -> List[SensorData]:
    """Thread-safe data batch access"""
    with data_lock:
        return current_data_batch.copy()


def extract_batch_features(batch: List[SensorData]) -> dict:
    """Extract numpy arrays from batch for analysis"""
    if not batch:
        return None
    
    return {
        'timestamps': np.array([d.timestamp for d in batch]),
        'accel_x': np.array([d.accel_x for d in batch]),
        'accel_y': np.array([d.accel_y for d in batch]),
        'accel_z': np.array([d.accel_z for d in batch]),
        'angular_x': np.array([d.angular_x for d in batch]),
        'angular_y': np.array([d.angular_y for d in batch]),
        'angular_z': np.array([d.angular_z for d in batch]),
        'latitude': np.array([d.latitude for d in batch]),
        'longitude': np.array([d.longitude for d in batch]),
        'speed': np.array([d.speed for d in batch]),
        'speed_limit': np.array([d.speed_limit for d in batch])
    }


def lstm_prediction_thread():
    """Thread for LSTM model predictions using 104 data points"""
    global lstm_model
    
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            features = extract_batch_features(batch)
            
            # Prepare input for LSTM (104 timesteps, 7 features)
            input_sequence = np.stack([
                features['accel_x'],
                features['accel_y'],
                features['accel_z'],
                features['angular_x'],
                features['angular_y'],
                features['angular_z'],
                features['speed']
            ], axis=1)
            
            # Reshape to (1, 104, 7) for batch prediction
            input_sequence = input_sequence.reshape(1, BATCH_SIZE, 7)
            
            if lstm_model is not None:
                # Predict: left, right, straight, stop, bump
                prediction = lstm_model.predict(input_sequence, verbose=0)
                
                # Check for bump detection (adjust index based on your model output)
                if prediction[0][-1] > 0.5:  # Assuming last output is bump
                    update_warning(1, 1)  # Update bump warning
                else:
                    update_warning(1, 0)
            
            time.sleep(0.05)
            
        except Exception as e:
            print(f"LSTM thread error: {e}")
            time.sleep(0.1)


def overspeeding_thread():
    """Thread for overspeeding detection using batch data"""
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            features = extract_batch_features(batch)
            
            # Check if any point in batch exceeds speed limit
            overspeeding = np.any(features['speed'] > features['speed_limit'] + SPEED_BUFFER)
            
            if overspeeding:
                update_warning(0, 1)
            else:
                update_warning(0, 0)
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Overspeeding thread error: {e}")
            time.sleep(0.1)


def speedy_turns_thread():
    """Thread for detecting speedy/sharp turns using batch data"""
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            features = extract_batch_features(batch)
            
            # Calculate angular velocity magnitude for each point
            angular_vel = np.sqrt(
                features['angular_x']**2 + 
                features['angular_y']**2 + 
                features['angular_z']**2
            )
            
            # Check if any turn exceeds threshold while at speed
            speedy_turn = np.any(
                (angular_vel > SPEEDY_TURN_THRESHOLD) & (features['speed'] > 20)
            )
            
            if speedy_turn:
                update_warning(4, 1)
            else:
                update_warning(4, 0)
            
            time.sleep(0.05)
            
        except Exception as e:
            print(f"Speedy turns thread error: {e}")
            time.sleep(0.1)


def pothole_detection_thread():
    """Thread for pothole detection using vertical acceleration spikes"""
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            features = extract_batch_features(batch)
            
            # Detect sudden vertical acceleration changes (pothole signature)
            z_accel = features['accel_z']
            
            # Look for sharp negative spikes in vertical acceleration
            pothole_detected = np.any(np.abs(z_accel - 9.8) > POTHOLE_Z_THRESHOLD)
            
            if pothole_detected:
                update_warning(2, 1)
            else:
                update_warning(2, 0)
            
            time.sleep(0.05)
            
        except Exception as e:
            print(f"Pothole thread error: {e}")
            time.sleep(0.1)


def car_distance_thread():
    """Thread for car distance monitoring (requires external sensor/camera data)"""
    while True:
        try:
            # Placeholder: In real implementation, get distance from radar/camera
            # This should be integrated with your actual distance sensor
            car_distance = get_simulated_car_distance()
            
            if car_distance < CAR_DISTANCE_THRESHOLD:
                update_warning(3, 1)
            else:
                update_warning(3, 0)
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Car distance thread error: {e}")
            time.sleep(0.1)


def harsh_braking_thread():
    """Thread for harsh braking detection using slope of 104 data points"""
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            features = extract_batch_features(batch)
            
            # Calculate deceleration using forward-facing acceleration
            accel_x = features['accel_x']
            timestamps = features['timestamps']
            
            # Calculate slope (rate of change) using linear regression
            if len(timestamps) > 1:
                # Time differences
                time_diffs = np.diff(timestamps)
                
                # Calculate jerk (derivative of acceleration)
                if np.sum(time_diffs) > 0:
                    accel_diffs = np.diff(accel_x)
                    jerk_values = accel_diffs / time_diffs
                    
                    # Check for harsh braking (sharp negative jerk)
                    avg_jerk = np.mean(jerk_values)
                    min_jerk = np.min(jerk_values)
                    
                    if min_jerk < HARSH_BRAKE_THRESHOLD or avg_jerk < HARSH_BRAKE_THRESHOLD / 2:
                        update_warning(5, 1)
                    else:
                        update_warning(5, 0)
            
            time.sleep(0.05)
            
        except Exception as e:
            print(f"Harsh braking thread error: {e}")
            time.sleep(0.1)


def sudden_acceleration_thread():
    """Thread for sudden acceleration detection using slope of 104 data points"""
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            features = extract_batch_features(batch)
            
            # Calculate acceleration slope
            accel_x = features['accel_x']
            timestamps = features['timestamps']
            
            if len(timestamps) > 1:
                # Calculate overall slope using linear regression
                time_normalized = timestamps - timestamps[0]
                
                # Fit line: accel = slope * time + intercept
                if np.std(time_normalized) > 0:
                    slope = np.polyfit(time_normalized, accel_x, 1)[0]
                    
                    # Also check for sudden jumps
                    accel_diffs = np.diff(accel_x)
                    time_diffs = np.diff(timestamps)
                    
                    if np.sum(time_diffs) > 0:
                        instant_slopes = accel_diffs / time_diffs
                        max_instant_slope = np.max(instant_slopes)
                        
                        if slope > SUDDEN_ACCEL_THRESHOLD or max_instant_slope > SUDDEN_ACCEL_THRESHOLD * 2:
                            update_warning(6, 1)
                        else:
                            update_warning(6, 0)
            
            time.sleep(0.05)
            
        except Exception as e:
            print(f"Sudden acceleration thread error: {e}")
            time.sleep(0.1)


def get_simulated_car_distance() -> float:
    """Placeholder for car distance sensor data"""
    # Replace with actual sensor reading
    return 5.0


def update_sensor_data_batch(new_batch: List[SensorData]):
    """Update global sensor data batch (called by data acquisition system)"""
    global current_data_batch
    with data_lock:
        current_data_batch = new_batch[-BATCH_SIZE:]  # Keep only last 104 points


def get_warnings() -> list:
    """Get current warning state"""
    with warning_lock:
        return warning_state.copy()


def start_warning_system():
    """Initialize and start all monitoring threads"""
    threads = [
        threading.Thread(target=lstm_prediction_thread, daemon=True, name="LSTM"),
        threading.Thread(target=overspeeding_thread, daemon=True, name="Overspeeding"),
        threading.Thread(target=speedy_turns_thread, daemon=True, name="SpeedyTurns"),
        threading.Thread(target=pothole_detection_thread, daemon=True, name="Pothole"),
        threading.Thread(target=car_distance_thread, daemon=True, name="CarDistance"),
        threading.Thread(target=harsh_braking_thread, daemon=True, name="HarshBraking"),
        threading.Thread(target=sudden_acceleration_thread, daemon=True, name="SuddenAccel")
    ]
    
    print("Starting warning generation system...")
    print(f"Batch size: {BATCH_SIZE} data points")
    for thread in threads:
        thread.start()
        print(f"Started thread: {thread.name}")
    
    return threads


# Example usage
def main():
    # Start all monitoring threads
    threads = start_warning_system()
    
    # Simulate data updates (replace with actual sensor data acquisition)
    try:
        batch_counter = 0
        while True:
            # Simulate a batch of 104 sensor data points
            sample_batch = []
            base_time = time.time()
            
            for i in range(BATCH_SIZE):
                sample_data = SensorData(
                    timestamp=base_time + (i * 0.01),  # 10ms intervals
                    accel_x=0.5 + np.random.normal(0, 0.1),
                    accel_y=0.2 + np.random.normal(0, 0.1),
                    accel_z=9.8 + np.random.normal(0, 0.2),
                    angular_x=0.1 + np.random.normal(0, 0.05),
                    angular_y=0.05 + np.random.normal(0, 0.05),
                    angular_z=0.3 + np.random.normal(0, 0.05),
                    latitude=17.385 + (i * 0.00001),
                    longitude=78.486 + (i * 0.00001),
                    speed=60.0 + np.random.normal(0, 2),
                    speed_limit=50.0
                )
                sample_batch.append(sample_data)
            
            # Update the batch
            update_sensor_data_batch(sample_batch)
            batch_counter += 1
            
            warnings = get_warnings()
            warning_names = [
                "Overspeeding", "Bump", "Pothole", "Car Distance",
                "Speedy Turns", "Harsh Braking", "Sudden Accel"
            ]
            
            active_warnings = [warning_names[i] for i, w in enumerate(warnings) if w == 1]
            if active_warnings:
                print(f"Batch {batch_counter} - Active warnings: {', '.join(active_warnings)}")
            else:
                print(f"Batch {batch_counter} - No warnings")
            
            time.sleep(1.04)  # Wait for next batch (104 points * 10ms)
            
    except KeyboardInterrupt:
        print("\nShutting down warning system...")

main()