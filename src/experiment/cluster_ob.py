"""Continuation model with Cluster OB detection.

Instead of taking just the single last opposite candle before a BOS, this
groups consecutive opposite/consolidating candles into a "cluster" base.
If the cluster is wider than MAX_CLUSTER_WIDTH_ATR, it is rejected.
"""

from dataclasses import dataclass
from typing import List, Optional

from ..smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    find_time_based_liquidity, compute_atr,
)
from ..fvg import find_fvgs_in_range
from ..config import (
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR,
    BUFFER_ATR, MIN_RR, MIN_TARGET_ATR, MIN_OB_WIDTH_ATR,
    MIN_CONT_FVG_ATR, CONT_LIQUIDITY_TOL_ATR, CONT_MAX_OB_AGE,
    CONT_MAX_BARS_BOS_TO_TOUCH, HTF_SWING_LOOKBACK,
    USE_TIME_BASED_LIQUIDITY, PREFER_MAJOR_LIQ_ATR,
)


SYNTHETIC_TARGET_ATR = 2.0
MAX_CLUSTER_WIDTH_ATR = 3.0   # Reject OBs wider than 3 * ATR

UPSIDE_KINDS = ("EQH", "swing_high", "PDH", "weekly_high", "asia_high", "london_high", "ny_high")
DOWNSIDE_KINDS = ("EQL", "swing_low", "PDL", "weekly_low", "asia_low", "london_low", "ny_low")
MAJOR_UPSIDE = ("PDH", "weekly_high", "asia_high", "london_high", "ny_high")
MAJOR_DOWNSIDE = ("PDL", "weekly_low", "asia_low", "london_low", "ny_low")
TIME_UPSIDE = ("PDH", "weekly_high", "asia_high", "london_high", "ny_high")
TIME_DOWNSIDE = ("PDL", "weekly_low", "asia_low", "london_low", "ny_low")


@dataclass
class ContinuationPatternCluster:
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
    confluences: List[str]
    target_kind: str
    target_is_synthetic: bool


def detect_htf_bias(d1_candles) -> Optional[str]:
    if not d1_candles or len(d1_candles) < HTF_SWING_LOOKBACK * 2 + 10: return None
    swings = find_swings(d1_candles, HTF_SWING_LOOKBACK)
    if not swings: return None
    _, _, trend = detect_bos_choch(d1_candles, swings)
    return "bullish" if trend == "up" else ("bearish" if trend == "down" else None)


def _has_eq_pool(pools, direction, ob_high, ob_low, atr) -> bool:
    tol = CONT_LIQUIDITY_TOL_ATR * atr
    if direction == "bullish":
        return any(p.kind == "EQL" and p.price < ob_low and (ob_low - p.price) <= tol for p in pools)
    else:
        return any(p.kind == "EQH" and p.price > ob_high and (p.price - ob_high) <= tol for p in pools)


def _has_time_pool(pools, direction, ob_high, ob_low, atr) -> bool:
    tol = CONT_LIQUIDITY_TOL_ATR * atr
    if direction == "bullish":
        return any(p.kind in TIME_DOWNSIDE and p.price < ob_low and (ob_low - p.price) <= tol for p in pools)
    else:
        return any(p.kind in TIME_UPSIDE and p.price > ob_high and (p.price - ob_high) <= tol for p in pools)


def _has_fvg(candles, ob_idx, bos_idx, direction, atr) -> bool:
    fvgs = find_fvgs_in_range(candles, ob_idx, bos_idx, direction, atr)
    min_size = MIN_CONT_FVG_ATR * atr
    return any((f["high"] - f["low"]) >= min_size for f in fvgs)


def _idm_swept(candles, ob_idx, bos_idx, direction, entry, swings, max_sweep_age=30) -> bool:
    last_idx = len(candles) - 1
    if direction == "bullish":
        for c in [s for s in swings if s.kind == "low" and bos_idx < s.index < last_idx and s.price > entry]:
            if any(candles[j]["low"] < c.price for j in range(max(c.index + 1, last_idx - max_sweep_age), last_idx)):
                return True
    else:
        for c in [s for s in swings if s.kind == "high" and bos_idx < s.index < last_idx and s.price < entry]:
            if any(candles[j]["high"] > c.price for j in range(max(c.index + 1, last_idx - max_sweep_age), last_idx)):
                return True
    return False


def _nearest_target_above(pools, price, atr):
    major = [p for p in pools if p.price > price and not p.swept and p.kind in MAJOR_UPSIDE]
    if major:
        best = min(major, key=lambda p: p.price)
        if (best.price - price) <= PREFER_MAJOR_LIQ_ATR * atr: return best.price, best.kind
    cand = [p for p in pools if p.price > price and not p.swept and p.kind in UPSIDE_KINDS]
    return (min(cand, key=lambda p: p.price).price, min(cand, key=lambda p: p.price).kind) if cand else (None, None)


def _nearest_target_below(pools, price, atr):
    major = [p for p in pools if p.price < price and not p.swept and p.kind in MAJOR_DOWNSIDE]
    if major:
        best = max(major, key=lambda p: p.price)
        if (price - best.price) <= PREFER_MAJOR_LIQ_ATR * atr: return best.price, best.kind
    cand = [p for p in pools if p.price < price and not p.swept and p.kind in DOWNSIDE_KINDS]
    return (max(cand, key=lambda p: p.price).price, max(cand, key=lambda p: p.price).kind) if cand else (None, None)


