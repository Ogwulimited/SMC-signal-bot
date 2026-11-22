"""Replay cycle orders on trading-timeframe bars, bar by bar.

Two target modes are produced side by side:
  - ceiling: target is the pullback ceiling (only for orders with a locked
    ceiling; unlocked orders get status 'skipped_unlocked')
  - rr3:     static 1 : config.RR_STATIC target with 50% partial scale-out at
             +1.0R and Break-Even stop on the remaining 50% runner to +3.0R

When spread > 0, prices are assumed to be BID.
  - BUY  fills on ASK (bar.low + spread <= entry),
         stops on BID (bar.low <= stop),
         hits target on BID (bar.high >= target).
  - SELL fills on BID (bar.high >= entry),
         stops on ASK (bar.high + spread >= stop),
         hits target on ASK (bar.low + spread <= target).
"""
import math

import pandas as pd

from src import config

TRADE_COLS = [
    "id", "pullback", "setup", "variant", "kind", "side", "mode", "placed_time",
    "fill_time", "exit_time", "entry", "fill_price", "stop", "target", "rr",
    "status", "r", "bars_to_fill", "bars_held", "cancel_reason", "mfe_r", "mae_r",
]

TP1_TRIGGER_R = 1.0
TP1_WEIGHT = 0.5


def _ok(x):
    return x is not None and not (isinstance(x, float) and math.isnan(x))


def _target(o, mode, fill):
    up = o["side"] == "sell"
    risk = (o["stop"] - fill) if up else (fill - o["stop"])
    if risk <= 0:
        return None, None
    if mode == "rr3":
        rr = float(config.RR_STATIC)
        t = fill - rr * risk if up else fill + rr * risk
        return float(t), rr
    if not o["ceiling_locked"] or not _ok(o["ceiling"]):
        return None, None
    t = float(o["ceiling"])
    rr = (fill - t) / risk if up else (t - fill) / risk
    if rr <= 0:
        return None, None
    return t, float(rr)


