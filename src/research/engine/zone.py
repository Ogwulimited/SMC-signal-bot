"""Zone leg (Phase 4 Step 5).

When price reaches one of the HTF zones built at BOS time (OB / FVG / Breaker)
AND 4H + D1 bias is still aligned, open a "zone scan" looking for a **with-trend**
15m structure chain (CHoCH in bias direction -> BOS in bias direction -> IDM)
and place a with-trend entry at the 15m OB or Breaker.

Simultaneously (Addition 1 - H1 Continuation Zones):
When 4H + D1 bias is aligned and a fresh pro-trend 1H BOS closes, record the
last opposite-colored 1H candle before that BOS as a candidate 1H continuation
Order Block. When price returns to touch that fresh 1H zone (within 48h of birth),
run a parallel non-interfering 15m confirmation scan (counter-trend 15m shift ->
pro-trend 15m CHoCH -> pro-trend 15m BOS setting 15m IDM -> IDM sweep ->
next-candle-open entry at 1:3 R static target) with strict 1-trade-per-zone cap,
room-to-opposing-HTF-zone check, 24h scan/order expiry, and D1/H4 zone precedence.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from . import cycle as cy
from . import orders as ord_mod
from . import takeaway1 as t1


# Module settings toggled by run_cycle.set_variant.
SETTINGS = {
    "enabled": True,
    "h1_continuation": True,
}

# Minimum room (in R multiples) to an opposing untouched D1/H4 zone for H1 continuation trades.
H1_OPPOSING_HTF_MIN_R = 1.5

# Freshness & expiry guards for 1H Continuation Zones.
H1_ZONE_MAX_AGE = pd.Timedelta(hours=48)
H1_SCAN_MAX_DURATION = pd.Timedelta(hours=24)
H1_ORDER_EXPIRY = pd.Timedelta(hours=24)

# Maximum runaway distance (in 1H ATR multiples) above/below the 1H zone during M15 confirmation scan.
H1_SCAN_RUNAWAY_ATR = 2.5


class ZoneRecorder(cy.CycleRecorder):
    """Extends CycleRecorder with the with-trend Zone leg (D1/H4 Deep + H1 Continuation)."""

    def __init__(self, pair: str):
        super().__init__(pair)
        self._scan: Optional[Dict] = None
        self.scans: List[Dict] = []
        # Parallel 1H Continuation Zone state (never mutates self.state or self._pb)
        self._h1_zones: List[Dict] = []
        self._h1_scan: Optional[Dict] = None
        self._h1_bos: bool = False
        self.h1_scans: List[Dict] = []

    # ---- Pullback start: also clear any leftover scan ----
    def _begin_pullback(self, tf, bos_event, snap, df_slice, atr):
        if self._scan is not None:
            self._end_scan(bos_event.confirmed_at, "new_bos")
        super()._begin_pullback(tf, bos_event, snap, df_slice, atr)
        # Tag pullback orders placed later so reports can separate legs.
        if self._pb is not None:
            self._pb["zones_for_scan"] = [dict(z) for z in self._pb["zones"]]

    def _place_order(self, kind, box, idm, bar_ts, bos_event):
        n_before = len(self.orders)
        super()._place_order(kind, box, idm, bar_ts, bos_event)
        if len(self.orders) > n_before:
            self.orders[-1]["leg"] = "pullback"

    # ---- Intercept zone touch: enter SCAN instead of dropping to IDLE ----
    def _end_pullback(self, ts: pd.Timestamp, reason: str):
        pb = self._pb
        super()._end_pullback(ts, reason)
        if not SETTINGS["enabled"] or pb is None:
            return
        if reason == "zone" and self.htf_bias in ("Bullish", "Bearish"):
            self._begin_scan(ts, pb)

    # ---- Step order: update bias -> cancel misaligned -> superclass step -> scan step -> H1 step ----
    def step(self, ts, bars, snaps, events, poi_events, df_slices):
        # Superclass handles bias update, order cancelling, pullback step, new BOS.
        super().step(ts, bars, snaps, events, poi_events, df_slices)
        if self._scan is not None:
            self._scan_step(ts, bars, events, df_slices)
        if SETTINGS.get("h1_continuation", True):
            self._h1_step(ts, bars, events, df_slices)

    def finalize(self, last_ts: pd.Timestamp):
        if self._scan is not None:
            self._end_scan(last_ts, "end_of_data")
        if self._h1_scan is not None:
            self._end_h1_scan(last_ts, "end_of_data")
        super().finalize(last_ts)

    # ---- D1/H4 Deep Zone scan lifecycle ----
    def _begin_scan(self, ts: pd.Timestamp, pb: Dict):
        # Find all zones touched on this bar; pick highest priority: ob > breaker > fvg.
        # (zones list was populated in priority order in build_zones.)
        prio = {"ob": 0, "breaker": 1, "fvg": 2}
        zones = sorted(pb["zones"], key=lambda z: prio.get(z["kind"], 9))
        chosen = zones[0] if zones else None
        if chosen is None:
            return
        self._scan = {
            "pair": self.pair,
            "htf_tf": pb["htf_tf"],
            "bias": pb["bias"],
            "zone": chosen,
            "zones": pb["zones"],
            "impulse_high": pb["impulse_high"],
            "impulse_low": pb["impulse_low"],
            "started_at": ts,
            "ended_at": None,
            "end_reason": None,
            "choch": None,
            "choch_box": None,
            "bos": None,
            "idm": None,
            "idm_swept_at": None,
            "ceiling": pb["impulse_high"] if pb["bias"] == "Bullish" else pb["impulse_low"],
        }
        self.state = "SCAN"
        self.counts["zone_scan"] += 1
        self.counts[f"zone_scan_{chosen['kind']}"] += 1

    def _end_scan(self, ts: pd.Timestamp, reason: str):
        if self._scan is None:
            return
        self._scan["ended_at"] = ts
        self._scan["end_reason"] = reason
        self.scans.append(self._scan)
        self._scan = None
        if self.state == "SCAN":
            self.state = cy.IDLE
        self.counts[f"scan_end_{reason}"] += 1

    def _scan_step(self, ts, bars, events, df_slices):
        sc = self._scan
        b15 = bars.get("ltf")
        if b15 is None:
            return
        bh, bl, bc = float(b15["high"]), float(b15["low"]), float(b15["close"])
        bull = sc["bias"] == "Bullish"

        # 1. Bias must remain aligned with scan bias.
        if self.htf_bias != sc["bias"]:
            self._end_scan(ts, "bias_lost")
            return

        # 2. Ceiling break before order triggers -> abort scan.
        if bull and bh >= sc["ceiling"]:
            self._end_scan(ts, "ceiling_break")
            return
        if (not bull) and bl <= sc["ceiling"]:
            self._end_scan(ts, "ceiling_break")
            return

        # 3. Close past far side of every zone -> abort scan (zone failed).
        if bull and all(bc < z["low"] for z in sc["zones"]):
            self._end_scan(ts, "zone_broken")
            return
        if (not bull) and all(bc > z["high"] for z in sc["zones"]):
            self._end_scan(ts, "zone_broken")
            return

        # 4. Walk 15m events in WITH-TREND direction (same as scan bias).
        want = "bullish" if bull else "bearish"
        for e in events.get("ltf", []):
            if e.direction != want:
                continue
            if sc["choch"] is None:
                # Need a prior opposite-direction 15m BOS during the pullback first.
                if not self._pb_bos:
                    self.counts["zone_choch_no_pb_bos"] += 1
                    continue
                sc["choch"] = e
                sc["choch_box"] = self._register_15m_box(e, df_slices["ltf"], want)
                self.counts["zone_setups"] += 1
            elif sc["bos"] is None and e.origin == "BOS":
                sc["bos"] = e
                idm = cy._find_idm(df_slices["ltf"], sc["choch"].confirmed_at,
                                   e.confirmed_at, want)
                sc["idm"] = idm
                if idm is not None:
                    self.counts["zone_idm_set"] += 1

        # 5. Track IDM sweep and place with-trend order.
        idm = sc["idm"]
        if idm is not None and sc["idm_swept_at"] is None:
            swept = (bl <= idm["price"]) if bull else (bh >= idm["price"])
            if swept:
                sc["idm_swept_at"] = ts
                self._place_zone_orders(sc, ts)

    def _place_zone_orders(self, sc: Dict, bar_ts: pd.Timestamp):
        """With-trend entry: OB first; if OB already broken, Breaker at same box."""
        if cy.SKIP_ASIAN and t1.in_asian(bar_ts):
            self.counts["zone_asian_skipped"] += 1
            return
        if sc["bos"] is None:
            self.counts["zone_ob_no_bos"] += 1
            return
        if sc["idm"] is None or sc["idm_swept_at"] is None:
            self.counts["zone_ob_no_idm"] += 1
            return
        box = sc["choch_box"]
        if box is None:
            self.counts["zone_no_choch_box"] += 1
            return
        if box["created_at"] >= bar_ts:
            self.counts["zone_ob_same_bar"] += 1
            return
        atr = self.atrs["ltf"].current_atr
        if atr is None:
            return
        if box["status"] in ("fresh", "tested"):
            kind = "ob"
        elif box["status"] == "used":
            self.counts["zone_ob_box_used"] += 1
            return
        else:
            self.counts["zone_ob_box_dead"] += 1
            return

        # Zone trades are WITH-trend: buy for Bullish bias, sell for Bearish.
        # _build_order uses "Bullish" -> sell (counter-trend). Flip string so it builds with-trend.
        flipped_bias = "Bearish" if sc["bias"] == "Bullish" else "Bullish"
        o = ord_mod._build_order(
            self.pair, sc["htf_tf"], flipped_bias, kind, box,
            sc["idm"], float(atr), bar_ts, sc["bos"], sc["ceiling"],
        )
        if o is None:
            self.counts[f"zone_{kind}_skipped_spread"] += 1
            return
        o["htf_bias"] = sc["bias"]  # restore true HTF bias label
        o["leg"] = "zone"
        o["zone_kind"] = sc["zone"]["kind"]
        o["zone_tf"] = sc["htf_tf"]
        self.orders.append(o)
        self.counts[f"zone_orders_{kind}"] += 1

    # =========================================================================
    # Addition 1: With-Trend 1H Continuation Zones (1H OB + 15m Confirmation)
    # =========================================================================
    def _h1_step(self, ts, bars, events, df_slices):
        b15 = bars.get("ltf")
        if b15 is None:
            return
        bh, bl, bc = float(b15["high"]), float(b15["low"]), float(b15["close"])

        # 0. Expire pending 1H continuation orders that have gone stale (> 24h unfilled)
        for o in self.orders:
            if (
                o["status"] == "pending"
                and o.get("leg") == "zone"
                and o.get("zone_tf") == "H1"
                and (ts - o["placed_at"]) > H1_ORDER_EXPIRY
            ):
                o["status"] = "cancelled"
                o["cancel_reason"] = "expired_24h"
                o["cancelled_at"] = ts
                self.counts["h1_orders_expired_24h"] += 1

        # 1. If 4H + D1 alignment is lost, clear active 1H zones and abort 1H scan
        if self.htf_bias not in ("Bullish", "Bearish"):
            if self._h1_scan is not None:
                self._end_h1_scan(ts, "bias_lost")
            self._h1_zones.clear()
            self._h1_bos = False
            return

        # 2. Discard any stored 1H zones that don't match current HTF bias or are spent
        kept_zones: List[Dict] = []
        for z in self._h1_zones:
            if z["bias"] != self.htf_bias or z.get("spent", False):
                continue
            # If untouched and older than 48h, expire the stale 1H zone
            if not z.get("touched", False) and (ts - z["created_at"]) > H1_ZONE_MAX_AGE:
                self.counts["h1_zone_expired_48h"] += 1
                continue
            kept_zones.append(z)
        self._h1_zones = kept_zones

        # 3. Track counter-trend 15m structure shift (CHoCH or BOS against HTF bias)
        #    so the subsequent pro-trend 15m CHoCH inside the 1H zone represents a genuine turn
        against = "bearish" if self.htf_bias == "Bullish" else "bullish"
        for e in events.get("ltf", []):
            if e.direction == against:
                self._h1_bos = True

        # 4. Detect new pro-trend 1H BOS events and birth fresh 1H continuation OBs
        want_h1 = "bullish" if self.htf_bias == "Bullish" else "bearish"
        for e in events.get("H1", []):
            if e.origin == "BOS" and e.direction == want_h1:
                self.counts["h1_bos_aligned"] += 1
                atr_h1 = self.atrs["H1"].current_atr
                if atr_h1 is not None:
                    z = self._build_h1_ob_zone(e, df_slices["H1"], float(atr_h1), self.htf_bias)
                    if z is not None:
                        self._h1_zones.append(z)
                        self.counts["h1_zones_born"] += 1

        # 5. Check active 1H zones for far-edge invalidation or first touch
        bull = self.htf_bias == "Bullish"
        surviving: List[Dict] = []
        touched_now: List[Dict] = []
        for z in self._h1_zones:
            # Far-side close invalidates the 1H zone immediately
            if bull and bc < z["low"]:
                self.counts["h1_zone_broken_pre"] += 1
                continue
            if (not bull) and bc > z["high"]:
                self.counts["h1_zone_broken_pre"] += 1
                continue

            # Touch check (only after the 1H BOS bar has closed -> zero lookahead)
            if ts > z["created_at"]:
                hit = (bl <= z["high"]) if bull else (bh >= z["low"])
                if hit and not z["touched"]:
                    z["touched"] = True
                    z["touched_at"] = ts
                    touched_now.append(z)
            surviving.append(z)
        self._h1_zones = surviving

        # 6. If a fresh 1H zone was touched and no 1H scan is running,
        #    start the 1H continuation scan
        if touched_now and self._h1_scan is None:
            # Pick most recently created 1H zone
            chosen = sorted(touched_now, key=lambda x: x["created_at"], reverse=True)[0]
            self._begin_h1_scan(ts, chosen, b15)

        # 7. Step active 1H scan
        if self._h1_scan is not None:
            self._h1_scan_step(ts, bars, events, df_slices)

        # 8. Mark 1H zone as spent as soon as any order linked to it fills (strictly 1 trade per 1H zone)
        for o in self.orders:
            if o.get("leg") == "zone" and o.get("zone_tf") == "H1" and o["status"] != "pending":
                zid = o.get("h1_zone_id")
                if zid is not None and o["status"] in ("open", "closed") and o.get("filled_at") is not None:
                    for z in self._h1_zones:
                        if z["id"] == zid and not z["spent"]:
                            z["spent"] = True
                            self.counts["h1_zone_spent"] += 1
                    if self._h1_scan is not None and self._h1_scan["zone"]["id"] == zid:
                        self._end_h1_scan(ts, "zone_spent")

    def _build_h1_ob_zone(
        self, bos_event, df_h1: pd.DataFrame, atr: float, bias: str
    ) -> Optional[Dict]:
        """Find the last opposite-colored 1H candle before the 1H BOS leg."""
        confirm_ts = bos_event.confirmed_at
        broken_ts = bos_event.broken_swing_ts
        leg = df_h1.loc[(df_h1.index >= broken_ts) & (df_h1.index <= confirm_ts)]
        if len(leg) < 2:
            return None
        bull = bias == "Bullish"
        extrema_ts = leg["low"].idxmin() if bull else leg["high"].idxmax()
        window = df_h1.loc[(df_h1.index >= extrema_ts) & (df_h1.index <= confirm_ts)]
        want_bear_candle = bull  # bullish OB = last bearish candle before the up-move
        ob_row = None
        ob_ts = None
        for ts_i, r in window.iloc[::-1].iterrows():
            is_bear = r["close"] < r["open"]
            is_bull = r["close"] > r["open"]
            if (want_bear_candle and is_bear) or ((not want_bear_candle) and is_bull):
                ob_row = r
                ob_ts = ts_i
                break
        if ob_row is None:
            ob_row = df_h1.loc[extrema_ts]
            ob_ts = extrema_ts

        hi, lo = float(ob_row["high"]), float(ob_row["low"])
        if hi <= lo:
            return None
        if (hi - lo) > t1.MAX_OB_ATR * atr:
            if bull:
                hi = lo + t1.MAX_OB_ATR * atr
            else:
                lo = hi - t1.MAX_OB_ATR * atr

        impulse_high = float(leg["high"].max())
        impulse_low = float(leg["low"].min())
        self.counts["h1_zone_id_seq"] += 1
        return {
            "id": self.counts["h1_zone_id_seq"],
            "kind": "ob",
            "tf": "H1",
            "bias": bias,
            "high": hi,
            "low": lo,
            "atr": float(atr),
            "candle_ts": ob_ts,
            "created_at": confirm_ts,
            "bos_event": bos_event,
            "impulse_high": impulse_high,
            "impulse_low": impulse_low,
            "touched": False,
            "touched_at": None,
            "spent": False,
        }

    def _begin_h1_scan(self, ts: pd.Timestamp, zone: Dict, b15):
        bull = zone["bias"] == "Bullish"
        bh, bl = float(b15["high"]), float(b15["low"])
        ceiling = max(zone["impulse_high"], bh) if bull else min(zone["impulse_low"], bl)
        self._h1_scan = {
            "pair": self.pair,
            "htf_tf": "H1",
            "bias": zone["bias"],
            "zone": zone,
            "started_at": ts,
            "ended_at": None,
            "end_reason": None,
            "choch": None,
            "choch_box": None,
            "bos": None,
            "idm": None,
            "idm_swept_at": None,
            "ceiling": ceiling,
            "order_placed": False,
        }
        self.counts["h1_scan"] += 1

    def _end_h1_scan(self, ts: pd.Timestamp, reason: str):
        if self._h1_scan is None:
            return
        self._h1_scan["ended_at"] = ts
        self._h1_scan["end_reason"] = reason
        self.h1_scans.append(self._h1_scan)
        self._h1_scan = None
        self.counts[f"h1_end_{reason}"] += 1

    def _h1_scan_step(self, ts, bars, events, df_slices):
        sc = self._h1_scan
        b15 = bars.get("ltf")
        if b15 is None:
            return
        bh, bl, bc = float(b15["high"]), float(b15["low"]), float(b15["close"])
        bull = sc["bias"] == "Bullish"
        z = sc["zone"]

        # 1. Bias must remain aligned
        if self.htf_bias != sc["bias"]:
            self._end_h1_scan(ts, "bias_lost")
            return

        # 2. Zone spent check
        if z.get("spent", False):
            self._end_h1_scan(ts, "zone_spent")
            return

        # 3. 24-hour scan duration guard: if M15 confirmation hasn't completed within 24h of touch, abort
        if (ts - sc["started_at"]) > H1_SCAN_MAX_DURATION:
            z["spent"] = True
            self._end_h1_scan(ts, "scan_expired_24h")
            return

        # 4. Runaway distance guard before order placement:
        #    On a fresh 1H continuation pullback, the 1H BOS high/low is right next to the 1H OB,
        #    so the confirming 15m CHoCH -> BOS displacement leg naturally pokes past that 1H high/low.
        #    Allow the 15m displacement leg up to 2.5x 1H ATR beyond the 1H zone while updating the
        #    swing ceiling; once the order is placed, simulate_orders locks that displacement peak as the ceiling.
        z_atr = float(z.get("atr", 0.0))
        if bull:
            if z_atr > 0 and bh >= (float(z["high"]) + H1_SCAN_RUNAWAY_ATR * z_atr):
                self._end_h1_scan(ts, "scan_ceiling_break")
                return
            if bh > sc["ceiling"]:
                sc["ceiling"] = bh
        else:
            if z_atr > 0 and bl <= (float(z["low"]) - H1_SCAN_RUNAWAY_ATR * z_atr):
                self._end_h1_scan(ts, "scan_ceiling_break")
                return
            if bl < sc["ceiling"]:
                sc["ceiling"] = bl

        # 5. Close beyond far edge of the 1H OB invalidates the zone and scan
        if bull and bc < z["low"]:
            z["spent"] = True
            self._end_h1_scan(ts, "scan_far_break")
            return
        if (not bull) and bc > z["high"]:
            z["spent"] = True
            self._end_h1_scan(ts, "scan_far_break")
            return

        # 6. Walk 15m events in WITH-TREND direction (CHoCH -> BOS -> IDM)
        want = "bullish" if bull else "bearish"
        for e in events.get("ltf", []):
            if e.direction != want:
                continue
            if sc["choch"] is None:
                if not self._h1_bos:
                    self.counts["h1_choch_no_bos"] += 1
                    continue
                sc["choch"] = e
                sc["choch_box"] = self._register_15m_box(e, df_slices["ltf"], want)
                self.counts["h1_setups"] += 1
            elif sc["bos"] is None and e.origin == "BOS":
                sc["bos"] = e
                idm = cy._find_idm(
                    df_slices["ltf"], sc["choch"].confirmed_at, e.confirmed_at, want
                )
                sc["idm"] = idm
                if idm is not None:
                    self.counts["h1_idm_set"] += 1

        # 7. Track IDM sweep and place 1H continuation order (strictly 1 order attempt per scan)
        idm = sc["idm"]
        if idm is not None and sc["idm_swept_at"] is None and not sc["order_placed"]:
            swept = (bl <= idm["price"]) if bull else (bh >= idm["price"])
            if swept:
                sc["idm_swept_at"] = ts
                self._place_h1_zone_order(sc, ts)

    def _has_opposing_htf_obstacle(self, entry: float, risk: float, bull: bool) -> bool:
        """Reject H1 continuation trade if a fresh/tested opposing D1/H4 POI sits within 1.5 R."""
        opp_dir = "bearish" if bull else "bullish"
        min_dist = H1_OPPOSING_HTF_MIN_R * risk
        for tf in ("D1", "H4"):
            book = self.books.get(tf)
            if book is None:
                continue
            for p in book.active:
                if p.direction != opp_dir:
                    continue
                if p.status not in ("fresh", "tested"):
                    continue
                if bull:
                    # Opposing supply zone ahead of bullish entry
                    if p.low > entry and (p.low - entry) < min_dist:
                        return True
                else:
                    # Opposing demand zone ahead of bearish entry
                    if p.high < entry and (entry - p.high) < min_dist:
                        return True
        return False

    def _place_h1_zone_order(self, sc: Dict, bar_ts: pd.Timestamp):
        if cy.SKIP_ASIAN and t1.in_asian(bar_ts):
            self.counts["h1_asian_skipped"] += 1
            return
        # Precedence rule: if a D1/H4 deep zone scan is currently active and already placed an order
        # on the same 15m box, skip to avoid duplicating the exact same trade.
        box = sc["choch_box"]
        if box is None:
            self.counts["h1_no_choch_box"] += 1
            return
        for existing in self.orders:
            if (
                existing.get("leg") == "zone"
                and existing.get("zone_tf") in ("D1", "H4")
                and existing["box_created_at"] == box["created_at"]
                and existing["status"] in ("pending", "open")
            ):
                self.counts["h1_duplicate_with_htf_zone_skipped"] += 1
                sc["order_placed"] = True
                return

        if sc["bos"] is None:
            self.counts["h1_ob_no_bos"] += 1
            return
        if sc["idm"] is None or sc["idm_swept_at"] is None:
            self.counts["h1_ob_no_idm"] += 1
            return
        if box["created_at"] >= bar_ts:
            self.counts["h1_ob_same_bar"] += 1
            return
        atr = self.atrs["ltf"].current_atr
        if atr is None:
            return
        atr_f = float(atr)
        if box["status"] in ("fresh", "tested"):
            kind = "ob"
        elif box["status"] == "used":
            self.counts["h1_ob_box_used"] += 1
            return
        else:
            self.counts["h1_ob_box_dead"] += 1
            return

        # Quality Guard 1: 15m Order Block width filter (0.25x to 1.75x 15m ATR)
        box_w = float(box["high"]) - float(box["low"])
        if box_w < 0.25 * atr_f or box_w > 1.75 * atr_f:
            self.counts["h1_ob_box_size_filtered"] += 1
            return

        # Quality Guard 2: Minimum 0.5x 15m ATR separation between Inducement and 15m OB edge
        bull = sc["bias"] == "Bullish"
        idm_price = float(sc["idm"]["price"])
        if bull:
            idm_dist = idm_price - float(box["high"])
        else:
            idm_dist = float(box["low"]) - idm_price
        if idm_dist < 0.5 * atr_f:
            self.counts["h1_ob_idm_too_close"] += 1
            return

        flipped_bias = "Bearish" if bull else "Bullish"
        o = ord_mod._build_order(
            self.pair, "H1", flipped_bias, kind, box,
            sc["idm"], atr_f, bar_ts, sc["bos"], sc["ceiling"],
        )
        if o is None:
            self.counts[f"h1_{kind}_skipped_spread"] += 1
            return

        # Quality Guard 3: Minimum stop distance floor (0.5x 15m ATR) so tight 15m OBs aren't clipped by noise
        min_risk = 0.5 * atr_f
        if o["risk"] < min_risk:
            if o["direction"] == "buy":
                o["sl"] = o["entry"] - min_risk
                o["risk"] = min_risk
                o["tp_3r"] = o["entry"] + 3.0 * min_risk
            else:
                o["sl"] = o["entry"] + min_risk
                o["risk"] = min_risk
                o["tp_3r"] = o["entry"] - 3.0 * min_risk
            self.counts["h1_ob_min_risk_padded"] += 1

        # Room-to-target check against opposing untouched D1/H4 zones
        if self._has_opposing_htf_obstacle(o["entry"], o["risk"], bull):
            self.counts["h1_blocked_opposing_htf"] += 1
            return

        o["htf_bias"] = sc["bias"]
        o["leg"] = "zone"
        o["zone_kind"] = sc["zone"]["kind"]
        o["zone_tf"] = "H1"
        o["h1_zone_id"] = sc["zone"]["id"]
        self.orders.append(o)
        sc["order_placed"] = True
        self.counts[f"h1_orders_{kind}"] += 1
