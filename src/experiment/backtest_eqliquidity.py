"""Backtest: EQH/EQL as preferred targets vs baseline.

Runs the baseline detector and the v2 detector on the same bars.
The two detectors produce the same signals (same detection logic), but
the target/rr may differ because v2 prefers EQH/EQL alongside time-based
pools for target selection.

Writes reports/experiments/eqliquidity_latest.md
"""

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
from .continuation_v2 import detect_continuation_signals_v2


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


def collect_signals(h1, d1, start, end):
    """Returns list of dicts with BOTH baseline and v2 trade plans.

    Match is done by (direction, touch_index, ob_index) — same signal,
    different target selection.
    """
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
            base_pats = detect_continuation_signals(h1_window, d1_window)
        except Exception:
            base_pats = []
        try:
            v2_pats = detect_continuation_signals_v2(h1_window, d1_window)
        except Exception:
            v2_pats = []

        atr_h1 = compute_atr(h1_window, ATR_PERIOD) or 0.0

        # Index patterns by (direction, ob_index) for matching
        base_by_key = {(p.direction, p.ob_index): p for p in base_pats}
        v2_by_key = {(p.direction, p.ob_index): p for p in v2_pats}

        all_keys = set(base_by_key) | set(v2_by_key)

        for key in all_keys:
            direction, ob_idx_rel = key
            base = base_by_key.get(key)
            v2 = v2_by_key.get(key)

            # Only consider signals that fire on the CURRENT bar (fresh touch)
            base_touch = (w_start + base.touch_index) if base else None
            v2_touch = (w_start + v2.touch_index) if v2 else None
            if base_touch != i and v2_touch != i:
                continue

            sig = {
                "index": i,
                "touch_index": i,
                "direction": direction,
                "ob_index_abs": w_start + ob_idx_rel,
                "atr_h1": atr_h1,
                "baseline": None,
                "v2": None,
            }
            if base:
                sig["baseline"] = {
                    "entry": base.entry, "stop": base.stop,
                    "target": base.target, "rr": base.rr,
                    "target_kind": base.target_kind,
                }
            if v2:
                sig["v2"] = {
                    "entry": v2.entry, "stop": v2.stop,
                    "target": v2.target, "rr": v2.rr,
                    "target_kind": v2.target_kind,
                }
            sigs.append(sig)

    # Dedupe by (direction, entry-of-baseline, target-of-baseline) when baseline exists
    seen = set()
    out = []
    for s in sigs:
        base = s["baseline"] or {}
        v2 = s["v2"] or {}
        key = (s["direction"],
               round(base.get("entry", 0), 5),
               round(base.get("target", 0), 5),
               round(v2.get("target", 0), 5))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


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


def _target_kind_breakdown(trades):
    kinds = {}
    for t in trades:
        k = t.get("target_kind", "unknown")
        if k not in kinds:
            kinds[k] = {"n": 0, "wins": 0, "losses": 0}
        kinds[k]["n"] += 1
        if t["outcome"] == "win":
            kinds[k]["wins"] += 1
        elif t["outcome"] == "loss":
            kinds[k]["losses"] += 1
    out = []
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]["n"]):
        res = v["wins"] + v["losses"]
        wr = (v["wins"] / res * 100) if res > 0 else 0
        out.append({"kind": k, "n": v["n"], "wins": v["wins"],
                    "losses": v["losses"], "wr": wr})
    return out


def _rr_stats(trades):
    if not trades:
        return {}
    rrs = sorted(t["rr_eff"] for t in trades)
    n = len(rrs)

    def pct(p):
        idx = max(0, min(n - 1, int(p * (n - 1))))
        return rrs[idx]

    return {"n": n, "min": rrs[0], "p25": pct(0.25),
            "median": statistics.median(rrs), "p75": pct(0.75),
            "max": rrs[-1], "mean": sum(rrs) / n}


