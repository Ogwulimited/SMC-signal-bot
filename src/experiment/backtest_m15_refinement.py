"""Backtest: H1 continuation baseline vs M15-refined entry.

Same signals fire in both branches. The refined branch uses a smaller M15 OB
inside the H1 OB for tighter entry/stop. Falls back to H1 entry when no M15
OB is available.

Writes a comparison report to reports/experiments/m15_refinement_latest.md
"""

import csv
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
from .m15_refinement import refine_to_m15


M15_GRANULARITY = 900
BACKTEST_H1_CANDLES = 6000
BACKTEST_M15_CANDLES = 24000
WARMUP_BARS = 500
N_WINDOWS = 4


def log(m):
    print(m, flush=True)


# ---------------- simulation helpers ----------------

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
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and tb["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, hit = _walk_exit(candles, entry_bar_idx + 1, direction, stop_eff, target_eff)
    bars = (hit - entry_bar_idx) if hit is not None else None
    return {"outcome": outcome, "bars": bars,
            "rr": _rr(direction, entry_eff, stop_eff, target_eff)}


# ---------------- signal collection with refinement ----------------

def collect_signals(h1, d1, m15, start, end):
    """Returns list of dicts with both baseline and refined trade plans."""
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

        # M15 window for refinement lookup
        m15_window = [c for c in m15 if c["epoch"] <= h1_window[-1]["epoch"]]
        m15_atr = compute_atr(m15_window[-200:], ATR_PERIOD) if len(m15_window) >= 50 else None

        for p in pats:
            abs_touch = w_start + p.touch_index
            if abs_touch != i:
                continue

            # Baseline H1 trade plan
            sig = {
                "index": abs_touch,
                "touch_index": abs_touch,
                "direction": p.direction,
                "h1_entry": p.entry,
                "h1_stop": p.stop,
                "h1_target": p.target,
                "h1_rr": p.rr,
                "target_kind": p.target_kind,
                "atr_h1": compute_atr(h1_window, ATR_PERIOD) or 0.0,
                "refined": None,
            }

            # Try M15 refinement
            if m15_atr is not None:
                # Pass H1 pattern with absolute indices
                # p.ob_index / p.bos_index are relative to h1_window; convert
                class AbsPattern:
                    pass
                abs_p = AbsPattern()
                abs_p.ob_index = w_start + p.ob_index
                abs_p.bos_index = w_start + p.bos_index
                abs_p.ob_high = p.ob_high
                abs_p.ob_low = p.ob_low
                abs_p.direction = p.direction
                abs_p.target = p.target

                try:
                    refined = refine_to_m15(abs_p, h1, m15_window, m15_atr)
                except Exception:
                    refined = None
                if refined is not None:
                    sig["refined"] = refined

            sigs.append(sig)

    # dedupe by (direction, h1_entry, h1_target)
    seen = set()
    out = []
    for s in sigs:
        key = (s["direction"], round(s["h1_entry"], 5), round(s["h1_target"], 5))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


# ---------------- aggregate ----------------

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


def _rr_stats(trades):
    if not trades:
        return {}
    rrs = sorted(t["rr_eff"] for t in trades)
    n = len(rrs)

    def pct(p):
        idx = max(0, min(n - 1, int(p * (n - 1))))
        return rrs[idx]

    return {
        "n": n,
        "min": rrs[0],
        "p25": pct(0.25),
        "median": statistics.median(rrs),
        "p75": pct(0.75),
        "max": rrs[-1],
        "mean": sum(rrs) / n,
    }


def _write_report(baseline_agg, refined_agg, refined_only_agg,
                   baseline_rr, refined_rr, fallback_count, refined_count,
                   per_window_rows, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(os.path.join(out_dir, "m15_refinement_latest.json"), "w") as f:
        json.dump({
            "generated": gen,
            "config": config_snap,
            "baseline_agg": baseline_agg,
            "refined_agg": refined_agg,
            "refined_only_agg": refined_only_agg,
            "baseline_rr": baseline_rr,
            "refined_rr": refined_rr,
            "fallback_count": fallback_count,
            "refined_count": refined_count,
            "per_window": per_window_rows,
        }, f, indent=2)

    md = []
    md.append("# Experiment: M15 OB Refinement\n")
    md.append(f"**Generated:** {gen}\n")

    md.append("## Hypothesis\n")
    md.append("Refining H1 OBs to a tighter M15 OB inside the same zone will improve "
              "R:R (tighter stop, same target) without reducing the signal count.\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Overall Comparison\n")
    md.append("| Metric | Baseline (H1 entry) | Refined (M15 or fallback) | M15-only (refined cases) |")
    md.append("|--------|---------------------|---------------------------|---------------------------|")
    for label, agg in [("Signals", None)]:
        pass
    md.append(f"| Signals | {baseline_agg['n']} | {refined_agg['n']} | {refined_only_agg['n']} |")
    md.append(f"| Wins | {baseline_agg['wins']} | {refined_agg['wins']} | {refined_only_agg['wins']} |")
    md.append(f"| Losses | {baseline_agg['losses']} | {refined_agg['losses']} | {refined_only_agg['losses']} |")
    md.append(f"| Timeouts | {baseline_agg['timeouts']} | {refined_agg['timeouts']} | {refined_only_agg['timeouts']} |")
    md.append(f"| **Win rate** | **{baseline_agg['wr']:.1f}%** | **{refined_agg['wr']:.1f}%** | **{refined_only_agg['wr']:.1f}%** |")
    md.append(f"| Avg R:R (all) | {baseline_agg['avg_rr_all']:.2f} | {refined_agg['avg_rr_all']:.2f} | {refined_only_agg['avg_rr_all']:.2f} |")
    md.append(f"| Avg R:R (wins) | {baseline_agg['avg_rr_won']:.2f} | {refined_agg['avg_rr_won']:.2f} | {refined_only_agg['avg_rr_won']:.2f} |")
    md.append(f"| **Expectancy** | **{baseline_agg['expectancy']:+.3f} R** | **{refined_agg['expectancy']:+.3f} R** | **{refined_only_agg['expectancy']:+.3f} R** |")
    md.append(f"| Net R | {baseline_agg['net_r']:+.1f} | {refined_agg['net_r']:+.1f} | {refined_only_agg['net_r']:+.1f} |")
    md.append("")

    md.append("## Refinement Coverage\n")
    md.append(f"- Signals where M15 OB found (refined): **{refined_count}**")
    md.append(f"- Signals with no M15 OB (fallback to H1): **{fallback_count}**")
    total = refined_count + fallback_count
    if total > 0:
        md.append(f"- Refinement rate: **{refined_count / total * 100:.1f}%**")
    md.append("")

    md.append("## R:R Distribution\n")
    md.append("| Metric | Baseline | Refined (all) |")
    md.append("|--------|----------|---------------|")
    for key in ["min", "p25", "median", "p75", "max", "mean"]:
        b = baseline_rr.get(key, 0)
        r = refined_rr.get(key, 0)
        md.append(f"| {key} | {b:.2f} | {r:.2f} |")
    md.append("")

    md.append("## Per-Window Breakdown\n")
    md.append("| Window | Signals | Base WR | Base Exp | Refined WR | Refined Exp |")
    md.append("|--------|---------|---------|----------|------------|-------------|")
    for row in per_window_rows:
        md.append(
            f"| W{row['window']} | {row['n']} | "
            f"{row['base_wr']:.1f}% | {row['base_exp']:+.3f} | "
            f"{row['ref_wr']:.1f}% | {row['ref_exp']:+.3f} |"
        )
    md.append("")

    md.append("## Verdict\n")
    base_exp = baseline_agg["expectancy"]
    ref_exp = refined_agg["expectancy"]
    delta = ref_exp - base_exp
    if delta > 0.05:
        md.append(f"✅ Refinement improves expectancy by **{delta:+.3f} R** per trade.")
        md.append("Consider promoting M15 refinement to the live bot after 30+ days of "
                  "further validation.")
    elif delta > 0:
        md.append(f"⚖️ Marginal improvement ({delta:+.3f} R). Not enough to justify the "
                  "added complexity yet.")
    else:
        md.append(f"❌ Refinement hurts expectancy ({delta:+.3f} R). Do not promote.")
    md.append("")

    with open(os.path.join(out_dir, "m15_refinement_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/m15_refinement_latest.md")


def main():
    random.seed(42)
    log(f"M15 Refinement experiment — {len(RECOMMENDED_PAIRS)} pairs")

    per_window_rows = []
    baseline_trades = []
    refined_trades = []
    refined_only_trades = []
    fallback_count = 0
    refined_count = 0
    failed = []

    for sym_idx, sym in enumerate(RECOMMENDED_PAIRS, 1):
        log(f"\n[{sym_idx}/{len(RECOMMENDED_PAIRS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_H1_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
            m15 = fetch_candles_paginated(sym, M15_GRANULARITY, BACKTEST_M15_CANDLES)
        except Exception as e:
            log(f"  fetch failed: {e}")
            failed.append(sym)
            continue
        if not h1 or not d1 or not m15:
            log(f"  insufficient data")
            failed.append(sym)
            continue
        log(f"  H1: {len(h1)}  D1: {len(d1)}  M15: {len(m15)}")

        # Align: only use H1 bars whose epoch <= max M15 epoch
        max_m15_epoch = max(c["epoch"] for c in m15)
        usable_h1 = [c for c in h1 if c["epoch"] <= max_m15_epoch]
        if len(usable_h1) < WARMUP_BARS + 50:
            log(f"  not enough overlapping H1 bars ({len(usable_h1)})")
            failed.append(sym)
            continue

        # Reindex: pass the truncated H1 + full M15 to the collector
        # We'll re-run detection on the truncated h1 but pass full m15 for slices
        n = len(usable_h1)
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
            sigs = collect_signals(usable_h1, d1, m15, s, e)
            for sig in sigs:
                sig["symbol"] = sym
                sig["window"] = w + 1

                # Simulate baseline
                candles_full = usable_h1
                spread_h1 = SPREAD_ATR_FRAC * sig["atr_h1"]
                base_r = simulate(
                    candles_full, sig["h1_entry"], sig["h1_stop"], sig["h1_target"],
                    sig["direction"], sig["touch_index"], spread_h1,
                )
                if base_r is not None:
                    baseline_trades.append({
                        "window": w + 1, "symbol": sym,
                        "outcome": base_r["outcome"],
                        "rr_eff": round(base_r["rr"], 2),
                    })

                # Simulate refined
                if sig["refined"] is not None:
                    ref = sig["refined"]
                    spread_h1_2 = SPREAD_ATR_FRAC * sig["atr_h1"]
                    ref_r = simulate(
                        candles_full, ref["entry"], ref["stop"], ref["target"],
                        sig["direction"], sig["touch_index"], spread_h1_2,
                    )
                    if ref_r is not None:
                        refined_trades.append({
                            "window": w + 1, "symbol": sym,
                            "outcome": ref_r["outcome"],
                            "rr_eff": round(ref_r["rr"], 2),
                        })
                        refined_only_trades.append({
                            "window": w + 1, "symbol": sym,
                            "outcome": ref_r["outcome"],
                            "rr_eff": round(ref_r["rr"], 2),
                        })
                    refined_count += 1
                else:
                    fallback_count += 1
                    # Refined branch uses H1 for these
                    if base_r is not None:
                        refined_trades.append({
                            "window": w + 1, "symbol": sym,
                            "outcome": base_r["outcome"],
                            "rr_eff": round(base_r["rr"], 2),
                        })

    # Aggregates
    baseline_agg = _agg(baseline_trades)
    refined_agg = _agg(refined_trades)
    refined_only_agg = _agg(refined_only_trades)
    baseline_rr = _rr_stats(baseline_trades)
    refined_rr = _rr_stats(refined_trades)

    log("\n" + "=" * 70)
    log("RESULTS")
    log("=" * 70)
    log(f"  Baseline (H1): n={baseline_agg['n']}  WR={baseline_agg['wr']:.1f}%  "
        f"exp={baseline_agg['expectancy']:+.3f}R  netR={baseline_agg['net_r']:+.1f}")
    log(f"  Refined (all): n={refined_agg['n']}  WR={refined_agg['wr']:.1f}%  "
        f"exp={refined_agg['expectancy']:+.3f}R  netR={refined_agg['net_r']:+.1f}")
    log(f"  Refined only:  n={refined_only_agg['n']}  WR={refined_only_agg['wr']:.1f}%  "
        f"exp={refined_only_agg['expectancy']:+.3f}R  netR={refined_only_agg['net_r']:+.1f}")
    log(f"  Refined count: {refined_count}  Fallback count: {fallback_count}")

    # Per-window
    for w in range(1, N_WINDOWS + 1):
        base_w = [t for t in baseline_trades if t["window"] == w]
        ref_w = [t for t in refined_trades if t["window"] == w]
        b = _agg(base_w)
        r = _agg(ref_w)
        per_window_rows.append({
            "window": w, "n": b["n"],
            "base_wr": b["wr"], "base_exp": b["expectancy"],
            "ref_wr": r["wr"], "ref_exp": r["expectancy"],
        })
        log(f"  W{w}: base WR={b['wr']:.1f}% exp={b['expectancy']:+.3f}  |  "
            f"ref WR={r['wr']:.1f}% exp={r['expectancy']:+.3f}")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles_requested": BACKTEST_H1_CANDLES,
        "m15_candles_requested": BACKTEST_M15_CANDLES,
        "m15_displacement_mult": 1.5,
        "m15_ob_tolerance_atr": 0.20,
        "buffer_atr": 0.20,
    }
    _write_report(baseline_agg, refined_agg, refined_only_agg,
                  baseline_rr, refined_rr, fallback_count, refined_count,
                  per_window_rows, config_snap)


if __name__ == "__main__":
    main()
