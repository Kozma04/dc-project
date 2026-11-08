# Smart-Home Energy Monitoring over MQTT: QoS, Latency Budget and TLS Cost

Group project (Distributed Computing). Authors: Costin-Cosmin Dumitru, Delia Ana-Maria Neagu, Dana-Teodora Orfescu.

This README describes the whole setup from a clean Linux Mint machine to a finished measured run: what to install, in which order, what to run, and where to find every result.

## 1. What the project does

Simulated smart-home devices publish telemetry over MQTT. A bridge forwards it into a time-series database, and a dashboard shows it live. The experiments measure how the number of publishers, the MQTT QoS and bursty load affect latency, delivery and throughput, and later what TLS costs.

Data path:

```
Python/paho-mqtt publishers (Docker)  ->  Eclipse Mosquitto  ->  Python bridge  ->  InfluxDB 2.x  ->  Grafana
        (power / thermostat / ambient)         (broker)        (subscriber +        (bucket           (dashboards)
                                                                per-message CSV)     "energy")
```

* Topic pattern: `home/<room>/<device>/<metric>`
* Payload: JSON with `device_id`, `seq`, `t_pub` (nanoseconds since Unix epoch) and `value`
* Stored measurements: `power`, `temperature`, `humidity`, tagged with `device_id` and `room`, numeric field `value`
* Network impairment (20 ms delay, 5 ms jitter, 1 % loss) is applied on the publisher side only. The path broker to InfluxDB is not impaired.
* All timestamps come from the host clock (publishers, bridge and broker run on the same machine).

## 2. Repository layout

```
dc-project/
├── docker-compose.yml        infrastructure: mosquitto, influxdb, grafana, bridge (+ 3 demo publishers)
├── compose.workload.yml      the 10 workload publishers (workload_*): 4 power, 3 thermostat, 3 ambient
├── compose.run.yml           gives the bridge a RUN_ID (one CSV per run)
├── .env                      INFLUXDB_TOKEN (not in git, you create it)
├── bridge/                   bridge.py + Dockerfile: MQTT -> InfluxDB + per-message CSV log
├── publishers/               publisher.py + Dockerfile (paho-mqtt, iproute2 for tc)
├── mosquitto/                mosquitto.conf
├── scripts/
│   ├── netem.sh              apply | status | disable  network impairment on the publisher containers
│   ├── capture.sh            start | stop  tcpdump on the docker bridge
│   └── run_midterm.sh        one complete measured run + analysis
├── analysis/                 common.py, kpi.py, plot.py, traffic.py, requirements.txt
├── logs/                     all run outputs (see section 8)
├── start.sh                  starts the demo stack and prints live MQTT messages
├── start_experiment.sh       starts infrastructure + all workload_* publishers
├── activate_conda_env.sh     conda activate dc_project
└── screenshots/
```

## 3. Install, in this order

Everything below is for Linux Mint (Ubuntu based). Run it in a terminal.

### 3.1 System packages

```bash
sudo apt update
sudo apt install -y git wget curl ca-certificates unzip \
  tcpdump tshark iproute2
```

When the installer asks "Should non-superusers be able to capture packets?" answer Yes.

### 3.2 Docker and Docker Compose

```bash
sudo apt install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
```

If `docker-compose-v2` is not found (older Mint 21), install Docker from the official repository instead: https://docs.docker.com/engine/install/ubuntu/ (use the Ubuntu codename from `/etc/os-release`, not the Mint codename) and install `docker-ce` plus `docker-compose-plugin`.

### 3.3 Let your user run Docker without sudo

```bash
sudo usermod -aG docker $USER
newgrp docker          # applies it to this terminal; a full logout/login applies it everywhere
docker ps              # must work without an error (an empty table is fine)
docker compose version
```

### 3.4 Anaconda

```bash
cd ~/Downloads
wget https://repo.anaconda.com/archive/Anaconda3-2024.10-1-Linux-x86_64.sh
bash Anaconda3-2024.10-1-Linux-x86_64.sh
```

Press Enter to scroll the license, type `yes`, accept the default location, and answer `yes` to "initialize conda". Close the terminal and open a new one, then check `conda --version`. If conda is not found: `~/anaconda3/bin/conda init bash && source ~/.bashrc`.

Optional: `conda config --set auto_activate_base false`.

### 3.5 Get the code

```bash
mkdir -p ~/Desktop/Dc_project && cd ~/Desktop/Dc_project
git clone https://github.com/Kozma04/dc-project.git
cd dc-project
chmod 755 scripts/*.sh start.sh start_experiment.sh
```

To update later: `git pull` (if you have local changes, `git stash` first, then `git stash pop`).

### 3.6 Python environment (for the analysis scripts only)

