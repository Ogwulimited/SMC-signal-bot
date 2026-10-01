"""Walk-forward validation + random baseline.

Splits each symbol's history into N equal windows. Runs the SMC detector
independently on each window. Reports WR / expectancy per window.

Also runs a random-entry baseline using the same stop/target/exit logic
applied to randomly chosen bars, to see whether the SMC pattern beats chance.
"""

import random
from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL,
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR, DISPLACEMENT_ATR_MULT,
    MIN_RR, MIN_SWEEP_PENETRATION_ATR, MAX_BARS_SWEEP_TO_ENTRY, MAX_OB_AGE_BARS,
    MIN_OB_WIDTH_ATR, MIN_TARGET_ATR,
    MAX_HORIZON_BARS, SPREAD_ATR_FRAC,
)
from .deriv_client import fetch_candles_paginated
from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    detect_sweeps, detect_order_blocks, compute_atr,
)
from .patterns import detect_patterns


BACKTEST_CANDLES = 12000
WARMUP_BARS = 200
DETECT_WINDOW = 500
N_WINDOWS = 4
RANDOM_TRIALS = 500


def log(m):
    print(m, flush=True)


def simulate(candles, entry_index, direction, entry, stop, target, spread):
    half = spread / 2.0
    if direction == "bullish":
        entry_eff = entry + half
        stop_eff = stop
        target_eff = target - half
    else:
        entry_eff = entry - half
        stop_eff = stop
        target_eff = target + half

    if direction == "bullish" and (entry_eff <= stop_eff or target_eff <= entry_eff):
        return "timeout", 0, 0
    if direction == "bearish" and (entry_eff >= stop_eff or target_eff >= entry_eff):
        return "timeout", 0, 0

    entry_bar = candles[entry_index]
    if direction == "bullish" and entry_bar["low"] <= stop_eff:
        return "loss", entry_index, 0
    if direction == "bearish" and entry_bar["high"] >= stop_eff:
        return "loss", entry_index, 0

    end = min(entry_index + 1 + MAX_HORIZON_BARS, len(candles))
    for k in range(entry_index + 1, end):
        c = candles[k]
        if direction == "bullish":
            if c["low"] <= stop_eff:
                return "loss", k, 0
            if c["high"] >= target_eff:
                return "win", k, 0
        else:
            if c["high"] >= stop_eff:
                return "loss", k, 0
            if c["low"] <= target_eff:
                return "win", k, 0
    return "timeout", 0, 0


