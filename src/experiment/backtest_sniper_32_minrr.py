"""Backtest: Strict Sniper Model (VALIDATION PHASE).

FIXES APPLIED:
- Bug 1 (Cancel logic): Fixed to only cancel if target hit before entry. Stop can only hit AFTER entry.
- Bug 2 (Dedup key): Uses the OB epoch instead of the sliding window index.
- Bug 3 (Time split/Drawdown): Trades sorted chronologically by fill_time. 60/40 split. Added monthly stats, % within 24 bars, and max drawdown on the sorted equity curve.
- Bug 4 (Errors): Exceptions are caught and counted.
- Bug 5 (Controls): Controls use the exact same entry time, price, and risk, but a random direction.
"""

import bisect
import csv
import os
import random
from datetime import datetime, timezone
from ..config import (
    GRANULARITY, HTF_GRANULARITY, MAX_HORIZON_BARS, ATR_PERIOD, 
    SPREAD_ATR_FRAC, REPORTS_DIR, RECOMMENDED_PAIRS
)
from ..deriv_client import fetch_candles_paginated
from ..smc import compute_atr
from .sniper_m15_confirm import detect_sniper_signals

MAX_WAIT_FOR_FILL_BARS = 30
M15_GRANULARITY = 900
BACKTEST_H1_CANDLES = 3000
BACKTEST_M15_CANDLES = 12000

def log(m):
    print(m, flush=True)

def format_time(epoch):
    if epoch is None: return ""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

