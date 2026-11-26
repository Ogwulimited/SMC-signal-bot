"""Order simulator for the cycle engine (practice years).
Takes the orders the cycle produced and plays them on M15 bars.
  * Touch: a bar after placement reaches the entry price.
  * Fill (default orders): at the NEXT M15 open (Fill 2). Stop/target are
    checked from the fill bar's open. 1R = |fill - stop|.
  * Fill (limit orders, o["fill"] == "limit"): in the touch bar itself.
    If the bar opens at or past the entry (buy: open <= entry, sell: open >=
    entry) the fill is at that open, like a broker. Otherwise it fills at the
    entry price. Fill bar rule: after a mid-bar edge fill the stop counts in
    that bar but the target does not (the order of high and low inside the bar
    is unknown); after an open fill the whole bar counts.
  * Targets: "static" = fill -/+ RR x R (all orders). RR is RR_STATIC unless
             the order carries its own "rr".
             "liquidity" (zone orders only) = the nearest unswept swing at least
             LIQ_MIN_R x R away (list carried by the order, nearest first); if
             none, the order's ceiling; if the ceiling is not beyond the fill,
             status skipped_no_target.
  * Phase 1 Management Ladder & Partial Engine:
    Simultaneously evaluates Legacy BE (+2R on pullback OB sell & H1 zone) and
    generalized BE / partial-exit presets on every static trade so paired
    bootstrap CIs can be computed without changing trade frequency.
"""
import numpy as np
import pandas as pd
from src import config

STEP = pd.Timedelta(minutes=15)
FAR = pd.Timestamp("2262-01-01", tz="UTC")
LIQ_MIN_R = 3.0
BE_TRIGGER_R = 2.0

MGMT_PRESETS = {
    "legacy":   {"mode": "legacy", "be_r": 2.0,   "part_r": None,  "part_f": 0.0},
    "be_10":    {"mode": "all",    "be_r": 1.0,   "part_r": None,  "part_f": 0.0},
    "be_15":    {"mode": "all",    "be_r": 1.5,   "part_r": None,  "part_f": 0.0},
    "be_20":    {"mode": "all",    "be_r": 2.0,   "part_r": None,  "part_f": 0.0},
    "be10_p20": {"mode": "all",    "be_r": 1.0,   "part_r": 2.0,   "part_f": 0.5},
    "p15_be":   {"mode": "all",    "be_r": 1.5,   "part_r": 1.5,   "part_f": 0.5},
    "be15_p20": {"mode": "all",    "be_r": 1.5,   "part_r": 2.0,   "part_f": 0.5},
    # +/- 25% perturbation grid around BE@1.0, BE@1.5, and 50%@1.5R+BE
    "be_075":   {"mode": "all",    "be_r": 0.75,  "part_r": None,  "part_f": 0.0},
    "be_1125":  {"mode": "all",    "be_r": 1.125, "part_r": None,  "part_f": 0.0},
    "be_125":   {"mode": "all",    "be_r": 1.25,  "part_r": None,  "part_f": 0.0},
    "be_1875":  {"mode": "all",    "be_r": 1.875, "part_r": None,  "part_f": 0.0},
    "p15_lo":   {"mode": "all",    "be_r": 1.125, "part_r": 1.125, "part_f": 0.5},
    "p15_hi":   {"mode": "all",    "be_r": 1.875, "part_r": 1.875, "part_f": 0.5},
}

_EXTRA_CONFLUENCE_COLS = (
    "raw_stop", "min_risk_padded", "dest_room_r", "opp_h1_in_path",
    "deal_pct", "local_ote_pct", "fvg_overlap", "sweep_reclaim",
    "disp_body_atr", "disp_close_pct", "ny_hour", "killzone", "h1_refined_ok",
)

TRADE_COLS = [
    "pair", "order_id", "pullback", "setup", "variant", "kind", "side",
    "placed_time", "end_time", "end_reason", "ceiling", "ceiling_locked",
    "entry", "stop", "status", "touch_time", "fill_time", "fill_price",
    "risk_r", "spread_cost_r", "target_price", "outcome", "exit_time",
    "exit_price", "r_gross", "net_r", "dur_hours", "mfe_r", "mae_r",
    "open_at_entry", "kept_1at", "flip_while_open",
    "leg", "target_mode", "target_kind", "target_r", "bos_time",
    "zone_touch_time", "zone_tf", "zone_low", "zone_high", "choch_time",
    "choch_level", "htf_bias", "box_low", "box_high", "box_time",
    "idm_level", "idm_sweep_time",
] + list(_EXTRA_CONFLUENCE_COLS) + [
    "fill1_net_r", "unpadded_net_r", "unpadded_spread_ratio",
] + [f"r_{k}" for k in MGMT_PRESETS] + [f"out_{k}" for k in MGMT_PRESETS]

