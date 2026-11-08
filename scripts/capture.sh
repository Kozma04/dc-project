#!/usr/bin/env bash
# Wire-byte capture on the docker bridge that carries the MQTT traffic (broker-facing interface).
# Usage: scripts/capture.sh start logs/<run_id>   |   scripts/capture.sh stop logs/<run_id>
# Capture filter (same for every run): tcp port 1883.
# Captures on the bridge, NOT "-i any" (that would count every packet twice).
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
ACTION=${1:-}; OUT=${2:-}
[[ -n "$ACTION" && -n "$OUT" ]] || { echo "usage: $0 start|stop <dir>"; exit 2; }
mkdir -p "$OUT"

if [[ "$ACTION" == "start" ]]; then
    # network id of the broker container (container_name: dc_mosquitto in docker-compose.yml)
    NETID=$(docker inspect dc_mosquitto -f '{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}')
    IFACE="br-${NETID:0:12}"
    ip link show "$IFACE" >/dev/null || { echo "interface $IFACE not found"; exit 1; }
    echo "$IFACE" > "$OUT/capture_iface.txt"
    echo "tcp port 1883" > "$OUT/capture_filter.txt"
    tcpdump --version 2>&1 | head -1 > "$OUT/tcpdump_version.txt"
    sudo tcpdump -i "$IFACE" -U -n -w "$OUT/capture.pcap" "tcp port 1883" 2> "$OUT/tcpdump.log" &
    sleep 1
    echo "capturing on $IFACE -> $OUT/capture.pcap"
elif [[ "$ACTION" == "stop" ]]; then
    sudo pkill -INT -f "tcpdump.*$OUT/capture.pcap" || true     # only OUR tcpdump
    sleep 2
    sudo chown "$USER" "$OUT/capture.pcap" || true
    echo "stopped: $(du -h "$OUT/capture.pcap" | cut -f1) captured"
fi
