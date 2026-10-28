"""
Phase 4 diagnostic #4: one-pair walk-forward glue.

NOT a hand-derived-exact-number diagnostic (real market data is too complex
to hand-predict). Pass criteria: no exceptions, internal invariants hold
(no overlapping trades per pair, state resets correctly, counts reconcile),
and printed trades are plausible on manual inspection.

Restricted to a single pair/year to keep runtime and output manageable.
Signal-generation calls (on_d1_close/on_h1_close/on_m15_close) always get
data truncated to "known as of this bar's close" -- no lookahead on the
entry decision. Trade-outcome scoring (build_trade_from_setup) gets the
full h1/m15/pool history, because scoring an already-placed historical
trade by scanning its own forward price path is standard backtesting,
not lookahead bias.

ASSUMPTION (flagged): H4 bos/choch events for find_htf_zones use
config.STRUCTURE_SWING_N (same as H1 structure detection), since no
H4-specific swing-N constant exists in config.py. D1_SWING_N is reserved
for D1 bias per compute_d1_bias. Revisit if H4 zone counts look off.
"""

import pandas as pd

from src import config
from src.research import zones, setups, simulate, primitives

PAIR = "eurusd"
YEAR = 2023

TF_D1 = pd.Timedelta(days=1)
TF_H4 = pd.Timedelta(hours=4)
TF_H1 = pd.Timedelta(hours=1)
TF_M15 = pd.Timedelta(minutes=15)


def _load(pair, year):
    base = f"data/processed/{pair}"
    d1 = pd.read_parquet(f"{base}_d1.parquet")
    h4 = pd.read_parquet(f"{base}_h4.parquet")
    h1 = pd.read_parquet(f"{base}_h1.parquet")
    m15 = pd.read_parquet(f"{base}_m15.parquet")

    for df in (d1, h4, h1, m15):
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    d1 = d1.sort_values("timestamp").reset_index(drop=True)
    h4 = h4.sort_values("timestamp").reset_index(drop=True)
    h1 = h1.sort_values("timestamp").reset_index(drop=True)
    m15 = m15.sort_values("timestamp").reset_index(drop=True)

    try:
        bad_days_df = pd.read_parquet(f"data/processed/bad_days_{pair}.parquet")
        print(f"bad_days_{pair}.parquet columns: {list(bad_days_df.columns)}")
        if "date" in bad_days_df.columns:
            col = "date"
        elif "ny_date" in bad_days_df.columns:
            col = "ny_date"
        elif "bad_date" in bad_days_df.columns:
            col = "bad_date"
        elif "timestamp" in bad_days_df.columns:
            col = "timestamp"
        elif "day" in bad_days_df.columns:
            col = "day"
        else:
            col = bad_days_df.columns[0]
        bad_days = set(pd.to_datetime(bad_days_df[col]).dt.date)
    except FileNotFoundError:
        bad_days = set()

    buffer_start = pd.Timestamp(f"{year}-01-01", tz="UTC") - pd.Timedelta(days=90)
    cutoff_end = pd.Timestamp(f"{year+1}-01-01", tz="UTC")

    d1 = d1[(d1["timestamp"] >= buffer_start) & (d1["timestamp"] < cutoff_end)].reset_index(drop=True)
    h4 = h4[(h4["timestamp"] >= buffer_start) & (h4["timestamp"] < cutoff_end)].reset_index(drop=True)
    h1 = h1[(h1["timestamp"] >= buffer_start) & (h1["timestamp"] < cutoff_end)].reset_index(drop=True)
    m15 = m15[(m15["timestamp"] >= buffer_start) & (m15["timestamp"] < cutoff_end)].reset_index(drop=True)

    return d1, h4, h1, m15, bad_days


