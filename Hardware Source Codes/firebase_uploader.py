import time
import os
import base64
import requests
from typing import Dict, Optional, Tuple

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
    # Legacy init_ride writes to the non-ride-scoped location. Keep for
    # backward compatibility; prefer using init_ride_for_ride with ride_id.
    url = f"{DB_URL}/users/{user_id}/rider_control/ride_status.json?auth={_current_auth_token()}"
    payload = {
        "is_active": True,
        "start_timestamp": start_timestamp_ms,
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
    url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/rider_control/ride_status.json?auth={_current_auth_token()}"
    payload = {
        "is_active": True,
        "start_timestamp": start_timestamp_ms,
        "calculate_model": False
    }
    try:
        response = requests.patch(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Firebase init_ride_for_ride exception: {e}")
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
    # This legacy function remains but we now route through the more general
    # ride-scoped helper below. Keep for backward compatibility.
    return get_control_flags_for_ride(user_id, None)


def get_control_flags_for_ride(user_id: str, ride_id: Optional[str]) -> Tuple[bool, bool]:
    """Returns (is_active, calculate_model) for a given ride_id.
    If ride_id is None, falls back to the top-level control locations.
    """
    try:
        if ride_id:
            url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/rider_control/ride_status.json?auth={_current_auth_token()}"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                js = resp.json() or {}
                return bool(js.get("is_active", False)), bool(js.get("calculate_model", False))
        # Try top-level locations (preferred path and fallback)
        resp = requests.get(_ride_status_url(user_id, True), timeout=5)
        if resp.status_code == 200:
            js = resp.json() or {}
            return bool(js.get("is_active", False)), bool(js.get("calculate_model", False))
    except Exception as e:
        print(f"Firebase get_control_flags_for_ride exception: {e}")

    try:
        resp = requests.get(_ride_status_url(user_id, False), timeout=5)
        if resp.status_code == 200:
            js = resp.json() or {}
            return bool(js.get("is_active", False)), bool(js.get("calculate_model", False))
    except Exception as e:
        print(f"Firebase get_control_flags_for_ride fallback exception: {e}")

    return False, False


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
    """Sets a boolean field under ride_status for a ride if ride_id provided,
    otherwise tries the legacy top-level paths.
    """
    payload = {field: bool(value)}
    try:
        if ride_id:
            url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/rider_control/ride_status.json?auth={_current_auth_token()}"
            r = requests.patch(url, json=payload, timeout=5)
            return r.status_code == 200
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


def upload_ride_data(user_id: str, ride_rows: list) -> bool:
    """Uploads the entire ride CSV (as JSON list of rows).

    If ride_rows belong to a specific ride, pass a `ride_id` and the data
    will be stored at `/users/{user_id}/rides/{ride_id}/ride_data`.
    """
    # Backward compatible single-arg signature (no ride_id) expects ride_rows only
    return upload_ride_data_for_ride(user_id, None, ride_rows)


def upload_ride_data_for_ride(user_id: str, ride_id: Optional[str], ride_rows: list) -> bool:
    if ride_id:
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_data.json?auth={_current_auth_token()}"
    else:
        url = f"{DB_URL}/users/{user_id}/ride_data.json?auth={_current_auth_token()}"
    try:
        r = requests.put(url, json=ride_rows, timeout=15)
        return r.status_code in (200, 204)
    except Exception as e:
        print(f"Firebase upload_ride_data exception: {e}")
        return False


def upload_ride_image_base64(user_id: str, file_path: str, content_type: str = "image/jpeg", ride_id: Optional[str] = None) -> Optional[str]:
    """Uploads an image as base64 into Realtime DB under /users/{user_id}/ride_images/.

    Returns the database ref path string on success, else None.
    """
    try:
        if not os.path.exists(file_path):
            print(f"Image not found: {file_path}")
            return None
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")

        ts_ms = int(time.time() * 1000)
        # Use timestamp as key when ride-scoped to map image by timestamp
        if ride_id:
            # Delegate to the ride-scoped uploader which stores under `ride_images_base64`.
            return upload_ride_image_base64_for_ride(user_id, ride_id, str(ts_ms), file_path, content_type)
        else:
            key = os.path.splitext(os.path.basename(file_path))[0] or f"img_{ts_ms}"
            # Ensure key is Firebase-safe
            key = key.replace('.', '_')
            url = f"{DB_URL}/users/{user_id}/ride_images/{key}.json?auth={_current_auth_token()}"
        payload = {
            "filename": os.path.basename(file_path),
            "content_type": content_type,
            "uploaded_at": ts_ms,
            "data_base64": b64
        }
        r = requests.put(url, json=payload, timeout=20)
        if r.status_code in (200, 204):
            return f"users/{user_id}/ride_images/{key}"
        print(f"Image upload failed ({r.status_code}): {r.text[:200]}")
        return None
    except Exception as e:
        print(f"Firebase upload_ride_image_base64 exception: {e}")
        return None

def upload_ride_image_base64_for_ride(user_id: str, ride_id: str, timestamp_key: str, file_path: str, content_type: str = "image/jpeg") -> Optional[str]:
    """Uploads an image's base64 under a specific ride at
    `/users/{user_id}/rides/{ride_id}/ride_images_base64/{timestamp_key}`.

    The stored value is an object with `content_type`, `uploaded_at`, and `data_base64`.
    Returns the DB path on success.
    """
    try:
        if not os.path.exists(file_path):
            print(f"Image not found: {file_path}")
            return None
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")

        ts_ms = int(time.time() * 1000)
        # sanitize timestamp_key to be Firebase-key-safe
        key = str(timestamp_key).replace('.', '_')
        url = f"{DB_URL}/users/{user_id}/rides/{ride_id}/ride_images_base64/{key}.json?auth={_current_auth_token()}"
        payload = {
            "content_type": content_type,
            "uploaded_at": ts_ms,
            "data_base64": b64
        }
        r = requests.put(url, json=payload, timeout=30)
        if r.status_code in (200, 204):
            return f"users/{user_id}/rides/{ride_id}/ride_images_base64/{key}"
        print(f"Ride image upload failed ({r.status_code}): {r.text[:200]}")
        return None
    except Exception as e:
        print(f"Firebase upload_ride_image_base64_for_ride exception: {e}")
        return None