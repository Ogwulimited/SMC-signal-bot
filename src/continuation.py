"""Continuation model: D1 bias + H1 OB entry. Time-based liquidity prioritized.

v7: target selector prefers major (time-based) liquidity within PREFER_MAJOR_LIQ_ATR.
"""

from dataclasses import dataclass
from typing import List, Optional

from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    find_time_based_liquidity, compute_atr,
)
from .fvg import find_fvgs_in_range
from .config import (
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR,
    BUFFER_ATR, MIN_RR, MIN_TARGET_ATR, MIN_OB_WIDTH_ATR,
    MIN_CONT_FVG_ATR, CONT_LIQUIDITY_TOL_ATR, CONT_MAX_OB_AGE,
    CONT_MAX_BARS_BOS_TO_TOUCH, HTF_SWING_LOOKBACK,
    USE_TIME_BASED_LIQUIDITY, PREFER_MAJOR_LIQ_ATR,
)


SYNTHETIC_TARGET_ATR = 2.0

# Full groupings — used for fallback
UPSIDE_KINDS = ("EQH", "swing_high", "PDH", "weekly_high",
                "asia_high", "london_high", "ny_high")
DOWNSIDE_KINDS = ("EQL", "swing_low", "PDL", "weekly_low",
                  "asia_low", "london_low", "ny_low")

# Major (time-based) pools — preferred when in range
MAJOR_UPSIDE = ("PDH", "weekly_high", "asia_high", "london_high", "ny_high")
MAJOR_DOWNSIDE = ("PDL", "weekly_low", "asia_low", "london_low", "ny_low")


@dataclass
class ContinuationPattern:
    direction: str
    ob_index: int
    bos_index: int
    touch_index: int
    ob_high: float
    ob_low: float
    entry: float
    stop: float
    target: float
    rr: float
    has_fvg: bool
    has_liquidity_nearby: bool
    target_is_synthetic: bool
    target_kind: str


def detect_htf_bias(d1_candles) -> Optional[str]:
    if not d1_candles or len(d1_candles) < HTF_SWING_LOOKBACK * 2 + 10:
        return None
    swings = find_swings(d1_candles, HTF_SWING_LOOKBACK)
    if not swings:
        return None
    _, _, trend = detect_bos_choch(d1_candles, swings)
    if trend == "up":
        return "bullish"
    if trend == "down":
        return "bearish"
    return None


def _has_matching_fvg(candles, ob_idx, bos_idx, direction, atr) -> bool:
    fvgs = find_fvgs_in_range(candles, ob_idx, bos_idx, direction, atr)
    min_size = MIN_CONT_FVG_ATR * atr
    for f in fvgs:
        if (f["high"] - f["low"]) >= min_size:
            return True
    return False


def _has_nearby_liquidity(pools, direction, ob_high, ob_low, atr) -> bool:
    tol = CONT_LIQUIDITY_TOL_ATR * atr
    if direction == "bullish":
        for p in pools:
            if p.kind in DOWNSIDE_KINDS and p.price < ob_low:
                if (ob_low - p.price) <= tol:
                    return True
    else:
        for p in pools:
            if p.kind in UPSIDE_KINDS and p.price > ob_high:
                if (p.price - ob_high) <= tol:
                    return True
    return False


def _nearest_target_above(pools, price, atr):
    """Prefer major (time-based) liquidity if within PREFER_MAJOR_LIQ_ATR.
    Fall back to nearest pool of any type. Returns (price, kind) or (None, None).
    """
    # 1. Try major pools first
    major = [p for p in pools if p.price > price and not p.swept
             and p.kind in MAJOR_UPSIDE]
    if major:
        best_major = min(major, key=lambda p: p.price)
        if (best_major.price - price) <= PREFER_MAJOR_LIQ_ATR * atr:
            return best_major.price, best_major.kind

    # 2. Fall back to any pool
    cand = [p for p in pools if p.price > price and not p.swept
            and p.kind in UPSIDE_KINDS]
    if cand:
        best = min(cand, key=lambda p: p.price)
        return best.price, best.kind

    return None, None


