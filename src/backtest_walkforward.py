"""Walk-forward validation with entry-timing variants + fixed random baseline.

FIX: BOS signals now only emit when the BOS bar is the CURRENT bar.
This prevents the same pattern being re-detected on later bars as the
rolling window slides forward.
"""

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
)
from .deriv_client import fetch_candles_paginated
from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    detect_sweeps, detect_order_blocks, compute_atr,
)
from .patterns import detect_patterns, detect_patterns_at_bos


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


# ---------------- Variants ----------------

def simulate_same_bar(candles, sig, spread):
    idx = sig["index"]
    if idx >= len(candles): return None
    direction = sig["direction"]
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, sig["entry"], sig["stop"], sig["target"], spread)
    if not _valid_geometry(direction, entry_eff, stop_eff, target_eff):
        return None
    c = candles[idx]
    if direction == "bullish" and c["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and c["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, hit = _walk_forward_exit(candles, idx + 1, direction, stop_eff, target_eff)
    bars = (hit - idx) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}


def simulate_next_bar_open(candles, sig, spread):
    idx = sig["index"]
    if idx + 1 >= len(candles): return None
    nxt = candles[idx + 1]
    direction = sig["direction"]
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, nxt["open"], sig["stop"], sig["target"], spread)
    if not _valid_geometry(direction, entry_eff, stop_eff, target_eff):
        return None
    if direction == "bullish" and nxt["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and nxt["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, hit = _walk_forward_exit(candles, idx + 2, direction, stop_eff, target_eff)
    bars = (hit - (idx + 1)) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}


def simulate_next_bar_limit(candles, sig, spread):
    idx = sig["index"]
    if idx + 1 >= len(candles): return None
    direction = sig["direction"]
    entry = sig["entry"]
    nxt = candles[idx + 1]
    if direction == "bullish" and nxt["low"] > entry: return None
    if direction == "bearish" and nxt["high"] < entry: return None
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, entry, sig["stop"], sig["target"], spread)
    if not _valid_geometry(direction, entry_eff, stop_eff, target_eff):
        return None
    if direction == "bullish" and nxt["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and nxt["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, hit = _walk_forward_exit(candles, idx + 2, direction, stop_eff, target_eff)
    bars = (hit - (idx + 1)) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}


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
    "same_bar":                      ("retrace", simulate_same_bar),
    "next_bar_open":                 ("retrace", simulate_next_bar_open),
    "next_bar_limit":                ("retrace", simulate_next_bar_limit),
    "prepositioned_limit":           ("bos",     simulate_prepositioned_limit),
    "prepositioned_limit_confirmed": ("bos",     simulate_prepositioned_limit_confirmed),
}


# ---------------- Signal collection (FIXED: BOS fires once) ----------------

def collect_signals(candles, start, end):
    retrace_sigs = []
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

        # Retrace signals: fires when current bar touched OB
        for p in detect_patterns(window, sweeps, choch_events, bos_events, obs, pools, atr):
            retrace_sigs.append({
                "index": i, "direction": p.direction,
                "entry": p.entry, "stop": p.stop, "target": p.target, "atr": atr,
            })

        # BOS signals: ONLY emit when the BOS bar is the CURRENT bar.
        # This ensures each BOS fires exactly once.
        for p in detect_patterns_at_bos(window, sweeps, choch_events, bos_events, obs, pools, atr):
            # The BOS index inside the window must equal the last bar index
            if p.bos.index != len(window) - 1:
                continue
            bos_sigs.append({
                "index": i,
                "bos_index": i,
                "direction": p.direction,
                "entry": p.entry, "stop": p.stop, "target": p.target, "atr": atr,
            })

    return retrace_sigs, bos_sigs


# ---------------- Random baseline ----------------

def random_baseline(candles, n_trials):
    wins = losses = timeouts = 0
    r_won = 0.0
    n = len(candles)
    for _ in range(n_trials):
        i = random.randint(WARMUP_BARS + DETECT_WINDOW, n - MAX_HORIZON_BARS - 3)
        direction = random.choice(["bullish", "bearish"])
        window = candles[i - ATR_PERIOD * 2 : i]
        atr = compute_atr(window, ATR_PERIOD)
        if atr is None:
            continue
        nxt = candles[i + 1]
        entry = nxt["open"]
        stop_dist = 0.5 * atr
        target_dist = 2.0 * atr
        spread = SPREAD_ATR_FRAC * atr
        entry_eff, stop_eff, target_eff = _apply_spread(
            direction, entry,
            entry - stop_dist if direction == "bullish" else entry + stop_dist,
            entry + target_dist if direction == "bullish" else entry - target_dist,
            spread)
        if direction == "bullish" and nxt["low"] <= stop_eff:
            losses += 1
            continue
        if direction == "bearish" and nxt["high"] >= stop_eff:
            losses += 1
            continue
        outcome, _ = _walk_forward_exit(candles, i + 2, direction, stop_eff, target_eff)
        if outcome == "win":
            wins += 1
            r_won += target_dist / stop_dist
        elif outcome == "loss":
            losses += 1
        else:
            timeouts += 1
    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    net_r = r_won - losses
    return {"n": n_trials, "wins": wins, "losses": losses, "timeouts": timeouts,
            "wr": wr, "expectancy": net_r / n_trials if n_trials else 0, "net_r": net_r}


