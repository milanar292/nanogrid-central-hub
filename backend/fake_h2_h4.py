import json
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

HOST = "127.0.0.1"
PORT = 1883

FAKE = {
    "H2": {"P_G": 300, "P_D": 200, "P_avail": 50, "C": 8},
    "H3": {"P_G": 100, "P_D": 250, "P_avail": 80, "C": 12},
    "H4": {"P_G": 150, "P_D": 150, "P_avail": 60, "C": 10},
}

client = mqtt.Client(
    callback_api_version=CallbackAPIVersion.VERSION2,
    client_id="fake-h2-h4",
)
client.connect(HOST, PORT, keepalive=60)
client.loop_start()
print("fake publisher running for H2, H3, H4 (Ctrl+C to stop)")

try:
    while True:
        for hid, data in FAKE.items():
            client.publish(f"nanogrid/house/{hid}/data", json.dumps(data), qos=1)
        print("published H2, H3, H4")
        time.sleep(2)
except KeyboardInterrupt:
    pass
finally:
    client.loop_stop()
    client.disconnect()