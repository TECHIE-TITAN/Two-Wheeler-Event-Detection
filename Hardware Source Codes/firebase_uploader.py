import time
import requests
from typing import Dict, Optional

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