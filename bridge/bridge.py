
import os
import json
import time
import csv
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision, WriteOptions


MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.environ["INFLUXDB_TOKEN"]
INFLUX_ORG = os.getenv("INFLUX_ORG", "dc_project")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "energy")

LOG_PATH = "/app/logs/messages.csv"

os.makedirs("/app/logs", exist_ok=True)

log_file = open(LOG_PATH, "a", newline="", buffering=1)
writer = csv.writer(log_file)

if log_file.tell() == 0:
    writer.writerow([
        "device_id", "seq", "t_pub", "t_sub",
        "t_db_ack", "topic", "qos", "value"
    ])

influx = InfluxDBClient(
    url=INFLUX_URL,
    token=INFLUX_TOKEN,
    org=INFLUX_ORG
)

# Synchronous write: t_db_ack is recorded after the
# InfluxDB write request completes successfully.
write_api = influx.write_api(write_options=WriteOptions(
    batch_size=1,
    flush_interval=1,
    write_type=1
))

def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"MQTT connection failed: {reason_code}", flush=True)
        return

    client.subscribe("home/#", qos=1)
    print("Bridge subscribed to home/#", flush=True)


def on_message(client, userdata, msg):
    t_sub = time.time_ns()

    try:
        payload = json.loads(msg.payload.decode("utf-8"))

        device_id = payload["device_id"]
        seq = int(payload["seq"])
        t_pub = int(payload["t_pub"])
        value = payload["value"]

        parts = msg.topic.split("/")
        if len(parts) != 4 or parts[0] != "home":
            raise ValueError(f"Invalid topic: {msg.topic}")

        _, room, topic_device, metric = parts

        if topic_device != device_id:
            raise ValueError("Topic device_id does not match payload")

        # InfluxDB schema: one measurement per metric.
        # State transitions are logged but not written as a
        # numeric measurement in the P0 power dashboard.
        if metric in ("power", "temperature", "humidity"):
            point = (
                Point(metric)
                .tag("device_id", device_id)
                .tag("room", room)
                .field("value", float(value))
                .field("seq", seq)
                .time(t_pub, WritePrecision.NS)
            )

            influx.write_api(
                write_options=WriteOptions(write_type=1)
            ).write(
                bucket=INFLUX_BUCKET,
                org=INFLUX_ORG,
                record=point
            )

        t_db_ack = time.time_ns()

        writer.writerow([
            device_id, seq, t_pub, t_sub, t_db_ack,
            msg.topic, msg.qos, value
        ])

        print(
            f"{device_id} seq={seq} metric={metric} "
            f"L1={(t_sub-t_pub)/1e6:.2f} ms",
            flush=True
        )

    except Exception as exc:
        print(f"Bridge error: {exc}", flush=True)


client = mqtt.Client(
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    client_id="dc_influx_bridge"
)

client.on_connect = on_connect
client.on_message = on_message

print("Connecting bridge to Mosquitto...", flush=True)
client.connect(MQTT_HOST, 1883, 60)
client.loop_forever()
