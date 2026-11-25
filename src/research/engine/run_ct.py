"""CT runner, one pair (PRACTICE YEARS ONLY, exam sealed).

Loads data/processed/{pair}_m15.parquet closed by PRACTICE_END, replays
CTEngine bar by bar, simulates on M15 and checks decision stability with cut re-runs.
Writes data/phase4_ct/{pair}_trades.csv, _funnel.json, _lookahead.json.

Usage: PAIR=eurusd python -m src.research.engine.run_ct
"""
import json
import hashlib
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.research.engine import ct_engine as ct
from src.research.engine import simulate_orders as so
from src.research.lookahead_guard import DataFeed, DecisionLog

ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_DIR = ROOT / "data" / "phase4_ct"
TF_M15 = pd.Timedelta(minutes=15)
NY = "America/New_York"
PRACTICE_START = pd.Timestamp("2016-01-03", tz="UTC")
PRACTICE_END = pd.Timestamp("2022-07-01", tz="UTC")


def pip_size(pair):
    return 0.01 if "jpy" in str(pair).lower() else 0.0001


def set_pair_settings(pair):
    ct.SETTINGS["pip"] = pip_size(pair)
    ct.SETTINGS["spread"] = float(config.SPREAD_PRICE[pair])


def drop_weekend(df):
    loc = df["timestamp"].dt.tz_convert(NY)
    dow = loc.dt.dayofweek
    hr = loc.dt.hour
    outside = (dow == 5) | ((dow == 6) & (hr < 17)) | ((dow == 4) & (hr >= 17))
    n = int(outside.sum())
    return df[~outside].reset_index(drop=True), n


def load_m15(pair, cutoff=PRACTICE_END):
    cutoff = pd.Timestamp(cutoff)
    if cutoff.tzinfo is None or cutoff > PRACTICE_END or cutoff <= PRACTICE_START:
        raise ValueError("cutoff must be inside the UTC practice window")
    # Push the practice-only predicate to Parquet; do not load exam observations.
    df = pd.read_parquet(
        PROCESSED_DIR / f"{pair}_m15.parquet",
        columns=["timestamp", "open", "high", "low", "close"],
        filters=[("timestamp", ">=", PRACTICE_START),
                 ("timestamp", "<=", cutoff - TF_M15)],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    df, dropped = drop_weekend(df)
    df["timestamp"] = df["timestamp"].astype("datetime64[ns, UTC]")
    df.attrs["dropped_weekend"] = dropped
    return df


def data_hash(m15):
    """Fingerprint the actual filtered OHLC inputs used for the comparison."""
    columns = ['timestamp', 'open', 'high', 'low', 'close']
    values = pd.util.hash_pandas_object(m15[columns], index=False).values
    return hashlib.sha256(values.tobytes()).hexdigest()


def run_engine(m15):
    ts = pd.to_datetime(m15["timestamp"], utc=True)
    if len(ts) and (ts.min() < PRACTICE_START or (ts.max() + TF_M15) > PRACTICE_END):
        raise ValueError("CT only accepts bars closed inside the practice window")
    # Restore globals after construction/replay; other systems remain unchanged.
    keys = ("MAJOR_HTF", "LTF_TF", "BIAS_TIMEFRAMES")
    saved = {k: (hasattr(config, k), getattr(config, k, None)) for k in keys}
    try:
        config.MAJOR_HTF = False
        config.LTF_TF = "H1"
        config.BIAS_TIMEFRAMES = "both"
        log = DecisionLog()
        rec = ct.CTEngine(log, first_read=3)
        DataFeed(m15, htf=("H1", "H4", "D1")).run(rec)
        return rec, log
    finally:
        for k, (existed, value) in saved.items():
            if existed:
                setattr(config, k, value)
            else:
                delattr(config, k)


def lookahead_check(m15, full_log, k):
    n = len(m15)
    if k <= 0:
        return {"cuts": 0, "pass": False, "decisions": 0, "bad": ["not run"]}
    fracs = [0.5] if k == 1 else [float(x) for x in np.linspace(0.1, 0.9, k)]
    bad, checked = [], 0
    for frac in fracs:
        m = max(int(n * frac), 100)
        part = m15.iloc[:m].reset_index(drop=True)
        cut = part["timestamp"].iloc[-1] + TF_M15
        _, log = run_engine(part)
        a = [d.key() for d in full_log.items if d.time <= cut]
        b = [d.key() for d in log.items]
        checked += len(b)
        if a != b:
            first = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y),
                         min(len(a), len(b)))
            bad.append({"frac": frac, "cut": str(cut), "full_n": len(a),
                        "cut_n": len(b), "first_diff": first})
        print(f"  lookahead cut {frac:.2f}: {'ok' if a == b else 'MISMATCH'} "
              f"({len(b)} decisions)", flush=True)
    return {"cuts": len(fracs), "pass": not bad, "decisions": checked, "bad": bad}


