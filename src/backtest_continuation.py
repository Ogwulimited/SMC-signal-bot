"""Walk-forward backtest for the continuation model.

Entry variants:
  - aggressive:  fill at OB mid on the touch bar
  - confirmed:   wait up to N bars after touch for a close above OB high
                 (bullish) / below OB low (bearish); enter at that close
"""

import csv
import json
import os
import random
from datetime import datetime, timezone

from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL,
    ATR_PERIOD, MAX_HORIZON_BARS, SPREAD_ATR_FRAC,
    CONT_CONFIRMATION_WAIT_BARS, HTF_GRANULARITY, HTF_CANDLE_COUNT,
    REPORTS_DIR,
)
from .deriv_client import fetch_candles_paginated
from .smc import compute_atr
from .continuation import detect_continuation_signals


BACKTEST_CANDLES = 8000       # ~333 days of H1
WARMUP_BARS = 500
N_WINDOWS = 4
RANDOM_TRIALS = 500


def log(m):
    print(m, flush=True)


# ---------- Exit simulation ----------

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


# ---------- Variant 1: aggressive (fill at OB mid on touch bar) ----------

def simulate_aggressive(candles, sig, spread):
    idx = sig["touch_index"]
    direction = sig["direction"]
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, sig["entry"], sig["stop"], sig["target"], spread)
    if not _valid_geo(direction, entry_eff, stop_eff, target_eff):
        return None

    # Same-bar SL check on touch bar
    tb = candles[idx]
    if direction == "bullish" and tb["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and tb["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}

    outcome, hit = _walk_exit(candles, idx + 1, direction, stop_eff, target_eff)
    bars = (hit - idx) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}


# ---------- Variant 2: confirmed (wait for close past OB edge) ----------

def simulate_confirmed(candles, sig, spread):
    idx = sig["touch_index"]
    direction = sig["direction"]
    ob_high = sig["ob_high"]
    ob_low = sig["ob_low"]

    # Find confirmation bar
    conf_idx = None
    for k in range(idx, min(idx + CONT_CONFIRMATION_WAIT_BARS, len(candles))):
        c = candles[k]
        if direction == "bullish" and c["close"] > ob_high:
            conf_idx = k
            break
        if direction == "bearish" and c["close"] < ob_low:
            conf_idx = k
            break
    if conf_idx is None or conf_idx + 1 >= len(candles):
        return None

    conf = candles[conf_idx]
    entry_raw = conf["close"]
    entry_eff, stop_eff, target_eff = _apply_spread(
        direction, entry_raw, sig["stop"], sig["target"], spread)
    if not _valid_geo(direction, entry_eff, stop_eff, target_eff):
        return None

    # Same-bar SL check on confirm bar
    if direction == "bullish" and conf["low"] <= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and conf["high"] >= stop_eff:
        return {"outcome": "loss", "bars": 0, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}

    outcome, hit = _walk_exit(candles, conf_idx + 1, direction, stop_eff, target_eff)
    bars = (hit - conf_idx) if hit is not None else None
    return {"outcome": outcome, "bars": bars, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}


VARIANTS = {
    "aggressive": simulate_aggressive,
    "confirmed": simulate_confirmed,
}


# ---------- Signal collection ----------

def collect_signals(h1, d1, start, end):
    sigs = []
    for i in range(start, end):
        # Use only data up to bar i
        h1_window = h1[: i + 1]
        d1_window = [c for c in d1 if c["epoch"] <= h1_window[-1]["epoch"]]
        if not d1_window:
            continue

        pats = detect_continuation_signals(h1_window, d1_window)
        for p in pats:
            # Only accept if the touch fired on the CURRENT bar
            if p.touch_index != i:
                continue
            sigs.append({
                "index": i,
                "touch_index": i,
                "direction": p.direction,
                "entry": p.entry,
                "stop": p.stop,
                "target": p.target,
                "ob_high": p.ob_high,
                "ob_low": p.ob_low,
                "ob_index": p.ob_index,
                "atr": compute_atr(h1_window, ATR_PERIOD) or 0.0,
            })

    # Dedupe by (direction, entry, target)
    seen = set()
    out = []
    for s in sigs:
        key = (s["direction"], round(s["entry"], 5), round(s["target"], 5))
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