_COPY = ("pullback", "setup", "variant", "kind", "side", "placed_time", "end_time",
         "end_reason", "ceiling", "ceiling_locked", "entry", "stop")
_ZONE_COPY = ("bos_time", "zone_touch_time", "zone_tf", "zone_low", "zone_high",
              "choch_time", "choch_level", "htf_bias", "box_low", "box_high",
              "box_time", "idm_level", "idm_sweep_time")


def prepare(m15):
    ts = pd.DatetimeIndex(m15["timestamp"])
    return {"open_t": ts, "close_t": ts + STEP,
            "o": m15["open"].to_numpy(float), "h": m15["high"].to_numpy(float),
            "l": m15["low"].to_numpy(float)}


def _liq_target(o, fill, risk, sell):
    """Liquidity target: nearest listed swing >= LIQ_MIN_R away, else the ceiling."""
    need = float(LIQ_MIN_R) * risk
    for p in o.get("liq") or []:
        if sell and p <= fill - need:
            return float(p), "swing"
        if (not sell) and p >= fill + need:
            return float(p), "swing"
    c = o.get("ceiling")
    if c is not None:
        c = float(c)
        if (sell and c < fill) or ((not sell) and c > fill):
            return c, "ceiling"
    return None, None


def _eval_path(h, l, op, fill, stop, target, risk, sc, sell, limit, open_fill,
               use_be, be_trig_r, part_trig_r=None, part_frac=0.0):
    """Evaluate trade path on arrays h, l, op starting from fill bar (index 0).
    Preserves exact vectorized rules for full-position BE and supports virtual
    sub-position partial exits (e.g. 50% at +1.5R or +2.0R, stop to BE from next bar).
    """
    if sell:
        stop_hit = h >= stop
        tgt_hit = l <= target
        gap = op >= stop
    else:
        stop_hit = l <= stop
        tgt_hit = h >= target
        gap = op <= stop
    gap = gap.copy()
    tgt_hit = tgt_hit.copy()
    gap[0] = False
    if limit and not open_fill:
        tgt_hit[0] = False

    si = int(np.argmax(stop_hit)) if stop_hit.any() else None
    ti = int(np.argmax(tgt_hit)) if tgt_hit.any() else None

    bi = None
    if use_be and be_trig_r is not None:
        if sell:
            be_trig = fill - float(be_trig_r) * risk
            be_hit = l <= be_trig
        else:
            be_trig = fill + float(be_trig_r) * risk
            be_hit = h >= be_trig
        if limit and not open_fill:
            be_hit = be_hit.copy()
            be_hit[0] = False
        bi = int(np.argmax(be_hit)) if be_hit.any() else None

    pi = None
    if part_trig_r is not None and part_frac > 0.0:
        if sell:
            p_trig = fill - float(part_trig_r) * risk
            p_hit = l <= p_trig
        else:
            p_trig = fill + float(part_trig_r) * risk
            p_hit = h >= p_trig
        if limit and not open_fill:
            p_hit = p_hit.copy()
            p_hit[0] = False
        pi = int(np.argmax(p_hit)) if p_hit.any() else None

    # Check if partial trigger happens before initial stop or full target
    part_active = (
        pi is not None
        and (si is None or pi < si)
        and (ti is None or pi <= ti)
    )

    # Effective BE activation bar index (earliest of BE trigger or partial trigger, active from next bar)
    eff_bi = None
    if use_be and bi is not None and (si is None or bi < si) and (ti is None or bi < ti):
        eff_bi = bi
    if part_active and pi < (ti if ti is not None else len(h)):
        if eff_bi is None or pi < eff_bi:
            eff_bi = pi

    be_active = (
        eff_bi is not None
        and (si is None or eff_bi < si)
        and (ti is None or eff_bi < ti)
        and (eff_bi + 1 < len(h))
    )

    if be_active:
        start = eff_bi + 1
        if sell:
            be_stop_hit = h[start:] >= fill
            be_gap = op[start:] >= fill
        else:
            be_stop_hit = l[start:] <= fill
            be_gap = op[start:] <= fill
        bsi = (start + int(np.argmax(be_stop_hit))) if be_stop_hit.any() else None
        if bsi is not None and (ti is None or bsi <= ti):
            idx = bsi
            if be_gap[bsi - start]:
                ex = float(op[bsi])
                out = "stop_gap"
            else:
                ex = fill
                out = "stop"
        elif ti is not None:
            idx = ti
            ex = target
            out = "target"
        else:
            return {"outcome": "open_at_cutoff", "idx": None, "ex": None,
                    "r_gross": None, "net_r": None, "mfe_r": None, "mae_r": None}
    else:
        if si is None and ti is None:
            return {"outcome": "open_at_cutoff", "idx": None, "ex": None,
                    "r_gross": None, "net_r": None, "mfe_r": None, "mae_r": None}
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

    # Compute MFE and MAE in R-multiples across the active trade path [0..idx]
    fav_start = 1 if (limit and not open_fill) else 0
    if fav_start <= idx:
        if sell:
            best_fav = float(np.min(l[fav_start:idx + 1]))
            mfe_r = max(0.0, (fill - best_fav) / risk)
        else:
            best_fav = float(np.max(h[fav_start:idx + 1]))
            mfe_r = max(0.0, (best_fav - fill) / risk)
    else:
        mfe_r = 0.0
    if out == "target":
        mfe_r = max(mfe_r, abs(target - fill) / risk)
    if sell:
        worst_adv = float(np.max(h[:idx + 1]))
        mae_r = max(0.0, (worst_adv - fill) / risk)
    else:
        worst_adv = float(np.min(l[:idx + 1]))
        mae_r = max(0.0, (fill - worst_adv) / risk)

    runner_gross = (fill - ex) / risk if sell else (ex - fill) / risk
    if part_active and pi <= idx:
        f_part = float(part_frac)
        gross = f_part * float(part_trig_r) + (1.0 - f_part) * runner_gross
        if out in ("stop", "stop_gap") and abs(runner_gross) < 1e-9:
            out = "partial_be"
        elif out == "target":
            out = "partial_target"
    else:
        gross = runner_gross

    net_r = gross - sc
    return {
        "outcome": out,
        "idx": idx,
        "ex": ex,
        "r_gross": gross,
        "net_r": net_r,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
    }


