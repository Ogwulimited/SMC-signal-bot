"""Backtest the SMC engine on historical candles. Reports signal frequency."""

from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL,
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR, DISPLACEMENT_ATR_MULT,
)
from .deriv_client import fetch_candles
from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    detect_sweeps, detect_order_blocks, compute_atr,
)
from .patterns import detect_patterns, pattern_signature


BACKTEST_CANDLES = 5000
WARMUP_BARS = 100


def backtest_symbol(symbol):
    print(f"\n=== {symbol} ===")
    try:
        candles = fetch_candles(symbol, GRANULARITY, BACKTEST_CANDLES)
    except Exception as e:
        print(f"  fetch failed: {e}")
        return []

    if not candles or len(candles) < WARMUP_BARS + 50:
        print(f"  not enough candles ({len(candles)})")
        return []

    print(f"  candles: {len(candles)}")

    found = []
    for i in range(WARMUP_BARS, len(candles)):
        window = candles[: i + 1]
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
            sig = pattern_signature(symbol, TIMEFRAME_LABEL, p)
            found.append((i, sig, p.direction, p.rr, p.entry, p.target))

    # Dedupe: same price = same signal (mirrors live bot)
    seen = set()
    unique = []
    for row in found:
        key = (row[2], round(row[4], 5), round(row[5], 5))
        if key in seen:
            continue
        seen.add(key)
        unique.append(row)

    print(f"  unique signals: {len(unique)}")
    bullish = sum(1 for r in unique if r[2] == "bullish")
    bearish = len(unique) - bullish
    print(f"  bullish: {bullish}  bearish: {bearish}")

    if unique:
        avg_rr = sum(r[3] for r in unique) / len(unique)
        print(f"  avg structural R:R: 1:{avg_rr:.2f}")

    first_epoch = candles[WARMUP_BARS]["epoch"]
    last_epoch = candles[-1]["epoch"]
    span_days = (last_epoch - first_epoch) / 86400
    print(f"  span: {span_days:.1f} days ({span_days/30.44:.1f} months)")
    if span_days > 0:
        print(f"  signals/month: {len(unique) / (span_days/30.44):.1f}")
        print(f"  signals/week:  {len(unique) / (span_days/7):.1f}")

    return unique


def main():
    print(f"Backtest — timeframe {TIMEFRAME_LABEL}, {len(SYMBOLS)} symbols")
    print(f"Requested candles per symbol: {BACKTEST_CANDLES}")

    all_signals = {}
    for sym in SYMBOLS:
        all_signals[sym] = backtest_symbol(sym)

    total = sum(len(v) for v in all_signals.values())

    print("\n" + "=" * 40)
    print("SUMMARY")
    print("=" * 40)
    for sym, sigs in all_signals.items():
        print(f"  {sym}: {len(sigs)} signals")
    print(f"  TOTAL: {total}")


if __name__ == "__main__":
    main()
