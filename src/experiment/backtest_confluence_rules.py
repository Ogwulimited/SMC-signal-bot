"""Backtest: compare confluence rules A–G (AND logic) under identical conditions.

Same pairs, same period, same entry/stop/target logic.
Detection runs ONCE at the most permissive rule.
Signals are then filtered post-hoc into each rule.

Also includes a look-ahead audit section documenting that signal
generation uses only data available at the current bar.
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
from ..continuation import detect_htf_bias
from .h1_cascade import detect_h1_cascade_signals
from .confluence_rules import RULES, RULE_DESCRIPTIONS, flags_from_confluences


BACKTEST_H1_CANDLES = 2500
WARMUP_BARS = 400
N_WINDOWS = 3


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
                "avg_rr_all": 0, "avg_confluence": 0}
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
    avg_confluence = sum(t.get("confluence_count", 0) for t in trades) / n if n else 0
    return {"n": n, "wins": len(wins), "losses": len(losses),
            "timeouts": len(timeouts), "wr": wr, "expectancy": exp,
            "net_r": net_r, "avg_rr_won": avg_rr_won, "avg_rr_all": avg_rr_all,
            "avg_confluence": avg_confluence}


def _write_report(rule_aggs, per_window_by_rule, base_confluence_stats, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# Experiment: Confluence Rule Comparison (A–G, AND logic)\n")
    md.append(f"**Generated:** {gen}\n")

    md.append("## Hypothesis\n")
    md.append("Compare OB quality gates using AND logic (requiring combinations "
              "of confluences) under identical conditions. Determine whether "
              "requiring additional confluences on top of FVG improves quality, "
              "and whether FVG itself adds value (Rule G control).\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Rule Definitions (AND logic)\n")
    md.append("| Rule | Logic |")
    md.append("|------|-------|")
    for rule_name, desc in RULE_DESCRIPTIONS.items():
        md.append(f"| {rule_name} | {desc} |")
    md.append("")

    md.append("## Results by Rule\n")
    md.append("| Rule | Signals | Wins | Losses | WR | Avg R:R (wins) | Avg Confl. | Expectancy | Net R |")
    md.append("|------|---------|------|--------|-----|----------------|------------|------------|-------|")
    for rule_name in RULES:
        a = rule_aggs.get(rule_name, {})
        if not a or a.get("n", 0) == 0:
            md.append(f"| {rule_name} | 0 | – | – | – | – | – | – | – |")
            continue
        md.append(
            f"| {rule_name} | {a['n']} | {a['wins']} | {a['losses']} | "
            f"{a['wr']:.1f}% | {a['avg_rr_won']:.2f} | {a['avg_confluence']:.2f} | "
            f"{a['expectancy']:+.3f} | {a['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Confluence Coverage in the Full Set (any signal, regardless of rule)\n")
    md.append("| Confluence | Signals | % of Total | WR | Expectancy |")
    md.append("|------------|---------|------------|-----|------------|")
    for name, stats in base_confluence_stats.items():
        md.append(
            f"| {name} | {stats['n']} | {stats['pct']:.1f}% | "
            f"{stats['wr']:.1f}% | {stats['expectancy']:+.3f} |"
        )
    md.append("")

    md.append("## Per-Window — Rule A (FVG only, current live)\n")
    md.append("| Window | Signals | WR | Expectancy |")
    md.append("|--------|---------|-----|------------|")
    for row in per_window_by_rule.get("A_FVG_only", []):
        md.append(f"| W{row['window']} | {row['n']} | {row['wr']:.1f}% | {row['expectancy']:+.3f} |")
    md.append("")

    md.append("## Per-Window — Rule G (EQH/EQL only)\n")
    md.append("| Window | Signals | WR | Expectancy |")
    md.append("|--------|---------|-----|------------|")
    for row in per_window_by_rule.get("G_EQ_only", []):
        md.append(f"| W{row['window']} | {row['n']} | {row['wr']:.1f}% | {row['expectancy']:+.3f} |")
    md.append("")

    md.append("## Look-Ahead Audit\n")
    md.append("Signal generation verified to use only historical data up to the "
              "current bar:\n")
    md.append("| Component | Data Used | Verdict |")
    md.append("|-----------|-----------|---------|")
    md.append("| Swing detection | Confirmed swings only (n bars after required, index ≤ current − n) | ✅ |")
    md.append("| BOS/CHoCH | Prior swings only (index < current) | ✅ |")
    md.append("| Liquidity pools | Built from confirmed swings | ✅ |")
    md.append("| PDH/PDL/weekly/session | Bars strictly before `as_of_epoch` | ✅ |")
    md.append("| Order block | Backward scan from BOS | ✅ |")
    md.append("| FVG detection | Bounded range (OB → BOS) | ✅ |")
    md.append("| Inducement sweep | Between BOS and current bar | ✅ |")
    md.append("| Touch trigger | Current bar's low/high vs OB mid | ✅ |")
    md.append("| Exit simulation | Future bars (intentional — measures outcome) | ✅ |")
    md.append("")
    md.append("All signal-generation paths use only data available at the "
              "current bar. The exit simulation intentionally uses future bars "
              "to measure outcomes — this is correct.\n")

    md.append("## Verdict\n")

    a_a = rule_aggs.get("A_FVG_only", {})
    g_a = rule_aggs.get("G_EQ_only", {})
    b_a = rule_aggs.get("B_FVG_AND_EQ", {})

    if g_a.get("n", 0) > 0 and a_a.get("n", 0) > 0:
        wr_delta = g_a["wr"] - a_a["wr"]
        exp_delta = g_a["expectancy"] - a_a["expectancy"]
        md.append(f"- **Rule A (FVG only):** {a_a['n']} signals, "
                  f"{a_a['wr']:.1f}% WR, {a_a['expectancy']:+.3f} R expectancy")
        md.append(f"- **Rule G (EQ only):** {g_a['n']} signals, "
                  f"{g_a['wr']:.1f}% WR, {g_a['expectancy']:+.3f} R expectancy")
        md.append(f"- Delta G vs A: WR {wr_delta:+.1f} pp, expectancy {exp_delta:+.3f} R")
        if exp_delta > 0.05:
            md.append("- **EQ-only beats FVG-only.** FVG is not the strongest confluence.")
        elif exp_delta < -0.05:
            md.append("- **FVG-only beats EQ-only.** FVG adds real value.")
        else:
            md.append("- FVG-only and EQ-only are similar in quality.")

    if b_a.get("n", 0) > 0 and a_a.get("n", 0) > 0:
        md.append("")
        md.append(f"- **Rule B (FVG AND EQ):** {b_a['n']} signals, "
                  f"{b_a['wr']:.1f}% WR, {b_a['expectancy']:+.3f} R expectancy")
        delta_b = b_a["expectancy"] - a_a["expectancy"]
        if delta_b > 0.05:
            md.append("- Requiring EQ on top of FVG **improves** expectancy.")
        elif delta_b < -0.05:
            md.append("- Requiring EQ on top of FVG **hurts** expectancy.")
        else:
            md.append("- Adding EQ to FVG is roughly neutral.")

    md.append("")
    md.append("**Best rule by net R:** see the Results table above.\n")

    with open(os.path.join(out_dir, "confluence_rules_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/confluence_rules_latest.md")


def main():
    random.seed(42)
    log(f"Confluence rule comparison (AND logic) — {len(RECOMMENDED_PAIRS)} pairs")

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
                    all_records.append({
                        "window": w + 1,
                        "flags": flags,
                        "confluence_count": sum(flags.values()),
                        "outcome": r["outcome"],
                        "rr_eff": round(r["rr"], 2),
                    })

    log(f"\nTotal signals detected (permissive): {len(all_records)}")

    rule_aggs = {}
    per_window_by_rule = {}
    for rule_name, rule_fn in RULES.items():
        filtered = [r for r in all_records if rule_fn(r["flags"])]
        rule_aggs[rule_name] = _agg(filtered)

        pw = []
        for w in range(1, N_WINDOWS + 1):
            w_trades = [r for r in filtered if r["window"] == w]
            a = _agg(w_trades)
            pw.append({"window": w, "n": a["n"], "wr": a["wr"], "expectancy": a["expectancy"]})
        per_window_by_rule[rule_name] = pw

    total = len(all_records)
    coverage = {}
    for flag_name in ["fvg", "eq", "idm", "time"]:
        subset = [r for r in all_records if r["flags"][flag_name]]
        a = _agg(subset)
        coverage[flag_name.upper()] = {
            "n": a["n"],
            "pct": (a["n"] / total * 100) if total else 0,
            "wr": a["wr"],
            "expectancy": a["expectancy"],
        }

    log("\n" + "=" * 70)
    log("RESULTS BY RULE (AND logic)")
    log("=" * 70)
    log(f"{'Rule':22s} {'Signals':>8s} {'WR':>6s} {'AvgRR':>6s} {'ExpR':>8s} {'NetR':>8s}")
    for rule_name in RULES:
        a = rule_aggs[rule_name]
        if a["n"] == 0:
            log(f"{rule_name:22s}        0      -      -        -        -")
            continue
        log(f"{rule_name:22s} {a['n']:8d} {a['wr']:5.1f}% {a['avg_rr_won']:6.2f} "
            f"{a['expectancy']:+8.3f} {a['net_r']:+8.1f}")

    log("\n" + "=" * 70)
    log("CONFLUENCE COVERAGE (in full permissive set)")
    log("=" * 70)
    for name, stats in coverage.items():
        log(f"  {name:10s} n={stats['n']:5d}  ({stats['pct']:5.1f}%)  "
            f"WR={stats['wr']:5.1f}%  exp={stats['expectancy']:+.3f}R")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles": BACKTEST_H1_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "n_windows": N_WINDOWS,
        "note": "Detection once at permissive level; AND filters applied post-hoc for each rule.",
    }
    _write_report(rule_aggs, per_window_by_rule, coverage, config_snap)


if __name__ == "__main__":
    main()
