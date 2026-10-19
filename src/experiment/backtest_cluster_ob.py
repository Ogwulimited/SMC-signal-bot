"""Backtest: Single Candle OB vs Cluster OB."""

import bisect, json, os, random, statistics
from datetime import datetime, timezone
from ..config import RECOMMENDED_PAIRS, GRANULARITY, DETECT_WINDOW, HTF_GRANULARITY, HTF_CANDLE_COUNT, MAX_HORIZON_BARS, SPREAD_ATR_FRAC, ATR_PERIOD, REPORTS_DIR
from ..deriv_client import fetch_candles_paginated
from ..smc import compute_atr
from ..continuation_eq import detect_continuation_signals_eq, detect_htf_bias
from .cluster_ob import detect_continuation_signals_cluster

BACKTEST_H1_CANDLES = 2500
WARMUP_BARS = 400
N_WINDOWS = 3

def log(m): print(m, flush=True)

def _walk_exit(candles, start_idx, direction, stop_eff, target_eff):
    end = min(start_idx + MAX_HORIZON_BARS, len(candles))
    for k in range(start_idx, end):
        c = candles[k]
        if direction == "bullish":
            if c["low"] <= stop_eff: return "loss", k
            if c["high"] >= target_eff: return "win", k
        else:
            if c["high"] >= stop_eff: return "loss", k
            if c["low"] <= target_eff: return "win", k
    return "timeout", None

def _rr(direction, entry, stop, target):
    return (target - entry) / (entry - stop) if direction == "bullish" and entry > stop else ((entry - target) / (stop - entry) if direction == "bearish" and stop > entry else 0)

def _apply_spread(direction, entry_raw, stop, target, spread):
    half = spread / 2.0
    return (entry_raw + half, stop, target - half) if direction == "bullish" else (entry_raw - half, stop, target + half)

def _valid_geo(direction, e, s, t):
    return (e > s and t > e) if direction == "bullish" else (e < s and t < e)

def simulate(candles, entry, stop, target, direction, entry_bar_idx, spread):
    entry_eff, stop_eff, target_eff = _apply_spread(direction, entry, stop, target, spread)
    if not _valid_geo(direction, entry_eff, stop_eff, target_eff): return None
    tb = candles[entry_bar_idx]
    if direction == "bullish" and tb["low"] <= stop_eff: return {"outcome": "loss", "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    if direction == "bearish" and tb["high"] >= stop_eff: return {"outcome": "loss", "rr": _rr(direction, entry_eff, stop_eff, target_eff)}
    outcome, _ = _walk_exit(candles, entry_bar_idx + 1, direction, stop_eff, target_eff)
    return {"outcome": outcome, "rr": _rr(direction, entry_eff, stop_eff, target_eff)}

def _agg(trades):
    if not trades: return {"n": 0, "wins": 0, "losses": 0, "wr": 0, "expectancy": 0, "net_r": 0, "avg_rr_won": 0}
    wins = [t for t in trades if t["outcome"] == "win"]
    losses = [t for t in trades if t["outcome"] == "loss"]
    timeouts = [t for t in trades if t["outcome"] == "timeout"]
    net_r = sum(t["rr_eff"] for t in wins) - len(losses)
    resolved = len(wins) + len(losses)
    wr = (len(wins) / resolved * 100) if resolved > 0 else 0
    exp = net_r / len(trades) if trades else 0
    avg_rr_won = (sum(t["rr_eff"] for t in wins) / len(wins)) if wins else 0
    return {"n": len(trades), "wins": len(wins), "losses": len(losses), "timeouts": len(timeouts), "wr": wr, "expectancy": exp, "net_r": net_r, "avg_rr_won": avg_rr_won}

def _write_report(base_agg, cluster_agg, config_snap):
    out_dir = os.path.join(REPORTS_DIR, "experiments")
    os.makedirs(out_dir, exist_ok=True)
    md = [
        "# Experiment: Single-Candle OB vs Cluster OB\n",
        f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}\n",
        "## Configuration\n"
    ]
    for k, v in config_snap.items(): md.append(f"| {k} | {v} |")
    md.append("\n## Results\n")
    md.append("| Metric | Single-Candle OB (Live) | Cluster OB |")
    md.append("|--------|-------------------------|------------|")
    md.append(f"| Signals | {base_agg['n']} | {cluster_agg['n']} |")
    md.append(f"| Wins | {base_agg['wins']} | {cluster_agg['wins']} |")
    md.append(f"| Losses | {base_agg['losses']} | {cluster_agg['losses']} |")
    md.append(f"| Win Rate | {base_agg['wr']:.1f}% | {cluster_agg['wr']:.1f}% |")
    md.append(f"| Avg R:R (wins) | {base_agg['avg_rr_won']:.2f} | {cluster_agg['avg_rr_won']:.2f} |")
    md.append(f"| Expectancy | {base_agg['expectancy']:+.3f} R | {cluster_agg['expectancy']:+.3f} R |")
    md.append(f"| Net R | {base_agg['net_r']:+.1f} | {cluster_agg['net_r']:+.1f} |")
    with open(os.path.join(out_dir, "cluster_ob_latest.md"), "w") as f: f.write("\n".join(md))

