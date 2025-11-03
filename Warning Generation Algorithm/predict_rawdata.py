import os
import re
import sys
import numpy as np
import pandas as pd
import h5py
from keras.models import Sequential
from keras.layers import LSTM, Dense, Dropout, Input

N_TIME_STEPS = 104  # number of time steps per window
def build_model(input_shape, n_classes, lstm_units=100, dense_intermediate=10):
    # Use an explicit Input layer to avoid Sequential input_shape warning
    model = Sequential()
    model.add(Input(shape=input_shape))
    model.add(LSTM(units=lstm_units))
    model.add(Dropout(0.5))
    # Do not force custom names to better match saved weights
    model.add(Dense(units=dense_intermediate, activation='relu'))
    model.add(Dense(n_classes, activation='softmax'))
    model.compile(optimizer='adam', loss='categorical_crossentropy', metrics=['accuracy'])
    return model


def infer_model_config_from_weights(weights_path):
    """Try to infer LSTM units and final dense output units from an HDF5 weights file.
    Returns (lstm_units, n_classes, dense_intermediate)
    """
    lstm_units = None
    n_classes = None
    dense_intermediate = None

    dense_kernels = []
    try:
        with h5py.File(weights_path, 'r') as f:
            for name, obj in f.items():
                pass  # force file open

            # Traverse all items to collect candidates
            def visitor(name, obj):
                nonlocal lstm_units
                if isinstance(obj, h5py.Dataset):
                    lname = name.lower()
                    if 'kernel' in lname:
                        shape = obj.shape
                        if len(shape) == 2:
                            # detect LSTM kernel by expecting input_dim=7 and 4*units columns
                            if 'lstm' in lname and shape[1] % 4 == 0:
                                lstm_units = shape[1] // 4
                            # collect dense kernels for later analysis
                            if 'dense' in lname:
                                dense_kernels.append((name, shape))

            f.visititems(visitor)
    except Exception as e:
        print('Warning: could not inspect weights file to infer config:', e)

    # fallbacks
    # Try to infer dense_intermediate and n_classes from collected dense kernels
    if dense_kernels:
        # sort by name to have deterministic order
        dense_kernels.sort(key=lambda x: x[0])
        # Prefer the kernel whose input dim equals lstm_units as the intermediate
        for _, (in_dim, out_dim) in dense_kernels:
            if lstm_units is not None and in_dim == lstm_units:
                dense_intermediate = out_dim
                break
        # Infer n_classes as the smallest out_dim (typically final softmax)
        n_classes_candidates = [shape[1] for _, shape in dense_kernels]
        if n_classes_candidates:
            n_classes = min(n_classes_candidates)

    # fallbacks
    if lstm_units is None:
        lstm_units = 100
    if dense_intermediate is None:
        dense_intermediate = 10
    if n_classes is None:
        n_classes = 5

    return int(lstm_units), int(n_classes), int(dense_intermediate)


def window_data(df, n_time_steps=104, step=104):
    segments = []
    indices = []
    for i in range(0, len(df) - n_time_steps, step):
        Ax = df['acc_x'].values[i:i+n_time_steps]
        Ay = df['acc_y'].values[i:i+n_time_steps]
        Az = df['acc_z'].values[i:i+n_time_steps]
        Gx = df['gyro_x'].values[i:i+n_time_steps]
        Gy = df['gyro_y'].values[i:i+n_time_steps]
        Gz = df['gyro_z'].values[i:i+n_time_steps]
        Speed = df['speed'].values[i:i+n_time_steps]

        # if any NaNs in window, skip
        window = np.vstack([Ax, Ay, Az, Gx, Gy, Gz, Speed])
        if np.isnan(window).any():
            continue

        segments.append(window)
        indices.append(i)

    if len(segments) == 0:
        return np.empty((0, n_time_steps, 7), dtype=np.float32), []

    X = np.asarray(segments, dtype=np.float32).reshape(-1, n_time_steps, 7)
    return X, indices


