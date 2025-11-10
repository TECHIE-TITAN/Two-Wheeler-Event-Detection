import threading
import time
import os
import re
import sys
import csv
import numpy as np
import h5py
from dataclasses import dataclass
from typing import List
import tensorflow as tf
from tensorflow import keras
from keras.models import Sequential
from keras.layers import LSTM, Dense, Dropout, Input

# Add Hardware Source Codes to path for shared_memory_bridge import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Hardware Source Codes'))
import shared_memory_bridge  # type: ignore

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

# Shared memory reader for receiving data from main2.py
shm_reader = None
shm_read_thread_active = False

# CSV logging
current_ride_id = None
CSV_FILENAME = "warnings.csv"  # Will be updated to warnings_{ride_id}.csv when ride starts
csv_lock = threading.Lock()

# Firebase integration
firebase_uploader = None
USER_ID = "OYFNMBRHiPduTdplwnSIa2dxdwx1"
FIREBASE_PUSH_INTERVAL_S = 7.0
last_firebase_push = 0.0

# Import firebase_uploader from Hardware Source Codes
try:
    import firebase_uploader  # type: ignore
    print("✓ Firebase uploader imported")
except Exception as e:
    print(f"⚠ Firebase uploader import failed: {e}")
    firebase_uploader = None

# Warning tuple: [overspeeding, bump, pothole, speedy_turns, harsh_braking, sudden_accel]
warning_state = [0, 0, 0, 0, 0, 0]
warning_lock = threading.Lock()

# LSTM model output tracking
lstm_last_prediction = "UNKNOWN"  # Last predicted class: BUMP, LEFT, RIGHT, STOP, STRAIGHT
lstm_prediction_lock = threading.Lock()

# LSTM model initialization
lstm_model = None
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), 'lstm_model_weights.weights.h5')

def build_lstm_model(input_shape, n_classes, lstm_units=100, dense_intermediate=10):
    """Build LSTM model architecture matching the weights file"""
    model = Sequential()
    model.add(Input(shape=input_shape))
    model.add(LSTM(units=lstm_units))
    model.add(Dropout(0.5))
    model.add(Dense(units=dense_intermediate, activation='relu'))
    model.add(Dense(n_classes, activation='softmax'))
    model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
    return model

def infer_model_config_from_weights(weights_path):
    """Infer LSTM units and output classes from HDF5 weights file"""
    lstm_units = None
    n_classes = None
    dense_intermediate = None
    dense_kernels = []
    
    try:
        with h5py.File(weights_path, 'r') as f:
            def visitor(name, obj):
                nonlocal lstm_units
                if isinstance(obj, h5py.Dataset):
                    lname = name.lower()
                    if 'kernel' in lname:
                        shape = obj.shape
                        if len(shape) == 2:
                            # Detect LSTM kernel by expecting input_dim=7 and 4*units columns
                            if 'lstm' in lname and shape[1] % 4 == 0:
                                lstm_units = shape[1] // 4
                            # Collect dense kernels for later analysis
                            if 'dense' in lname:
                                dense_kernels.append((name, shape))
            
            f.visititems(visitor)
    except Exception as e:
        print(f'Warning: could not inspect weights file: {e}')
    
    # Infer dense_intermediate and n_classes from dense kernels
    if dense_kernels:
        dense_kernels.sort(key=lambda x: x[0])
        for _, (in_dim, out_dim) in dense_kernels:
            if lstm_units is not None and in_dim == lstm_units:
                dense_intermediate = out_dim
                break
        n_classes_candidates = [shape[1] for _, shape in dense_kernels]
        if n_classes_candidates:
            n_classes = min(n_classes_candidates)
    
    # Fallbacks
    if lstm_units is None:
        lstm_units = 100
    if dense_intermediate is None:
        dense_intermediate = 10
    if n_classes is None:
        n_classes = 5
    
    return int(lstm_units), int(n_classes), int(dense_intermediate)

