"""
p50/p95 latency plot (10 s windows).
Usage: python analysis/plot.py logs/messages_<run>.csv [--settle 10] [--duration 120] [--run -1]
Saves logs/<run>_latency_p50_p95.png
"""
import argparse, os
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # find common.py wherever the script is started from
from common import loadRuns, window

parser = argparse.ArgumentParser()
parser.add_argument("file")
parser.add_argument("--settle", type=float, default=0.0)
parser.add_argument("--duration", type=float, default=120.0)
parser.add_argument("--split-gap", type=float, default=20.0)
parser.add_argument("--run", type=int, default=-1, help="which run of a multi-run file (default: last)")
args = parser.parse_args()

runs, outDir = loadRuns(args.file, args.split_gap)
runId, full = runs[args.run]
df = window(full, args.settle, args.duration)
df = df.drop_duplicates(subset=["device_id", "seq"])

df["L1"] = (df["t_sub"] - df["t_pub"]) / 1e6                 # device -> subscriber [ms]
df["E2E"] = (df["t_db_ack"] - df["t_pub"]) / 1e6             # device -> DB ack [ms]
df["tSec"] = (df["t_pub"] - df["t_pub"].min()) / 1e9 + args.settle
df["win"] = (df["tSec"] // 10) * 10

g = df.groupby("win")
plt.figure(figsize=(9, 5))
plt.plot(g["E2E"].quantile(0.5), "o-", label="end-to-end p50 (device -> DB ack)")
plt.plot(g["E2E"].quantile(0.95), "o--", label="end-to-end p95")
plt.plot(g["L1"].quantile(0.5), "s-", alpha=0.5, label="L1 p50 (device -> subscriber)")
plt.plot(g["L1"].quantile(0.95), "s--", alpha=0.5, label="L1 p95")
plt.xlabel("time since first publish [s] (10 s windows)")
plt.ylabel("latency [ms]")
plt.title("Latency p50 / p95 - " + runId)
plt.grid(alpha=0.3)
plt.legend()
plt.tight_layout()
out = os.path.join(outDir, runId + "_latency_p50_p95.png")
plt.savefig(out, dpi=150)
print("saved", out)
