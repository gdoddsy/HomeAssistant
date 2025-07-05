#!/usr/bin/env python3
import os
import json
from datetime import datetime
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import paho.mqtt.client as mqtt

# 📍 Receiver location
RECEIVER_LAT = -33.9
RECEIVER_LON = 150.9
RECEIVER_POS = (RECEIVER_LAT, RECEIVER_LON)

# 🔍 Paths
HISTORY_DIR = "/run/tar1090"
OUTPUT_FILE = "/home/pi/airspace_snapshot.txt"

# 📊 Tracking
seen_hexes = set()
furthest_distance = 0
furthest_coords = None

# 🗂️ Scan history files
history_files = sorted(
    f for f in os.listdir(HISTORY_DIR)
    if f.startswith("history_") and f.endswith(".json")
)

for fname in history_files:
    full_path = os.path.join(HISTORY_DIR, fname)
    if os.path.getsize(full_path) == 0:
        continue  # Skip empty files

    try:
        with open(full_path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    for ac in data.get("aircraft", []):
                        hex_id = ac[0]
                        seen_hexes.add(hex_id)

                        # Check if valid position
                        if (
                            len(ac) > 5 and
                            isinstance(ac[4], float) and
                            isinstance(ac[5], float) and
                            -90 <= ac[4] <= 90 and
                            -180 <= ac[5] <= 180
                        ):
                            dist = geodesic(RECEIVER_POS, (ac[4], ac[5])).km
                            if 0 < dist < 1000 and dist > furthest_distance:
                                furthest_distance = dist
                                furthest_coords = (ac[4], ac[5])
                except json.JSONDecodeError as e:
                    print(f"Line error in {fname}: {e}")
    except Exception as e:
        print(f"File error in {fname}: {e}")

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

furthest_location = None
if furthest_coords:
    furthest_location = reverse_geocode(*furthest_coords)

# 📝 Compose summary
summary = (
    f"Total in {len(history_files) * 5} mins: {len(seen_hexes)} aircraft\n"
    f"Furthest: {furthest_distance:.1f} km"
)
if furthest_coords:
    summary += f" at ({furthest_coords[0]:.4f}, {furthest_coords[1]:.4f})"
if furthest_location:
    summary += f"\nNear: {furthest_location}"

# 💾 Write to file
with open(OUTPUT_FILE, "w") as f:
    f.write(summary + "\n")

# 🖥️ Optional: Print to console
print(summary)

# 📡 MQTT publish
MQTT_BROKER = "ha.doddsy.com.au"
MQTT_PORT = 1883
MQTT_USER = "mqttclient"
MQTT_PASS = "ROLEX-cheering5townsend"

client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.connect(MQTT_BROKER, MQTT_PORT, 60)

client.publish("homeassistant/sensor/airspace_total/config", json.dumps({
    "name": "Airspace Total (Today)",
    "state_topic": "adsb/airspace/total",
    "unit_of_measurement": "aircraft",
    "unique_id": "airspace_total",
}), retain=True)
client.publish("homeassistant/sensor/airspace_furthest_km/config", json.dumps({
    "name": "Airspace Furthest Distance",
    "state_topic": "adsb/airspace/furthest_km",
    "unit_of_measurement": "km",
    "device_class": "distance",
    "unique_id": "airspace_furthest_km"
}), retain=True)

client.publish("homeassistant/sensor/airspace_furthest_coords/config", json.dumps({
    "name": "Airspace Furthest Coordinates",
    "state_topic": "adsb/airspace/furthest_coords",
    "unique_id": "airspace_furthest_coords",
    "icon": "mdi:map-marker-distance"
}), retain=True)

client.publish("homeassistant/sensor/airspace_furthest_location/config", json.dumps({
    "name": "Airspace Furthest Location",
    "state_topic": "adsb/airspace/furthest_location",
    "unique_id": "airspace_furthest_location",
    "icon": "mdi:map-marker"
}), retain=True)

client.publish("adsb/airspace/total", len(seen_hexes))
client.publish("adsb/airspace/furthest_km", round(furthest_distance, 1))
if furthest_coords:
    coord_str = f"{furthest_coords[0]:.4f},{furthest_coords[1]:.4f}"
    client.publish("adsb/airspace/furthest_coords", coord_str)
if furthest_location:
    client.publish("adsb/airspace/furthest_location", furthest_location)

client.disconnect()
