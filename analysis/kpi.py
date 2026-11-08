"""
KPIs from the bridge log.
Usage: python analysis/kpi.py logs/messages_<run>.csv [more files] [--settle 10] [--duration 120]
  --settle   seconds after the first publish that are NOT measured (connection/netem settling)
  --duration measured seconds per run (the roadmap uses 120)
  --split-gap  split a file that contains several runs where no message arrived for N seconds (0 = off)
  --last     only report the last run found in each file
  --sent     optional CSV (device_id,sent) with publisher-confirmed counts (only valid with --settle 0)
Writes <file>_kpi.csv next to each input and prints a summary.
"""
import argparse, os
import sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # find common.py wherever the script is started from
from common import loadRuns, window

parser = argparse.ArgumentParser()
parser.add_argument("files", nargs="+")
parser.add_argument("--settle", type=float, default=0.0)
parser.add_argument("--duration", type=float, default=120.0)
parser.add_argument("--split-gap", type=float, default=20.0)
parser.add_argument("--last", action="store_true")
parser.add_argument("--sent", default=None)
args = parser.parse_args()

allRows = []
for path in args.files:
    runs, outDir = loadRuns(path, args.split_gap)
    if args.last:
        runs = runs[-1:]
    rows = []
    for runId, full in runs:
        df = window(full, args.settle, args.duration)
        nReceived = len(df)
        # QoS 1 duplicates = same (device_id, seq) seen more than once. The publisher keeps ONE
        # seq counter per device (also for thermostat state messages) so this key is correct.
        uniq = df.drop_duplicates(subset=["device_id", "seq"], keep="first").copy()
        nUnique = len(uniq)
        nDup = nReceived - nUnique

        uniq["L1"] = (uniq["t_sub"] - uniq["t_pub"]) / 1e6        # device -> subscriber [ms]
        uniq["L2"] = (uniq["t_db_ack"] - uniq["t_sub"]) / 1e6     # subscriber -> DB ack [ms] (NaN for state msgs)
        uniq["E2E"] = (uniq["t_db_ack"] - uniq["t_pub"]) / 1e6    # device -> DB ack [ms]
        if (uniq["L1"] < 0).any():
            print("WARNING: negative L1 in", runId, "- clocks differ?")

        if args.sent:
            nSent = pd.read_csv(args.sent)["sent"].sum()
            note = "sender-confirmed"
        else:
            # estimate: seq range seen per device inside the window (tail losses are not visible)
            g = uniq.groupby("device_id")["seq"]
            nSent = (g.max() - g.min() + 1).sum()
            note = "estimated from seq range"
        pdr = min(100.0 * nUnique / nSent, 100.0)

        rows.append({
            "run_id": runId, "devices": uniq["device_id"].nunique(),
            "qos_seen": ",".join(str(int(q)) for q in sorted(df["qos"].dropna().unique())) if "qos" in df else "",
            "n_received": nReceived, "n_unique": nUnique, "n_duplicates": nDup,
            "n_sent": int(nSent), "sent_source": note, "pdr_percent": round(pdr, 2),
            "throughput_msg_s": round(nUnique / args.duration, 2),
            "L1_p50_ms": round(uniq["L1"].quantile(0.50), 2), "L1_p95_ms": round(uniq["L1"].quantile(0.95), 2),
            "L2_p50_ms": round(uniq["L2"].quantile(0.50), 2), "L2_p95_ms": round(uniq["L2"].quantile(0.95), 2),
            "E2E_p50_ms": round(uniq["E2E"].quantile(0.50), 2), "E2E_p95_ms": round(uniq["E2E"].quantile(0.95), 2),
        })
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(outDir, os.path.basename(path)[:-4] + "_kpi.csv"), index=False)
    allRows.extend(rows)

summary = pd.DataFrame(allRows)
pd.set_option("display.width", 220)
pd.set_option("display.max_columns", 30)
print(summary.T if len(summary) == 1 else summary)