def load_lstm_model():
    """Load LSTM model with weights, handling shape mismatches"""
    global lstm_model
    
    if not os.path.exists(WEIGHTS_PATH):
        print(f"Warning: Weights file not found at {WEIGHTS_PATH}")
        return None
    
    try:
        # Infer configuration from weights
        lstm_units, n_classes, dense_intermediate = infer_model_config_from_weights(WEIGHTS_PATH)
        print(f"Inferred model config: lstm_units={lstm_units}, n_classes={n_classes}, dense_intermediate={dense_intermediate}")
        
        # Build model with correct architecture
        model = build_lstm_model(
            input_shape=(BATCH_SIZE, 7),
            n_classes=n_classes,
            lstm_units=lstm_units,
            dense_intermediate=dense_intermediate
        )
        
        # Load weights
        try:
            model.load_weights(WEIGHTS_PATH)
            print("LSTM model weights loaded successfully")
            return model
        except Exception as e:
            # Try to infer units from error message
            msg = str(e)
            print(f'Initial load_weights failed: {msg}')
            matches = re.findall(r"value\.shape=\((\d+)\s*,\s*(\d+)\)", msg)
            inferred_units = None
            
            for a_str, b_str in matches:
                try:
                    a = int(a_str)
                    b = int(b_str)
                    if b % 4 == 0 and a == 7:  # Expect input_dim=7 features
                        inferred_units = b // 4
                        break
                except Exception:
                    pass
            
            if inferred_units is not None and inferred_units != lstm_units:
                print(f'Rebuilding with lstm_units={inferred_units} based on error parsing...')
                model = build_lstm_model(
                    input_shape=(BATCH_SIZE, 7),
                    n_classes=n_classes,
                    lstm_units=inferred_units,
                    dense_intermediate=dense_intermediate
                )
                model.load_weights(WEIGHTS_PATH)
                print("LSTM model loaded with corrected units")
                return model
            else:
                raise
    
    except Exception as e:
        print(f"Error loading LSTM model: {e}")
        return None

# Load model on startup
try:
    lstm_model = load_lstm_model()
except Exception as e:
    print(f"Failed to load LSTM model: {e}")
    lstm_model = None

# Configuration parameters
SPEEDY_TURN_THRESHOLD = 0.5  # rad/s (Z-axis angular velocity for yaw/turning)
HARSH_BRAKE_THRESHOLD = -4.0  # m/s^2
SUDDEN_ACCEL_THRESHOLD = 3.5  # m/s^2
POTHOLE_Z_THRESHOLD = 2.5  # m/s^2 vertical acceleration spike


def update_warning(index: int, value: int):
    """Thread-safe warning update"""
    with warning_lock:
        warning_state[index] = value

def update_lstm_prediction(prediction: str):
    """Thread-safe LSTM prediction update"""
    global lstm_last_prediction
    with lstm_prediction_lock:
        lstm_last_prediction = prediction

