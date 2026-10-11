"""Backtest v3 vs v1 baseline. MASSIVELY reduced sample for speed.

Runtime target: <20 min. If this still hangs, the detector itself
needs restructuring, which is a separate project.
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
from .multi_tf_liquidity import detect_continuation_signals_v3


M15_GRANULARITY = 900
BACKTEST_H1_CANDLES = 1200       # small sample, ~15 min runtime
BACKTEST_M15_CANDLES = 5000
WARMUP_BARS = 300
N_WINDOWS = 3                    # 3 windows for smaller sample
V3_SAMPLE_EVERY = 2              # run v3 on every 2nd bar only


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


def _confluence_breakdown(trades):
    kinds = {}
    for t in trades:
        for c in t.get("confluences", []):
            if c not in kinds:
                kinds[c] = {"n": 0, "wins": 0, "losses": 0}
            kinds[c]["n"] += 1
            if t["outcome"] == "win": kinds[c]["wins"] += 1
            elif t["outcome"] == "loss": kinds[c]["losses"] += 1
    out = []
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]["n"]):
        res = v["wins"] + v["losses"]
        wr = (v["wins"] / res * 100) if res > 0 else 0
        out.append({"kind": k, "n": v["n"], "wins": v["wins"],
                    "losses": v["losses"], "wr": wr})
    return out


def _tf_breakdown(trades):
    out = {}
    for t in trades:
        tf = t.get("entry_tf", "H1")
        if tf not in out:
            out[tf] = {"n": 0, "wins": 0, "losses": 0}
        out[tf]["n"] += 1
        if t["outcome"] == "win": out[tf]["wins"] += 1
        elif t["outcome"] == "loss": out[tf]["losses"] += 1
    rows = []
    for k, v in out.items():
        res = v["wins"] + v["losses"]
        wr = (v["wins"] / res * 100) if res > 0 else 0
        rows.append({"tf": k, "n": v["n"], "wins": v["wins"],
                     "losses": v["losses"], "wr": wr})
    return rows


def _write_report(base_agg, v3_agg, v3_confluences, v3_tfs,
                   per_window_rows, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# Experiment: Multi-TF Cascade + Flexible Confluence (v3, small sample)\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("> **Note:** reduced sample (1200 H1 bars, 3 windows, sampled v3). "
              "Directional signal only — not a full statistical result.\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Overall Comparison\n")
    md.append("| Metric | Baseline (v1) | v3 (multi-TF + flex confl) |")
    md.append("|--------|---------------|-----------------------------|")
    md.append(f"| Signals | {base_agg['n']} | {v3_agg['n']} |")
    md.append(f"| Wins | {base_agg['wins']} | {v3_agg['wins']} |")
    md.append(f"| Losses | {base_agg['losses']} | {v3_agg['losses']} |")
    md.append(f"| Timeouts | {base_agg['timeouts']} | {v3_agg['timeouts']} |")
    md.append(f"| **Win rate** | **{base_agg['wr']:.1f}%** | **{v3_agg['wr']:.1f}%** |")
    md.append(f"| Avg R:R (wins) | {base_agg['avg_rr_won']:.2f} | {v3_agg['avg_rr_won']:.2f} |")
    md.append(f"| Avg R:R (all) | {base_agg['avg_rr_all']:.2f} | {v3_agg['avg_rr_all']:.2f} |")
    md.append(f"| **Expectancy** | **{base_agg['expectancy']:+.3f} R** | **{v3_agg['expectancy']:+.3f} R** |")
    md.append(f"| Net R | {base_agg['net_r']:+.1f} | {v3_agg['net_r']:+.1f} |")
    md.append("")

    md.append("## v3 — Confluence-Type Breakdown\n")
    md.append("| Confluence | Trades | Wins | Losses | WR |")
    md.append("|------------|--------|------|--------|-----|")
    for k in v3_confluences:
        md.append(f"| {k['kind']} | {k['n']} | {k['wins']} | {k['losses']} | {k['wr']:.1f}% |")
    md.append("")

    md.append("## v3 — Entry Timeframe Breakdown\n")
    md.append("| TF | Trades | Wins | Losses | WR |")
    md.append("|----|--------|------|--------|-----|")
    for k in v3_tfs:
        md.append(f"| {k['tf']} | {k['n']} | {k['wins']} | {k['losses']} | {k['wr']:.1f}% |")
    md.append("")

    md.append("## Per-Window Breakdown\n")
    md.append("| Window | Base n | Base WR | Base Exp | v3 n | v3 WR | v3 Exp |")
    md.append("|--------|--------|---------|----------|------|-------|--------|")
    for row in per_window_rows:
        md.append(
            f"| W{row['window']} | {row['base_n']} | "
            f"{row['base_wr']:.1f}% | {row['base_exp']:+.3f} | "
            f"{row['v3_n']} | {row['v3_wr']:.1f}% | {row['v3_exp']:+.3f} |"
        )
    md.append("")

    md.append("## Verdict\n")
    delta = v3_agg["expectancy"] - base_agg["expectancy"]
    sig_gain = v3_agg["n"] - base_agg["n"]
    if base_agg["n"] < 15:
        md.append("⚠️ Sample too small for a verdict. Rerun with larger sample if needed.")
    elif delta > 0.05 and sig_gain > 0:
        md.append(f"✅ v3 improves expectancy by {delta:+.3f} R while adding "
                  f"{sig_gain} signals.")
    elif delta > -0.05 and sig_gain > 10:
        md.append(f"⚖️ Expectancy roughly flat ({delta:+.3f} R), v3 adds {sig_gain} signals.")
    elif delta > 0:
        md.append(f"⚖️ Marginal gain ({delta:+.3f} R).")
    else:
        md.append(f"❌ v3 hurts expectancy ({delta:+.3f} R).")
    md.append("")

    with open(os.path.join(out_dir, "multi_tf_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/multi_tf_latest.md")


def main():
    random.seed(42)
    log(f"Multi-TF experiment v3 (small sample) — {len(RECOMMENDED_PAIRS)} pairs")

    base_trades = []
    v3_trades = []
    per_window_raw = {w: {"base": [], "v3": []} for w in range(1, N_WINDOWS + 1)}
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

        d1_epochs = [c["epoch"] for c in d1]
        m15_epochs = [c["epoch"] for c in m15]

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
                    base_pats = detect_continuation_signals(h1_window, d1_window)
                except Exception:
                    base_pats = []
                base_touches = [p for p in base_pats if p.touch_index == len(h1_window) - 1]

                for p in base_touches:
                    r = simulate(h1, p.entry, p.stop, p.target,
                                 p.direction, i, spread)
                    if r is None:
                        continue
                    trade = {"window": w + 1, "symbol": sym,
                             "outcome": r["outcome"], "rr_eff": round(r["rr"], 2)}
                    base_trades.append(trade)
                    per_window_raw[w + 1]["base"].append(trade)

                # Skip v3 on most bars — cascade + sampling
                if base_touches:
                    continue
                if (i - s) % V3_SAMPLE_EVERY != 0:
                    continue

                m15_end_idx = bisect.bisect_right(m15_epochs, last_h1_epoch)
                if m15_end_idx < 50:
                    continue
                m15_window = m15[:m15_end_idx]

                try:
                    v3_pats = detect_continuation_signals_v3(
                        h1_window, m15_window, d1_window,
                    )
                except Exception:
                    v3_pats = []

                for p in v3_pats:
                    if p.touch_index != len(h1_window) - 1:
                        continue
                    r = simulate(h1, p.entry, p.stop, p.target,
                                 p.direction, i, spread)
                    if r is None:
                        continue
                    trade = {
                        "window": w + 1, "symbol": sym,
                        "outcome": r["outcome"], "rr_eff": round(r["rr"], 2),
                        "entry_tf": p.entry_tf,
                        "confluences": p.confluences,
                        "target_kind": p.target_kind,
                    }
                    v3_trades.append(trade)
                    per_window_raw[w + 1]["v3"].append(trade)

    base_agg = _agg(base_trades)
    v3_agg = _agg(v3_trades)
    v3_confluences = _confluence_breakdown(v3_trades)
    v3_tfs = _tf_breakdown(v3_trades)

    log("\n" + "=" * 70)
    log("RESULTS")
    log("=" * 70)
    log(f"  Baseline: n={base_agg['n']}  WR={base_agg['wr']:.1f}%  "
        f"exp={base_agg['expectancy']:+.3f}R")
    log(f"  v3:       n={v3_agg['n']}  WR={v3_agg['wr']:.1f}%  "
        f"exp={v3_agg['expectancy']:+.3f}R")

    per_window_rows = []
    for w in range(1, N_WINDOWS + 1):
        b = _agg(per_window_raw[w]["base"])
        v = _agg(per_window_raw[w]["v3"])
        per_window_rows.append({
            "window": w,
            "base_n": b["n"], "base_wr": b["wr"], "base_exp": b["expectancy"],
            "v3_n": v["n"], "v3_wr": v["wr"], "v3_exp": v["expectancy"],
        })
        log(f"  W{w}: base n={b['n']} WR={b['wr']:.1f}% | v3 n={v['n']} WR={v['wr']:.1f}%")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles": BACKTEST_H1_CANDLES,
        "m15_candles": BACKTEST_M15_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "n_windows": N_WINDOWS,
        "v3_sample_every": V3_SAMPLE_EVERY,
    }
    _write_report(base_agg, v3_agg, v3_confluences, v3_tfs,
                   per_window_rows, config_snap)


if __name__ == "__main__":
    main()
