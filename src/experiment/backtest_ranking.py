"""Backtest: does capping to top-N/day by ranking formula preserve edge?

Collects all EQ signals over the sample period, tags each with day + plan.
Filters to the top 5 per UTC day using each ranking formula.
Compares each formula's aggregate performance against:
  - The unfiltered EQ-only baseline
  - Each other formula

Writes reports/experiments/ranking_latest.md
"""

import bisect
import json
import os
import random
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from ..config import (
    RECOMMENDED_PAIRS, GRANULARITY, DETECT_WINDOW, HTF_GRANULARITY,
    HTF_CANDLE_COUNT, MAX_HORIZON_BARS, SPREAD_ATR_FRAC, ATR_PERIOD,
    REPORTS_DIR,
)
from ..deriv_client import fetch_candles_paginated
from ..smc import compute_atr
from ..continuation import detect_htf_bias
from .h1_cascade import detect_h1_cascade_signals
from .eq_idm_rules import flags_from_confluences
from .ranking import RANK_FORMULAS, FORMULA_DESCRIPTIONS


BACKTEST_H1_CANDLES = 2500
WARMUP_BARS = 400
N_WINDOWS = 3
DAILY_CAP = 5


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


def _write_report(baseline, formula_results, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# Experiment: Daily Cap + Ranking Formulas\n")
    md.append(f"**Generated:** {gen}\n")

    md.append("## Hypothesis\n")
    md.append(f"Given ~12 EQ signals per day, capping at {DAILY_CAP}/day via a "
              "ranking formula should preserve or improve per-trade quality "
              "while cutting signal volume to a manageable level.\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Ranking Formulas\n")
    md.append("| Formula | Description |")
    md.append("|---------|-------------|")
    for name, desc in FORMULA_DESCRIPTIONS.items():
        md.append(f"| {name} | {desc} |")
    md.append("")

    md.append(f"## Unfiltered Baseline (all EQ signals, no cap)\n")
    md.append(f"- Signals: {baseline['n']}")
    md.append(f"- WR: {baseline['wr']:.1f}%")
    md.append(f"- Expectancy: {baseline['expectancy']:+.3f} R")
    md.append(f"- Net R: {baseline['net_r']:+.1f}")
    md.append(f"- Avg R:R on wins: {baseline['avg_rr_won']:.2f}")
    md.append("")

    md.append(f"## Capped to Top {DAILY_CAP}/day by Formula\n")
    md.append("| Formula | Signals | Days | Avg/day | Wins | Losses | WR | Avg R:R (wins) | Expectancy | Net R |")
    md.append("|---------|---------|------|---------|------|--------|-----|----------------|------------|-------|")
    for name in RANK_FORMULAS:
        r = formula_results.get(name, {})
        agg = r.get("agg", {})
        if not agg or agg.get("n", 0) == 0:
            md.append(f"| {name} | 0 | – | – | – | – | – | – | – | – |")
            continue
        days = r.get("days", 0)
        avg_day = agg["n"] / days if days > 0 else 0
        md.append(
            f"| {name} | {agg['n']} | {days} | {avg_day:.1f} | "
            f"{agg['wins']} | {agg['losses']} | {agg['wr']:.1f}% | "
            f"{agg['avg_rr_won']:.2f} | {agg['expectancy']:+.3f} | {agg['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Deltas vs Unfiltered Baseline\n")
    md.append("| Formula | Δ Signals | Δ WR (pp) | Δ Expectancy (R) | Δ Net R |")
    md.append("|---------|-----------|-----------|------------------|---------|")
    for name in RANK_FORMULAS:
        r = formula_results.get(name, {})
        agg = r.get("agg", {})
        if not agg or agg.get("n", 0) == 0:
            continue
        d_n = agg["n"] - baseline["n"]
        d_wr = agg["wr"] - baseline["wr"]
        d_exp = agg["expectancy"] - baseline["expectancy"]
        d_net = agg["net_r"] - baseline["net_r"]
        md.append(f"| {name} | {d_n:+d} | {d_wr:+.1f} | {d_exp:+.3f} | {d_net:+.1f} |")
    md.append("")

    md.append("## Verdict\n")

    # Find best by expectancy and best by net_r
    valid = [(n, r["agg"]) for n, r in formula_results.items()
             if r.get("agg", {}).get("n", 0) > 0]
    if not valid:
        md.append("No formula produced trades. Check sample.\n")
    else:
        best_exp = max(valid, key=lambda x: x[1]["expectancy"])
        best_net = max(valid, key=lambda x: x[1]["net_r"])

        md.append(f"- **Best by expectancy:** {best_exp[0]} "
                  f"({best_exp[1]['expectancy']:+.3f} R, n={best_exp[1]['n']})")
        md.append(f"- **Best by net R:** {best_net[0]} "
                  f"({best_net[1]['net_r']:+.1f} R, n={best_net[1]['n']})")
        md.append("")

        if best_exp[0] == best_net[0]:
            md.append(f"**Recommendation:** promote **{best_exp[0]}** as the "
                      "live ranking formula. It wins on both per-trade quality "
                      "and total profit.\n")
        else:
            md.append(f"**Trade-off:** {best_exp[0]} wins per-trade; "
                      f"{best_net[0]} wins total. Choose based on whether you "
                      "value expectancy or total R more.\n")

        # Compare against baseline
        best = formula_results[best_exp[0]]["agg"]
        d_wr = best["wr"] - baseline["wr"]
        if d_wr > 3:
            md.append(f"Ranking improves WR over unfiltered baseline by "
                      f"{d_wr:+.1f} pp → selection is working.\n")
        elif d_wr < -3:
            md.append(f"Ranking degrades WR by {d_wr:+.1f} pp vs unfiltered. "
                      "The cap is picking worse signals.\n")
        else:
            md.append(f"Ranking WR is within {abs(d_wr):.1f} pp of unfiltered "
                      "baseline — selection is roughly neutral.\n")

    with open(os.path.join(out_dir, "ranking_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/ranking_latest.md")


def main():
    random.seed(42)
    log(f"Ranking experiment — {len(RECOMMENDED_PAIRS)} pairs, cap={DAILY_CAP}/day")

    all_records = []
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

                try:
                    pats = detect_h1_cascade_signals(h1_window, d1_window)
                except Exception:
                    pats = []

                for p in pats:
                    if p.touch_index != len(h1_window) - 1:
                        continue
                    r = simulate(h1, p.entry, p.stop, p.target,
                                 p.direction, i, spread)
                    if r is None:
                        continue
                    flags = flags_from_confluences(p.confluences)
                    # Only EQ signals (our primary filter)
                    if not flags["eq"]:
                        continue
                    day = datetime.fromtimestamp(
                        last_h1_epoch, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                    all_records.append({
                        "day": day,
                        "window": w + 1,
                        "symbol": sym,
                        "rr": p.rr,
                        "flags": flags,
                        "hour": datetime.fromtimestamp(
                            last_h1_epoch, tz=timezone.utc
                        ).hour,
                        "outcome": r["outcome"],
                        "rr_eff": round(r["rr"], 2),
                    })

    log(f"\nTotal EQ signals collected: {len(all_records)}")
    if not all_records:
        log("No signals; aborting.")
        return

    # Baseline: unfiltered
    baseline = _agg(all_records)

    # Group by day
    by_day = defaultdict(list)
    for rec in all_records:
        by_day[rec["day"]].append(rec)

    total_days = len(by_day)
    log(f"Total unique days: {total_days}")

    # For each formula: rank each day, take top N
    formula_results = {}
    for fname, ffn in RANK_FORMULAS.items():
        selected = []
        for day, recs in by_day.items():
            if ffn is None:
                # Random: shuffle
                shuffled = recs[:]
                random.shuffle(shuffled)
                top = shuffled[:DAILY_CAP]
            else:
                ranked = sorted(recs, key=ffn, reverse=True)
                top = ranked[:DAILY_CAP]
            selected.extend(top)
        agg = _agg(selected)
        formula_results[fname] = {
            "agg": agg,
            "days": total_days,
        }

    log("\n" + "=" * 70)
    log(f"RANKING RESULTS (cap = {DAILY_CAP}/day)")
    log("=" * 70)
    log(f"{'Baseline (unfiltered)':30s} n={baseline['n']:5d}  "
        f"WR={baseline['wr']:5.1f}%  exp={baseline['expectancy']:+.3f}R  "
        f"netR={baseline['net_r']:+.1f}")
    for fname in RANK_FORMULAS:
        r = formula_results[fname]
        a = r["agg"]
        avg_day = a["n"] / r["days"] if r["days"] else 0
        log(f"{fname:30s} n={a['n']:5d}  WR={a['wr']:5.1f}%  "
            f"exp={a['expectancy']:+.3f}R  netR={a['net_r']:+.1f}  "
            f"avg/day={avg_day:.1f}")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles": BACKTEST_H1_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "n_windows": N_WINDOWS,
        "daily_cap": DAILY_CAP,
        "total_signals_after_eq_filter": len(all_records),
        "total_days": total_days,
    }
    _write_report(baseline, formula_results, config_snap)


if __name__ == "__main__":
    main()
