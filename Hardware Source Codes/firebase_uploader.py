import time
import requests
from typing import Dict, Optional, Tuple

DB_URL = "https://wheeler-event-detection-default-rtdb.asia-southeast1.firebasedatabase.app"
_API_KEY = "AIzaSyA__tMBGiQ-PVqyvv9kvNHaSUJk2QPXU-c"
_EMAIL = "rpi@example.com"
_PASSWORD = "rpi123456"
DEFAULT_USER_ID = "test_user_123"

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
    return _ID_TOKEN


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


def init_ride(user_id: str, start_timestamp_ms: int) -> bool:
    url = f"{DB_URL}/users/{user_id}/rider_control/ride_status.json?auth={_current_auth_token()}"
    payload = {
        "is_active": True,
        "start_timestamp": start_timestamp_ms,
        "end_ride_signal": False
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase ride init exception: {e}")
        return False


def init_auth():
    _sign_in_email_password()


# ---- Control flags (Realtime Database) ----
def _ride_status_url(user_id: str, prefer_top_level: bool = True) -> str:
    # Prefer top-level path: /{user_id}/ride_control/ride_status
    # Fallback used by existing writers is /users/{user_id}/...
    if prefer_top_level:
        return f"{DB_URL}/{user_id}/ride_control/ride_status.json?auth={_current_auth_token()}"
    return f"{DB_URL}/users/{user_id}/rider_control/ride_status.json?auth={_current_auth_token()}"


def get_control_flags(user_id: str) -> Tuple[bool, bool]:
    """
    Returns (is_active, calculate_model) from Realtime DB.
    Tries top-level path first, then falls back to /users path.
    """
    try:
        # Try top-level
        resp = requests.get(_ride_status_url(user_id, True), timeout=5)
        if resp.status_code == 200:
            js = resp.json() or {}
            is_active = bool(js.get("is_active", False))
            calculate_model = bool(js.get("calculate_model", False))
            return is_active, calculate_model
    except Exception as e:
        print(f"Firebase get_control_flags (top-level) exception: {e}")

    try:
        # Fallback to /users
        resp = requests.get(_ride_status_url(user_id, False), timeout=5)
        if resp.status_code == 200:
            js = resp.json() or {}
            is_active = bool(js.get("is_active", False))
            calculate_model = bool(js.get("calculate_model", False))
            return is_active, calculate_model
    except Exception as e:
        print(f"Firebase get_control_flags (/users) exception: {e}")

    return False, False


def set_control_flag(user_id: str, field: str, value: bool) -> bool:
    """Sets a boolean field under ride_status, trying top-level first then /users."""
    payload = {field: bool(value)}
    try:
        r = requests.patch(_ride_status_url(user_id, True), json=payload, timeout=5)
        if r.status_code == 200:
            return True
    except Exception as e:
        print(f"Firebase set_control_flag (top-level) exception: {e}")

    try:
        r = requests.patch(_ride_status_url(user_id, False), json=payload, timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"Firebase set_control_flag (/users) exception: {e}")
        return False


def toggle_calculate_model_off(user_id: str) -> bool:
    """Convenience helper to set calculate_model back to False."""
    return set_control_flag(user_id, "calculate_model", False)