The publishers and the bridge run inside Docker and install their own Python packages. On the host you only need pandas, numpy and matplotlib for the analysis.

```bash
conda create -n dc_project python=3.12 -y
conda activate dc_project
pip install -r analysis/requirements.txt
python -c "import pandas, matplotlib; print('ok')"
```

Use `source activate_conda_env.sh` (or `conda activate dc_project`) in every new terminal before running the analysis or `scripts/run_midterm.sh`. The prompt must start with `(dc_project)`.

## 4. Configuration: the .env file

`docker-compose.yml` starts InfluxDB with a fixed admin token (`DOCKER_INFLUXDB_INIT_ADMIN_TOKEN`), organization `dc_project` and bucket `energy`. The bridge reads the token from an `.env` file in the repo root, so `.env` has to contain exactly the same value.

Create it without typing or showing the token:

```bash
cd ~/Desktop/Dc_project/dc-project
TOKEN=$(grep 'DOCKER_INFLUXDB_INIT_ADMIN_TOKEN' docker-compose.yml | head -1 | sed 's/.*ADMIN_TOKEN:[[:space:]]*//' | tr -d '"\r ')
echo "INFLUXDB_TOKEN=$TOKEN" > .env
grep -c INFLUXDB_TOKEN .env          # must print 1
```

Rules:

* Never commit `.env` to git.
* InfluxDB applies the token only when its data volume is created for the first time. If it was started before with another token, reset it once: `docker compose down -v` (this deletes the InfluxDB and Grafana data).
* Do not paste tokens or passwords into chats or tickets. The compose file contains development credentials (InfluxDB and Grafana users); treat the repository as internal.

## 5. Pre-flight check

Run this before every session, from the repo root, with `(dc_project)` active:

```bash
docker ps                                                  # no permission error
python -c "import pandas, matplotlib; print('ok')"
which tcpdump tshark                                       # both print a path
ls scripts/run_midterm.sh scripts/capture.sh scripts/netem.sh compose.run.yml
grep -c INFLUXDB_TOKEN .env                                # prints 1
```

## 6. Running things

### 6.1 Quick look: the demo stack

```bash
docker compose up -d --build
docker compose ps                         # all services "running"
docker compose logs bridge --tail 20      # "Bridge subscribed to home/#"
docker exec -it dc_mosquitto mosquitto_sub -h localhost -p 1883 -t 'home/#' -v     # live MQTT messages, Ctrl+C to leave
docker compose down                       # stop (add -v to also delete the data volumes)
```

This starts the infrastructure and the three demo publishers (`publisher_power`, `publisher_thermostat`, `publisher_ambient`).

### 6.2 The measured run (midterm: 10 devices, QoS 0, steady load, seed 101)

```bash
conda activate dc_project
cd ~/Desktop/Dc_project/dc-project
scripts/run_midterm.sh
```

If the shell says "Permission denied", use `bash scripts/run_midterm.sh` or `chmod 755 scripts/*.sh`.

What the script does:

1. Creates a `RUN_ID` such as `n10_q0_steady_s101_163045` and writes `logs/<RUN_ID>/manifest.json`.
2. Starts Mosquitto, InfluxDB, Grafana and the bridge. The bridge is recreated with the new `RUN_ID` and opens `logs/messages_<RUN_ID>.csv`.
3. Starts `tcpdump` on the Docker bridge (asks for the sudo password once).
4. Starts the 10 `workload_*` publishers and applies netem (20 ms, 5 ms jitter, 1 % loss) to them.
5. Waits 10 s settling plus 120 s measured traffic.
6. Saves the netem status, stops the publishers and the capture, and removes the publisher containers.
7. Computes KPIs, the latency plot and the traffic statistics.

It takes about 2.5 minutes, plus a few minutes for the first Docker build. The script ends by itself. Mosquitto, InfluxDB, Grafana and the bridge keep running afterwards (so Grafana stays available for the demo). Stop them with:

```bash
docker compose -f docker-compose.yml -f compose.workload.yml -f compose.run.yml down
```

Other runs use environment variables:

```bash
PUBLISH_QOS=1 scripts/run_midterm.sh                         # QoS 1
LOAD_MODE=bursty scripts/run_midterm.sh                      # 5x rate for 10 s every 60 s
RUN_SEED=202 scripts/run_midterm.sh                          # another seed
SETTLE=10 DURATION=120 scripts/run_midterm.sh                # defaults
```

Each run gets its own `RUN_ID`, so nothing is overwritten.

### 6.3 Running the pieces separately

Start publishers by hand (infrastructure + all workload publishers):

```bash
./start_experiment.sh
```

Network impairment on the running publisher containers:

