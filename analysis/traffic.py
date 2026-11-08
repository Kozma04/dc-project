"""
Traffic proxy: captured wire bytes per unique delivered message.
Usage: python analysis/traffic.py logs/messages_<run>.csv [capture.pcap]
Default pcap: logs/<run>/capture.pcap (written by scripts/capture.sh).
Counting rule (same for every run): ALL frames in the pcap (filter 'tcp port 1883' on the
docker bridge that carries the broker traffic), both directions, incl. Ethernet/IP/TCP headers and ACKs.
  wire_bytes_per_msg    = sum(frame.len) / unique delivered messages of the WHOLE run (no settle cut)
  payload_bytes_per_msg = sum(tcp.len)   / unique delivered messages
Writes logs/<run>_traffic.csv
"""
import os, subprocess, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # find common.py wherever the script is started from
from common import loadRuns

path = sys.argv[1]
runs, outDir = loadRuns(path, 0)          # split-gap 0: one log file = one run
runId, df = runs[0]
pcap = sys.argv[2] if len(sys.argv) > 2 else os.path.join(outDir, runId, "capture.pcap")

out = subprocess.run(["tshark", "-r", pcap, "-T", "fields", "-e", "frame.len", "-e", "tcp.len"],
                     capture_output=True, text=True, check=True).stdout
wireBytes, payloadBytes, packets = 0, 0, 0
for line in out.splitlines():
    cols = line.split("\t")
    wireBytes += int(cols[0])
    payloadBytes += int(cols[1]) if len(cols) > 1 and cols[1] else 0
    packets += 1

nUnique = len(df.drop_duplicates(subset=["device_id", "seq"]))
res = {"run_id": runId, "packets": packets, "wire_bytes": wireBytes, "payload_bytes": payloadBytes,
       "unique_msgs": nUnique,
       "wire_bytes_per_msg": round(wireBytes / nUnique, 1),
       "payload_bytes_per_msg": round(payloadBytes / nUnique, 1)}
pd.DataFrame([res]).to_csv(os.path.join(outDir, runId + "_traffic.csv"), index=False)
print(pd.Series(res))