def _nearest_target_below(pools, price, atr):
    """Mirror of _nearest_target_above for downside."""
    major = [p for p in pools if p.price < price and not p.swept
             and p.kind in MAJOR_DOWNSIDE]
    if major:
        best_major = max(major, key=lambda p: p.price)
        if (price - best_major.price) <= PREFER_MAJOR_LIQ_ATR * atr:
            return best_major.price, best_major.kind

    cand = [p for p in pools if p.price < price and not p.swept
            and p.kind in DOWNSIDE_KINDS]
    if cand:
        best = max(cand, key=lambda p: p.price)
        return best.price, best.kind

    return None, None


def _find_ob_before_bos(candles, bos_idx, direction, max_lookback=15):
    for j in range(bos_idx - 1, max(0, bos_idx - max_lookback) - 1, -1):
        c = candles[j]
        if direction == "bullish" and c["close"] < c["open"]:
            return j
        if direction == "bearish" and c["close"] > c["open"]:
            return j
    return None


COUNTERS = {
    "bias_none": 0,
    "h1_trend_none": 0,
    "h1_trend_opposite": 0,
    "total_bos": 0,
    "bos_too_old": 0,
    "bos_wrong_dir": 0,
    "no_ob": 0,
    "ob_too_narrow": 0,
    "ob_too_old": 0,
    "no_fvg": 0,
    "no_liquidity": 0,
    "not_touching_now": 0,
    "touched_before": 0,
    "no_target": 0,
    "synthetic_target_used": 0,
    "rr_too_low": 0,
    "emitted": 0,
    "target_kind_PDH": 0,
    "target_kind_PDL": 0,
    "target_kind_session": 0,
    "target_kind_weekly": 0,
    "target_kind_swing": 0,
    "target_kind_EQ": 0,
    "target_kind_synthetic": 0,
}


def reset_counters():
    for k in COUNTERS:
        COUNTERS[k] = 0