def main():
    random.seed(42)
    log("Cluster OB experiment running...")
    base_trades, cluster_trades = [], []
    
    for sym_idx, sym in enumerate(RECOMMENDED_PAIRS, 1):
        log(f"[{sym_idx}/{len(RECOMMENDED_PAIRS)}] {sym}")
        try:
            h1 = fetch_candles_paginated(sym, GRANULARITY, BACKTEST_H1_CANDLES)
            d1 = fetch_candles_paginated(sym, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception: continue
        if not h1 or not d1: continue

        d1_epochs = [c["epoch"] for c in d1]
        n = len(h1)
        span = (n - MAX_HORIZON_BARS - 3) - WARMUP_BARS
        win_size = span // N_WINDOWS

        for w in range(N_WINDOWS):
            s = WARMUP_BARS + w * win_size
            e = s + win_size if w < N_WINDOWS - 1 else (n - MAX_HORIZON_BARS - 3)
            cached_bias_epoch = None; cached_bias = None

            for i in range(s, e):
                w_start = max(0, i + 1 - DETECT_WINDOW)
                h1_window = h1[w_start : i + 1]
                if len(h1_window) < 50: continue

                d1_end_idx = bisect.bisect_right(d1_epochs, h1_window[-1]["epoch"])
                if d1_end_idx < 20: continue
                d1_window = d1[:d1_end_idx]
                if d1_epochs[d1_end_idx - 1] != cached_bias_epoch:
                    cached_bias = detect_htf_bias(d1_window)
                    cached_bias_epoch = d1_epochs[d1_end_idx - 1]
                if cached_bias is None: continue

                atr_h1 = compute_atr(h1_window, ATR_PERIOD)
                if atr_h1 is None: continue
                spread = SPREAD_ATR_FRAC * atr_h1

                # Baseline
                try: base_pats = detect_continuation_signals_eq(h1_window, d1_window)
                except: base_pats = []
                for p in [p for p in base_pats if p.touch_index == len(h1_window) - 1]:
                    r = simulate(h1, p.entry, p.stop, p.target, p.direction, i, spread)
                    if r: base_trades.append({"outcome": r["outcome"], "rr_eff": round(r["rr"], 2)})

                # Cluster
                try: cluster_pats = detect_continuation_signals_cluster(h1_window, d1_window)
                except: cluster_pats = []
                for p in [p for p in cluster_pats if p.touch_index == len(h1_window) - 1]:
                    r = simulate(h1, p.entry, p.stop, p.target, p.direction, i, spread)
                    if r: cluster_trades.append({"outcome": r["outcome"], "rr_eff": round(r["rr"], 2)})

    base_agg, cluster_agg = _agg(base_trades), _agg(cluster_trades)
    log(f"\nBASELINE (Single-Candle): n={base_agg['n']} WR={base_agg['wr']:.1f}% Exp={base_agg['expectancy']:+.3f}")
    log(f"VARIANT  (Cluster Base):  n={cluster_agg['n']} WR={cluster_agg['wr']:.1f}% Exp={cluster_agg['expectancy']:+.3f}")
    
    config_snap = {"pairs": len(RECOMMENDED_PAIRS), "max_cluster_width_atr": 3.0, "min_ob_width_atr": 0.30}
    _write_report(base_agg, cluster_agg, config_snap)

if __name__ == "__main__":
    main()
