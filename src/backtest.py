"""Backtest the SMC engine. Writes a report to reports/."""

import json
import os
from datetime import datetime, timezone

from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL,
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR, DISPLACEMENT_ATR_MULT,
    MIN_RR, MIN_SWEEP_PENETRATION_ATR, MAX_BARS_SWEEP_TO_ENTRY, MAX_OB_AGE_BARS,
    MAX_HORIZON_BARS, REPORTS_DIR,
)
from .deriv_client import fetch_candles_paginated
from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    detect_sweeps, detect_order_blocks, compute_atr,
)
from .patterns import detect_patterns


BACKTEST_CANDLES = 5000
WARMUP_BARS = 100


def simulate_outcome(candles, entry_index, direction, stop, target, max_horizon):
    """Walk forward from entry_index+1. Return (outcome, hit_index, hit_price).

    outcome in {"win", "loss", "timeout"}.
    Conservative: if a candle touches both SL and TP, count as loss.
    """
    end = min(entry_index + 1 + max_horizon, len(candles))
    for k in range(entry_index + 1, end):
        c = candles[k]
        if direction == "bullish":
            if c["low"] <= stop:
                return "loss", k, stop
            if c["high"] >= target:
                return "win", k, target
        else:  # bearish
            if c["high"] >= stop:
                return "loss", k, stop
            if c["low"] <= target:
                return "win", k, target
    return "timeout", None, None


