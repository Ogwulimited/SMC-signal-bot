"""Continuation model — EQ-gated production detector.

Quality gate: OB passes if an EQH/EQL liquidity pool exists nearby
(within CONT_LIQUIDITY_TOL_ATR × ATR). FVG is NO LONGER required.

IDM, FVG, and TIME_LIQ are recorded as confluences and used to compute a
signal score, but they do not gate the entry.

Same entry, stop, target, touch logic as the live v1 detector. Only the
quality gate changed.
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

UPSIDE_KINDS = ("EQH", "swing_high", "PDH", "weekly_high",
                "asia_high", "london_high", "ny_high")
DOWNSIDE_KINDS = ("EQL", "swing_low", "PDL", "weekly_low",
                  "asia_low", "london_low", "ny_low")

MAJOR_UPSIDE = ("PDH", "weekly_high", "asia_high", "london_high", "ny_high")
MAJOR_DOWNSIDE = ("PDL", "weekly_low", "asia_low", "london_low", "ny_low")

TIME_UPSIDE = ("PDH", "weekly_high", "asia_high", "london_high", "ny_high")
TIME_DOWNSIDE = ("PDL", "weekly_low", "asia_low", "london_low", "ny_low")


@dataclass
class ContinuationPatternEQ:
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


# ---------------- helpers ----------------

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


def _has_eq_pool(pools, direction, ob_high, ob_low, atr) -> bool:
    tol = CONT_LIQUIDITY_TOL_ATR * atr
    if direction == "bullish":
        for p in pools:
            if p.kind == "EQL" and p.price < ob_low and (ob_low - p.price) <= tol:
                return True
    else:
        for p in pools:
            if p.kind == "EQH" and p.price > ob_high and (p.price - ob_high) <= tol:
                return True
    return False


def _has_time_pool(pools, direction, ob_high, ob_low, atr) -> bool:
    tol = CONT_LIQUIDITY_TOL_ATR * atr
    if direction == "bullish":
        for p in pools:
            if p.kind in TIME_DOWNSIDE and p.price < ob_low and (ob_low - p.price) <= tol:
                return True
    else:
        for p in pools:
            if p.kind in TIME_UPSIDE and p.price > ob_high and (p.price - ob_high) <= tol:
                return True
    return False


def _has_fvg(candles, ob_idx, bos_idx, direction, atr) -> bool:
    fvgs = find_fvgs_in_range(candles, ob_idx, bos_idx, direction, atr)
    min_size = MIN_CONT_FVG_ATR * atr
    for f in fvgs:
        if (f["high"] - f["low"]) >= min_size:
            return True
    return False


def _idm_swept(candles, ob_idx, bos_idx, direction, entry, swings,
                max_sweep_age=30) -> bool:
    last_idx = len(candles) - 1
    if direction == "bullish":
        cands = [s for s in swings if s.kind == "low"
                 and bos_idx < s.index < last_idx and s.price > entry]
        for c in cands:
            start = max(c.index + 1, last_idx - max_sweep_age)
            for j in range(start, last_idx):
                if candles[j]["low"] < c.price:
                    return True
        return False
    else:
        cands = [s for s in swings if s.kind == "high"
                 and bos_idx < s.index < last_idx and s.price < entry]
        for c in cands:
            start = max(c.index + 1, last_idx - max_sweep_age)
            for j in range(start, last_idx):
                if candles[j]["high"] > c.price:
                    return True
        return False


def _nearest_target_above(pools, price, atr):
    major = [p for p in pools if p.price > price and not p.swept
             and p.kind in MAJOR_UPSIDE]
    if major:
        best_major = min(major, key=lambda p: p.price)
        if (best_major.price - price) <= PREFER_MAJOR_LIQ_ATR * atr:
            return best_major.price, best_major.kind
    cand = [p for p in pools if p.price > price and not p.swept
            and p.kind in UPSIDE_KINDS]
    if cand:
        best = min(cand, key=lambda p: p.price)
        return best.price, best.kind
    return None, None


def _nearest_target_below(pools, price, atr):
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


def compute_score(pattern) -> float:
    """Score = RR + 3×IDM + 0.5×FVG + 0.5×TIME. EQ is always present (base gate)."""
    score = pattern.rr
    if "IDM" in pattern.confluences:
        score += 3.0
    if "FVG" in pattern.confluences:
        score += 0.5
    if "TIME_LIQ" in pattern.confluences:
        score += 0.5
    return score


# ---------------- main detector ----------------

def detect_continuation_signals_eq(h1_candles, d1_candles):
    """Detect continuation signals whose OB passes the EQ gate.

    Returns list of ContinuationPatternEQ firing on the current (last) bar.
    """
    bias = detect_htf_bias(d1_candles)
    if bias is None:
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
        return []
    if bias == "bearish" and h1_trend == "up":
        return []

    pools = find_liquidity_pools(h1_candles, h1_swings, atr, EQ_TOLERANCE_ATR)
    if USE_TIME_BASED_LIQUIDITY:
        time_pools = find_time_based_liquidity(h1_candles, h1_candles[-1]["epoch"])
        pools = pools + time_pools

    last_idx = len(h1_candles) - 1
    last = h1_candles[last_idx]

    out: List[ContinuationPatternEQ] = []

    for bos in bos_events:
        if last_idx - bos.index > CONT_MAX_BARS_BOS_TO_TOUCH:
            continue
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

        if (ob_high - ob_low) < MIN_OB_WIDTH_ATR * atr:
            continue
        if last_idx - ob_idx > CONT_MAX_OB_AGE:
            continue

        # EQ gate — required
        if not _has_eq_pool(pools, bias, ob_high, ob_low, atr):
            continue

        entry = (ob_high + ob_low) / 2

        # Current-bar touch
        if bias == "bullish":
            if last["low"] > entry:
                continue
        else:
            if last["high"] < entry:
                continue

        # Prior-touch guard
        touched_before = False
        for k in range(bos.index + 1, last_idx):
            c = h1_candles[k]
            if c["low"] <= entry <= c["high"]:
                touched_before = True
                break
        if touched_before:
            continue

        # Confluences for scoring (EQ is guaranteed)
        confluences = ["EQH/EQL"]
        if _has_fvg(h1_candles, ob_idx, bos.index, bias, atr):
            confluences.append("FVG")
        if _idm_swept(h1_candles, ob_idx, bos.index, bias, entry, h1_swings):
            confluences.append("IDM")
        if _has_time_pool(pools, bias, ob_high, ob_low, atr):
            confluences.append("TIME_LIQ")

        # Target + R:R
        target_is_synthetic = False
        if bias == "bullish":
            stop = ob_low - BUFFER_ATR * atr
            target, target_kind = _nearest_target_above(pools, entry, atr)
            if target is None:
                target = entry + SYNTHETIC_TARGET_ATR * atr
                target_kind = "synthetic"
                target_is_synthetic = True
            if target <= entry or entry <= stop:
                continue
            if (target - entry) < MIN_TARGET_ATR * atr:
                continue
            rr = (target - entry) / (entry - stop)
        else:
            stop = ob_high + BUFFER_ATR * atr
            target, target_kind = _nearest_target_below(pools, entry, atr)
            if target is None:
                target = entry - SYNTHETIC_TARGET_ATR * atr
                target_kind = "synthetic"
                target_is_synthetic = True
            if target >= entry or stop <= entry:
                continue
            if (entry - target) < MIN_TARGET_ATR * atr:
                continue
            rr = (entry - target) / (stop - entry)

        if rr < MIN_RR:
            continue

        out.append(ContinuationPatternEQ(
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
            confluences=confluences,
            target_kind=target_kind,
            target_is_synthetic=target_is_synthetic,
        ))

    return out


def pattern_signature(symbol, timeframe, p):
    return f"{symbol}|{timeframe}|{p.direction}|{p.sweep_idx if hasattr(p, 'sweep_idx') else p.ob_index}"
