import time
import os
import requests
from typing import Dict, Optional  # Removed Tuple since we no longer return a pair

DB_URL = "https://wheeler-event-detection-default-rtdb.asia-southeast1.firebasedatabase.app"
_API_KEY = "AIzaSyA__tMBGiQ-PVqyvv9kvNHaSUJk2QPXU-c"
_EMAIL = "rpi@example.com"
_PASSWORD = "rpi123456"
DEFAULT_USER_ID = "OYFNMBRHiPduTdplwnSIa2dxdwx1"

# Auth state
_ID_TOKEN: Optional[str] = None
_REFRESH_TOKEN: Optional[str] = None
_TOKEN_EXPIRY_EPOCH: float = 0.0

IDENTITY_ENDPOINT = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
SECURETOKEN_ENDPOINT = "https://securetoken.googleapis.com/v1/token"


def _sign_in_email_password():
    global _ID_TOKEN, _REFRESH_TOKEN, _TOKEN_EXPIRY_EPOCH
    r = requests.post(
        f"{IDENTITY_ENDPOINT}?key={_API_KEY}",
        json={"email": _EMAIL, "password": _PASSWORD, "returnSecureToken": True},
        timeout=8
    )
    r.raise_for_status()
    js = r.json()
    _ID_TOKEN = js.get('idToken')
    _REFRESH_TOKEN = js.get('refreshToken')
    expires_in = int(js.get('expiresIn', '3600'))
    _TOKEN_EXPIRY_EPOCH = time.time() + expires_in
    print("--------------------------------------------")
    print("Signed in to Firebase.")
    print("--------------------------------------------")


def _refresh_token():
    global _ID_TOKEN, _REFRESH_TOKEN, _TOKEN_EXPIRY_EPOCH
    r = requests.post(
        f"{SECURETOKEN_ENDPOINT}?key={_API_KEY}",
        data={"grant_type": "refresh_token", "refresh_token": _REFRESH_TOKEN},
        timeout=8
    )
    r.raise_for_status()
    js = r.json()
    _ID_TOKEN = js.get('id_token')
    _REFRESH_TOKEN = js.get('refresh_token')
    expires_in = int(js.get('expires_in', '3600'))
    _TOKEN_EXPIRY_EPOCH = time.time() + expires_in


def _current_auth_token() -> str:
    global _ID_TOKEN, _REFRESH_TOKEN, _TOKEN_EXPIRY_EPOCH
    now = time.time()
    if not _ID_TOKEN or now >= _TOKEN_EXPIRY_EPOCH - 60:
        if _REFRESH_TOKEN:
            _refresh_token()
        else:
            _sign_in_email_password()
    return _ID_TOKEN  # type: ignore