def get_lstm_prediction() -> str:
    """Get last LSTM prediction"""
    with lstm_prediction_lock:
        return lstm_last_prediction


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
    """Thread for LSTM model predictions using 104 data points
    
    Model outputs 5 classes in alphabetical order: [BUMP, LEFT, RIGHT, STOP, STRAIGHT]
    Returns a single prediction per batch of 104 points.
    """
    global lstm_model
    
    # Class names from model (alphabetical order from get_dummies)
    CLASS_NAMES = ['BUMP', 'LEFT', 'RIGHT', 'STOP', 'STRAIGHT']
    BUMP_CONFIDENCE_THRESHOLD = 0.6  # Minimum confidence to trigger bump warning
    
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            if lstm_model is None:
                time.sleep(0.1)
                continue
            
            features = extract_batch_features(batch)
            
            # Prepare input for LSTM (104 timesteps, 7 features)
            # Match the exact order used in training: acc_x, acc_y, acc_z, gyro_x, gyro_y, gyro_z, speed
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
            input_sequence = input_sequence.reshape(1, BATCH_SIZE, 7).astype(np.float32)
            
            # Check for NaNs in input
            if np.isnan(input_sequence).any():
                print("Warning: NaN values detected in LSTM input, skipping prediction")
                time.sleep(0.1)
                continue
            
            # Predict: [BUMP, LEFT, RIGHT, STOP, STRAIGHT]
            prediction = lstm_model.predict(input_sequence, verbose=0)
            pred_class_idx = np.argmax(prediction[0])
            confidence = prediction[0][pred_class_idx]
            predicted_label = CLASS_NAMES[pred_class_idx] if pred_class_idx < len(CLASS_NAMES) else str(pred_class_idx)
            
            # Update global LSTM prediction for output
            update_lstm_prediction(predicted_label)
            
            # BUMP is index 0 in alphabetical order
            bump_idx = CLASS_NAMES.index('BUMP') if 'BUMP' in CLASS_NAMES else 0
            
            # Update bump warning based on prediction and confidence
            if pred_class_idx == bump_idx and confidence >= BUMP_CONFIDENCE_THRESHOLD:
                update_warning(1, 1)  # Bump detected
            else:
                update_warning(1, 0)  # No bump
            
            # Note: Debug print removed - prediction is displayed in main loop
            
            time.sleep(0.05)
            
        except Exception as e:
            print(f"LSTM thread error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(0.1)


def overspeeding_thread():
    """Thread for overspeeding detection using batch data
    
    Checks if current speed exceeds the posted speed limit directly.
    No buffer is used - any speed over the limit is considered overspeeding.
    """
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            features = extract_batch_features(batch)
            
            # Check if any point in batch exceeds speed limit (no buffer)
            overspeeding = np.any(features['speed'] > features['speed_limit'])
            
            if overspeeding:
                update_warning(0, 1)
            else:
                update_warning(0, 0)
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"Overspeeding thread error: {e}")
            time.sleep(0.1)


def speedy_turns_thread():
    """Thread for detecting speedy/sharp turns using batch data
    
    For a scooter/two-wheeler:
    - Z-axis (vertical) represents yaw rotation (turning left/right)
    - X-axis represents pitch (front-back tilt)
    - Y-axis represents roll (side-to-side tilt)
    
    We only monitor Z-axis angular velocity for turn detection.
    ONLY checks if turn is speedy when LSTM predicts LEFT or RIGHT event.
    """
    while True:
        try:
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.1)
                continue
            
            # Get latest LSTM prediction
            latest_prediction = get_lstm_prediction()
            
            # Only check for speedy turns if LSTM detected a LEFT or RIGHT turn
            if latest_prediction not in ['LEFT', 'RIGHT']:
                update_warning(3, 0)  # No turn event, so no speedy turn warning
                time.sleep(0.05)
                continue
            
            features = extract_batch_features(batch)
            
            # Use only Z-axis angular velocity (yaw) for turn detection
            angular_vel_z = np.abs(features['angular_z'])
            
            # Check if any turn exceeds threshold while at speed (>20 km/h)
            speedy_turn = np.any(
                (angular_vel_z > SPEEDY_TURN_THRESHOLD) & (features['speed'] > 20)
            )
            
            if speedy_turn:
                update_warning(3, 1)  # Speedy turn detected during LEFT/RIGHT event
            else:
                update_warning(3, 0)  # Turn detected but not speedy
            
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
                        update_warning(4, 1)  # Updated index after removing car_distance
                    else:
                        update_warning(4, 0)
            
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
                            update_warning(5, 1)  # Updated index after removing car_distance
                        else:
                            update_warning(5, 0)
            
            time.sleep(0.05)
            
        except Exception as e:
            print(f"Sudden acceleration thread error: {e}")
            time.sleep(0.1)


