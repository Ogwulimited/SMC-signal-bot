"""Phase 4 cycle runner, one pair (PRACTICE YEARS ONLY).

Loads data/processed/{pair}_m15.parquet (bars fully closed by PRACTICE_END; the
feed builds H1/H4/D1 from M15), replays the cycle bar by bar, simulates the
orders (on M15 bars), then proves no lookahead by re-running on cut-off data
and comparing decisions. Writes data/phase4_cycle/{pair}_trades.csv,
_funnel.json, _lookahead.json, _pullbacks.csv.

Bad days are NOT excluded in this run.
Bars outside the trading week (New York clock: Saturday, Sunday before 17:00,
Friday from 17:00) are dropped at load time. This uses only each bar's own
timestamp. The count is reported.

Variants (env VARIANT, default v1 = as first built):
  v1: first read 5 counted swings, D1 and H4 must agree, breaker + OB orders
  v2: first read 3 counted swings, D1 and H4 must agree
  v3: first read 3 counted swings, H4 alone decides the bias
  v4: as v1, but only OB entries are simulated (pullbacks)
  zt: as v1 (pullbacks, breaker + OB) PLUS zone trades (with the trend):
      breaker and OB entries, each played with a static 1:3 target and a
      liquidity target. Zone and pullback trades are separate scorecards.
  mz: REBUILD from his chart rules (not a tuning version):
      Major swings for H4/D1 (N=8, config MAJOR_*), bias first read 3 counted
      Major swings, plus zone trades with used-zone rule B and the 150-pip
      cancel of pending zone orders. Trading timeframe M15.
  mh: RULE CHANGE (his request, after seeing mz): same as mz but the trading
      timeframe is H1 (BOS, CHoCH, breaker, OB, inducement and ceiling come
      from H1 bars; HTF stays D1 + H4). Orders are still played on M15 bars.
The lookahead re-runs use the same variant.

Pullback trades are always counter-trend: sells in a bull HTF bias, buys in a
bear HTF bias. Zone trades go with the trend: buys in a bull bias, sells in a
bear bias.

Pip size for the cancel rule: 0.01 for JPY pairs, 0.0001 otherwise.

Usage (repo root):  PAIR=eurusd VARIANT=mh python -m src.research.engine.run_cycle
"""
import json
import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.research.engine import simulate_orders as so
from src.research.engine import zone as zn
from src.research.engine.bias import htf_bias
from src.research.lookahead_guard import DataFeed, DecisionLog

ROOT = Path(__file__).resolve().parents[3]
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_DIR = ROOT / "data" / "phase4_cycle"
TF_M15 = pd.Timedelta(minutes=15)
NY = "America/New_York"

BOTH = ("breaker", "ob")

# first_read None = use config.BIAS_FIRST_READ_SWINGS (5), or the Major value
# (MAJOR_BIAS_FIRST_READ) when major is on (the mapper decides).
# ltf = trading timeframe (config.LTF_TF): "M15" for every old variant.
VARIANTS = {
    "v1": {"first_read": None, "bias_tfs": "both", "kinds": BOTH, "zone": False,
           "major": False, "rules": False, "ltf": "M15",
           "text": "first read 5 swings (config default), D1 and H4 must agree, breaker + OB"},
    "v2": {"first_read": 3, "bias_tfs": "both", "kinds": BOTH, "zone": False,
           "major": False, "rules": False, "ltf": "M15",
           "text": "first read 3 swings, D1 and H4 must agree, breaker + OB"},
    "v3": {"first_read": 3, "bias_tfs": "h4", "kinds": BOTH, "zone": False,
           "major": False, "rules": False, "ltf": "M15",
           "text": "first read 3 swings, H4 alone decides the bias, breaker + OB"},
    "v4": {"first_read": None, "bias_tfs": "both", "kinds": ("ob",), "zone": False,
           "major": False, "rules": False, "ltf": "M15",
           "text": "as v1 (5 swings, D1 and H4 agree) but OB entries only, breaker orders dropped"},
    "zt": {"first_read": None, "bias_tfs": "both", "kinds": BOTH, "zone": True,
           "major": False, "rules": False, "ltf": "M15",
           "text": "as v1 (5 swings, D1 and H4 agree) plus zone trades (with the trend), "
                   "breaker + OB, static and liquidity targets"},
    "mz": {"first_read": None, "bias_tfs": "both", "kinds": BOTH, "zone": True,
           "major": True, "rules": True, "ltf": "M15",
           "text": "REBUILD: Major swings H4/D1 (N=8), first read 3 Major swings, D1 and H4 "
                   "agree, pullbacks + zone trades, used-zone rule B (spent on real fill), "
                   "150-pip cancel of pending zone orders, trading timeframe M15"},
    "mh": {"first_read": None, "bias_tfs": "both", "kinds": BOTH, "zone": True,
           "major": True, "rules": True, "ltf": "H1",
           "text": "RULE CHANGE: as mz but the trading timeframe is H1 (D1 + H4 + H1): "
                   "H1 BOS, CHoCH, breaker, OB, inducement and ceiling; orders played on M15"},
}
ACTIVE = {"name": "v1", "first_read": None, "kinds": BOTH, "zone": False,
          "major": False, "rules": False, "ltf": "M15", "text": VARIANTS["v1"]["text"]}


