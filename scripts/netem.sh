#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

COMPOSE_FILES=( -f docker-compose.yml -f compose.workload.yml )
COMPOSE=( docker compose "${COMPOSE_FILES[@]}" )

SERVICE_PREFIX="${SERVICE_PREFIX:-workload_}"
NETEM_IFACE="${NETEM_IFACE:-eth0}"
NETEM_DELAY="${NETEM_DELAY:-20ms}"
NETEM_JITTER="${NETEM_JITTER:-5ms}"
NETEM_LOSS="${NETEM_LOSS:-1%}"

usage() {
  cat <<USAGE
Usage: $(basename "$0") {apply|disable|status}

  apply    Apply delay/jitter/loss to every running ${SERVICE_PREFIX}* service.
  disable  Remove this script's root netem qdisc from every running ${SERVICE_PREFIX}* service.
  status   Show the qdisc on every running ${SERVICE_PREFIX}* service.

Environment overrides:
  SERVICE_PREFIX  Default: workload_
  NETEM_IFACE     Default: eth0
  NETEM_DELAY     Default: 20ms
  NETEM_JITTER    Default: 5ms
  NETEM_LOSS      Default: 1%
USAGE
}

MODE="${1:-}"
case "$MODE" in
  apply|disable|status) ;;
  *) usage; exit 2 ;;
esac

command -v docker >/dev/null 2>&1 || { echo "ERROR: docker was not found in PATH." >&2; exit 1; }

# Confirm that expected Compose configuration is available.
for file in docker-compose.yml compose.workload.yml; do
  [[ -f "$file" ]] || { echo "ERROR: expected $PROJECT_DIR/$file" >&2; exit 1; }
done

mapfile -t SERVICES < <("${COMPOSE[@]}" config --services | awk -v p="$SERVICE_PREFIX" 'index($0, p) == 1')
if ((${#SERVICES[@]} == 0)); then
  echo "ERROR: no Compose services found with prefix '$SERVICE_PREFIX'." >&2
  exit 1
fi

running=0
skipped=0
failed=0

for service in "${SERVICES[@]}"; do
  # Compose ps -q returns no ID for a service that is not currently running.
  container_id="$("${COMPOSE[@]}" ps -q "$service" 2>/dev/null || true)"
  if [[ -z "$container_id" ]]; then
    echo "SKIP  $service (not running)"
    ((skipped+=1))
    continue
  fi

  echo "---- $service ----"
  case "$MODE" in
    apply)
      if "${COMPOSE[@]}" exec -T -u 0 "$service" sh -c '
        iface="$1"; delay="$2"; jitter="$3"; loss="$4"
        command -v tc >/dev/null 2>&1 || { echo "ERROR: tc is missing; rebuild the publisher image." >&2; exit 127; }
        ip link show dev "$iface" >/dev/null 2>&1 || { echo "ERROR: interface $iface not found." >&2; exit 2; }
        exec tc qdisc replace dev "$iface" root netem delay "$delay" "$jitter" loss random "$loss"
      ' sh "$NETEM_IFACE" "$NETEM_DELAY" "$NETEM_JITTER" "$NETEM_LOSS"; then
        echo "APPLIED $service: ${NETEM_DELAY} delay, ${NETEM_JITTER} jitter, ${NETEM_LOSS} random loss on $NETEM_IFACE"
        ((running+=1))
      else
        echo "FAILED $service" >&2
        ((failed+=1))
      fi
      ;;

    disable)
      if "${COMPOSE[@]}" exec -T -u 0 "$service" sh -c '
        iface="$1"
        command -v tc >/dev/null 2>&1 || { echo "ERROR: tc is missing." >&2; exit 127; }
        ip link show dev "$iface" >/dev/null 2>&1 || { echo "ERROR: interface $iface not found." >&2; exit 2; }
        current="$(tc qdisc show dev "$iface")"
        case "$current" in
          *netem*) tc qdisc del dev "$iface" root && echo "Removed root netem qdisc from $iface" ;;
          *) echo "No netem qdisc found on $iface; leaving existing qdisc unchanged" ;;
        esac
      ' sh "$NETEM_IFACE"; then
        ((running+=1))
      else
        echo "FAILED $service" >&2
        ((failed+=1))
      fi
      ;;

    status)
      if "${COMPOSE[@]}" exec -T "$service" tc -s qdisc show dev "$NETEM_IFACE"; then
        ((running+=1))
      else
        echo "FAILED to inspect $service" >&2
        ((failed+=1))
      fi
      ;;
  esac
done

echo
echo "Summary: processed=$running skipped_not_running=$skipped failed=$failed"
((failed == 0))
