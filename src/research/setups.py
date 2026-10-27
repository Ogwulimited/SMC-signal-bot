"""
setups.py -- Phase 3 candidate signal generation (per-pair state machine).
"""

import pandas as pd
import numpy as np

from src import config
from src.research import primitives


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
