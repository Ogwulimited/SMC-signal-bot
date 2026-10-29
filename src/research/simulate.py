"""
simulate.py -- Phase 4 trade simulation: pool targeting, exit scanning, trade log.
"""

import pandas as pd
import numpy as np

from src import config
from src.research import primitives
from src.research import zones


_POOL_COLS = ["pool_price", "side", "pool_type", "confirm_time", "expires_at", "swept_time"]


def build_pool_universe(h1_df, h4_df, tf_h1, tf_h4, bad_days=None):
    """
    Merge every liquidity-pool source into one normalized table, for use as
    T1 target candidates. Columns: pool_price, side, pool_type, confirm_time,
    expires_at, swept_time. Each source df is reduced to this common schema
    before concatenation -- extra columns (cluster_size, member_indexes,
    timeframe, bucket, index, timestamp) are dropped here, not upstream.
    """
    frames = []

    for side in ("low", "high"):
        frames.append(zones.find_swing_pools(h1_df, tf_h1, "H1", side, bad_days))
        frames.append(zones.find_swing_pools(h4_df, tf_h4, "H4", side, bad_days))

    frames.append(zones.detect_equal_lows(h1_df, tf_h1, bad_days))
    frames.append(zones.find_equal_highs(h1_df, tf_h1, bad_days))
    frames.append(zones.find_pdh_pdl(h1_df, tf_h1, bad_days))
    frames.append(zones.find_pwh_pwl(h1_df, tf_h1, bad_days))
    frames.append(zones.find_pmh_pml(h1_df, tf_h1, bad_days))

    frames = [f[_POOL_COLS] for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame(columns=_POOL_COLS)

    out = pd.concat(frames, ignore_index=True)
    for col in ["confirm_time", "expires_at", "swept_time"]:
        out[col] = pd.to_datetime(out[col], utc=True)
    return out


def select_t1_target(pool_universe, entry_time, entry_price, direction, risk_r,
                      spread_cost_r, min_r=None):
    """
    Pick the T1 target: the nearest liquidity pool ahead of price in the trade
    direction whose net-of-cost R clears min_r. If none clears it, the trade
    is skipped (skipped_no_t1=True). Also reports the nearest pool's R
    regardless of whether it qualifies, for diagnostic purposes (logging both
    readings of the 3R rule, per explicit instruction).

    No-lookahead: only pools with confirm_time <= entry_time are considered.
    A pool already swept or expired before entry_time is excluded.
    """
    if min_r is None:
        min_r = config.MIN_TARGET_R

    side = "high" if direction == "bullish" else "low"
    cand = pool_universe[pool_universe["side"] == side].copy()

    # Defensive dtype coercion: if confirm_time/expires_at/swept_time is
    # entirely NaT in this subset, pandas infers a tz-naive dtype, which
    # then fails comparison against a tz-aware entry_time. Force tz-aware
    # UTC regardless of content (all-real, all-NaT, or mixed).
    for col in ["confirm_time", "expires_at", "swept_time"]:
        cand[col] = pd.to_datetime(cand[col], utc=True)

    cand = cand[cand["confirm_time"] <= entry_time]
    cand = cand[(cand["swept_time"].isna()) | (cand["swept_time"] >= entry_time)]
    cand = cand[(cand["expires_at"].isna()) | (cand["expires_at"] >= entry_time)]
    cand = cand[cand["pool_price"] > entry_price] if side == "high" else cand[cand["pool_price"] < entry_price]

    if cand.empty:
        return {"nearest_pool_type": None, "nearest_pool_price": np.nan, "nearest_r_net": np.nan,
                "chosen_pool_type": None, "chosen_pool_price": np.nan,
                "chosen_r_gross": np.nan, "chosen_r_net": np.nan, "skipped_no_t1": True}

    cand["distance"] = (cand["pool_price"] - entry_price).abs()
    cand = cand.sort_values("distance").reset_index(drop=True)
    cand["r_gross"] = cand["distance"] / risk_r
    cand["r_net"] = cand["r_gross"] - spread_cost_r

    nearest = cand.iloc[0]
    qualifying = cand[cand["r_net"] >= min_r]

    if qualifying.empty:
        return {"nearest_pool_type": nearest["pool_type"], "nearest_pool_price": nearest["pool_price"],
                "nearest_r_net": nearest["r_net"],
                "chosen_pool_type": None, "chosen_pool_price": np.nan,
                "chosen_r_gross": np.nan, "chosen_r_net": np.nan, "skipped_no_t1": True}

    chosen = qualifying.iloc[0]
    return {"nearest_pool_type": nearest["pool_type"], "nearest_pool_price": nearest["pool_price"],
            "nearest_r_net": nearest["r_net"],
            "chosen_pool_type": chosen["pool_type"], "chosen_pool_price": chosen["pool_price"],
            "chosen_r_gross": chosen["r_gross"], "chosen_r_net": chosen["r_net"],
            "skipped_no_t1": False}


def scan_trade_exit(m15_df, tf_m15, tf_h1, entry_time, entry_price, direction,
                     stop_price, target_price, time_stop_h1_bars=None):
    """
    Walk forward M15 bar-by-bar from entry_time until stop, target, or the
    time-stop window elapses. Same-candle rule: if one bar's range touches
    both stop and target, stop wins (conservative). time_stop_h1_bars counts
    in H1-bar units (default config.TIME_STOP_H1_BARS) but scanning itself
    happens at M15 resolution for precision.

    target_price may be None/NaN (e.g. a skipped-T1 trade being scanned for
    diagnostic purposes only) -- in that case only stop and time-stop apply.

    Returns dict: exit_reason ("stop"/"target"/"time_stop"), exit_time,
    exit_price.
    """
    if time_stop_h1_bars is None:
        time_stop_h1_bars = config.TIME_STOP_H1_BARS

    bull = direction == "bullish"
    cutoff_time = entry_time + time_stop_h1_bars * tf_h1
    has_target = target_price is not None and pd.notna(target_price)

    after = m15_df[m15_df["timestamp"] + tf_m15 > entry_time].reset_index(drop=False)

    last_bar = None
    for _, r in after.iterrows():
        bar_close_time = r["timestamp"] + tf_m15
        if bar_close_time > cutoff_time:
            break
        last_bar = r

        stop_hit = (r["low"] <= stop_price) if bull else (r["high"] >= stop_price)
        target_hit = False
        if has_target:
            target_hit = (r["high"] >= target_price) if bull else (r["low"] <= target_price)

        if stop_hit:
            return {"exit_reason": "stop", "exit_time": bar_close_time, "exit_price": stop_price}
        if target_hit:
            return {"exit_reason": "target", "exit_time": bar_close_time, "exit_price": target_price}

    if last_bar is not None:
        return {"exit_reason": "time_stop", "exit_time": last_bar["timestamp"] + tf_m15,
                "exit_price": last_bar["close"]}
    return {"exit_reason": "time_stop", "exit_time": entry_time, "exit_price": entry_price}


def compute_r_result(entry_price, exit_price, direction, risk_r):
    """Signed R outcome of a closed trade. Positive = profit, negative = loss."""
    if direction == "bullish":
        return (exit_price - entry_price) / risk_r
    return (entry_price - exit_price) / risk_r


def build_trade_from_setup(ps, pair, h1_df, m15_df, pool_universe, tf_h1, tf_m15):
    """
    Phase 4: consume a PairSetup instance whose winner has just resolved,
    compute stop/entry/risk, apply the spread-cost filter, select T1/T2
    targets, scan both to their exits, then free the pair via close_trade().

    OB winner: entry = fill2_price, realized one M15 bar after touch_time
    (fill2 executes at the next bar's open after touch -- entry_time is
    therefore touch_time + tf_m15, so the forward exit-scan starts strictly
    after the entry bar itself, not from inside it).
    Stop = far OB edge -+ 0.1*ATR(H1,14), ATR taken at the OB's own H1 bar
    index, shifted by 1 -- same convention as zones.py's _atr_shifted.

    Breaker winner: entry = limit_price, entry_time = fill_time, stop = the
    breaker's own precomputed stop field (already zone edge -+0.1 ATR).

    Design decision: T1 and T2 are both evaluated as hypothetical outcomes
    of the SAME entry -- the trade is still considered "opened" even if T1
    fails to qualify (skipped_no_t1=True); only the T1 exit fields are left
    blank in that case. This supports the explicit goal of comparing
    real-liquidity targeting (T1) against blind fixed-3R (T2) on identical
    entries, not just on the subset of trades that happen to qualify for T1.

    Fix #5 (this session): added a defensive guard immediately after
    entry_price/stop_price are determined. Under normal operation this
    should never trigger post-Fix-5 (setups.py now never declares an OB
    winner before fill2_price exists) -- but as belt-and-suspenders against
    any future/edge-case path producing a None or NaN entry/stop (e.g. a
    touch occurring on the very last bar of the loaded dataset, with no
    further bar ever arriving to realize fill2_price), this logs the
    attempt as status="skipped_invalid_entry" instead of crashing the
    entire run, consistent with the existing skipped_spread/skipped_no_t1
    pattern and the requirement that every episode attempt be logged.
    """
    if ps.winner == "ob":
        ob = ps.candidate_ob
        direction = ob["direction"]
        entry_price = ps.fill2_price
        entry_time = ps.touch_time + tf_m15
        atr_series = primitives.compute_atr(h1_df, period=config.ATR_PERIOD).shift(1)
        atr_at_ob = atr_series.iloc[ob["ob_index"]]
        if direction == "bullish":
            stop_price = ob["ob_low"] - 0.1 * atr_at_ob
        else:
            stop_price = ob["ob_high"] + 0.1 * atr_at_ob
    elif ps.winner == "breaker":
        br = ps.breaker
        direction = br["direction"]
        entry_price = br["limit_price"]
        entry_time = br["fill_time"]
        stop_price = br["stop"]
    else:
        raise ValueError(f"build_trade_from_setup called with no winner resolved: {ps.winner}")

    # Fix #5 defensive guard: never let a None/NaN entry or stop reach the
    # risk calculation below -- log and skip cleanly instead of crashing.
    entry_invalid = entry_price is None or pd.isna(entry_price)
    stop_invalid = stop_price is None or pd.isna(stop_price)
    if entry_invalid or stop_invalid:
        record = {"pair": pair, "model": ps.winner, "direction": direction,
                  "entry_time": entry_time, "entry_price": entry_price,
                  "stop_price": stop_price, "status": "skipped_invalid_entry"}
        ps.close_trade()
        return record

    risk_r = abs(entry_price - stop_price)
    spread = config.SPREAD_PRICE[pair]
    spread_cost_r = spread / risk_r if risk_r > 0 else np.nan

    record = {"pair": pair, "model": ps.winner, "direction": direction,
              "entry_time": entry_time, "entry_price": entry_price,
              "stop_price": stop_price, "risk_r": risk_r,
              "spread_cost_r": spread_cost_r}

    if pd.isna(spread_cost_r) or spread_cost_r > config.MAX_SPREAD_RISK_RATIO:
        record["status"] = "skipped_spread"
        ps.close_trade()
        return record

    t1 = select_t1_target(pool_universe, entry_time, entry_price, direction, risk_r, spread_cost_r)
    record.update({"t1_pool_type": t1["chosen_pool_type"],
                    "t1_target_price": t1["chosen_pool_price"],
                    "t1_r_gross": t1["chosen_r_gross"], "t1_r_net": t1["chosen_r_net"],
                    "t1_nearest_pool_type": t1["nearest_pool_type"],
                    "t1_nearest_r_net": t1["nearest_r_net"],
                    "skipped_no_t1": t1["skipped_no_t1"]})

    t2_target_price = (entry_price + config.MIN_TARGET_R * risk_r if direction == "bullish"
                        else entry_price - config.MIN_TARGET_R * risk_r)
    record["t2_target_price"] = t2_target_price

    if not t1["skipped_no_t1"]:
        t1_exit = scan_trade_exit(m15_df, tf_m15, tf_h1, entry_time, entry_price, direction,
                                   stop_price, t1["chosen_pool_price"])
        record.update({"exit_reason_t1": t1_exit["exit_reason"], "exit_time_t1": t1_exit["exit_time"],
                        "exit_price_t1": t1_exit["exit_price"],
                        "r_result_t1": compute_r_result(entry_price, t1_exit["exit_price"], direction, risk_r)})
    else:
        record.update({"exit_reason_t1": None, "exit_time_t1": pd.NaT,
                        "exit_price_t1": np.nan, "r_result_t1": np.nan})

    t2_exit = scan_trade_exit(m15_df, tf_m15, tf_h1, entry_time, entry_price, direction,
                               stop_price, t2_target_price)
    record.update({"exit_reason_t2": t2_exit["exit_reason"], "exit_time_t2": t2_exit["exit_time"],
                    "exit_price_t2": t2_exit["exit_price"],
                    "r_result_t2": compute_r_result(entry_price, t2_exit["exit_price"], direction, risk_r)})

    record["status"] = "opened"
    ps.close_trade()
    return record
