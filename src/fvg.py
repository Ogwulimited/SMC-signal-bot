"""Fair Value Gap detection (3-candle imbalance).

Bullish FVG: low[i+1] > high[i-1]  → gap in [high[i-1], low[i+1]]
Bearish FVG: high[i+1] < low[i-1]  → gap in [high[i+1], low[i-1]]

Minimum size enforced: gap height must be >= MIN_FVG_ATR * ATR.
"""

from typing import List, Dict

from .config import MIN_FVG_ATR


def find_fvgs_in_range(candles, start_idx, end_idx, direction, atr):
    """Return list of FVGs formed strictly within [start_idx+1, end_idx-1].

    An FVG is defined by its middle bar at index i. The scan covers
    i from start_idx+1 to end_idx-1, meaning the 3-candle window
    spans (i-1, i, i+1) with i-1 >= start_idx and i+1 <= end_idx.
    """
    if atr is None or end_idx - start_idx < 2:
        return []

    min_size = MIN_FVG_ATR * atr
    out: List[Dict] = []

    lo = max(1, start_idx + 1)
    hi = min(len(candles) - 1, end_idx)
    for i in range(lo, hi):
        left = candles[i - 1]
        right = candles[i + 1]

        if direction == "bullish":
            if right["low"] > left["high"]:
                low = left["high"]
                high = right["low"]
                if (high - low) >= min_size:
                    out.append({"index": i, "low": low, "high": high, "direction": "bullish"})
        else:
            if right["high"] < left["low"]:
                low = right["high"]
                high = left["low"]
                if (high - low) >= min_size:
                    out.append({"index": i, "low": low, "high": high, "direction": "bearish"})

    return out


def has_fvg_in_displacement(candles, ob_idx, bos_idx, direction, atr):
    """True if any matching-direction FVG exists between the OB candle and BOS."""
    fvgs = find_fvgs_in_range(candles, ob_idx, bos_idx, direction, atr)
    return len(fvgs) > 0