def run_one_pair(pair=PAIR, year=YEAR):
    d1_df, h4_df, h1_df, m15_df, bad_days = _load(pair, year)
    print(f"Loaded {pair} {year}: d1={len(d1_df)} h4={len(h4_df)} h1={len(h1_df)} m15={len(m15_df)} bad_days={len(bad_days)}")

    d1_swings = primitives.find_swings(d1_df, config.D1_SWING_N, TF_D1)
    d1_events = primitives.detect_bos_choch(d1_df, d1_swings, TF_D1)
    d1_zones = zones.find_htf_zones(d1_df, TF_D1, d1_events, bad_days=bad_days)

    h4_swings = primitives.find_swings(h4_df, config.STRUCTURE_SWING_N, TF_H4)
    h4_events = primitives.detect_bos_choch(h4_df, h4_swings, TF_H4)
    h4_zones = zones.find_htf_zones(h4_df, TF_H4, h4_events, bad_days=bad_days)

    pools_full = simulate.build_pool_universe(h1_df, h4_df, TF_H1, TF_H4, bad_days=bad_days)

    print(f"d1_zones={len(d1_zones)} h4_zones={len(h4_zones)} pools={len(pools_full)}")

    ps = setups.PairSetup(pair)
    trades = []
    d1_ptr, h1_ptr = 0, 0
    last_exit_time = None

    for m_i in range(len(m15_df)):
        now = m15_df["timestamp"].iloc[m_i] + TF_M15

        while d1_ptr < len(d1_df) and (d1_df["timestamp"].iloc[d1_ptr] + TF_D1) <= now:
            d1_close_time = d1_df["timestamp"].iloc[d1_ptr] + TF_D1
            d1_slice = d1_df.iloc[:d1_ptr + 1]
            d1z_slice = d1_zones[d1_zones["confirm_time"] <= d1_close_time]
            h4z_slice = h4_zones[h4_zones["confirm_time"] <= d1_close_time]
            if h1_ptr > 0:
                cur_low = h1_df["low"].iloc[h1_ptr - 1]
                cur_high = h1_df["high"].iloc[h1_ptr - 1]
            else:
                cur_low = d1_df["low"].iloc[d1_ptr]
                cur_high = d1_df["high"].iloc[d1_ptr]
            ps.on_d1_close(d1_slice, d1z_slice, h4z_slice, cur_low, cur_high)
            d1_ptr += 1

        while h1_ptr < len(h1_df) and (h1_df["timestamp"].iloc[h1_ptr] + TF_H1) <= now:
            h1_close_time = h1_df["timestamp"].iloc[h1_ptr] + TF_H1
            h1_slice = h1_df.iloc[:h1_ptr + 1]
            pools_slice = pools_full[pools_full["confirm_time"] <= h1_close_time]
            ps.on_h1_close(h1_slice, pools_slice, TF_H1)
            h1_ptr += 1

        if h1_ptr > 0:
            m15_slice = m15_df.iloc[:m_i + 1]
            h1_known_slice = h1_df.iloc[:h1_ptr]
            ps.on_m15_close(h1_known_slice, m15_slice, TF_H1, TF_M15)

            if ps.winner is not None:
                entry_time_check = ps.touch_time if ps.winner == "ob" else (
                    ps.breaker.get("fill_time") if ps.breaker else None
                )
                if last_exit_time is not None and entry_time_check is not None:
                    if entry_time_check < last_exit_time:
                        print(f"INVARIANT VIOLATION: new entry {entry_time_check} before prior exit {last_exit_time}")

                rec = simulate.build_trade_from_setup(
                    ps, pair, h1_df, m15_df, pools_full, TF_H1, TF_M15
                )
                trades.append(rec)
                if rec.get("status") == "opened":
                    t1_exit = rec.get("exit_time_t1")
                    t2_exit = rec.get("exit_time_t2")
                    candidates = [t for t in (t1_exit, t2_exit) if pd.notna(t)]
                    if candidates:
                        last_exit_time = max(candidates)

    return trades


if __name__ == "__main__":
    trades = run_one_pair()
    print(f"\nTotal episode attempts logged: {len(trades)}")

    statuses = {}
    for t in trades:
        statuses[t["status"]] = statuses.get(t["status"], 0) + 1
    print(f"Status breakdown: {statuses}")

    print("\nFirst 10 trade records:")
    for t in trades[:10]:
        print(t)
