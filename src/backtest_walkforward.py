"""Walk-forward with HTF bias split.

Key output: for each entry variant, results split by
  - aligned    (LTF signal direction == HTF bias direction)
  - counter    (LTF signal direction != HTF bias direction)
  - neutral    (no HTF bias)
"""

import bisect
import csv
import json
import os
import random
from datetime import datetime, timezone

from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL,
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR, DISPLACEMENT_ATR_MULT,
    MIN_RR, MIN_SWEEP_PENETRATION_ATR, MAX_BARS_SWEEP_TO_ENTRY, MAX_OB_AGE_BARS,
    MIN_OB_WIDTH_ATR, MIN_TARGET_ATR,
    MAX_HORIZON_BARS, SPREAD_ATR_FRAC,
    MAX_WAIT_FOR_FILL_BARS, REPORTS_DIR,
    HTF_GRANULARITY, HTF_CANDLE_COUNT, HTF_SWING_LOOKBACK,
)
from .deriv_client import fetch_candles_paginated
from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    detect_sweeps, detect_order_blocks, compute_atr,
)
from .patterns import detect_patterns, detect_patterns_at_bos
from .htf_bias import compute_htf_bias_series


BACKTEST_CANDLES = 12000
WARMUP_BARS = 200
DETECT_WINDOW = 500
N_WINDOWS = 4
RANDOM_TRIALS = 500


def log(m):
    print(m, flush=True)


def _rr(direction, entry_eff, stop_eff, target_eff):
    if direction == "bullish":
        risk = entry_eff - stop_eff
        reward = target_eff - entry_eff
    else:
        risk = stop_eff - entry_eff
        reward = entry_eff - target_eff
    return reward / risk if risk > 0 else 0.0


def _walk_forward_exit(candles, start_idx, direction, stop_eff, target_eff):
    end = min(start_idx + MAX_HORIZON_BARS, len(candles))
    for k in range(start_idx, end):
        c = candles[k]
        if direction == "bullish":
            if c["low"] <= stop_eff: return "loss", k
            if c["high"] >= target_eff: return "win", k
        else:
            if c["high"] >= stop_eff: return "loss", k
            if c["low"] <= target_eff: return "win", k
    return "timeout", None


def _apply_spread(direction, entry_raw, stop, target, spread):
    half = spread / 2.0
    if direction == "bullish":
        return entry_raw + half, stop, target - half
    return entry_raw - half, stop, target + half


def _valid_geometry(direction, entry_eff, stop_eff, target_eff):
    if direction == "bullish":
        return entry_eff > stop_eff and target_eff > entry_eff
    return entry_eff < stop_eff and target_eff < entry_eff


def _wait_for_fill(candles, start_idx, direction, entry, max_wait):
    end = min(start_idx + max_wait, len(candles))
    for k in range(start_idx, end):
        c = candles[k]
        if direction == "bullish" and c["low"] <= entry:
            return k
        if direction == "bearish" and c["high"] >= entry:
            return k
    return None


def simulate_prepositioned_limit(candles, sig, spread):
    bos_idx = sig["bos_index"]
    direction = sig["direction"]
    entry = sig["entry"]
    fill_idx = _wait_for_fill(candles, bos_idx + 1, direction, entry, MAX_WAIT_FOR_FILL_BARS)
    if fill_idx is None:
        return None
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, entry, sig["stop"], sig["target"], spread)
    if not _valid_geometry(direction, entry_eff, stop_eff, target_eff):
        return None
    fill_c = candles[fill_idx]
    if direction == "bullish" and fill_c["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and fill_c["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, hit = _walk_forward_exit(candles, fill_idx + 1, direction, stop_eff, target_eff)
    bars = (hit - fill_idx) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}


def simulate_prepositioned_limit_confirmed(candles, sig, spread):
    bos_idx = sig["bos_index"]
    direction = sig["direction"]
    entry = sig["entry"]
    fill_idx = _wait_for_fill(candles, bos_idx + 1, direction, entry, MAX_WAIT_FOR_FILL_BARS)
    if fill_idx is None or fill_idx + 1 >= len(candles):
        return None
    conf = candles[fill_idx + 1]
    if direction == "bullish" and conf["close"] <= conf["open"]:
        return None
    if direction == "bearish" and conf["close"] >= conf["open"]:
        return None
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, conf["close"], sig["stop"], sig["target"], spread)
    if not _valid_geometry(direction, entry_eff, stop_eff, target_eff):
        return None
    if direction == "bullish" and conf["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and conf["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, hit = _walk_forward_exit(candles, fill_idx + 2, direction, stop_eff, target_eff)
    bars = (hit - (fill_idx + 1)) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}