def predict_file(input_csv_path, weights_path, output_csv_path):
    df = pd.read_csv(input_csv_path)

    # Check required columns
    required = ['acc_x','acc_y','acc_z','gyro_x','gyro_y','gyro_z','speed']
    for c in required:
        if c not in df.columns:
            raise ValueError(f"Required column '{c}' not found in {input_csv_path}")

    X, indices = window_data(df)
    print('Windows:', X.shape)

    if X.shape[0] == 0:
        print('No valid windows to predict (possibly NaNs). Exiting.')
        return

    # infer model config from weights file to avoid shape mismatches
    if not os.path.exists(weights_path):
        raise FileNotFoundError(f"Weights file not found: {weights_path}")

    lstm_units, n_classes, dense_intermediate = infer_model_config_from_weights(weights_path)
    print(f'Inferred from weights: lstm_units={lstm_units}, n_classes={n_classes}, dense_intermediate={dense_intermediate}')

    model = build_model(input_shape=(X.shape[1], X.shape[2]), n_classes=n_classes, lstm_units=lstm_units, dense_intermediate=dense_intermediate)

    # Load weights and handle shape mismatch by auto-adjusting units from error message
    try:
        model.load_weights(weights_path)
    except Exception as e:
        msg = str(e)
        print('Initial load_weights failed. Attempting to infer units from error:', msg)
        # Look for value.shape=(a, b) pattern; if b%4==0 assume b//4 is units
        matches = re.findall(r"value\.shape=\((\d+)\s*,\s*(\d+)\)", msg)
        inferred_units = None
        for a_str, b_str in matches:
            try:
                a = int(a_str)
                b = int(b_str)
                if b % 4 == 0 and a in (7,):  # expect input_dim=7 features
                    inferred_units = b // 4
                    break
            except Exception:
                pass

        if inferred_units is not None and inferred_units != lstm_units:
            print(f'Rebuilding with lstm_units={inferred_units} based on weights error parsing...')
            # Optionally refine dense size from weights for this units
            try:
                # re-infer dense sizes using new lstm_units
                _lstm_units, _n_classes, _dense_intermediate = infer_model_config_from_weights(weights_path)
                # If previous inference still guessed old units, override
                _lstm_units = inferred_units
                model = build_model(input_shape=(X.shape[1], X.shape[2]), n_classes=_n_classes, lstm_units=_lstm_units, dense_intermediate=_dense_intermediate)
            except Exception:
                model = build_model(input_shape=(X.shape[1], X.shape[2]), n_classes=n_classes, lstm_units=inferred_units, dense_intermediate=dense_intermediate)

            model.load_weights(weights_path)
        else:
            # re-raise if we couldn't infer
            raise

    preds = model.predict(X, batch_size=16)
    pred_classes = np.argmax(preds, axis=1)

    # Class names: choose label set by env var (default to bump/left/right/stop/straight as in notebook)
    label_set = os.getenv('LABEL_SET', 'bump').lower().strip()
    if label_set == 'event':
        # taxonomy from labelling.py thresholds
        class_names = ['Acceleration', 'Deceleration', 'Left Turn', 'Right Turn', 'Stable']
    else:
        # default taxonomy as seen in LSTM-ESW outputs (assumed alphabetical order from get_dummies)
        class_names = ['BUMP', 'LEFT', 'RIGHT', 'STOP', 'STRAIGHT']

    # Optional override: if predicted BUMP confidence < threshold, set to STRAIGHT
    bump_threshold = float(os.getenv('BUMP_THRESHOLD', '0.6'))

    # Save a summary CSV with window start index, end index, predicted label and confidence
    out_rows = []
    confidences = preds.max(axis=1)
    # try to include timestamps if available
    has_timestamp = 'timestamp' in df.columns
    for idx, cls_idx, conf in zip(indices, pred_classes, confidences):
        label = class_names[cls_idx] if cls_idx < len(class_names) else str(cls_idx)
        # apply BUMP confidence override only when using bump taxonomy
        if 'BUMP' in class_names and label.upper() == 'BUMP' and conf < bump_threshold:
            label = 'STRAIGHT'
        row = {'window_start': idx, 'window_end': idx + N_TIME_STEPS, 'pred_label': label, 'confidence': float(conf)}
        if has_timestamp:
            try:
                row['window_start_timestamp'] = df['timestamp'].iloc[idx]
                row['window_end_timestamp'] = df['timestamp'].iloc[idx + N_TIME_STEPS - 1]
            except Exception:
                row['window_start_timestamp'] = ''
                row['window_end_timestamp'] = ''
        out_rows.append(row)

    out_df = pd.DataFrame(out_rows)
    out_df.to_csv(output_csv_path, index=False)
    print('Wrote', output_csv_path)


if __name__ == '__main__':
    base = os.path.dirname(__file__)
    weights = os.path.join(base, 'lstm_model_weights.weights.h5')

    # Accept a file number or direct CSV path via CLI arg or interactive prompt
    arg = None
    if len(sys.argv) > 1:
        arg = sys.argv[1].strip()
    else:
        try:
            arg = input("Enter rawdata file number (e.g., 26) or a CSV path: ").strip()
        except Exception:
            arg = ''

    if not arg:
        # default to 26 if nothing provided
        arg = '26'

    # Resolve input/output paths
    input_csv = None
    output_csv = None

    # If arg looks like a CSV path, use it directly
    if arg.lower().endswith('.csv') or os.sep in arg:
        input_csv = arg if os.path.isabs(arg) else os.path.join(base, arg)
        if not input_csv.lower().endswith('.csv'):
            input_csv += '.csv'
        # derive output next to the input file
        in_dir, in_name = os.path.split(input_csv)
        name_no_ext, _ = os.path.splitext(in_name)
        output_csv = os.path.join(in_dir, f"{name_no_ext}_predicted.csv")
    else:
        # assume it's a number like '26'
        if not arg.isdigit():
            raise SystemExit(f"Invalid input '{arg}'. Provide a number (e.g., 26) or a CSV path.")
        num = arg
        input_csv = os.path.join(base, 'attachments', f'rawdata_{num}.csv')
        output_csv = os.path.join(base, 'attachments', f'rawdata_{num}_predicted.csv')

    # Validate input exists
    if not os.path.exists(input_csv):
        raise SystemExit(f"Input CSV not found: {input_csv}")

    predict_file(input_csv, weights, output_csv)