# ---------------- Report ----------------

def _write_reports(all_windows_data, aggregate, random_agg, config_snap, trades_all):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(os.path.join(REPORTS_DIR, "walkforward_latest.json"), "w") as f:
        json.dump({"generated": generated, "config": config_snap,
                   "per_window": all_windows_data, "aggregate": aggregate,
                   "random_baseline": random_agg}, f, indent=2)

    with open(os.path.join(REPORTS_DIR, "walkforward_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "variant", "window", "symbol", "bar_index", "direction",
            "entry", "stop", "target", "outcome", "bars_held", "rr_eff",
        ])
        writer.writeheader()
        for variant, trades in trades_all.items():
            for t in trades:
                row = {"variant": variant}
                row.update(t)
                writer.writerow(row)

    md = []
    md.append("# SMC Signal Bot — Walk-Forward Validation (v2)\n")
    md.append(f"**Generated:** {generated}\n")
    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Entry Variant Comparison — Per Window\n")
    md.append("| Window | Variant | Signals | Skipped | Wins | Losses | Timeouts | WR | Expectancy | Net R |")
    md.append("|--------|---------|---------|---------|------|--------|----------|-----|------------|-------|")
    for row in all_windows_data:
        md.append(
            f"| W{row['window']} | {row['variant']} | {row['n']} | {row['skipped']} | "
            f"{row['wins']} | {row['losses']} | {row['timeouts']} | "
            f"{row['wr']:.1f}% | {row['expectancy']:+.3f} | {row['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Aggregate Across All Windows\n")
    md.append("| Variant | Signals | Skipped | Wins | Losses | Timeouts | WR | Expectancy | Net R |")
    md.append("|---------|---------|---------|------|--------|----------|-----|------------|-------|")
    for vname, agg in aggregate.items():
        md.append(
            f"| {vname} | {agg['n']} | {agg['skipped']} | {agg['wins']} | {agg['losses']} | "
            f"{agg['timeouts']} | {agg['wr']:.1f}% | {agg['expectancy']:+.3f} | {agg['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Random Baseline\n")
    md.append(f"- **Signals:** {random_agg['n']}")
    md.append(f"- **Wins / Losses / Timeouts:** {random_agg['wins']} / {random_agg['losses']} / {random_agg['timeouts']}")
    md.append(f"- **Win rate:** {random_agg['wr']:.1f}%")
    md.append(f"- **Expectancy:** {random_agg['expectancy']:+.3f} R")
    md.append(f"- **Net R:** {random_agg['net_r']:+.1f}")
    md.append("")

    md.append("## Interpretation\n")
    md.append("- `same_bar`: fill on the retrace candle (fantasy benchmark, unrealistic).")
    md.append("- `next_bar_open`: fill at next candle open (chase entry).")
    md.append("- `next_bar_limit`: limit at OB mid, only next candle (chase entry).")
    md.append("- `prepositioned_limit`: signal at BOS, limit at OB mid, wait N bars (realistic SMC entry).")
    md.append("- `prepositioned_limit_confirmed`: same + require confirmation candle after fill.")
    md.append("")
    md.append("**Fixed in v2:** BOS signals only fire when the BOS bar is the current bar — no re-emission.")
    md.append("")

    with open(os.path.join(REPORTS_DIR, "walkforward_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReports written to {REPORTS_DIR}/")


# ---------------- Main ----------------

def main():
    random.seed(42)
    log(f"Walk-forward v2 — {N_WINDOWS} windows × {len(VARIANTS)} variants")

    per_window = {w: {"retrace": [], "bos": []} for w in range(1, N_WINDOWS + 1)}
    random_results = []

    for sym_idx, sym in enumerate(SYMBOLS, 1):
        log(f"\n[{sym_idx}/{len(SYMBOLS)}] {sym}")
        try:
            candles = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_CANDLES)
        except Exception as e:
            log(f"  fetch failed: {e}")
            continue
        n = len(candles)
        if n < WARMUP_BARS + DETECT_WINDOW + 500:
            log(f"  not enough candles")
            continue

        usable_start = WARMUP_BARS + DETECT_WINDOW
        usable_end = n - MAX_HORIZON_BARS - 3
        span = usable_end - usable_start
        win_size = span // N_WINDOWS

        for w in range(N_WINDOWS):
            s = usable_start + w * win_size
            e = s + win_size if w < N_WINDOWS - 1 else usable_end
            ret_sigs, bos_sigs = collect_signals(candles, s, e)
            for sig in ret_sigs:
                sig["symbol"] = sym
                sig["candles_ref"] = candles
            for sig in bos_sigs:
                sig["symbol"] = sym
                sig["candles_ref"] = candles
            per_window[w + 1]["retrace"].extend(ret_sigs)
            per_window[w + 1]["bos"].extend(bos_sigs)
            log(f"  W{w+1}: retrace={len(ret_sigs)} bos={len(bos_sigs)}")

        rnd = random_baseline(candles, RANDOM_TRIALS)
        random_results.append(rnd)

    log("\n" + "=" * 70)
    log("VARIANT COMPARISON (per window)")
    log("=" * 70)

    all_windows_data = []
    trades_all = {v: [] for v in VARIANTS}

    for w in range(1, N_WINDOWS + 1):
        sig_buckets = per_window[w]
        log(f"\nWindow {w}")
        for vname, (sig_type, vfn) in VARIANTS.items():
            sigs = sig_buckets[sig_type]
            wins = losses = timeouts = skipped = 0
            r_won = 0.0
            for sig in sigs:
                candles = sig["candles_ref"]
                spread = SPREAD_ATR_FRAC * sig["atr"]
                r = vfn(candles, sig, spread)
                if r is None:
                    skipped += 1
                    continue
                if r["outcome"] == "win":
                    wins += 1
                    r_won += r["rr_eff"]
                elif r["outcome"] == "loss":
                    losses += 1
                else:
                    timeouts += 1
                trades_all[vname].append({
                    "window": w, "symbol": sig.get("symbol", ""),
                    "bar_index": sig["index"], "direction": sig["direction"],
                    "entry": round(sig["entry"], 5), "stop": round(sig["stop"], 5),
                    "target": round(sig["target"], 5),
                    "outcome": r["outcome"], "bars_held": r["bars"],
                    "rr_eff": round(r["rr_eff"], 2),
                })

            net_r = r_won - losses
            resolved = wins + losses
            wr = (wins / resolved * 100) if resolved > 0 else 0
            n_eval = wins + losses + timeouts
            exp = net_r / n_eval if n_eval else 0

            log(f"  {vname:32s} n={n_eval:5d} skip={skipped:5d} "
                f"W{wins}/L{losses}/T{timeouts}  WR={wr:5.1f}%  exp={exp:+.3f}R")

            all_windows_data.append({
                "window": w, "variant": vname, "n": n_eval, "skipped": skipped,
                "wins": wins, "losses": losses, "timeouts": timeouts,
                "wr": wr, "expectancy": exp, "net_r": net_r,
            })

    log("\n" + "=" * 70)
    log("AGGREGATE ACROSS ALL WINDOWS")
    log("=" * 70)
    aggregate = {}
    for vname in VARIANTS:
        rows = [r for r in all_windows_data if r["variant"] == vname]
        n = sum(r["n"] for r in rows)
        skipped = sum(r["skipped"] for r in rows)
        wins = sum(r["wins"] for r in rows)
        losses = sum(r["losses"] for r in rows)
        timeouts = sum(r["timeouts"] for r in rows)
        net_r = sum(r["net_r"] for r in rows)
        resolved = wins + losses
        wr = (wins / resolved * 100) if resolved > 0 else 0
        exp = net_r / n if n else 0
        aggregate[vname] = {"n": n, "skipped": skipped, "wins": wins, "losses": losses,
                            "timeouts": timeouts, "wr": wr, "expectancy": exp, "net_r": net_r}
        log(f"  {vname:32s} n={n:5d} skip={skipped:5d} "
            f"W{wins}/L{losses}/T{timeouts}  WR={wr:5.1f}%  exp={exp:+.3f}R  netR={net_r:+.1f}")

    log("\n" + "=" * 70)
    log("RANDOM BASELINE")
    log("=" * 70)
    n = sum(r["n"] for r in random_results)
    wins = sum(r["wins"] for r in random_results)
    losses = sum(r["losses"] for r in random_results)
    timeouts = sum(r["timeouts"] for r in random_results)
    net_r = sum(r["net_r"] for r in random_results)
    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    exp = net_r / n if n else 0
    random_agg = {"n": n, "wins": wins, "losses": losses, "timeouts": timeouts,
                  "wr": wr, "expectancy": exp, "net_r": net_r}
    log(f"  n={n}  W{wins}/L{losses}/T{timeouts}  WR={wr:.1f}%  exp={exp:+.3f}R")

    config_snap = {
        "timeframe": TIMEFRAME_LABEL,
        "symbols_count": len(SYMBOLS),
        "candles_requested": BACKTEST_CANDLES,
        "n_windows": N_WINDOWS,
        "random_trials": RANDOM_TRIALS,
        "max_horizon_bars": MAX_HORIZON_BARS,
        "max_wait_for_fill_bars": MAX_WAIT_FOR_FILL_BARS,
        "spread_atr_frac": SPREAD_ATR_FRAC,
        "min_rr": MIN_RR,
        "min_ob_width_atr": MIN_OB_WIDTH_ATR,
        "min_target_atr": MIN_TARGET_ATR,
    }
    _write_reports(all_windows_data, aggregate, random_agg, config_snap, trades_all)


if __name__ == "__main__":
    main()