def run_pair(pair):
    t0 = time.time()
    set_pair_settings(pair)
    print(f"[{pair}] CT continuation: H1 LTF, D1+H4 agree (first read 3), "
          f"with-trend OB + HTF zone, stop far edge +0.3 ATR, "
          f"static and liquidity alternatives (simulator)", flush=True)
    cutoff = PRACTICE_END
    m15 = load_m15(pair, cutoff)
    dropped = int(m15.attrs.get("dropped_weekend", 0))
    print(f"[{pair}] m15 bars: {len(m15)} first {m15['timestamp'].iloc[0]} "
          f"last close {m15['timestamp'].iloc[-1] + TF_M15} dropped {dropped}",
          flush=True)
    if m15.empty:
        raise ValueError("No practice bars found for " + pair)
    rec, log = run_engine(m15)
    orders = list(rec.ctorders)
    print(f"[{pair}] done in {time.time()-t0:.0f}s: {len(log.items)} decisions, "
          f"{len(orders)} CT orders, {len(rec.flips)} bias flips", flush=True)
    recs = so.simulate_all(orders, m15, pair)
    groups = {}
    for r in recs:
        groups.setdefault((r["leg"], r["target_mode"]), []).append(r)
    for g in groups.values():
        so.tag_trades(g, rec.flips)
    df = pd.DataFrame(recs, columns=so.TRADE_COLS)
    k = int(os.environ.get("LOOKAHEAD_CUTS", "10"))
    look = lookahead_check(m15, log, k)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / f"{pair}_trades.csv", index=False)
    statuses = df["status"].value_counts().to_dict() if len(df) else {}
    funnel = {"counts": {k_: int(v) for k_, v in rec.counts.items()},
              "orders": len(orders), "statuses": statuses,
              "flips": len(rec.flips), "decisions": len(log.items),
              "bars": len(m15), "data_hash": data_hash(m15), "first_bar": str(m15["timestamp"].iloc[0]),
              "last_close": str(m15["timestamp"].iloc[-1] + TF_M15),
              "dropped_weekend_bars": dropped,
              "variant": "ct", "ltf": "H1", "major_htf": False}
    (OUT_DIR / f"{pair}_funnel.json").write_text(
        json.dumps(funnel, indent=1, default=str))
    (OUT_DIR / f"{pair}_lookahead.json").write_text(
        json.dumps(look, indent=1, default=str))
    done = ["target", "stop", "stop_gap"]
    res = df[df["outcome"].isin(done)] if len(df) else df

    def card(mode):
        t = res[res["target_mode"] == mode] if len(res) else res
        return (f"{len(t)} trades, net R "
                f"{t['net_r'].astype(float).sum():.2f}" if len(t) else "0 trades")

    lines = [
        f"### CT run: {pair}",
        f"- Bars: {len(m15)} to {config.PRACTICE_END}; orders {len(orders)} "
        f"| Status: {statuses}",
        f"- Resolved static: {card('static')}; liquidity: {card('liquidity')}",
        f"- open_at_cutoff {int((df['outcome'] == 'open_at_cutoff').sum()) if len(df) else 0}",
        f"- Lookahead: {'PASS' if look['pass'] else 'FAIL'} "
        f"({look['cuts']} cuts, {look['decisions']} decisions)",
        f"- Run time: {time.time()-t0:.0f}s\n",
    ]
    summary = "\n".join(lines)
    print("\n" + summary, flush=True)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a") as f:
            f.write(summary + "\n")
    return df


if __name__ == "__main__":
    run_pair(os.environ.get("PAIR", "eurusd"))
