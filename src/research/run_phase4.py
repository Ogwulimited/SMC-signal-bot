"""
Phase 4 per-pair runner (PRACTICE YEARS ONLY).

Walks one pair from the start of its data up to config.PRACTICE_END, driving
PairSetup exactly as tests/diag_phase4_walkforward_onepair.py does, and writes
the full attempt log (every resolved episode, tagged with status) to
data/phase4/{pair}_trades.csv.

Rules baked in:
  - Practice window only: a bar is loaded only if it has fully CLOSED by
    PRACTICE_END (so no D1/H4/H1 bar ever contains exam-period data).
  - Stacking: a new setup is taken even if an earlier trade on the pair is
    still open. Each trade runs to its own stop / T1 / T2 / time stop.
    `open_at_entry` records how many earlier trades were still running.
  - Net R = gross R - spread_cost_r (spread paid on every trade).
  - Trades whose 48-bar time stop would run past PRACTICE_END are flagged
    `truncated_by_cutoff` (closed early by the data edge, not by the rules).

Usage (repo root):  PAIR=eurusd python -m src.research.run_phase4
"""

import os
import time
from pathlib import Path

import numpy as np
import pandas as pd

from src import config
from src.research import zones, setups, simulate, primitives

TF_D1 = pd.Timedelta(days=1)
TF_H4 = pd.Timedelta(hours=4)
TF_H1 = pd.Timedelta(hours=1)
TF_M15 = pd.Timedelta(minutes=15)

ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = ROOT / "data" / "processed"
OUT_DIR = ROOT / "data" / "phase4"


def _closed_before(df, tf, cutoff):
    """Keep only bars that have fully closed by the cutoff."""
    return df[df["timestamp"] + tf <= cutoff].reset_index(drop=True)


def _load(pair, cutoff):
    frames = {}
    for name, tf in (("d1", TF_D1), ("h4", TF_H4), ("h1", TF_H1), ("m15", TF_M15)):
        df = pd.read_parquet(PROCESSED_DIR / f"{pair}_{name}.parquet")
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        frames[name] = _closed_before(df, tf, cutoff)

    bad_days = set()
    bd_path = PROCESSED_DIR / f"bad_days_{pair}.parquet"
    if bd_path.exists():
        bd = pd.read_parquet(bd_path)
        col = "ny_date" if "ny_date" in bd.columns else bd.columns[0]
        bad_days = {d for d in pd.to_datetime(bd[col]).dt.date if d < cutoff.date()}

    return frames["d1"], frames["h4"], frames["h1"], frames["m15"], bad_days


def _held_until(t):
    """When this trade stops being open: T1 exit if T1 qualified, else T2 exit."""
    if not t.get("skipped_no_t1") and pd.notna(t.get("exit_time_t1")):
        return t["exit_time_t1"]
    return t.get("exit_time_t2")


