"""Debug: sweep bars, count every emission. Tells us if signals exist at all."""

from .config import SYMBOLS, GRANULARITY, ATR_PERIOD, HTF_GRANULARITY, HTF_CANDLE_COUNT
from .deriv_client import fetch_candles_paginated
from .continuation import (
    detect_continuation_signals, reset_counters, COUNTERS,
)
from .smc import find_swings, detect_bos_choch, compute_atr


DEBUG_SYMBOL = "frxEURUSD"
DEBUG_H1_CANDLES = 4000
SWEEP_START = 500
SWEEP_END = 2500


def log(m):
    print(m, flush=True)


def main():
    log(f"Sweep debug: {DEBUG_SYMBOL}  bars {SWEEP_START}..{SWEEP_END}")

    h1 = fetch_candles_paginated(DEBUG_SYMBOL, GRANULARITY, DEBUG_H1_CANDLES)
    d1 = fetch_candles_paginated(DEBUG_SYMBOL, HTF_GRANULARITY, HTF_CANDLE_COUNT)
    log(f"  H1 candles: {len(h1)}  D1 candles: {len(d1)}")

    reset_counters()
    emitted_signals = []

    for i in range(SWEEP_START, min(SWEEP_END, len(h1))):
        h1_window = h1[: i + 1]
        d1_window = [c for c in d1 if c["epoch"] <= h1_window[-1]["epoch"]]
        if not d1_window:
            continue

        pats = detect_continuation_signals(h1_window, d1_window, debug=True)
        for p in pats:
            if p.touch_index != i:
                continue
            emitted_signals.append({
                "bar": i,
                "direction": p.direction,
                "entry": round(p.entry, 5),
                "stop": round(p.stop, 5),
                "target": round(p.target, 5),
                "rr": round(p.rr, 2),
                "ob_idx": p.ob_index,
            })

    log(f"\nSweep complete. Emitted signals: {len(emitted_signals)}")
    if emitted_signals:
        log("\nFirst 20 signals:")
        for s in emitted_signals[:20]:
            log(f"  {s}")

    log("\n" + "=" * 60)
    log("FILTER COUNTERS (cumulative over the sweep)")
    log("=" * 60)
    for k, v in COUNTERS.items():
        log(f"  {k:22s}: {v}")

    log("\n" + "=" * 60)
    log("FUNNEL ANALYSIS")
    log("=" * 60)
    total = COUNTERS["total_bos"]
    if total > 0:
        log(f"  total BOS:                {total}")
        log(f"  aligned BOS:              {total - COUNTERS['bos_wrong_dir']}")
        log(f"  survived OB quality:      {total - COUNTERS['bos_wrong_dir'] - COUNTERS['ob_too_narrow'] - COUNTERS['ob_too_old']}")
        log(f"  survived FVG:             {total - COUNTERS['bos_wrong_dir'] - COUNTERS['ob_too_narrow'] - COUNTERS['ob_too_old'] - COUNTERS['no_fvg']}")
        log(f"  survived liquidity:       (subtract no_liquidity)")
        log(f"  fresh touches emitted:    {COUNTERS['emitted']}")

    log("\nDecision:")
    log("- If emitted > 0 → detector works. Full backtest has a loop bug.")
    log("- If emitted == 0 but candidates reach 'not_touching_now' → tune touch criteria.")
    log("- If ob_too_old dominates → extend CONT_MAX_OB_AGE further.")
    log("- If no_fvg dominates → lower MIN_CONT_FVG_ATR or widen FVG window.")


if __name__ == "__main__":
    main()
