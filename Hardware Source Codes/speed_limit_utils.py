import requests

def get_speed_limit(latitude, longitude, api_key):
    url = "https://api.olamaps.io/routing/v1/speedLimits"
    points = f"{latitude},{longitude}|{latitude},{longitude}"
    params = {
        "points": points,
        "api_key": api_key
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            # Extract speed limit from response structure
            # This may need adjustment based on actual API response
            return data.get('speedLimits', [{}])[0].get('speedLimit')
        else:
            print(f"Speed limit API error: {response.status_code}")
    except Exception as e:
        print(f"Speed limit API exception: {e}")
    return None