def _sim_zone_fill1_net_r(o, a, touch, stop, spread, sell):
    """Simulate counterfactual Fill-1 (limit fill inside touch bar) on zone orders for stress test."""
    entry = float(o["entry"])
    bar_open = float(a["o"][touch])
    open_fill = (bar_open >= entry) if sell else (bar_open <= entry)
    fill = bar_open if open_fill else entry
    if (sell and fill >= stop) or ((not sell) and fill <= stop):
        return None
    risk = abs(fill - stop)
    if risk <= 0:
        return None
    sc = float(spread) / risk
    if sc > float(config.MAX_SPREAD_RISK_RATIO):
        return None
    rr = float(config.RR_STATIC) if o.get("rr") is None else float(o.get("rr"))
    target = fill - rr * risk if sell else fill + rr * risk
    use_be = (o.get("leg") == "zone" and o.get("zone_tf") == "H1")
    res = _eval_path(
        a["h"][touch:], a["l"][touch:], a["o"][touch:],
        fill, stop, target, risk, sc, sell, True, open_fill,
        use_be, float(BE_TRIGGER_R), None, 0.0
    )
    return res["net_r"]


def simulate_order(o, a, spread, pair, mode="static"):
    sell = o["side"] == "sell"
    limit = o.get("fill") == "limit"
    leg = o.get("leg", "pullback")
    rec = {c: None for c in TRADE_COLS}
    rec["pair"] = pair
    rec["order_id"] = o["id"]
    for k in _COPY:
        rec[k] = o[k]
    rec["leg"] = leg
    rec["target_mode"] = mode
    for k in _ZONE_COPY:
        rec[k] = o.get(k)
    for k in _EXTRA_CONFLUENCE_COLS:
        rec[k] = o.get(k)

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
    open_fill = False
    if limit:
        f = touch
        bar_open = float(a["o"][f])
        open_fill = (bar_open >= entry) if sell else (bar_open <= entry)
        fill = bar_open if open_fill else entry
    else:
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
    if mode == "liquidity":
        target, tkind = _liq_target(o, fill, risk, sell)
        if target is None:
            rec["status"] = "skipped_no_target"
            return rec
    else:
        rr = o.get("rr")
        rr = float(config.RR_STATIC) if rr is None else float(rr)
        target = fill - rr * risk if sell else fill + rr * risk
        tkind = "static"
    rec["target_price"] = target
    rec["target_kind"] = tkind
    rec["target_r"] = abs(target - fill) / risk
    rec["status"] = "filled"

    h = a["h"][f:]
    l = a["l"][f:]
    op = a["o"][f:]

    legacy_use_be = (
        (leg == "pullback" and sell and o["kind"] == "ob")
        or (leg == "zone" and o.get("zone_tf") == "H1")
    )

    # Evaluate Legacy baseline first
    res_leg = _eval_path(
        h, l, op, fill, stop, target, risk, sc, sell, limit, open_fill,
        legacy_use_be, float(BE_TRIGGER_R), None, 0.0
    )
    rec["r_legacy"] = res_leg["net_r"]
    rec["out_legacy"] = res_leg["outcome"]

    # Evaluate all Management Ladder presets on static target plays
    if mode == "static":
        for k, spec in MGMT_PRESETS.items():
            if k == "legacy":
                continue
            r_k = _eval_path(
                h, l, op, fill, stop, target, risk, sc, sell, limit, open_fill,
                True, spec["be_r"], spec["part_r"], spec["part_f"]
            )
            rec[f"r_{k}"] = r_k["net_r"]
            rec[f"out_{k}"] = r_k["outcome"]

        # Counterfactual Fill-1 vs Fill-2 on zone orders
        if leg == "zone":
            rec["fill1_net_r"] = _sim_zone_fill1_net_r(o, a, touch, stop, spread, sell)

        # Counterfactual unpadded stop outcome for min_risk_padded trades
        if o.get("min_risk_padded") and o.get("raw_stop") is not None:
            raw_stop = float(o["raw_stop"])
            raw_risk = abs(fill - raw_stop)
            if raw_risk > 0 and not ((sell and fill >= raw_stop) or ((not sell) and fill <= raw_stop)):
                raw_sc = float(spread) / raw_risk
                rec["unpadded_spread_ratio"] = raw_sc
                rr_val = float(config.RR_STATIC) if o.get("rr") is None else float(o.get("rr"))
                raw_target = fill - rr_val * raw_risk if sell else fill + rr_val * raw_risk
                res_unpad = _eval_path(
                    h, l, op, fill, raw_stop, raw_target, raw_risk, raw_sc, sell, limit, open_fill,
                    legacy_use_be, float(BE_TRIGGER_R), None, 0.0
                )
                rec["unpadded_net_r"] = res_unpad["net_r"]

    # Select active management mode from config.MANAGEMENT_MODE for primary outcome columns
    mgmt_mode = str(getattr(config, "MANAGEMENT_MODE", "legacy") or "legacy")
    if mode == "static" and mgmt_mode in MGMT_PRESETS and mgmt_mode != "legacy":
        spec = MGMT_PRESETS[mgmt_mode]
        active = _eval_path(
            h, l, op, fill, stop, target, risk, sc, sell, limit, open_fill,
            True, spec["be_r"], spec["part_r"], spec["part_f"]
        )
    else:
        active = res_leg

    if active["outcome"] == "open_at_cutoff":
        rec["outcome"] = "open_at_cutoff"
        return rec

    idx = active["idx"]
    exit_time = a["close_t"][f + idx]
    rec["outcome"] = active["outcome"]
    rec["exit_time"] = exit_time
    rec["exit_price"] = active["ex"]
    rec["r_gross"] = active["r_gross"]
    rec["net_r"] = active["net_r"]
    rec["dur_hours"] = (exit_time - rec["fill_time"]).total_seconds() / 3600.0
    rec["mfe_r"] = active["mfe_r"]
    rec["mae_r"] = active["mae_r"]
    return rec


def tag_trades(recs, flips):
    """open_at_entry, kept_1at (one-at-a-time per pair), flip_while_open.
    Call once per scorecard group (leg + target_mode)."""
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
    """Pullback orders: one play (static). Zone orders: two plays.
    Any other leg (for example the aggressive run): one play (static)."""
    a = prepare(m15)
    spread = config.SPREAD_PRICE[pair]
    out = []
    for o in orders:
        out.append(simulate_order(o, a, spread, pair, "static"))
        if o.get("leg") == "zone":
            out.append(simulate_order(o, a, spread, pair, "liquidity"))
    return out
