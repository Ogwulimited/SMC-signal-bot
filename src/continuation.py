"""Continuation model: HTF bias + H1 OB + FVG + liquidity confluence.

Rules:
  1. HTF (D1) must have a direction (bullish/bearish) via CHoCH.
  2. H1 trend must align with HTF direction.
  3. For each H1 BOS in the trend direction, the OB is the last opposite
     candle before the displacement leg.
  4. The displacement leg must contain an FVG in the trend direction.
  5. A liquidity pool must exist within CONT_LIQUIDITY_TOL_ATR of the OB.
  6. Signal fires when the current H1 bar touches the OB mid (first tap).
"""

from dataclasses import dataclass
from typing import List, Optional

from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    compute_atr,
)
from .fvg import find_fvgs_in_range
from .config import (
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR,
    BUFFER_ATR, MIN_RR, MIN_TARGET_ATR, MIN_OB_WIDTH_ATR,
    MIN_CONT_FVG_ATR, CONT_LIQUIDITY_TOL_ATR, CONT_MAX_OB_AGE,
    HTF_SWING_LOOKBACK,
)


@dataclass
class ContinuationPattern:
    direction: str          # "bullish" | "bearish"
    ob_index: int           # H1 bar index of the OB candle
    bos_index: int          # H1 bar index of the BOS
    touch_index: int        # H1 bar where price first touched OB
    ob_high: float
    ob_low: float
    entry: float            # OB midpoint
    stop: float
    target: float
    rr: float
    has_fvg: bool
    has_liquidity_nearby: bool


def detect_htf_bias(d1_candles) -> Optional[str]:
    """Return 'bullish' / 'bearish' / None based on D1 CHoCH."""
    if not d1_candles or len(d1_candles) < HTF_SWING_LOOKBACK * 2 + 10:
        return None
    swings = find_swings(d1_candles, HTF_SWING_LOOKBACK)
    _, _, trend = detect_bos_choch(d1_candles, swings)
    if trend == "up":
        return "bullish"
    if trend == "down":
        return "bearish"
    return None


def _has_matching_fvg(candles, ob_idx, bos_idx, direction, atr) -> bool:
    """True if a matching-direction FVG exists between OB and BOS with size >= threshold."""
    fvgs = find_fvgs_in_range(candles, ob_idx, bos_idx, direction, atr)
    min_size = MIN_CONT_FVG_ATR * atr
    for f in fvgs:
        if (f["high"] - f["low"]) >= min_size:
            return True
    return False


def _has_nearby_liquidity(pools, direction, ob_high, ob_low, atr) -> bool:
    """A structural liquidity pool within CONT_LIQUIDITY_TOL_ATR of the OB.

    For bullish: pool BELOW ob_low (inducement / protective liquidity)
    For bearish: pool ABOVE ob_high
    """
    tol = CONT_LIQUIDITY_TOL_ATR * atr
    if direction == "bullish":
        for p in pools:
            if p.kind in ("EQL", "swing_low") and p.price < ob_low:
                if (ob_low - p.price) <= tol:
                    return True
    else:
        for p in pools:
            if p.kind in ("EQH", "swing_high") and p.price > ob_high:
                if (p.price - ob_high) <= tol:
                    return True
    return False


def _nearest_target_above(pools, price):
    cand = [p for p in pools if p.price > price and not p.swept
            and p.kind in ("EQH", "swing_high")]
    return min(cand, key=lambda p: p.price).price if cand else None


def _nearest_target_below(pools, price):
    cand = [p for p in pools if p.price < price and not p.swept
            and p.kind in ("EQL", "swing_low")]
    return max(cand, key=lambda p: p.price).price if cand else None


def _find_ob_before_bos(candles, bos_idx, direction, max_lookback=15):
    """The last opposite-direction candle before the BOS candle."""
    for j in range(bos_idx - 1, max(0, bos_idx - max_lookback) - 1, -1):
        c = candles[j]
        if direction == "bullish" and c["close"] < c["open"]:
            return j
        if direction == "bearish" and c["close"] > c["open"]:
            return j
    return None


def detect_continuation_signals(h1_candles, d1_candles):
    """Return continuation patterns whose OB was touched by the LATEST H1 bar."""
    bias = detect_htf_bias(d1_candles)
    if bias is None:
        return []

    if len(h1_candles) < SWING_LOOKBACK * 2 + ATR_PERIOD + 50:
        return []

    atr = compute_atr(h1_candles, ATR_PERIOD)
    if atr is None:
        return []

    h1_swings = find_swings(h1_candles, SWING_LOOKBACK)
    bos_events, _, h1_trend = detect_bos_choch(h1_candles, h1_swings)

    # H1 trend must align with HTF
    if bias == "bullish" and h1_trend != "up":
        return []
    if bias == "bearish" and h1_trend != "down":
        return []

    pools = find_liquidity_pools(h1_candles, h1_swings, atr, EQ_TOLERANCE_ATR)

    last_idx = len(h1_candles) - 1
    last = h1_candles[last_idx]

    out: List[ContinuationPattern] = []

    for bos in bos_events:
        if bias == "bullish" and bos.direction != "up":
            continue
        if bias == "bearish" and bos.direction != "down":
            continue

        ob_idx = _find_ob_before_bos(h1_candles, bos.index, bias)
        if ob_idx is None:
            continue

        ob = h1_candles[ob_idx]
        ob_high = ob["high"]
        ob_low = ob["low"]

        # OB quality gates
        if (ob_high - ob_low) < MIN_OB_WIDTH_ATR * atr:
            continue
        if last_idx - ob_idx > CONT_MAX_OB_AGE:
            continue

        has_fvg = _has_matching_fvg(h1_candles, ob_idx, bos.index, bias, atr)
        if not has_fvg:
            continue

        has_liq = _has_nearby_liquidity(pools, bias, ob_high, ob_low, atr)
        if not has_liq:
            continue

        # Only fire when the LATEST bar first touches the OB
        entry = (ob_high + ob_low) / 2
        if bias == "bullish":
            if last["low"] > entry:
                continue
        else:
            if last["high"] < entry:
                continue

        # Never touched before the latest bar
        touched_before = False
        for k in range(ob_idx + 1, last_idx):
            c = h1_candles[k]
            if c["low"] <= entry <= c["high"]:
                touched_before = True
                break
        if touched_before:
            continue

        if bias == "bullish":
            stop = ob_low - BUFFER_ATR * atr
            target = _nearest_target_above(pools, entry)
            if target is None or target <= entry or entry <= stop:
                continue
            if (target - entry) < MIN_TARGET_ATR * atr:
                continue
            rr = (target - entry) / (entry - stop)
        else:
            stop = ob_high + BUFFER_ATR * atr
            target = _nearest_target_below(pools, entry)
            if target is None or target >= entry or stop <= entry:
                continue
            if (entry - target) < MIN_TARGET_ATR * atr:
                continue
            rr = (entry - target) / (stop - entry)

        if rr < MIN_RR:
            continue

        out.append(ContinuationPattern(
            direction=bias,
            ob_index=ob_idx,
            bos_index=bos.index,
            touch_index=last_idx,
            ob_high=ob_high,
            ob_low=ob_low,
            entry=entry,
            stop=stop,
            target=target,
            rr=rr,
            has_fvg=has_fvg,
            has_liquidity_nearby=has_liq,
        ))

    return out
