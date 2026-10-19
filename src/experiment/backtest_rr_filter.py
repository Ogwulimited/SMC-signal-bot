"""Backtest: EQ signals filtered by different Minimum R:R thresholds.

Collects all signals from the EQ detector, simulates their outcome, and 
then reports what happens if we only took the ones with R:R >= 2.0, 2.5, 3.0, etc.
"""

import bisect
import json
import os
import random
import statistics
from datetime import datetime, timezone

from ..config import (
    RECOMMENDED_PAIRS, GRANULARITY, DETECT_WINDOW, HTF_GRANULARITY,
    HTF_CANDLE_COUNT, MAX_HORIZON_BARS, SPREAD_ATR_FRAC, ATR_PERIOD,
    REPORTS_DIR,
)
from ..deriv_client import fetch_candles_paginated
from ..smc import compute_atr
from ..continuation_eq import detect_continuation_signals_eq, detect_htf_bias


BACKTEST_H1_CANDLES = 2500
WARMUP_BARS = 400
N_WINDOWS = 3
RR_THRESHOLDS = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]


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


def simulate(candles, entry, stop, target, direction, entry_bar_idx, spread):
    entry_eff, stop_eff, target_eff = _apply_spread(direction, entry, stop, target, spread)
    if not _valid_geo(direction, entry_eff, stop_eff, target_eff):
        return None
    tb = candles[entry_bar_idx]
    if direction == "bullish" and tb["low"] <= stop_eff:
        return {"outcome": "loss", "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and tb["high"] >= stop_eff:
        return {"outcome": "loss", "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, _ = _walk_exit(candles, entry_bar_idx + 1, direction, stop_eff, target_eff)
    return {"outcome": outcome, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}


def _agg(trades):
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
    return {"n": n, "wins": len(wins), "losses": len(losses),
            "timeouts": len(timeouts), "wr": wr, "expectancy": exp,
            "net_r": net_r, "avg_rr_won": avg_rr_won}


def _write_report(threshold_results, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# Experiment: Minimum R:R Filter\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Hypothesis\n")
    md.append("Filtering out low R:R trades (e.g. 1:1.5) will reduce signal count "
              "but improve Win Rate and overall Expectancy, because the bot is "
              "only taking trades with highly asymmetric payouts.\n")

    md.append("## Results by Minimum R:R\n")
    md.append("| MIN_RR | Signals | Wins | Losses | WR | Avg R:R (wins) | Expectancy | Net R |")
    md.append("|--------|---------|------|--------|-----|----------------|------------|-------|")
    for thr in RR_THRESHOLDS:
        a = threshold_results[thr]
        if a["n"] == 0:
            md.append(f"| {thr:.1f} | 0 | – | – | – | – | – | – |")
            continue
        md.append(
            f"| {thr:.1f} | {a['n']} | {a['wins']} | {a['losses']} | "
            f"{a['wr']:.1f}% | {a['avg_rr_won']:.2f} | "
            f"{a['expectancy']:+.3f} | {a['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Verdict\n")
    base = threshold_results[1.5]
    best_exp = max(RR_THRESHOLDS, key=lambda t: threshold_results[t]["expectancy"])
    best_net = max(RR_THRESHOLDS, key=lambda t: threshold_results[t]["net_r"])
    
    md.append(f"- **Baseline (1.5):** {base['n']} signals, {base['expectancy']:+.3f} R exp, {base['net_r']:+.1f} Net R.")
    md.append(f"- **Best Expectancy:** MIN_RR = {best_exp:.1f} ({threshold_results[best_exp]['expectancy']:+.3f} R).")
    md.append(f"- **Best Total Profit (Net R):** MIN_RR = {best_net:.1f} ({threshold_results[best_net]['net_r']:+.1f} Net R).")
    
    md.append("\n**Decision:** If you value per-trade quality, choose the Best Expectancy. "
              "If you value total account growth, choose the Best Net R.\n")

    with open(os.path.join(out_dir, "rr_filter_latest.md"), "w") as f:
        f.write("\n".join(md))


def main():
    random.seed(42)
    log(f"RR Filter experiment — {len(RECOMMENDED_PAIRS)} pairs")

    all_trades = []
    failed = []

    for sym_idx, sym in enumerate(RECOMMENDED_PAIRS, 1):
        log(f"[{sym_idx}/{len(RECOMMENDED_PAIRS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_H1_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception:
            failed.append(sym)
            continue
        if not h1 or not d1: continue

        d1_epochs = [c["epoch"] for c in d1]
        n = len(h1)
        span = (n - MAX_HORIZON_BARS - 3) - WARMUP_BARS
        win_size = span // N_WINDOWS

        for w in range(N_WINDOWS):
            s = WARMUP_BARS + w * win_size
            e = s + win_size if w < N_WINDOWS - 1 else (n - MAX_HORIZON_BARS - 3)
            cached_bias_epoch = None
            cached_bias = None

            for i in range(s, e):
                w_start = max(0, i + 1 - DETECT_WINDOW)
                h1_window = h1[w_start : i + 1]
                if len(h1_window) < 50: continue

                d1_end_idx = bisect.bisect_right(d1_epochs, h1_window[-1]["epoch"])
                if d1_end_idx < 20: continue
                d1_window = d1[:d1_end_idx]
                if d1_epochs[d1_end_idx - 1] != cached_bias_epoch:
                    cached_bias = detect_htf_bias(d1_window)
                    cached_bias_epoch = d1_epochs[d1_end_idx - 1]
                if cached_bias is None: continue

                atr_h1 = compute_atr(h1_window, ATR_PERIOD)
                if atr_h1 is None: continue
                spread = SPREAD_ATR_FRAC * atr_h1

                try:
                    pats = detect_continuation_signals_eq(h1_window, d1_window)
                except Exception:
                    pats = []

                for p in [p for p in pats if p.touch_index == len(h1_window) - 1]:
                    r = simulate(h1, p.entry, p.stop, p.target, p.direction, i, spread)
                    if r:
                        all_trades.append({
                            "planned_rr": p.rr,
                            "outcome": r["outcome"],
                            "rr_eff": round(r["rr"], 2)
                        })

    threshold_results = {}
    for thr in RR_THRESHOLDS:
        filtered = [t for t in all_trades if t["planned_rr"] >= thr]
        threshold_results[thr] = _agg(filtered)

    log("\n" + "=" * 70)
    log("RESULTS BY MIN RR")
    log("=" * 70)
    log(f"{'MIN_RR':8s} {'Signals':>8s} {'WR':>6s} {'AvgRR_won':>10s} {'ExpR':>8s} {'NetR':>8s}")
    for thr in RR_THRESHOLDS:
        a = threshold_results[thr]
        log(f"{thr:<8.1f} {a['n']:8d} {a['wr']:5.1f}% {a['avg_rr_won']:10.2f} {a['expectancy']:+8.3f} {a['net_r']:+8.1f}")

    if failed:
        log(f"\nFAILED SYMBOLS: {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles": BACKTEST_H1_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "n_windows": N_WINDOWS,
    }
    _write_report(threshold_results, config_snap)


if __name__ == "__main__":
    main()
