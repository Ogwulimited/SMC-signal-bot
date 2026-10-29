"""
setups.py -- Phase 3 candidate signal generation (per-pair state machine).
"""

import pandas as pd
import numpy as np

from src import config
from src.research import primitives
from src.research import zones


def compute_d1_bias(d1_df):
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


def _scan_sweep_and_touch(m15_df, tf_m15, armed_time, idm_price, ob_low, ob_high, direction, bad_days=None):
    bull = direction == "bullish"
    m15_after = m15_df[m15_df["timestamp"] + tf_m15 > armed_time].reset_index(drop=False)

    swept_time, swept_idx = pd.NaT, None
    for _, r in m15_after.iterrows():
        if bad_days and r["timestamp"].date() in bad_days:
            continue
        if bull and r["low"] < idm_price:
            swept_time, swept_idx = r["timestamp"] + tf_m15, r["index"]
            break
        if (not bull) and r["high"] > idm_price:
            swept_time, swept_idx = r["timestamp"] + tf_m15, r["index"]
            break

    touch_time, same_bar_ambiguous = pd.NaT, False
    if swept_idx is not None:
        after_sweep = m15_df[m15_df["timestamp"] >= m15_df["timestamp"].iloc[swept_idx]].reset_index(drop=False)
        for _, r in after_sweep.iterrows():
            touched = (r["low"] <= ob_high) if bull else (r["high"] >= ob_low)
            if touched:
                if r["index"] == swept_idx:
                    same_bar_ambiguous = True
                else:
                    touch_time = r["timestamp"] + tf_m15
                break

    return {"swept_time": swept_time, "touch_time": touch_time, "same_bar_ambiguous": same_bar_ambiguous}


