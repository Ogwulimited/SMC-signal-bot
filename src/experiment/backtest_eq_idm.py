"""Backtest: does IDM (and/or FVG) add value on top of EQ?

Baseline: EQ-only (best rule from prior experiment).
Compare:
  - EQ only
  - EQ + IDM
  - EQ + FVG
  - EQ + IDM + FVG

Detection runs once at permissive level. Filters applied post-hoc.

The verdict explicitly refuses to conclude when sample size is too small.
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
from .eq_idm_rules import RULES, RULE_DESCRIPTIONS, flags_from_confluences, MIN_TRADES_FOR_VERDICT


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


def _write_report(rule_aggs, per_window_by_rule, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# Experiment: Does IDM Add Value to EQ?\n")
    md.append(f"**Generated:** {gen}\n")

    md.append("## Hypothesis\n")
    md.append("EQ-only was the strongest confluence rule in the prior experiment "
              "(45.6% WR, +0.365 R expectancy). This experiment tests whether "
              "adding IDM and/or FVG on top of EQ improves it, degrades it, or "
              "does nothing.\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Rule Definitions\n")
    md.append("| Rule | Logic |")
    md.append("|------|-------|")
    for rule_name, desc in RULE_DESCRIPTIONS.items():
        md.append(f"| {rule_name} | {desc} |")
    md.append("")

    md.append("## Results by Rule\n")
    md.append("| Rule | Signals | Wins | Losses | WR | Avg R:R (wins) | Expectancy | Net R |")
    md.append("|------|---------|------|--------|-----|----------------|------------|-------|")
    for rule_name in RULES:
        a = rule_aggs.get(rule_name, {})
        if not a or a.get("n", 0) == 0:
            md.append(f"| {rule_name} | 0 | – | – | – | – | – | – |")
            continue
        md.append(
            f"| {rule_name} | {a['n']} | {a['wins']} | {a['losses']} | "
            f"{a['wr']:.1f}% | {a['avg_rr_won']:.2f} | "
            f"{a['expectancy']:+.3f} | {a['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Deltas vs EQ-only (baseline)\n")
    base = rule_aggs.get("EQ_only", {})
    md.append("| Rule | Δ Signals | Δ WR (pp) | Δ Expectancy (R) | Δ Net R | Sample OK? |")
    md.append("|------|-----------|-----------|------------------|---------|------------|")
    for rule_name in RULES:
        if rule_name == "EQ_only":
            continue
        a = rule_aggs.get(rule_name, {})
        if not a or a.get("n", 0) == 0 or not base or base.get("n", 0) == 0:
            md.append(f"| {rule_name} | – | – | – | – | ✗ |")
            continue
        d_sig = a["n"] - base["n"]
        d_wr = a["wr"] - base["wr"]
        d_exp = a["expectancy"] - base["expectancy"]
        d_net = a["net_r"] - base["net_r"]
        sample_ok = "✓" if a["n"] >= MIN_TRADES_FOR_VERDICT else "✗"
        md.append(
            f"| {rule_name} | {d_sig:+d} | {d_wr:+.1f} | {d_exp:+.3f} | "
            f"{d_net:+.1f} | {sample_ok} |"
        )
    md.append("")
    md.append(f"**Sample OK** = at least {MIN_TRADES_FOR_VERDICT} trades "
              "(below this, deltas are not statistically meaningful).\n")

    md.append("## Per-Window Breakdown\n")
    md.append("| Rule | W1 n | W1 WR | W2 n | W2 WR | W3 n | W3 WR |")
    md.append("|------|------|-------|------|-------|------|-------|")
    for rule_name in RULES:
        pw = per_window_by_rule.get(rule_name, [])
        cells = []
        for w in range(1, N_WINDOWS + 1):
            row = next((r for r in pw if r["window"] == w), None)
            if row and row["n"] > 0:
                cells.append(f"{row['n']}")
                cells.append(f"{row['wr']:.1f}%")
            else:
                cells.append("0")
                cells.append("–")
        md.append(f"| {rule_name} | " + " | ".join(cells) + " |")
    md.append("")

    md.append("## Verdict\n")

    base_n = base.get("n", 0)
    base_wr = base.get("wr", 0)
    base_exp = base.get("expectancy", 0)

    idm = rule_aggs.get("EQ_AND_IDM", {})
    idm_n = idm.get("n", 0)
    idm_wr = idm.get("wr", 0)
    idm_exp = idm.get("expectancy", 0)

    fvg = rule_aggs.get("EQ_AND_FVG", {})
    both = rule_aggs.get("EQ_AND_IDM_AND_FVG", {})

    md.append(f"**Baseline (EQ-only):** {base_n} signals, "
              f"{base_wr:.1f}% WR, {base_exp:+.3f} R expectancy\n")

    # --- IDM addition analysis ---
    if idm_n == 0:
        md.append("**EQ + IDM:** No signals. IDM filter is too restrictive "
                  "when combined with EQ.\n")
    elif idm_n < MIN_TRADES_FOR_VERDICT:
        md.append(f"**EQ + IDM:** Only {idm_n} signals — below the "
                  f"{MIN_TRADES_FOR_VERDICT}-trade threshold. **Inconclusive.** "
                  f"Observed: {idm_wr:.1f}% WR, {idm_exp:+.3f} R expectancy, but "
                  "sample is too small to conclude whether IDM adds value.\n")
    else:
        d_wr = idm_wr - base_wr
        d_exp = idm_exp - base_exp
        if d_exp > 0.10 and d_wr > 3:
            md.append(f"**EQ + IDM:** Improves both WR ({d_wr:+.1f} pp) and "
                      f"expectancy ({d_exp:+.3f} R). **IDM adds value.** "
                      f"Worth considering as a filter if signal count "
                      f"({idm_n}) is acceptable.\n")
        elif d_exp > 0.05:
            md.append(f"**EQ + IDM:** Modest improvement ({d_exp:+.3f} R). "
                      f"Marginal case — depends on how much you value the "
                      f"signal count reduction.\n")
        elif d_exp > -0.05:
            md.append(f"**EQ + IDM:** Roughly neutral ({d_exp:+.3f} R). "
                      "IDM adds no meaningful edge on top of EQ. **Don't "
                      "require it.**\n")
        else:
            md.append(f"**EQ + IDM:** Hurts expectancy ({d_exp:+.3f} R). "
                      "**Reject.**\n")

    # --- FVG addition analysis ---
    if fvg.get("n", 0) >= MIN_TRADES_FOR_VERDICT:
        d_wr_f = fvg["wr"] - base_wr
        d_exp_f = fvg["expectancy"] - base_exp
        if d_exp_f > 0.10 and d_wr_f > 3:
            md.append(f"**EQ + FVG:** Improves WR ({d_wr_f:+.1f} pp) and "
                      f"expectancy ({d_exp_f:+.3f} R). FVG adds value on top "
                      "of EQ.\n")
        elif d_exp_f > -0.05:
            md.append(f"**EQ + FVG:** Neutral ({d_exp_f:+.3f} R). FVG "
                      "adds nothing on top of EQ.\n")
        else:
            md.append(f"**EQ + FVG:** Hurts expectancy ({d_exp_f:+.3f} R). "
                      "Reject.\n")
    elif fvg.get("n", 0) > 0:
        md.append(f"**EQ + FVG:** Only {fvg['n']} signals — inconclusive.\n")

    md.append("## Recommendation\n")
    if idm_n >= MIN_TRADES_FOR_VERDICT and (idm_exp - base_exp) > 0.10:
        md.append("Promote **EQ + IDM** to live. It improves both WR and "
                  "expectancy with adequate sample.\n")
    elif idm_n < MIN_TRADES_FOR_VERDICT:
        md.append("Keep **EQ-only** for the live bot. IDM sample is too small "
                  "to justify requiring it — insisting on IDM would cut "
                  "profitable opportunities without proven benefit.\n")
    else:
        md.append("Keep **EQ-only** for the live bot. Adding IDM does not "
                  "improve performance at acceptable confidence.\n")

    with open(os.path.join(out_dir, "eq_idm_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/eq_idm_latest.md")


def main():
    random.seed(42)
    log(f"EQ + IDM experiment — {len(RECOMMENDED_PAIRS)} pairs")

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
                        "outcome": r["outcome"],
                        "rr_eff": round(r["rr"], 2),
                    })

    log(f"\nTotal detected signals: {len(all_records)}")

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

    log("\n" + "=" * 70)
    log("RESULTS BY RULE")
    log("=" * 70)
    log(f"{'Rule':22s} {'Signals':>8s} {'WR':>6s} {'AvgRR':>6s} {'ExpR':>8s} {'NetR':>8s}")
    for rule_name in RULES:
        a = rule_aggs[rule_name]
        if a["n"] == 0:
            log(f"{rule_name:22s}        0      -      -        -        -")
            continue
        log(f"{rule_name:22s} {a['n']:8d} {a['wr']:5.1f}% {a['avg_rr_won']:6.2f} "
            f"{a['expectancy']:+8.3f} {a['net_r']:+8.1f}")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles": BACKTEST_H1_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "n_windows": N_WINDOWS,
        "min_trades_for_verdict": MIN_TRADES_FOR_VERDICT,
    }
    _write_report(rule_aggs, per_window_by_rule, config_snap)


if __name__ == "__main__":
    main()
