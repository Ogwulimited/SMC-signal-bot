"""Backtest the SMC engine with spread + fill realism. Writes report to reports/.

Uses a rolling detection window to keep runtime manageable across many symbols.
"""

import csv
import json
import os
import sys
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


BACKTEST_CANDLES = 12000      # ~125 days of M15
WARMUP_BARS = 200
DETECT_WINDOW = 500


def log(msg):
    print(msg, flush=True)


def simulate_outcome(candles, entry_index, direction, entry, stop, target,
                     max_horizon, spread):
    half = spread / 2.0

    if direction == "bullish":
        entry_eff = entry + half
        stop_eff = stop
        target_eff = target - half
    else:
        entry_eff = entry - half
        stop_eff = stop
        target_eff = target + half

    if direction == "bullish" and (entry_eff <= stop_eff or target_eff <= entry_eff):
        return "timeout", None, None, entry_eff, stop_eff, target_eff
    if direction == "bearish" and (entry_eff >= stop_eff or target_eff >= entry_eff):
        return "timeout", None, None, entry_eff, stop_eff, target_eff

    entry_bar = candles[entry_index]
    if direction == "bullish" and entry_bar["low"] <= stop_eff:
        return "loss", entry_index, stop_eff, entry_eff, stop_eff, target_eff
    if direction == "bearish" and entry_bar["high"] >= stop_eff:
        return "loss", entry_index, stop_eff, entry_eff, stop_eff, target_eff

    end = min(entry_index + 1 + max_horizon, len(candles))
    for k in range(entry_index + 1, end):
        c = candles[k]
        if direction == "bullish":
            if c["low"] <= stop_eff:
                return "loss", k, stop_eff, entry_eff, stop_eff, target_eff
            if c["high"] >= target_eff:
                return "win", k, target_eff, entry_eff, stop_eff, target_eff
        else:
            if c["high"] >= stop_eff:
                return "loss", k, stop_eff, entry_eff, stop_eff, target_eff
            if c["low"] <= target_eff:
                return "win", k, target_eff, entry_eff, stop_eff, target_eff
    return "timeout", None, None, entry_eff, stop_eff, target_eff


