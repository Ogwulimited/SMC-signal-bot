"""Debug script: run the continuation detector on ONE symbol, log filter counts.

Run locally or via a workflow. Tells us exactly where signals die.
"""

from .config import SYMBOLS, GRANULARITY, ATR_PERIOD, HTF_GRANULARITY, HTF_CANDLE_COUNT
from .deriv_client import fetch_candles_paginated
from .continuation import (
    detect_continuation_signals, reset_counters, COUNTERS,
    detect_htf_bias,
)
from .smc import find_swings, detect_bos_choch, compute_atr


DEBUG_SYMBOL = "frxEURUSD"
DEBUG_H1_CANDLES = 4000
DEBUG_SAMPLE_BARS = [1000, 1500, 2000, 2500, 3000, 3500]


def log(m):
    print(m, flush=True)


def main():
    log(f"Debug: {DEBUG_SYMBOL}")

    h1 = fetch_candles_paginated(DEBUG_SYMBOL, GRANULARITY, DEBUG_H1_CANDLES)
    d1 = fetch_candles_paginated(DEBUG_SYMBOL, HTF_GRANULARITY, HTF_CANDLE_COUNT)
    log(f"  H1 candles: {len(h1)}")
    log(f"  D1 candles: {len(d1)}")

    # Full D1 bias
    bias = detect_htf_bias(d1)
    log(f"  D1 bias (full): {bias}")

    # D1 swings
    d1_swings = find_swings(d1, 3)
    log(f"  D1 swings found: {len(d1_swings)}")
    if d1_swings:
        log(f"    first 5: {[(s.index, round(s.price,5), s.kind) for s in d1_swings[:5]]}")

    # Sample bars
    reset_counters()
    for bar in DEBUG_SAMPLE_BARS:
        if bar >= len(h1):
            continue
        h1_window = h1[: bar + 1]
        d1_window = [c for c in d1 if c["epoch"] <= h1_window[-1]["epoch"]]
        log(f"\n  Bar {bar} (D1 window: {len(d1_window)} candles)")

        atr = compute_atr(h1_window, ATR_PERIOD)
        swings = find_swings(h1_window, 2)
        bos, choch, trend = detect_bos_choch(h1_window, swings)
        log(f"    H1 swings={len(swings)}  BOS={len(bos)}  CHoCH={len(choch)}  trend={trend}")

        d1_bias = detect_htf_bias(d1_window)
        log(f"    D1 bias at bar: {d1_bias}")

        pats = detect_continuation_signals(h1_window, d1_window, debug=True)
        log(f"    -> patterns emitted: {len(pats)}")

    log("\n" + "=" * 60)
    log("FILTER COUNTERS (cumulative over all sample bars)")
    log("=" * 60)
    for k, v in COUNTERS.items():
        log(f"  {k:22s}: {v}")

    log("\nInterpretation:")
    log("- If bias_none is high → D1 bias isn't being computed. Problem in HTF.")
    log("- If h1_trend_opposite is high → H1 trend disagrees with D1 too often.")
    log("- If no_ob or no_fvg or no_liquidity is high → filters are too strict.")
    log("- If emitted > 0 → signals exist, issue is in the backtest loop, not the detector.")


if __name__ == "__main__":
    main()
