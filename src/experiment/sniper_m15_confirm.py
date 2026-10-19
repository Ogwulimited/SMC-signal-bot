"""Sniper Model: H1 Sweep -> CHoCH -> OB + M15 Confirmation -> 1:3 Day Trade Target."""

from dataclasses import dataclass
from typing import List
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
    d1_swings = find_swings(d1_candles, 3)
    _, _, d1_trend = detect_bos_choch(d1_candles, d1_swings)
    if d1_trend is None: return []

    h1_atr = compute_atr(h1_window, ATR_PERIOD)
    if not h1_atr: return []
    
    h1_swings = find_swings(h1_window, SWING_LOOKBACK)
    pools = find_liquidity_pools(h1_window, h1_swings, h1_atr)
    sweeps = detect_sweeps(h1_window, pools, h1_atr)
    
    h1_bos, h1_choch, h1_trend = detect_bos_choch(h1_window, h1_swings)
    
    last_h1 = h1_window[-1]
    out = []

    if not sweeps or not h1_choch: return []
    
    recent_sweep = sweeps[-1]
    sweep_idx = recent_sweep.index
    
    valid_choch = None
    for choch in h1_choch:
        if choch.index > sweep_idx:
            valid_choch = choch
            break

    if not valid_choch: return []
    direction = valid_choch.direction 
    
    if (d1_trend == "up" and direction != "up") or (d1_trend == "down" and direction != "down"):
        return []

    ob_idx = None
    for j in range(valid_choch.index - 1, max(0, valid_choch.index - 15), -1):
        c = h1_window[j]
        if direction == "up" and c["close"] < c["open"]: ob_idx = j; break
        elif direction == "down" and c["close"] > c["open"]: ob_idx = j; break
        
    if ob_idx is None: return []
    
    ob = h1_window[ob_idx]
    ob_high, ob_low = ob["high"], ob["low"]
    entry = (ob_high + ob_low) / 2
    
    if last_h1["low"] <= ob_high and last_h1["high"] >= ob_low:
        
        m15_recent = m15_window[-30:]
        if len(m15_recent) < 30: return []
        
        m15_swings = find_swings(m15_recent, 2)
        if not m15_swings: return []
        
        m15_bos, m15_choch, m15_trend = detect_bos_choch(m15_recent, m15_swings)
        
        valid_confirmation = False
        if direction == "up" and m15_trend == "up":
            if any(c.index >= 25 for c in m15_choch): valid_confirmation = True
        elif direction == "down" and m15_trend == "down":
            if any(c.index >= 25 for c in m15_choch): valid_confirmation = True
        
        if valid_confirmation:
            # --- DAY TRADE TARGET LOGIC (HARD 1:3) ---
            if direction == "up":
                stop = recent_sweep.pool_price - (BUFFER_ATR * h1_atr)
                risk = entry - stop
                if risk <= 0: return []
                target = entry + (risk * 3.0) # Hard 3R Target
            else:
                stop = recent_sweep.pool_price + (BUFFER_ATR * h1_atr)
                risk = stop - entry
                if risk <= 0: return []
                target = entry - (risk * 3.0) # Hard 3R Target

            out.append(SniperPattern(
                direction=direction,
                h1_ob_high=ob_high, h1_ob_low=ob_low, h1_entry=entry,
                m15_choch_index=40, 
                stop=stop, target=target, rr=3.0
            ))
    return out