def backtest_symbol(symbol, idx, total):
    log(f"\n[{idx}/{total}] === {symbol} ===")
    try:
        candles = fetch_candles_paginated(symbol, GRANULARITY, BACKTEST_CANDLES)
    except Exception as e:
        log(f"  fetch failed: {e}")
        return {"symbol": symbol, "error": str(e), "signals": [], "trades": [], "signal_count": 0}

    if not candles or len(candles) < WARMUP_BARS + 50:
        log(f"  not enough candles ({len(candles)})")
        return {"symbol": symbol, "error": "insufficient_candles", "signals": [], "trades": [], "signal_count": 0}

    n = len(candles)
    log(f"  candles: {n}")

    found = []
    log_every = 2000

    for i in range(WARMUP_BARS, n):
        if (i - WARMUP_BARS) % log_every == 0:
            log(f"  scanning bar {i}/{n}")

        start = max(0, i + 1 - DETECT_WINDOW)
        window = candles[start : i + 1]

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
                "rr": p.rr,
                "atr": atr,
            })

    log(f"  raw patterns found: {len(found)}")

    seen = set()
    unique = []
    for r in found:
        key = (r["direction"], round(r["entry"], 5), round(r["target"], 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    log(f"  unique signals: {len(unique)}")

    wins = losses = timeouts = 0
    total_r_won = 0.0
    loss_r = 0.0
    bars_to_win = []
    bars_to_loss = []
    trades = []

    for r in unique:
        spread = SPREAD_ATR_FRAC * r["atr"]
        outcome, hit_idx, hit_price, entry_eff, stop_eff, target_eff = simulate_outcome(
            candles, r["index"], r["direction"],
            r["entry"], r["stop"], r["target"],
            MAX_HORIZON_BARS, spread,
        )

        if r["direction"] == "bullish":
            risk_eff = entry_eff - stop_eff
            reward_eff = target_eff - entry_eff
        else:
            risk_eff = stop_eff - entry_eff
            reward_eff = entry_eff - target_eff
        rr_eff = reward_eff / risk_eff if risk_eff > 0 else 0

        r["outcome"] = outcome
        r["hit_index"] = hit_idx
        r["rr_eff"] = round(rr_eff, 2)

        trades.append({
            "symbol": symbol,
            "bar_index": r["index"],
            "direction": r["direction"],
            "entry": round(r["entry"], 5),
            "stop": round(r["stop"], 5),
            "target": round(r["target"], 5),
            "rr": round(r["rr"], 2),
            "rr_eff": round(rr_eff, 2),
            "outcome": outcome,
            "bars_held": (hit_idx - r["index"]) if hit_idx is not None else None,
        })

        if outcome == "win":
            wins += 1
            total_r_won += rr_eff
            if hit_idx is not None:
                bars_to_win.append(hit_idx - r["index"])
        elif outcome == "loss":
            losses += 1
            loss_r += 1.0
            if hit_idx is not None:
                bars_to_loss.append(hit_idx - r["index"])
        else:
            timeouts += 1

    resolved = wins + losses
    win_rate = (wins / resolved * 100) if resolved > 0 else 0.0

    total_signals = len(unique)
    net_r = total_r_won - loss_r
    expectancy = (net_r / total_signals) if total_signals > 0 else 0.0
    profit_factor = (total_r_won / loss_r) if loss_r > 0 else (999.0 if total_r_won > 0 else 0.0)

    first_epoch = candles[WARMUP_BARS]["epoch"]
    last_epoch = candles[-1]["epoch"]
    span_days = (last_epoch - first_epoch) / 86400
    months = span_days / 30.44 if span_days > 0 else 0

    avg_rr = sum(r["rr_eff"] for r in unique) / len(unique) if unique else 0
    avg_bars_win = sum(bars_to_win) / len(bars_to_win) if bars_to_win else 0
    avg_bars_loss = sum(bars_to_loss) / len(bars_to_loss) if bars_to_loss else 0

    result = {
        "symbol": symbol,
        "candles": len(candles),
        "signals": unique,
        "trades": trades,
        "signal_count": len(unique),
        "bullish": sum(1 for r in unique if r["direction"] == "bullish"),
        "bearish": sum(1 for r in unique if r["direction"] == "bearish"),
        "avg_rr": round(avg_rr, 2),
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate": round(win_rate, 1),
        "expectancy_r": round(expectancy, 3),
        "net_r": round(net_r, 2),
        "profit_factor": round(profit_factor, 2),
        "avg_bars_to_win": round(avg_bars_win, 1),
        "avg_bars_to_loss": round(avg_bars_loss, 1),
        "span_days": round(span_days, 2),
        "signals_per_month": round(len(unique) / months, 1) if months > 0 else 0,
        "signals_per_week": round(len(unique) / (span_days / 7), 1) if span_days > 0 else 0,
    }

    log(f"  signals: {len(unique)} (bull {result['bullish']} / bear {result['bearish']})")
    log(f"  wins: {wins}  losses: {losses}  timeouts: {timeouts}  WR: {win_rate:.1f}%")
    log(f"  expectancy: {expectancy:+.3f} R  net R: {net_r:+.2f}  PF: {result['profit_factor']}")

    return result


def _write_reports(results, config_snapshot):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    json_path = os.path.join(REPORTS_DIR, "backtest_latest.json")
    with open(json_path, "w") as f:
        json.dump({"generated": generated, "config": config_snapshot, "results": results}, f, indent=2)

    trades_csv = os.path.join(REPORTS_DIR, "backtest_trades.csv")
    with open(trades_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "symbol", "bar_index", "direction", "entry", "stop", "target",
            "rr", "rr_eff", "outcome", "bars_held",
        ])
        writer.writeheader()
        for r in results:
            for t in r.get("trades", []):
                writer.writerow(t)

    md_path = os.path.join(REPORTS_DIR, "backtest_latest.md")
    lines = []
    lines.append("# SMC Signal Bot — Backtest Report\n")
    lines.append(f"**Generated:** {generated}\n")

    lines.append("## Configuration\n")
    lines.append("| Parameter | Value |")
    lines.append("|-----------|-------|")
    for k, v in config_snapshot.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    lines.append("## Frequency & Setup Quality\n")
    lines.append("| Symbol | Candles | Signals | Bull | Bear | Avg R:R (after spread) | Span (days) | Signals/Month |")
    lines.append("|--------|---------|---------|------|------|------------------------|-------------|---------------|")
    for r in results:
        if r.get("signal_count", 0) == 0 and "error" in r:
            lines.append(f"| {r['symbol']} | – | ERROR | – | – | – | – | – |")
            continue
        lines.append(
            f"| {r['symbol']} | {r['candles']} | {r['signal_count']} | "
            f"{r['bullish']} | {r['bearish']} | 1:{r['avg_rr']} | {r['span_days']} | "
            f"{r['signals_per_month']} |"
        )
    lines.append("")

    lines.append("## Performance\n")
    lines.append("| Symbol | Wins | Losses | Timeouts | Win Rate | Expectancy (R) | Net R | Profit Factor |")
    lines.append("|--------|------|--------|----------|----------|----------------|-------|---------------|")
    for r in results:
        if r.get("signal_count", 0) == 0 and "error" in r:
            lines.append(f"| {r['symbol']} | – | – | – | – | – | – | – |")
            continue
        lines.append(
            f"| {r['symbol']} | {r['wins']} | {r['losses']} | {r['timeouts']} | "
            f"{r['win_rate']}% | {r['expectancy_r']:+.3f} | {r['net_r']:+.2f} | "
            f"{r['profit_factor']} |"
        )
    lines.append("")

    total_signals = sum(r.get("signal_count", 0) for r in results)
    total_wins = sum(r.get("wins", 0) for r in results)
    total_losses = sum(r.get("losses", 0) for r in results)
    total_timeouts = sum(r.get("timeouts", 0) for r in results)
    total_net_r = sum(r.get("net_r", 0) for r in results)
    resolved = total_wins + total_losses
    overall_wr = (total_wins / resolved * 100) if resolved > 0 else 0
    overall_exp = (total_net_r / total_signals) if total_signals > 0 else 0

    lines.append("## Aggregate (all symbols)\n")
    lines.append(f"- **Total signals:** {total_signals}")
    lines.append(f"- **Wins / Losses / Timeouts:** {total_wins} / {total_losses} / {total_timeouts}")
    lines.append(f"- **Overall win rate:** {overall_wr:.1f}%")
    lines.append(f"- **Overall expectancy:** {overall_exp:+.3f} R per signal")
    lines.append(f"- **Net R:** {total_net_r:+.2f}")
    lines.append("")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    log(f"\nReports written:\n  {json_path}\n  {trades_csv}\n  {md_path}")


def main():
    log(f"Backtest — timeframe {TIMEFRAME_LABEL}, {len(SYMBOLS)} symbols")
    log(f"Candles per symbol: {BACKTEST_CANDLES}")
    log(f"Detection window: last {DETECT_WINDOW} bars")
    log(f"Spread model: {SPREAD_ATR_FRAC} × ATR")

    config_snapshot = {
        "timeframe": TIMEFRAME_LABEL,
        "granularity_sec": GRANULARITY,
        "candles_requested": BACKTEST_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "detect_window": DETECT_WINDOW,
        "max_horizon_bars": MAX_HORIZON_BARS,
        "spread_atr_frac": SPREAD_ATR_FRAC,
        "swing_lookback": SWING_LOOKBACK,
        "atr_period": ATR_PERIOD,
        "eq_tolerance_atr": EQ_TOLERANCE_ATR,
        "displacement_atr_mult": DISPLACEMENT_ATR_MULT,
        "min_rr": MIN_RR,
        "min_sweep_penetration_atr": MIN_SWEEP_PENETRATION_ATR,
        "max_bars_sweep_to_entry": MAX_BARS_SWEEP_TO_ENTRY,
        "max_ob_age_bars": MAX_OB_AGE_BARS,
        "min_ob_width_atr": MIN_OB_WIDTH_ATR,
        "min_target_atr": MIN_TARGET_ATR,
    }

    results = []
    total = len(SYMBOLS)
    for idx, sym in enumerate(SYMBOLS, 1):
        results.append(backtest_symbol(sym, idx, total))

    _write_reports(results, config_snapshot)

    log("\n" + "=" * 40)
    log("SUMMARY")
    log("=" * 40)
    grand_total = 0
    for r in results:
        if "signal_count" in r:
            grand_total += r["signal_count"]
            if r["signal_count"] > 0:
                log(f"  {r['symbol']}: {r['signal_count']} signals, "
                    f"{r['win_rate']}% WR, {r['expectancy_r']:+.3f} R/signal")
    log(f"  TOTAL SIGNALS: {grand_total}")


if __name__ == "__main__":
    main()
