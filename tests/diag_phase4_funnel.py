"""
Phase 4 funnel diagnostic (PRACTICE YEARS ONLY).

Why: the first EURUSD practice run (2016 -> 2022-07-01) produced only 3 trades
and 175 bias flips. This script replays one practice-year window with the same
loop as src/research/run_phase4.py and counts where setups die, so we can tell
"rules are very selective" from "something upstream is killing setups".

Counts only begin at the window start; the 90 days before it are warm-up
(state machine runs, nothing is counted).

Refuses any window that extends past config.PRACTICE_END (exam years sealed).

Usage (repo root):
  PYTHONPATH=. PAIR=eurusd START_YEAR=2019 YEARS=1 python tests/diag_phase4_funnel.py
"""

import os
import time
from collections import Counter

import pandas as pd

from src import config
from src.research import zones, setups, simulate, primitives
from src.research.run_phase4 import _load, _get_bias

TF_D1 = pd.Timedelta(days=1)
TF_H4 = pd.Timedelta(hours=4)
TF_H1 = pd.Timedelta(hours=1)
TF_M15 = pd.Timedelta(minutes=15)


def _changed(a, b):
    try:
        return bool(a != b)
    except Exception:
        return str(a) != str(b)


def _f(x, nd=4):
    try:
        if x is None or pd.isna(x):
            return "-"
        return f"{float(x):.{nd}f}"
    except Exception:
        return str(x)