def _find_cluster_ob_before_bos(candles, bos_idx, direction, atr, max_lookback=15):
    """Find the consolidation base before the impulse."""
    # Start with the single opposite candle
    base_idx = None
    for j in range(bos_idx - 1, max(0, bos_idx - max_lookback) - 1, -1):
        c = candles[j]
        if direction == "bullish" and c["close"] < c["open"]: base_idx = j; break
        if direction == "bearish" and c["close"] > c["open"]: base_idx = j; break
    
    if base_idx is None: return None, None, None

    # Expand backwards to find the cluster (group opposite/small candles)
    cluster_high = candles[base_idx]["high"]
    cluster_low = candles[base_idx]["low"]
    start_idx = base_idx

    for j in range(base_idx - 1, max(0, base_idx - 5) - 1, -1):
        c = candles[j]
        body = abs(c["close"] - c["open"])
        is_opposite = (c["close"] < c["open"]) if direction == "bullish" else (c["close"] > c["open"])
        is_small = body < 0.5 * atr

        if is_opposite or is_small:
            cluster_high = max(cluster_high, c["high"])
            cluster_low = min(cluster_low, c["low"])
            start_idx = j
        else:
            break

    return start_idx, cluster_high, cluster_low


def detect_continuation_signals_cluster(h1_candles, d1_candles):
    bias = detect_htf_bias(d1_candles)
    if bias is None or len(h1_candles) < SWING_LOOKBACK * 2 + ATR_PERIOD + 50: return []

    atr = compute_atr(h1_candles, ATR_PERIOD)
    if atr is None: return []

    h1_swings = find_swings(h1_candles, SWING_LOOKBACK)
    if not h1_swings: return []

    bos_events, _, h1_trend = detect_bos_choch(h1_candles, h1_swings)
    if (bias == "bullish" and h1_trend == "down") or (bias == "bearish" and h1_trend == "up"): return []

    pools = find_liquidity_pools(h1_candles, h1_swings, atr, EQ_TOLERANCE_ATR)
    if USE_TIME_BASED_LIQUIDITY:
        pools += find_time_based_liquidity(h1_candles, h1_candles[-1]["epoch"])

    last_idx = len(h1_candles) - 1
    last = h1_candles[last_idx]
    out = []

    for bos in bos_events:
        if last_idx - bos.index > CONT_MAX_BARS_BOS_TO_TOUCH: continue
        if (bias == "bullish" and bos.direction != "up") or (bias == "bearish" and bos.direction != "down"): continue

        ob_idx, ob_high, ob_low = _find_cluster_ob_before_bos(h1_candles, bos.index, bias, atr)
        if ob_idx is None: continue

        # Width Filter: Reject OBs that are too wide
        if (ob_high - ob_low) < MIN_OB_WIDTH_ATR * atr: continue
        if (ob_high - ob_low) > MAX_CLUSTER_WIDTH_ATR * atr: continue
        if last_idx - ob_idx > CONT_MAX_OB_AGE: continue
        if not _has_eq_pool(pools, bias, ob_high, ob_low, atr): continue

        entry = (ob_high + ob_low) / 2
        if (bias == "bullish" and last["low"] > entry) or (bias == "bearish" and last["high"] < entry): continue

        if any(h1_candles[k]["low"] <= entry <= h1_candles[k]["high"] for k in range(bos.index + 1, last_idx)): continue

        confluences = ["EQH/EQL"]
        if _has_fvg(h1_candles, ob_idx, bos.index, bias, atr): confluences.append("FVG")
        if _idm_swept(h1_candles, ob_idx, bos.index, bias, entry, h1_swings): confluences.append("IDM")
        if _has_time_pool(pools, bias, ob_high, ob_low, atr): confluences.append("TIME_LIQ")

        if bias == "bullish":
            stop = ob_low - BUFFER_ATR * atr
            target, t_kind = _nearest_target_above(pools, entry, atr)
            if target is None: target, t_kind = entry + SYNTHETIC_TARGET_ATR * atr, "synthetic"
            if target <= entry or entry <= stop or (target - entry) < MIN_TARGET_ATR * atr: continue
            rr = (target - entry) / (entry - stop)
        else:
            stop = ob_high + BUFFER_ATR * atr
            target, t_kind = _nearest_target_below(pools, entry, atr)
            if target is None: target, t_kind = entry - SYNTHETIC_TARGET_ATR * atr, "synthetic"
            if target >= entry or stop <= entry or (entry - target) < MIN_TARGET_ATR * atr: continue
            rr = (entry - target) / (stop - entry)

        if rr < MIN_RR: continue
        out.append(ContinuationPatternCluster(
            direction=bias, ob_index=ob_idx, bos_index=bos.index, touch_index=last_idx,
            ob_high=ob_high, ob_low=ob_low, entry=entry, stop=stop, target=target, rr=rr,
            confluences=confluences, target_kind=t_kind, target_is_synthetic=(t_kind == "synthetic")
        ))

    return out
