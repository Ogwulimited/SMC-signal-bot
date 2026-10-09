"""Backtest: continuation signals filtered by inducement (IDM) sweep.

Same baseline detector. Two branches:
  - Baseline: all signals that fire today
  - IDM-filtered: only signals where a minor liquidity pool was swept
    between BOS and the OB touch

Writes reports to reports/experiments/inducement_latest.md
"""

import json
import os
import random
import statistics
from datetime import datetime, timezone

from ..config import (
    RECOMMENDED_PAIRS, GRANULARITY, DETECT_WINDOW, HTF_GRANULARITY,
    HTF_CANDLE_COUNT, MAX_HORIZON_BARS, SPREAD_ATR_FRAC, ATR_PERIOD,
    SWING_LOOKBACK, REPORTS_DIR,
)
from ..deriv_client import fetch_candles_paginated
from ..smc import compute_atr, find_swings
from ..continuation import detect_continuation_signals, detect_htf_bias
from .inducement import has_swept_inducement, MAX_SWEEP_AGE_BARS


BACKTEST_H1_CANDLES = 6000
WARMUP_BARS = 500
N_WINDOWS = 4


def log(m):
    print(m, flush=True)


# ---------------- simulation ----------------

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


# ---------------- signal collection ----------------

def collect_signals(h1, d1, start, end):
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

        # Precompute swings on this window (used for inducement check)
        try:
            h1_swings = find_swings(h1_window, SWING_LOOKBACK)
        except Exception:
            h1_swings = []

        for p in pats:
            abs_touch = w_start + p.touch_index
            if abs_touch != i:
                continue

            # Inducement check
            try:
                idm = has_swept_inducement(h1_window, p, h1_swings)
            except Exception:
                idm = False

            atr_h1 = compute_atr(h1_window, ATR_PERIOD) or 0.0

            sigs.append({
                "index": abs_touch,
                "touch_index": abs_touch,
                "direction": p.direction,
                "entry": p.entry,
                "stop": p.stop,
                "target": p.target,
                "rr": p.rr,
                "target_kind": p.target_kind,
                "atr_h1": atr_h1,
                "has_idm_sweep": idm,
            })

    # dedupe
    seen = set()
    out = []
    for s in sigs:
        key = (s["direction"], round(s["entry"], 5), round(s["target"], 5))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


# ---------------- aggregation ----------------

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

    return {"n": n, "min": rrs[0], "p25": pct(0.25),
            "median": statistics.median(rrs), "p75": pct(0.75),
            "max": rrs[-1], "mean": sum(rrs) / n}