def update_sensor_data_batch(new_batch: List[SensorData]):
    """Update global sensor data batch (called by data acquisition system)"""
    global current_data_batch
    with data_lock:
        current_data_batch = new_batch[-BATCH_SIZE:]  # Keep only last 104 points


def shared_memory_reader_thread():
    """Thread to continuously read batches from shared memory and update current_data_batch"""
    global shm_reader, shm_read_thread_active, current_data_batch, current_ride_id, CSV_FILENAME
    
    print("⏳ Shared memory reader thread starting...")
    
    # Wait for and initialize reader
    try:
        shm_reader = shared_memory_bridge.SensorDataReader(wait_for_creation=True, timeout=30.0)
        print("✓ Shared memory reader connected to main2.py")
    except Exception as e:
        print(f"✗ Failed to connect to shared memory: {e}")
        print("  Make sure main2.py is running first!")
        shm_read_thread_active = False
        return
    
    shm_read_thread_active = True
    last_read_time = time.time()
    read_count = 0
    
    print("⏳ Waiting for ride to start...")
    
    while shm_read_thread_active:
        try:
            # Check if ride is active using flag
            ride_active = shm_reader.is_ride_active()
            
            if not ride_active:
                # Ride is inactive - clear batch and wait
                with data_lock:
                    current_data_batch = []
                
                # If we had a ride_id, it just ended
                if current_ride_id is not None:
                    print(f"🛑 Ride {current_ride_id} ended - pausing processing")
                    current_ride_id = None
                    CSV_FILENAME = "warnings.csv"  # Reset to default
                
                time.sleep(0.5)  # Poll every 500ms when inactive
                continue
            
            # Ride is active - check if it's a new ride
            ride_id = shm_reader.get_ride_id()
            if current_ride_id != ride_id:
                # New ride started
                current_ride_id = str(ride_id)
                CSV_FILENAME = f"warnings_{ride_id}.csv"
                print(f"� New ride started: ride_id={ride_id}")
                print(f"📝 Writing to: {CSV_FILENAME}")
                
                # Initialize CSV file with header
                with csv_lock:
                    with open(CSV_FILENAME, 'w', newline='') as csvfile:
                        fieldnames = [
                            'timestamp', 'accel_x', 'accel_y', 'accel_z',
                            'angular_x', 'angular_y', 'angular_z',
                            'latitude', 'longitude', 'speed', 'speed_limit',
                            'lstm_prediction', 'warnings'
                        ]
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writeheader()
            
            # Read batch from shared memory
            batch_dict = shm_reader.read_batch_as_dict()
            
            if batch_dict is not None:
                # Convert to SensorData objects
                new_batch = []
                for i in range(BATCH_SIZE):
                    sensor_point = SensorData(
                        timestamp=float(batch_dict['timestamps'][i]),
                        accel_x=float(batch_dict['accel_x'][i]),
                        accel_y=float(batch_dict['accel_y'][i]),
                        accel_z=float(batch_dict['accel_z'][i]),
                        angular_x=float(batch_dict['angular_x'][i]),
                        angular_y=float(batch_dict['angular_y'][i]),
                        angular_z=float(batch_dict['angular_z'][i]),
                        latitude=float(batch_dict['latitude'][i]),
                        longitude=float(batch_dict['longitude'][i]),
                        speed=float(batch_dict['speed'][i]),
                        speed_limit=float(batch_dict['speed_limit'][i])
                    )
                    new_batch.append(sensor_point)
                
                # Update global batch
                with data_lock:
                    current_data_batch = new_batch
                
                read_count += 1
                
                # Print stats every 10 batches
                if read_count % 10 == 0:
                    elapsed = time.time() - last_read_time
                    rate = 10 / elapsed if elapsed > 0 else 0
                    print(f"📊 Received {read_count} batches (rate: {rate:.1f} batches/s)")
                    last_read_time = time.time()
            
            # Small sleep to avoid spinning (shared memory is always available)
            time.sleep(0.01)  # 100 Hz polling rate
            
        except Exception as e:
            print(f"✗ Shared memory read error: {e}")
            time.sleep(0.1)
    
    # Cleanup
    if shm_reader:
        shm_reader.cleanup()
    print("✓ Shared memory reader thread stopped")