def set_variant(name):
    name = (name or "v1").strip().lower()
    if name not in VARIANTS:
        raise SystemExit(f"Unknown VARIANT '{name}'. Use one of {sorted(VARIANTS)}")
    v = VARIANTS[name]
    config.BIAS_TIMEFRAMES = v["bias_tfs"]
    config.MAJOR_HTF = bool(v["major"])
    config.LTF_TF = v["ltf"]
    zn.SETTINGS["enabled"] = bool(v["zone"])
    zn.SETTINGS["rules"] = bool(v["rules"])
    ACTIVE["name"] = name
    ACTIVE["first_read"] = v["first_read"]
    ACTIVE["kinds"] = v["kinds"]
    ACTIVE["zone"] = bool(v["zone"])
    ACTIVE["major"] = bool(v["major"])
    ACTIVE["rules"] = bool(v["rules"])
    ACTIVE["ltf"] = v["ltf"]
    ACTIVE["text"] = v["text"]
    return name


def pip_size(pair):
    """0.01 for JPY pairs, 0.0001 otherwise."""
    return 0.01 if "jpy" in str(pair).lower() else 0.0001


def set_pair_settings(pair):
    """Per-pair values the zone rules need. Set before any engine run."""
    zn.SETTINGS["pip"] = pip_size(pair)
    zn.SETTINGS["spread"] = float(config.SPREAD_PRICE[pair])


class FlipRecorder(zn.ZoneRecorder):
    """ZoneRecorder + a read-only list of HTF bias flips (bull<->bear)."""

    def __init__(self, log, first_read=None):
        super().__init__(log, first_read)
        self.flips = []
        self._last_real = None

    def on_bar_close(self, bar, feed):
        super().on_bar_close(bar, feed)
        if bar.tf == "M15":
            hb = htf_bias(self.bias["D1"], self.bias["H4"])
            if hb is not None:
                if self._last_real is not None and hb != self._last_real:
                    self.flips.append(bar.close_time)
                self._last_real = hb


def run_engine(m15):
    log = DecisionLog()
    rec = FlipRecorder(log, ACTIVE["first_read"])
    DataFeed(m15, htf=("H1", "H4", "D1")).run(rec)
    return rec, log


def drop_weekend(df):
    """Drop bars outside the trading week on the New York clock.
    Uses only the bar's own open time. Returns (frame, number dropped)."""
    loc = df["timestamp"].dt.tz_convert(NY)
    dow = loc.dt.dayofweek
    hr = loc.dt.hour
    outside = (dow == 5) | ((dow == 6) & (hr < 17)) | ((dow == 4) & (hr >= 17))
    n = int(outside.sum())
    return df[~outside].reset_index(drop=True), n


def load_m15(pair, cutoff):
    df = pd.read_parquet(PROCESSED_DIR / f"{pair}_m15.parquet")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    df = df[df["timestamp"] + TF_M15 <= cutoff]
    df = df[["timestamp", "open", "high", "low", "close"]].reset_index(drop=True)
    df, dropped = drop_weekend(df)
    df["timestamp"] = df["timestamp"].astype("datetime64[ns, UTC]")
    df.attrs["dropped_weekend"] = dropped
    return df