def detect_continuation_signals(h1_candles, d1_candles, debug=False):
    bias = detect_htf_bias(d1_candles)
    if bias is None:
        if debug:
            COUNTERS["bias_none"] += 1
        return []

    if len(h1_candles) < SWING_LOOKBACK * 2 + ATR_PERIOD + 50:
        return []

    atr = compute_atr(h1_candles, ATR_PERIOD)
    if atr is None:
        return []

    h1_swings = find_swings(h1_candles, SWING_LOOKBACK)
    if not h1_swings:
        return []

    bos_events, _, h1_trend = detect_bos_choch(h1_candles, h1_swings)

    if bias == "bullish" and h1_trend == "down":
        if debug:
            COUNTERS["h1_trend_opposite"] += 1
        return []
    if bias == "bearish" and h1_trend == "up":
        if debug:
            COUNTERS["h1_trend_opposite"] += 1
        return []
    if h1_trend is None and debug:
        COUNTERS["h1_trend_none"] += 1

    pools = find_liquidity_pools(h1_candles, h1_swings, atr, EQ_TOLERANCE_ATR)

    if USE_TIME_BASED_LIQUIDITY:
        time_pools = find_time_based_liquidity(h1_candles, h1_candles[-1]["epoch"])
        pools = pools + time_pools

    last_idx = len(h1_candles) - 1
    last = h1_candles[last_idx]

    out: List[ContinuationPattern] = []

    for bos in bos_events:
        if debug:
            COUNTERS["total_bos"] += 1

        if last_idx - bos.index > CONT_MAX_BARS_BOS_TO_TOUCH:
            if debug:
                COUNTERS["bos_too_old"] += 1
            continue

        if bias == "bullish" and bos.direction != "up":
            if debug:
                COUNTERS["bos_wrong_dir"] += 1
            continue
        if bias == "bearish" and bos.direction != "down":
            if debug:
                COUNTERS["bos_wrong_dir"] += 1
            continue

        ob_idx = _find_ob_before_bos(h1_candles, bos.index, bias)
        if ob_idx is None:
            if debug:
                COUNTERS["no_ob"] += 1
            continue

        ob = h1_candles[ob_idx]
        ob_high = ob["high"]
        ob_low = ob["low"]

        if (ob_high - ob_low) < MIN_OB_WIDTH_ATR * atr:
            if debug:
                COUNTERS["ob_too_narrow"] += 1
            continue
        if last_idx - ob_idx > CONT_MAX_OB_AGE:
            if debug:
                COUNTERS["ob_too_old"] += 1
            continue

        has_fvg = _has_matching_fvg(h1_candles, ob_idx, bos.index, bias, atr)
        if not has_fvg:
            if debug:
                COUNTERS["no_fvg"] += 1
            continue

        has_liq = _has_nearby_liquidity(pools, bias, ob_high, ob_low, atr)
        if not has_liq:
            if debug:
                COUNTERS["no_liquidity"] += 1
            continue

        entry = (ob_high + ob_low) / 2
        if bias == "bullish":
            if last["low"] > entry:
                if debug:
                    COUNTERS["not_touching_now"] += 1
                continue
        else:
            if last["high"] < entry:
                if debug:
                    COUNTERS["not_touching_now"] += 1
                continue

        touched_before = False
        for k in range(bos.index + 1, last_idx):
            c = h1_candles[k]
            if c["low"] <= entry <= c["high"]:
                touched_before = True
                break
        if touched_before:
            if debug:
                COUNTERS["touched_before"] += 1
            continue

        target_is_synthetic = False
        target_kind = "unknown"

        if bias == "bullish":
            stop = ob_low - BUFFER_ATR * atr
            target, target_kind = _nearest_target_above(pools, entry, atr)
            if target is None:
                target = entry + SYNTHETIC_TARGET_ATR * atr
                target_kind = "synthetic"
                target_is_synthetic = True
                if debug:
                    COUNTERS["synthetic_target_used"] += 1
            if target <= entry or entry <= stop:
                if debug:
                    COUNTERS["no_target"] += 1
                continue
            if (target - entry) < MIN_TARGET_ATR * atr:
                if debug:
                    COUNTERS["no_target"] += 1
                continue
            rr = (target - entry) / (entry - stop)
        else:
            stop = ob_high + BUFFER_ATR * atr
            target, target_kind = _nearest_target_below(pools, entry, atr)
            if target is None:
                target = entry - SYNTHETIC_TARGET_ATR * atr
                target_kind = "synthetic"
                target_is_synthetic = True
                if debug:
                    COUNTERS["synthetic_target_used"] += 1
            if target >= entry or stop <= entry:
                if debug:
                    COUNTERS["no_target"] += 1
                continue
            if (entry - target) < MIN_TARGET_ATR * atr:
                if debug:
                    COUNTERS["no_target"] += 1
                continue
            rr = (entry - target) / (stop - entry)

        if rr < MIN_RR:
            if debug:
                COUNTERS["rr_too_low"] += 1
            continue

        if debug:
            COUNTERS["emitted"] += 1
            if target_kind == "PDH":
                COUNTERS["target_kind_PDH"] += 1
            elif target_kind == "PDL":
                COUNTERS["target_kind_PDL"] += 1
            elif target_kind in ("asia_high", "asia_low", "london_high",
                                 "london_low", "ny_high", "ny_low"):
                COUNTERS["target_kind_session"] += 1
            elif target_kind in ("weekly_high", "weekly_low"):
                COUNTERS["target_kind_weekly"] += 1
            elif target_kind in ("EQH", "EQL"):
                COUNTERS["target_kind_EQ"] += 1
            elif target_kind in ("swing_high", "swing_low"):
                COUNTERS["target_kind_swing"] += 1
            elif target_kind == "synthetic":
                COUNTERS["target_kind_synthetic"] += 1

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
            target_is_synthetic=target_is_synthetic,
            target_kind=target_kind,
        ))

    return out
