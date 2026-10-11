"""H1-only cascade detector with flexible confluence.

Same H1 OB detection as v3, but WITHOUT the M15 fallback.
The only change from the live v1 detector: the confluence requirement
is relaxed from "must have FVG" to "any one of {FVG, EQH/EQL, IDM, time-based liq}".

Reuses the confluence-scanning logic from multi_tf_liquidity.py.
"""

from ..smc import (
    find_swings, find_liquidity_pools, find_time_based_liquidity, compute_atr,
)
from ..config import (
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR, USE_TIME_BASED_LIQUIDITY,
)
from .multi_tf_liquidity import _scan_tf_for_signals, detect_htf_bias


def detect_h1_cascade_signals(h1_window, d1_candles):
    """Detect H1 signals using flexible confluence (any-of-four).

    Returns list of ContinuationPatternV3 with entry_tf="H1".
    """
    bias = detect_htf_bias(d1_candles)
    if bias is None:
        return []

    if len(h1_window) < SWING_LOOKBACK * 2 + ATR_PERIOD + 50:
        return []

    atr = compute_atr(h1_window, ATR_PERIOD)
    if atr is None:
        return []

    h1_swings = find_swings(h1_window, SWING_LOOKBACK)
    if not h1_swings:
        return []

    h1_pools = find_liquidity_pools(h1_window, h1_swings, atr, EQ_TOLERANCE_ATR)
    if USE_TIME_BASED_LIQUIDITY:
        h1_pools = h1_pools + find_time_based_liquidity(
            h1_window, h1_window[-1]["epoch"]
        )

    return _scan_tf_for_signals(
        h1_window, "H1", bias, atr, h1_pools, h1_swings,
    )