```bash
scripts/netem.sh apply        # 20 ms delay, 5 ms jitter, 1 % random loss on eth0
scripts/netem.sh status
scripts/netem.sh disable
# overrides: NETEM_DELAY=50ms NETEM_JITTER=10ms NETEM_LOSS=2% scripts/netem.sh apply
```

Packet capture around a run:

```bash
scripts/capture.sh start logs/test1       # before the publishers start
scripts/capture.sh stop  logs/test1       # after they stopped
```

Analysis of any bridge log (also the old shared `logs/messages.csv`, where runs are split automatically wherever no message arrived for 20 s):

```bash
python analysis/kpi.py     logs/messages_<RUN_ID>.csv --settle 10 --duration 120
python analysis/plot.py    logs/messages_<RUN_ID>.csv --settle 10 --duration 120
python analysis/traffic.py logs/messages_<RUN_ID>.csv            # reads logs/<RUN_ID>/capture.pcap
python analysis/kpi.py logs/messages.csv --last                  # newest run of the old shared file
```

## 7. Where to see what

| What | Where |
|---|---|
| Live dashboard | Grafana, http://localhost:3000 (login: see `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD` in `docker-compose.yml`) |
| Raw time series | InfluxDB UI, http://localhost:8086 (org `dc_project`, bucket `energy`, measurements `power`, `temperature`, `humidity`) |
| Live MQTT messages | `docker exec -it dc_mosquitto mosquitto_sub -h localhost -p 1883 -t 'home/#' -v` |
| Bridge activity | `docker compose logs -f bridge` (prints device, seq, metric and L1 per message) |
| Publisher activity | `docker compose logs <service>` e.g. `workload_power_meter_01` (set `LOG_EACH_PUBLISH=true` for one line per message) |
| Run results | the `logs/` folder (section 8) |

The services listen on `127.0.0.1` only, so the web UIs are reachable from the same machine.

The Grafana data source and the dashboard panels are owned by the infrastructure part of the project. If a panel is empty, check the data source settings first (the roadmap panel uses an InfluxQL query on `power`).

## 8. Output files (all in `logs/`)

`<RUN_ID>` looks like `n10_q0_steady_s101_163045`.

| File | Content |
|---|---|
| `messages_<RUN_ID>.csv` | one row per received message: `device_id, seq, t_pub, t_sub, t_db_ack, topic, qos, value, mqtt_dup, run_id` (timestamps in ns) |
| `messages_<RUN_ID>_kpi.csv` | latency L1, L2, end-to-end (p50, p95), PDR, throughput, duplicates |
| `<RUN_ID>_latency_p50_p95.png` | p50/p95 latency over time (10 s windows) |
| `<RUN_ID>_traffic.csv` | wire bytes and payload bytes per unique delivered message |
| `<RUN_ID>/manifest.json` | run configuration: QoS, load, seed, netem, date, software versions, git commit |
| `<RUN_ID>/capture.pcap` | packet capture (open with Wireshark or tshark) |
| `<RUN_ID>/capture_iface.txt`, `capture_filter.txt`, `tcpdump_version.txt`, `tcpdump.log` | how the capture was done |
| `<RUN_ID>/netem_status.txt` | proof that netem was active during the run |

Keep the raw logs and manifests of every run you report. The old `logs/messages.csv` (shared file from earlier runs) is no longer written.

## 9. How the numbers are defined

* L1 = (t_sub - t_pub) / 1e6 ms: publisher to subscriber (bridge).
* L2 = (t_db_ack - t_sub) / 1e6 ms: bridge receive to acknowledged InfluxDB write. `t_db_ack` is taken after a synchronous write returns, so it is a real database acknowledgement. Thermostat state messages are not written to InfluxDB, so their `t_db_ack` is empty.
* End-to-end = (t_db_ack - t_pub) / 1e6 ms.
* p50 and p95 are computed from the per-message records. Grafana refresh time is not a latency metric.
* PDR = 100 x unique received sequence IDs / published sequence IDs. Duplicates (same `device_id` and `seq`) are counted separately and never raise PDR above 100 %. The publishers keep one sequence counter per device, also for thermostat state messages.
* Throughput = unique messages per second at the subscriber.
* Traffic proxy = captured bytes per unique delivered message, from `tcpdump` on the Docker bridge with the filter `tcp port 1883`, both directions, including headers and ACKs, same rule for all runs.

Limits to state in the report:

* "Published" is estimated from the sequence range seen per device inside the measured window, because the publishers do not write a sent counter. Messages lost at the very end of a run are invisible. For a sender-confirmed number, collect counts from publisher logs (`LOG_EACH_PUBLISH=true`) and pass `--sent sent.csv` (columns `device_id,sent`) together with `--settle 0`.
* Wire bytes are counted on the Docker bridge, after netem already dropped packets on the publisher side.

## 10. Experiment plan

