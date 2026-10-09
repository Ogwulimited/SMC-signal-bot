"""Inducement (IDM) detection for continuation patterns.

Inducement = a minor liquidity pool that sits BETWEEN current price and
the real POI (OB). SMC theory says price often sweeps this minor pool
first (baiting retail), THEN continues into the real OB.

For a bullish setup:
  - The OB is BELOW current price
  - Inducement = a minor swing LOW between current price and the OB mid
  - Sweep = a subsequent candle's low pierces that minor low

For a bearish setup: symmetric with minor swing highs.

We only accept an inducement as "swept" if the sweep occurred within
MAX_SWEEP_AGE_BARS of the touch bar (keeps it fresh).
"""


MAX_SWEEP_AGE_BARS = 30  # sweep must occur within last 30 H1 bars before touch


def has_swept_inducement(h1_window, pattern, swings,
                          max_sweep_age_bars=MAX_SWEEP_AGE_BARS):
    """Return True if the pattern has a recently-swept inducement.

    h1_window:      the H1 candles that were used by the detector
    pattern:        ContinuationPattern (ob_index, bos_index, touch_index,
                    direction, entry, ob_high, ob_low)
    swings:         list of Swing objects found on h1_window
    max_sweep_age_bars: sweep must occur within this many bars of touch

    Returns True / False.
    """
    direction = pattern.direction
    ob_mid = pattern.entry
    bos_idx = pattern.bos_index
    touch_idx = pattern.touch_index

    if touch_idx >= len(h1_window):
        return False

    if direction == "bullish":
        # Inducement = minor low ABOVE ob_mid, formed after BOS
        candidates = [
            s for s in swings
            if s.kind == "low"
            and bos_idx < s.index < touch_idx
            and s.price > ob_mid
        ]
        for c in candidates:
            sweep_start = max(c.index + 1, touch_idx - max_sweep_age_bars)
            for j in range(sweep_start, touch_idx):
                if h1_window[j]["low"] < c.price:
                    return True
        return False

    else:
        # Inducement = minor high BELOW ob_mid, formed after BOS
        candidates = [
            s for s in swings
            if s.kind == "high"
            and bos_idx < s.index < touch_idx
            and s.price < ob_mid
        ]
        for c in candidates:
            sweep_start = max(c.index + 1, touch_idx - max_sweep_age_bars)
            for j in range(sweep_start, touch_idx):
                if h1_window[j]["high"] > c.price:
                    return True
        return False
