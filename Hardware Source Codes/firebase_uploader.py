import time
import requests
from typing import Dict, Optional, Tuple

DB_URL = "https://wheeler-event-detection-default-rtdb.asia-southeast1.firebasedatabase.app"
_API_KEY = "AIzaSyA__tMBGiQ-PVqyvv9kvNHaSUJk2QPXU-c"
_EMAIL = "rpi@example.com"
_PASSWORD = "rpi123456"

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
        timeout=8,
    )
    r.raise_for_status()
    js = r.json()
    _ID_TOKEN = js.get("idToken")
    _REFRESH_TOKEN = js.get("refreshToken")
    expires_in = int(js.get("expiresIn", "3600"))
    _TOKEN_EXPIRY_EPOCH = time.time() + expires_in
    print("Signed in to Firebase.")


def _refresh_token():
    global _ID_TOKEN, _REFRESH_TOKEN, _TOKEN_EXPIRY_EPOCH
    r = requests.post(
        f"{SECURETOKEN_ENDPOINT}?key={_API_KEY}",
        data={"grant_type": "refresh_token", "refresh_token": _REFRESH_TOKEN},
        timeout=8,
    )
    r.raise_for_status()
    js = r.json()
    _ID_TOKEN = js.get("id_token")
    _REFRESH_TOKEN = js.get("refresh_token")
    expires_in = int(js.get("expires_in", "3600"))
    _TOKEN_EXPIRY_EPOCH = time.time() + expires_in


def _current_auth_token() -> str:
    global _ID_TOKEN, _REFRESH_TOKEN, _TOKEN_EXPIRY_EPOCH
    now = time.time()
    if (not _ID_TOKEN) or now >= _TOKEN_EXPIRY_EPOCH - 60:
        if _REFRESH_TOKEN:
            _refresh_token()
        else:
            _sign_in_email_password()
    return _ID_TOKEN or ""


# ---- Rider data (telemetry) ----
def update_rider_speed(user_id: str, speed: float, speed_limit: float, warnings: Optional[Dict[str, dict]] = None) -> bool:
    """Patch speed, speed_limit, and active_warnings under users/{uid}/rider_data"""
    url = f"{DB_URL}/users/{user_id}/rider_data.json?auth={_current_auth_token()}"
    payload = {
        "speed": speed,
        "speed_limit": speed_limit,
        "active_warnings": warnings or {},
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase update_rider_speed exception: {e}")
        return False


def build_speeding_warning(speed: float, speed_limit: float) -> Dict[str, dict]:
    if speed is None or speed_limit is None or speed <= speed_limit:
        return {}
    ts_ms = int(time.time() * 1000)
    return {f"warning_{ts_ms}": {"type": "speed_limit", "message": "Speed Limit Exceeded!", "timestamp": ts_ms}}


def update_rider_mpu(
    user_id: str,
    acc_x: float,
    acc_y: float,
    acc_z: float,
    gyro_x: float,
    gyro_y: float,
    gyro_z: float,
    timestamp_ms: Optional[int] = None,
) -> bool:
    """Keep MPU nested under rider_data for quick diagnostics."""
    if timestamp_ms is None:
        timestamp_ms = int(time.time() * 1000)
    url = f"{DB_URL}/users/{user_id}/rider_data.json?auth={_current_auth_token()}"
    payload = {
        "mpu": {
            "acc_x": acc_x,
            "acc_y": acc_y,
            "acc_z": acc_z,
            "gyro_x": gyro_x,
            "gyro_y": gyro_y,
            "gyro_z": gyro_z,
            "timestamp": timestamp_ms,
        }
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase update_rider_mpu exception: {e}")
        return False


# ---- Ride control and helpers ----
def init_auth():
    _sign_in_email_password()


def get_current_ride_id(user_id: str) -> Optional[str]:
    """Reads users/{uid}/next_ride_id and returns string."""
    try:
        url = f"{DB_URL}/users/{user_id}/next_ride_id.json?auth={_current_auth_token()}"
        resp = requests.get(url, timeout=6)
        if resp.status_code != 200:
            return None
        val = resp.json()
        if val is None:
            return None
        return str(int(val)) if isinstance(val, (int, float)) else str(val)
    except Exception as e:
        print(f"Firebase get_current_ride_id exception: {e}")
        return None


def init_ride_for_ride(user_id: str, ride_id: str, start_timestamp_ms: int) -> bool:
    """Initialize ride control status under users/{uid}/rides/{ride_id}/ride_control"""
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_control.json?auth={_current_auth_token()}"
        payload = {
            "is_active": True,
            "start_time": start_timestamp_ms,
            # end_time will be set when ride stops
        }
        resp = requests.patch(url, json=payload, timeout=6)
        return resp.status_code == 200
    except Exception as e:
        print(f"Firebase init_ride_for_ride exception: {e}")
        return False


def set_control_flag(user_id: str, ride_id: str, field: str, value) -> bool:
    """Set a control field under ride_control for a given ride."""
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_control.json?auth={_current_auth_token()}"
        resp = requests.patch(url, json={field: value}, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        print(f"Firebase set_control_flag exception: {e}")
        return False


def get_is_active_for_ride(user_id: str, ride_id: str) -> bool:
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_control/is_active.json?auth={_current_auth_token()}"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return False
        js = resp.json()
        return bool(js)
    except Exception as e:
        print(f"Firebase get_is_active_for_ride exception: {e}")
        return False


def set_ride_end_time(user_id: str, ride_id: str, end_timestamp_ms: int) -> bool:
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_control.json?auth={_current_auth_token()}"
        resp = requests.patch(url, json={"end_time": end_timestamp_ms}, timeout=5)
        return resp.status_code == 200
    except Exception as e:
        print(f"Firebase set_ride_end_time exception: {e}")
        return False


# ---- Ride data uploads (new schema) ----
def upload_ride_raw_data_for_ride(user_id: str, ride_id: str, rows: list) -> bool:
    """PUT array of row dicts to users/{uid}/rides/{ride_id}/raw_data"""
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/raw_data.json?auth={_current_auth_token()}"
        resp = requests.put(url, json=rows, timeout=20)
        return resp.status_code == 200
    except Exception as e:
        print(f"Firebase upload_ride_raw_data_for_ride exception: {e}")
        return False


def upload_ride_processed_for_ride(user_id: str, ride_id: str, processed_obj: dict) -> bool:
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/processed.json?auth={_current_auth_token()}"
        resp = requests.patch(url, json=processed_obj, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Firebase upload_ride_processed_for_ride exception: {e}")
        return False
