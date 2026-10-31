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
    wins on exact-equal resolution time.

    Fix #3 (prior session): h1_bos_event is now only matched against events with
    label=="BOS" (previously matched by direction only, which let a CHoCH -- or
    even an INIT -- event masquerade as "the BOS"). Confirmed on real 2023 EURUSD
    data to be the actual cause of candidate_ob always coming back None and
    self.breaker never updating (both downstream consumers correctly require
    label=="BOS", so a mislabeled h1_bos_event silently broke both paths at once).

    Fix #4 (prior session): h1_bos_event is now tracked continuously from the
    moment self.zone is established (self.zone["confirm_time"]) -- including
    before price ever touches the zone, and continuing to update after the
    zone is touched -- rather than latching onto the first direction+label
    match seen after zone-touch. This matches the intended trading model:
    numerous countertrend H1 BOS legs can print while price is still
    approaching a D1/H4 POI (pure bookkeeping, not acted on until price
    arrives), and a wide HTF zone can easily contain more than one such leg
    before a genuine CHoCH prints. The system always treats the *most
    recent* countertrend BOS as "the" BOS right up until a CHoCH breaks it
    -- never just the first one it happened to notice. Once CHoCH is
    confirmed (state -> CHOCH_SEEN), h1_bos_event is frozen: on_h1_close
    returns immediately for CHOCH_SEEN and all later states, so the
    breaker/OB machinery downstream always sees a stable, consistent
    reference.

    Fix #5 (prior session, partially reverted by Fix #5b -- see below):
    the OB side of the ob-vs-breaker race could previously be declared the
    winner (self.winner = "ob") the *instant* state flips to TRIGGERED on
    touch -- a full M15 bar before fill2_price (the OB's actual realized
    entry, which by design fills one bar after touch) had any chance to be
    computed. In real walk-forward usage (m15_df as a growing slice, one
    bar added per loop iteration) this left fill2_price = None at the
    moment build_trade_from_setup was called, crashing on
    `entry_price - stop_price` with a None operand. Fix #5 addressed this
    by (a) computing fill2_price before resolving the winner each call,
    using a >= timestamp comparison (gap-safe across weekends/holidays,
    instead of exact equality, which would otherwise fail forever across
    any such gap) -- this part is kept -- and (b) gating _resolve_winner's
    OB-side condition on fill2_price being non-None, not just
    state == TRIGGERED -- this part broke the locked Layer 6 contract
    (test_layer6_ob_wins, test_layer6_no_breaker_regression expect winner
    to resolve to "ob" the instant state == TRIGGERED, independent of
    fill2_price, which by design only resolves one bar later -- see
    test_fill2_resolves_on_next_bar). winner and fill2_price are two
    separate facts: who is ahead in the race vs. whether their entry price
    is realized yet.

    Fix #5b (prior session): reverted _resolve_winner to depend only on
    state == TRIGGERED for the OB side, restoring the Layer 6 contract.
    The actual guard against calling build_trade_from_setup before
    fill2_price is ready belongs at the CALL SITE (the simulator/
    walk-forward driver), not here: callers must check `winner == "ob"
    and fill2_price is None` and simply wait one more bar, rather than
    treating an unresolved fill2_price as a reason to alter who won.

    Fix #6 (prior session): persistent-hunting episode lifecycle +
    anti-duplication guard. Diagnostic walk-forward run exposed that
    close_trade() was sending the pair all the way back to IDLE while
    leaving self.zone untouched -- the very next on_h1_close call would
    then re-scan countertrend BOS history with no floor other than
    self.zone["confirm_time"], re-find the exact same BOS that fed the
    trade just closed (since no new countertrend BOS had necessarily
    printed yet), and replay the entire BOS_SEEN -> CHOCH_SEEN -> ARMED ->
    TRIGGERED chain off the same historical candles, re-logging the same
    trade repeatedly. Corrected trading model (confirmed by user,
    hand-drawn diagrams): after the first CHoCH confirms a pullback is
    over and the HTF trend is resuming, the episode should NOT go back to
    requiring a fresh HTF zone touch for every subsequent trade -- it
    should stay "live", actively hunting for new countertrend-BOS -> CHoCH
    -> breaker/OB cycles (each with its own fresh local POI, independently
    validated) for as long as price hasn't yet closed (candle body) beyond
    the swing high/low that price broke away from to start the original
    pullback -- or until the HTF bias itself flips. Two new fields support
    this: last_traded_bos_time (floors the countertrend-BOS scan so a
    just-traded sweep can never be re-selected -- see Fix #7 below, this
    is now superseded as the actual duplication guard but retained as a
    diagnostic field) and leg_ceiling_price (the fixed reference price for
    the leg-ending close-beyond check, captured once from the first
    countertrend BOS of the leg that carries a known swing reference --
    see cold-start guard note below -- held fixed thereafter regardless of
    how far h1_bos_event itself drifts during later cycles). A trade
    closing now triggers the new _cycle_reset() (stay in EPISODE, keep
    hunting, preserve last_traded_bos_time/leg_ceiling_price) rather than
    the full _reset_episode() (back to IDLE, forget everything) -- full
    reset is now reserved for: the leg-ceiling being cleared, a bias flip,
    a zone change, an OB invalidated by an H1 close-through, or a
    same-bar-ambiguous cancellation (all unchanged/pre-existing full-reset
    triggers except the leg-ceiling case, which is new). Cold-start guard
    (also this session): leg_ceiling_price is only captured from a
    countertrend BOS whose last_opposite_price is a known (non-NaN) value
    -- this is only ever blank at true cold-start, before any swing of the
    opposite kind has ever been confirmed anywhere in the dataset; without
    this guard a blank value could be locked in permanently for the whole
    leg, silently disabling the leg-ending check for that entire leg.

    Fix #7 (this session): Fix #6's duplication guard (last_traded_bos_time,
    cleared by _reset_episode()) was proven insufficient by a real
    walk-forward run on EURUSD 2023 (duplicate trade off the same
    2022-12-22 17:00 BOS, five days apart). Root cause: the leg-ceiling
    check in on_h1_close is allowed -- correctly, per the trading model --
    to fire a full reset on a single H1 candle body closing beyond the
    ceiling, even if that break does not hold and price closes back inside
    the range on the very next candle. That is not a bug; clause (e)(1) is
    working exactly as specified, on a strict body-close basis, and is NOT
    changed by this fix. The bug was that "full reset" also wiped
    last_traded_bos_time, giving the state machine total amnesia about
    which sweep had already produced a trade -- so when the exact same
    historical countertrend BOS re-appeared as "most recent" after the
    failed ceiling break, it looked brand new and got re-traded.

    Fix: self.traded_bos_times (a set, not a single value) now holds every
    BOS timestamp that has ever produced a trade in the current leg. It is
    populated by _cycle_reset() (cumulative -- grows across cycles, never
    shrinks mid-leg) and is the actual filter used in on_h1_close's
    countertrend-BOS scan (excludes ANY previously-traded timestamp, not
    just ones before the most recent). Critically, _reset_episode() does
    NOT clear it, regardless of which of its trigger sites fired --
    leg-ceiling clear, OB invalidated by H1 close-through, or same-bar-
    ambiguous cancellation all leave it untouched. It is cleared in
    exactly two places, both inside on_d1_close, matching the user's
    explicit instruction ("only cleared on bias flip or genuine zone
    change"): when bias leaves bullish/bearish, and when bias_changed or
    zone_changed is True. The third on_d1_close reset trigger (a D1 close
    beyond the zone's far edge, with state already active) is deliberately
    NOT treated as a clearing point -- it is neither a bias flip nor a
    zone change by the letter of that instruction, even though it is
    structurally similar to the H1 leg-ceiling check and could in
    principle carry the same single-candle-noise risk. This is a
    conscious, narrower scope decision, not an oversight: there is no
    trade-log evidence (yet) that this specific trigger has ever caused a
    duplicate. last_traded_bos_time is left in place, still updated the
    same way as Fix #6, purely as a legacy/diagnostic single-value field;
    it is no longer read by the duplication-guard filter.

    Phase 4: close_trade() is the simulator's hook to free this pair for a new
    trade cycle once an open trade has been closed in the market (stop / T1 /
    T2 / time-stop hit). As of Fix #6 it calls _cycle_reset(), not
    _reset_episode() -- see Fix #6 note above.
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
        # Fix #6: persistent-hunting lifecycle state.
        self.last_traded_bos_time = pd.NaT
        self.leg_ceiling_price = None
        # Fix #7: the real anti-duplication memory. Grows across cycles
        # within a leg; survives _reset_episode() entirely; cleared only
        # by on_d1_close on a genuine bias flip or zone change.
        self.traded_bos_times = set()

    def _reset_episode(self):
        """Full reset: forget this leg entirely, go back to IDLE, require a
        fresh HTF zone touch before anything can arm again. Triggered by:
        bias flip, zone change, zone invalidation (on_d1_close); an OB
        invalidated by an H1 close-through; a same-bar-ambiguous
        cancellation; or (Fix #6) the leg ceiling being cleared.

        Fix #7: deliberately does NOT touch self.traded_bos_times, no
        matter which trigger called this method. That field is only ever
        cleared from inside on_d1_close, at the specific points matching
        a genuine bias flip or zone change -- see the Fix #7 class
        docstring note for why this reset method itself must not be the
        place that clears it."""
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
        self.last_traded_bos_time = pd.NaT
        self.leg_ceiling_price = None

    def _cycle_reset(self):
        """
        Fix #6: called when a trade closes but the HTF leg is still active
        (ceiling not yet cleared, bias not flipped). Unlike _reset_episode,
        this does NOT go back to IDLE or require a fresh HTF zone touch --
        per the trading model, once the first CHoCH confirms a leg is
        underway, the system keeps actively hunting for new
        countertrend-BOS -> CHoCH -> breaker/OB cycles for as long as the
        leg is live. leg_ceiling_price and last_traded_bos_time are
        deliberately NOT cleared here -- they persist across cycles within
        the same leg; only _reset_episode() clears them.

        Fix #7: also adds the just-closed cycle's BOS timestamp to
        self.traded_bos_times (cumulative set, never cleared here or by
        _reset_episode() -- see class docstring). This is now the actual
        anti-duplication filter used in on_h1_close; last_traded_bos_time
        above is retained only as a legacy/diagnostic single-value field.
        """
        if self.h1_bos_event is not None:
            self.last_traded_bos_time = self.h1_bos_event["time"]
            self.traded_bos_times.add(self.h1_bos_event["time"])

        self.state = "EPISODE"
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
        has been closed in the market (stop hit, T1/T2 hit, or time-stop hit),
        or an attempt was skipped for cost/data reasons after a real entry
        point had already been identified in price. Frees the pair to keep
        hunting for the next cycle within the same HTF leg (Fix #6:
        _cycle_reset(), not a full reset). Does not alter self.bias or
        self.zone -- those are only touched by on_d1_close, exactly as before.
        """
        self._cycle_reset()

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
            # Fix #7: genuine bias flip (leaving bullish/bearish entirely)
            # is one of the two explicit clearing points for the
            # persistent anti-duplication memory.
            self.traded_bos_times = set()
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
            # Fix #7: genuine bias change or a genuine new HTF zone is the
            # other explicit clearing point for the persistent
            # anti-duplication memory.
            self.traded_bos_times = set()
        self.zone = new_zone

        if self.zone is not None and self.state != "IDLE":
            far_edge = self.zone["zone_low"] if new_bias["state"] == "bullish" else self.zone["zone_high"]
            d1_close = d1_df.iloc[-1]["close"]
            beyond = (d1_close < far_edge) if new_bias["state"] == "bullish" else (d1_close > far_edge)
            if beyond:
                # Fix #7 note: this reset deliberately does NOT clear
                # self.traded_bos_times. It is neither a bias flip nor a
                # zone change by the letter of the user's Option 1
                # instruction, even though it is structurally similar to
                # the H1 leg-ceiling check. Flagged as a conscious,
                # narrower scope decision -- revisit if a future
                # walk-forward run ever shows a duplicate correlated with
                # this specific trigger.
                self._reset_episode()

    def on_h1_close(self, h1_df, pools, tf):
        if self.bias is None or self.bias["state"] not in ("bullish", "bearish") or self.zone is None:
            return

        last_bar = h1_df.iloc[-1]

        # Fix #6: leg-ending ceiling check, takes priority over everything
        # else. leg_ceiling_price is the swing high (bullish leg) / swing
        # low (bearish leg) that price broke away from to start the
        # original pullback -- captured once below, held fixed for the
        # whole leg. The moment a candle BODY closes beyond it, the HTF
        # leg is considered complete: full reset, wait for the next
        # pullback to draw a brand-new POI.
        #
        # Fix #7 note: this check is intentionally UNCHANGED -- clause
        # (e)(1) of the trading model is correct exactly as specified,
        # including the case where a single candle's close-beyond does
        # not hold and price closes back inside the range on the very
        # next candle. _reset_episode() below is allowed to fire on that
        # basis. What changed is that _reset_episode() no longer wipes
        # the persistent anti-duplication memory (self.traded_bos_times)
        # -- see Fix #7 class docstring.
        if self.leg_ceiling_price is not None:
            bull = self.bias["state"] == "bullish"
            cleared = (last_bar["close"] > self.leg_ceiling_price) if bull else (last_bar["close"] < self.leg_ceiling_price)
            if cleared:
                self._reset_episode()
                return

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

        # Fix #4: once CHoCH has confirmed, h1_bos_event must stay frozen --
        # the breaker/OB machinery downstream depends on it being stable.
        # Nothing below this point should run for CHOCH_SEEN or later.
        if self.state == "CHOCH_SEEN":
            return

        bias_dir = "up" if self.bias["state"] == "bullish" else "down"
        sweep_dir = "down" if bias_dir == "up" else "up"

        # Fix #3 + Fix #4 combined: track the most recent countertrend BOS
        # (direction == sweep_dir AND label == "BOS", never a CHoCH or INIT
        # event mistaken for one) continuously from the moment self.zone was
        # established (self.zone["confirm_time"]) -- including before price
        # ever touches the zone, and continuing to update after the zone has
        # been touched, right up until a CHoCH breaks whichever BOS is
        # currently held. This mirrors a trader watching the chart update
        # their "latest pullback leg" reference in real time, rather than
        # the state machine latching onto the first match it happens to see
        # only after zone-touch.
        #
        # Fix #7 (supersedes the Fix #6 filter): the candidate pool is
        # floored by excluding every timestamp in self.traded_bos_times --
        # the full history of sweeps that have already produced a trade
        # this leg, surviving even a full _reset_episode() (see class
        # docstring). A countertrend BOS that already produced a trade can
        # never be re-selected, regardless of how many ceiling-triggered
        # or OB-invalidation resets happen in between. This is the actual
        # anti-duplication fix: a real walk-forward run showed the Fix #6
        # version (floor on last_traded_bos_time, wiped by every full
        # reset) was insufficient -- a leg-ceiling reset that failed to
        # hold could wipe the floor entirely and let an already-traded
        # sweep be rediscovered.
        #
        # Note this floor is applied only to the BOS-candidate pool, not
        # to `events` itself -- `events` (zone-floored only) is reused
        # below for CHoCH matching, and does not need the extra floor
        # since CHoCH candidates are already required to post-date
        # h1_bos_event's time.
        swings = primitives.find_swings(h1_df, config.STRUCTURE_SWING_N, tf)
        events = primitives.detect_bos_choch(h1_df, swings, tf)
        if not events.empty:
            events = events[events["time"] >= self.zone["confirm_time"]]
            bos_pool = events
            if self.traded_bos_times:
                bos_pool = bos_pool[~bos_pool["time"].isin(self.traded_bos_times)]
            bos_candidates = bos_pool[(bos_pool["direction"] == sweep_dir) & (bos_pool["label"] == "BOS")]
            if not bos_candidates.empty:
                self.h1_bos_event = bos_candidates.iloc[-1]
                # Fix #6: capture the leg ceiling exactly once -- the first
                # time a countertrend BOS carrying a KNOWN (non-NaN)
                # last_opposite_price is seen since the last full reset.
                # last_opposite_price is the swing high (sweep_dir ==
                # "down") / swing low (sweep_dir == "up") that price broke
                # away from to start the pullback -- the dashed "HTF BOS"
                # ceiling line in the trading diagram. This is normally
                # the very first countertrend BOS of the leg, since every
                # normal countertrend BOS is only possible because an H1
                # CHoCH already confirmed the swing it's breaking away
                # from. The ONLY time last_opposite_price can be NaN is
                # true cold-start -- before any swing of the opposite kind
                # has ever been confirmed anywhere in the dataset (only
                # possible in the very first leg). Guarding on pd.notna()
                # here prevents permanently locking in an unusable blank
                # ceiling for the whole leg in that one-time case; instead
                # the check is simply retried on every later update to
                # h1_bos_event until one with a real value appears. Once
                # set, never overwritten again until _reset_episode()
                # clears it, even though h1_bos_event itself keeps
                # drifting to newer, closer countertrend BOS events on
                # later cycles.
                if self.leg_ceiling_price is None and pd.notna(self.h1_bos_event["last_opposite_price"]):
                    self.leg_ceiling_price = self.h1_bos_event["last_opposite_price"]

        if self.state == "IDLE":
            overlaps = (last_bar["low"] <= self.zone["zone_high"]) and (last_bar["high"] >= self.zone["zone_low"])
            if overlaps:
                self.episode_start_time = last_bar["timestamp"]
                # If a countertrend BOS was already being tracked before
                # price arrived, we already know "the" BOS -- skip straight
                # to watching for CHoCH. Otherwise wait for the first one.
                self.state = "BOS_SEEN" if self.h1_bos_event is not None else "EPISODE"
            return

        if events.empty:
            return

        if self.state == "EPISODE" and self.h1_bos_event is not None:
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
                # Fix #1 (diagnostic #4 finding): a failed OB match here must
                # not reset the episode -- that would wipe h1_bos_event, the
                # one input detect_breakers() needs. OB and breaker are
                # independent, parallel entry candidates: we always progress
                # to CHOCH_SEEN once CHoCH confirms; candidate_ob is
                # populated only if a valid OB was found, left None
                # otherwise (breaker-only episode).
                if not match.empty:
                    self.candidate_ob = match.iloc[0].to_dict()
                self.state = "CHOCH_SEEN"

    def _update_breaker(self, h1_df, m15_df, tf_h1, tf_m15):
        bos_row = pd.DataFrame([self.h1_bos_event])
        result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_row)
        self.breaker = result.iloc[0].to_dict() if not result.empty else None

    def _resolve_winner(self):
        # Fix #5b: winner is decided purely by which side has a known
        # timestamp (touch_time for OB, fill_time for breaker) -- NOT by
        # whether the OB side's actual fill price (fill2_price) has been
        # realized yet. Those are separate facts: Layer 6's locked test
        # contract (test_layer6_ob_wins, test_layer6_no_breaker_regression)
        # requires winner to resolve the instant state == TRIGGERED, one
        # full bar before fill2_price can possibly be known
        # (test_fill2_resolves_on_next_bar). The earlier Fix 5 gated this
        # on fill2_price, which silently broke that contract (winner stuck
        # at None). The real guard against building a trade before
        # fill2_price is ready belongs at the CALL SITE of
        # build_trade_from_setup, not here.
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

        # Fix #1 continued: this only needs h1_bos_event (confirmed from
        # zones.py source); that is the only gate here, independent of
        # candidate_ob or state, so breaker-only episodes remain reachable.
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

        # Fix #5 Part A (kept): compute fill2_price (OB path's actual fill,
        # one bar after touch) using a >= inequality rather than exact
        # timestamp equality -- exact equality silently fails forever
        # across any weekend/holiday gap between the touch bar and the
        # next real bar, since no bar's open time would ever exactly equal
        # touch_time in that case. Computing this before _resolve_winner()
        # is still correct/harmless (identical result either order, since
        # _resolve_winner no longer reads fill2_price) and is kept for
        # clarity and gap-safety.
        if self.state == "TRIGGERED" and self.fill2_price is None:
            next_candidates = m15_df[m15_df["timestamp"] >= self.touch_time]
            if not next_candidates.empty:
                self.fill2_price = next_candidates.iloc[0]["open"]

        if self.winner is None:
            self._resolve_winner()