# ---------- Random baseline ----------

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


# ---------- Report ----------

def _write_report(per_window_rows, aggregate, random_agg, config_snap, trades_all):
    os.makedirs(REPORTS_DIR, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(os.path.join(REPORTS_DIR, "continuation_latest.json"), "w") as f:
        json.dump({"generated": gen, "config": config_snap,
                   "per_window": per_window_rows, "aggregate": aggregate,
                   "random_baseline": random_agg}, f, indent=2)

    with open(os.path.join(REPORTS_DIR, "continuation_trades.csv"), "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "variant", "window", "symbol", "touch_index", "direction",
            "entry", "stop", "target", "outcome", "bars_held", "rr_eff",
        ])
        writer.writeheader()
        for v, rows in trades_all.items():
            for t in rows:
                r = {"variant": v}
                r.update(t)
                writer.writerow(r)

    md = []
    md.append("# SMC Signal Bot — Continuation Model Backtest\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Configuration\n")
    md.append("| Parameter | Value |")
    md.append("|-----------|-------|")
    for k, v in config_snap.items():
        md.append(f"| {k} | {v} |")
    md.append("")

    md.append("## Per-Window Results\n")
    md.append("| Window | Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |")
    md.append("|--------|---------|---------|------|--------|----------|-----|------------|-------|")
    for r in per_window_rows:
        md.append(
            f"| W{r['window']} | {r['variant']} | {r['n']} | {r['wins']} | {r['losses']} | "
            f"{r['timeouts']} | {r['wr']:.1f}% | {r['expectancy']:+.3f} | {r['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Aggregate\n")
    md.append("| Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |")
    md.append("|---------|---------|------|--------|----------|-----|------------|-------|")
    for v, a in aggregate.items():
        md.append(
            f"| {v} | {a['n']} | {a['wins']} | {a['losses']} | {a['timeouts']} | "
            f"{a['wr']:.1f}% | {a['expectancy']:+.3f} | {a['net_r']:+.1f} |"
        )
    md.append("")

    md.append("## Random Baseline\n")
    md.append(f"- Signals: {random_agg['n']}")
    md.append(f"- W/L/T: {random_agg['wins']}/{random_agg['losses']}/{random_agg['timeouts']}")
    md.append(f"- WR: {random_agg['wr']:.1f}%")
    md.append(f"- Expectancy: {random_agg['expectancy']:+.3f} R")
    md.append(f"- Net R: {random_agg['net_r']:+.1f}")
    md.append("")

    with open(os.path.join(REPORTS_DIR, "continuation_latest.md"), "w") as f:
        f.write("\n".join(md))

    log(f"\nReports written to {REPORTS_DIR}/")


# ---------- Main ----------

