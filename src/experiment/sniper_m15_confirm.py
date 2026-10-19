"""Sniper Model: H1 Sweep -> CHoCH -> OB + M15 Confirmation -> 1:3 Target.

FIXES APPLIED:
- Bug 1: D1 uses only fully closed candles.
- Bug 2: M15 requires fully closed candles, uses a 96-candle window, and checks CHoCH after OB touch.
- Bug 4: Sweeps sorted by time, direction matched to CHoCH, time limits enforced.
- Bug 5: Minimum and maximum stop sizes enforced (0.5 to 3.0 ATR).
"""

from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime, timezone
from ..smc import find_swings, detect_bos_choch, compute_atr, find_liquidity_pools, detect_sweeps
from ..config import ATR_PERIOD, SWING_LOOKBACK, BUFFER_ATR

@dataclass
class SniperPattern:
    direction: str
    d1_trend: str
    h1_ob_high: float
    h1_ob_low: float
    h1_ob_index: int
    h1_entry: float
    stop: float
    target: float
    rr: float
    sweep_pool_kind: str
    sweep_time: int
    choch_time: int
    signal_time: int

def detect_sniper_signals(h1_window, m15_window, d1_window):
    # 1. D1 Bias (Bug 1: Only closed D1 candles)
    current_h1_epoch = h1_window[-1]["epoch"]
    closed_d1 = [c for c in d1_window if c["epoch"] + 86400 <= current_h1_epoch]
    
    if len(closed_d1) < 10: return []
    d1_swings = find_swings(closed_d1, 3)
    _, _, d1_trend = detect_bos_choch(closed_d1, d1_swings)
    if d1_trend is None: return []

    h1_atr = compute_atr(h1_window, ATR_PERIOD)
    if not h1_atr: return []
    
    h1_swings = find_swings(h1_window, SWING_LOOKBACK)
    if not h1_swings: return []

    pools = find_liquidity_pools(h1_window, h1_swings, h1_atr)
    sweeps = detect_sweeps(h1_window, pools, h1_atr)
    h1_bos, h1_choch, h1_trend = detect_bos_choch(h1_window, h1_swings)
    
    if not sweeps or not h1_choch: return []
    
    # Bug 4: Sort sweeps by index (time) to find the most recent
    sweeps = sorted(sweeps, key=lambda x: x.index)
    
    last_h1 = h1_window[-1]
    out = []

    for sweep in reversed(sweeps):
        sweep_idx = sweep.index
        # Look for a CHoCH after this sweep (within 10 bars)
        valid_choch = None
        for choch in h1_choch:
            if sweep_idx < choch.index <= sweep_idx + 10:
                # Bug 4: Sweep direction must be opposite to CHoCH direction
                if (sweep.direction == "up" and choch.direction == "down") or \
                   (sweep.direction == "down" and choch.direction == "up"):
                    valid_choch = choch
                    break
        
        if not valid_choch: continue
        direction = valid_choch.direction 

        # Check D1 alignment
        if (d1_trend == "up" and direction != "up") or (d1_trend == "down" and direction != "down"):
            continue

        # Find the H1 OB that caused the CHoCH
        ob_idx = None
        for j in range(valid_choch.index - 1, max(0, valid_choch.index - 15), -1):
            c = h1_window[j]
            if direction == "up" and c["close"] < c["open"]: ob_idx = j; break
            elif direction == "down" and c["close"] > c["open"]: ob_idx = j; break
            
        if ob_idx is None: continue
        
        # Bug 4: Signal (zone touch) must occur within 24 bars of CHoCH
        if not (valid_choch.index < len(h1_window) - 1 <= valid_choch.index + 24):
            continue

        ob = h1_window[ob_idx]
        ob_high, ob_low = ob["high"], ob["low"]
        entry = (ob_high + ob_low) / 2
        
        # Is current candle touching the OB?
        if not (last_h1["low"] <= ob_high and last_h1["high"] >= ob_low):
            continue
            
        # Bug 5: Risk filter (0.5 to 3.0 ATR)
        if direction == "up":
            stop = sweep.pool_price - (BUFFER_ATR * h1_atr)
            risk = entry - stop
        else:
            stop = sweep.pool_price + (BUFFER_ATR * h1_atr)
            risk = stop - entry
            
        if not (0.5 * h1_atr <= risk <= 3.0 * h1_atr): 
            continue

        # Bug 2: M15 Confirmation (Only closed candles, 96-candle window, CHoCH must be recent)
        closed_m15 = [c for c in m15_window if c["epoch"] + 900 <= current_h1_epoch + 3600]
        if len(closed_m15) < 96: continue
        
        m15_recent = closed_m15[-96:]
        m15_swings = find_swings(m15_recent, 2)
        if not m15_swings: continue
        
        m15_bos, m15_choch, m15_trend = detect_bos_choch(m15_recent, m15_swings)
        
        valid_confirmation = False
        # Require CHoCH in the last 16 bars (4 hours) to align with the H1 touch
        if direction == "up" and m15_trend == "up":
            if any(c.index >= len(m15_recent) - 16 for c in m15_choch): valid_confirmation = True
        elif direction == "down" and m15_trend == "down":
            if any(c.index >= len(m15_recent) - 16 for c in m15_choch): valid_confirmation = True
            
        if not valid_confirmation: continue

        # Target Calculation (Hard 1:3)
        target = entry + (risk * 3.0) if direction == "up" else entry - (risk * 3.0)
        
        out.append(SniperPattern(
            direction=direction,
            d1_trend=d1_trend,
            h1_ob_high=ob_high, h1_ob_low=ob_low, h1_ob_index=ob_idx,
            h1_entry=entry, stop=stop, target=target, rr=3.0,
            sweep_pool_kind=sweep.pool_kind,
            sweep_time=h1_window[sweep.index]["epoch"],
            choch_time=h1_window[valid_choch.index]["epoch"],
            signal_time=last_h1["epoch"]
        ))
        break # Only take the most recent valid setup per bar
    return out