Reduced core matrix: 3 publisher scales (10, 50, 100) x 2 QoS (0, 1) x 2 loads (steady, bursty) = 12 combinations, 3 repetitions each (seeds 101, 202, 303) = 36 runs of 120 s. Run order is randomized with the fixed order seed 909.

* Device mix: 40 % power / 30 % thermostat / 30 % ambient (10: 4/3/3, 50: 20/15/15, 100: 40/30/30).
* Power: 1 Hz, 250 B JSON. Thermostat: 0.5 Hz plus state-change messages. Ambient: 0.5 Hz, 100 B JSON.
* Bursty: each device reports at 5x its base rate for 10 s every 60 s.
* Publisher PRNG seed = run seed + numeric device index. Subscriber subscribes at QoS 1.
* TLS follow-up (after the core matrix): scales 50 and 100, QoS 1, steady load, TLS off and on, 3 seeds each (12 runs). Compare p50/p95, bytes per delivered message and broker CPU.

Currently implemented in the repo: the 10-publisher workload (`compose.workload.yml`), QoS and load mode through `PUBLISH_QOS` and `LOAD_MODE`, seeds through `RUN_SEED`, netem, the measured-run script and the analysis. Still to do: 50 and 100 publisher workloads, the run matrix runner with randomized order, broker CPU observations, the TLS comparison and the full dashboard set.

## 11. Midterm checklist

The midterm needs: the P0 to P2 pipeline at 10 devices with QoS 0, reproducible CSV-based KPIs, and one p50/p95 end-to-end latency plot.

* [ ] `docker compose down -v` and a fresh start work without manual steps (repeatability from a clean start)
* [ ] `scripts/run_midterm.sh` completes
* [ ] `logs/messages_<RUN_ID>_kpi.csv` exists; sanity check: `n_duplicates` is 0 at QoS 0, `pdr_percent` is around 99 (1 % loss), `L1_p50_ms` is around 20 to 30 ms (20 ms netem delay)
* [ ] `logs/<RUN_ID>_latency_p50_p95.png` exists
* [ ] `logs/<RUN_ID>/manifest.json` and `netem_status.txt` are kept as evidence
* [ ] Grafana shows the live feed during the demo
* [ ] Changes are pushed to GitHub (never `.env`)

## 12. Troubleshooting

| Symptom | Fix |
|---|---|
| `permission denied` for `docker` / `docker.sock` | `sudo usermod -aG docker $USER && newgrp docker`; log out and in if it persists; `sudo systemctl enable --now docker` |
| `Permission denied` when running a script | `chmod 755 scripts/*.sh` or run with `bash scripts/run_midterm.sh`. Do not use `chmod =X` (it removes read/write) |
| `conda: command not found` | `~/anaconda3/bin/conda init bash && source ~/.bashrc`, then open a new terminal |
| "INFLUXDB_TOKEN is not set" or the bridge cannot authenticate | `.env` is missing or does not match `DOCKER_INFLUXDB_INIT_ADMIN_TOKEN`; fix `.env`, then `docker compose down -v` and start again |
| `docker compose logs bridge` shows "Influx write failed" | check the token, org (`dc_project`), bucket (`energy`) and that the `influxdb` container is running |
| `tc` / netem errors | rebuild the publisher image (`docker compose -f docker-compose.yml -f compose.workload.yml build`), the workload services need `NET_ADMIN` (already set) |
| Capture interface not found | the script looks up the network of the `dc_mosquitto` container; start the stack before capturing; check `docker network ls` |
| `tshark` not found at the end of the run | `sudo apt install -y tshark`; KPIs and plot are still valid, only `traffic.csv` is missing |
| `L1` negative warning in the KPI script | publisher and bridge clocks differ; all containers must run on the same host |
| Stuck run (Ctrl+C) | `docker compose -f docker-compose.yml -f compose.workload.yml -f compose.run.yml down` and `sudo pkill tcpdump` |
| Files in `logs/` owned by root | `sudo chown -R $USER:$USER logs` (happens if the stack was started with `sudo`) |

## 13. Team responsibilities

* Costin-Cosmin Dumitru: infrastructure and observability (Docker Compose, Mosquitto, InfluxDB buckets and tags, Grafana data source and dashboards, deployment instructions, clean-start repeatability).
* Delia Ana-Maria Neagu: workload and network (sensor mix and rates, 10/50/100 publishers, QoS and load modes, seeds, `tc netem`, TLS comparison, broker CPU).
* Dana-Teodora Orfescu: instrumentation and analysis (bridge and CSV log, KPI calculation and duplicate handling, `tcpdump`/`tshark` capture, plots, report integration).
* Shared: run manifest and data schema, reviewing each other's results, preserving raw logs and configuration, validating the final demo.
