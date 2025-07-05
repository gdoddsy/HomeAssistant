#!/usr/bin/env python3
import os
import json
import paho.mqtt.client as mqtt
from zoneinfo import ZoneInfo
from datetime import datetime
from math import radians, cos, sin, asin, sqrt, atan2, degrees

# --- Configuration ---
ARCHIVE_DIR = "/run/tar1090"
MQTT_BROKER = "ha.doddsy.com.au"
MQTT_PORT = 1883
MQTT_USER = "mqttclient"
MQTT_PASS = "ROLEX-cheering5townsend"
RECEIVER_LAT = -34.049953
RECEIVER_LON = 150.724844

# --- Distance and Bearing Helpers ---
def distance_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2)**2
    return R * 2 * asin(sqrt(a))

def bearing_deg(lat1, lon1, lat2, lon2):
    dlon = radians(lon2 - lon1)
    y = sin(dlon) * cos(radians(lat2))
    x = cos(radians(lat1)) * sin(radians(lat2)) - sin(radians(lat1)) * cos(radians(lat2)) * cos(dlon)
    return (degrees(atan2(y, x)) + 360) % 360

def bearing_to_compass(degrees):
    directions = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    return directions[int((degrees + 22.5) % 360 // 45)]

# --- Find the Latest Valid Aircraft Snapshot ---
def find_latest_valid_aircraft_snapshot():
    files = sorted(
        (f for f in os.listdir(ARCHIVE_DIR) if f.startswith("history_") and f.endswith(".json")),
        reverse=True
    )
    for fname in files:
        fpath = os.path.join(ARCHIVE_DIR, fname)
        try:
            if os.path.getsize(fpath) < 10:
                continue
            with open(fpath) as f:
                aircraft = []
                for line in f:
                    line = line.strip().rstrip(",")
                    if not line:
                        continue
                    obj = json.loads(line)
                    aircraft.extend(obj.get("aircraft", []))
            return fname, aircraft
        except Exception:
            continue
    return None, []

# --- Main Execution ---
last_file, aircraft = find_latest_valid_aircraft_snapshot()
print(f"📄 Snapshot: {last_file}")
print(f"📡 Aircraft Entries → {len(aircraft)}")

callsigns = set()
flight_lines = []

for ac in aircraft:
    if isinstance(ac, list) and len(ac) >= 9:
        callsign = ac[8]
        lat, lon = ac[4], ac[5]
        aircraft_type = ac[0] if len(ac) > 0 and ac[0] else "Unknown"
        altitude = ac[7] if len(ac) > 7 and isinstance(ac[7], (int, float)) else None

        if callsign and isinstance(lat, (int, float)) and isinstance(lon, (int, float)):
            callsigns.add(callsign.strip())
            dist = distance_km(RECEIVER_LAT, RECEIVER_LON, lat, lon)
            bearing = bearing_deg(RECEIVER_LAT, RECEIVER_LON, lat, lon)
            compass = bearing_to_compass(bearing)
            alt_str = f"{int(altitude)} ft" if altitude else "Altitude Unknown"
            line = f"{callsign.strip()} — {dist:.1f} km {compass} — {aircraft_type} @ {alt_str}"
            flight_lines.append(line)

print(f"📡 Flight Lines → {"\n".join(sorted(flight_lines))}")

# --- MQTT Publishing ---
client = mqtt.Client()
client.username_pw_set(MQTT_USER, MQTT_PASS)
client.connect(MQTT_BROKER, MQTT_PORT, 60)

# Discovery registration
client.publish("homeassistant/sensor/currently_tracking/config", json.dumps({
    "name": "Airspace Currently Tracking",
    "state_topic": "adsb/airspace/currently_tracking",
    "unit_of_measurement": "flights",
    "icon": "mdi:airplane",
    "unique_id": "currently_tracking"
}), retain=True)

client.publish("homeassistant/sensor/current_flights/config", json.dumps({
    "name": "Airspace Current Flights",
    "state_topic": "adsb/airspace/current_flights",
    "icon": "mdi:airplane",
    "unique_id": "current_flights"
}), retain=True)

# State publish
client.publish("adsb/airspace/currently_tracking", len(callsigns), retain=True)
client.publish("adsb/airspace/current_flights", "\n".join(sorted(flight_lines)), retain=True)

client.disconnect()