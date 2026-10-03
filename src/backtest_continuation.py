"""Continuation backtest v4 — D1 bias + H1 entry + time-based liquidity.

Reports R:R distribution AND target-kind breakdown.
"""

import csv
import json
import os
import random
import statistics
from datetime import datetime, timezone

from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL, DETECT_WINDOW,
    ATR_PERIOD, MAX_HORIZON_BARS, SPREAD_ATR_FRAC,
    HTF_GRANULARITY, HTF_CANDLE_COUNT,
    REPORTS_DIR,
)
from .deriv_client import fetch_candles_paginated
from .smc import compute_atr
from .continuation import detect_continuation_signals, detect_htf_bias


BACKTEST_CANDLES = 10000
WARMUP_BARS = 500
N_WINDOWS = 4
RANDOM_TRIALS = 500


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


def simulate(candles, sig, spread):
    idx = sig["touch_index"]
    direction = sig["direction"]
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, sig["entry"], sig["stop"], sig["target"], spread)
    if not _valid_geo(direction, entry_eff, stop_eff, target_eff):
        return None
    tb = candles[idx]
    if direction == "bullish" and tb["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and tb["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, hit = _walk_exit(candles, idx + 1, direction, stop_eff, target_eff)
    bars = (hit - idx) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}


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

        for p in pats:
            abs_touch = w_start + p.touch_index
            if abs_touch != i:
                continue
            sigs.append({
                "index": abs_touch,
                "touch_index": abs_touch,
                "direction": p.direction,
                "entry": p.entry,
                "stop": p.stop,
                "target": p.target,
                "ob_index": w_start + p.ob_index,
                "target_kind": p.target_kind,
                "atr": compute_atr(h1_window, ATR_PERIOD) or 0.0,
            })

    seen = set()
    out = []
    for s in sigs:
        key = (s["direction"], round(s["entry"], 5), round(s["target"], 5))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def random_baseline(candles, n_trials):
    wins = losses = timeouts = 0
    r_won = 0.0
    n = len(candles)
    for _ in range(n_trials):
        i = random.randint(WARMUP_BARS, n - MAX_HORIZON_BARS - 3)
        direction = random.choice(["bullish", "bearish"])
        atr = compute_atr(candles[i - ATR_PERIOD * 2 : i], ATR_PERIOD)
        if atr is None:
            continue
        nxt = candles[i + 1]
        entry = nxt["open"]
        stop_dist = 0.5 * atr
        target_dist = 2.0 * atr
        spread = SPREAD_ATR_FRAC * atr
        if direction == "bullish":
            entry_eff = entry + spread / 2
            stop_eff = entry - stop_dist
            target_eff = entry + target_dist - spread / 2
        else:
            entry_eff = entry - spread / 2
            stop_eff = entry + stop_dist
            target_eff = entry - target_dist + spread / 2
        if direction == "bullish" and nxt["low"] <= stop_eff:
            losses += 1
            continue
        if direction == "bearish" and nxt["high"] >= stop_eff:
            losses += 1
            continue
        outcome, _ = _walk_exit(candles, i + 2, direction, stop_eff, target_eff)
        if outcome == "win":
            wins += 1
            r_won += target_dist / stop_dist
        elif outcome == "loss":
            losses += 1
        else:
            timeouts += 1
    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    net_r = r_won - losses
    return {"n": n_trials, "wins": wins, "losses": losses, "timeouts": timeouts,
            "wr": wr, "expectancy": net_r / n_trials if n_trials else 0, "net_r": net_r}


