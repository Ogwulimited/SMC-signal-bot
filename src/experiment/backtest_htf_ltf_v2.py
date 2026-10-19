"""Backtest for HTF POI + LTF (Sweep -> CHoCH -> IDM -> OB) Model."""

import bisect, os, random
from datetime import datetime, timezone
from ..config import RECOMMENDED_PAIRS, GRANULARITY, DETECT_WINDOW, HTF_GRANULARITY, HTF_CANDLE_COUNT, MAX_HORIZON_BARS, REPORTS_DIR
from ..deriv_client import fetch_candles_paginated
from ..smc import compute_atr
from .htf_ltf_reversal_v2 import detect_htf_ltf_v2

BACKTEST_H1_CANDLES = 4000
WARMUP_BARS = 500

def log(m): print(m, flush=True)

def simulate(candles, entry, stop, target, direction, start_idx):
    end = min(start_idx + MAX_HORIZON_BARS, len(candles))
    for k in range(start_idx + 1, end):
        c = candles[k]
        if direction == "bullish":
            if c["low"] <= stop: return "loss", 1.0
            if c["high"] >= target: return "win", 3.0
        else:
            if c["high"] >= stop: return "loss", 1.0
            if c["low"] <= target: return "win", 3.0
    return "timeout", 0.0

def main():
    random.seed(42)
    log("Running HTF POI + LTF (Sweep -> CHoCH -> IDM -> OB) Backtest...")
    trades = []
    
    for sym_idx, sym in enumerate(RECOMMENDED_PAIRS, 1):
        log(f"[{sym_idx}/{len(RECOMMENDED_PAIRS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_H1_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception: continue
        if not h1 or not d1: continue

        d1_epochs = [c["epoch"] for c in d1]
        
        for i in range(WARMUP_BARS, len(h1) - MAX_HORIZON_BARS - 1):
            w_start = max(0, i + 1 - DETECT_WINDOW)
            h1_window = h1[w_start : i + 1]
            
            d1_end_idx = bisect.bisect_right(d1_epochs, h1_window[-1]["epoch"])
            if d1_end_idx < 20: continue
            d1_window = d1[:d1_end_idx]

            try:
                pats = detect_htf_ltf_v2(h1_window, d1_window)
            except Exception:
                continue

            for p in pats:
                outcome, rr = simulate(h1, p.entry, p.stop, p.target, p.direction, i)
                trades.append({"outcome": outcome, "rr": rr})

    wins = sum(1 for t in trades if t["outcome"] == "win")
    losses = sum(1 for t in trades if t["outcome"] == "loss")
    timeouts = sum(1 for t in trades if t["outcome"] == "timeout")
    
    resolved = wins + losses
    wr = (wins / resolved * 100) if resolved > 0 else 0
    net_r = (wins * 3.0) - losses
    exp = net_r / len(trades) if trades else 0

    log(f"\nRESULTS: n={len(trades)} WR={wr:.1f}% Exp={exp:+.3f}R NetR={net_r:+.1f} (W:{wins}/L:{losses}/T:{timeouts})")
    
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "htf_ltf_v2_latest.md"), "w") as f:
        f.write("# Experiment: HTF POI + LTF (Sweep -> CHoCH -> IDM -> OB)\n\n")
        f.write(f"- **Signals:** {len(trades)}\n")
        f.write(f"- **Win Rate:** {wr:.1f}%\n")
        f.write(f"- **Expectancy:** {exp:+.3f} R\n")
        f.write(f"- **Net R:** {net_r:+.1f}\n")

if __name__ == "__main__":
    main()