def run_pair(pair):
    t0 = time.time()
    cutoff = pd.Timestamp(config.PRACTICE_END, tz="UTC")

    d1_df, h4_df, h1_df, m15_df, bad_days = _load(pair, cutoff)
    print(f"[{pair}] practice window to {cutoff}: d1={len(d1_df)} h4={len(h4_df)} "
          f"h1={len(h1_df)} m15={len(m15_df)} bad_days={len(bad_days)}", flush=True)
    print(f"[{pair}] last m15 close: {m15_df['timestamp'].iloc[-1] + TF_M15}", flush=True)

    d1_swings = primitives.find_swings(d1_df, config.D1_SWING_N, TF_D1)
    d1_events = primitives.detect_bos_choch(d1_df, d1_swings, TF_D1)
    d1_zones = zones.find_htf_zones(d1_df, TF_D1, d1_events, bad_days=bad_days)

    h4_swings = primitives.find_swings(h4_df, config.STRUCTURE_SWING_N, TF_H4)
    h4_events = primitives.detect_bos_choch(h4_df, h4_swings, TF_H4)
    h4_zones = zones.find_htf_zones(h4_df, TF_H4, h4_events, bad_days=bad_days)

    pools_full = simulate.build_pool_universe(h1_df, h4_df, TF_H1, TF_H4, bad_days=bad_days)
    print(f"[{pair}] d1_zones={len(d1_zones)} h4_zones={len(h4_zones)} pools={len(pools_full)}", flush=True)

    ps = setups.PairSetup(pair)
    trades = []

    d1_ts = d1_df["timestamp"].tolist()
    h1_ts = h1_df["timestamp"].tolist()
    m15_ts = m15_df["timestamp"].tolist()
    h1_low = h1_df["low"].to_numpy()
    h1_high = h1_df["high"].to_numpy()
    d1_low = d1_df["low"].to_numpy()
    d1_high = d1_df["high"].to_numpy()
    n_d1, n_h1, n_m15 = len(d1_ts), len(h1_ts), len(m15_ts)

    d1_ptr, h1_ptr = 0, 0
    progress_every = 20000

    for m_i in range(n_m15):
        now = m15_ts[m_i] + TF_M15

        while d1_ptr < n_d1 and (d1_ts[d1_ptr] + TF_D1) <= now:
            d1_close_time = d1_ts[d1_ptr] + TF_D1
            d1_slice = d1_df.iloc[:d1_ptr + 1]
            d1z_slice = d1_zones[d1_zones["confirm_time"] <= d1_close_time]
            h4z_slice = h4_zones[h4_zones["confirm_time"] <= d1_close_time]
            if h1_ptr > 0:
                cur_low, cur_high = h1_low[h1_ptr - 1], h1_high[h1_ptr - 1]
            else:
                cur_low, cur_high = d1_low[d1_ptr], d1_high[d1_ptr]
            ps.on_d1_close(d1_slice, d1z_slice, h4z_slice, cur_low, cur_high)
            d1_ptr += 1

        while h1_ptr < n_h1 and (h1_ts[h1_ptr] + TF_H1) <= now:
            h1_close_time = h1_ts[h1_ptr] + TF_H1
            h1_slice = h1_df.iloc[:h1_ptr + 1]
            pools_slice = pools_full[pools_full["confirm_time"] <= h1_close_time]
            ps.on_h1_close(h1_slice, pools_slice, TF_H1)
            h1_ptr += 1

        if h1_ptr > 0:
            m15_slice = m15_df.iloc[:m_i + 1]
            h1_known_slice = h1_df.iloc[:h1_ptr]
            ps.on_m15_close(h1_known_slice, m15_slice, TF_H1, TF_M15)

            # OB winner locks in one bar before fill2_price exists: just wait.
            winner_ready = ps.winner is not None and not (ps.winner == "ob" and ps.fill2_price is None)
            if winner_ready:
                rec = simulate.build_trade_from_setup(
                    ps, pair, h1_df, m15_df, pools_full, TF_H1, TF_M15
                )
                # Net R = gross R - spread paid (in R)
                sc = rec.get("spread_cost_r")
                for k in ("t1", "t2"):
                    r = rec.get(f"r_result_{k}")
                    ok = r is not None and pd.notna(r) and sc is not None and pd.notna(sc)
                    rec[f"net_r_{k}"] = (r - sc) if ok else np.nan
                et = rec.get("entry_time")
                rec["truncated_by_cutoff"] = bool(
                    et is not None and pd.notna(et) and et + config.TIME_STOP_H1_BARS * TF_H1 > cutoff
                )
                trades.append(rec)

        if m_i and m_i % progress_every == 0:
            print(f"[{pair}] {m_i}/{n_m15} m15 bars, {len(trades)} attempts, "
                  f"{time.time() - t0:.0f}s elapsed", flush=True)

    # Stacking diagnostic: how many earlier trades were still open at each entry
    opened = [t for t in trades if t.get("status") == "opened"]
    for i, t in enumerate(opened):
        n = 0
        for j in range(i):
            held = _held_until(opened[j])
            if held is not None and pd.notna(held) and held > t["entry_time"]:
                n += 1
        t["open_at_entry"] = n

    elapsed = time.time() - t0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["pair", "status"])
    df.to_csv(OUT_DIR / f"{pair}_trades.csv", index=False)

    statuses = df["status"].value_counts().to_dict() if len(df) else {}
    t1_ok = 0
    mean_t1 = mean_t2 = float("nan")
    max_stack = 0
    trunc = 0
    if opened:
        od = pd.DataFrame(opened)
        q = od[od["skipped_no_t1"] == False]
        t1_ok = len(q)
        if t1_ok:
            mean_t1 = q["net_r_t1"].mean()
        mean_t2 = od["net_r_t2"].mean()
        max_stack = int(od["open_at_entry"].max())
        trunc = int(od["truncated_by_cutoff"].sum())

    summary = (
        f"### Phase 4 practice run: {pair}\n"
        f"- Window: start of data to {config.PRACTICE_END} (bars fully closed only)\n"
        f"- Attempts logged: {len(df)}  |  Status: {statuses}\n"
        f"- Opened with a qualifying T1: {t1_ok}\n"
        f"- Mean net R per trade: T1 headline = {mean_t1:.3f}, T2 (fixed 3R) = {mean_t2:.3f}\n"
        f"- Max trades already open at an entry (stacking): {max_stack}\n"
        f"- Trades truncated by the cutoff: {trunc}\n"
        f"- Run time: {elapsed:.0f}s\n"
    )
    print("\n" + summary, flush=True)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a") as f:
            f.write(summary)
    return df


if __name__ == "__main__":
    run_pair(os.environ.get("PAIR", "eurusd"))
