import json
import math
import os
import random
import threading
import time

import paho.mqtt.client as mqtt


# Configuration supplied by Docker Compose
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

DEVICE_ID = os.environ["DEVICE_ID"]
ROOM = os.environ["ROOM"]
SENSOR_TYPE = os.environ["SENSOR_TYPE"].lower()

INTERVAL = float(os.getenv("PUBLISH_INTERVAL", "1.0"))
QOS = int(os.getenv("PUBLISH_QOS", "0"))
SEED = int(os.getenv("SEED", "1"))

if QOS not in (0, 1):
    raise ValueError("PUBLISH_QOS must be 0 or 1")

rng = random.Random(SEED)


def connect_mqtt():
    """Connect to Mosquitto, retrying if the broker is not ready yet."""
    while True:
        connected = threading.Event()

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=DEVICE_ID,
            protocol=mqtt.MQTTv311,
        )

        def on_connect(client, userdata, flags, reason_code, properties):
            if reason_code.is_failure:
                print(
                    f"[{DEVICE_ID}] MQTT connection failed: {reason_code}",
                    flush=True,
                )
            else:
                print(f"[{DEVICE_ID}] Connected to MQTT broker", flush=True)
                connected.set()

        client.on_connect = on_connect

        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=30)
            client.loop_start()

            if connected.wait(timeout=10):
                return client

            client.loop_stop()
            client.disconnect()
            print(f"[{DEVICE_ID}] Connection timed out; retrying", flush=True)

        except Exception as exc:
            print(f"[{DEVICE_ID}] MQTT error: {exc}", flush=True)

        time.sleep(2)


class DevicePublisher:
    def __init__(self, client):
        self.client = client
        self.seq = 0

    def publish(self, metric, value, unit=None, target_bytes=None):
        # One monotonically increasing sequence per device,
        # including thermostat state-change messages.
        seq = self.seq
        self.seq += 1

        payload = {
            "device_id": DEVICE_ID,
            "seq": seq,
            "t_pub": time.time_ns(),
            "value": value,
        }

        if unit is not None:
            payload["unit"] = unit

        # Match the specified JSON payload sizes for power and
        # ambient sensors. Padding is data-size filler only.
        if target_bytes is not None:
            payload["padding"] = ""

            encoded = json.dumps(
                payload, separators=(",", ":"), ensure_ascii=True
            ).encode("utf-8")

            padding_length = target_bytes - len(encoded)

            if padding_length < 0:
                raise ValueError(
                    f"{DEVICE_ID}: base payload exceeds "
                    f"{target_bytes} bytes"
                )

            payload["padding"] = "x" * padding_length

        encoded = json.dumps(
            payload, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")

        if target_bytes is not None and len(encoded) != target_bytes:
            raise ValueError(
                f"{DEVICE_ID}: expected {target_bytes} bytes, "
                f"got {len(encoded)}"
            )

        topic = f"home/{ROOM}/{DEVICE_ID}/{metric}"

        result = self.client.publish(
            topic,
            encoded,
            qos=QOS,
            retain=False,
        )

        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            print(f"[{DEVICE_ID}] Publish failed: {result.rc}", flush=True)
            return

        print(
            f"[{DEVICE_ID}] topic={topic} seq={seq} "
            f"payload_bytes={len(encoded)} qos={QOS}",
            flush=True,
        )


def run_power_meter(publisher):
    """Power meter: 1 message/s, 250-byte JSON payload."""
    sample = 0

    while True:
        watts = round(
            420
            + 65 * math.sin(sample / 8)
            + rng.uniform(-6, 6),
            2,
        )

        publisher.publish(
            metric="power",
            value=watts,
            unit="W",
            target_bytes=250,
        )

        sample += 1
        time.sleep(INTERVAL)


def run_thermostat(publisher):
    """Thermostat: temperature at 0.5 Hz and state on transitions."""
    sample = 0
    last_state = None

    while True:
        temperature = round(
            21
            + 2 * math.sin(sample / 3)
            + rng.uniform(-0.15, 0.15),
            2,
        )

        publisher.publish(
            metric="temperature",
            value=temperature,
            unit="C",
        )

        state = "heating" if temperature < 20.0 else "idle"

        # Publish the initial state, then every subsequent state change.
        if state != last_state:
            publisher.publish(metric="state", value=state)
            last_state = state

        sample += 1
        time.sleep(INTERVAL)


def run_ambient_sensor(publisher):
    """Ambient sensor: 0.5 messages/s, 100-byte JSON payload."""
    while True:
        humidity = round(45 + rng.uniform(-4, 4), 1)

        publisher.publish(
            metric="humidity",
            value=humidity,
            target_bytes=100,
        )

        time.sleep(INTERVAL)


def main():
    client = connect_mqtt()
    publisher = DevicePublisher(client)

    print(
        f"[{DEVICE_ID}] type={SENSOR_TYPE}, "
        f"room={ROOM}, interval={INTERVAL}s, QoS={QOS}, seed={SEED}",
        flush=True,
    )

    if SENSOR_TYPE == "power":
        run_power_meter(publisher)
    elif SENSOR_TYPE == "thermostat":
        run_thermostat(publisher)
    elif SENSOR_TYPE == "ambient":
        run_ambient_sensor(publisher)
    else:
        raise ValueError(f"Unsupported SENSOR_TYPE: {SENSOR_TYPE}")


if __name__ == "__main__":
    main()