VARIANTS = {
    "prepositioned_limit":           simulate_prepositioned_limit,
    "prepositioned_limit_confirmed": simulate_prepositioned_limit_confirmed,
}


def collect_signals(candles, start, end):
    bos_sigs = []
    for i in range(start, end):
        w_start = max(0, i + 1 - DETECT_WINDOW)
        window = candles[w_start : i + 1]
        atr = compute_atr(window, ATR_PERIOD)
        if atr is None:
            continue

        swings = find_swings(window, SWING_LOOKBACK)
        bos_events, choch_events, _ = detect_bos_choch(window, swings)
        pools = find_liquidity_pools(window, swings, atr, EQ_TOLERANCE_ATR)
        sweeps = detect_sweeps(window, pools, atr)
        obs = detect_order_blocks(window, bos_events, atr, DISPLACEMENT_ATR_MULT)

        for p in detect_patterns_at_bos(window, sweeps, choch_events, bos_events, obs, pools, atr):
            if p.bos.index != len(window) - 1:
                continue
            bos_sigs.append({
                "index": i,
                "bos_index": i,
                "epoch": window[-1]["epoch"],
                "direction": p.direction,
                "entry": p.entry, "stop": p.stop, "target": p.target, "atr": atr,
            })

    # dedupe by (direction, entry, target)
    seen = set()
    out = []
    for r in bos_sigs:
        key = (r["direction"], round(r["entry"], 5), round(r["target"], 5))
        if key in seen: continue
        seen.add(key)
        out.append(r)
    return out


def classify_bias(sig_direction, htf_bias):
    if htf_bias is None:
        return "neutral"
    if (sig_direction == "bullish" and htf_bias == "up") or \
       (sig_direction == "bearish" and htf_bias == "down"):
        return "aligned"
    return "counter"