def _write_report(base_agg, v2_agg, base_rr, v2_rr,
                   base_kinds, v2_kinds, per_window_rows, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(os.path.join(out_dir, "eqliquidity_latest.json"), "w") as f:
        json.dump({
            "generated": gen, "config": config_snap,
            "baseline_agg": base_agg, "v2_agg": v2_agg,
            "baseline_rr": base_rr, "v2_rr": v2_rr,
            "baseline_kinds": base_kinds, "v2_kinds": v2_kinds,
            "per_window": per_window_rows,
        }, f, indent=2)

    md = []
    md.append("# Experiment: EQH/EQL as Preferred Targets\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Hypothesis\n")
    md.append("Treating equal highs (EQH) and equal lows (EQL) as preferred "
              "targets — alongside time-based pools — will improve expectancy, "
              "since these levels are highly visible to retail traders and "
              "attract clustered stops.\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Overall Comparison\n")
    md.append("| Metric | Baseline (time-based preferred) | v2 (EQH/EQL added) |")
    md.append("|--------|---------------------------------|---------------------|")
    md.append(f"| Signals | {base_agg['n']} | {v2_agg['n']} |")
    md.append(f"| Wins | {base_agg['wins']} | {v2_agg['wins']} |")
    md.append(f"| Losses | {base_agg['losses']} | {v2_agg['losses']} |")
    md.append(f"| Timeouts | {base_agg['timeouts']} | {v2_agg['timeouts']} |")
    md.append(f"| **Win rate** | **{base_agg['wr']:.1f}%** | **{v2_agg['wr']:.1f}%** |")
    md.append(f"| Avg R:R (wins) | {base_agg['avg_rr_won']:.2f} | {v2_agg['avg_rr_won']:.2f} |")
    md.append(f"| Avg R:R (all) | {base_agg['avg_rr_all']:.2f} | {v2_agg['avg_rr_all']:.2f} |")
    md.append(f"| **Expectancy** | **{base_agg['expectancy']:+.3f} R** | **{v2_agg['expectancy']:+.3f} R** |")
    md.append(f"| Net R | {base_agg['net_r']:+.1f} | {v2_agg['net_r']:+.1f} |")
    md.append("")

    md.append("## R:R Distribution\n")
    md.append("| Metric | Baseline | v2 |")
    md.append("|--------|----------|-----|")
    for key in ["min", "p25", "median", "p75", "max", "mean"]:
        md.append(f"| {key} | {base_rr.get(key, 0):.2f} | {v2_rr.get(key, 0):.2f} |")
    md.append("")

    md.append("## Target-Kind Breakdown — Baseline\n")
    md.append("| Kind | Trades | Wins | Losses | WR |")
    md.append("|------|--------|------|--------|-----|")
    for k in base_kinds:
        md.append(f"| {k['kind']} | {k['n']} | {k['wins']} | {k['losses']} | {k['wr']:.1f}% |")
    md.append("")

    md.append("## Target-Kind Breakdown — v2\n")
    md.append("| Kind | Trades | Wins | Losses | WR |")
    md.append("|------|--------|------|--------|-----|")
    for k in v2_kinds:
        md.append(f"| {k['kind']} | {k['n']} | {k['wins']} | {k['losses']} | {k['wr']:.1f}% |")
    md.append("")

    md.append("## Per-Window Breakdown\n")
    md.append("| Window | Signals | Base WR | Base Exp | v2 WR | v2 Exp |")
    md.append("|--------|---------|---------|----------|-------|--------|")
    for row in per_window_rows:
        md.append(
            f"| W{row['window']} | {row['n']} | "
            f"{row['base_wr']:.1f}% | {row['base_exp']:+.3f} | "
            f"{row['v2_wr']:.1f}% | {row['v2_exp']:+.3f} |"
        )
    md.append("")

    md.append("## Verdict\n")
    delta = v2_agg["expectancy"] - base_agg["expectancy"]
    if delta > 0.10:
        md.append(f"✅ v2 improves expectancy by **{delta:+.3f} R**. "
                  "EQH/EQL targets add real value. Consider promoting.")
    elif delta > 0:
        md.append(f"⚖️ Marginal improvement ({delta:+.3f} R). Not decisive.")
    else:
        md.append(f"❌ v2 hurts expectancy ({delta:+.3f} R). Reject. "
                  "Keep time-based pools as preferred targets.")
    md.append("")

    with open(os.path.join(out_dir, "eqliquidity_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/eqliquidity_latest.md")


def main():
    random.seed(42)
    log(f"EQH/EQL target experiment — {len(RECOMMENDED_PAIRS)} pairs")

    base_trades = []
    v2_trades = []
    per_window_raw = {w: {"base": [], "v2": []} for w in range(1, N_WINDOWS + 1)}
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
            sigs = collect_signals(h1, d1, s, e)
            for sig in sigs:
                sig["symbol"] = sym
                sig["window"] = w + 1
                spread = SPREAD_ATR_FRAC * sig["atr_h1"]

                if sig["baseline"] is not None:
                    b = sig["baseline"]
                    r = simulate(h1, b["entry"], b["stop"], b["target"],
                                 sig["direction"], sig["touch_index"], spread)
                    if r is not None:
                        trade = {
                            "window": w + 1, "symbol": sym,
                            "outcome": r["outcome"],
                            "rr_eff": round(r["rr"], 2),
                            "target_kind": b["target_kind"],
                        }
                        base_trades.append(trade)
                        per_window_raw[w + 1]["base"].append(trade)

                if sig["v2"] is not None:
                    v = sig["v2"]
                    r = simulate(h1, v["entry"], v["stop"], v["target"],
                                 sig["direction"], sig["touch_index"], spread)
                    if r is not None:
                        trade = {
                            "window": w + 1, "symbol": sym,
                            "outcome": r["outcome"],
                            "rr_eff": round(r["rr"], 2),
                            "target_kind": v["target_kind"],
                        }
                        v2_trades.append(trade)
                        per_window_raw[w + 1]["v2"].append(trade)

    base_agg = _agg(base_trades)
    v2_agg = _agg(v2_trades)
    base_rr = _rr_stats(base_trades)
    v2_rr = _rr_stats(v2_trades)
    base_kinds = _target_kind_breakdown(base_trades)
    v2_kinds = _target_kind_breakdown(v2_trades)

    log("\n" + "=" * 70)
    log("RESULTS")
    log("=" * 70)
    log(f"  Baseline: n={base_agg['n']}  WR={base_agg['wr']:.1f}%  "
        f"exp={base_agg['expectancy']:+.3f}R  netR={base_agg['net_r']:+.1f}")
    log(f"  v2:       n={v2_agg['n']}  WR={v2_agg['wr']:.1f}%  "
        f"exp={v2_agg['expectancy']:+.3f}R  netR={v2_agg['net_r']:+.1f}")

    per_window_rows = []
    for w in range(1, N_WINDOWS + 1):
        b = _agg(per_window_raw[w]["base"])
        v = _agg(per_window_raw[w]["v2"])
        per_window_rows.append({
            "window": w, "n": b["n"],
            "base_wr": b["wr"], "base_exp": b["expectancy"],
            "v2_wr": v["wr"], "v2_exp": v["expectancy"],
        })
        log(f"  W{w}: base WR={b['wr']:.1f}% exp={b['expectancy']:+.3f} | "
            f"v2 WR={v['wr']:.1f}% exp={v['expectancy']:+.3f}")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles_requested": BACKTEST_H1_CANDLES,
        "prefer_major_liq_atr": 5.0,
    }
    _write_report(base_agg, v2_agg, base_rr, v2_rr,
                  base_kinds, v2_kinds, per_window_rows, config_snap)


if __name__ == "__main__":
    main()