def get_warnings() -> list:
    """Get current warning state"""
    with warning_lock:
        return warning_state.copy()


def write_batch_to_csv(batch: List[SensorData], lstm_prediction: str, warnings: list):
    """Write batch of 104 rows to CSV with LSTM prediction and warnings columns
    
    Args:
        batch: List of 104 SensorData objects
        lstm_prediction: LSTM prediction for this batch (same value for all 104 rows)
        warnings: Warning state list for this batch (same value for all 104 rows)
    """
    if len(batch) != BATCH_SIZE:
        print(f"⚠ Warning: Batch size {len(batch)} != {BATCH_SIZE}, skipping CSV write")
        return
    
    # Convert warnings list to string representation
    warning_names = ["Overspeeding", "Bump", "Pothole", "Speedy Turns", "Harsh Braking", "Sudden Accel"]
    active_warnings = [warning_names[i] for i, w in enumerate(warnings) if w == 1]
    warnings_str = ','.join(active_warnings) if active_warnings else "None"
    
    with csv_lock:
        # Check if file exists to determine if we need to write header
        file_exists = os.path.isfile(CSV_FILENAME)
        
        with open(CSV_FILENAME, 'a', newline='') as csvfile:
            fieldnames = [
                'timestamp', 'accel_x', 'accel_y', 'accel_z',
                'angular_x', 'angular_y', 'angular_z',
                'latitude', 'longitude', 'speed', 'speed_limit',
                'lstm_prediction', 'warnings'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            # Write header if file is new
            if not file_exists:
                writer.writeheader()
            
            # Write all 104 rows with same LSTM prediction and warnings
            for point in batch:
                row = {
                    'timestamp': point.timestamp,
                    'accel_x': point.accel_x,
                    'accel_y': point.accel_y,
                    'accel_z': point.accel_z,
                    'angular_x': point.angular_x,
                    'angular_y': point.angular_y,
                    'angular_z': point.angular_z,
                    'latitude': point.latitude,
                    'longitude': point.longitude,
                    'speed': point.speed,
                    'speed_limit': point.speed_limit,
                    'lstm_prediction': lstm_prediction,
                    'warnings': warnings_str
                }
                writer.writerow(row)


def firebase_push_thread():
    """Thread to periodically push data to Firebase with LSTM prediction and warnings
    
    Pushes only: speed, speed_limit, events (LSTM prediction), and warning list
    """
    global last_firebase_push
    
    if firebase_uploader is None:
        print("⚠ Firebase uploader not available, skipping Firebase push thread")
        return
    
    print("🔥 Firebase push thread started")
    
    while shm_read_thread_active:
        try:
            current_time = time.time()
            
            # Check if ride is active before pushing
            if shm_reader and not shm_reader.is_ride_active():
                time.sleep(1.0)
                continue
            
            # Check if it's time to push
            if (current_time - last_firebase_push) < FIREBASE_PUSH_INTERVAL_S:
                time.sleep(0.5)
                continue
            
            # Get current batch and warnings
            batch = get_current_data_batch()
            if len(batch) < BATCH_SIZE:
                time.sleep(0.5)
                continue
            
            # Get latest sensor data (use last point in batch for real-time data)
            latest = batch[-1]
            
            # Get warnings and LSTM prediction (events)
            warnings = get_warnings()
            lstm_pred = get_lstm_prediction()
            
            # Convert warnings to list of strings
            warning_names = ["Overspeeding", "Bump", "Pothole", "Speedy Turns", "Harsh Braking", "Sudden Accel"]
            active_warnings = [warning_names[i] for i, w in enumerate(warnings) if w == 1]
            
            # Push speed data with warnings and events (LSTM prediction)
            try:
                # Build warnings list for Firebase
                fb_warnings = active_warnings if active_warnings else []
                
                # Push: speed, speed_limit, warnings list
                firebase_uploader.update_rider_speed(
                    USER_ID,
                    latest.speed,
                    latest.speed_limit,
                    fb_warnings
                )
                
                # Note: LSTM prediction (events) is included as part of warnings
                # If you have a separate method to push events, use it here:
                # firebase_uploader.update_rider_events(USER_ID, lstm_pred)
                
            except Exception as e:
                print(f"Firebase push error: {e}")
            
            last_firebase_push = current_time
            
        except Exception as e:
            print(f"Firebase push thread error: {e}")
            time.sleep(1.0)
    
    print("🔥 Firebase push thread stopped")


def start_warning_system():
    """Initialize and start all monitoring threads"""
    threads = [
        threading.Thread(target=shared_memory_reader_thread, daemon=True, name="SharedMemReader"),
        threading.Thread(target=lstm_prediction_thread, daemon=True, name="LSTM"),
        threading.Thread(target=overspeeding_thread, daemon=True, name="Overspeeding"),
        threading.Thread(target=pothole_detection_thread, daemon=True, name="Pothole"),
        threading.Thread(target=speedy_turns_thread, daemon=True, name="SpeedyTurns"),
        threading.Thread(target=harsh_braking_thread, daemon=True, name="HarshBraking"),
        threading.Thread(target=sudden_acceleration_thread, daemon=True, name="SuddenAccel"),
        threading.Thread(target=firebase_push_thread, daemon=True, name="FirebasePush")
    ]
    
    print("Starting warning generation system...")
    print(f"Batch size: {BATCH_SIZE} data points")
    for thread in threads:
        thread.start()
        print(f"Started thread: {thread.name}")
    
    return threads


# Example usage
def main():
    """
    Main function - now receives data from main2.py via shared memory
    No need to simulate data anymore!
    """
    global shm_read_thread_active
    
    print("="*60)
    print("  Two-Wheeler Event Detection - Warning Generation System")
    print("  Receiving real-time data from main2.py via shared memory")
    print("="*60)
    
    # Start all monitoring threads (includes shared memory reader)
    threads = start_warning_system()
    
    # Monitor warnings
    try:
        batch_counter = 0
        while True:
            # Wait for data to be available
            if len(get_current_data_batch()) < BATCH_SIZE:
                print("⏳ Waiting for first batch from main2.py...")
                time.sleep(1.0)
                continue
            
            batch_counter += 1
            
            # Get current batch, warnings, and LSTM prediction
            current_batch = get_current_data_batch()
            warnings = get_warnings()
            lstm_pred = get_lstm_prediction()
            
            # Write batch to CSV
            write_batch_to_csv(current_batch, lstm_pred, warnings)
            
            warning_names = [
                "Overspeeding", "Bump", "Pothole",
                "Speedy Turns", "Harsh Braking", "Sudden Accel"
            ]
            
            active_warnings = [warning_names[i] for i, w in enumerate(warnings) if w == 1]
            print(f"\nBatch {batch_counter}:")
            print(f"  LSTM Prediction: {lstm_pred}")
            if active_warnings:
                print(f"  Active warnings: {', '.join(active_warnings)}")
            else:
                print(f"  No warnings")
            print(f"  Written to {CSV_FILENAME}")
            
            time.sleep(1.0)  # Display update rate (1 Hz)
            
    except KeyboardInterrupt:
        print("\n\nShutting down warning system...")
        shm_read_thread_active = False
        
        # Wait for threads to finish
        for thread in threads:
            thread.join(timeout=1.0)
        
        print("✓ Warning system stopped")


if __name__ == "__main__":
    main()