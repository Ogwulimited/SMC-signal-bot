"""Backtest: Strict Sniper Model on 32 Forex pairs."""

import bisect
import os
from datetime import datetime, timezone

from ..config import (
    GRANULARITY, HTF_GRANULARITY, HTF_CANDLE_COUNT, 
    MAX_HORIZON_BARS, ATR_PERIOD, REPORTS_DIR
)
from ..deriv_client import fetch_candles_paginated
from ..smc import compute_atr
from .sniper_m15_confirm import detect_sniper_signals

# The 32 Pairs
PAIRS_32 = [
    "frxEURUSD", "frxGBPUSD", "frxAUDUSD", "frxUSDCAD", "frxUSDCHF",
    "frxUSDJPY", "frxNZDUSD",
    "frxEURGBP", "frxEURJPY", "frxGBPJPY", "frxAUDJPY", "frxEURAUD",
    "frxGBPAUD", "frxCADJPY", "frxNZDJPY", "frxGBPCHF", "frxEURNZD",
    "frxAUDCAD", "frxAUDCHF", "frxAUDNZD", "frxEURCAD", "frxEURCHF",
    "frxGBPCAD", "frxGBPNZD", "frxNZDCAD", "frxNZDCHF", "frxCADCHF",
    "frxCHFJPY",
    "frxEURSGD", "frxUSDNOK", "frxUSDSEK", "frxUSDTRY"
]

M15_GRANULARITY = 900
BACKTEST_H1_CANDLES = 3000
BACKTEST_M15_CANDLES = 12000
WARMUP_BARS = 200

def log(m):
    print(m, flush=True)

def simulate(candles, entry, stop, target, direction, start_idx):
    end = min(start_idx + MAX_HORIZON_BARS, len(candles))
    for k in range(start_idx + 1, end):
        c = candles[k]
        if direction == "bullish" or direction == "up":
            if c["low"] <= stop: return "loss", 1.0
            if c["high"] >= target: return "win", (target - entry) / (entry - stop)
        else:
            if c["high"] >= stop: return "loss", 1.0
            if c["low"] <= target: return "win", (entry - target) / (stop - entry)
    return "timeout", 0.0

def _write_report(trades, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    timeouts = [t for t in trades if t["outcome"] == "timeout"]
    
    resolved = len(wins) + len(losses)
    wr = (len(wins) / resolved * 100) if resolved > 0 else 0
    net_r = sum(t["rr"] for t in wins) - len(losses)
    exp = net_r / len(trades) if trades else 0

    md = []
    md.append("# Experiment: Strict Sniper Model on 32 Pairs\n")
    md.append(f"**Generated:** {gen}\n")
    md.append("## Results\n")
    md.append(f"- **Signals:** {len(trades)}")
    md.append(f"- **Wins:** {len(wins)}")
    md.append(f"- **Losses:** {len(losses)}")
    md.append(f"- **Timeouts:** {len(timeouts)}")
    md.append(f"- **Win Rate:** **{wr:.1f}%**")
    md.append(f"- **Expectancy:** **{exp:+.3f} R**")
    md.append(f"- **Net R:** **{net_r:+.1f}**")
    if wins:
        md.append(f"- **Avg Win R:R:** {sum(t['rr'] for t in wins) / len(wins):.2f} R")
    md.append("\n### Per Symbol Breakdown\n")
    md.append("| Symbol | Signals | Wins | Losses | Net R |")
    md.append("|--------|---------|------|--------|-------|")
    
    # Group by symbol
    for sym in PAIRS_32:
        sym_trades = [t for t in trades if t["symbol"] == sym]
        if not sym_trades: continue
        s_wins = sum(1 for t in sym_trades if t["outcome"] == "win")
        s_losses = sum(1 for t in sym_trades if t["outcome"] == "loss")
        s_net = sum(t["rr"] for t in sym_trades if t["outcome"] == "win") - s_losses
        md.append(f"| {sym} | {len(sym_trades)} | {s_wins} | {s_losses} | {s_net:+.1f} |")

    with open(os.path.join(out_dir, "sniper_32_latest.md"), "w") as f:
        f.write("\n".join(md))
    
    log(f"\nReport written to {out_dir}/sniper_32_latest.md")


def main():
    log(f"Strict Sniper Model Backtest on 32 Pairs")
    all_trades = []

    for sym_idx, sym in enumerate(PAIRS_32, 1):
        log(f"[{sym_idx}/{len(PAIRS_32)}] Fetching {sym}...")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_H1_CANDLES)
            m15 = fetch_candles_paginated(sym, M15_GRANULARITY, BACKTEST_M15_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception as e:
            log(f"  Fetch failed: {e}")
            continue

        if not h1 or not m15 or not d1: continue

        m15_epochs = [c["epoch"] for c in m15]
        
        for i in range(WARMUP_BARS, len(h1) - MAX_HORIZON_BARS - 1):
            h1_window = h1[:i+1]
            current_epoch = h1_window[-1]["epoch"]

            m15_end_idx = bisect.bisect_right(m15_epochs, current_epoch)
            if m15_end_idx < 50: continue
            
            m15_window = m15[:m15_end_idx]
            d1_window = d1[:bisect.bisect_right([c["epoch"] for c in d1], current_epoch)]

            # Using the STRICT detector
            pats = detect_sniper_signals(h1_window, m15_window, d1_window)

            for p in pats:
                outcome, rr = simulate(h1, p.h1_entry, p.stop, p.target, p.direction, i)
                all_trades.append({
                    "outcome": outcome,
                    "rr": round(rr, 2),
                    "symbol": sym,
                    "direction": p.direction
                })

    config_snap = {
        "pairs": len(PAIRS_32),
        "h1_candles": BACKTEST_H1_CANDLES,
        "m15_candles": BACKTEST_M15_CANDLES,
        "min_rr": 2.0,
        "logic": "Strict Sweep -> CHoCH -> M15 Confirm in last 5 candles"
    }
    _write_report(all_trades, config_snap)

if __name__ == "__main__":
    main()
