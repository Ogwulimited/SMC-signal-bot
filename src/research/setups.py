"""
setups.py -- Phase 3 candidate signal generation (per-pair state machine).
"""

import pandas as pd
import numpy as np

from src import config
from src.research import primitives
from src.research import zones

def compute_d1_bias(d1_df):
    """
    Computes current D1 directional bias from closed D1 bars.
    Returns dict: state ("bullish"/"bearish"/"reversing"/"none"),
    plus the triggering event's time/direction/label.
    """
    tf = pd.Timedelta(days=1)
    swings = primitives.find_swings(d1_df, config.D1_SWING_N, tf)
    events = primitives.detect_bos_choch(d1_df, swings, tf)

    if events.empty:
        return {"state": "none", "time": pd.NaT, "direction": None, "label": None}

    last = events.iloc[-1]
    if last["label"] == "CHoCH":
        state = "reversing"
    else:
        state = "bullish" if last["direction"] == "up" else "bearish"

    return {"state": state, "time": last["time"], "direction": last["direction"], "label": last["label"]}


def select_htf_zone(d1_zones, h4_zones, bias_direction, current_low, current_high):
    """
    Picks which HTF zone to watch: active D1 zone if price overlaps it,
    else nearest active H4 zone in the trend direction. Returns dict or None.
    """
    def _active(zones_df):
        z = zones_df[(zones_df["direction"] == bias_direction) & (zones_df["invalidated_at"].isna())]
        return z

    d1_active = _active(d1_zones)
    if not d1_active.empty:
        last_d1 = d1_active.sort_values("confirm_time").iloc[-1]
        overlaps = (current_low <= last_d1["zone_high"]) and (current_high >= last_d1["zone_low"])
        if overlaps:
            return {"timeframe": "D1", "zone_low": last_d1["zone_low"], "zone_high": last_d1["zone_high"],
                    "confirm_time": last_d1["confirm_time"]}

    h4_active = _active(h4_zones)
    if h4_active.empty:
        return None

    mid_price = (current_low + current_high) / 2.0
    h4_active = h4_active.copy()
    h4_active["dist"] = ((h4_active["zone_low"] + h4_active["zone_high"]) / 2.0 - mid_price).abs()
    nearest = h4_active.sort_values("dist").iloc[0]
    return {"timeframe": "H4", "zone_low": nearest["zone_low"], "zone_high": nearest["zone_high"],
            "confirm_time": nearest["confirm_time"]}


def find_candidate_obs(df, tf, bos_choch_events, pools):
    """
    Combines detect_order_blocks + find_liquidity_taken to produce
    candidate OB setups that pass both structural and liquidity checks.
    """
    atr_series = primitives.compute_atr(df, period=14).shift(1)
    time_to_idx = {t: i for i, t in enumerate(df["timestamp"])}

    obs = zones.detect_order_blocks(df, tf, bos_choch_events)
    obs = obs[obs["valid_pretouch"] == True].reset_index(drop=True)

    rows = []
    for _, row in obs.iterrows():
        bos_open_time = row["bos_time"] - tf
        bos_idx = time_to_idx.get(bos_open_time)
        atr_at_bos = atr_series.iloc[bos_idx] if bos_idx is not None else np.nan
        edge = row["ob_high"] if row["direction"] == "bullish" else row["ob_low"]

        liq = zones.find_liquidity_taken(pools, bos_open_time, row["l_base_price"],
                                          row["direction"], atr_at_bos=atr_at_bos, ob_upper_edge=edge)
        if liq.empty:
            continue
        out_row = row.to_dict()
        out_row["liquidity_pools"] = liq.to_dict("records")
        rows.append(out_row)

    cols = list(obs.columns) + ["liquidity_pools"]
    return pd.DataFrame(rows, columns=cols)