def main():
    random.seed(42)
    log("Starting Sniper Validation Backtest...")
    
    trades = []
    controls = []
    err_count = 0
    
    for sym_idx, sym in enumerate(RECOMMENDED_PAIRS, 1):
        log(f"[{sym_idx}/{len(RECOMMENDED_PAIRS)}] Fetching {sym}...")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_H1_CANDLES)
            m15 = fetch_candles_paginated(sym, M15_GRANULARITY, BACKTEST_M15_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, 500)
            if not h1 or not m15 or not d1: continue
        except Exception as e:
            log(f"  Failed to fetch {sym}: {e}")
            continue

        m15_epochs = [c["epoch"] for c in m15]
        d1_epochs = [c["epoch"] for c in d1]
        
        active_trade_until = 0
        seen_obs = set()

        # Bug 9: Live only sees 200 candles
        for i in range(200, len(h1) - MAX_HORIZON_BARS - MAX_WAIT_FOR_FILL_BARS - 1):
            if h1[i]["epoch"] < active_trade_until:
                continue
                
            h1_window = h1[i-199 : i+1]
            current_epoch = h1_window[-1]["epoch"]
            
            m15_end_idx = bisect.bisect_right(m15_epochs, current_epoch + 3600 - 900)
            d1_end_idx = bisect.bisect_right(d1_epochs, current_epoch - 86400)
            
            if m15_end_idx < 96 or d1_end_idx < 20: continue
                
            m15_window = m15[:m15_end_idx]
            d1_window = d1[:d1_end_idx]
            
            try:
                pats = detect_sniper_signals(h1_window, m15_window, d1_window)
            except Exception as e:
                err_count += 1
                continue

            for p in pats:
                # Bug 2: Dedup by OB Epoch
                ob_epoch = h1_window[p.h1_ob_index]["epoch"]
                ob_key = (sym, ob_epoch)
                if ob_key in seen_obs: continue
                seen_obs.add(ob_key)
                
                atr = compute_atr(h1_window, ATR_PERIOD)
                risk = abs(p.h1_entry - p.stop)
                spread = SPREAD_ATR_FRAC * atr
                spread_r = spread / risk

                # Bug 1: Correct Pending Order Simulation
                fill_idx = None
                for k in range(i+1, min(i+1+MAX_WAIT_FOR_FILL_BARS, len(h1))):
                    c = h1[k]
                    if p.direction == "up":
                        if c["low"] <= p.h1_entry: 
                            fill_idx = k
                            break
                        if c["high"] >= p.target: break   # Ran away without filling
                    else:
                        if c["high"] >= p.h1_entry: 
                            fill_idx = k
                            break
                        if c["low"] <= p.target: break
                        
                if fill_idx is None:
                    trades.append({
                        "symbol": sym, "direction": p.direction, "d1_trend": p.d1_trend,
                        "sweep_pool_kind": p.sweep_pool_kind, "sweep_time": format_time(p.sweep_time),
                        "choch_time": format_time(p.choch_time), "signal_time": format_time(p.signal_time),
                        "fill_time": "", "exit_time": "", "entry": p.h1_entry, "stop": p.stop,
                        "target": p.target, "risk_atr": risk/atr, "spread_r": spread_r,
                        "outcome": "cancelled", "r_result": 0.0, "bars_to_fill": None,
                        "bars_in_trade": None, "exit_price": None
                    })
                    continue
                
                # Trade filled
                fill_time = h1[fill_idx]["epoch"]
                bars_to_fill = fill_idx - i
                active_trade_until = fill_time + (MAX_HORIZON_BARS * 3600)

                outcome = "timeout"
                exit_price = h1[fill_idx + MAX_HORIZON_BARS]["close"]
                exit_idx = fill_idx + MAX_HORIZON_BARS
                
                fill_c = h1[fill_idx]
                # If stop is hit on the same bar we fill, it's a loss.
                if (p.direction == "up" and fill_c["low"] <= p.stop) or \
                   (p.direction == "down" and fill_c["high"] >= p.stop):
                    outcome = "loss"
                    exit_price = p.stop
                    exit_idx = fill_idx
                else:
                    for k in range(fill_idx + 1, fill_idx + MAX_HORIZON_BARS):
                        c = h1[k]
                        if p.direction == "up":
                            if c["low"] <= p.stop: outcome = "loss"; exit_price = p.stop; exit_idx = k; break
                            if c["high"] >= p.target: outcome = "win"; exit_price = p.target; exit_idx = k; break
                        else:
                            if c["high"] >= p.stop: outcome = "loss"; exit_price = p.stop; exit_idx = k; break
                            if c["low"] <= p.target: outcome = "win"; exit_price = p.target; exit_idx = k; break

                if outcome == "win": r_result = 3.0 - spread_r
                elif outcome == "loss": r_result = -1.0 - spread_r
                else:
                    if p.direction == "up": r_result = (exit_price - p.h1_entry) / risk - spread_r
                    else: r_result = (p.h1_entry - exit_price) / risk - spread_r

                trades.append({
                    "symbol": sym, "direction": p.direction, "d1_trend": p.d1_trend,
                    "sweep_pool_kind": p.sweep_pool_kind, "sweep_time": format_time(p.sweep_time),
                    "choch_time": format_time(p.choch_time), "signal_time": format_time(p.signal_time),
                    "fill_time": format_time(fill_time), "exit_time": format_time(h1[exit_idx]["epoch"]),
                    "entry": p.h1_entry, "stop": p.stop, "target": p.target,
                    "risk_atr": round(risk/atr, 2), "spread_r": round(spread_r, 3),
                    "outcome": outcome, "r_result": round(r_result, 2),
                    "bars_to_fill": bars_to_fill, "bars_in_trade": exit_idx - fill_idx, "exit_price": exit_price
                })

                # CONTROL TRADE
                c_dir = random.choice(["up", "down"])
                c_stop = p.h1_entry - risk if c_dir == "up" else p.h1_entry + risk
                c_target = p.h1_entry + (risk * 3.0) if c_dir == "up" else p.h1_entry - (risk * 3.0)
                
                c_outcome = "timeout"
                c_exit_price = h1[fill_idx + MAX_HORIZON_BARS]["close"]
                
                if (c_dir == "up" and fill_c["low"] <= c_stop) or (c_dir == "down" and fill_c["high"] >= c_stop):
                    c_outcome = "loss"
                else:
                    for k in range(fill_idx + 1, fill_idx + MAX_HORIZON_BARS):
                        c = h1[k]
                        if c_dir == "up":
                            if c["low"] <= c_stop: c_outcome = "loss"; break
                            if c["high"] >= c_target: c_outcome = "win"; break
                        else:
                            if c["high"] >= c_stop: c_outcome = "loss"; break
                            if c["low"] <= c_target: c_outcome = "win"; break
                            
                if c_outcome == "win": c_r = 3.0 - spread_r
                elif c_outcome == "loss": c_r = -1.0 - spread_r
                else: c_r = ((c_exit_price - p.h1_entry) / risk if c_dir == "up" else (p.h1_entry - c_exit_price) / risk) - spread_r
                
                controls.append({
                    "symbol": sym, "entry_time": format_time(fill_time), "direction": c_dir,
                    "entry": p.h1_entry, "stop": c_stop, "target": c_target,
                    "risk_atr": round(risk/atr, 2), "outcome": c_outcome, "r_result": round(c_r, 2)
                })

    # --- BUG 3: CHRONOLOGICAL SORTING ---
    filled = [t for t in trades if t["outcome"] in ("win", "loss", "timeout")]
    filled.sort(key=lambda t: t["fill_time"])
    controls.sort(key=lambda t: t["entry_time"])
    
    cancelled = [t for t in trades if t["outcome"] == "cancelled"]
    wins = [t for t in filled if t["outcome"] == "win"]
    losses = [t for t in filled if t["outcome"] == "loss"]
    timeouts = [t for t in filled if t["outcome"] == "timeout"]
    
    total_r = sum(t["r_result"] for t in filled)
    win_rate = (len(wins) / len(filled) * 100) if filled else 0
    exp = total_r / len(filled) if filled else 0
    
    # Max Drawdown (Sequential)
    equity = 0
    peak = 0
    max_dd = 0
    for t in filled:
        equity += t["r_result"]
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)

    # 60/40 Time Split
    split_idx = int(len(filled) * 0.6)
    first_60 = filled[:split_idx]
    last_40 = filled[split_idx:]
    
    def calc_stats(subset):
        if not subset: return 0, 0
        r = sum(t["r_result"] for t in subset)
        wr = (sum(1 for t in subset if t["outcome"] == "win") / len(subset) * 100)
        return round(wr, 1), round(r, 1)

    h1_wr, h1_r = calc_stats(first_60)
    h2_wr, h2_r = calc_stats(last_40)

    # Percentage closed within 24 bars (1 day)
    closed_fast = sum(1 for t in filled if t["bars_in_trade"] is not None and t["bars_in_trade"] <= 24)
    pct_fast = (closed_fast / len(filled) * 100) if filled else 0

    # Monthly Stats
    monthly = {}
    for t in filled:
        month = t["fill_time"][:7] # YYYY-MM
        if month not in monthly: monthly[month] = {"n": 0, "w": 0, "r": 0}
        monthly[month]["n"] += 1
        monthly[month]["r"] += t["r_result"]
        if t["outcome"] == "win": monthly[month]["w"] += 1

    c_wins = [t for t in controls if t["outcome"] == "win"]
    c_total_r = sum(t["r_result"] for t in controls)
    c_wr = (len(c_wins) / len(controls) * 100) if controls else 0

    # --- OUTPUTS ---
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    
    csv_path = os.path.join(out_dir, "sniper_trades_latest.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys() if trades else [])
        if trades:
            writer.writeheader()
            writer.writerows(trades)
            
    control_path = os.path.join(out_dir, "sniper_control_latest.csv")
    with open(control_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=controls[0].keys() if controls else [])
        if controls:
            writer.writeheader()
            writer.writerows(controls)

    report = f"""# Sniper Model: Validation Report (Post-Audit)

## Summary Statistics (All Filled Trades)
- **Total Signals Generated:** {len(trades)}
- **Filled:** {len(filled)}
- **Cancelled:** {len(cancelled)}
- **Wins:** {len(wins)}
- **Losses:** {len(losses)}
- **Timeouts:** {len(timeouts)}
- **Win Rate (incl. timeouts):** {win_rate:.1f}%
- **Expectancy:** {exp:+.3f} R
- **Net R:** {total_r:+.1f} R
- **Max Drawdown:** -{max_dd:.1f} R
- **Avg Bars in Trade:** {sum(t['bars_in_trade'] for t in filled) / len(filled) if filled else 0:.1f}
- **Closed within 24 bars:** {pct_fast:.1f}%
- **Detection Exceptions:** {err_count}

## Random-Direction Control
- **Control Win Rate:** {c_wr:.1f}% (Expected ~25% for 1:3)
- **Control Net R:** {c_total_r:+.1f} R

## Time Split (60/40)
- **First 60%:** WR {h1_wr}% | Net R {h1_r:+.1f}
- **Last 40%:** WR {h2_wr}% | Net R {h2_r:+.1f}

## Monthly Breakdown
| Month | Trades | WR | Net R |
|-------|--------|-----|-------|
"""
    for m in sorted(monthly.keys()):
        d = monthly[m]
        report += f"| {m} | {d['n']} | {d['w']/d['n']*100:.1f}% | {d['r']:+.1f} |\n"

    report += "\n## Per-Symbol Performance\n| Symbol | Filled | WR | Net R |\n|--------|--------|-----|-------|\n"
    sym_stats = {}
    for t in filled:
        s = t["symbol"]
        if s not in sym_stats: sym_stats[s] = {"n": 0, "w": 0, "r": 0}
        sym_stats[s]["n"] += 1
        sym_stats[s]["r"] += t["r_result"]
        if t["outcome"] == "win": sym_stats[s]["w"] += 1
        
    for s in sorted(sym_stats.keys()):
        d = sym_stats[s]
        report += f"| {s} | {d['n']} | {d['w']/d['n']*100:.1f}% | {d['r']:+.1f} |\n"

    with open(os.path.join(out_dir, "sniper_validation_latest.md"), "w") as f:
        f.write(report)
        
    print("\n" + report)

if __name__ == "__main__":
    main()