def _sim_one(o, bars, times, mode, spread=0.0):
    up = o["side"] == "sell"
    entry = o["entry"]
    stop = o["stop"]
    end = o["end_time"]
    fill_type = o.get("fill", "limit")
    i0 = times.searchsorted(o["placed_time"], side="right")
    fill_t = None
    fill_i = None
    fill = entry
    for i in range(i0, len(bars)):
        b = bars[i]
        if end is not None and b.close_time > end:
            return _row(o, mode, None, None, None, None, None, "cancelled", None,
                        None, None, o["end_reason"])
        if fill_type == "next_open":
            fill = (b.open + spread) if not up else b.open
            if (up and fill >= stop) or (not up and fill <= stop):
                return _row(o, mode, None, None, None, None, None,
                            "skipped_beyond_stop", None, None, None, "open_beyond_stop")
            risk = (stop - fill) if up else (fill - stop)
            if spread > 0.0 and (spread / risk) > float(config.MAX_SPREAD_RISK_RATIO):
                return _row(o, mode, None, None, None, None, None,
                            "skipped_spread", None, None, None, "spread_too_wide")
            fill_t = b.close_time
            fill_i = i
            break
        hit = b.high >= entry if up else (b.low + spread) <= entry
        if hit:
            fill = entry
            risk = (stop - fill) if up else (fill - stop)
            if spread > 0.0 and (spread / risk) > float(config.MAX_SPREAD_RISK_RATIO):
                return _row(o, mode, None, None, None, None, None,
                            "skipped_spread", None, None, None, "spread_too_wide")
            fill_t = b.close_time
            fill_i = i
            break
    if fill_t is None:
        return _row(o, mode, None, None, None, None, None, "unfilled", None, None,
                    None, None)
    target, rr = _target(o, mode, fill)
    if target is None:
        why = "unlocked" if mode == "ceiling" else "bad_target"
        return _row(o, mode, fill_t, None, fill, None, None, f"skipped_{why}", None,
                    fill_i - i0 + 1, None, None)
    risk = (stop - fill) if up else (fill - stop)
    use_scaleout = (mode == "rr3")
    tp1_trigger = (fill - TP1_TRIGGER_R * risk) if up else (fill + TP1_TRIGGER_R * risk)
    full_win_r = (TP1_WEIGHT * TP1_TRIGGER_R + (1.0 - TP1_WEIGHT) * rr) if use_scaleout else rr
    partial_win_r = TP1_WEIGHT * TP1_TRIGGER_R
    curr_stop = stop
    tp1_active = False
    if fill_type == "next_open":
        b0 = bars[fill_i]
        sh0 = (b0.high + spread) >= stop if up else b0.low <= stop
        th0 = (b0.low + spread) <= target if up else b0.high >= target
        if sh0 and th0:
            return _row(o, mode, fill_t, fill_t, fill, target, rr, "loss", -1.0,
                        1, 0, "both_hit_open_bar", 0.0, 1.0)
        if sh0:
            return _row(o, mode, fill_t, fill_t, fill, target, rr, "loss", -1.0,
                        1, 0, None, 0.0, 1.0)
        if th0:
            return _row(o, mode, fill_t, fill_t, fill, target, rr, "win", full_win_r,
                        1, 0, None, rr, 0.0)
        if use_scaleout:
            tp1_0 = (b0.low + spread) <= tp1_trigger if up else b0.high >= tp1_trigger
            if tp1_0:
                curr_stop = fill
                tp1_active = True
    mfe_r = 0.0
    mae_r = 0.0
    for j in range(fill_i + 1, len(bars)):
        b = bars[j]
        if up:
            fav = (fill - (b.low + spread)) / risk
            adv = ((b.high + spread) - fill) / risk
        else:
            fav = (b.high - fill) / risk
            adv = (fill - b.low) / risk
        if fav > mfe_r:
            mfe_r = fav
        if adv > mae_r:
            mae_r = adv
        stop_hit = (b.high + spread) >= curr_stop if up else b.low <= curr_stop
        target_hit = (b.low + spread) <= target if up else b.high >= target
        if stop_hit and target_hit:
            status = "win" if tp1_active else "loss"
            r_val = partial_win_r if tp1_active else -1.0
            return _row(o, mode, fill_t, b.close_time, fill, target, rr, status,
                        r_val, fill_i - i0 + 1, j - fill_i, "both_hit_same_bar",
                        mfe_r, mae_r)
        if stop_hit:
            status = "win" if tp1_active else "loss"
            r_val = partial_win_r if tp1_active else -1.0
            return _row(o, mode, fill_t, b.close_time, fill, target, rr, status,
                        r_val, fill_i - i0 + 1, j - fill_i, None, mfe_r, mae_r)
        if target_hit:
            return _row(o, mode, fill_t, b.close_time, fill, target, rr, "win",
                        full_win_r, fill_i - i0 + 1, j - fill_i, None, mfe_r, mae_r)
        if use_scaleout and not tp1_active:
            tp1_hit = (b.low + spread) <= tp1_trigger if up else b.high >= tp1_trigger
            if tp1_hit:
                curr_stop = fill
                tp1_active = True
    return _row(o, mode, fill_t, None, fill, target, rr, "open", None,
                fill_i - i0 + 1, len(bars) - 1 - fill_i, None, mfe_r, mae_r)


def _row(o, mode, fill_t, exit_t, fill_p, target, rr, status, r, btf, bh, reason,
         mfe_r=None, mae_r=None):
    return {"id": o["id"], "pullback": o["pullback"], "setup": o["setup"],
            "variant": o.get("variant", "plain"), "kind": o["kind"],
            "side": o["side"], "mode": mode, "placed_time": o["placed_time"],
            "fill_time": fill_t, "exit_time": exit_t, "entry": o["entry"],
            "fill_price": fill_p, "stop": o["stop"], "target": target, "rr": rr,
            "status": status, "r": r, "bars_to_fill": btf, "bars_held": bh,
            "cancel_reason": reason, "mfe_r": mfe_r, "mae_r": mae_r}


def simulate(orders, m15_df, spread=0.0):
    bars = [row for row in m15_df.itertuples(index=False)]
    times = pd.Index([b.close_time for b in bars])
    rows = []
    for o in orders:
        for mode in ("ceiling", "rr3"):
            rows.append(_sim_one(o, bars, times, mode, spread=spread))
    return pd.DataFrame(rows, columns=TRADE_COLS)
