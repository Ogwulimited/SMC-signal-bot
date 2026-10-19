"""Sniper Model: H1 Sweep -> CHoCH -> OB + M15 Confirmation -> DOL Target."""

from dataclasses import dataclass
from typing import List, Optional
from ..smc import find_swings, detect_bos_choch, compute_atr, find_liquidity_pools, detect_sweeps
from ..config import ATR_PERIOD, SWING_LOOKBACK, BUFFER_ATR

@dataclass
class SniperPattern:
    direction: str
    h1_ob_high: float
    h1_ob_low: float
    h1_entry: float
    m15_choch_index: int
    stop: float
    target: float
    rr: float

def detect_sniper_signals(h1_window, m15_window, d1_candles):
    # 1. HTF Bias (D1)
    d1_swings = find_swings(d1_candles, 3)
    _, _, d1_trend = detect_bos_choch(d1_candles, d1_swings)
    if d1_trend is None: return []

    h1_atr = compute_atr(h1_window, ATR_PERIOD)
    if not h1_atr: return []
    
    # 2. Find Liquidity Pools & Sweeps (The Engine)
    h1_swings = find_swings(h1_window, SWING_LOOKBACK)
    pools = find_liquidity_pools(h1_window, h1_swings, h1_atr)
    sweeps = detect_sweeps(h1_window, pools, h1_atr)
    
    # 3. H1 Structure & CHoCH
    h1_bos, h1_choch, h1_trend = detect_bos_choch(h1_window, h1_swings)
    
    last_h1 = h1_window[-1]
    out = []

    # We need a recent sweep and a recent CHoCH
    if not sweeps or not h1_choch: return []
    
    # Look at the most recent sweep
    recent_sweep = sweeps[-1]
    sweep_idx = recent_sweep.index
    
    # Find a CHoCH that happened AFTER the sweep
    valid_choch = None
    for choch in h1_choch:
        if choch.index > sweep_idx:
            valid_choch = choch
            break

    if not valid_choch: return []
    
    # Direction of the trade is the direction of the CHoCH
    direction = valid_choch.direction # "up" or "down"
    
    # Check D1 alignment
    if (d1_trend == "up" and direction != "up") or (d1_trend == "down" and direction != "down"):
        return []

    # 4. Find the H1 OB that caused the CHoCH
    ob_idx = None
    for j in range(valid_choch.index - 1, max(0, valid_choch.index - 15), -1):
        c = h1_window[j]
        if direction == "up" and c["close"] < c["open"]: ob_idx = j; break
        elif direction == "down" and c["close"] > c["open"]: ob_idx = j; break
        
    if ob_idx is None: return []
    
    ob = h1_window[ob_idx]
    ob_high, ob_low = ob["high"], ob["low"]
    entry = (ob_high + ob_low) / 2
    
    # 5. Check if price is currently tapping the H1 OB
    if last_h1["low"] <= ob_high and last_h1["high"] >= ob_low:
        
        # 6. M15 Confirmation: Look for a CHoCH in the last 3 M15 candles inside the OB
        m15_swings = find_swings(m15_window[-20:], 2)
        if not m15_swings: return []
        
        m15_bos, m15_choch, m15_trend = detect_bos_choch(m15_window[-20:], m15_swings)
        
        valid_confirmation = False
        if direction == "up" and m15_trend == "up":
            if any(c.index > len(m15_window) - 4 for c in m15_choch):
                valid_confirmation = True
        elif direction == "down" and m15_trend == "down":
            if any(c.index > len(m15_window) - 4 for c in m15_choch):
                valid_confirmation = True
        
        if valid_confirmation:
            # 7. Find the Draw on Liquidity (Target)
            target = None
            if direction == "up":
                # Target the nearest unswept high
                for p in sorted([p for p in pools if p.price > entry and not p.swept], key=lambda x: x.price):
                    target = p.price
                    break
                stop = recent_sweep.pool_price - (BUFFER_ATR * h1_atr) # Stop below the original sweep
            else:
                for p in sorted([p for p in pools if p.price < entry and not p.swept], key=lambda x: -x.price):
                    target = p.price
                    break
                stop = recent_sweep.pool_price + (BUFFER_ATR * h1_atr)
                
            # If no major liquidity found, use a fixed 3R target
            if target is None:
                risk = (entry - stop) if direction == "up" else (stop - entry)
                target = entry + (risk * 3.0) if direction == "up" else entry - (risk * 3.0)

            # Calculate RR
            risk = (entry - stop) if direction == "up" else (stop - entry)
            reward = (target - entry) if direction == "up" else (entry - target)
            
            if risk > 0 and reward > 0:
                rr = reward / risk
                if rr >= 2.0: # Minimum 2R for this sniper model
                    out.append(SniperPattern(
                        direction=direction,
                        h1_ob_high=ob_high, h1_ob_low=ob_low, h1_entry=entry,
                        m15_choch_index=m15_choch[-1].index,
                        stop=stop, target=target, rr=rr
                    ))
    return out
