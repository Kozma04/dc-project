"""Shared helpers for kpi.py / plot.py / traffic.py."""
import os, sys
import pandas as pd

# accepted column names -> standard name
ALIASES = {
    "device_id": ["device_id", "deviceid", "device"],
    "seq": ["seq", "sequence"],
    "t_pub": ["t_pub", "tpub"],
    "t_sub": ["t_sub", "tsub"],
    "t_db_ack": ["t_db_ack", "tdback", "t_db", "t_ack"],
}


def loadRuns(path, splitGap=20.0):
    """Read a bridge log (logs/messages_<run>.csv, or a folder containing one).
    If the file mixes several runs (old logs/messages.csv), split it wherever no message
    arrived for more than splitGap seconds (0 = do not split).
    Returns ([(runId, dataframe), ...], outDir)."""
    if os.path.isdir(path):
        files = sorted(f for f in os.listdir(path) if f.startswith("messages") and f.endswith(".csv"))
        if not files:
            sys.exit("ERROR: no messages*.csv in " + path)
        path = os.path.join(path, files[-1])
    outDir = os.path.dirname(os.path.abspath(path))
    stem = os.path.basename(path)[:-4]
    baseId = stem[len("messages_"):] if stem.startswith("messages_") else stem

    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    df = df.loc[:, ~df.columns.duplicated()]
    rename = {}
    for std, names in ALIASES.items():
        for n in names:
            if n in df.columns:
                rename[n] = std
                break
    df = df.rename(columns=rename)
    missing = [c for c in ["device_id", "seq", "t_pub", "t_sub"] if c not in df.columns]
    if missing:
        sys.exit("ERROR: " + path + " is missing columns " + str(missing) +
                 "\nFound: " + str(list(df.columns)) + "\nAdd names to ALIASES in common.py")
    if "t_db_ack" not in df.columns:
        df["t_db_ack"] = float("nan")
    for c in ["seq", "t_pub", "t_sub", "t_db_ack"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["seq", "t_pub", "t_sub"]).sort_values("t_sub").reset_index(drop=True)

    if splitGap and splitGap > 0 and len(df) > 0:
        part = (df["t_sub"].diff() > splitGap * 1e9).cumsum()
    else:
        part = pd.Series(0, index=df.index)
    runs = []
    nParts = part.max() + 1 if len(df) else 0
    for k in range(nParts):
        runId = baseId if nParts == 1 else baseId + "_r" + str(k + 1)
        runs.append((runId, df[part == k].copy()))
    return runs, outDir


def window(df, settle=0.0, duration=None):
    """Keep messages published between t0+settle and t0+settle+duration (t0 = first publish)."""
    t0 = df["t_pub"].min()
    start = t0 + settle * 1e9
    out = df[df["t_pub"] >= start]
    if duration:
        out = out[out["t_pub"] < start + duration * 1e9]
    return out.copy()
