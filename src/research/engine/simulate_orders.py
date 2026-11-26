"""Simulate pending limit orders on M15 OHLC with Phase 1 Management Ladder & Partial Engine."""
import numpy as np
import pandas as pd

from src import config

EXPIRY = pd.Timedelta(hours=48)
ASSAULT_PROX_R = 0.25
ZONE_CANCEL_PIPS = 150.0
BE_TRIGGER_R = 2.0

# Management presets evaluated simultaneously on every trade for paired A/B testing
MGMT_PRESETS = {
    "legacy":   {"mode": "legacy", "be_r": 2.0,  "part_r": None,  "part_f": 0.0},
    "be_10":    {"mode": "all",    "be_r": 1.0,  "part_r": None,  "part_f": 0.0},
    "be_15":    {"mode": "all",    "be_r": 1.5,  "part_r": None,  "part_f": 0.0},
    "be_20":    {"mode": "all",    "be_r": 2.0,  "part_r": None,  "part_f": 0.0},
    "be10_p20": {"mode": "all",    "be_r": 1.0,  "part_r": 2.0,   "part_f": 0.5},
    "p15_be":   {"mode": "all",    "be_r": 1.5,  "part_r": 1.5,   "part_f": 0.5},
    "be15_p20": {"mode": "all",    "be_r": 1.5,  "part_r": 2.0,   "part_f": 0.5},
    # +/-25% perturbation sensitivity grid
    "be_075":   {"mode": "all",    "be_r": 0.75, "part_r": None,  "part_f": 0.0},
    "be_1125":  {"mode": "all",    "be_r": 1.125,"part_r": None,  "part_f": 0.0},
    "be_125":   {"mode": "all",    "be_r": 1.25, "part_r": None,  "part_f": 0.0},
    "be_1875":  {"mode": "all",    "be_r": 1.875,"part_r": None,  "part_f": 0.0},
    "p15_lo":   {"mode": "all",    "be_r": 1.125,"part_r": 1.125, "part_f": 0.5},
    "p15_hi":   {"mode": "all",    "be_r": 1.875,"part_r": 1.875, "part_f": 0.5},
}


def _eval_path(h, l, op, ts, fi, fill, stop, target, risk, sc, sell,
               open_fill, use_be, be_trig_r, part_trig_r=None, part_frac=0.0):
    """Evaluate bar-by-bar outcome from fill index `fi` under given management parameters."""
    mfe = 0.0
    mae = 0.0
    be_active = False
    part_done = False
    cur_stop = stop
    be_trig_px = (fill - be_trig_r * risk) if (use_be and sell) else (
                 (fill + be_trig_r * risk) if use_be else None)
    part_px = None
    if part_trig_r is not None and part_frac > 0.0:
        part_px = (fill - part_trig_r * risk) if sell else (fill + part_trig_r * risk)

    for j in range(fi, len(ts)):
        hj, lj, oj = h[j], l[j], op[j]
        if sell:
            fav = max(0.0, fill - lj)
            adv = max(0.0, hj - fill)
            hit_sl = hj >= cur_stop
            hit_tp = lj <= target
            hit_part = (part_px is not None) and (not part_done) and (lj <= part_px)
        else:
            fav = max(0.0, hj - fill)
            adv = max(0.0, fill - lj)
            hit_sl = lj <= cur_stop
            hit_tp = hj >= target
            hit_part = (part_px is not None) and (not part_done) and (hj >= part_px)

        if fav > mfe:
            mfe = fav
        if adv > mae:
            mae = adv

        # Same-bar limit fill: only count target if bar opened beyond fill (conservative rule)
        if j == fi and not open_fill:
            hit_tp = False
            hit_part = False

        # Conservative intrabar ordering: stop checked before partial/target on the same bar
        if hit_sl:
            if part_done:
                # Runner stopped at BE; partial already banked at part_trig_r
                rem = 1.0 - part_frac
                net_r = part_frac * (part_trig_r - sc / risk) + rem * (-sc / risk)
                status = "partial_be"
            else:
                status = "be" if be_active else "stop"
                gross_r = 0.0 if be_active else -1.0
                net_r = gross_r - (sc / risk)
            return {
                "status": status,
                "fill_ts": ts[fi],
                "fill_price": fill,
                "exit_ts": ts[j],
                "exit_price": cur_stop,
                "gross_r": round(net_r + (sc / risk), 4),
                "net_r": round(net_r, 4),
                "mfe_r": round(mfe / risk, 3),
                "mae_r": round(mae / risk, 3),
            }

        if hit_part:
            part_done = True
            be_active = True
            cur_stop = fill

        if hit_tp:
            full_tp_r = abs(target - fill) / risk
            if part_done:
                rem = 1.0 - part_frac
                gross_r = part_frac * part_trig_r + rem * full_tp_r
                status = "partial_target"
            else:
                gross_r = full_tp_r
                status = "target"
            net_r = gross_r - (sc / risk)
            return {
                "status": status,
                "fill_ts": ts[fi],
                "fill_price": fill,
                "exit_ts": ts[j],
                "exit_price": target,
                "gross_r": round(gross_r, 4),
                "net_r": round(net_r, 4),
                "mfe_r": round(mfe / risk, 3),
                "mae_r": round(mae / risk, 3),
            }

        # Next-bar BE activation once price reaches be_trig_px
        if use_be and not be_active:
            if (sell and lj <= be_trig_px) or (not sell and hj >= be_trig_px):
                if j > fi or open_fill:
                    be_active = True
                    cur_stop = fill

    return {
        "status": "open",
        "fill_ts": ts[fi],
        "fill_price": fill,
        "mfe_r": round(mfe / risk, 3),
        "mae_r": round(mae / risk, 3),
    }


