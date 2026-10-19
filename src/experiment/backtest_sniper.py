"""Backtest: Sniper Model."""

import bisect, os
from ..config import RECOMMENDED_PAIRS, GRANULARITY, HTF_GRANULARITY, HTF_CANDLE_COUNT, REPORTS_DIR
from ..deriv_client import fetch_candles_paginated
from .sniper_m15_confirm import detect_sniper_signals

# Hardcoded core 11 for this test
CORE_11 = ["frxNZDUSD", "frxAUDJPY", "frxAUDNZD", "frxGBPAUD", "frxEURCAD", "frxUSDJPY", "frxEURUSD", "frxUSDSEK", "frxGBPCHF", "frxCADJPY", "frxGBPJPY"]
M15_GRANULARITY = 900

def main():
    trades = []
    for sym in CORE_11:
        h1 = fetch_candles_paginated(sym, GRANULARITY, 2500)
        m15 = fetch_candles_paginated(sym, M15_GRANULARITY, 8000)
        d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        
        if not h1 or not m15 or not d1: continue

        for i in range(200, len(h1)):
            h1_window = h1[:i+1]
            # Filter M15 to match H1 timestamp
            current_epoch = h1_window[-1]["epoch"]
            m15_window = [c for c in m15 if c["epoch"] <= current_epoch]
            if len(m15_window) < 50: continue

            pats = detect_sniper_signals(h1_window, m15_window, d1)
            for p in pats:
                # Simulate outcome using H1 candles (since trade spans hours/days)
                outcome = "timeout"
                for k in range(i+1, min(i+50, len(h1))):
                    if p.direction == "up":
                        if h1[k]["low"] <= p.stop: outcome = "loss"; break
                        if h1[k]["high"] >= p.target: outcome = "win"; break
                    else:
                        if h1[k]["high"] >= p.stop: outcome = "loss"; break
                        if h1[k]["low"] <= p.target: outcome = "win"; break
                
                rr = 3.0 if outcome == "win" else (-1.0 if outcome == "loss" else 0.0)
                trades.append({"outcome": outcome, "rr": rr})
    
    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    wr = (wins / (wins+losses) * 100) if (wins+losses) > 0 else 0
    net_r = (wins * 3.0) - losses
    exp = net_r / len(trades) if trades else 0

    print(f"\n--- SNIPER MODEL RESULTS ---")
    print(f"Signals: {len(trades)}")
    print(f"Win Rate: {wr:.1f}%")
    print(f"Expectancy: {exp:+.3f} R")
    print(f"Net R: {net_r:+.1f}")

if __name__ == "__main__":
    main()
