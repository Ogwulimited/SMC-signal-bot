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


class PairSetup:
    """
    Stateful per-pair state machine implementing the setups spec.
    States covered this slice: IDLE -> EPISODE -> BOS_SEEN -> CHOCH_SEEN -> ARMED.
    SWEPT/TRIGGERED/IN_TRADE/CLOSED are later slices (need Phase 4 stop/target math).

    Arming (Layer 4) tries Model A first, falls back to Model B if Model A
    hasn't resolved yet -- both checked via the same zones.find_inducement
    call, which already implements "A or B" fallback internally. This is a
    single sequence, not two separate parallel models; a trade is skipped
    only if neither model resolves.
    """

    def __init__(self, pair):
        self.pair = pair
        self.state = "IDLE"
        self.bias = None
        self.zone = None
        self.episode_start_time = None
        self.h1_bos_event = None
        self.h1_choch_event = None
        self.candidate_ob = None
        self.model = None
        self.m15_bos_time = None
        self.idm_price = None
        self.idm_time = None
        self.idm_swept_time = None
        self.touch_time = None
        self.same_bar_ambiguous = None
        self.invalid_h1_close_through = None

    def _reset_episode(self):
        self.state = "IDLE"
        self.episode_start_time = None
        self.h1_bos_event = None
        self.h1_choch_event = None
        self.candidate_ob = None
        self.model = None
        self.m15_bos_time = None
        self.idm_price = None
        self.idm_time = None
        self.idm_swept_time = None
        self.touch_time = None
        self.same_bar_ambiguous = None
        self.invalid_h1_close_through = None

    def on_d1_close(self, d1_df, d1_zones, h4_zones, current_low, current_high):
        new_bias = compute_d1_bias(d1_df)
        bias_changed = (
            self.bias is None
            or new_bias["state"] != self.bias["state"]
            or new_bias["direction"] != self.bias["direction"]
        )
        self.bias = new_bias

        if new_bias["state"] not in ("bullish", "bearish"):
            self._reset_episode()
            self.zone = None
            return

        new_zone = select_htf_zone(d1_zones, h4_zones, new_bias["state"], current_low, current_high)
        zone_changed = (
            self.zone is None or new_zone is None
            or new_zone["zone_low"] != self.zone["zone_low"]
            or new_zone["zone_high"] != self.zone["zone_high"]
            or new_zone["confirm_time"] != self.zone["confirm_time"]
        )
        if bias_changed or zone_changed:
            self._reset_episode()
        self.zone = new_zone

        if self.zone is not None and self.state != "IDLE":
            far_edge = self.zone["zone_low"] if new_bias["state"] == "bullish" else self.zone["zone_high"]
            d1_close = d1_df.iloc[-1]["close"]
            beyond = (d1_close < far_edge) if new_bias["state"] == "bullish" else (d1_close > far_edge)
            if beyond:
                self._reset_episode()

    def on_h1_close(self, h1_df, pools, tf):
        if self.bias is None or self.bias["state"] not in ("bullish", "bearish") or self.zone is None:
            return
        if self.state == "ARMED":
            return

        bias_dir = "up" if self.bias["state"] == "bullish" else "down"
        sweep_dir = "down" if bias_dir == "up" else "up"
        last_bar = h1_df.iloc[-1]

        if self.state == "IDLE":
            overlaps = (last_bar["low"] <= self.zone["zone_high"]) and (last_bar["high"] >= self.zone["zone_low"])
            if overlaps:
                self.state = "EPISODE"
                self.episode_start_time = last_bar["timestamp"]
            return

        swings = primitives.find_swings(h1_df, config.STRUCTURE_SWING_N, tf)
        events = primitives.detect_bos_choch(h1_df, swings, tf)
        if events.empty:
            return
        events = events[events["time"] >= self.episode_start_time]

        if self.state == "EPISODE":
            bos_candidates = events[events["direction"] == sweep_dir]
            if not bos_candidates.empty:
                self.h1_bos_event = bos_candidates.iloc[0]
                self.state = "BOS_SEEN"

        if self.state == "BOS_SEEN":
            choch_candidates = events[
                (events["time"] > self.h1_bos_event["time"])
                & (events["direction"] == bias_dir)
                & (events["label"] == "CHoCH")
            ]
            if not choch_candidates.empty:
                self.h1_choch_event = choch_candidates.iloc[0]
                candidates = find_candidate_obs(h1_df, tf, events, pools)
                match = candidates[
                    (candidates["bos_time"] == self.h1_bos_event["time"])
                    & (candidates["choch_time"] == self.h1_choch_event["time"])
                ]
                if not match.empty:
                    self.candidate_ob = match.iloc[0].to_dict()
                    self.state = "CHOCH_SEEN"
                else:
                    self._reset_episode()

    def on_m15_close(self, h1_df, m15_df, tf_h1, tf_m15):
        """
        Arming check (Layer 4), delegated entirely to zones.find_inducement
        (already-locked Phase 2 code) rather than reimplementing M15/H1
        BOS/IDM logic by hand. find_inducement tries Model A first and
        falls back to Model B internally -- we accept whichever resolves
        first. Only if neither resolves do we stay in CHOCH_SEEN and retry
        on the next M15 close.
        """
        if self.state != "CHOCH_SEEN" or self.candidate_ob is None:
            return

        result = zones.find_inducement(
            h1_df, m15_df, tf_h1, tf_m15,
            choch_time=self.h1_choch_event["time"],
            l_base_time=self.candidate_ob["l_base_time"],
            ob_low=self.candidate_ob["ob_low"],
            ob_high=self.candidate_ob["ob_high"],
            direction=self.candidate_ob["direction"],
        )

        if result is None:
            return  # neither model resolved yet; stay in CHOCH_SEEN, retry on next M15 close

        self.model = result["model"]  # "A" or "B" -- kept for research/logging only
        self.m15_bos_time = result["armed_time"]
        self.idm_price = result["idm_price"]
        self.idm_time = result["idm_time"]
        self.idm_swept_time = result.get("swept_time")
        self.touch_time = result.get("touch_time")
        self.same_bar_ambiguous = result.get("same_bar_ambiguous")
        self.invalid_h1_close_through = result.get("invalid_h1_close_through")
        self.state = "ARMED"