class PairSetup:
    """
    State machine states: IDLE -> EPISODE -> BOS_SEEN -> CHOCH_SEEN -> ARMED -> SWEPT -> TRIGGERED.
    Layer 6 breaker: self.breaker is a dict/None snapshot refreshed every M15 close once
    BOTH candidate_ob AND h1_bos_event are set. self.winner ("ob"/"breaker"/None) freezes
    whichever side resolves first; losing side stops updating. Tie-break (untested): OB
    wins on exact-equal resolution time. Known limitation: h1_bos_event matched by direction
    only, not label=="BOS" -- if the very first H1 event is "INIT", detect_breakers won't
    find it and self.breaker stays None for that episode (not fixed -- would touch locked
    Layer 3 code).

    Phase 4: close_trade() is the simulator's hook to free this pair for a new episode
    once an open trade has been closed in the market (stop / T1 / T2 / time-stop hit).
    It is a thin public wrapper around the existing _reset_episode() -- no new state logic.
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
        self.fill1_price = None
        self.fill2_price = None
        self.last_cancel_reason = None
        self.breaker = None
        self.winner = None
        self.resolved_at = pd.NaT

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
        self.fill1_price = None
        self.fill2_price = None
        self.breaker = None
        self.winner = None
        self.resolved_at = pd.NaT

    def close_trade(self):
        """
        Phase 4 hook: called by the simulator once an open trade for this pair
        has been closed in the market (stop hit, T1/T2 hit, or time-stop hit).
        Frees the pair to begin hunting for a brand-new episode from IDLE.
        Does not alter self.bias or self.zone -- those are only touched by
        on_d1_close, exactly as before.
        """
        self._reset_episode()

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

        last_bar = h1_df.iloc[-1]

        if self.state in ("ARMED", "SWEPT") and self.winner is None:
            ob_low = self.candidate_ob["ob_low"]
            ob_high = self.candidate_ob["ob_high"]
            bull = self.candidate_ob["direction"] == "bullish"
            invalidated = (last_bar["close"] < ob_low) if bull else (last_bar["close"] > ob_high)
            if invalidated:
                self.last_cancel_reason = "h1_close_through_ob"
                self._reset_episode()
            return

        if self.state in ("ARMED", "SWEPT", "TRIGGERED"):
            return

        bias_dir = "up" if self.bias["state"] == "bullish" else "down"
        sweep_dir = "down" if bias_dir == "up" else "up"

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
                # Fix #1 (diagnostic #4 finding): previously, a failed OB match
                # here called _reset_episode(), which wiped h1_bos_event -- the
                # one input detect_breakers() actually needs. That made the
                # breaker-block path structurally unreachable, regardless of
                # whether a real breaker setup existed. OB and breaker are
                # independent, parallel entry candidates (confirmed trading
                # logic): a failed OB match must not destroy the breaker's
                # inputs. We now always progress to CHOCH_SEEN once CHoCH
                # confirms; candidate_ob is populated only if a valid OB was
                # found, left None otherwise (breaker-only episode).
                if not match.empty:
                    self.candidate_ob = match.iloc[0].to_dict()
                self.state = "CHOCH_SEEN"

    def _update_breaker(self, h1_df, m15_df, tf_h1, tf_m15):
        bos_row = pd.DataFrame([self.h1_bos_event])
        result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_row)
        self.breaker = result.iloc[0].to_dict() if not result.empty else None

    def _resolve_winner(self):
        ob_time = self.touch_time if self.state == "TRIGGERED" else pd.NaT
        breaker_time = pd.NaT
        if self.breaker is not None and self.breaker.get("filled"):
            breaker_time = self.breaker.get("fill_time")

        ob_known = pd.notna(ob_time)
        breaker_known = pd.notna(breaker_time)

        if not ob_known and not breaker_known:
            return
        if ob_known and not breaker_known:
            self.winner, self.resolved_at = "ob", ob_time
        elif breaker_known and not ob_known:
            self.winner, self.resolved_at = "breaker", breaker_time
        else:
            if ob_time <= breaker_time:
                self.winner, self.resolved_at = "ob", ob_time
            else:
                self.winner, self.resolved_at = "breaker", breaker_time

        def on_m15_close(self, h1_df, m15_df, tf_h1, tf_m15):
        if self.state == "CHOCH_SEEN" and self.candidate_ob is not None:
            result = zones.find_inducement(
                h1_df, m15_df, tf_h1, tf_m15,
                choch_time=self.h1_choch_event["time"],
                l_base_time=self.candidate_ob["l_base_time"],
                ob_low=self.candidate_ob["ob_low"],
                ob_high=self.candidate_ob["ob_high"],
                direction=self.candidate_ob["direction"],
            )
            if result is not None:
                self.model = result["model"]
                self.m15_bos_time = result["armed_time"]
                self.idm_price = result["idm_price"]
                self.idm_time = result["idm_time"]
                self.idm_swept_time = pd.NaT
                self.touch_time = pd.NaT
                self.same_bar_ambiguous = False
                self.invalid_h1_close_through = False
                self.state = "ARMED"

        # Fix #1 continued: this used to require self.candidate_ob is not None
        # too, AND the block above used to `return` the whole function when
        # candidate_ob was None -- both of which made this line unreachable
        # for breaker-only episodes. detect_breakers() only needs
        # h1_bos_event (confirmed from zones.py source); that is now the only
        # gate here.
        if self.h1_bos_event is not None and self.winner is None:
            self._update_breaker(h1_df, m15_df, tf_h1, tf_m15)

        if self.state in ("ARMED", "SWEPT") and self.winner is None:
            scan = _scan_sweep_and_touch(
                m15_df, tf_m15,
                armed_time=self.m15_bos_time,
                idm_price=self.idm_price,
                ob_low=self.candidate_ob["ob_low"],
                ob_high=self.candidate_ob["ob_high"],
                direction=self.candidate_ob["direction"],
            )
            self.idm_swept_time = scan["swept_time"]

            if scan["same_bar_ambiguous"]:
                self.same_bar_ambiguous = True
                self.last_cancel_reason = "same_bar_ambiguous"
                self._reset_episode()
                return

            if pd.notna(scan["touch_time"]):
                self.touch_time = scan["touch_time"]
                edge = (self.candidate_ob["ob_high"] if self.candidate_ob["direction"] == "bullish"
                        else self.candidate_ob["ob_low"])
                self.fill1_price = edge
                self.state = "TRIGGERED"
            elif pd.notna(self.idm_swept_time) and self.state == "ARMED":
                self.state = "SWEPT"

        if self.winner is None:
            self._resolve_winner()

        if self.winner == "ob" and self.state == "TRIGGERED" and self.fill2_price is None:
            next_bar = m15_df[m15_df["timestamp"] == self.touch_time]
            if not next_bar.empty:
                self.fill2_price = next_bar.iloc[0]["open"]
