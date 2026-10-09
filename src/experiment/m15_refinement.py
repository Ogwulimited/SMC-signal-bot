"""M15 OB refinement for H1 continuation patterns.

Given an H1 continuation pattern, look for an M15 OB inside the H1 OB zone.
If found, use the M15 OB for entry/stop (tighter). Otherwise return None
so the caller falls back to H1 entry/stop.

v2: loosened displacement threshold (1.5 → 1.0) and zone tolerance (0.20 → 0.50)
to increase refinement coverage.
"""

from ..config import BUFFER_ATR


M15_DISPLACEMENT_MULT = 1.0      # was 1.5 — weaker M15 displacement now qualifies
M15_OB_TOLERANCE_ATR = 0.50      # was 0.20 — allow M15 OB to poke out of H1 zone more


def _find_m15_ob_in_zone(m15_window, h1_ob_high, h1_ob_low, direction, m15_atr):
    """Scan an M15 window for the last opposite-direction candle before a
    small M15 displacement that lives inside the H1 OB zone.

    Returns {"high", "low", "index"} or None.
    """
    if not m15_window or m15_atr is None or m15_atr <= 0:
        return None

    tol = M15_OB_TOLERANCE_ATR * m15_atr
    zone_lo = h1_ob_low - tol
    zone_hi = h1_ob_high + tol

    for i in range(len(m15_window) - 2, 0, -1):
        c = m15_window[i]
        nxt = m15_window[i + 1]

        # Candle must overlap the H1 OB zone
        if c["high"] < zone_lo or c["low"] > zone_hi:
            continue

        if direction == "bullish":
            if c["close"] >= c["open"]:
                continue
            if (nxt["close"] - nxt["open"]) < M15_DISPLACEMENT_MULT * m15_atr:
                continue
            return {"high": c["high"], "low": c["low"], "index": i}
        else:
            if c["close"] <= c["open"]:
                continue
            if (nxt["open"] - nxt["close"]) < M15_DISPLACEMENT_MULT * m15_atr:
                continue
            return {"high": c["high"], "low": c["low"], "index": i}

    return None


def refine_to_m15(h1_pattern, h1_candles, m15_candles, m15_atr):
    """Attempt to refine an H1 continuation pattern to an M15 OB.

    Returns a dict with keys entry, stop, target, rr, m15_ob_high, m15_ob_low
    OR None if no valid M15 refinement exists (caller should fall back to H1).
    """
    if h1_pattern is None or m15_atr is None or m15_atr <= 0:
        return None

    ob_idx = h1_pattern.ob_index
    bos_idx = h1_pattern.bos_index
    if ob_idx >= len(h1_candles) or bos_idx >= len(h1_candles):
        return None
    if ob_idx >= bos_idx:
        return None

    ob_epoch = h1_candles[ob_idx]["epoch"]
    bos_epoch = h1_candles[bos_idx]["epoch"]

    # 1-hour buffer on each side of the OB -> BOS window
    buf = 3600
    m15_window = [c for c in m15_candles
                  if ob_epoch - buf <= c["epoch"] <= bos_epoch + buf]

    if len(m15_window) < 5:
        return None

    m15_ob = _find_m15_ob_in_zone(
        m15_window, h1_pattern.ob_high, h1_pattern.ob_low,
        h1_pattern.direction, m15_atr,
    )
    if m15_ob is None:
        return None

    entry = (m15_ob["high"] + m15_ob["low"]) / 2
    buffer = BUFFER_ATR * m15_atr

    if h1_pattern.direction == "bullish":
        stop = m15_ob["low"] - buffer
        if entry <= stop:
            return None
    else:
        stop = m15_ob["high"] + buffer
        if stop <= entry:
            return None

    target = h1_pattern.target
    if h1_pattern.direction == "bullish":
        if target <= entry:
            return None
        rr = (target - entry) / (entry - stop)
    else:
        if target >= entry:
            return None
        rr = (entry - target) / (stop - entry)

    if rr < 1.5:
        return None

    return {
        "entry": entry,
        "stop": stop,
        "target": target,
        "rr": rr,
        "m15_ob_high": m15_ob["high"],
        "m15_ob_low": m15_ob["low"],
    }
