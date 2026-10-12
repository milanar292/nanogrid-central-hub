"""Simulated houses H2, H3, H4 for the nanogrid hub.
Publishes fixed data to nanogrid/house/{H2,H3,H4}/data every 2 seconds.
Keep this running; the bridge ignores data older than 10 s."""
import json
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

HOST = "127.0.0.1"
PORT = 1883

HOUSES = {
    "H2": {"P_G": 100, "P_D": 40, "P_avail": 40, "C": 12, "soc_pct": 60, "capacity_Wh": 100},  # surplus house
    "H3": {"P_G": 30,  "P_D": 60, "P_avail": 20, "C": 8,  "soc_pct": 40, "capacity_Wh": 100},  # deficit house
    "H4": {"P_G": 50,  "P_D": 50, "P_avail": 30, "C": 15, "soc_pct": 50, "capacity_Wh": 100},  # balanced house
}

client = mqtt.Client(callback_api_version=CallbackAPIVersion.VERSION2,
                     client_id="nanogrid-seed")
client.connect(HOST, PORT, keepalive=60)
client.loop_start()
print("[seed] publishing H2, H3, H4 every 2 s - press Ctrl+C to stop")

seq = 0
try:
    while True:
        seq += 1
        for hid, data in HOUSES.items():
            doc = {"id": hid, "seq": seq}
            doc.update(data)
            client.publish(f"nanogrid/house/{hid}/data", json.dumps(doc), qos=1)
        print(f"[seed] sent seq {seq}")
        time.sleep(2)
except KeyboardInterrupt:
    pass
finally:
    client.loop_stop()
    client.disconnect()