def backtest_symbol(symbol):
    print(f"\n=== {symbol} ===")
    try:
        candles = fetch_candles_paginated(symbol, GRANULARITY, BACKTEST_CANDLES)
    except Exception as e:
        print(f"  fetch failed: {e}")
        return {"symbol": symbol, "error": str(e), "signals": [], "signal_count": 0}

    if not candles or len(candles) < WARMUP_BARS + 50:
        print(f"  not enough candles ({len(candles)})")
        return {"symbol": symbol, "error": "insufficient_candles", "signals": [], "signal_count": 0}

    print(f"  candles: {len(candles)}")

    # ---- 1. Detect all patterns across history ----
    found = []
    for i in range(WARMUP_BARS, len(candles)):
        window = candles[: i + 1]
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
                "entry": round(p.entry, 5),
                "stop": round(p.stop, 5),
                "target": round(p.target, 5),
                "rr": round(p.rr, 2),
                "sweep_index": p.sweep.index,
                "ob_index": p.ob.index,
            })

    # ---- 2. Dedupe (same direction + entry + target = same signal) ----
    seen = set()
    unique = []
    for r in found:
        key = (r["direction"], r["entry"], r["target"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    # ---- 3. Simulate each unique signal forward ----
    wins = losses = timeouts = 0
    total_r_won = 0.0
    loss_r = 0.0
    bars_to_win = []
    bars_to_loss = []

    for r in unique:
        outcome, hit_idx, hit_price = simulate_outcome(
            candles, r["index"], r["direction"], r["stop"], r["target"], MAX_HORIZON_BARS
        )
        r["outcome"] = outcome
        r["hit_index"] = hit_idx
        if outcome == "win":
            wins += 1
            total_r_won += r["rr"]
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

    # Expectancy in R units, per signal (timeouts count as 0R)
    total_signals = len(unique)
    net_r = total_r_won - loss_r
    expectancy = (net_r / total_signals) if total_signals > 0 else 0.0

    # Profit factor = gross win R / gross loss R
    profit_factor = (total_r_won / loss_r) if loss_r > 0 else (float("inf") if total_r_won > 0 else 0.0)

    # ---- 4. Timing ----
    first_epoch = candles[WARMUP_BARS]["epoch"]
    last_epoch = candles[-1]["epoch"]
    span_days = (last_epoch - first_epoch) / 86400
    months = span_days / 30.44 if span_days > 0 else 0

    avg_rr_target = sum(r["rr"] for r in unique) / len(unique) if unique else 0
    avg_bars_win = sum(bars_to_win) / len(bars_to_win) if bars_to_win else 0
    avg_bars_loss = sum(bars_to_loss) / len(bars_to_loss) if bars_to_loss else 0

    result = {
        "symbol": symbol,
        "candles": len(candles),
        "signals": unique,
        "signal_count": len(unique),
        "bullish": sum(1 for r in unique if r["direction"] == "bullish"),
        "bearish": sum(1 for r in unique if r["direction"] == "bearish"),
        "avg_rr": round(avg_rr_target, 2),
        "wins": wins,
        "losses": losses,
        "timeouts": timeouts,
        "win_rate": round(win_rate, 1),
        "expectancy_r": round(expectancy, 3),
        "net_r": round(net_r, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else 999.0,
        "avg_bars_to_win": round(avg_bars_win, 1),
        "avg_bars_to_loss": round(avg_bars_loss, 1),
        "span_days": round(span_days, 2),
        "signals_per_month": round(len(unique) / months, 1) if months > 0 else 0,
        "signals_per_week": round(len(unique) / (span_days / 7), 1) if span_days > 0 else 0,
    }

    print(f"  signals: {len(unique)}  (bull {result['bullish']} / bear {result['bearish']})")
    print(f"  wins: {wins}  losses: {losses}  timeouts: {timeouts}")
    print(f"  WIN RATE: {win_rate:.1f}%  (excluding timeouts)")
    print(f"  avg R:R target: 1:{avg_rr_target:.2f}")
    print(f"  expectancy: {expectancy:+.3f} R per signal")
    print(f"  net R: {net_r:+.2f}  profit factor: {result['profit_factor']}")
    print(f"  avg bars to win: {avg_bars_win:.1f}  to loss: {avg_bars_loss:.1f}")
    print(f"  span: {span_days:.1f} days ({months:.1f} months)")
    print(f"  signals/month: {result['signals_per_month']}")

    return result


def _write_reports(results, config_snapshot):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # JSON report
    json_path = os.path.join(REPORTS_DIR, "backtest_latest.json")
    with open(json_path, "w") as f:
        json.dump({
            "generated": generated,
            "config": config_snapshot,
            "results": results,
        }, f, indent=2)

    # Markdown report
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
    lines.append("| Symbol | Candles | Signals | Bull | Bear | Avg R:R | Span (days) | Signals/Month | Signals/Week |")
    lines.append("|--------|---------|---------|------|------|---------|-------------|---------------|--------------|")
    for r in results:
        if r.get("signal_count", 0) == 0 and "error" in r:
            lines.append(f"| {r['symbol']} | – | ERROR | – | – | – | – | – | – |")
            continue
        lines.append(
            f"| {r['symbol']} | {r['candles']} | {r['signal_count']} | "
            f"{r['bullish']} | {r['bearish']} | 1:{r['avg_rr']} | {r['span_days']} | "
            f"{r['signals_per_month']} | {r['signals_per_week']} |"
        )
    lines.append("")

    lines.append("## Performance\n")
    lines.append("| Symbol | Wins | Losses | Timeouts | Win Rate | Expectancy (R) | Net R | Profit Factor | Avg Bars to Win | Avg Bars to Loss |")
    lines.append("|--------|------|--------|----------|----------|----------------|-------|---------------|-----------------|------------------|")
    for r in results:
        if r.get("signal_count", 0) == 0 and "error" in r:
            lines.append(f"| {r['symbol']} | – | – | – | – | – | – | – | – | – |")
            continue
        lines.append(
            f"| {r['symbol']} | {r['wins']} | {r['losses']} | {r['timeouts']} | "
            f"{r['win_rate']}% | {r['expectancy_r']:+.3f} | {r['net_r']:+.2f} | "
            f"{r['profit_factor']} | {r['avg_bars_to_win']} | {r['avg_bars_to_loss']} |"
        )
    lines.append("")

    # Aggregate
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
    lines.append("**Notes:**")
    lines.append("- Win rate excludes timeouts (signals that hit neither TP nor SL within the horizon).")
    lines.append("- Conservative assumption: if a single candle touches both SL and TP, it is counted as a loss.")
    lines.append(f"- Max horizon: {MAX_HORIZON_BARS} bars.")

    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nReports written:\n  {json_path}\n  {md_path}")


def main():
    print(f"Backtest — timeframe {TIMEFRAME_LABEL}, {len(SYMBOLS)} symbols")
    print(f"Requested candles per symbol: {BACKTEST_CANDLES}")
    print(f"Max horizon per signal: {MAX_HORIZON_BARS} bars\n")

    config_snapshot = {
        "timeframe": TIMEFRAME_LABEL,
        "granularity_sec": GRANULARITY,
        "candles_requested": BACKTEST_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "max_horizon_bars": MAX_HORIZON_BARS,
        "swing_lookback": SWING_LOOKBACK,
        "atr_period": ATR_PERIOD,
        "eq_tolerance_atr": EQ_TOLERANCE_ATR,
        "displacement_atr_mult": DISPLACEMENT_ATR_MULT,
        "min_rr": MIN_RR,
        "min_sweep_penetration_atr": MIN_SWEEP_PENETRATION_ATR,
        "max_bars_sweep_to_entry": MAX_BARS_SWEEP_TO_ENTRY,
        "max_ob_age_bars": MAX_OB_AGE_BARS,
    }

    results = []
    for sym in SYMBOLS:
        results.append(backtest_symbol(sym))

    _write_reports(results, config_snapshot)

    print("\n" + "=" * 40)
    print("SUMMARY")
    print("=" * 40)
    total = 0
    for r in results:
        if "signal_count" in r:
            total += r["signal_count"]
            if r["signal_count"] > 0:
                print(f"  {r['symbol']}: {r['signal_count']} signals, "
                      f"{r['win_rate']}% WR, {r['expectancy_r']:+.3f} R/signal")
    print(f"  TOTAL: {total}")


if __name__ == "__main__":
    main()
