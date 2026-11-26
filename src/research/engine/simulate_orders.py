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
  * Management Ladder (Phase 1):
      - "legacy"   : Asymmetric BE at +2.0R (only PB OB Sell & H1 Zone)
      - "be_10"    : Symmetric BE at +1.0R across all Zone & Pullback trades
      - "be_15"    : Symmetric BE at +1.5R across all Zone & Pullback trades
      - "be_20"    : Symmetric BE at +2.0R across all Zone & Pullback trades
      - "be10_p20" : Symmetric BE at +1.0R + 50% Partial at +2.0R, 50% runner to 3.0R
      - "p15_be"   : 50% Partial at +1.5R + BE at +1.5R, 50% runner to 3.0R
      - "be15_p20" : Symmetric BE at +1.5R + 50% Partial at +2.0R, 50% runner to 3.0R
    All ladder presets and +-25% trigger perturbations are also evaluated in
    parallel on every filled static trade for paired bootstrap A/B comparison.
"""
import numpy as np
import pandas as pd
from src import config

STEP = pd.Timedelta(minutes=15)
FAR = pd.Timestamp("2262-01-01", tz="UTC")
LIQ_MIN_R = 3.0
BE_TRIGGER_R = 2.0

MGMT_PRESETS = {
    "legacy":   {"sym": False, "be": 2.0,   "part_r": None,  "part_f": 0.0},
    "be_10":    {"sym": True,  "be": 1.0,   "part_r": None,  "part_f": 0.0},
    "be_15":    {"sym": True,  "be": 1.5,   "part_r": None,  "part_f": 0.0},
    "be_20":    {"sym": True,  "be": 2.0,   "part_r": None,  "part_f": 0.0},
    "be10_p20": {"sym": True,  "be": 1.0,   "part_r": 2.0,   "part_f": 0.5},
    "p15_be":   {"sym": True,  "be": 1.5,   "part_r": 1.5,   "part_f": 0.5},
    "be15_p20": {"sym": True,  "be": 1.5,   "part_r": 2.0,   "part_f": 0.5},
    # +-25% perturbation sensitivity presets
    "be_075":   {"sym": True,  "be": 0.75,  "part_r": None,  "part_f": 0.0},
    "be_1125":  {"sym": True,  "be": 1.125, "part_r": None,  "part_f": 0.0},
    "be_125":   {"sym": True,  "be": 1.25,  "part_r": None,  "part_f": 0.0},
    "be_1875":  {"sym": True,  "be": 1.875, "part_r": None,  "part_f": 0.0},
    "p15_lo":   {"sym": True,  "be": 1.125, "part_r": 1.125, "part_f": 0.5},
    "p15_hi":   {"sym": True,  "be": 1.875, "part_r": 1.875, "part_f": 0.5},
}

TRADE_COLS = [
    "pair", "order_id", "pullback", "setup", "variant", "kind", "side",
    "placed_time", "end_time", "end_reason", "ceiling", "ceiling_locked",
    "entry", "stop", "status", "touch_time", "fill_time", "fill_price",
    "risk_r", "spread_cost_r", "target_price", "outcome", "mgmt_exit",
    "exit_time", "exit_price", "r_gross", "net_r", "dur_hours", "mfe_r", "mae_r",
    "open_at_entry", "kept_1at", "flip_while_open",
    "leg", "target_mode", "target_kind", "target_r", "bos_time",
    "zone_touch_time", "zone_tf", "zone_low", "zone_high", "choch_time",
    "choch_level", "htf_bias", "box_low", "box_high", "box_time",
    "idm_level", "idm_sweep_time",
    # Phase 1 parallel management ladder columns (paired on exact trade ID)
    "net_r_legacy", "out_legacy",
    "net_r_be_10", "out_be_10",
    "net_r_be_15", "out_be_15",
    "net_r_be_20", "out_be_20",
    "net_r_be10_p20", "out_be10_p20",
    "net_r_p15_be", "out_p15_be",
    "net_r_be15_p20", "out_be15_p20",
    "net_r_be_075", "net_r_be_1125", "net_r_be_125", "net_r_be_1875",
    "net_r_p15_lo", "net_r_p15_hi",
    "net_r_fill1",
    # Phase 2 & 3 ICT Confluence diagnostic columns
    "min_risk_padded", "raw_stop", "dest_room_r", "opp_h1_in_path",
    "deal_pct", "local_ote_pct", "fvg_overlap", "sweep_reclaim",
    "disp_body_atr", "disp_close_pct", "ny_hour", "killzone",
    "h1_refined_ok",
]

_COPY = ("pullback", "setup", "variant", "kind", "side", "placed_time", "end_time",
         "end_reason", "ceiling", "ceiling_locked", "entry", "stop")

_ZONE_COPY = (
    "bos_time", "zone_touch_time", "zone_tf", "zone_low", "zone_high",
    "choch_time", "choch_level", "htf_bias", "box_low", "box_high",
    "box_time", "idm_level", "idm_sweep_time",
    "min_risk_padded", "raw_stop", "dest_room_r", "opp_h1_in_path",
    "deal_pct", "local_ote_pct", "fvg_overlap", "sweep_reclaim",
    "disp_body_atr", "disp_close_pct", "ny_hour", "killzone",
    "h1_refined_ok",
)


def prepare(m15):
    ts = pd.DatetimeIndex(m15["timestamp"])
    return {
        "open_t": ts,
        "close_t": ts + STEP,
        "o": m15["open"].to_numpy(float),
        "h": m15["high"].to_numpy(float),
        "l": m15["low"].to_numpy(float),
    }


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
    """Evaluate a single management rule on post-fill bar arrays [f:].
    Returns (outcome, mgmt_exit, idx, exit_price, gross_r, net_r)."""
    target_r = abs(target - fill) / risk
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
    has_part = (part_trig_r is not None and float(part_frac) > 0.0)
    if has_part:
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

    # Check if BE activates before original stop or full target
    be_active = (
        use_be
        and bi is not None
        and (si is None or bi < si)
        and (ti is None or bi < ti)
        and (bi + 1 < len(h))
    )

    bsi = None
    be_gap = None
    if be_active:
        be_start = bi + 1
        if sell:
            be_stop_hit = h[be_start:] >= fill
            be_gap = op[be_start:] >= fill
        else:
            be_stop_hit = l[be_start:] <= fill
            be_gap = op[be_start:] <= fill
        bsi = (be_start + int(np.argmax(be_stop_hit))) if be_stop_hit.any() else None

    # Check if virtual partial sub-position triggers before stop / BE-stop
    part_filled = False
    if has_part and pi is not None and (si is None or pi < si):
        if bi is not None and bi < pi:
            # BE became active at bi + 1; partial at pi requires BE stop not hit in [bi+1..pi]
            if be_active and (bsi is None or pi < bsi):
                part_filled = True
        else:
            part_filled = True

    if part_filled:
        pf = float(part_frac)
        pr = float(part_trig_r)
        # Case 1: Full target is also reached in the same bar as partial (ti == pi)
        if ti is not None and ti <= pi:
            idx = ti
            ex = target
            out = "target"
            mgmt_exit = "partial_target"
            gross = pf * pr + (1.0 - pf) * target_r
            return out, mgmt_exit, idx, ex, gross, gross - sc

        # Case 2: Runner continues from pi + 1 with stop at BE (fill)
        r_start = pi + 1
        if r_start >= len(h):
            return "open_at_cutoff", "open_at_cutoff", None, None, None, None

        if sell:
            r_stop_hit = h[r_start:] >= fill
            r_gap = op[r_start:] >= fill
        else:
            r_stop_hit = l[r_start:] <= fill
            r_gap = op[r_start:] <= fill
        bsi_r = (r_start + int(np.argmax(r_stop_hit))) if r_stop_hit.any() else None

        if bsi_r is not None and (ti is None or bsi_r <= ti):
            idx = bsi_r
            if r_gap[bsi_r - r_start]:
                ex = float(op[bsi_r])
                out = "stop_gap"
            else:
                ex = fill
                out = "stop"
            runner_r = ((fill - ex) / risk) if sell else ((ex - fill) / risk)
            gross = pf * pr + (1.0 - pf) * runner_r
            mgmt_exit = "partial_be"
            return out, mgmt_exit, idx, ex, gross, gross - sc
        elif ti is not None:
            idx = ti
            ex = target
            out = "target"
            mgmt_exit = "partial_target"
            gross = pf * pr + (1.0 - pf) * target_r
            return out, mgmt_exit, idx, ex, gross, gross - sc
        else:
            return "open_at_cutoff", "open_at_cutoff", None, None, None, None

    # Standard full-position path (with or without BE)
    if be_active:
        be_start = bi + 1
        if bsi is not None and (ti is None or bsi <= ti):
            idx = bsi
            if be_gap[bsi - be_start]:
                ex = float(op[bsi])
                out = "stop_gap"
            else:
                ex = fill
                out = "stop"
            gross = ((fill - ex) / risk) if sell else ((ex - fill) / risk)
            return out, "be", idx, ex, gross, gross - sc
        elif ti is not None:
            idx = ti
            ex = target
            out = "target"
            gross = target_r
            return out, "full_target", idx, ex, gross, gross - sc
        else:
            return "open_at_cutoff", "open_at_cutoff", None, None, None, None
    else:
        if si is None and ti is None:
            return "open_at_cutoff", "open_at_cutoff", None, None, None, None
        if ti is None or (si is not None and si <= ti):
            idx = si
            if gap[si]:
                ex = float(op[si])
                out = "stop_gap"
            else:
                ex = stop
                out = "stop"
            gross = ((fill - ex) / risk) if sell else ((ex - fill) / risk)
            return out, "loss", idx, ex, gross, gross - sc
        else:
            idx = ti
            ex = target
            out = "target"
            gross = target_r
            return out, "full_target", idx, ex, gross, gross - sc


def _sim_zone_fill1_net_r(o, a, touch, spread, sell, entry, stop, preset):
    """Simulate a zone order as if it filled in-bar (Fill-1 limit) for stress testing."""
    f = touch
    bar_open = float(a["o"][f])
    open_fill = (bar_open >= entry) if sell else (bar_open <= entry)
    fill = bar_open if open_fill else entry
    if (sell and fill >= stop) or ((not sell) and fill <= stop):
        return np.nan
    risk = abs(fill - stop)
    sc = float(spread) / risk
    if sc > float(config.MAX_SPREAD_RISK_RATIO):
        return np.nan
    rr = o.get("rr")
    rr = float(config.RR_STATIC) if rr is None else float(rr)
    target = fill - rr * risk if sell else fill + rr * risk
    h = a["h"][f:]
    l = a["l"][f:]
    op = a["o"][f:]
    use_be = True if preset["sym"] else (o.get("zone_tf") == "H1")
    out, _, _, _, _, net_r = _eval_path(
        h, l, op, fill, stop, target, risk, sc, sell,
        limit=True, open_fill=open_fill,
        use_be=use_be, be_trig_r=preset["be"],
        part_trig_r=preset["part_r"], part_frac=preset["part_f"]
    )
    if out == "open_at_cutoff" or net_r is None:
        return np.nan
    return float(net_r)


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

    legacy_be_allowed = (
        (leg == "pullback" and sell and o["kind"] == "ob")
        or (leg == "zone" and o.get("zone_tf") == "H1")
    )

    active_mode = str(getattr(config, "MANAGEMENT_MODE", "legacy") or "legacy")
    if mode == "liquidity" or active_mode not in MGMT_PRESETS:
        active_preset = MGMT_PRESETS["legacy"]
    else:
        active_preset = MGMT_PRESETS[active_mode]

    # Evaluate all management presets in parallel on static trades
    if mode == "static":
        for p_name, p_cfg in MGMT_PRESETS.items():
            u_be = True if p_cfg["sym"] else legacy_be_allowed
            p_out, p_mexit, _, _, _, p_net = _eval_path(
                h, l, op, fill, stop, target, risk, sc, sell,
                limit, open_fill, u_be, p_cfg["be"], p_cfg["part_r"], p_cfg["part_f"]
            )
            col_net = f"net_r_{p_name}"
            col_out = f"out_{p_name}"
            if col_net in rec:
                rec[col_net] = p_net
            if col_out in rec:
                rec[col_out] = p_mexit
        if leg == "zone":
            rec["net_r_fill1"] = _sim_zone_fill1_net_r(
                o, a, touch, spread, sell, entry, stop, active_preset
            )
        else:
            rec["net_r_fill1"] = None

    use_be_main = True if active_preset["sym"] else legacy_be_allowed
    out, mgmt_exit, idx, ex, gross, net_r = _eval_path(
        h, l, op, fill, stop, target, risk, sc, sell,
        limit, open_fill, use_be_main, active_preset["be"],
        active_preset["part_r"], active_preset["part_f"]
    )
    if out == "open_at_cutoff" or idx is None:
        rec["outcome"] = "open_at_cutoff"
        rec["mgmt_exit"] = "open_at_cutoff"
        return rec

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

    exit_time = a["close_t"][f + idx]
    rec["outcome"] = out
    rec["mgmt_exit"] = mgmt_exit
    rec["exit_time"] = exit_time
    rec["exit_price"] = ex
    rec["r_gross"] = gross
    rec["net_r"] = net_r
    rec["dur_hours"] = (exit_time - rec["fill_time"]).total_seconds() / 3600.0
    rec["mfe_r"] = mfe_r
    rec["mae_r"] = mae_r
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
