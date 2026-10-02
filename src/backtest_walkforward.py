"""Walk-forward validation with 3 entry-timing variants + fixed random baseline.

Writes a report to reports/walkforward_latest.md, .json, and .csv.

Variants:
  - same_bar:         fill on the detection bar
  - next_bar_open:    fill at the next bar's open (market order next candle)
  - next_bar_limit:   fill on next bar only if it reaches the OB mid (limit order)

Random baseline: random bar, next-bar-open entry, same stop/target geometry.
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
    MAX_HORIZON_BARS, SPREAD_ATR_FRAC, REPORTS_DIR,
)
from .deriv_client import fetch_candles_paginated
from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    detect_sweeps, detect_order_blocks, compute_atr,
)
from .patterns import detect_patterns


BACKTEST_CANDLES = 12000
WARMUP_BARS = 200
DETECT_WINDOW = 500
N_WINDOWS = 4
RANDOM_TRIALS = 500


def log(m):
    print(m, flush=True)


# ---------------- Entry variants ----------------

def _rr(direction, entry_eff, stop_eff, target_eff):
    if direction == "bullish":
        risk = entry_eff - stop_eff
        reward = target_eff - entry_eff
    else:
        risk = stop_eff - entry_eff
        reward = entry_eff - target_eff
    if risk <= 0:
        return 0.0
    return reward / risk


def _walk_forward_exit(candles, start_idx, direction, stop_eff, target_eff):
    end = min(start_idx + MAX_HORIZON_BARS, len(candles))
    for k in range(start_idx, end):
        c = candles[k]
        if direction == "bullish":
            if c["low"] <= stop_eff:
                return "loss", k
            if c["high"] >= target_eff:
                return "win", k
        else:
            if c["high"] >= stop_eff:
                return "loss", k
            if c["low"] <= target_eff:
                return "win", k
    return "timeout", None


def simulate_same_bar(candles, sig, spread):
    idx = sig["index"]
    if idx >= len(candles):
        return None
    half = spread / 2.0
    direction = sig["direction"]
    entry = sig["entry"]; stop = sig["stop"]; target = sig["target"]

    if direction == "bullish":
        entry_eff = entry + half; stop_eff = stop; target_eff = target - half
    else:
        entry_eff = entry - half; stop_eff = stop; target_eff = target + half

    if direction == "bullish" and (entry_eff <= stop_eff or target_eff <= entry_eff):
        return None
    if direction == "bearish" and (entry_eff >= stop_eff or target_eff >= entry_eff):
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
    if idx + 1 >= len(candles):
        return None
    half = spread / 2.0
    direction = sig["direction"]
    stop = sig["stop"]; target = sig["target"]
    nxt = candles[idx + 1]
    open_price = nxt["open"]

    if direction == "bullish":
        entry_eff = open_price + half; stop_eff = stop; target_eff = target - half
    else:
        entry_eff = open_price - half; stop_eff = stop; target_eff = target + half

    if direction == "bullish" and (entry_eff <= stop_eff or target_eff <= entry_eff):
        return None
    if direction == "bearish" and (entry_eff >= stop_eff or target_eff >= entry_eff):
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
    if idx + 1 >= len(candles):
        return None
    half = spread / 2.0
    direction = sig["direction"]
    entry = sig["entry"]; stop = sig["stop"]; target = sig["target"]
    nxt = candles[idx + 1]

    if direction == "bullish":
        if nxt["low"] > entry:
            return None
        entry_eff = entry + half; stop_eff = stop; target_eff = target - half
    else:
        if nxt["high"] < entry:
            return None
        entry_eff = entry - half; stop_eff = stop; target_eff = target + half

    if direction == "bullish" and (entry_eff <= stop_eff or target_eff <= entry_eff):
        return None
    if direction == "bearish" and (entry_eff >= stop_eff or target_eff >= entry_eff):
        return None

    if direction == "bullish" and nxt["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and nxt["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}

    outcome, hit = _walk_forward_exit(candles, idx + 2, direction, stop_eff, target_eff)
    bars = (hit - (idx + 1)) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr_eff": _rr(direction, entry_eff, stop_eff, target_eff)}


VARIANTS = {
    "same_bar": simulate_same_bar,
    "next_bar_open": simulate_next_bar_open,
    "next_bar_limit": simulate_next_bar_limit,
}


def stats_from_signals(candles, signals, variant_fn):
    wins = losses = timeouts = skipped = 0
    r_won = 0.0
    bars_wins = []
    bars_losses = []
    trades = []

    for sig in signals:
        spread = SPREAD_ATR_FRAC * sig["atr"]
        res = variant_fn(candles, sig, spread)
        if res is None:
            skipped += 1
            continue
        if res["outcome"] == "win":
            wins += 1
            r_won += res["rr_eff"]
            if res["bars"] is not None:
                bars_wins.append(res["bars"])
        elif res["outcome"] == "loss":
            losses += 1
            if res["bars"] is not None:
                bars_losses.append(res["bars"])
        else:
            timeouts += 1

        trades.append({
            "symbol": sig.get("symbol", ""),
            "bar_index": sig["index"],
            "direction": sig["direction"],
            "entry": round(sig["entry"], 5),
            "stop": round(sig["stop"], 5),
            "target": round(sig["target"], 5),
            "outcome": res["outcome"],
            "bars_held": res["bars"],
            "rr_eff": round(res["rr_eff"], 2),
        })

    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    net_r = r_won - losses
    n_eval = wins + losses + timeouts
    exp = net_r / n_eval if n_eval else 0
    avg_bw = sum(bars_wins) / len(bars_wins) if bars_wins else 0
    avg_bl = sum(bars_losses) / len(bars_losses) if bars_losses else 0
    return {
        "n": n_eval, "skipped": skipped,
        "wins": wins, "losses": losses, "timeouts": timeouts,
        "wr": wr, "expectancy": exp, "net_r": net_r,
        "avg_bars_win": avg_bw, "avg_bars_loss": avg_bl,
        "trades": trades,
    }


# ---------------- Signal collection ----------------

def collect_signals(candles, start, end):
    found = []
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
        patterns = detect_patterns(window, sweeps, choch_events, bos_events, obs, pools, atr)
        for p in patterns:
            found.append({
                "index": i,
                "direction": p.direction,
                "entry": p.entry,
                "stop": p.stop,
                "target": p.target,
                "atr": atr,
            })

    seen = set()
    unique = []
    for r in found:
        key = (r["direction"], round(r["entry"], 5), round(r["target"], 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


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
        half = spread / 2.0

        if direction == "bullish":
            entry_eff = entry + half
            stop_eff = entry - stop_dist
            target_eff = entry + target_dist - half
        else:
            entry_eff = entry - half
            stop_eff = entry + stop_dist
            target_eff = entry - target_dist + half

        if direction == "bullish" and nxt["low"] <= stop_eff:
            losses += 1
            continue
        if direction == "bearish" and nxt["high"] >= stop_eff:
            losses += 1
            continue

        outcome, hit = _walk_forward_exit(candles, i + 2, direction, stop_eff, target_eff)
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
    exp = net_r / n_trials if n_trials else 0
    return {"n": n_trials, "wins": wins, "losses": losses, "timeouts": timeouts,
            "wr": wr, "expectancy": exp, "net_r": net_r}


# ---------------- Report writing ----------------

def _write_reports(all_windows_data, variant_aggregate, random_agg, config_snapshot, all_trades):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # JSON
    json_path = os.path.join(REPORTS_DIR, "walkforward_latest.json")
    with open(json_path, "w") as f:
        json.dump({
            "generated": generated,
            "config": config_snapshot,
            "per_window": all_windows_data,
            "aggregate": variant_aggregate,
            "random_baseline": random_agg,
        }, f, indent=2)

    # CSV of all trades per variant
    csv_path = os.path.join(REPORTS_DIR, "walkforward_trades.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "variant", "window", "symbol", "bar_index", "direction",
            "entry", "stop", "target", "outcome", "bars_held", "rr_eff",
        ])
        writer.writeheader()
        for variant, trades in all_trades.items():
            for t in trades:
                row = {"variant": variant}
                row.update(t)
                writer.writerow(row)

    # Markdown
    md_path = os.path.join(REPORTS_DIR, "walkforward_latest.md")
    lines = []
    lines.append("# SMC Signal Bot — Walk-Forward Validation\n")
    lines.append(f"**Generated:** {generated}\n")

    lines.append("## Configuration\n")
    lines.append("| Parameter | Value |")
    lines.append("|-----------|-------|")
    for k, v in config_snapshot.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    lines.append("## Entry Variant Comparison — Per Window\n")
    lines.append("| Window | Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |")
    lines.append("|--------|---------|---------|------|--------|----------|-----|------------|-------|")
    for row in all_windows_data:
        lines.append(
            f"| W{row['window']} | {row['variant']} | {row['n']} | "
            f"{row['wins']} | {row['losses']} | {row['timeouts']} | "
            f"{row['wr']:.1f}% | {row['expectancy']:+.3f} | {row['net_r']:+.1f} |"
        )
    lines.append("")

    lines.append("## Aggregate Across All Windows\n")
    lines.append("| Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |")
    lines.append("|---------|---------|------|--------|----------|-----|------------|-------|")
    for vname, agg in variant_aggregate.items():
        lines.append(
            f"| {vname} | {agg['n']} | {agg['wins']} | {agg['losses']} | "
            f"{agg['timeouts']} | {agg['wr']:.1f}% | {agg['expectancy']:+.3f} | {agg['net_r']:+.1f} |"
        )
    lines.append("")

    lines.append("## Random Baseline\n")
    lines.append(f"- **Signals:** {random_agg['n']}")
    lines.append(f"- **Wins / Losses / Timeouts:** {random_agg['wins']} / {random_agg['losses']} / {random_agg['timeouts']}")
    lines.append(f"- **Win rate:** {random_agg['wr']:.1f}%")
    lines.append(f"- **Expectancy:** {random_agg['expectancy']:+.3f} R")
    lines.append(f"- **Net R:** {random_agg['net_r']:+.1f}")
    lines.append("")

    lines.append("## Interpretation\n")
    lines.append("- `same_bar` = fill on detection candle (best case, unrealistic)")
    lines.append("- `next_bar_open` = fill at the open of the next candle (realistic market order)")
    lines.append("- `next_bar_limit` = fill only if the next candle reaches OB mid (realistic limit order)")
    lines.append("")
    lines.append("**Decision criteria:**")
    lines.append("- If `next_bar_open` and `next_bar_limit` beat the random baseline by a clear margin AND stay positive across all 4 windows → real, tradable edge.")
    lines.append("- If they collapse to random levels → the apparent edge was entry-timing bias.")
    lines.append("- If `next_bar_limit` holds while `next_bar_open` collapses → the zones are genuinely respected; use limit-order strategy.")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    log(f"\nReports written:\n  {json_path}\n  {csv_path}\n  {md_path}")


# ---------------- Main ----------------

def main():
    random.seed(42)
    log(f"Walk-forward — {N_WINDOWS} windows × {len(VARIANTS)} entry variants")

    per_window = {w: [] for w in range(1, N_WINDOWS + 1)}
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
            log(f"  not enough candles ({n})")
            continue

        usable_start = WARMUP_BARS + DETECT_WINDOW
        usable_end = n - MAX_HORIZON_BARS - 3
        span = usable_end - usable_start
        win_size = span // N_WINDOWS

        for w in range(N_WINDOWS):
            s = usable_start + w * win_size
            e = s + win_size if w < N_WINDOWS - 1 else usable_end
            sigs = collect_signals(candles, s, e)
            for sig in sigs:
                sig["symbol"] = sym
                sig["candles_ref"] = candles
            per_window[w + 1].extend(sigs)
            log(f"  W{w+1}: {len(sigs)} signals")

        rnd = random_baseline(candles, RANDOM_TRIALS)
        random_results.append(rnd)

    # -------- Variant comparison per window --------
    log("\n" + "=" * 70)
    log("VARIANT COMPARISON (per window)")
    log("=" * 70)

    all_windows_data = []
    all_trades = {vname: [] for vname in VARIANTS}

    for w in range(1, N_WINDOWS + 1):
        sigs = per_window[w]
        log(f"\nWindow {w}: {len(sigs)} total signals across all symbols")
        for vname, vfn in VARIANTS.items():
            candles_set = {}
            for sig in sigs:
                candles_set[id(sig["candles_ref"])] = sig["candles_ref"]
            # Simulate each signal
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

                all_trades[vname].append({
                    "window": w,
                    "symbol": sig.get("symbol", ""),
                    "bar_index": sig["index"],
                    "direction": sig["direction"],
                    "entry": round(sig["entry"], 5),
                    "stop": round(sig["stop"], 5),
                    "target": round(sig["target"], 5),
                    "outcome": r["outcome"],
                    "bars_held": r["bars"],
                    "rr_eff": round(r["rr_eff"], 2),
                })

            net_r = r_won - losses
            resolved = wins + losses
            wr = (wins / resolved * 100) if resolved > 0 else 0
            n_eval = wins + losses + timeouts
            exp = net_r / n_eval if n_eval else 0

            log(f"  {vname:18s} n={n_eval:4d} skip={skipped:3d} "
                f"W{wins}/L{losses}/T{timeouts}  WR={wr:5.1f}%  "
                f"exp={exp:+.3f}R  netR={net_r:+.1f}")

            all_windows_data.append({
                "window": w, "variant": vname,
                "n": n_eval, "wins": wins, "losses": losses,
                "timeouts": timeouts, "wr": wr,
                "expectancy": exp, "net_r": net_r,
            })

    # -------- Aggregate across windows --------
    log("\n" + "=" * 70)
    log("AGGREGATE ACROSS ALL WINDOWS")
    log("=" * 70)
    variant_aggregate = {}
    for vname in VARIANTS:
        rows = [r for r in all_windows_data if r["variant"] == vname]
        n = sum(r["n"] for r in rows)
        wins = sum(r["wins"] for r in rows)
        losses = sum(r["losses"] for r in rows)
        timeouts = sum(r["timeouts"] for r in rows)
        net_r = sum(r["net_r"] for r in rows)
        resolved = wins + losses
        wr = (wins / resolved * 100) if resolved > 0 else 0
        exp = net_r / n if n else 0
        variant_aggregate[vname] = {
            "n": n, "wins": wins, "losses": losses, "timeouts": timeouts,
            "wr": wr, "expectancy": exp, "net_r": net_r,
        }
        log(f"  {vname:18s} n={n:4d}  W{wins}/L{losses}/T{timeouts}  "
            f"WR={wr:5.1f}%  exp={exp:+.3f}R  netR={net_r:+.1f}")

    # -------- Random baseline --------
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
    log(f"  n={n}  W{wins}/L{losses}/T{timeouts}  WR={wr:.1f}%  "
        f"exp={exp:+.3f}R  netR={net_r:+.1f}")

    # -------- Reports --------
    config_snapshot = {
        "timeframe": TIMEFRAME_LABEL,
        "symbols_count": len(SYMBOLS),
        "candles_requested": BACKTEST_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "detect_window": DETECT_WINDOW,
        "n_windows": N_WINDOWS,
        "random_trials": RANDOM_TRIALS,
        "max_horizon_bars": MAX_HORIZON_BARS,
        "spread_atr_frac": SPREAD_ATR_FRAC,
        "min_rr": MIN_RR,
        "min_ob_width_atr": MIN_OB_WIDTH_ATR,
        "min_target_atr": MIN_TARGET_ATR,
        "buffer_atr": 0.20,
    }
    _write_reports(all_windows_data, variant_aggregate, random_agg, config_snapshot, all_trades)

    log("\n" + "=" * 70)
    log("INTERPRETATION")
    log("=" * 70)
    log("- If next_bar_open / next_bar_limit still beats random → real edge.")
    log("- If they collapse to random-ish levels → edge was entry-timing bias.")


if __name__ == "__main__":
    main()
