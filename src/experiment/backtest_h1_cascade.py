"""Backtest: H1-only cascade (flexible confluence) vs live v1 baseline.

Both detectors run on H1 only. No M15 fetch. Fast runtime.
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


def _write_report(base_agg, new_agg, base_rr, new_rr,
                   new_confl, per_window_rows, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    md = []
    md.append("# Experiment: H1-Only Flexible Confluence Cascade\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Hypothesis\n")
    md.append("Relaxing the confluence requirement on H1 from 'must have FVG' "
              "to 'any one of {FVG, EQH/EQL, IDM, time-based liq}' will add "
              "signals without hurting WR — as long as we stay on H1 (no M15 "
              "cascade).\n")

    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Overall Comparison\n")
    md.append("| Metric | Baseline (v1) | H1 flexible confluence |")
    md.append("|--------|---------------|------------------------|")
    md.append(f"| Signals | {base_agg['n']} | {new_agg['n']} |")
    md.append(f"| Wins | {base_agg['wins']} | {new_agg['wins']} |")
    md.append(f"| Losses | {base_agg['losses']} | {new_agg['losses']} |")
    md.append(f"| Timeouts | {base_agg['timeouts']} | {new_agg['timeouts']} |")
    md.append(f"| **Win rate** | **{base_agg['wr']:.1f}%** | **{new_agg['wr']:.1f}%** |")
    md.append(f"| Avg R:R (wins) | {base_agg['avg_rr_won']:.2f} | {new_agg['avg_rr_won']:.2f} |")
    md.append(f"| Avg R:R (all) | {base_agg['avg_rr_all']:.2f} | {new_agg['avg_rr_all']:.2f} |")
    md.append(f"| **Expectancy** | **{base_agg['expectancy']:+.3f} R** | **{new_agg['expectancy']:+.3f} R** |")
    md.append(f"| Net R | {base_agg['net_r']:+.1f} | {new_agg['net_r']:+.1f} |")
    md.append("")

    md.append("## R:R Distribution\n")
    md.append("| Metric | Baseline | Flexible |")
    md.append("|--------|----------|----------|")
    for key in ["min", "p25", "median", "p75", "max", "mean"]:
        md.append(f"| {key} | {base_rr.get(key, 0):.2f} | {new_rr.get(key, 0):.2f} |")
    md.append("")

    md.append("## Flexible Confluence-Type Breakdown\n")
    md.append("(A trade can have multiple confluences; counts can exceed signal count.)\n")
    md.append("| Confluence | Trades | Wins | Losses | WR |")
    md.append("|------------|--------|------|--------|-----|")
    for k in new_confl:
        md.append(f"| {k['kind']} | {k['n']} | {k['wins']} | {k['losses']} | {k['wr']:.1f}% |")
    md.append("")

    md.append("## Per-Window Breakdown\n")
    md.append("| Window | Base n | Base WR | Base Exp | New n | New WR | New Exp |")
    md.append("|--------|--------|---------|----------|-------|--------|---------|")
    for row in per_window_rows:
        md.append(
            f"| W{row['window']} | {row['base_n']} | "
            f"{row['base_wr']:.1f}% | {row['base_exp']:+.3f} | "
            f"{row['new_n']} | {row['new_wr']:.1f}% | {row['new_exp']:+.3f} |"
        )
    md.append("")

    md.append("## Verdict\n")
    delta = new_agg["expectancy"] - base_agg["expectancy"]
    sig_gain = new_agg["n"] - base_agg["n"]
    wr_delta = new_agg["wr"] - base_agg["wr"]
    if base_agg["n"] < 15:
        md.append("⚠️ Baseline sample too small for a confident verdict.")
    elif delta > 0.05 and sig_gain > 10:
        md.append(f"✅ Flexible confluence improves expectancy by {delta:+.3f} R "
                  f"while adding {sig_gain} signals. Promote candidate.")
    elif delta > -0.05 and sig_gain > 15 and wr_delta > -3:
        md.append(f"⚖️ Roughly flat expectancy ({delta:+.3f} R) but {sig_gain} more "
                  f"signals and WR within {wr_delta:+.1f} pp of baseline. "
                  "Useful for signal frequency.")
    elif delta > 0:
        md.append(f"⚖️ Marginal gain ({delta:+.3f} R).")
    else:
        md.append(f"❌ Flexible confluence hurts expectancy ({delta:+.3f} R). Reject.")
    md.append("")

    with open(os.path.join(out_dir, "h1_cascade_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReport written to {out_dir}/h1_cascade_latest.md")


def main():
    random.seed(42)
    log(f"H1 flexible confluence experiment — {len(RECOMMENDED_PAIRS)} pairs")

    base_trades = []
    new_trades = []
    per_window_raw = {w: {"base": [], "new": []} for w in range(1, N_WINDOWS + 1)}
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

                # ---- Baseline v1 ----
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

                # ---- H1 flexible confluence ----
                try:
                    new_pats = detect_h1_cascade_signals(h1_window, d1_window)
                except Exception:
                    new_pats = []

                for p in new_pats:
                    if p.touch_index != len(h1_window) - 1:
                        continue
                    r = simulate(h1, p.entry, p.stop, p.target,
                                 p.direction, i, spread)
                    if r is None:
                        continue
                    trade = {
                        "window": w + 1, "symbol": sym,
                        "outcome": r["outcome"], "rr_eff": round(r["rr"], 2),
                        "confluences": p.confluences,
                        "target_kind": p.target_kind,
                    }
                    new_trades.append(trade)
                    per_window_raw[w + 1]["new"].append(trade)

    base_agg = _agg(base_trades)
    new_agg = _agg(new_trades)
    base_rr = _rr_stats(base_trades)
    new_rr = _rr_stats(new_trades)
    new_confl = _confluence_breakdown(new_trades)

    log("\n" + "=" * 70)
    log("RESULTS")
    log("=" * 70)
    log(f"  Baseline: n={base_agg['n']}  WR={base_agg['wr']:.1f}%  "
        f"exp={base_agg['expectancy']:+.3f}R  netR={base_agg['net_r']:+.1f}")
    log(f"  Flexible: n={new_agg['n']}  WR={new_agg['wr']:.1f}%  "
        f"exp={new_agg['expectancy']:+.3f}R  netR={new_agg['net_r']:+.1f}")

    per_window_rows = []
    for w in range(1, N_WINDOWS + 1):
        b = _agg(per_window_raw[w]["base"])
        v = _agg(per_window_raw[w]["new"])
        per_window_rows.append({
            "window": w,
            "base_n": b["n"], "base_wr": b["wr"], "base_exp": b["expectancy"],
            "new_n": v["n"], "new_wr": v["wr"], "new_exp": v["expectancy"],
        })
        log(f"  W{w}: base n={b['n']} WR={b['wr']:.1f}% exp={b['expectancy']:+.3f} | "
            f"new n={v['n']} WR={v['wr']:.1f}% exp={v['expectancy']:+.3f}")

    log(f"\n  Confluence breakdown:")
    for c in new_confl:
        log(f"    {c['kind']:15s} n={c['n']:4d}  WR={c['wr']:5.1f}%")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "pairs": len(RECOMMENDED_PAIRS),
        "h1_candles": BACKTEST_H1_CANDLES,
        "warmup_bars": WARMUP_BARS,
        "n_windows": N_WINDOWS,
        "note": "H1-only, no M15 fetch, flexible confluence",
    }
    _write_report(base_agg, new_agg, base_rr, new_rr,
                   new_confl, per_window_rows, config_snap)


if __name__ == "__main__":
    main()
