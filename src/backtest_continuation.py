"""Continuation backtest v5 — per-symbol breakdown.

Same model as v4. Adds:
  - Per-symbol performance table
  - Ranking by expectancy
  - Recommended pairs list (positive expectancy + min trades)
  - Filtered aggregate (what the model looks like trading only recommended pairs)
"""

import csv
import json
import os
import random
import statistics
from datetime import datetime, timezone

from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL, DETECT_WINDOW,
    ATR_PERIOD, MAX_HORIZON_BARS, SPREAD_ATR_FRAC,
    HTF_GRANULARITY, HTF_CANDLE_COUNT,
    REPORTS_DIR,
)
from .deriv_client import fetch_candles_paginated
from .smc import compute_atr
from .continuation import detect_continuation_signals, detect_htf_bias


BACKTEST_CANDLES = 10000
WARMUP_BARS = 500
N_WINDOWS = 4
RANDOM_TRIALS = 500

MIN_TRADES_FOR_RECOMMENDATION = 8


def log(m):
    print(m, flush=True)


def _walk_exit(candles, start_idx, direction, stop_eff, target_eff):
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


def _rr(direction, entry, stop, target):
    if direction == "bullish":
        return (target - entry) / (entry - stop) if entry > stop else 0
    return (entry - target) / (stop - entry) if stop > entry else 0


def _apply_spread(direction, entry_raw, stop, target, spread):
    half = spread / 2.0
    if direction == "bullish":
        return entry_raw + half, stop, target - half
    return entry_raw - half, stop, target + half


def _valid_geo(direction, e, s, t):
    if direction == "bullish":
        return e > s and t > e
    return e < s and t < e


def simulate(candles, sig, spread):
    idx = sig["touch_index"]
    direction = sig["direction"]
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, sig["entry"], sig["stop"], sig["target"], spread)
    if not _valid_geo(direction, entry_eff, stop_eff, target_eff):
        return None
    tb = candles[idx]
    if direction == "bullish" and tb["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and tb["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, hit = _walk_exit(candles, idx + 1, direction, stop_eff, target_eff)
    bars = (hit - idx) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}


def collect_signals(h1, d1, start, end):
    sigs = []
    cached_bias_epoch = None
    cached_bias = None
    log_every = 500

    for i in range(start, end):
        if (i - start) % log_every == 0:
            log(f"    scanning bar {i}/{end}")

        w_start = max(0, i + 1 - DETECT_WINDOW)
        h1_window = h1[w_start : i + 1]
        if len(h1_window) < 50:
            continue

        d1_window = [c for c in d1 if c["epoch"] <= h1_window[-1]["epoch"]]
        if not d1_window:
            continue
        latest_d1_epoch = d1_window[-1]["epoch"]
        if latest_d1_epoch != cached_bias_epoch:
            cached_bias = detect_htf_bias(d1_window)
            cached_bias_epoch = latest_d1_epoch
        if cached_bias is None:
            continue

        try:
            pats = detect_continuation_signals(h1_window, d1_window)
        except Exception:
            continue

        for p in pats:
            abs_touch = w_start + p.touch_index
            if abs_touch != i:
                continue
            sigs.append({
                "index": abs_touch,
                "touch_index": abs_touch,
                "direction": p.direction,
                "entry": p.entry,
                "stop": p.stop,
                "target": p.target,
                "ob_index": w_start + p.ob_index,
                "target_kind": p.target_kind,
                "atr": compute_atr(h1_window, ATR_PERIOD) or 0.0,
            })

    seen = set()
    out = []
    for s in sigs:
        key = (s["direction"], round(s["entry"], 5), round(s["target"], 5))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def random_baseline(candles, n_trials):
    wins = losses = timeouts = 0
    r_won = 0.0
    n = len(candles)
    for _ in range(n_trials):
        i = random.randint(WARMUP_BARS, n - MAX_HORIZON_BARS - 3)
        direction = random.choice(["bullish", "bearish"])
        atr = compute_atr(candles[i - ATR_PERIOD * 2 : i], ATR_PERIOD)
        if atr is None:
            continue
        nxt = candles[i + 1]
        entry = nxt["open"]
        stop_dist = 0.5 * atr
        target_dist = 2.0 * atr
        spread = SPREAD_ATR_FRAC * atr
        if direction == "bullish":
            entry_eff = entry + spread / 2
            stop_eff = entry - stop_dist
            target_eff = entry + target_dist - spread / 2
        else:
            entry_eff = entry - spread / 2
            stop_eff = entry + stop_dist
            target_eff = entry - target_dist + spread / 2
        if direction == "bullish" and nxt["low"] <= stop_eff:
            losses += 1
            continue
        if direction == "bearish" and nxt["high"] >= stop_eff:
            losses += 1
            continue
        outcome, _ = _walk_exit(candles, i + 2, direction, stop_eff, target_eff)
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


