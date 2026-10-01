"""Backtest the SMC engine. Writes a report to reports/."""

import json
import os
from datetime import datetime, timezone

from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL,
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR, DISPLACEMENT_ATR_MULT,
    MIN_RR, MIN_SWEEP_PENETRATION_ATR, MAX_BARS_SWEEP_TO_ENTRY, MAX_OB_AGE_BARS,
    REPORTS_DIR,
)
from .deriv_client import fetch_candles_paginated
from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    detect_sweeps, detect_order_blocks, compute_atr,
)
from .patterns import detect_patterns


BACKTEST_CANDLES = 5000
WARMUP_BARS = 100


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

    # Dedupe: same direction + same entry + same target = same signal
    seen = set()
    unique = []
    for r in found:
        key = (r["direction"], r["entry"], r["target"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    bullish = sum(1 for r in unique if r["direction"] == "bullish")
    bearish = len(unique) - bullish

    first_epoch = candles[WARMUP_BARS]["epoch"]
    last_epoch = candles[-1]["epoch"]
    span_days = (last_epoch - first_epoch) / 86400
    months = span_days / 30.44 if span_days > 0 else 0

    avg_rr = sum(r["rr"] for r in unique) / len(unique) if unique else 0

    result = {
        "symbol": symbol,
        "candles": len(candles),
        "signals": unique,
        "signal_count": len(unique),
        "bullish": bullish,
        "bearish": bearish,
        "avg_rr": round(avg_rr, 2),
        "span_days": round(span_days, 2),
        "signals_per_month": round(len(unique) / months, 1) if months > 0 else 0,
        "signals_per_week": round(len(unique) / (span_days / 7), 1) if span_days > 0 else 0,
    }

    print(f"  unique signals: {len(unique)}")
    print(f"  bullish: {bullish}  bearish: {bearish}")
    print(f"  avg structural R:R: 1:{avg_rr:.2f}")
    print(f"  span: {span_days:.1f} days ({months:.1f} months)")
    print(f"  signals/month: {result['signals_per_month']}")
    print(f"  signals/week:  {result['signals_per_week']}")

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
    lines.append("## Results\n")
    lines.append("| Symbol | Candles | Signals | Bull | Bear | Avg R:R | Span (days) | Signals/Month | Signals/Week |")
    lines.append("|--------|---------|---------|------|------|---------|-------------|---------------|--------------|")
    total_signals = 0
    for r in results:
        if r.get("signal_count", 0) == 0 and "error" in r:
            lines.append(f"| {r['symbol']} | – | ERROR: {r.get('error','?')} | – | – | – | – | – | – |")
            continue
        total_signals += r["signal_count"]
        lines.append(
            f"| {r['symbol']} | {r['candles']} | {r['signal_count']} | "
            f"{r['bullish']} | {r['bearish']} | 1:{r['avg_rr']} | {r['span_days']} | "
            f"{r['signals_per_month']} | {r['signals_per_week']} |"
        )
    lines.append("")
    lines.append(f"**Total unique signals across all symbols:** {total_signals}\n")
    with open(md_path, "w") as f:
        f.write("\n".join(lines))

    print(f"\nReports written:\n  {json_path}\n  {md_path}")


def main():
    print(f"Backtest — timeframe {TIMEFRAME_LABEL}, {len(SYMBOLS)} symbols")
    print(f"Requested candles per symbol: {BACKTEST_CANDLES}\n")

    config_snapshot = {
        "timeframe": TIMEFRAME_LABEL,
        "granularity_sec": GRANULARITY,
        "candles_requested": BACKTEST_CANDLES,
        "warmup_bars": WARMUP_BARS,
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
            print(f"  {r['symbol']}: {r['signal_count']} signals")
    print(f"  TOTAL: {total}")


if __name__ == "__main__":
    main()