def _rr_stats(trades):
    if not trades:
        return {}
    rrs = [t["rr_eff"] for t in trades]
    rrs_sorted = sorted(rrs)
    n = len(rrs_sorted)

    def pct(p):
        if n == 0: return 0.0
        idx = max(0, min(n - 1, int(p * (n - 1))))
        return rrs_sorted[idx]

    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    timeouts = [t for t in trades if t["outcome"] == "timeout"]
    win_rrs = [t["rr_eff"] for t in wins]

    buckets = [
        ("1.5-2.0", 1.5, 2.0),
        ("2.0-3.0", 2.0, 3.0),
        ("3.0-5.0", 3.0, 5.0),
        ("5.0+",    5.0, 1e9),
    ]
    bucket_rows = []
    for label, lo, hi in buckets:
        b = [t for t in trades if lo <= t["rr_eff"] < hi]
        bw = sum(1 for t in b if t["outcome"] == "win")
        bl = sum(1 for t in b if t["outcome"] == "loss")
        b_res = bw + bl
        b_wr = (bw / b_res * 100) if b_res > 0 else 0
        bucket_rows.append({"bucket": label, "n": len(b), "wins": bw, "losses": bl, "wr": b_wr})

    # Target-kind breakdown
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
    kind_rows = []
    for k, v in sorted(kinds.items(), key=lambda x: -x[1]["n"]):
        res = v["wins"] + v["losses"]
        wr = (v["wins"] / res * 100) if res > 0 else 0
        kind_rows.append({"kind": k, "n": v["n"], "wins": v["wins"],
                          "losses": v["losses"], "wr": wr})

    return {
        "n": n,
        "min_rr": min(rrs),
        "p25_rr": pct(0.25),
        "median_rr": statistics.median(rrs),
        "p75_rr": pct(0.75),
        "max_rr": max(rrs),
        "mean_rr": sum(rrs) / n,
        "full_tp_hits": len(wins),
        "avg_rr_won": (sum(win_rrs) / len(win_rrs)) if win_rrs else 0,
        "best_rr_won": max(win_rrs) if win_rrs else 0,
        "worst_rr_won": min(win_rrs) if win_rrs else 0,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "n_timeouts": len(timeouts),
        "buckets": bucket_rows,
        "target_kinds": kind_rows,
    }