def _write_report(base_agg, idm_agg, no_idm_agg,
                   base_rr, idm_rr, per_window_rows, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(os.path.join(out_dir, "inducement_latest.json"), "w") as f:
        json.dump({
            "generated": gen,
            "config": config_snap,
            "baseline_agg": base_agg,
            "idm_agg": idm_agg,
            "no_idm_agg": no_idm_agg,
            "baseline_rr": base_rr,
            "idm_rr": idm_rr,
            "per_window": per_window_rows,
        }, f, indent=2)

    md = []
    md.append("# Experiment: Inducement (IDM) Sweep Filter\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Hypothesis\n")
    md.append("Requiring a minor liquidity pool to be swept between the BOS "
              "and the OB touch will improve WR and expectancy at the cost of "
              "fewer signals.\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Overall Comparison\n")
    md.append("| Metric | Baseline (all signals) | IDM-swept only | No IDM (rejected) |")
    md.append("|--------|------------------------|----------------|--------------------|")
    md.append(f"| Signals | {base_agg['n']} | {idm_agg['n']} | {no_idm_agg['n']} |")
    md.append(f"| Wins | {base_agg['wins']} | {idm_agg['wins']} | {no_idm_agg['wins']} |")
    md.append(f"| Losses | {base_agg['losses']} | {idm_agg['losses']} | {no_idm_agg['losses']} |")
    md.append(f"| Timeouts | {base_agg['timeouts']} | {idm_agg['timeouts']} | {no_idm_agg['timeouts']} |")
    md.append(f"| **Win rate** | **{base_agg['wr']:.1f}%** | **{idm_agg['wr']:.1f}%** | **{no_idm_agg['wr']:.1f}%** |")
    md.append(f"| Avg R:R (wins) | {base_agg['avg_rr_won']:.2f} | {idm_agg['avg_rr_won']:.2f} | {no_idm_agg['avg_rr_won']:.2f} |")
    md.append(f"| **Expectancy** | **{base_agg['expectancy']:+.3f} R** | **{idm_agg['expectancy']:+.3f} R** | **{no_idm_agg['expectancy']:+.3f} R** |")
    md.append(f"| Net R | {base_agg['net_r']:+.1f} | {idm_agg['net_r']:+.1f} | {no_idm_agg['net_r']:+.1f} |")
    md.append("")

    md.append("## IDM Coverage\n")
    if base_agg["n"] > 0:
        rate = idm_agg["n"] / base_agg["n"] * 100
        md.append(f"- Signals with swept IDM: **{idm_agg['n']}** ({rate:.1f}%)")
        md.append(f"- Signals without swept IDM: **{no_idm_agg['n']}**")
    md.append("")

    md.append("## R:R Distribution\n")
    md.append("| Metric | Baseline | IDM-filtered |")
    md.append("|--------|----------|--------------|")
    for key in ["min", "p25", "median", "p75", "max", "mean"]:
        b = base_rr.get(key, 0)
        r = idm_rr.get(key, 0)
        md.append(f"| {key} | {b:.2f} | {r:.2f} |")
    md.append("")

    md.append("## Per-Window Breakdown\n")
    md.append("| Window | Signals | Base WR | Base Exp | IDM WR | IDM Exp |")
    md.append("|--------|---------|---------|----------|--------|---------|")
    for row in per_window_rows:
        md.append(
            f"| W{row['window']} | {row['n']} | "
            f"{row['base_wr']:.1f}% | {row['base_exp']:+.3f} | "
            f"{row['idm_wr']:.1f}% | {row['idm_exp']:+.3f} |"
        )
    md.append("")

    md.append("## Verdict\n")
    base_exp = base_agg["expectancy"]
    idm_exp = idm_agg["expectancy"]
    delta = idm_exp - base_exp
    coverage = (idm_agg["n"] / base_agg["n"] * 100) if base_agg["n"] > 0 else 0

    if coverage < 15:
        md.append(f"⚠️ Coverage too low ({coverage:.1f}%). Not enough signals "
                  "survive the IDM filter to draw conclusions.")
    elif delta > 0.10 and idm_agg["wr"] > base_agg["wr"] + 3:
        md.append(f"✅ IDM filter improves expectancy by **{delta:+.3f} R** "
                  f"and WR by **{idm_agg['wr'] - base_agg['wr']:+.1f} pp**. "
                  "Worth promoting after live validation.")
    elif delta > 0:
        md.append(f"⚖️ Marginal improvement ({delta:+.3f} R). Not decisive.")
    else:
        md.append(f"❌ IDM filter hurts expectancy ({delta:+.3f} R). Reject.")
    md.append("")

    with open(os.path.join(out_dir, "inducement_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/inducement_latest.md")


def main():
    random.seed(42)
    log(f"Inducement experiment — {len(RECOMMENDED_PAIRS)} pairs")

    baseline_trades = []
    idm_trades = []
    no_idm_trades = []
    per_window_raw = {w: [] for w in range(1, N_WINDOWS + 1)}
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
                r = simulate(h1, sig["entry"], sig["stop"], sig["target"],
                              sig["direction"], sig["touch_index"], spread)
                if r is None:
                    continue

                trade = {
                    "window": w + 1, "symbol": sym,
                    "outcome": r["outcome"],
                    "rr_eff": round(r["rr"], 2),
                    "has_idm_sweep": sig["has_idm_sweep"],
                }
                baseline_trades.append(trade)
                per_window_raw[w + 1].append(trade)
                if sig["has_idm_sweep"]:
                    idm_trades.append(trade)
                else:
                    no_idm_trades.append(trade)

    base_agg = _agg(baseline_trades)
    idm_agg = _agg(idm_trades)
    no_idm_agg = _agg(no_idm_trades)
    base_rr = _rr_stats(baseline_trades)
    idm_rr = _rr_stats(idm_trades)

    log("\n" + "=" * 70)
    log("RESULTS")
    log("=" * 70)
    log(f"  Baseline:  n={base_agg['n']}  WR={base_agg['wr']:.1f}%  "
        f"exp={base_agg['expectancy']:+.3f}R  netR={base_agg['net_r']:+.1f}")
    log(f"  IDM-swept: n={idm_agg['n']}  WR={idm_agg['wr']:.1f}%  "
        f"exp={idm_agg['expectancy']:+.3f}R  netR={idm_agg['net_r']:+.1f}")
    log(f"  No IDM:    n={no_idm_agg['n']}  WR={no_idm_agg['wr']:.1f}%  "
        f"exp={no_idm_agg['expectancy']:+.3f}R  netR={no_idm_agg['net_r']:+.1f}")

    per_window_rows = []
    for w in range(1, N_WINDOWS + 1):
        w_trades = per_window_raw[w]
        base_w = [t for t in w_trades]
        idm_w = [t for t in w_trades if t["has_idm_sweep"]]
        b = _agg(base_w)
        i = _agg(idm_w)
        per_window_rows.append({
            "window": w, "n": b["n"],
            "base_wr": b["wr"], "base_exp": b["expectancy"],
            "idm_wr": i["wr"], "idm_exp": i["expectancy"],
        })
        log(f"  W{w}: base WR={b['wr']:.1f}% exp={b['expectancy']:+.3f} | "
            f"IDM WR={i['wr']:.1f}% exp={i['expectancy']:+.3f}")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles_requested": BACKTEST_H1_CANDLES,
        "max_sweep_age_bars": MAX_SWEEP_AGE_BARS,
        "swing_lookback": SWING_LOOKBACK,
    }
    _write_report(base_agg, idm_agg, no_idm_agg,
                  base_rr, idm_rr, per_window_rows, config_snap)


if __name__ == "__main__":
    main()
