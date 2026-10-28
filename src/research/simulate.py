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
