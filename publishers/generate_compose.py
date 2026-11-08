import argparse

parser = argparse.ArgumentParser()
parser.add_argument(
    "--devices",
    type=int,
    choices=[10, 50, 100],
    required=True
)

args = parser.parse_args()

device_count = args.devices

counts = {
    10: (4, 3, 3),
    50: (20, 15, 15),
    100: (40, 30, 30),
}

power_count, thermostat_count, ambient_count = counts[device_count]

rooms = ["livingroom", "bedroom", "kitchen"]

device_groups = [
    ("power", "power_meter", power_count, 1.0),
    ("thermostat", "thermostat", thermostat_count, 2.0),
    ("ambient", "ambient", ambient_count, 2.0),
]

lines = ["services:"]

device_index = 0

for sensor_type, prefix, count, interval in device_groups:

    for number in range(1, count + 1):

        device_index += 1

        device_id = f"{prefix}_{number:02d}"
        service_name = f"workload_{prefix}_{number:02d}"

        room = rooms[(number - 1) % len(rooms)]

        lines.extend([
            f"  {service_name}:",
            "    build: ./publishers",
            "    image: dc-project-publisher:local",
            '    restart: "no"',
            "    depends_on:",
            "      - mosquitto",
            "    cap_add:",
            "      - NET_ADMIN",
            "    environment:",
            "      MQTT_HOST: mosquitto",
            '      MQTT_PORT: "1883"',
            f"      DEVICE_ID: {device_id}",
            f'      DEVICE_INDEX: "{device_index}"',
            '      RUN_SEED: "${RUN_SEED:-101}"',
            f"      ROOM: {room}",
            f"      SENSOR_TYPE: {sensor_type}",
            f'      PUBLISH_INTERVAL: "{interval}"',
            '      PUBLISH_QOS: "${PUBLISH_QOS:-0}"',
            '      LOAD_MODE: "${LOAD_MODE:-steady}"',
            '      LOG_EACH_PUBLISH: "${LOG_EACH_PUBLISH:-false}"',
            "",
        ])

print("\n".join(lines))