def update_rider_speed(user_id: str, speed: float, speed_limit: float, warnings: Optional[Dict[str, dict]] = None) -> bool:
    # Write to new schema: users/{uid}/rider_data with keys: speed, speed_limit, active_warnings
    url = f"{DB_URL}/users/{user_id}/rider_data.json?auth={_current_auth_token()}"
    payload = {
        "speed": speed,
        "speed_limit": speed_limit,
        "active_warnings": warnings or {}
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase update exception: {e}")
        return False


def build_speeding_warning(speed: float, speed_limit: float) -> Dict[str, dict]:
    if speed is None or speed_limit is None or speed <= speed_limit:
        return {}
    ts_ms = int(time.time() * 1000)
    return {
        f"warning_{ts_ms}": {
            "type": "speed_limit",
            "message": "Speed Limit Exceeded!",
            "timestamp": ts_ms
        }
    }


def update_rider_mpu(
    user_id: str,
    acc_x: float,
    acc_y: float,
    acc_z: float,
    gyro_x: float,
    gyro_y: float,
    gyro_z: float,
    timestamp_ms: Optional[int] = None
) -> bool:
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    # Keep MPU nested under rider_data for telemetry convenience
    url = f"{DB_URL}/users/{user_id}/rider_data.json?auth={_current_auth_token()}"
    payload = {
        "mpu": {
            "acc_x": acc_x,
            "acc_y": acc_y,
            "acc_z": acc_z,
            "gyro_x": gyro_x,
            "gyro_y": gyro_y,
            "gyro_z": gyro_z,
            "timestamp": timestamp_ms
        }
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase MPU update exception: {e}")
        return False


def init_auth():
    _sign_in_email_password()


# ---- Control flags (Realtime Database) ----
def _ride_status_url(user_id: str, prefer_top_level: bool = True) -> str:
    # Return the URL to the ride control node used by legacy helpers.
    # New preferred location for ride control is users/{uid}/rides/<ride_id>/ride_control
    # When ride_id is not known, keep a simple users/{uid}/rider_control fallback.
    if prefer_top_level:
        return f"{DB_URL}/users/{user_id}/rider_control.json?auth={_current_auth_token()}"
    return f"{DB_URL}/users/{user_id}/rider_control.json?auth={_current_auth_token()}"


def get_control_flags(user_id: str) -> tuple[bool, bool]:
    """
    Returns (is_active, calculate_model) from Realtime DB.
    Tries top-level path first, then falls back to /users path.
    """
    # This legacy function remains but we now route through the more general
    # ride-scoped helper below. Keep for backward compatibility.
    return get_control_flags_for_ride(user_id, None)


def get_control_flags_for_ride(user_id: str, ride_id: Optional[str]) -> tuple[bool, bool]:
    """Returns (is_active, calculate_model) for a given ride_id.
    If ride_id is None, falls back to the top-level control locations.
    """
    try:
        if ride_id:
            url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_control.json?auth={_current_auth_token()}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                js = resp.json() or {}
                return bool(js.get("is_active", False)), bool(js.get("calculate_model", False))
        # Try legacy fallback location under users/<uid>/rider_control
        resp = requests.get(_ride_status_url(user_id, True), timeout=5)
        if resp.status_code == 200:
            js = resp.json() or {}
            return bool(js.get("is_active", False)), False
    except Exception as e:
        print(f"Firebase get_control_flags_for_ride exception: {e}")
    return False, False


def get_next_ride_id(user_id: str) -> str:
    """Return the next integer ride id as a string.

    If no rides exist, returns "0". Otherwise reads from next_ride_id field.
    """
    try:
        url = f"{DB_URL}/users/{user_id}/next_ride_id.json?auth={_current_auth_token()}"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return "0"
        next_id = resp.json()
        if next_id is None:
            return "0"
        return str(next_id)
    except Exception as e:
        print(f"Firebase get_next_ride_id exception: {e}")
        return "0"


def upload_raw_data_to_firebase(user_id: str, ride_id: str, csv_filepath: str) -> bool:
    """Upload entire CSV file content to Firebase under rides/{ride_id}/raw_data.
    
    Reads the CSV file and uploads each row as a JSON object.
    Returns True if successful, False otherwise.
    """
    import csv as csv_module
    
    if not os.path.isfile(csv_filepath):
        print(f"CSV file not found: {csv_filepath}")
        return False
    
    try:
        print(f"Uploading raw data from {csv_filepath} to Firebase...")
        
        # Read CSV file
        rows_data = []
        with open(csv_filepath, 'r', newline='') as f:
            reader = csv_module.DictReader(f)
            for row in reader:
                rows_data.append(row)
        
        if not rows_data:
            print("No data to upload (CSV is empty)")
            return False
        
        # Upload to Firebase
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/raw_data.json?auth={_current_auth_token()}"
        response = requests.put(url, json=rows_data, timeout=30)
        
        if response.status_code == 200:
            print(f"Successfully uploaded {len(rows_data)} rows to Firebase")
            return True
        else:
            print(f"Failed to upload raw data. Status code: {response.status_code}")
            return False
            
    except Exception as e:
        print(f"Firebase raw data upload exception: {e}")
        return False