"""
Phase 4 per-pair runner (PRACTICE YEARS ONLY).

Walks one pair from the start of its data up to config.PRACTICE_END, driving
PairSetup exactly as tests/diag_phase4_walkforward_onepair.py does, and writes
the full attempt log to data/phase4/{pair}_trades.csv.

Rules baked in:
  - Practice window only: a bar is loaded only if it has fully CLOSED by
    PRACTICE_END, so no bar ever contains exam-period data.
  - Stacking simulation: every valid setup is taken, even if an earlier trade
    on the pair is still open. One-at-a-time scorecards are derived from the
    same trades via kept_1at_t1 / kept_1at_t2 flags (kept = no earlier KEPT
    trade on that track was still open at entry).
  - NO TIME STOP (practice experiment): each trade is followed until stop or
    target, or until the practice cutoff. A trade unresolved at the cutoff is
    labelled open_at_cutoff and excluded from win rate / R (we never peek
    past the cutoff). The old 48-bar time-stop results are kept as ts48_*
    side columns for comparison.
  - T1 track = trades with a qualifying T1 (headline). T2 track = all opened
    trades, fixed 3R target.
  - Net R = gross R - spread_cost_r.
  - Same-candle rule: stop wins if stop and target are touched on one bar.
  - Bias-flip tag: open trades are NOT managed. Each trade is tagged with
    whether the HTF bias flipped while it was open (flip_while_open_t1/t2).

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

FAR = pd.Timestamp("2262-01-01", tz="UTC")  # "still open" sentinel for overlap math

_BIAS_ATTRS = ("bias", "htf_bias", "d1_bias", "bias_direction")


def _get_bias(ps):
    for a in _BIAS_ATTRS:
        v = getattr(ps, a, None)
        if v is not None:
            return v
    return None


def _bias_attr_name(ps):
    for a in _BIAS_ATTRS:
        if getattr(ps, a, None) is not None:
            return a
    return None


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


def _scan_to_resolution(m15_close_idx, m15_high, m15_low, entry_time, direction,
                        stop_price, target_price):
    """
    Follow a trade bar by bar (M15) from just after entry until stop or target.
    No time stop. Same-candle rule: stop wins ties.
    Returns dict(exit_reason, exit_time, exit_price) or None if unresolved by
    the end of the loaded (practice-window) data.
    """
    bull = direction == "bullish"
    start = int(m15_close_idx.searchsorted(entry_time, side="right"))
    if start >= len(m15_high):
        return None
    h = m15_high[start:]
    l = m15_low[start:]
    stop_mask = (l <= stop_price) if bull else (h >= stop_price)
    has_target = target_price is not None and pd.notna(target_price)
    if has_target:
        tgt_mask = (h >= target_price) if bull else (l <= target_price)
    else:
        tgt_mask = np.zeros(len(h), dtype=bool)

    s_i = int(np.argmax(stop_mask)) if stop_mask.any() else None
    t_i = int(np.argmax(tgt_mask)) if tgt_mask.any() else None
    if s_i is None and t_i is None:
        return None
    if t_i is None or (s_i is not None and s_i <= t_i):
        return {"exit_reason": "stop", "exit_time": m15_close_idx[start + s_i], "exit_price": stop_price}
    return {"exit_reason": "target", "exit_time": m15_close_idx[start + t_i], "exit_price": target_price}


def _rescan_no_time_stop(rec, m15_close_idx, m15_high, m15_low):
    """
    Move the 48-bar results from build_trade_from_setup to ts48_* columns,
    then compute the no-time-stop outcome for each track.
    """
    sc = rec.get("spread_cost_r")
    entry_time = rec["entry_time"]
    entry_price = rec["entry_price"]
    stop_price = rec["stop_price"]
    risk_r = rec["risk_r"]
    direction = rec["direction"]

    for k in ("t1", "t2"):
        for f in ("exit_reason", "exit_time", "exit_price", "r_result"):
            rec[f"ts48_{f}_{k}"] = rec.pop(f"{f}_{k}", None)
        r48 = rec.get(f"ts48_r_result_{k}")
        ok48 = r48 is not None and pd.notna(r48) and sc is not None and pd.notna(sc)
        rec[f"ts48_net_r_{k}"] = (r48 - sc) if ok48 else np.nan

        # defaults (also used when the track does not apply)
        rec[f"outcome_{k}"] = None
        rec[f"exit_reason_{k}"] = None
        rec[f"exit_time_{k}"] = pd.NaT
        rec[f"exit_price_{k}"] = np.nan
        rec[f"r_result_{k}"] = np.nan
        rec[f"net_r_{k}"] = np.nan
        rec[f"dur_hours_{k}"] = np.nan

        if k == "t1" and rec.get("skipped_no_t1"):
            continue
        target = rec.get("t1_target_price") if k == "t1" else rec.get("t2_target_price")
        res = _scan_to_resolution(m15_close_idx, m15_high, m15_low, entry_time,
                                  direction, stop_price, target)
        if res is None:
            rec[f"outcome_{k}"] = "open_at_cutoff"
            rec[f"exit_reason_{k}"] = "open_at_cutoff"
            continue
        r = simulate.compute_r_result(entry_price, res["exit_price"], direction, risk_r)
        rec[f"outcome_{k}"] = res["exit_reason"]
        rec[f"exit_reason_{k}"] = res["exit_reason"]
        rec[f"exit_time_{k}"] = res["exit_time"]
        rec[f"exit_price_{k}"] = res["exit_price"]
        rec[f"r_result_{k}"] = r
        rec[f"net_r_{k}"] = (r - sc) if (sc is not None and pd.notna(sc)) else np.nan
        rec[f"dur_hours_{k}"] = (res["exit_time"] - entry_time).total_seconds() / 3600.0


def _held_until(t, k):
    """When this trade stops being open on track k. None = trade not on this track."""
    out = t.get(f"outcome_{k}")
    if out is None:
        return None
    if out == "open_at_cutoff":
        return FAR
    et = t.get(f"exit_time_{k}")
    return FAR if (et is None or pd.isna(et)) else et


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
    m15_high = m15_df["high"].to_numpy()
    m15_low = m15_df["low"].to_numpy()
    m15_close_idx = pd.DatetimeIndex(m15_df["timestamp"] + TF_M15)
    n_d1, n_h1, n_m15 = len(d1_ts), len(h1_ts), len(m15_ts)

    bias_events = []          # D1 close times at which bias changed between two real values
    prev_bias = _get_bias(ps)
    bias_attr_seen = None

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

            b = _get_bias(ps)
            if bias_attr_seen is None:
                bias_attr_seen = _bias_attr_name(ps)
            if b != prev_bias:
                if prev_bias is not None and b is not None:
                    bias_events.append(d1_close_time)
                prev_bias = b
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
                if rec.get("status") == "opened":
                    _rescan_no_time_stop(rec, m15_close_idx, m15_high, m15_low)
                trades.append(rec)

        if m_i and m_i % progress_every == 0:
            print(f"[{pair}] {m_i}/{n_m15} m15 bars, {len(trades)} attempts, "
                  f"{time.time() - t0:.0f}s elapsed", flush=True)

    if bias_attr_seen is None:
        print(f"[{pair}] WARNING: no bias attribute found on PairSetup "
              f"(tried {_BIAS_ATTRS}); flip tags will be empty.", flush=True)
    else:
        print(f"[{pair}] bias attribute: ps.{bias_attr_seen}; bias flips seen: {len(bias_events)}", flush=True)

    # ---- Per-track stacking / one-at-a-time / flip tagging ----
    opened = sorted([t for t in trades if t.get("status") == "opened"],
                    key=lambda t: t["entry_time"])
    for k in ("t1", "t2"):
        track = [t for t in opened if _held_until(t, k) is not None]
        last_free = None
        for i, t in enumerate(track):
            et = t["entry_time"]
            held = _held_until(t, k)
            n_open = sum(1 for j in range(i) if _held_until(track[j], k) > et)
            t[f"open_at_entry_{k}"] = n_open
            if last_free is None or et >= last_free:
                t[f"kept_1at_{k}"] = True
                last_free = held
            else:
                t[f"kept_1at_{k}"] = False
            t[f"flip_while_open_{k}"] = bool(any(et < e <= held for e in bias_events)) if bias_attr_seen else None
        for t in opened:
            if _held_until(t, k) is None:
                t[f"open_at_entry_{k}"] = None
                t[f"kept_1at_{k}"] = False
                t[f"flip_while_open_{k}"] = None

    elapsed = time.time() - t0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(trades) if trades else pd.DataFrame(columns=["pair", "status"])
    df.to_csv(OUT_DIR / f"{pair}_trades.csv", index=False)

    statuses = df["status"].value_counts().to_dict() if len(df) else {}
    lines = [
        f"### Phase 4 practice run: {pair}",
        f"- Window: start of data to {config.PRACTICE_END} (bars fully closed only), NO time stop",
        f"- Attempts logged: {len(df)}  |  Status: {statuses}",
        f"- Bias attribute: {bias_attr_seen}  |  bias flips seen: {len(bias_events)}",
    ]
    if opened:
        od = pd.DataFrame(opened)
        for k, label in (("t1", "T1 (headline, qualifying T1 only)"), ("t2", "T2 (fixed 3R, all opened)")):
            tr = od[od[f"outcome_{k}"].notna()]
            res = tr[tr[f"outcome_{k}"].isin(["target", "stop"])]
            n_win = int((res[f"outcome_{k}"] == "target").sum())
            kept = res[res[f"kept_1at_{k}"].fillna(False).astype(bool)]
            lines += [
                f"- **{label}**: trades={len(tr)}, resolved={len(res)}, "
                f"open_at_cutoff={int((tr[f'outcome_{k}'] == 'open_at_cutoff').sum())}",
                f"  - Stacking: wins={n_win}, mean net R={res[f'net_r_{k}'].mean():.3f}, "
                f"sum net R={res[f'net_r_{k}'].sum():.2f}, max already-open at entry="
                f"{int(tr[f'open_at_entry_{k}'].max())}",
                f"  - One-at-a-time: trades={len(kept)}, mean net R={kept[f'net_r_{k}'].mean():.3f}, "
                f"sum net R={kept[f'net_r_{k}'].sum():.2f}",
                f"  - Duration (hours): median={res[f'dur_hours_{k}'].median():.1f}, "
                f"mean={res[f'dur_hours_{k}'].mean():.1f}, max={res[f'dur_hours_{k}'].max():.1f}",
            ]
    lines.append(f"- Run time: {elapsed:.0f}s\n")
    summary = "\n".join(lines)
    print("\n" + summary, flush=True)
    gh = os.environ.get("GITHUB_STEP_SUMMARY")
    if gh:
        with open(gh, "a") as f:
            f.write(summary + "\n")
    return df


if __name__ == "__main__":
    run_pair(os.environ.get("PAIR", "eurusd"))
