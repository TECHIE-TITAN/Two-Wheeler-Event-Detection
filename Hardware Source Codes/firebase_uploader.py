import time
import os
import requests
from typing import Dict, Optional  # Removed Tuple since we no longer return a pair

DB_URL = "https://wheeler-event-detection-default-rtdb.asia-southeast1.firebasedatabase.app"
_API_KEY = "AIzaSyA__tMBGiQ-PVqyvv9kvNHaSUJk2QPXU-c"
_EMAIL = "rpi@example.com"
_PASSWORD = "rpi123456"
DEFAULT_USER_ID = "ocadXHESmIZ8TUHfzN2ZYKV51os2"

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


def init_ride(user_id: str, start_timestamp_ms: int) -> bool:
    # Legacy init_ride writes to a non-ride-scoped location. Keep for
    # backward compatibility but prefer ride-scoped control paths.
    url = f"{DB_URL}/users/{user_id}/rider_control.json?auth={_current_auth_token()}"
    payload = {
        "is_active": True,
        "start_time": start_timestamp_ms,
        "calculate_model": False
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase ride init exception: {e}")
        return False


def init_ride_for_ride(user_id: str, ride_id: str, start_timestamp_ms: int) -> bool:
    """Initialize ride control status under a rides/{ride_id} path."""
    # New schema: rides/{ride_id}/ride_control contains control keys
    url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_control.json?auth={_current_auth_token()}"
    payload = {
        "is_active": True,
        "calculate_model": False,
        "start_time": start_timestamp_ms
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase init_ride_for_ride exception: {e}")
        return False


def init_auth():
    _sign_in_email_password()


# ---- Ride data uploads for new schema ----
def upload_ride_raw_data_for_ride(user_id: str, ride_id: str, rows: list) -> bool:
    """PUT the full array of CSV row dicts to users/{uid}/rides/{ride_id}/raw_data"""
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/raw_data.json?auth={_current_auth_token()}"
        resp = requests.put(url, json=rows, timeout=20)
        return resp.status_code == 200
    except Exception as e:
        print(f"Firebase upload_ride_raw_data_for_ride exception: {e}")
        return False


def upload_ride_processed_for_ride(user_id: str, ride_id: str, processed_obj: dict) -> bool:
    """Write processed/model outputs under users/{uid}/rides/{ride_id}/processed"""
    try:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/processed.json?auth={_current_auth_token()}"
        resp = requests.patch(url, json=processed_obj, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Firebase upload_ride_processed_for_ride exception: {e}")
        return False


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
        return str(max(numeric_ids))
    except Exception as e:
        print(f"Firebase get_next_ride_id exception: {e}")
        return "0"


def set_control_flag(user_id: str, field: str, value: bool, ride_id: Optional[str] = None) -> bool:
    """Sets a boolean field under ride_status for a ride if ride_id provided,
    otherwise tries the legacy top-level paths.
    """
    payload = {field: bool(value)}
    try:
        if ride_id:
            url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_control.json?auth={_current_auth_token()}"
            r = requests.patch(url, json=payload, timeout=5)
            return r.status_code == 200
        # Try legacy fallback location
        r = requests.patch(_ride_status_url(user_id, True), json=payload, timeout=5)
        if r.status_code == 200:
            return True
    except Exception as e:
        print(f"Firebase set_control_flag (primary) exception: {e}")

    try:
        r = requests.patch(_ride_status_url(user_id, False), json=payload, timeout=5)
        return r.status_code == 200
    except Exception as e:
        print(f"Firebase set_control_flag (fallback) exception: {e}")
        return False


def toggle_calculate_model_off(user_id: str, ride_id: Optional[str] = None) -> bool:
    """Convenience helper to set calculate_model back to False for a ride or legacy path."""
    return set_control_flag(user_id, "calculate_model", False, ride_id=ride_id)
