"""Order simulator for the cycle engine (practice years).

Takes the orders the cycle produced and plays them on M15 bars.
  * Touch: a bar after placement reaches the entry price.
  * Fill: at the NEXT M15 open (Fill 2). Stop/target are checked from the fill
    bar's open. 1R = |fill - stop|. Target = fill -/+ RR_STATIC x R.
  * Next open already beyond the stop -> fill_beyond_stop (no trade).
  * Spread cost = SPREAD_PRICE[pair] / risk. Above MAX_SPREAD_RISK_RATIO -> skipped_spread.
  * Stop wins a same-bar tie. A bar that OPENS beyond the stop fills the loss
    at that open (loss can exceed 1R).
  * Order ended by zone / attempt_failed / bias_lost: the ending bar cannot touch.
    Ended by ceiling_break: the ending bar can touch.
  * No management after entry, no time stop. Unresolved = open_at_cutoff.
  * Net R = gross R - spread_cost_r.
"""
import numpy as np
import pandas as pd

from src import config

STEP = pd.Timedelta(minutes=15)
FAR = pd.Timestamp("2262-01-01", tz="UTC")

TRADE_COLS = [
    "pair", "order_id", "pullback", "setup", "variant", "kind", "side",
    "placed_time", "end_time", "end_reason", "ceiling", "ceiling_locked",
    "entry", "stop", "status", "touch_time", "fill_time", "fill_price",
    "risk_r", "spread_cost_r", "target_price", "outcome", "exit_time",
    "exit_price", "r_gross", "net_r", "dur_hours",
    "open_at_entry", "kept_1at", "flip_while_open",
]

_COPY = ("pullback", "setup", "variant", "kind", "side", "placed_time", "end_time",
         "end_reason", "ceiling", "ceiling_locked", "entry", "stop")


def prepare(m15):
    ts = pd.DatetimeIndex(m15["timestamp"])
    return {"open_t": ts, "close_t": ts + STEP,
            "o": m15["open"].to_numpy(float), "h": m15["high"].to_numpy(float),
            "l": m15["low"].to_numpy(float)}


def simulate_order(o, a, spread, pair):
    sell = o["side"] == "sell"
    rec = {c: None for c in TRADE_COLS}
    rec["pair"] = pair
    rec["order_id"] = o["id"]
    for k in _COPY:
        rec[k] = o[k]
    n = len(a["o"])
    entry = float(o["entry"])
    stop = float(o["stop"])
    end = o["end_time"]

    s = int(a["open_t"].searchsorted(o["placed_time"], side="left"))
    if end is None:
        e = n
    elif o["end_reason"] == "ceiling_break":
        e = int(a["close_t"].searchsorted(end, side="right"))
    else:
        e = int(a["close_t"].searchsorted(end, side="left"))
    e = min(max(e, s), n)

    touch = None
    if e > s:
        seg = (a["h"][s:e] >= entry) if sell else (a["l"][s:e] <= entry)
        if seg.any():
            touch = s + int(np.argmax(seg))
    if touch is None:
        rec["status"] = "unfilled_open" if end is None else "unfilled_cancelled"
        return rec

    rec["touch_time"] = a["close_t"][touch]
    f = touch + 1
    if f >= n:
        rec["status"] = "unfilled_open"
        return rec

    fill = float(a["o"][f])
    rec["fill_time"] = a["open_t"][f]
    rec["fill_price"] = fill
    if (sell and fill >= stop) or ((not sell) and fill <= stop):
        rec["status"] = "fill_beyond_stop"
        return rec

    risk = abs(fill - stop)
    sc = float(spread) / risk
    rec["risk_r"] = risk
    rec["spread_cost_r"] = sc
    if sc > float(config.MAX_SPREAD_RISK_RATIO):
        rec["status"] = "skipped_spread"
        return rec

    rr = float(config.RR_STATIC)
    target = fill - rr * risk if sell else fill + rr * risk
    rec["target_price"] = target
    rec["status"] = "filled"

    h = a["h"][f:]
    l = a["l"][f:]
    op = a["o"][f:]
    if sell:
        stop_hit = h >= stop
        tgt_hit = l <= target
        gap = op >= stop
    else:
        stop_hit = l <= stop
        tgt_hit = h >= target
        gap = op <= stop
    gap[0] = False
    si = int(np.argmax(stop_hit)) if stop_hit.any() else None
    ti = int(np.argmax(tgt_hit)) if tgt_hit.any() else None
    if si is None and ti is None:
        rec["outcome"] = "open_at_cutoff"
        return rec

    if ti is None or (si is not None and si <= ti):
        idx = si
        if gap[si]:
            ex = float(op[si])
            out = "stop_gap"
        else:
            ex = stop
            out = "stop"
    else:
        idx = ti
        ex = target
        out = "target"

    gross = (fill - ex) / risk if sell else (ex - fill) / risk
    exit_time = a["close_t"][f + idx]
    rec["outcome"] = out
    rec["exit_time"] = exit_time
    rec["exit_price"] = ex
    rec["r_gross"] = gross
    rec["net_r"] = gross - sc
    rec["dur_hours"] = (exit_time - rec["fill_time"]).total_seconds() / 3600.0
    return rec


def tag_trades(recs, flips):
    """open_at_entry, kept_1at (one-at-a-time per pair), flip_while_open."""
    filled = [r for r in recs if r["status"] == "filled"]
    filled.sort(key=lambda r: r["fill_time"])

    def held(r):
        return FAR if r["outcome"] == "open_at_cutoff" else r["exit_time"]

    last_free = None
    for i, r in enumerate(filled):
        et = r["fill_time"]
        r["open_at_entry"] = sum(1 for j in range(i) if held(filled[j]) > et)
        if last_free is None or et >= last_free:
            r["kept_1at"] = True
            last_free = held(r)
        else:
            r["kept_1at"] = False
        hu = held(r)
        r["flip_while_open"] = bool(any(et < fl <= hu for fl in flips))
    for r in recs:
        if r["status"] != "filled":
            r["kept_1at"] = False
            r["flip_while_open"] = False


def simulate_all(orders, m15, pair):
    a = prepare(m15)
    spread = config.SPREAD_PRICE[pair]
    return [simulate_order(o, a, spread, pair) for o in orders]
