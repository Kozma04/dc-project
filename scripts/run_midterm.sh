#!/usr/bin/env bash
# One measured run: 10 publishers (the workload_* services), default QoS 0, steady load, seed 101,
# netem 20 ms / 5 ms / 1 % on the publisher side, 10 s settling + 120 s measured.
# Usage (from anywhere):  scripts/run_midterm.sh
# Other runs:  PUBLISH_QOS=1 LOAD_MODE=bursty RUN_SEED=202 scripts/run_midterm.sh
set -Eeuo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

export RUN_SEED=${RUN_SEED:-101}
export PUBLISH_QOS=${PUBLISH_QOS:-0}
export LOAD_MODE=${LOAD_MODE:-steady}
SETTLE=${SETTLE:-10}
DURATION=${DURATION:-120}
export RUN_ID="n10_q${PUBLISH_QOS}_${LOAD_MODE}_s${RUN_SEED}_$(date +%H%M%S)"

OUT="logs/$RUN_ID"                         # pcap + manifest of this run
CSV="logs/messages_${RUN_ID}.csv"          # written by the bridge container
COMPOSE=(docker compose -f docker-compose.yml -f compose.workload.yml -f compose.run.yml)
WORKLOADS=$("${COMPOSE[@]}" config --services | grep '^workload_')
mkdir -p "$OUT"

# manifest: what exactly was run (reproducibility)
cat > "$OUT/manifest.json" <<JSON
{"run_id":"$RUN_ID","publishers":$(echo "$WORKLOADS" | wc -l),"qos":$PUBLISH_QOS,"load":"$LOAD_MODE",
 "run_seed":$RUN_SEED,"settle_s":$SETTLE,"duration_s":$DURATION,
 "netem":"delay ${NETEM_DELAY:-20ms} ${NETEM_JITTER:-5ms} loss random ${NETEM_LOSS:-1%} (scripts/netem.sh)",
 "date":"$(date -Is)","docker":"$(docker --version)","git":"$(git rev-parse --short HEAD 2>/dev/null || echo n/a)"}
JSON

echo ">> infrastructure + bridge (new RUN_ID => bridge is recreated and opens $CSV)"
"${COMPOSE[@]}" up -d --build mosquitto influxdb grafana bridge
sleep 10

echo ">> start capture, then publishers"
scripts/capture.sh start "$OUT"
"${COMPOSE[@]}" up -d --build $WORKLOADS
sleep 3
scripts/netem.sh apply                       # device-side impairment (publisher containers only)

echo ">> measuring: ${SETTLE}s settling + ${DURATION}s"
sleep $((SETTLE + DURATION + 2))

scripts/netem.sh status > "$OUT/netem_status.txt" 2>&1 || true   # evidence that netem was active
"${COMPOSE[@]}" stop $WORKLOADS
sleep 3
scripts/capture.sh stop "$OUT"
"${COMPOSE[@]}" rm -sf $WORKLOADS            # removes containers => netem state disappears too

echo ">> analysis"
python analysis/kpi.py "$CSV" --settle "$SETTLE" --duration "$DURATION"
python analysis/plot.py "$CSV" --settle "$SETTLE" --duration "$DURATION"
python analysis/traffic.py "$CSV" || echo "(traffic.py failed - is tshark installed?)"
echo ">> results are in logs/ (messages_${RUN_ID}.csv, *_kpi.csv, *_latency_p50_p95.png, *_traffic.csv)"