def main():
    random.seed(42)
    log(f"Continuation backtest — H1 entry / D1 bias — {N_WINDOWS} windows")

    per_window = {w: [] for w in range(1, N_WINDOWS + 1)}
    rnd_acc = []

    for sym_idx, sym in enumerate(SYMBOLS, 1):
        log(f"\n[{sym_idx}/{len(SYMBOLS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception as e:
            log(f"  fetch failed: {e}")
            continue
        if not h1 or not d1:
            log(f"  insufficient data")
            continue
        log(f"  H1: {len(h1)}  D1: {len(d1)}")

        n = len(h1)
        usable_start = WARMUP_BARS
        usable_end = n - MAX_HORIZON_BARS - 3
        if usable_end <= usable_start:
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
    log("VARIANT COMPARISON")
    log("=" * 70)

    per_window_rows = []
    trades_all = {v: [] for v in VARIANTS}

    for w in range(1, N_WINDOWS + 1):
        sigs = per_window[w]
        log(f"\nWindow {w}: {len(sigs)} signals")
        for vname, vfn in VARIANTS.items():
            wins = losses = timeouts = skipped = 0
            r_won = 0.0
            for sig in sigs:
                candles = sig["candles_ref"]
                spread = SPREAD_ATR_FRAC * sig["atr"]
                r = vfn(candles, sig, spread)
                if r is None:
                    skipped += 1
                    continue
                if r["outcome"] == "win":
                    wins += 1; r_won += r["rr"]
                elif r["outcome"] == "loss":
                    losses += 1
                else:
                    timeouts += 1
                trades_all[vname].append({
                    "window": w, "symbol": sig.get("symbol", ""),
                    "touch_index": sig["touch_index"], "direction": sig["direction"],
                    "entry": round(sig["entry"], 5), "stop": round(sig["stop"], 5),
                    "target": round(sig["target"], 5),
                    "outcome": r["outcome"], "bars_held": r["bars"],
                    "rr_eff": round(r["rr"], 2),
                })

            net_r = r_won - losses
            resolved = wins + losses
            wr = (wins / resolved * 100) if resolved > 0 else 0
            n_eval = wins + losses + timeouts
            exp = net_r / n_eval if n_eval else 0

            log(f"  {vname:12s} n={n_eval:4d} skip={skipped:4d} "
                f"W{wins}/L{losses}/T{timeouts}  WR={wr:5.1f}%  exp={exp:+.3f}R")

            per_window_rows.append({
                "window": w, "variant": vname, "n": n_eval,
                "wins": wins, "losses": losses, "timeouts": timeouts,
                "wr": wr, "expectancy": exp, "net_r": net_r,
            })

    log("\n" + "=" * 70)
    log("AGGREGATE")
    log("=" * 70)
    aggregate = {}
    for vname in VARIANTS:
        rows = [r for r in per_window_rows if r["variant"] == vname]
        n = sum(r["n"] for r in rows)
        wins = sum(r["wins"] for r in rows)
        losses = sum(r["losses"] for r in rows)
        timeouts = sum(r["timeouts"] for r in rows)
        net_r = sum(r["net_r"] for r in rows)
        resolved = wins + losses
        wr = (wins / resolved * 100) if resolved > 0 else 0
        exp = net_r / n if n else 0
        aggregate[vname] = {"n": n, "wins": wins, "losses": losses,
                            "timeouts": timeouts, "wr": wr,
                            "expectancy": exp, "net_r": net_r}
        log(f"  {vname:12s} n={n:4d}  W{wins}/L{losses}/T{timeouts}  "
            f"WR={wr:5.1f}%  exp={exp:+.3f}R  netR={net_r:+.1f}")

    log("\nRANDOM BASELINE")
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
    log(f"  n={n}  W{wins}/L{losses}/T{timeouts}  WR={wr:.1f}%  exp={exp:+.3f}R")

    config_snap = {
        "timeframe": TIMEFRAME_LABEL,
        "htf_granularity_sec": HTF_GRANULARITY,
        "symbols_count": len(SYMBOLS),
        "candles_requested": BACKTEST_CANDLES,
        "max_horizon_bars": MAX_HORIZON_BARS,
        "spread_atr_frac": SPREAD_ATR_FRAC,
        "min_cont_fvg_atr": 0.15,
        "cont_liquidity_tol_atr": 2.0,
        "cont_confirmation_wait_bars": CONT_CONFIRMATION_WAIT_BARS,
    }
    _write_report(per_window_rows, aggregate, rnd_agg, config_snap, trades_all)

    log("\nInterpretation:")
    log("- If aggressive or confirmed beats random by a clear margin AND is")
    log("  positive in all 4 windows → real continuation edge.")
    log("- If both are ≈ random or worse → base pattern has no edge, pivot.")


if __name__ == "__main__":
    main()