def main():
    random.seed(42)
    log(f"Walk-forward with HTF bias split — {N_WINDOWS} windows")

    # Collect all signals per symbol with HTF bias assigned
    all_signals = []  # each: {symbol, window, sig dict, bias_class}

    for sym_idx, sym in enumerate(SYMBOLS, 1):
        log(f"\n[{sym_idx}/{len(SYMBOLS)}] {sym}")
        try:
            ltf = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_CANDLES)
            htf = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception as e:
            log(f"  fetch failed: {e}")
            continue
        if not ltf or not htf:
            log(f"  insufficient data")
            continue

        log(f"  LTF candles: {len(ltf)}  HTF candles: {len(htf)}")

        # Build HTF bias series
        bias_series = compute_htf_bias_series(htf, HTF_SWING_LOOKBACK)
        htf_epochs = [e for e, _ in bias_series]
        bias_lookup = {e: b for e, b in bias_series}

        def bias_at(ltf_epoch):
            if not htf_epochs:
                return None
            idx = bisect.bisect_right(htf_epochs, ltf_epoch) - 1
            if idx < 0:
                return None
            return bias_lookup.get(htf_epochs[idx], None)

        n = len(ltf)
        usable_start = WARMUP_BARS + DETECT_WINDOW
        usable_end = n - MAX_HORIZON_BARS - 3
        span = usable_end - usable_start
        win_size = span // N_WINDOWS

        for w in range(N_WINDOWS):
            s = usable_start + w * win_size
            e = s + win_size if w < N_WINDOWS - 1 else usable_end
            sigs = collect_signals(ltf, s, e)
            for sig in sigs:
                sig["symbol"] = sym
                sig["candles_ref"] = ltf
                sig["window"] = w + 1
                sig["htf_bias"] = bias_at(sig["epoch"])
                sig["bias_class"] = classify_bias(sig["direction"], sig["htf_bias"])
            all_signals.extend(sigs)
            n_aligned = sum(1 for x in sigs if x["bias_class"] == "aligned")
            n_counter = sum(1 for x in sigs if x["bias_class"] == "counter")
            n_neutral = sum(1 for x in sigs if x["bias_class"] == "neutral")
            log(f"  W{w+1}: total={len(sigs)} aligned={n_aligned} counter={n_counter} neutral={n_neutral}")

    log(f"\nTotal signals collected: {len(all_signals)}")

    # Simulate each signal for each variant, tag outcome
    all_trades = {v: [] for v in VARIANTS}

    for sig in all_signals:
        candles = sig["candles_ref"]
        spread = SPREAD_ATR_FRAC * sig["atr"]
        for vname, vfn in VARIANTS.items():
            r = vfn(candles, sig, spread)
            if r is None:
                continue
            all_trades[vname].append({
                "window": sig["window"],
                "symbol": sig["symbol"],
                "bar_index": sig["index"],
                "direction": sig["direction"],
                "entry": round(sig["entry"], 5),
                "stop": round(sig["stop"], 5),
                "target": round(sig["target"], 5),
                "outcome": r["outcome"],
                "bars_held": r["bars"],
                "rr_eff": round(r["rr_eff"], 2),
                "htf_bias": sig["htf_bias"] or "none",
                "bias_class": sig["bias_class"],
            })

    # Aggregate
    def aggregate(trades_subset):
        wins = sum(1 for t in trades_subset if t["outcome"] == "win")
        losses = sum(1 for t in trades_subset if t["outcome"] == "loss")
        timeouts = sum(1 for t in trades_subset if t["outcome"] == "timeout")
        r_won = sum(t["rr_eff"] for t in trades_subset if t["outcome"] == "win")
        net_r = r_won - losses
        resolved = wins + losses
        wr = (wins / resolved * 100) if resolved > 0 else 0
        n = wins + losses + timeouts
        exp = net_r / n if n else 0
        return {"n": n, "wins": wins, "losses": losses, "timeouts": timeouts,
                "wr": wr, "expectancy": exp, "net_r": net_r}

    log("\n" + "=" * 70)
    log("AGGREGATE BY BIAS CLASS")
    log("=" * 70)
    agg_table = {}
    for vname in VARIANTS:
        trades = all_trades[vname]
        log(f"\n{vname}  (total = {len(trades)})")
        agg_table[vname] = {}
        for cls in ["aligned", "counter", "neutral", "ALL"]:
            subset = trades if cls == "ALL" else [t for t in trades if t["bias_class"] == cls]
            a = aggregate(subset)
            agg_table[vname][cls] = a
            log(f"  {cls:8s} n={a['n']:5d}  W{a['wins']}/L{a['losses']}/T{a['timeouts']}  "
                f"WR={a['wr']:5.1f}%  exp={a['expectancy']:+.3f}R  netR={a['net_r']:+.1f}")

    # Report
    os.makedirs(REPORTS_DIR, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# SMC Signal Bot — Walk-Forward with HTF Bias Split\n")
    md.append(f"**Generated:** {generated}\n")
    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    md.append(f"| timeframe | {TIMEFRAME_LABEL} |")
    md.append(f"| symbols_count | {len(SYMBOLS)} |")
    md.append(f"| htf_granularity_sec | {HTF_GRANULARITY} |")
    md.append(f"| htf_swing_lookback | {HTF_SWING_LOOKBACK} |")
    md.append(f"| max_wait_for_fill_bars | {MAX_WAIT_FOR_FILL_BARS} |")
    md.append(f"| min_fvg_atr | 0.0 (disabled) |")
    md.append("")

    md.append("## Aggregate by HTF Bias Class\n")
    md.append("`aligned` = LTF signal direction matches HTF trend  |  `counter` = opposite  |  `neutral` = no HTF trend\n")
    md.append("| Variant | Class | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |")
    md.append("|---------|-------|---------|------|--------|----------|-----|------------|-------|")
    for vname in VARIANTS:
        for cls in ["aligned", "counter", "neutral", "ALL"]:
            a = agg_table[vname][cls]
            md.append(
                f"| {vname} | {cls} | {a['n']} | {a['wins']} | {a['losses']} | {a['timeouts']} | "
                f"{a['wr']:.1f}% | {a['expectancy']:+.3f} | {a['net_r']:+.1f} |"
            )

    with open(os.path.join(REPORTS_DIR, "walkforward_htf_latest.md"), "w") as f:
        f.write("\n".join(md))

    # Trades CSV
    with open(os.path.join(REPORTS_DIR, "walkforward_htf_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "variant", "window", "symbol", "bar_index", "direction",
            "entry", "stop", "target", "outcome", "bars_held", "rr_eff",
            "htf_bias", "bias_class",
        ])
        writer.writeheader()
        for vname, trades in all_trades.items():
            for t in trades:
                row = {"variant": vname}
                row.update(t)
                writer.writerow(row)

    log(f"\nReports written to {REPORTS_DIR}/")
    log("\nKey question: does 'aligned' have positive expectancy while 'counter' is negative?")
    log("If yes → real HTF-conditioned edge. If both bad → pattern has no edge at M15.")


if __name__ == "__main__":
    main()
