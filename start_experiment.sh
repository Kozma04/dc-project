WORKLOAD_SERVICES=$(
  docker compose \
    -f docker-compose.yml \
    -f compose.workload.yml \
    config --services | grep '^workload_'
)

docker compose \
  -f docker-compose.yml \
  -f compose.workload.yml \
  up -d --build --remove-orphans \
  mosquitto influxdb grafana bridge $WORKLOAD_SERVICES