def lookahead_check(m15, full_log, k):
    n = len(m15)
    if k <= 0:
        return {"cuts": 0, "pass": False, "decisions": 0, "bad": ["not run"]}
    fracs = [0.5] if k == 1 else [float(x) for x in np.linspace(0.1, 0.9, k)]
    bad = []
    checked = 0
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
    vname = set_variant(os.environ.get("VARIANT", "v1"))
    set_pair_settings(pair)
    print(f"[{pair}] variant {vname}: {ACTIVE['text']}", flush=True)
    print(f"[{pair}] ltf={ACTIVE['ltf']} major_htf={ACTIVE['major']} "
          f"zone_rules={ACTIVE['rules']} pip={zn.SETTINGS['pip']} "
          f"spread={zn.SETTINGS['spread']}", flush=True)
    cutoff = pd.Timestamp(config.PRACTICE_END, tz="UTC")
    m15 = load_m15(pair, cutoff)
    dropped = int(m15.attrs.get("dropped_weekend", 0))
    print(f"[{pair}] m15 bars: {len(m15)}  first {m15['timestamp'].iloc[0]}  "
          f"last close {m15['timestamp'].iloc[-1] + TF_M15}  "
          f"dropped weekend-window bars: {dropped}", flush=True)

    rec, log = run_engine(m15)
    n_all = len(rec.orders)
    kinds = tuple(ACTIVE["kinds"])
    orders = [o for o in rec.orders if o["kind"] in kinds]
    zorders = list(rec.zorders) if ACTIVE["zone"] else []
    print(f"[{pair}] main run done in {time.time() - t0:.0f}s: "
          f"{len(log.items)} decisions, {len(rec.pullbacks)} pullbacks, "
          f"{n_all} pullback orders made, {len(orders)} kept ({'+'.join(kinds)}), "
          f"{len(zorders)} zone orders, {len(rec.flips)} bias flips", flush=True)

    recs = so.simulate_all(orders + zorders, m15, pair)
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
    pd.DataFrame(rec.pullback_rows()).to_csv(OUT_DIR / f"{pair}_pullbacks.csv", index=False)
    statuses = df["status"].value_counts().to_dict() if len(df) else {}
    funnel = {"counts": {k_: int(v) for k_, v in rec.counts.items()},
              "orders": len(orders), "orders_made": n_all, "zone_orders": len(zorders),
              "statuses": statuses,
              "pullbacks": len(rec.pullbacks), "flips": len(rec.flips),
              "decisions": len(log.items), "bars": len(m15),
              "dropped_weekend_bars": dropped,
              "variant": vname, "ltf": ACTIVE["ltf"], "major_htf": bool(ACTIVE["major"]),
              "zone_rules": bool(ACTIVE["rules"]), "pip": zn.SETTINGS["pip"]}
    (OUT_DIR / f"{pair}_funnel.json").write_text(json.dumps(funnel, indent=1, default=str))
    (OUT_DIR / f"{pair}_lookahead.json").write_text(json.dumps(look, indent=1, default=str))

    done = ["target", "stop", "stop_gap"]
    res = df[df["outcome"].isin(done)]

    def card(leg, mode):
        t = res[(res["leg"] == leg) & (res["target_mode"] == mode)]
        return f"{len(t)} trades, net R {t['net_r'].astype(float).sum():.2f}"

    lines = [
        f"### Phase 4 cycle run: {pair}  [variant {vname}]",
        f"- Variant: {vname} ({ACTIVE['text']})",
        f"- Switches: trading timeframe {ACTIVE['ltf']}, major_htf {ACTIVE['major']}, "
        f"zone_rules {ACTIVE['rules']}, pip {zn.SETTINGS['pip']}",
        f"- Window: start of data to {config.PRACTICE_END}; bad days NOT excluded",
        f"- Bars used: {len(m15)}; dropped outside trading week (NY clock): {dropped}",
        f"- Pullback orders made {n_all}, simulated {len(orders)} ({'+'.join(kinds)}); "
        f"zone orders {len(zorders)}  |  Status: {statuses}",
        f"- Resolved: pullback {card('pullback', 'static')}; "
        f"zone static {card('zone', 'static')}; zone liquidity {card('zone', 'liquidity')}",
        f"- open_at_cutoff {int((df['outcome'] == 'open_at_cutoff').sum())}",
        f"- Lookahead: {'PASS' if look['pass'] else 'FAIL'} "
        f"({look['cuts']} cuts, {look['decisions']} decisions compared)",
        f"- Run time: {time.time() - t0:.0f}s\n",
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