def _write_report(per_window_rows, aggregate, random_agg, rr_stats, config_snap, trades_all):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(os.path.join(REPORTS_DIR, "continuation_latest.json"), "w") as f:
        json.dump({"generated": gen, "config": config_snap,
                   "per_window": per_window_rows, "aggregate": aggregate,
                   "rr_stats": rr_stats, "random_baseline": random_agg}, f, indent=2)

    with open(os.path.join(REPORTS_DIR, "continuation_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "window", "symbol", "touch_index", "direction",
            "entry", "stop", "target", "target_kind",
            "outcome", "bars_held", "rr_eff",
        ])
        writer.writeheader()
        for t in trades_all:
            writer.writerow(t)

    md = []
    md.append("# SMC Signal Bot — Continuation Backtest (D1+H1 + liquidity)\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")
    md.append("## Per-Window Results\n")
    md.append("| Window | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |")
    md.append("|--------|---------|------|--------|----------|-----|------------|-------|")
    for r in per_window_rows:
        md.append(
            f"| W{r['window']} | {r['n']} | {r['wins']} | {r['losses']} | "
            f"{r['timeouts']} | {r['wr']:.1f}% | {r['expectancy']:+.3f} | {r['net_r']:+.1f} |"
        )
    md.append("")
    md.append("## Aggregate\n")
    md.append(f"- Signals: {aggregate['n']}")
    md.append(f"- Wins / Losses / Timeouts: {aggregate['wins']} / {aggregate['losses']} / {aggregate['timeouts']}")
    md.append(f"- Win rate: {aggregate['wr']:.1f}%")
    md.append(f"- Expectancy: {aggregate['expectancy']:+.3f} R")
    md.append(f"- Net R: {aggregate['net_r']:+.1f}")
    md.append("")

    if rr_stats:
        md.append("## R:R Distribution\n")
        md.append("| Metric | Value |")
        md.append("|--------|-------|")
        md.append(f"| Trades | {rr_stats['n']} |")
        md.append(f"| Min R:R | {rr_stats['min_rr']:.2f} |")
        md.append(f"| 25th pct | {rr_stats['p25_rr']:.2f} |")
        md.append(f"| Median R:R | {rr_stats['median_rr']:.2f} |")
        md.append(f"| 75th pct | {rr_stats['p75_rr']:.2f} |")
        md.append(f"| Max R:R | {rr_stats['max_rr']:.2f} |")
        md.append(f"| Mean R:R | {rr_stats['mean_rr']:.2f} |")
        md.append("")
        md.append("## Winners vs Losers\n")
        md.append(f"- Full TP hits: **{rr_stats['full_tp_hits']}**")
        md.append(f"- Avg R:R on wins: **{rr_stats['avg_rr_won']:.2f}**")
        md.append(f"- Best win R:R: {rr_stats['best_rr_won']:.2f}")
        md.append(f"- Worst win R:R: {rr_stats['worst_rr_won']:.2f}")
        md.append(f"- Losses (all −1.00 R): {rr_stats['n_losses']}")
        md.append(f"- Timeouts (0 R): {rr_stats['n_timeouts']}")
        md.append("")
        md.append("## R:R Buckets\n")
        md.append("| R:R Range | Trades | Wins | Losses | WR |")
        md.append("|-----------|--------|------|--------|-----|")
        for b in rr_stats["buckets"]:
            md.append(f"| {b['bucket']} | {b['n']} | {b['wins']} | {b['losses']} | {b['wr']:.1f}% |")
        md.append("")
        md.append("## Target-Kind Breakdown\n")
        md.append("How often each liquidity type was the take-profit target.\n")
        md.append("| Target Kind | Trades | Wins | Losses | WR |")
        md.append("|-------------|--------|------|--------|-----|")
        for k in rr_stats["target_kinds"]:
            md.append(f"| {k['kind']} | {k['n']} | {k['wins']} | {k['losses']} | {k['wr']:.1f}% |")
        md.append("")

    md.append("## Random Baseline\n")
    md.append(f"- Signals: {random_agg['n']}")
    md.append(f"- WR: {random_agg['wr']:.1f}%")
    md.append(f"- Expectancy: {random_agg['expectancy']:+.3f} R")
    md.append("")

    with open(os.path.join(REPORTS_DIR, "continuation_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReports written to {REPORTS_DIR}/")


def main():
    random.seed(42)
    log(f"Continuation v4 — D1+H1 + time-based liquidity, {len(SYMBOLS)} symbols")

    per_window = {w: [] for w in range(1, N_WINDOWS + 1)}
    rnd_acc = []
    failed = []

    for sym_idx, sym in enumerate(SYMBOLS, 1):
        log(f"\n[{sym_idx}/{len(SYMBOLS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_CANDLES)
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
                sig["candles_ref"] = h1
                sig["window"] = w + 1
            per_window[w + 1].extend(sigs)
            log(f"  W{w+1}: {len(sigs)} signals")

        rnd = random_baseline(h1, RANDOM_TRIALS)
        rnd_acc.append(rnd)

    log("\n" + "=" * 70)
    log("AGGREGATE")
    log("=" * 70)
    per_window_rows = []
    trades_all = []
    for w in range(1, N_WINDOWS + 1):
        sigs = per_window[w]
        wins = losses = timeouts = 0
        r_won = 0.0
        for sig in sigs:
            candles = sig["candles_ref"]
            spread = SPREAD_ATR_FRAC * sig["atr"]
            r = simulate(candles, sig, spread)
            if r is None:
                continue
            if r["outcome"] == "win":
                wins += 1
                r_won += r["rr"]
            elif r["outcome"] == "loss":
                losses += 1
            else:
                timeouts += 1
            trades_all.append({
                "window": w, "symbol": sig.get("symbol", ""),
                "touch_index": sig["touch_index"], "direction": sig["direction"],
                "entry": round(sig["entry"], 5), "stop": round(sig["stop"], 5),
                "target": round(sig["target"], 5),
                "target_kind": sig.get("target_kind", "unknown"),
                "outcome": r["outcome"], "bars_held": r["bars"],
                "rr_eff": round(r["rr"], 2),
            })
        net_r = r_won - losses
        resolved = wins + losses
        wr = (wins / resolved * 100) if resolved > 0 else 0
        n_eval = wins + losses + timeouts
        exp = net_r / n_eval if n_eval else 0
        log(f"  W{w}: n={n_eval:4d}  W{wins}/L{losses}/T{timeouts}  WR={wr:5.1f}%  exp={exp:+.3f}R")
        per_window_rows.append({"window": w, "n": n_eval, "wins": wins, "losses": losses,
                                 "timeouts": timeouts, "wr": wr,
                                 "expectancy": exp, "net_r": net_r})

    total_n = sum(r["n"] for r in per_window_rows)
    total_wins = sum(r["wins"] for r in per_window_rows)
    total_losses = sum(r["losses"] for r in per_window_rows)
    total_timeouts = sum(r["timeouts"] for r in per_window_rows)
    total_net_r = sum(r["net_r"] for r in per_window_rows)
    total_resolved = total_wins + total_losses
    total_wr = (total_wins / total_resolved * 100) if total_resolved > 0 else 0
    total_exp = total_net_r / total_n if total_n else 0
    aggregate = {"n": total_n, "wins": total_wins, "losses": total_losses,
                 "timeouts": total_timeouts, "wr": total_wr,
                 "expectancy": total_exp, "net_r": total_net_r}
    log(f"\n  ALL: n={total_n}  W{total_wins}/L{total_losses}/T{total_timeouts}  "
        f"WR={total_wr:.1f}%  exp={total_exp:+.3f}R  netR={total_net_r:+.1f}")

    rr_stats = _rr_stats(trades_all)
    if rr_stats:
        log(f"\n  R:R — min={rr_stats['min_rr']:.2f}  median={rr_stats['median_rr']:.2f}  "
            f"max={rr_stats['max_rr']:.2f}  mean={rr_stats['mean_rr']:.2f}")
        log(f"  Full TP hits: {rr_stats['full_tp_hits']}  Avg R:R on wins: {rr_stats['avg_rr_won']:.2f}")
        log(f"  Target kinds:")
        for k in rr_stats["target_kinds"]:
            log(f"    {k['kind']:15s} n={k['n']:3d}  WR={k['wr']:5.1f}%")

    n = sum(r["n"] for r in rnd_acc)
    wins = sum(r["wins"] for r in rnd_acc)
    losses = sum(r["losses"] for r in rnd_acc)
    timeouts = sum(r["timeouts"] for r in rnd_acc)
    net_r = sum(r["net_r"] for r in rnd_acc)
    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    exp = net_r / n if n else 0
    rnd_agg = {"n": n, "wins": wins, "losses": losses, "timeouts": timeouts,
               "wr": wr, "expectancy": exp, "net_r": net_r}
    log(f"\n  RANDOM: n={n}  WR={wr:.1f}%  exp={exp:+.3f}R")

    if failed:
        log(f"\n  FAILED SYMBOLS ({len(failed)}): {', '.join(failed)}")

    config_snap = {
        "symbols_count": len(SYMBOLS),
        "failed_symbols": len(failed),
        "stack": "D1 bias + H1 OB entry + time-based liquidity",
        "detect_window": DETECT_WINDOW,
        "candles_per_symbol": BACKTEST_CANDLES,
        "max_horizon_bars": MAX_HORIZON_BARS,
    }
    _write_report(per_window_rows, aggregate, rnd_agg, rr_stats, config_snap, trades_all)


if __name__ == "__main__":
    main()
