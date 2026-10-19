"""HTF POI + LTF Confirmation (Sweep -> CHoCH -> IDM -> OB Entry)."""

from dataclasses import dataclass
from typing import List
from ..smc import find_swings, detect_bos_choch, compute_atr
from ..config import ATR_PERIOD, SWING_LOOKBACK, BUFFER_ATR, MIN_TARGET_ATR

@dataclass
class HTFReversalPatternV2:
    direction: str
    d1_ob_high: float
    d1_ob_low: float
    sweep_index: int
    choch_index: int
    idm_index: int
    entry: float
    stop: float
    target: float
    rr: float

def _find_d1_obs(d1_candles):
    swings = find_swings(d1_candles, SWING_LOOKBACK)
    if not swings: return []
    bos_events, _, _ = detect_bos_choch(d1_candles, swings)
    obs = []
    
    # Look at the last 5 D1 BOS events
    for bos in bos_events[-5:]:
        ob_idx = None
        for j in range(bos.index - 1, max(0, bos.index - 15), -1):
            c = d1_candles[j]
            if bos.direction == "up" and c["close"] < c["open"]:
                ob_idx = j; break
            elif bos.direction == "down" and c["close"] > c["open"]:
                ob_idx = j; break
        
        if ob_idx is not None:
            obs.append({
                "direction": "bullish" if bos.direction == "up" else "bearish",
                "high": d1_candles[ob_idx]["high"],
                "low": d1_candles[ob_idx]["low"]
            })
    return obs

def detect_htf_ltf_v2(h1_candles, d1_candles):
    if len(h1_candles) < 100 or len(d1_candles) < 20: return []
    
    d1_obs = _find_d1_obs(d1_candles)
    if not d1_obs: return []
    
    h1_atr = compute_atr(h1_candles, ATR_PERIOD)
    if h1_atr is None: return []
    
    last_idx = len(h1_candles) - 1
    last = h1_candles[last_idx]
    out = []
    
    # Check if current H1 price is inside a D1 OB
    for ob in d1_obs:
        if ob["direction"] == "bullish":
            if last["low"] <= ob["high"] and last["high"] >= ob["low"]:
                
                # Look back over the last 30 bars for the sequence
                for i in range(last_idx - 30, last_idx - 3):
                    if i < 5: continue
                    
                    # 1. SWEEP (Low pierces previous low, close above)
                    prev_low = min(c["low"] for c in h1_candles[i-5:i])
                    if h1_candles[i]["low"] < prev_low and h1_candles[i]["close"] > prev_low:
                        
                        # 2. CHoCH (Must break a recent high after the sweep)
                        recent_high = max(c["high"] for c in h1_candles[i-3:i])
                        choch_idx = None
                        for j in range(i+1, min(i+10, last_idx)):
                            if h1_candles[j]["close"] > recent_high:
                                choch_idx = j
                                break
                        
                        if choch_idx:
                            # 3. IDM (First minor pullback after CHoCH)
                            # A pullback candle must take out the previous candle's low
                            idm_idx = None
                            for k in range(choch_idx + 1, last_idx):
                                if h1_candles[k]["low"] < h1_candles[k-1]["low"]:
                                    idm_idx = k
                                    break # Found the first valid pullback
                            
                            if idm_idx:
                                # 4. OB (Last bearish candle before CHoCH)
                                ob_idx = None
                                for m in range(choch_idx - 1, i, -1):
                                    if h1_candles[m]["close"] < h1_candles[m]["open"]:
                                        ob_idx = m; break
                                
                                if ob_idx:
                                    ob_high = h1_candles[ob_idx]["high"]
                                    ob_low = h1_candles[ob_idx]["low"]
                                    entry = (ob_high + ob_low) / 2
                                    stop = h1_candles[i]["low"] - (BUFFER_ATR * h1_atr)
                                    
                                    # 5. ENTRY (Price must tap the OB on this current bar)
                                    if last["low"] <= entry <= last["high"]:
                                        risk = entry - stop
                                        target = entry + (risk * 3.0) # 1:3 RR for this test
                                        
                                        if risk > 0 and (target - entry) > (MIN_TARGET_ATR * h1_atr):
                                            out.append(HTFReversalPatternV2(
                                                direction="bullish", d1_ob_high=ob["high"], d1_ob_low=ob["low"],
                                                sweep_index=i, choch_index=choch_idx, idm_index=idm_idx,
                                                entry=entry, stop=stop, target=target, rr=3.0
                                            ))
                                    break # Only take the first valid sequence

        elif ob["direction"] == "bearish":
            if last["low"] <= ob["high"] and last["high"] >= ob["low"]:
                
                for i in range(last_idx - 30, last_idx - 3):
                    if i < 5: continue
                    
                    # 1. SWEEP (High pierces previous high, close below)
                    prev_high = max(c["high"] for c in h1_candles[i-5:i])
                    if h1_candles[i]["high"] > prev_high and h1_candles[i]["close"] < prev_high:
                        
                        # 2. CHoCH (Must break a recent low)
                        recent_low = min(c["low"] for c in h1_candles[i-3:i])
                        choch_idx = None
                        for j in range(i+1, min(i+10, last_idx)):
                            if h1_candles[j]["close"] < recent_low:
                                choch_idx = j
                                break
                        
                        if choch_idx:
                            # 3. IDM (First minor pullback)
                            idm_idx = None
                            for k in range(choch_idx + 1, last_idx):
                                if h1_candles[k]["high"] > h1_candles[k-1]["high"]:
                                    idm_idx = k
                                    break
                            
                            if idm_idx:
                                # 4. OB (Last bullish candle before CHoCH)
                                ob_idx = None
                                for m in range(choch_idx - 1, i, -1):
                                    if h1_candles[m]["close"] > h1_candles[m]["open"]:
                                        ob_idx = m; break
                                
                                if ob_idx:
                                    ob_high = h1_candles[ob_idx]["high"]
                                    ob_low = h1_candles[ob_idx]["low"]
                                    entry = (ob_high + ob_low) / 2
                                    stop = h1_candles[i]["high"] + (BUFFER_ATR * h1_atr)
                                    
                                    # 5. ENTRY
                                    if last["low"] <= entry <= last["high"]:
                                        risk = stop - entry
                                        target = entry - (risk * 3.0)
                                        
                                        if risk > 0 and (entry - target) > (MIN_TARGET_ATR * h1_atr):
                                            out.append(HTFReversalPatternV2(
                                                direction="bearish", d1_ob_high=ob["high"], d1_ob_low=ob["low"],
                                                sweep_index=i, choch_index=choch_idx, idm_index=idm_idx,
                                                entry=entry, stop=stop, target=target, rr=3.0
                                            ))
                                    break
    return out
