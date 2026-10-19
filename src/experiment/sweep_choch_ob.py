"""Sweep -> CHoCH -> OB Reversal Model.

1. Finds a liquidity sweep (low pierced, close above).
2. Finds the subsequent CHoCH/BOS (close above recent swing high).
3. Defines the OB as the last bearish candle before the CHoCH move.
4. Looks for confluences near the OB (EQ, FVG, IDM).
5. Fires when price returns to the OB mid.
"""

from dataclasses import dataclass
from typing import List, Optional

from ..smc import (
    find_swings, find_liquidity_pools, find_time_based_liquidity, compute_atr,
)
from ..fvg import find_fvgs_in_range
from ..config import (
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR, BUFFER_ATR, MIN_RR,
    MIN_TARGET_ATR, MIN_OB_WIDTH_ATR, MIN_CONT_FVG_ATR,
    CONT_MAX_OB_AGE, HTF_SWING_LOOKBACK, USE_TIME_BASED_LIQUIDITY,
    PREFER_MAJOR_LIQ_ATR,
)
from .continuation_eq import (
    UPSIDE_KINDS, DOWNSIDE_KINDS, MAJOR_UPSIDE, MAJOR_DOWNSIDE,
    TIME_UPSIDE, TIME_DOWNSIDE, SYNTHETIC_TARGET_ATR
)


@dataclass
class SweepReversalPattern:
    direction: str
    ob_index: int
    sweep_index: int
    choch_index: int
    touch_index: int
    ob_high: float
    ob_low: float
    entry: float
    stop: float
    target: float
    rr: float
    confluences: List[str]
    target_kind: str


def detect_htf_bias(d1_candles) -> Optional[str]:
    if not d1_candles or len(d1_candles) < HTF_SWING_LOOKBACK * 2 + 10: return None
    swings = find_swings(d1_candles, HTF_SWING_LOOKBACK)
    if not swings: return None
    # Assuming detect_bos_choch is available or we just use a simple trend check
    # For this isolated experiment, we'll infer bias from the last 20 days structure
    # (Fallback if smc.detect_bos_choch isn't imported)
    from ..smc import detect_bos_choch
    _, _, trend = detect_bos_choch(d1_candles, swings)
    return "bullish" if trend == "up" else ("bearish" if trend == "down" else None)


def _has_eq_pool(pools, direction, ob_high, ob_low, atr) -> bool:
    tol = 3.0 * atr
    if direction == "bullish":
        return any(p.kind == "EQL" and p.price < ob_low and (ob_low - p.price) <= tol for p in pools)
    else:
        return any(p.kind == "EQH" and p.price > ob_high and (p.price - ob_high) <= tol for p in pools)


def _has_fvg(candles, ob_idx, choch_idx, direction, atr) -> bool:
    fvgs = find_fvgs_in_range(candles, ob_idx, choch_idx, direction, atr)
    return any((f["high"] - f["low"]) >= MIN_CONT_FVG_ATR * atr for f in fvgs)


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


