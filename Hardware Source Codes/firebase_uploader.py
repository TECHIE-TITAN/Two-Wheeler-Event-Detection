import time
import os
import requests
from typing import Dict, Optional  # Removed Tuple since we no longer return a pair

DB_URL = "https://wheeler-event-detection-default-rtdb.asia-southeast1.firebasedatabase.app"
_API_KEY = "AIzaSyA__tMBGiQ-PVqyvv9kvNHaSUJk2QPXU-c"
_EMAIL = "rpi@example.com"
_PASSWORD = "rpi123456"
DEFAULT_USER_ID = "abSdkSyZuxdmryk4jnlMqfwl49n2"

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
    print("Signed in to Firebase.")


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
    url = f"{DB_URL}/users/{user_id}/rider_data.json?auth={_current_auth_token()}"
    payload = {
        "current_speed": speed,
        "speed_limit": speed_limit,
        "active_warnings_list": warnings or {}
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


def init_ride_for_ride(user_id: str, ride_id: str, start_timestamp_ms: int) -> bool:
    """Initialize ride control status for a ride (only is_active retained)."""
    url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/rider_control/ride_status.json?auth={_current_auth_token()}"
    payload = {
        "is_active": True,
        "start_timestamp": start_timestamp_ms
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase init_ride_for_ride exception: {e}")
        return False


def init_auth():
    _sign_in_email_password()


def get_control_flags_for_ride(user_id: str, ride_id: str) -> bool:
    """Return is_active flag for the specified ride. calculate_model removed."""
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/rider_control/ride_status.json?auth={_current_auth_token()}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            js = resp.json() or {}
            return bool(js.get("is_active", False))
    except Exception as e:
        print(f"Firebase get_control_flags_for_ride exception: {e}")
    return False


def get_next_ride_id(user_id: str) -> str:
    """Return the next integer ride id as a string.

    If no rides exist, returns "0". Otherwise returns str(max_id+1).
    """
    try:
        url = f"{DB_URL}/users/{user_id}/rides.json?auth={_current_auth_token()}"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return "0"
        js = resp.json() or {}
        numeric_ids = [int(k) for k in js.keys() if k.isdigit()]
        if not numeric_ids:
            return "0"
        return str(max(numeric_ids) + 1)
    except Exception as e:
        print(f"Firebase get_next_ride_id exception: {e}")
        return "0"


def set_control_flag(user_id: str, field: str, value: bool, ride_id: Optional[str] = None) -> bool:
    """Set a boolean field under ride_status for a ride. Legacy fallbacks removed.
    ride_id is now required for writes (returns False if absent)."""
    if not ride_id:
        return False
    payload = {field: bool(value)}
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/rider_control/ride_status.json?auth={_current_auth_token()}"
        r = requests.patch(url, json=payload, timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"Firebase set_control_flag exception: {e}")
        return False
