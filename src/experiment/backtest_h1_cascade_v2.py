"""Backtest: H1 flexible confluence at varying MIN_RR thresholds.

Runs detection once with MIN_RR=1.5 (baseline), then evaluates
simulated outcomes at four thresholds: 1.5, 2.0, 2.5, 3.0.

This answers: does filtering out low-R:R signals improve expectancy?
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
from ..continuation import detect_continuation_signals, detect_htf_bias
from .h1_cascade import detect_h1_cascade_signals


BACKTEST_H1_CANDLES = 2500
WARMUP_BARS = 400
N_WINDOWS = 3
RR_THRESHOLDS = [1.5, 2.0, 2.5, 3.0]


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
                "wr": 0, "expectancy": 0, "net_r": 0, "avg_rr_won": 0,
                "avg_rr_all": 0}
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
    avg_rr_all = sum(t["rr_eff"] for t in trades) / n if n else 0
    return {"n": n, "wins": len(wins), "losses": len(losses),
            "timeouts": len(timeouts), "wr": wr, "expectancy": exp,
            "net_r": net_r, "avg_rr_won": avg_rr_won, "avg_rr_all": avg_rr_all}


def _write_report(threshold_results, base_agg, per_window_rows, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# Experiment: H1 Flexible Confluence at RR Thresholds\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Hypothesis\n")
    md.append("Filtering flexible-confluence signals by higher R:R thresholds "
              "will improve expectancy per trade, at the cost of fewer signals. "
              "Find the threshold that maximizes net R.\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Baseline (v1 — FVG required)\n")
    md.append(f"- Signals: {base_agg['n']}")
    md.append(f"- WR: {base_agg['wr']:.1f}%")
    md.append(f"- Expectancy: {base_agg['expectancy']:+.3f} R")
    md.append(f"- Net R: {base_agg['net_r']:+.1f}")
    md.append("")

    md.append("## Flexible Confluence at RR Thresholds\n")
    md.append("| MIN_RR | Signals | Wins | Losses | WR | Avg R:R (wins) | Expectancy | Net R |")
    md.append("|--------|---------|------|--------|-----|----------------|------------|-------|")
    for thr in RR_THRESHOLDS:
        a = threshold_results[thr]
        md.append(
            f"| {thr:.1f} | {a['n']} | {a['wins']} | {a['losses']} | "
            f"{a['wr']:.1f}% | {a['avg_rr_won']:.2f} | {a['expectancy']:+.3f} | "
            f"{a['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Per-Window — Best Threshold vs Baseline\n")
    best_thr = max(RR_THRESHOLDS, key=lambda t: threshold_results[t]["expectancy"])
    md.append(f"**Best threshold by expectancy: MIN_RR = {best_thr:.1f}**\n")
    md.append("| Window | Base n | Base WR | Base Exp | Best n | Best WR | Best Exp |")
    md.append("|--------|--------|---------|----------|--------|---------|----------|")
    for row in per_window_rows:
        md.append(
            f"| W{row['window']} | {row['base_n']} | "
            f"{row['base_wr']:.1f}% | {row['base_exp']:+.3f} | "
            f"{row['best_n']} | {row['best_wr']:.1f}% | {row['best_exp']:+.3f} |"
        )
    md.append("")

    md.append("## Verdict\n")
    best_a = threshold_results[best_thr]
    delta_exp = best_a["expectancy"] - base_agg["expectancy"]
    delta_sig = best_a["n"] - base_agg["n"]
    if best_a["wr"] >= base_agg["wr"] and delta_exp > 0.10:
        md.append(f"✅ **MIN_RR={best_thr:.1f}** improves expectancy by "
                  f"{delta_exp:+.3f} R vs baseline with WR {best_a['wr']:.1f}% "
                  f"(baseline {base_agg['wr']:.1f}%). Signals: {best_a['n']} "
                  f"({delta_sig:+d} vs baseline). **Promote candidate.**")
    elif best_a["wr"] >= base_agg["wr"] - 2 and best_a["n"] > base_agg["n"] * 3:
        md.append(f"⚖️ MIN_RR={best_thr:.1f} keeps WR near baseline "
                  f"({best_a['wr']:.1f}%) while delivering {best_a['n']} signals "
                  f"({delta_sig:+d}). Trade-off: more signals, similar quality.")
    else:
        md.append(f"❌ No threshold dominates. Best is MIN_RR={best_thr:.1f} "
                  f"with expectancy {best_a['expectancy']:+.3f} R and "
                  f"{best_a['n']} signals.")
    md.append("")

    with open(os.path.join(out_dir, "h1_cascade_v2_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/h1_cascade_v2_latest.md")


def main():
    random.seed(42)
    log(f"H1 flexible confluence RR-threshold test — {len(RECOMMENDED_PAIRS)} pairs")

    # Collect (signal, simulated outcome) tuples once
    # Then re-filter by RR at each threshold.
    all_records = []  # each: {"rr": float, "outcome": str, "rr_eff": float, "window": int}
    base_records = []
    failed = []

    for sym_idx, sym in enumerate(RECOMMENDED_PAIRS, 1):
        log(f"\n[{sym_idx}/{len(RECOMMENDED_PAIRS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_H1_CANDLES)
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

        d1_epochs = [c["epoch"] for c in d1]

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
            log(f"  W{w+1}: bars {s}..{e}")

            cached_bias_epoch = None
            cached_bias = None

            for i in range(s, e):
                w_start = max(0, i + 1 - DETECT_WINDOW)
                h1_window = h1[w_start : i + 1]
                if len(h1_window) < 50:
                    continue

                last_h1_epoch = h1_window[-1]["epoch"]
                d1_end_idx = bisect.bisect_right(d1_epochs, last_h1_epoch)
                if d1_end_idx < 20:
                    continue
                d1_window = d1[:d1_end_idx]
                latest_d1_epoch = d1_epochs[d1_end_idx - 1]
                if latest_d1_epoch != cached_bias_epoch:
                    cached_bias = detect_htf_bias(d1_window)
                    cached_bias_epoch = latest_d1_epoch
                if cached_bias is None:
                    continue

                atr_h1 = compute_atr(h1_window, ATR_PERIOD)
                if atr_h1 is None:
                    continue
                spread = SPREAD_ATR_FRAC * atr_h1

                # ---- Baseline v1 (FVG required, MIN_RR=1.5) ----
                try:
                    base_pats = detect_continuation_signals(h1_window, d1_window)
                except Exception:
                    base_pats = []
                for p in base_pats:
                    if p.touch_index != len(h1_window) - 1:
                        continue
                    r = simulate(h1, p.entry, p.stop, p.target,
                                 p.direction, i, spread)
                    if r is None:
                        continue
                    base_records.append({
                        "window": w + 1,
                        "outcome": r["outcome"],
                        "rr_eff": round(r["rr"], 2),
                    })

                # ---- Flexible confluence: collect ALL signals, tag with RR ----
                try:
                    flex_pats = detect_h1_cascade_signals(h1_window, d1_window)
                except Exception:
                    flex_pats = []

                for p in flex_pats:
                    if p.touch_index != len(h1_window) - 1:
                        continue
                    r = simulate(h1, p.entry, p.stop, p.target,
                                 p.direction, i, spread)
                    if r is None:
                        continue
                    all_records.append({
                        "window": w + 1,
                        "signal_rr": p.rr,  # from detector (nearest pool RR)
                        "outcome": r["outcome"],
                        "rr_eff": round(r["rr"], 2),
                    })

    # Aggregate baseline
    base_agg = _agg(base_records)

    # For each RR threshold: filter flexible signals by signal_rr >= threshold
    threshold_results = {}
    for thr in RR_THRESHOLDS:
        filtered = [r for r in all_records if r["signal_rr"] >= thr]
        threshold_results[thr] = _agg(filtered)

    log("\n" + "=" * 70)
    log("RESULTS")
    log("=" * 70)
    log(f"  Baseline (v1): n={base_agg['n']}  WR={base_agg['wr']:.1f}%  "
        f"exp={base_agg['expectancy']:+.3f}R  netR={base_agg['net_r']:+.1f}")
    log("")
    for thr in RR_THRESHOLDS:
        a = threshold_results[thr]
        log(f"  Flexible @ MIN_RR={thr:.1f}: n={a['n']}  WR={a['wr']:.1f}%  "
            f"avgWinR:R={a['avg_rr_won']:.2f}  exp={a['expectancy']:+.3f}R  "
            f"netR={a['net_r']:+.1f}")

    # Per-window for best threshold
    best_thr = max(RR_THRESHOLDS, key=lambda t: threshold_results[t]["expectancy"])
    log(f"\n  Best threshold: MIN_RR = {best_thr:.1f}")

    per_window_rows = []
    for w in range(1, N_WINDOWS + 1):
        base_w = [r for r in base_records if r["window"] == w]
        flex_w = [r for r in all_records
                  if r["window"] == w and r["signal_rr"] >= best_thr]
        b = _agg(base_w)
        f = _agg(flex_w)
        per_window_rows.append({
            "window": w,
            "base_n": b["n"], "base_wr": b["wr"], "base_exp": b["expectancy"],
            "best_n": f["n"], "best_wr": f["wr"], "best_exp": f["expectancy"],
        })
        log(f"  W{w}: base n={b['n']} WR={b['wr']:.1f}% exp={b['expectancy']:+.3f} | "
            f"best n={f['n']} WR={f['wr']:.1f}% exp={f['expectancy']:+.3f}")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles": BACKTEST_H1_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "n_windows": N_WINDOWS,
        "rr_thresholds_tested": RR_THRESHOLDS,
        "note": "Detection run once at MIN_RR=1.5; signals filtered post-hoc by RR.",
    }
    _write_report(threshold_results, base_agg, per_window_rows, config_snap)


if __name__ == "__main__":
    main()