def main():
    t0 = time.time()
    pair = os.environ.get("PAIR", "eurusd")
    start_year = int(os.environ.get("START_YEAR", "2019"))
    years = int(os.environ.get("YEARS", "1"))

    practice_end = pd.Timestamp(config.PRACTICE_END, tz="UTC")
    win_start = pd.Timestamp(f"{start_year}-01-01", tz="UTC")
    win_end = pd.Timestamp(f"{start_year + years}-01-01", tz="UTC")
    if win_end > practice_end:
        raise SystemExit(f"REFUSED: window ends {win_end}, past PRACTICE_END {practice_end}. "
                         f"Exam years are sealed.")
    buffer_start = win_start - pd.Timedelta(days=90)

    d1_df, h4_df, h1_df, m15_df, bad_days = _load(pair, win_end)

    def _trim(df):
        return df[df["timestamp"] >= buffer_start].reset_index(drop=True)

    d1_df, h4_df, h1_df, m15_df = (_trim(x) for x in (d1_df, h4_df, h1_df, m15_df))
    print(f"[{pair}] window {win_start.date()} -> {win_end.date()} (+90d warm-up): "
          f"d1={len(d1_df)} h4={len(h4_df)} h1={len(h1_df)} m15={len(m15_df)}", flush=True)

    d1_swings = primitives.find_swings(d1_df, config.D1_SWING_N, TF_D1)
    d1_events = primitives.detect_bos_choch(d1_df, d1_swings, TF_D1)
    d1_zones = zones.find_htf_zones(d1_df, TF_D1, d1_events, bad_days=bad_days)
    h4_swings = primitives.find_swings(h4_df, config.STRUCTURE_SWING_N, TF_H4)
    h4_events = primitives.detect_bos_choch(h4_df, h4_swings, TF_H4)
    h4_zones = zones.find_htf_zones(h4_df, TF_H4, h4_events, bad_days=bad_days)
    pools_full = simulate.build_pool_universe(h1_df, h4_df, TF_H1, TF_H4, bad_days=bad_days)

    ps = setups.PairSetup(pair)

    d1_ts = d1_df["timestamp"].tolist()
    h1_ts = h1_df["timestamp"].tolist()
    m15_ts = m15_df["timestamp"].tolist()
    h1_low, h1_high = h1_df["low"].to_numpy(), h1_df["high"].to_numpy()
    d1_low, d1_high = d1_df["low"].to_numpy(), d1_df["high"].to_numpy()
    n_d1, n_h1, n_m15 = len(d1_ts), len(h1_ts), len(m15_ts)

    prev_state = ps.state
    prev_bias = _get_bias(ps)
    counting = False

    state_entries = Counter()
    transitions = Counter()
    state_bars = Counter()
    bias_values = Counter()
    bias_changes = []
    choch_entries = []
    winners = Counter()
    statuses = Counter()
    attempts = []
    d1_closes = 0
    zone_changes = 0

    def note(source):
        nonlocal prev_state
        if ps.state != prev_state:
            if counting:
                transitions[(source, str(prev_state), str(ps.state))] += 1
                state_entries[str(ps.state)] += 1
                if ps.state == "CHOCH_SEEN":
                    ev = ps.h1_bos_event
                    choch_entries.append({
                        "candidate_ob": ps.candidate_ob is not None,
                        "h1_bos_label": ev.get("label") if ev is not None else None,
                    })
            prev_state = ps.state

    d1_ptr, h1_ptr = 0, 0
    for m_i in range(n_m15):
        now = m15_ts[m_i] + TF_M15
        counting = now >= win_start

        while d1_ptr < n_d1 and (d1_ts[d1_ptr] + TF_D1) <= now:
            d1_close_time = d1_ts[d1_ptr] + TF_D1
            d1_slice = d1_df.iloc[:d1_ptr + 1]
            d1z_slice = d1_zones[d1_zones["confirm_time"] <= d1_close_time]
            h4z_slice = h4_zones[h4_zones["confirm_time"] <= d1_close_time]
            if h1_ptr > 0:
                cur_low, cur_high = h1_low[h1_ptr - 1], h1_high[h1_ptr - 1]
            else:
                cur_low, cur_high = d1_low[d1_ptr], d1_high[d1_ptr]
            zone_before = ps.zone
            ps.on_d1_close(d1_slice, d1z_slice, h4z_slice, cur_low, cur_high)
            b = _get_bias(ps)
            if counting:
                d1_closes += 1
                bias_values[str(b)] += 1
                if _changed(zone_before, ps.zone):
                    zone_changes += 1
            if _changed(b, prev_bias):
                if counting:
                    bias_changes.append((d1_close_time, prev_bias, b))
                prev_bias = b
            note("D1")
            d1_ptr += 1

        while h1_ptr < n_h1 and (h1_ts[h1_ptr] + TF_H1) <= now:
            h1_close_time = h1_ts[h1_ptr] + TF_H1
            h1_slice = h1_df.iloc[:h1_ptr + 1]
            pools_slice = pools_full[pools_full["confirm_time"] <= h1_close_time]
            ps.on_h1_close(h1_slice, pools_slice, TF_H1)
            h1_ptr += 1
            note("H1")

        if h1_ptr > 0:
            m15_slice = m15_df.iloc[:m_i + 1]
            h1_known_slice = h1_df.iloc[:h1_ptr]
            ps.on_m15_close(h1_known_slice, m15_slice, TF_H1, TF_M15)
            note("M15")

            winner_ready = ps.winner is not None and not (ps.winner == "ob" and ps.fill2_price is None)
            if winner_ready:
                if counting:
                    winners[str(ps.winner)] += 1
                rec = simulate.build_trade_from_setup(
                    ps, pair, h1_df, m15_df, pools_full, TF_H1, TF_M15
                )
                if counting:
                    statuses[str(rec.get("status"))] += 1
                    attempts.append(rec)

        if counting:
            state_bars[str(ps.state)] += 1

    total_bars = sum(state_bars.values()) or 1
    no_t1 = sum(1 for r in attempts if r.get("skipped_no_t1"))
    ch_with_ob = sum(1 for c in choch_entries if c["candidate_ob"])
    label_counts = Counter(str(c["h1_bos_label"]) for c in choch_entries)

    out = []
    out.append(f"### Phase 4 funnel: {pair}, {win_start.date()} -> {win_end.date()} (practice only)")
    out.append(f"- D1 closes counted: {d1_closes}  |  zone changes: {zone_changes}")
    out.append(f"- Bias values at D1 closes: {dict(bias_values)}")
    out.append(f"- Bias changes in window: {len(bias_changes)}")
    out.append("- Time in each state (% of M15 bars): "
               + ", ".join(f"{k}={100 * v / total_bars:.1f}%" for k, v in state_bars.most_common()))
    out.append(f"- Entries into each state: {dict(state_entries)}")
    out.append(f"- CHOCH_SEEN entries: {len(choch_entries)}  |  with candidate OB: {ch_with_ob}  "
               f"|  h1_bos labels: {dict(label_counts)}")
    out.append(f"- Winners resolved: {dict(winners)}  |  attempt status: {dict(statuses)}  "
               f"|  no qualifying T1: {no_t1}")
    out.append(f"- Run time: {time.time() - t0:.0f}s")
    out.append("")
    out.append("Bias changes (first 15):")
    out.append("```")
    for t, o, n in bias_changes[:15]:
        out.append(f"{t}  {o} -> {n}")
    out.append("```")
    out.append("State transitions by call site (top 30):")
    out.append("```")
    for (src, o, n), c in transitions.most_common(30):
        out.append(f"{c:5d}  [{src}] {o} -> {n}")
    out.append("```")
    out.append("Attempts (first 40):")
    out.append("```")
    for r in attempts[:40]:
        out.append(
            f"{r.get('entry_time')} {r.get('model')} {r.get('direction')} {r.get('status')} "
            f"risk={_f(r.get('risk_r'), 5)} spread_r={_f(r.get('spread_cost_r'), 3)} "
            f"no_t1={r.get('skipped_no_t1')} nearest_r_net={_f(r.get('t1_nearest_r_net'), 2)} "
            f"t1_r_net={_f(r.get('t1_r_net'), 2)}"
        )
    out.append("```")
    text = "\n".join(out)
    print("\n" + text, flush=True)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a") as fh:
            fh.write(text + "\n")


if __name__ == "__main__":
    main()
