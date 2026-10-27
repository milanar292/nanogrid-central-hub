"""MQTT bridge between the nanogrid MQTT topics and the allocation logic.

Run from the backend folder:

    python mqtt_bridge.py

Reads house data from nanogrid/house/{H1..H4}/data (QoS 1) and publishes the
allocation results to nanogrid/house/{H1..H4}/result (QoS 1, not retained).
It also POSTs each house's data to the FastAPI backend so the dashboard updates.

Settings come from environment variables:
    MQTT_HOST       (default 127.0.0.1)
    MQTT_PORT       (default 1883)
    MQTT_USER       (default empty -> no login)
    MQTT_PASS       (default empty)
    MQTT_TLS        (default false; "true" enables TLS with system CA certs)
    STALE_SECONDS   (default 10)
    BACKEND_URL     (default http://127.0.0.1:8000)
"""

import json
import os
import sys
import time
import urllib.request

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from main import HouseData, run_allocation

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "")
MQTT_PASS = os.environ.get("MQTT_PASS", "")
MQTT_TLS = os.environ.get("MQTT_TLS", "false").strip().lower() == "true"
STALE_SECONDS = float(os.environ.get("STALE_SECONDS", "10"))
BACKEND_URL = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000")

DATA_TOPIC = "nanogrid/house/+/data"
RESULT_TOPIC = "nanogrid/house/{id}/result"

HOUSE_IDS = ("H1", "H2", "H3", "H4")
# P_avail is only required when the house does NOT send soc_pct
# (with soc_pct, the hub computes charge/discharge limits itself).
REQUIRED_FIELDS = ("P_G", "P_D", "C")
OPTIONAL_FIELDS = (("soc_pct", None), ("capacity_Wh", 30.0), ("P_avail", 0.0))

# Only forward the optional fields that run_allocation's input model accepts.
_MODEL_FIELDS = set(getattr(HouseData, "model_fields", {}).keys())
FORWARDED_FIELDS = tuple(name for name in ("soc_pct", "capacity_Wh", "rtc", "loads") if name in _MODEL_FIELDS)

latest: dict = {}        # house id -> last valid input payload
received_at: dict = {}   # house id -> monotonic receive time
last_missing_log = 0.0

# Houses that are not real yet. Their fixed values are used instead of MQTT data.
# Change these numbers to test other cases.
DUMMY_HOUSES = {
    "H2": {"P_G": 80.0, "P_D": 80.0, "P_avail": 20.0, "C": 1.0, "soc_pct": 20.0},
    "H3": {"P_G": 80.0, "P_D": 80.0, "P_avail": 20.0, "C": 1.0, "soc_pct": 40.0},
    "H4": {"P_G": 80.0, "P_D": 80.0, "P_avail": 20.0, "C": 1.0, "soc_pct": 20.0},
}
for _hid, _vals in DUMMY_HOUSES.items():
    latest[_hid] = {"id": _hid, "seq": None, "soc_pct": None, "capacity_Wh": 30.0,
                    "rtc": None, "loads": None, **_vals}


def _as_number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _handle_message(client, msg):
    parts = msg.topic.split("/")
    if len(parts) != 4 or parts[0] != "nanogrid" or parts[1] != "house" or parts[3] != "data":
        print(f"[bridge] ignoring message on unexpected topic: {msg.topic}")
        return

    house_id = parts[2]
    if house_id not in HOUSE_IDS:
        return

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as exc:
        print(f"[bridge] {house_id}: invalid JSON ({exc})")
        return

    if not isinstance(payload, dict):
        print(f"[bridge] {house_id}: message is not a JSON object")
        return

    values = {}
    for field in REQUIRED_FIELDS:
        if field not in payload:
            print(f"[bridge] {house_id}: missing required field '{field}'")
            return
        number = _as_number(payload[field])
        if number is None:
            print(f"[bridge] {house_id}: field '{field}' is not a number: {payload[field]!r}")
            return
        values[field] = number

    for field, default in OPTIONAL_FIELDS:
        if field in payload:
            number = _as_number(payload[field])
            if number is None:
                print(f"[bridge] {house_id}: field '{field}' is not a number, using {default}")
                values[field] = default
            else:
                values[field] = number
        else:
            values[field] = default

    if values["soc_pct"] is None and "P_avail" not in payload:
        print(f"[bridge] {house_id}: need either 'soc_pct' or 'P_avail'")
        return

    # Optional pass-through fields for the dashboard
    rtc = payload.get("rtc")
    values["rtc"] = rtc if isinstance(rtc, str) else None
    loads = payload.get("loads")
    if isinstance(loads, dict):
        values["loads"] = {str(k): n for k, v in loads.items() if (n := _as_number(v)) is not None}
    else:
        values["loads"] = None

    seq = _as_number(payload.get("seq"))
    record = {"id": house_id}
    record.update(values)
    record["seq"] = int(seq) if seq is not None else None
    latest[house_id] = record
    received_at[house_id] = time.monotonic()

    now = time.monotonic()
    stale = [
        hid
        for hid in HOUSE_IDS
        if hid not in DUMMY_HOUSES
        and (hid not in received_at or now - received_at[hid] >= STALE_SECONDS)
    ]
    if stale:
        global last_missing_log
        if now - last_missing_log >= 5.0:
            print(f"[bridge] waiting for fresh data from: {', '.join(stale)}")
            last_missing_log = now
        return

    _publish_results(client)