def _sim_zone_fill1_net_r(h, l, op, ts, fi, o, sc, fill2_net_r):
    """Simulate counterfactual Fill-1 (entering on first M15 bar after zone touch) for stress test."""
    if o.get("leg") != "zone":
        return fill2_net_r
    z_low = o.get("zone_low")
    z_high = o.get("zone_high")
    if z_low is None or z_high is None:
        return fill2_net_r
    sell = o["direction"] == "sell"
    entry = float(o["entry"])
    stop = float(o["stop"])
    target = float(o["target"])
    risk = abs(entry - stop)
    if risk <= 0:
        return fill2_net_r
    # Check if an earlier bar between placed_ts and fi already touched the HTF zone
    placed_idx = max(0, fi - 32)
    f1_idx = fi
    for k in range(placed_idx, fi):
        if l[k] <= entry <= h[k]:
            f1_idx = k
            break
    open_fill = (op[f1_idx] <= entry) if sell else (op[f1_idx] >= entry)
    res = _eval_path(h, l, op, ts, f1_idx, entry, stop, target, risk, sc, sell,
                     open_fill, False, 2.0, None, 0.0)
    return res.get("net_r", fill2_net_r)


def simulate_order(o, ts, h, l, op, cl, spread, pip=0.0001, rules=False):
    placed = pd.Timestamp(o["placed_ts"]).tz_convert("UTC") if pd.Timestamp(o["placed_ts"]).tzinfo else pd.Timestamp(o["placed_ts"], tz="UTC")
    entry = float(o["entry"])
    stop = float(o["stop"])
    target = float(o["target"])
    sell = o["direction"] == "sell"
    risk = abs(entry - stop)
    if risk <= 0:
        return {"status": "invalid"}

    start = int(np.searchsorted(ts, placed.to_datetime64(), side="right"))
    end_ts = (placed + EXPIRY).to_datetime64()
    end = int(np.searchsorted(ts, end_ts, side="right"))

    leg = o.get("leg", "pullback")
    prox = ASSAULT_PROX_R * risk
    cancel_dist = ZONE_CANCEL_PIPS * pip
    fi = None
    for i in range(start, min(end, len(ts))):
        if l[i] <= entry <= h[i]:
            fi = i
            break
        if leg == "pullback":
            if (sell and l[i] <= target + prox) or (not sell and h[i] >= target - prox):
                return {"status": "cancelled_assault", "cancel_ts": ts[i]}
        elif rules and leg == "zone":
            dist = (cl[i] - entry) if not sell else (entry - cl[i])
            if dist >= cancel_dist:
                return {"status": "cancelled_150p", "cancel_ts": ts[i]}

    if fi is None:
        return {"status": "expired"}

    fill = entry
    sc = spread
    open_fill = (op[fi] <= entry) if sell else (op[fi] >= entry)

    # Legacy BE rule: only applied on pullback OB sell and H1 zone trades at +2R
    legacy_use_be = rules and (
        (leg == "pullback" and sell and o.get("kind") == "ob")
        or (leg == "zone" and o.get("zone_tf") == "H1")
    )

    # Pure static 1:3 (no BE, no partials)
    res_static = _eval_path(h, l, op, ts, fi, fill, stop, target, risk, sc, sell,
                            open_fill, False, 2.0, None, 0.0)
    # Legacy baseline (matches +235.75R exact rules)
    res_leg = _eval_path(h, l, op, ts, fi, fill, stop, target, risk, sc, sell,
                         open_fill, legacy_use_be, BE_TRIGGER_R, None, 0.0)

    # Active management mode from config (used only if explicitly requested; default report shows both)
    active_mode = getattr(config, "MANAGEMENT_MODE", "legacy")
    if active_mode not in MGMT_PRESETS:
        active_mode = "legacy"

    # Keep main scorecard outcome fields anchored to Legacy Baseline so baseline comparison is exact,
    # while attaching all management ladder outcomes & active managed outcome to every trade record.
    res_base = dict(res_leg)
    res_base["static_status"] = res_static["status"]
    res_base["static_net_r"] = res_static.get("net_r")

    if res_leg["status"] not in ("target", "stop", "be", "partial_be", "partial_target"):
        return res_base

    # Evaluate all management ladder presets for Change 1 paired bootstrap & sensitivity tables
    for k, spec in MGMT_PRESETS.items():
        if k == "legacy":
            r_k = res_leg
        else:
            r_k = _eval_path(
                h, l, op, ts, fi, fill, stop, target, risk, sc, sell,
                open_fill, True, spec["be_r"], spec["part_r"], spec["part_f"]
            )
        res_base[f"r_{k}"] = r_k.get("net_r")
        res_base[f"st_{k}"] = r_k["status"]

    # Active managed columns for primary managed scorecard
    res_base["managed_mode"] = active_mode
    res_base["managed_net_r"] = res_base.get(f"r_{active_mode}", res_base.get("net_r"))
    res_base["managed_status"] = res_base.get(f"st_{active_mode}", res_base["status"])

    # Spread cost in R and counterfactual Fill-1 R for stress testing
    res_base["spread_r"] = round(sc / risk, 4)
    res_base["fill1_net_r"] = _sim_zone_fill1_net_r(h, l, op, ts, fi, o, sc, res_base.get("net_r"))

    # Counterfactual unpadded net_r for trades where stop was min-risk padded
    if o.get("min_risk_padded") and o.get("raw_stop") is not None:
        raw_stop = float(o["raw_stop"])
        raw_risk = abs(entry - raw_stop)
        if raw_risk > 0:
            raw_target = (entry - config.RR_TARGET * raw_risk) if sell else (entry + config.RR_TARGET * raw_risk)
            r_unpad = _eval_path(h, l, op, ts, fi, fill, raw_stop, raw_target, raw_risk, sc, sell,
                                 open_fill, legacy_use_be, BE_TRIGGER_R, None, 0.0)
            res_base["unpadded_net_r"] = r_unpad.get("net_r")
            res_base["unpadded_spread_ratio"] = round(sc / raw_risk, 4)

    return res_base


def simulate_all(orders, m15_df, spread, pip=0.0001, rules=False):
    ts = m15_df["timestamp"].to_numpy()
    h = m15_df["high"].to_numpy(dtype=float)
    l = m15_df["low"].to_numpy(dtype=float)
    op = m15_df["open"].to_numpy(dtype=float)
    cl = m15_df["close"].to_numpy(dtype=float)
    out = []
    for o in orders:
        res = simulate_order(o, ts, h, l, op, cl, spread, pip=pip, rules=rules)
        row = dict(o)
        row.update(res)
        out.append(row)
    return out