def collect_signals(candles, start, end):
    """Run detector over window [start, end)."""
    found = []
    for i in range(start, end):
        w_start = max(0, i + 1 - DETECT_WINDOW)
        window = candles[w_start : i + 1]
        atr = compute_atr(window, ATR_PERIOD)
        if atr is None:
            continue
        swings = find_swings(window, SWING_LOOKBACK)
        bos_events, choch_events, _ = detect_bos_choch(window, swings)
        pools = find_liquidity_pools(window, swings, atr, EQ_TOLERANCE_ATR)
        sweeps = detect_sweeps(window, pools, atr)
        obs = detect_order_blocks(window, bos_events, atr, DISPLACEMENT_ATR_MULT)
        patterns = detect_patterns(window, sweeps, choch_events, bos_events, obs, pools, atr)
        for p in patterns:
            found.append({
                "index": i,
                "direction": p.direction,
                "entry": p.entry,
                "stop": p.stop,
                "target": p.target,
                "atr": atr,
            })

    # dedupe
    seen = set()
    unique = []
    for r in found:
        key = (r["direction"], round(r["entry"], 5), round(r["target"], 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)
    return unique


def stats_from_signals(candles, signals):
    wins = losses = timeouts = 0
    r_won = 0.0
    for r in signals:
        spread = SPREAD_ATR_FRAC * r["atr"]
        outcome, hit_idx, _ = simulate(
            candles, r["index"], r["direction"],
            r["entry"], r["stop"], r["target"], spread,
        )
        if outcome == "win":
            wins += 1
            if r["direction"] == "bullish":
                entry_eff = r["entry"] + spread / 2
                stop_eff = r["stop"]
                target_eff = r["target"] - spread / 2
                r_won += (target_eff - entry_eff) / (entry_eff - stop_eff)
            else:
                entry_eff = r["entry"] - spread / 2
                stop_eff = r["stop"]
                target_eff = r["target"] + spread / 2
                r_won += (entry_eff - target_eff) / (stop_eff - entry_eff)
        elif outcome == "loss":
            losses += 1
        else:
            timeouts += 1

    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    net_r = r_won - losses
    exp = net_r / len(signals) if signals else 0
    return {
        "n": len(signals),
        "wins": wins, "losses": losses, "timeouts": timeouts,
        "wr": wr, "expectancy": exp, "net_r": net_r,
    }


def random_baseline(candles, n_trials):
    """Random entries using the same structure as the pattern entries."""
    wins = losses = timeouts = 0
    r_won = 0.0
    n = len(candles)
    for _ in range(n_trials):
        i = random.randint(WARMUP_BARS + DETECT_WINDOW, n - MAX_HORIZON_BARS - 1)
        direction = random.choice(["bullish", "bearish"])
        entry = candles[i]["close"]
        # Stop and target sized like typical pattern trades
        window = candles[i - ATR_PERIOD * 2 : i]
        atr = compute_atr(window, ATR_PERIOD)
        if atr is None:
            continue
        stop_dist = 0.5 * atr
        target_dist = 2.0 * atr
        if direction == "bullish":
            stop = entry - stop_dist
            target = entry + target_dist
        else:
            stop = entry + stop_dist
            target = entry - target_dist
        spread = SPREAD_ATR_FRAC * atr
        outcome, _, _ = simulate(candles, i, direction, entry, stop, target, spread)
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
    exp = net_r / n_trials if n_trials else 0
    return {"n": n_trials, "wins": wins, "losses": losses, "timeouts": timeouts,
            "wr": wr, "expectancy": exp, "net_r": net_r}


def main():
    random.seed(42)
    log(f"Walk-forward test — {N_WINDOWS} windows per symbol")

    all_window_results = []
    all_random_results = []

    for sym_idx, sym in enumerate(SYMBOLS, 1):
        log(f"\n[{sym_idx}/{len(SYMBOLS)}] {sym}")
        try:
            candles = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_CANDLES)
        except Exception as e:
            log(f"  fetch failed: {e}")
            continue
        n = len(candles)
        if n < WARMUP_BARS + DETECT_WINDOW + 500:
            log(f"  not enough candles ({n})")
            continue

        usable_start = WARMUP_BARS + DETECT_WINDOW
        usable_end = n - MAX_HORIZON_BARS - 1
        span = usable_end - usable_start
        win_size = span // N_WINDOWS

        # Walk-forward windows
        for w in range(N_WINDOWS):
            s = usable_start + w * win_size
            e = s + win_size if w < N_WINDOWS - 1 else usable_end
            sigs = collect_signals(candles, s, e)
            res = stats_from_signals(candles, sigs)
            res["symbol"] = sym
            res["window"] = w + 1
            all_window_results.append(res)
            log(f"  W{w+1} bars[{s}..{e}]: n={res['n']} "
                f"W{res['wins']}/L{res['losses']}/T{res['timeouts']} "
                f"WR={res['wr']:.1f}% exp={res['expectancy']:+.3f}R")

        # Random baseline on full history
        rnd = random_baseline(candles, RANDOM_TRIALS)
        rnd["symbol"] = sym
        all_random_results.append(rnd)
        log(f"  RANDOM: W{rnd['wins']}/L{rnd['losses']}/T{rnd['timeouts']} "
            f"WR={rnd['wr']:.1f}% exp={rnd['expectancy']:+.3f}R")

    # Summary
    log("\n" + "=" * 50)
    log("WALK-FORWARD SUMMARY (per window index)")
    log("=" * 50)
    for w in range(1, N_WINDOWS + 1):
        rows = [r for r in all_window_results if r["window"] == w]
        n = sum(r["n"] for r in rows)
        wins = sum(r["wins"] for r in rows)
        losses = sum(r["losses"] for r in rows)
        timeouts = sum(r["timeouts"] for r in rows)
        net_r = sum(r["net_r"] for r in rows)
        resolved = wins + losses
        wr = (wins / resolved * 100) if resolved > 0 else 0
        exp = net_r / n if n else 0
        log(f"  W{w}: n={n}  W{wins}/L{losses}/T{timeouts}  WR={wr:.1f}%  "
            f"expectancy={exp:+.3f}R  netR={net_r:+.1f}")

    log("\n" + "=" * 50)
    log("RANDOM BASELINE")
    log("=" * 50)
    n = sum(r["n"] for r in all_random_results)
    wins = sum(r["wins"] for r in all_random_results)
    losses = sum(r["losses"] for r in all_random_results)
    timeouts = sum(r["timeouts"] for r in all_random_results)
    net_r = sum(r["net_r"] for r in all_random_results)
    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    exp = net_r / n if n else 0
    log(f"  n={n}  W{wins}/L{losses}/T{timeouts}  WR={wr:.1f}%  "
        f"expectancy={exp:+.3f}R  netR={net_r:+.1f}")
    log(f"\n  If SMC expectancy ≈ random expectancy → no edge.")
    log(f"  If SMC > random by a clear margin AND stable across windows → real.")


if __name__ == "__main__":
    main()