def _aggregate_trades(trades):
    if not trades:
        return {"n": 0, "wins": 0, "losses": 0, "timeouts": 0,
                "wr": 0, "expectancy": 0, "net_r": 0, "avg_rr_won": 0}
    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    timeouts = [t for t in trades if t["outcome"] == "timeout"]
    r_won = sum(t["rr_eff"] for t in wins)
    net_r = r_won - len(losses)
    resolved = len(wins) + len(losses)
    wr = (len(wins) / resolved * 100) if resolved > 0 else 0
    n = len(trades)
    exp = net_r / n if n > 0 else 0
    avg_rr_won = (sum(t["rr_eff"] for t in wins) / len(wins)) if wins else 0
    return {
        "n": n, "wins": len(wins), "losses": len(losses), "timeouts": len(timeouts),
        "wr": wr, "expectancy": exp, "net_r": net_r, "avg_rr_won": avg_rr_won,
    }


def _write_report(per_window_rows, aggregate, random_agg, per_symbol,
                  recommended, filtered_agg, config_snap, trades_all):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(os.path.join(REPORTS_DIR, "continuation_latest.json"), "w") as f:
        json.dump({"generated": gen, "config": config_snap,
                   "per_window": per_window_rows, "aggregate": aggregate,
                   "per_symbol": per_symbol, "recommended": recommended,
                   "filtered_aggregate": filtered_agg,
                   "random_baseline": random_agg}, f, indent=2)

    with open(os.path.join(REPORTS_DIR, "continuation_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "window", "symbol", "touch_index", "direction",
            "entry", "stop", "target", "target_kind",
            "outcome", "bars_held", "rr_eff",
        ])
        writer.writeheader()
        for t in trades_all:
            writer.writerow(t)

    md = []
    md.append("# SMC Signal Bot — Continuation Backtest (per-symbol)\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Overall Aggregate (all 31 symbols)\n")
    md.append(f"- Signals: {aggregate['n']}")
    md.append(f"- Wins / Losses / Timeouts: {aggregate['wins']} / {aggregate['losses']} / {aggregate['timeouts']}")
    md.append(f"- Win rate: **{aggregate['wr']:.1f}%**")
    md.append(f"- Expectancy: **{aggregate['expectancy']:+.3f} R**")
    md.append(f"- Net R: {aggregate['net_r']:+.1f}")
    md.append("")

    md.append("## Per-Symbol Performance (sorted by expectancy)\n")
    md.append("| Symbol | Trades | Wins | Losses | WR | Avg R:R on Wins | Net R | Expectancy |")
    md.append("|--------|--------|------|--------|-----|-----------------|-------|------------|")
    for s in per_symbol:
        if s["n"] == 0:
            md.append(f"| {s['symbol']} | 0 | – | – | – | – | – | – |")
            continue
        md.append(
            f"| {s['symbol']} | {s['n']} | {s['wins']} | {s['losses']} | "
            f"{s['wr']:.1f}% | {s['avg_rr_won']:.2f} | {s['net_r']:+.1f} | "
            f"{s['expectancy']:+.3f} |"
        )
    md.append("")

    md.append(f"## Recommended Pairs (positive expectancy + ≥{MIN_TRADES_FOR_RECOMMENDATION} trades)\n")
    if recommended:
        md.append("| Symbol | Trades | WR | Net R | Expectancy |")
        md.append("|--------|--------|-----|-------|------------|")
        for s in recommended:
            md.append(
                f"| {s['symbol']} | {s['n']} | {s['wr']:.1f}% | "
                f"{s['net_r']:+.1f} | {s['expectancy']:+.3f} |"
            )
    else:
        md.append("_No pairs met the recommendation threshold._")
    md.append("")

    md.append("## Filtered Aggregate (recommended pairs only)\n")
    md.append(f"- Pairs: {len(recommended)}")
    md.append(f"- Signals: {filtered_agg['n']}")
    md.append(f"- Wins / Losses / Timeouts: {filtered_agg['wins']} / {filtered_agg['losses']} / {filtered_agg['timeouts']}")
    md.append(f"- Win rate: **{filtered_agg['wr']:.1f}%**")
    md.append(f"- Expectancy: **{filtered_agg['expectancy']:+.3f} R**")
    md.append(f"- Net R: {filtered_agg['net_r']:+.1f}")
    md.append("")

    md.append("## Excluded Pairs (negative or unproven)\n")
    excluded = [s for s in per_symbol
                if s["n"] > 0 and (
                    s["n"] < MIN_TRADES_FOR_RECOMMENDATION or s["expectancy"] <= 0
                )]
    if excluded:
        md.append("| Symbol | Trades | WR | Net R | Expectancy | Reason |")
        md.append("|--------|--------|-----|-------|------------|--------|")
        for s in excluded:
            if s["n"] < MIN_TRADES_FOR_RECOMMENDATION:
                reason = "too few trades"
            else:
                reason = "negative expectancy"
            md.append(
                f"| {s['symbol']} | {s['n']} | {s['wr']:.1f}% | "
                f"{s['net_r']:+.1f} | {s['expectancy']:+.3f} | {reason} |"
            )
    md.append("")

    md.append("## Random Baseline\n")
    md.append(f"- Signals: {random_agg['n']}")
    md.append(f"- WR: {random_agg['wr']:.1f}%")
    md.append(f"- Expectancy: {random_agg['expectancy']:+.3f} R")
    md.append("")

    with open(os.path.join(REPORTS_DIR, "continuation_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReports written to {REPORTS_DIR}/")


def main():
    random.seed(42)
    log(f"Continuation per-symbol analysis — {len(SYMBOLS)} symbols")

    per_window = {w: [] for w in range(1, N_WINDOWS + 1)}
    rnd_acc = []
    failed = []

    for sym_idx, sym in enumerate(SYMBOLS, 1):
        log(f"\n[{sym_idx}/{len(SYMBOLS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception as e:
            log(f"  fetch failed: {e}")
            failed.append(sym)
            continue
        if not h1 or not d1:
            log(f"  insufficient data")
            failed.append(sym)
            continue
        log(f"  H1: {len(h1)}  D1: {len(d1)}")

        n = len(h1)
        usable_start = WARMUP_BARS
        usable_end = n - MAX_HORIZON_BARS - 3
        if usable_end <= usable_start:
            failed.append(sym)
            continue
        span = usable_end - usable_start
        win_size = span // N_WINDOWS

        for w in range(N_WINDOWS):
            s = usable_start + w * win_size
            e = s + win_size if w < N_WINDOWS - 1 else usable_end
            sigs = collect_signals(h1, d1, s, e)
            for sig in sigs:
                sig["symbol"] = sym
                sig["candles_ref"] = h1
                sig["window"] = w + 1
            per_window[w + 1].extend(sigs)
            log(f"  W{w+1}: {len(sigs)} signals")

        rnd = random_baseline(h1, RANDOM_TRIALS)
        rnd_acc.append(rnd)

    # Simulate all signals, accumulate trades per symbol
    log("\nSimulating all trades...")
    all_trades = []
    for w in range(1, N_WINDOWS + 1):
        for sig in per_window[w]:
            candles = sig["candles_ref"]
            spread = SPREAD_ATR_FRAC * sig["atr"]
            r = simulate(candles, sig, spread)
            if r is None:
                continue
            all_trades.append({
                "window": w,
                "symbol": sig["symbol"],
                "touch_index": sig["touch_index"],
                "direction": sig["direction"],
                "entry": round(sig["entry"], 5),
                "stop": round(sig["stop"], 5),
                "target": round(sig["target"], 5),
                "target_kind": sig.get("target_kind", "unknown"),
                "outcome": r["outcome"],
                "bars_held": r["bars"],
                "rr_eff": round(r["rr"], 2),
            })

    # Per-window aggregates
    per_window_rows = []
    for w in range(1, N_WINDOWS + 1):
        w_trades = [t for t in all_trades if t["window"] == w]
        agg = _aggregate_trades(w_trades)
        per_window_rows.append({"window": w, **agg})
        log(f"  W{w}: n={agg['n']:4d}  W{agg['wins']}/L{agg['losses']}/T{agg['timeouts']}  "
            f"WR={agg['wr']:5.1f}%  exp={agg['expectancy']:+.3f}R")

    # Overall aggregate
    aggregate = _aggregate_trades(all_trades)
    log(f"\n  ALL: n={aggregate['n']}  W{aggregate['wins']}/L{aggregate['losses']}/T{aggregate['timeouts']}  "
        f"WR={aggregate['wr']:.1f}%  exp={aggregate['expectancy']:+.3f}R  netR={aggregate['net_r']:+.1f}")

    # Per-symbol aggregates
    per_symbol = []
    for sym in SYMBOLS:
        sym_trades = [t for t in all_trades if t["symbol"] == sym]
        agg = _aggregate_trades(sym_trades)
        per_symbol.append({"symbol": sym, **agg})
    per_symbol.sort(key=lambda x: x["expectancy"], reverse=True)

    # Recommendations
    recommended = [s for s in per_symbol
                   if s["n"] >= MIN_TRADES_FOR_RECOMMENDATION and s["expectancy"] > 0]

    # Filtered aggregate
    recommended_syms = {s["symbol"] for s in recommended}
    filtered_trades = [t for t in all_trades if t["symbol"] in recommended_syms]
    filtered_agg = _aggregate_trades(filtered_trades)

    # Random
    n = sum(r["n"] for r in rnd_acc)
    wins = sum(r["wins"] for r in rnd_acc)
    losses = sum(r["losses"] for r in rnd_acc)
    timeouts = sum(r["timeouts"] for r in rnd_acc)
    net_r = sum(r["net_r"] for r in rnd_acc)
    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    exp = net_r / n if n else 0
    rnd_agg = {"n": n, "wins": wins, "losses": losses, "timeouts": timeouts,
               "wr": wr, "expectancy": exp, "net_r": net_r}

    log("\n" + "=" * 70)
    log("PER-SYMBOL PERFORMANCE (sorted by expectancy)")
    log("=" * 70)
    log(f"{'Symbol':18s} {'N':>4s} {'W':>4s} {'L':>4s} {'WR%':>6s} {'AvgRRwon':>9s} {'NetR':>7s} {'ExpR':>8s}")
    for s in per_symbol:
        if s["n"] == 0:
            log(f"{s['symbol']:18s}    0    -    -      -         -       -        -")
            continue
        log(f"{s['symbol']:18s} {s['n']:4d} {s['wins']:4d} {s['losses']:4d} "
            f"{s['wr']:6.1f} {s['avg_rr_won']:9.2f} {s['net_r']:+7.1f} {s['expectancy']:+8.3f}")

    log("\n" + "=" * 70)
    log(f"RECOMMENDED PAIRS (positive expectancy, ≥{MIN_TRADES_FOR_RECOMMENDATION} trades)")
    log("=" * 70)
    if recommended:
        for s in recommended:
            log(f"  {s['symbol']:18s} n={s['n']:3d}  WR={s['wr']:5.1f}%  "
                f"NetR={s['net_r']:+6.1f}  Exp={s['expectancy']:+.3f}")
    else:
        log("  (none)")

    log("\n" + "=" * 70)
    log("FILTERED AGGREGATE (recommended pairs only)")
    log("=" * 70)
    log(f"  Pairs: {len(recommended)}")
    log(f"  Signals: {filtered_agg['n']}")
    log(f"  W/L/T: {filtered_agg['wins']}/{filtered_agg['losses']}/{filtered_agg['timeouts']}")
    log(f"  WR: {filtered_agg['wr']:.1f}%")
    log(f"  Expectancy: {filtered_agg['expectancy']:+.3f} R")
    log(f"  Net R: {filtered_agg['net_r']:+.1f}")

    log("\n  RANDOM: n={}  WR={:.1f}%  exp={:+.3f}R".format(
        rnd_agg["n"], rnd_agg["wr"], rnd_agg["expectancy"]))

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "symbols_count": len(SYMBOLS),
        "failed_symbols": len(failed),
        "min_trades_for_recommendation": MIN_TRADES_FOR_RECOMMENDATION,
        "detect_window": DETECT_WINDOW,
        "candles_per_symbol": BACKTEST_CANDLES,
        "max_horizon_bars": MAX_HORIZON_BARS,
    }
    _write_report(per_window_rows, aggregate, rnd_agg, per_symbol,
                  recommended, filtered_agg, config_snap, all_trades)


if __name__ == "__main__":
    main()