def _forward_to_backend(houses):
    """POST each house's data to the FastAPI backend so the dashboard updates."""
    for h in houses:
        body = json.dumps(h.model_dump() if hasattr(h, "model_dump") else h.dict()).encode("utf-8")
        req = urllib.request.Request(
            f"{BACKEND_URL}/houses/{h.id}/data",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=2).close()
        except Exception as exc:
            print(f"[bridge] backend POST failed for {h.id}: {exc}")
            return
    print("[bridge] forwarded data to backend")


def _publish_results(client):
    houses = []
    for hid in HOUSE_IDS:
        data = latest[hid]
        kwargs = {name: data.get(name) for name in FORWARDED_FIELDS}
        kwargs["source"] = "dummy" if hid in DUMMY_HOUSES else "live"
        if kwargs.get("soc_pct") is None:
            kwargs.pop("soc_pct", None)
        try:
            houses.append(
                HouseData(
                    id=hid,
                    P_G=data["P_G"],
                    P_D=data["P_D"],
                    P_avail=data["P_avail"],
                    C=data["C"],
                    **kwargs,
                )
            )
        except Exception as exc:
            print(f"[bridge] could not build input for {hid}: {exc}")
            return

    try:
        results = run_allocation(houses)
    except Exception as exc:
        print(f"[bridge] run_allocation failed: {exc}")
        return

    ts = int(time.time())
    published = []
    for result in results:
        if hasattr(result, "model_dump"):
            doc = result.model_dump()
        else:
            doc = result.dict()
        doc["ts"] = ts
        doc["ready"] = True
        doc["seq"] = latest[result.id].get("seq")
        client.publish(
            RESULT_TOPIC.format(id=result.id),
            json.dumps(doc),
            qos=1,
            retain=False,
        )
        published.append(result.id)
    print(f"[bridge] published results for {', '.join(published)} (ts={ts})")

    _forward_to_backend(houses)


def on_connect(client, userdata, flags, reason_code, properties):
    client.subscribe(DATA_TOPIC, qos=1)
    print(f"[bridge] connected to {MQTT_HOST}:{MQTT_PORT} as {reason_code}, "
          f"subscribed to {DATA_TOPIC} (QoS 1)")


def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    print(f"[bridge] disconnected ({reason_code}), reconnecting automatically")


def on_message(client, userdata, msg):
    try:
        _handle_message(client, msg)
    except Exception as exc:
        print(f"[bridge] error while handling {msg.topic}: {exc}")


def main():
    client = mqtt.Client(
        callback_api_version=CallbackAPIVersion.VERSION2,
        client_id="nanogrid-bridge",
    )
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASS or None)
    if MQTT_TLS:
        client.tls_set()  # system CA certificates
    client.reconnect_delay_set(min_delay=1, max_delay=60)
    client.suppress_exceptions = True
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            break
        except OSError as exc:
            print(f"[bridge] cannot reach {MQTT_HOST}:{MQTT_PORT} ({exc}), retrying in 5s")
            time.sleep(5)

    client.loop_start()
    print(f"[bridge] running, waiting for data on {DATA_TOPIC} "
          f"(staleness limit {STALE_SECONDS:g}s)")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("[bridge] shutting down")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
