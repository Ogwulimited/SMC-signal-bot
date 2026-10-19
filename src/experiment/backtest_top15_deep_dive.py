"""Deep Dive: Top 15 pairs over 6000 H1 candles.

Confirms if the top performers from the 32-pair test hold their edge
across a longer timeframe and checks consistency across 4 windows.
"""

import bisect
import os
import random
from datetime import datetime, timezone

from ..config import (
    GRANULARITY, DETECT_WINDOW, HTF_GRANULARITY, HTF_CANDLE_COUNT,
    MAX_HORIZON_BARS, SPREAD_ATR_FRAC, ATR_PERIOD, REPORTS_DIR
)
from ..deriv_client import fetch_candles_paginated
from ..smc import compute_atr
from ..continuation_eq import detect_continuation_signals_eq, detect_htf_bias

# Top 15 from the 32-pair test
TOP_15_PAIRS = [
    "frxNZDCHF", "frxNZDUSD", "frxEURUSD", "frxUSDSEK", "frxAUDNZD",
    "frxGBPJPY", "frxAUDJPY", "frxEURCAD", "frxGBPCHF", "frxGBPCAD",
    "frxGBPAUD", "frxUSDCHF", "frxUSDJPY", "frxNZDJPY", "frxCADJPY"
]

BACKTEST_H1_CANDLES = 6000
WARMUP_BARS = 500
N_WINDOWS = 4


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
        return {"n": 0, "wins": 0, "losses": 0, "wr": 0, "expectancy": 0, "net_r": 0}
    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    net_r = sum(t["rr_eff"] for t in wins) - len(losses)
    resolved = len(wins) + len(losses)
    wr = (len(wins) / resolved * 100) if resolved > 0 else 0
    exp = net_r / len(trades) if trades else 0
    return {"n": len(trades), "wins": len(wins), "losses": len(losses), "wr": wr, "expectancy": exp, "net_r": net_r}


def _write_report(results, window_breakdown, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# Deep Dive: Top 15 Pairs (6,000 Candles)\n")
    md.append(f"**Generated:** {gen}\n")
    
    md.append("## Overall Results (Ranked by Expectancy)\n")
    md.append("| Symbol | Signals | Wins | Losses | WR | Expectancy | Net R |")
    md.append("|--------|---------|------|--------|-----|------------|-------|")
    for r in results:
        if r["n"] == 0:
            md.append(f"| {r['symbol']} | 0 | – | – | – | – | – |")
        else:
            md.append(f"| {r['symbol']} | {r['n']} | {r['wins']} | {r['losses']} | {r['wr']:.1f}% | {r['expectancy']:+.3f} | {r['net_r']:+.1f} |")

    md.append("\n## Per-Window Breakdown (Consistency Check)\n")
    md.append("| Pair | W1 Exp | W2 Exp | W3 Exp | W4 Exp |")
    md.append("|------|--------|--------|--------|--------|")
    for sym in TOP_15_PAIRS:
        w_data = window_breakdown[sym]
        md.append(f"| {sym} | {w_data[1]:+.2f} | {w_data[2]:+.2f} | {w_data[3]:+.2f} | {w_data[4]:+.2f} |")

    with open(os.path.join(out_dir, "top15_deep_dive_latest.md"), "w") as f:
        f.write("\n".join(md))


def main():
    random.seed(42)
    log(f"Deep Dive — testing Top 15 over {BACKTEST_H1_CANDLES} candles")

    per_symbol_trades = {sym: [] for sym in TOP_15_PAIRS}
    per_window_trades = {sym: {w: [] for w in range(1, N_WINDOWS + 1)} for sym in TOP_15_PAIRS}
    failed_fetch = []

    for sym_idx, sym in enumerate(TOP_15_PAIRS, 1):
        log(f"[{sym_idx}/{len(TOP_15_PAIRS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_H1_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception:
            failed_fetch.append(sym)
            continue
        
        if not h1 or not d1: 
            failed_fetch.append(sym)
            continue

        log(f"  H1: {len(h1)}")
        d1_epochs = [c["epoch"] for c in d1]
        n = len(h1)
        
        # Ensure we have enough data for 4 windows
        usable_end = n - MAX_HORIZON_BARS - 3
        if usable_end <= WARMUP_BARS + (N_WINDOWS * 100):
            log(f"  Not enough data for 4 windows. Skipping.")
            failed_fetch.append(sym)
            continue

        span = usable_end - WARMUP_BARS
        win_size = span // N_WINDOWS

        for w in range(N_WINDOWS):
            s = WARMUP_BARS + w * win_size
            e = s + win_size if w < N_WINDOWS - 1 else usable_end
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
                        trade = {"outcome": r["outcome"], "rr_eff": round(r["rr"], 2)}
                        per_symbol_trades[sym].append(trade)
                        per_window_trades[sym][w+1].append(trade)

    # Aggregate
    results = []
    window_breakdown = {}
    
    for sym in TOP_15_PAIRS:
        agg = _agg(per_symbol_trades[sym])
        agg["symbol"] = sym
        results.append(agg)
        
        w_exp = {}
        for w in range(1, N_WINDOWS + 1):
            w_agg = _agg(per_window_trades[sym][w])
            w_exp[w] = w_agg["expectancy"]
        window_breakdown[sym] = w_exp

    results.sort(key=lambda x: x["expectancy"], reverse=True)

    log("\n" + "=" * 70)
    log("DEEP DIVE RESULTS (RANKED)")
    log("=" * 70)
    log(f"{'Symbol':12s} {'Signals':>8s} {'WR':>6s} {'ExpR':>8s} {'NetR':>8s}")
    for r in results:
        if r["n"] == 0:
            log(f"{r['symbol']:12s}        0      -        -        -")
            continue
        log(f"{r['symbol']:12s} {r['n']:8d} {r['wr']:5.1f}% {r['expectancy']:+8.3f} {r['net_r']:+8.1f}")

    if failed_fetch:
        log(f"\nFAILED TO FETCH: {', '.join(failed_fetch)}")

    config_snap = {
        "pairs_tested": len(TOP_15_PAIRS),
        "candles": BACKTEST_H1_CANDLES,
        "windows": N_WINDOWS,
    }
    _write_report(results, window_breakdown, config_snap)


if __name__ == "__main__":
    main()