def detect_sweep_choch_signals(candles, d1_candles):
    bias = detect_htf_bias(d1_candles)
    if bias is None or len(candles) < 100: return []

    atr = compute_atr(candles, ATR_PERIOD)
    if atr is None: return []

    swings = find_swings(candles, SWING_LOOKBACK)
    if not swings: return []

    pools = find_liquidity_pools(candles, swings, atr, EQ_TOLERANCE_ATR)
    if USE_TIME_BASED_LIQUIDITY:
        pools += find_time_based_liquidity(candles, candles[-1]["epoch"])

    last_idx = len(candles) - 1
    last = candles[last_idx]
    out = []

    # We look for a sweep and CHoCH that happened in the last 50 bars
    lookback = 50
    for i in range(max(1, last_idx - lookback), last_idx):
        
        # --- BULLISH REVERSAL (Sweep Low -> CHoCH Up) ---
        if bias == "bullish":
            # 1. Check for Sweep of a recent low (low < previous low, close > previous low)
            prev_low = min(c["low"] for c in candles[i-10:i])
            is_sweep = candles[i]["low"] < prev_low and candles[i]["close"] > prev_low
            
            if is_sweep:
                # 2. Find subsequent CHoCH (a strong close above a recent swing high)
                recent_high = max(c["high"] for c in candles[i-5:i])
                choch_idx = None
                for j in range(i+1, min(i+15, last_idx + 1)):
                    if candles[j]["close"] > recent_high:
                        choch_idx = j
                        break
                
                if choch_idx:
                    # 3. Find the OB (last bearish candle between sweep and choch)
                    ob_idx = None
                    for k in range(choch_idx - 1, i - 1, -1):
                        if candles[k]["close"] < candles[k]["open"]:
                            ob_idx = k; break
                    
                    if ob_idx:
                        ob_high, ob_low = candles[ob_idx]["high"], candles[ob_idx]["low"]
                        if (ob_high - ob_low) < MIN_OB_WIDTH_ATR * atr: continue
                        
                        # 4. Check confluences
                        has_eq = _has_eq_pool(pools, "bullish", ob_high, ob_low, atr)
                        has_fvg = _has_fvg(candles, ob_idx, choch_idx, "bullish", atr)
                        if not (has_eq or has_fvg): continue

                        entry = (ob_high + ob_low) / 2
                        stop = ob_low - BUFFER_ATR * atr
                        
                        # 5. Check if touch happened on the current bar
                        if last["low"] <= entry <= last["high"]:
                            target, t_kind = _nearest_target_above(pools, entry, atr)
                            if target is None: target, t_kind = entry + SYNTHETIC_TARGET_ATR * atr, "synthetic"
                            
                            if target > entry and entry > stop and (target - entry) >= MIN_TARGET_ATR * atr:
                                rr = (target - entry) / (entry - stop)
                                if rr >= 2.5: # Hardcode 2.5 for this test
                                    confl = []
                                    if has_eq: confl.append("EQH/EQL")
                                    if has_fvg: confl.append("FVG")
                                    out.append(SweepReversalPattern(
                                        direction="bullish", ob_index=ob_idx, sweep_index=i, choch_index=choch_idx,
                                        touch_index=last_idx, ob_high=ob_high, ob_low=ob_low, entry=entry, stop=stop,
                                        target=target, rr=rr, confluences=confl, target_kind=t_kind
                                    ))

        # --- BEARISH REVERSAL (Sweep High -> CHoCH Down) ---
        elif bias == "bearish":
            prev_high = max(c["high"] for c in candles[i-10:i])
            is_sweep = candles[i]["high"] > prev_high and candles[i]["close"] < prev_high
            
            if is_sweep:
                recent_low = min(c["low"] for c in candles[i-5:i])
                choch_idx = None
                for j in range(i+1, min(i+15, last_idx + 1)):
                    if candles[j]["close"] < recent_low:
                        choch_idx = j
                        break
                
                if choch_idx:
                    ob_idx = None
                    for k in range(choch_idx - 1, i - 1, -1):
                        if candles[k]["close"] > candles[k]["open"]:
                            ob_idx = k; break
                    
                    if ob_idx:
                        ob_high, ob_low = candles[ob_idx]["high"], candles[ob_idx]["low"]
                        if (ob_high - ob_low) < MIN_OB_WIDTH_ATR * atr: continue
                        
                        has_eq = _has_eq_pool(pools, "bearish", ob_high, ob_low, atr)
                        has_fvg = _has_fvg(candles, ob_idx, choch_idx, "bearish", atr)
                        if not (has_eq or has_fvg): continue

                        entry = (ob_high + ob_low) / 2
                        stop = ob_high + BUFFER_ATR * atr
                        
                        if last["low"] <= entry <= last["high"]:
                            target, t_kind = _nearest_target_below(pools, entry, atr)
                            if target is None: target, t_kind = entry - SYNTHETIC_TARGET_ATR * atr, "synthetic"
                            
                            if target < entry and stop > entry and (entry - target) >= MIN_TARGET_ATR * atr:
                                rr = (entry - target) / (stop - entry)
                                if rr >= 2.5:
                                    confl = []
                                    if has_eq: confl.append("EQH/EQL")
                                    if has_fvg: confl.append("FVG")
                                    out.append(SweepReversalPattern(
                                        direction="bearish", ob_index=ob_idx, sweep_index=i, choch_index=choch_idx,
                                        touch_index=last_idx, ob_high=ob_high, ob_low=ob_low, entry=entry, stop=stop,
                                        target=target, rr=rr, confluences=confl, target_kind=t_kind
                                    ))
    return out
