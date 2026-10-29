"""
Phase 4 diagnostic #4: one-pair walk-forward glue.

NOT a hand-derived-exact-number diagnostic (real market data is too complex
to hand-predict). Pass criteria: no exceptions, internal invariants hold
(no overlapping trades per pair, state resets correctly, counts reconcile),
and printed trades are plausible on manual inspection.

This revision adds source-tagged state-transition logging (D1 vs H1 vs M15
call sites) and a detailed zone/bias/state snapshot log around every D1
close that changes anything, to pin down exactly why every episode this
year stalls at BOS_SEEN and never reaches CHOCH_SEEN (confirmed via the
prior instrumentation run: state_reach_counts = {EPISODE:6, BOS_SEEN:6,
IDLE:6}, i.e. 6/6/6 -- every cycle dies at the same wall).

Post-Fix-1/Fix-2 addendum: CHOCH_SEEN is now reachable (confirmed in the
following run), but zero episodes resolved a winner. This revision adds
two new logs to distinguish between three competing hypotheses for why:
(1) candidate_ob was never set for the stalled episode (OB path dead,
breaker-only), (2) candidate_ob was set but Model A/B never armed it,
(3) h1_bos_event's label was never actually "BOS" (documented limitation:
h1_bos_event is matched by direction only, not label -- if it's "INIT" or
something else, detect_breakers' internal label=="BOS" filter silently
excludes it, so the breaker path would never even get a chance to fire).

New logs:
  - choch_seen_entries: snapshot taken the instant each episode first
    enters CHOCH_SEEN -- candidate_ob_present, h1_bos_label, h1_bos_direction.
  - breaker_change_log: snapshot taken every time ps.breaker's value changes
    (None -> dict, or dict -> different dict), with episode context
    (candidate_ob_present, h1_bos_label) attached, so we can see whether
    detect_breakers ever produced a candidate at all for the stalled episode.
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


def _zone_repr(z):
    if z is None:
        return None
    if hasattr(z, "to_dict"):
        try:
            return z.to_dict()
        except Exception:
            return str(z)
    return z


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

    print(f"d1_events={len(d1_events)} h4_events={len(h4_events)}")
    print(f"d1_zones={len(d1_zones)} h4_zones={len(h4_zones)} pools={len(pools_full)}")
    if not d1_events.empty:
        print(f"d1_events label counts: {d1_events['label'].value_counts().to_dict()}")
    if not h4_events.empty:
        print(f"h4_events label counts: {h4_events['label'].value_counts().to_dict()}")

    ps = setups.PairSetup(pair)
    trades = []
    d1_ptr, h1_ptr = 0, 0
    last_exit_time = None

    prev_state = ps.state
    state_reach_counts = {}
    zone_change_count = 0
    d1_close_count = 0

    transition_log = []       # (timestamp, source, old_state, new_state)
    d1_reset_log = []         # zone/bias/state snapshots around D1 closes that change anything
    choch_seen_entries = []   # snapshot the instant each episode first enters CHOCH_SEEN
    breaker_change_log = []   # snapshot every time ps.breaker's value changes

    prev_breaker_repr = None

    def _note_transition(now_ts, source):
        nonlocal prev_state
        if ps.state != prev_state:
            transition_log.append((now_ts, source, prev_state, ps.state))
            state_reach_counts[ps.state] = state_reach_counts.get(ps.state, 0) + 1
            if ps.state == "CHOCH_SEEN":
                h1_bos_label = ps.h1_bos_event.get("label") if ps.h1_bos_event is not None else None
                h1_bos_direction = ps.h1_bos_event.get("direction") if ps.h1_bos_event is not None else None
                choch_seen_entries.append({
                    "time": now_ts,
                    "source": source,
                    "candidate_ob_present": ps.candidate_ob is not None,
                    "h1_bos_label": h1_bos_label,
                    "h1_bos_direction": h1_bos_direction,
                })
            prev_state = ps.state

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

            zone_before = ps.zone
            state_before = ps.state
            bias_before = getattr(ps, "bias", "N/A")

            ps.on_d1_close(d1_slice, d1z_slice, h4z_slice, cur_low, cur_high)
            d1_close_count += 1

            zone_after = ps.zone
            bias_after = getattr(ps, "bias", "N/A")

            if zone_before != zone_after:
                zone_change_count += 1

            if (zone_before != zone_after) or (state_before != ps.state) or (bias_before != bias_after):
                if len(d1_reset_log) < 40:
                    d1_reset_log.append({
                        "d1_close_time": d1_close_time,
                        "state": f"{state_before}->{ps.state}",
                        "bias": f"{bias_before}->{bias_after}",
                        "zone_before": _zone_repr(zone_before),
                        "zone_after": _zone_repr(zone_after),
                        "cur_low": cur_low,
                        "cur_high": cur_high,
                    })

            _note_transition(d1_close_time, "D1")
            d1_ptr += 1

        while h1_ptr < len(h1_df) and (h1_df["timestamp"].iloc[h1_ptr] + TF_H1) <= now:
            h1_close_time = h1_df["timestamp"].iloc[h1_ptr] + TF_H1
            h1_slice = h1_df.iloc[:h1_ptr + 1]
            pools_slice = pools_full[pools_full["confirm_time"] <= h1_close_time]
            ps.on_h1_close(h1_slice, pools_slice, TF_H1)
            h1_ptr += 1
            _note_transition(h1_close_time, "H1")

        if h1_ptr > 0:
            m15_slice = m15_df.iloc[:m_i + 1]
            h1_known_slice = h1_df.iloc[:h1_ptr]
            ps.on_m15_close(h1_known_slice, m15_slice, TF_H1, TF_M15)
            _note_transition(now, "M15")

            breaker_repr = _zone_repr(ps.breaker) if ps.breaker is not None else None
            if breaker_repr != prev_breaker_repr:
                if len(breaker_change_log) < 40:
                    h1_bos_label = ps.h1_bos_event.get("label") if ps.h1_bos_event is not None else None
                    breaker_change_log.append({
                        "time": now,
                        "candidate_ob_present": ps.candidate_ob is not None,
                        "h1_bos_label": h1_bos_label,
                        "winner": ps.winner,
                        "breaker": breaker_repr,
                    })
                prev_breaker_repr = breaker_repr

            # Fix 5b: winner resolving to "ob" does NOT mean fill2_price is
            # ready yet -- by design (Layer 6 contract) winner locks in the
            # instant touch_time is known, one full M15 bar before fill2_price
            # (the OB's realized entry, one bar after touch) can possibly
            # exist. Calling build_trade_from_setup before fill2_price is
            # populated is exactly what crashed this script previously. The
            # correct behavior here is simply to wait: do nothing this bar,
            # try again next bar -- on_m15_close recomputes fill2_price on
            # every call regardless of winner, so it will populate on the
            # very next M15 close after touch, and this condition will then
            # pass naturally. This is NOT an error/skip status -- no record
            # should be logged for a bar where we're just waiting.
            winner_ready = ps.winner is not None and not (ps.winner == "ob" and ps.fill2_price is None)

            if winner_ready:
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

    print(f"\n--- INSTRUMENTATION ---")
    print(f"d1_close_count={d1_close_count}")
    print(f"zone_change_count={zone_change_count} (each zone change forces _reset_episode)")
    print(f"state_reach_counts (distinct new-state entries over the run): {state_reach_counts}")

    print(f"\n--- STATE TRANSITION LOG (first 60 of {len(transition_log)}) ---")
    for ts, source, old, new in transition_log[:60]:
        print(f"{ts} [{source}] {old} -> {new}")

    print(f"\n--- D1 ZONE/BIAS CHANGE DETAIL LOG (first {len(d1_reset_log)}) ---")
    for entry in d1_reset_log:
        print(entry)

    print(f"\n--- CHOCH_SEEN ENTRY LOG ({len(choch_seen_entries)} entries) ---")
    for entry in choch_seen_entries:
        print(entry)

    print(f"\n--- BREAKER CHANGE LOG (first {len(breaker_change_log)}) ---")
    for entry in breaker_change_log:
        print(entry)

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
