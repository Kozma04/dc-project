import os
import json
import time
import csv
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.environ["INFLUXDB_TOKEN"]
INFLUX_ORG = os.getenv("INFLUX_ORG", "dc_project")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "energy")

# One CSV per run: logs/messages_<RUN_ID>.csv  (RUN_ID comes from compose.run.yml;
# if it is empty a timestamp is used, so runs never get mixed in one file)
RUN_ID = os.getenv("RUN_ID") or time.strftime("run_%Y%m%d_%H%M%S")
LOG_PATH = f"/app/logs/messages_{RUN_ID}.csv"
os.makedirs("/app/logs", exist_ok=True)
log_file = open(LOG_PATH, "a", newline="", buffering=1)
writer = csv.writer(log_file)
if log_file.tell() == 0:
    writer.writerow([
        "device_id", "seq", "t_pub", "t_sub",
        "t_db_ack", "topic", "qos", "value",
        "mqtt_dup", "run_id"
    ])

influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
# FIX: SYNCHRONOUS write = the call returns only after InfluxDB answered,
# so t_db_ack is a real database acknowledgement. (write_type=1 is *batching*:
# write() returns immediately and the data is sent later, and creating a new
# write_api per message also leaks a background thread per message.)
write_api = influx.write_api(write_options=SYNCHRONOUS)


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"MQTT connection failed: {reason_code}", flush=True)
        return
    client.subscribe("home/#", qos=1)
    print(f"Bridge subscribed to home/# (run {RUN_ID})", flush=True)


def on_message(client, userdata, msg):
    t_sub = time.time_ns()   # first thing: arrival timestamp
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

        t_db_ack = ""   # stays empty for messages that are not written to the DB
        # State transitions are logged but not written as a numeric measurement.
        if metric in ("power", "temperature", "humidity"):
            point = (
                Point(metric)
                .tag("device_id", device_id)
                .tag("room", room)
                .field("value", float(value))
                .field("seq", seq)
                .time(t_pub, WritePrecision.NS)
            )
            try:
                write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)
                t_db_ack = time.time_ns()   # DB acknowledged the write
            except Exception as exc:
                print(f"Influx write failed: {exc}", flush=True)   # row is still logged

        writer.writerow([
            device_id, seq, t_pub, t_sub, t_db_ack,
            msg.topic, msg.qos, value, int(msg.dup), RUN_ID
        ])
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
