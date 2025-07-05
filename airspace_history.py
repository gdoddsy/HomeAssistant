#!/usr/bin/env python3
import os
import json
import paho.mqtt.client as mqtt
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from math import radians, cos, sin, asin, sqrt
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

# --- Configuration ---
ARCHIVE_DIR = "/run/tar1090"
STATE_DIR = "/home/pi/airspace_state"

MQTT_BROKER = "ha.doddsy.com.au"
MQTT_PORT = 1883
MQTT_USER = "mqttclient"
MQTT_PASS = "ROLEX-cheering5townsend"

RECEIVER_LAT = -34.049953
RECEIVER_LON = 150.724844
HOME_COORDS = (RECEIVER_LAT, RECEIVER_LON)

# --- Setup paths and state ---
today = datetime.now(ZoneInfo("Australia/Sydney")).date()
today_str = today.strftime("%Y-%m-%d")
os.makedirs(STATE_DIR, exist_ok=True)
STATE_FILE = os.path.join(STATE_DIR, f"{today_str}.json")


def distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance using Haversine formula (in kilometers)."""
    from math import radians, cos, sin, asin, sqrt
    R = 6371.0  # Earth radius in km
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
    return R * 2 * asin(sqrt(a))

# 📍 Reverse geocode
def reverse_geocode(lat, lon):
    try:
        geolocator = Nominatim(user_agent="airspace_snapshot")
        location = geolocator.reverse((lat, lon), language="en", timeout=10)
        return location.address if location else "Unknown"
    except GeocoderTimedOut:
        return "Timed out"
    except Exception as e:
        return f"Error: {e}"

# --- Load previous state ---
last_file = None
unique_flights = set()
furthest = {}

if os.path.exists(STATE_FILE):
    with open(STATE_FILE) as f:
        state = json.load(f)
    last_file = state.get("last_filename")
    unique_flights = set(state.get("unique_flights", []))
    furthest = state.get("furthest", {})

last_file_prev = last_file
last_filepath = os.path.join(ARCHIVE_DIR, last_file) if last_file else None


# --- Process new history files ---
files = sorted(f for f in os.listdir(ARCHIVE_DIR) if f.startswith("history_") and f.endswith(".json"))
print(f"🗂️  Found {len(files)} total history files in {ARCHIVE_DIR}")

if last_file:
    files = [f for f in files if f > last_file]
    print(f"🔍 Filtering to files newer than {last_file} → {len(files)} files remain")
else:
    print("⚠️ No last_file found — will process all history files")

for filename in files:
    print(f"📖 Attempting to process: {filename}")
    filepath = os.path.join(ARCHIVE_DIR, filename)

    try:
        if os.path.getsize(filepath) < 10:
            raise ValueError("File too small")

        aircraft = []
        with open(filepath) as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip().rstrip(',')
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    aircraft.extend(obj.get("aircraft", []))
                except json.JSONDecodeError as e:
                    print(f"⚠️ Line {lineno} in {filename} failed: {e}")

        print(f"✅ Parsed {filename} with {len(aircraft)} aircraft")
        
        for ac in aircraft:
            if not isinstance(ac, list) or len(ac) < 9:
                continue

            callsign = ac[8]
            if callsign and callsign.strip():
                unique_flights.add(callsign.strip())

            lat, lon = ac[4], ac[5]
            if lat is not None and lon is not None:
                dist = distance_km(HOME_COORDS[0], HOME_COORDS[1], lat, lon)
                if not furthest or dist > furthest.get("distance_km", 0):
                    furthest = {
                        "distance_km": round(dist, 1),
                        "coords": [lat, lon],
                        "location": reverse_geocode(lat, lon)
                    }

        last_file = filename

    except Exception as e:
        print(f"❌ Failed to parse {filename}: {e}")

# --- Save updated state ---
with open(STATE_FILE, "w") as f:
    json.dump({
        "last_filename": last_file,
        "unique_flights": sorted(unique_flights),
        "furthest": furthest
    }, f)

# --- Cleanup old state files ---
cutoff = today - timedelta(days=7)
for f in os.listdir(STATE_DIR):
    if f.endswith(".json"):
        try:
            dt = datetime.strptime(f.rstrip(".json"), "%Y-%m-%d").date()
            if dt < cutoff:
                os.remove(os.path.join(STATE_DIR, f))
        except ValueError:
            continue

# --- MQTT publish ---
client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.connect(MQTT_BROKER, MQTT_PORT, 60)

# --- Publish MQTT Discovery for each sensor individually ---

# 1. Unique Flights Today
client.publish("homeassistant/sensor/airspace_unique_flight_count/config", json.dumps({
    "name": "Airspace Unique Flights (Today)",
    "state_topic": "adsb/airspace/unique_flight_count",
    "unit_of_measurement": "flights",
    "icon": "mdi:airplane-clock",
    "unique_id": "airspace_unique_flight_count"
}), retain=True)

# 2. Furthest Distance (km)
client.publish("homeassistant/sensor/airspace_furthest_km/config", json.dumps({
    "name": "Airspace Furthest Distance",
    "state_topic": "adsb/airspace/furthest_km",
    "unit_of_measurement": "km",
    "device_class": "distance",
    "icon": "mdi:map-marker-distance",
    "unique_id": "airspace_furthest_km"
}), retain=True)

# 3. Furthest Location (reverse geocoded)
client.publish("homeassistant/sensor/airspace_furthest_location/config", json.dumps({
    "name": "Airspace Furthest Location",
    "state_topic": "adsb/airspace/furthest_location",
    "icon": "mdi:map-marker",
    "unique_id": "airspace_furthest_location"
}), retain=True)

# 4. Furthest Coordinates (also used on map)
client.publish("homeassistant/sensor/airspace_furthest_coords/config", json.dumps({
    "name": "Airspace Furthest Coordinates",
    "state_topic": "adsb/airspace/furthest_coords",
    "icon": "mdi:map-marker-distance",
    "unique_id": "airspace_furthest_coords",
    "json_attributes_topic": "adsb/airspace/furthest_coords/attributes"
}), retain=True)

# --- Publish values only if new files were processed ---
if last_file != last_file_prev:
    client.publish("adsb/airspace/unique_flight_count", len(unique_flights), retain=True)
    print("✅ New data found in files → Publishing updated metrics:")
    print(f"  • Unique Flights Today     → {len(unique_flights)}")

    if furthest:
        lat, lon = furthest["coords"]
        coord_str = f"{lat:.4f},{lon:.4f}"
        client.publish("adsb/airspace/furthest_coords", coord_str, retain=True)
        client.publish("adsb/airspace/furthest_coords/attributes", json.dumps({
            "latitude": lat,
            "longitude": lon,
            "location": furthest.get("location", "Unknown"),
            "distance_km": furthest.get("distance_km", 0)
        }), retain=True)

        client.publish("adsb/airspace/furthest_location", furthest.get("location", "Unknown"), retain=True)
        client.publish("adsb/airspace/furthest_km", furthest.get("distance_km", 0), retain=True)
        print(f"  • Furthest Distance (km)   → {furthest['distance_km']}")
        print(f"  • Furthest Coords          → {coord_str}")
        print(f"  • Furthest Location        → {furthest.get('location', 'Unknown')}")
else:
    print("No new files — skipping furthest + unique flight publish")

client.disconnect()