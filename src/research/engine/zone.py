"""Stage 5 zone engine: D1/H4 deep zones + H1 with-trend continuation zones.
Pullback streams are recorded by the parent CycleRecorder in self.orders
(leg="pullback"). The D1/H4 zone stream and the H1 continuation zone stream
run alongside on the same M15 bar feed and record their orders in self.zorders
(leg="zone", distinguished by zone_tf in {"D1", "H4", "H1"}). Both lists are
combined at the end of a pair run and tagged for both COMBINED and isolated
scorecards.
"""
import pandas as pd
from src import config
from src.research.engine.cycle import CycleRecorder, IDLE

H1_OPPOSING_HTF_MIN_R = 1.5
H1_ZONE_MAX_AGE = pd.Timedelta(hours=48)
H1_SCAN_MAX_DURATION = pd.Timedelta(hours=24)
H1_ORDER_EXPIRY = pd.Timedelta(hours=24)
H1_SCAN_RUNAWAY_ATR = 2.5


class ZoneRecorder(CycleRecorder):
    def __init__(self, pair):
        super().__init__(pair)
        self.zorders = []
        self._z_scan = None
        self._z_bos = False
        # Parallel With-Trend H1 Continuation stream state
        self._h1_zones = []
        self._h1_scan = None
        self._h1_bos = False
        self._h1_last_seen_id = {"Bullish": -1, "Bearish": -1}

    # --- Pullback / Deep Zone hook overrides ---
    def _on_new_zones(self, zones):
        for z in zones:
            z["z_spent"] = False

    def _on_pb_end(self, now, reason):
        if reason == "bias_lost":
            if self._z_scan is not None:
                self._end_z_scan(now, "bias_lost")
            if self._h1_scan is not None:
                self._end_h1_scan(now, "bias_lost")
            self._h1_zones = []
            self._h1_bos = False

    def _end_z_scan(self, now, reason):
        for o in self.zorders:
            if o["end_time"] is None and o.get("zone_tf") in ("D1", "H4"):
                o["end_time"] = now
                o["end_reason"] = "zone_" + reason
        self._z_scan = None
        self._bump("z_end_" + reason)

    def _end_h1_scan(self, now, reason):
        for o in self.zorders:
            if o["end_time"] is None and o.get("zone_tf") == "H1":
                o["end_time"] = now
                o["end_reason"] = "h1_" + reason
        self._h1_scan = None
        self._bump("h1_end_" + reason)

    def _watch_orders(self, b, now):
        super()._watch_orders(b, now)
        bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
        for o in self.zorders:
            if o["end_time"] is not None:
                continue
            if o.get("zone_tf") == "H1" and (now - o["placed_time"]) >= H1_ORDER_EXPIRY:
                o["end_time"] = now
                o["end_reason"] = "h1_expired_24h"
                self._bump("h1_orders_expired_24h")
                continue
            c = o["ceiling"]
            if c is not None:
                if (o["side"] == "buy" and bh > c) or (o["side"] == "sell" and bl < c):
                    o["end_time"] = now
                    o["end_reason"] = "ceiling_break"
                    continue
            if (o["side"] == "buy" and bc > o["target_3r"]) or (
                o["side"] == "sell" and bc < o["target_3r"]
            ):
                o["end_time"] = now
                o["end_reason"] = "ran_away"
                if o.get("zone_tf") == "H1":
                    self._bump("h1_ran_away")
                else:
                    self._bump("z_ran_away")

    def step(self, m15_bar, m15_events, htf_events, now, h1_events=()):
        super().step(m15_bar, m15_events, htf_events, now)
        self._z_step(m15_bar, m15_events, now)
        self._h1_step(m15_bar, m15_events, h1_events, now)

    # --- D1 / H4 Deep Zone stream ---
    def _z_step(self, m15_bar, m15_events, now):
        if self._pb is None:
            return
        up = self.htf_bias == "Bullish"
        want = "Bullish" if up else "Bearish"
        against = "Bearish" if up else "Bullish"
        for e in m15_events:
            if e.direction == against and e.origin == "BOS":
                self._z_bos = True
                self._bump("z_bos_seen")
            elif e.direction == want and e.origin == "CHoCH":
                if self._z_scan is not None:
                    if self._z_bos:
                        self._z_scan["setups"].append({
                            "id": len(self._z_scan["setups"]) + 1,
                            "choch_time": now,
                            "choch_level": float(e.broken_level),
                            "bos_time": None,
                            "idm": None,
                            "idm_Sweep_time": None,
                            "done": False,
                        })
                        self._bump("z_setups")
                    else:
                        self._bump("z_choch_no_bos")
                else:
                    self._bump("z_bos_cleared_by_choch")
                self._z_bos = False
        if self._z_scan is None:
            for z in self._pb["zones"]:
                if z.get("z_spent"):
                    continue
                if self._zone_touched(m15_bar, z, up):
                    if not self._z_bos:
                        continue
                    self._z_scan = {
                        "zone": z,
                        "touch_time": now,
                        "ceiling": self._pb["ceiling"],
                        "setups": [],
                    }
                    self._bump("z_scan")
                    break
        if self._z_scan is not None:
            self._z_scan_step(m15_bar, m15_events, now, up, want)

    def _z_scan_step(self, b, m15_events, now, up, want):
        sc = self._z_scan
        z = sc["zone"]
        bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
        if (up and bc < z["low"]) or ((not up) and bc > z["high"]):
            z["z_spent"] = True
            self._bump("z_scan_far_break")
            self._end_z_scan(now, "zone_far_break")
            return
        c = sc["ceiling"]
        if c is not None and ((up and bh > c) or ((not up) and bl < c)):
            self._bump("z_scan_ceiling_break")
            self._end_z_scan(now, "ceiling_break")
            return
        for o in self.zorders:
            if o["end_time"] is None and o.get("zone_tf") in ("D1", "H4"):
                if (o["side"] == "buy" and bl <= o["entry"]) or (
                    o["side"] == "sell" and bh >= o["entry"]
                ):
                    z["z_spent"] = True
                    self._bump("z_zone_spent")
                    for o2 in self.zorders:
                        if o2 is not o and o2["end_time"] is None and o2.get("zone_tf") in ("D1", "H4"):
                            o2["end_time"] = now
                            o2["end_reason"] = "zone_spent"
                    self._z_scan = None
                    return
        for e in m15_events:
            if e.direction == want and e.origin == "BOS":
                for s in sc["setups"]:
                    if s["bos_time"] is None and not s["done"]:
                        s["bos_time"] = now
                        s["idm"] = self._find_idm(s["choch_time"], now, not up)
                        if s["idm"] is not None:
                            self._bump("z_idm_set")
                        else:
                            self._bump("z_ob_no_idm")
                            s["done"] = True
        for s in sc["setups"]:
            if not s["done"]:
                self._z_try_setup(s, sc, b, now, up)

    def _z_try_setup(self, s, sc, b, now, up):
        if s["bos_time"] is None:
            self._bump("z_ob_no_bos")
            return
        idm = s["idm"]
        if idm is None:
            return
        swept = (float(b["low"]) < idm["price"]) if up else (float(b["high"]) > idm["price"])
        if not swept:
            return
        s["done"] = True
        s["idm_sweep_time"] = now
        box = self._find_choch_box(s["choch_time"], up)
        if box is None:
            self._bump("z_no_choch_box")
            return
        if box.status == "dead":
            self._bump("z_ob_box_dead")
            return
        if box.status != "fresh":
            self._bump("z_ob_box_used")
            return
        if box.created_time >= now:
            self._bump("z_ob_same_bar")
            return
        entry = float(box.high) if up else float(box.low)
        raw_stop = (
            float(box.low) - self.pip * config.OB_STOP_BUFFER_PIPS
            if up
            else float(box.high) + self.pip * config.OB_STOP_BUFFER_PIPS
        )
        min_risk = self.pip * float(config.MIN_STOP_PIPS)
        if abs(entry - raw_stop) < min_risk:
            stop = (entry - min_risk) if up else (entry + min_risk)
            self._bump("z_ob_min_risk_padded")
        else:
            stop = raw_stop
        self._z_place(s, sc, box, "ob", entry, stop, now, up)

    def _z_place(self, s, sc, box, kind, entry, stop, now, up):
        z = sc["zone"]
        risk = abs(entry - stop)
        t3r = (entry + 3.0 * risk) if up else (entry - 3.0 * risk)
        sw = self.ltf_struct.active_L if (not up) else self.ltf_struct.active_H
        liq = sorted(
            [float(x.price) for x in sw if (x.price > entry if up else x.price < entry)],
            reverse=(not up),
        )
        self.zorders.append({
            "id": f"ZO{len(self.zorders) + 1}",
            "leg": "zone",
            "pullback": self._pb["id"],
            "setup": s["id"],
            "variant": self.variant,
            "kind": kind,
            "side": "buy" if up else "sell",
            "placed_time": now,
            "end_time": None,
            "end_reason": None,
            "ceiling": sc["ceiling"],
            "ceiling_locked": sc["ceiling"] is not None,
            "entry": float(entry),
            "stop": float(stop),
            "target_3r": float(t3r),
            "liq": liq,
            "bos_time": self._pb["bos_time"],
            "zone_touch_time": sc["touch_time"],
            "zone_tf": z["tf"],
            "zone_low": z["low"],
            "zone_high": z["high"],
            "choch_time": s["choch_time"],
            "choch_level": s["choch_level"],
            "htf_bias": self.htf_bias,
            "box_low": float(box.low),
            "box_high": float(box.high),
            "box_time": box.created_time,
            "idm_level": float(s["idm"]["price"]) if s.get("idm") else None,
            "idm_sweep_time": s.get("idm_sweep_time"),
        })
        self._bump("z_orders_" + kind)

    # --- H1 With-Trend Continuation Zone stream ---
    def _new_h1_zones(self, want_dir, now):
        book = self.books["H1"]
        pool = book.bullish_obs if want_dir == "Bullish" else book.bearish_obs
        last_id = self._h1_last_seen_id[want_dir]
        out = []
        max_id = last_id
        atr = self.atrs["H1"].current_atr
        for b in reversed(pool):
            if b.id > max_id:
                max_id = b.id
            if b.id <= last_id:
                continue
            if b.status != "fresh":
                continue
            out.append({
                "tf": "H1",
                "id": b.id,
                "dir": want_dir,
                "low": float(b.low),
                "high": float(b.high),
                "created": b.created_time,
                "born_time": now,
                "atr": float(atr) if (atr is not None and not pd.isna(atr)) else 0.0,
                "h1_spent": False,
                "ceiling": None,
            })
        self._h1_last_seen_id[want_dir] = max_id
        return out

    def _h1_step(self, m15_bar, m15_events, h1_events, now):
        if self.htf_bias not in ("Bullish", "Bearish") or self.state == IDLE or self._pb is None:
            if self._h1_scan is not None:
                self._end_h1_scan(now, "bias_lost")
            self._h1_zones = []
            self._h1_bos = False
            return

        up = self.htf_bias == "Bullish"
        want = "Bullish" if up else "Bearish"
        against = "Bearish" if up else "Bullish"
        bh, bl = float(m15_bar["high"]), float(m15_bar["low"])

        # 1. Detect pro-trend H1 BOS to birth fresh H1 continuation zones
        for he in h1_events:
            if he.direction == want and he.origin == "BOS":
                self._bump("h1_bos_aligned")
                new_z = self._new_h1_zones(want, now)
                for z in new_z:
                    z["ceiling"] = bh if up else bl
                    self._h1_zones.append(z)
                    self._bump("h1_zones_born")

        # Update local impulse ceiling on active H1 zones prior to touch
        if self._h1_scan is None:
            for z in self._h1_zones:
                if z.get("h1_spent"):
                    continue
                if z["ceiling"] is None or (up and bh > z["ceiling"]) or ((not up) and bl < z["ceiling"]):
                    z["ceiling"] = bh if up else bl

        # 2. Track M15 counter-trend structure shift (CHoCH or BOS) & pro-trend CHoCH
        for e in m15_events:
            if e.direction == against:
                self._h1_bos = True
            elif e.direction == want and e.origin == "CHoCH":
                if self._h1_scan is not None:
                    if self._h1_bos:
                        self._h1_scan["setups"].append({
                            "id": len(self._h1_scan["setups"]) + 1,
                            "choch_time": now,
                            "choch_level": float(e.broken_level),
                            "bos_time": None,
                            "idm": None,
                            "idm_sweep_time": None,
                            "done": False,
                        })
                        self._bump("h1_setups")
                    else:
                        self._bump("h1_choch_no_bos")
                self._h1_bos = False

        # 3. Check for touch of an unspent, fresh (<= 48h) H1 continuation zone
        #    Precedence rule: skip if D1/H4 deep zone scan is already active
        if self._h1_scan is None and self._z_scan is None:
            for z in reversed(self._h1_zones):
                if z.get("h1_spent"):
                    continue
                if (now - z["born_time"]) > H1_ZONE_MAX_AGE:
                    z["h1_spent"] = True
                    self._bump("h1_zone_expired_48h")
                    continue
                if self._h1_zone_touched(m15_bar, z, up):
                    self._h1_scan = {
                        "zone": z,
                        "touch_time": now,
                        "ceiling": z["ceiling"] if z["ceiling"] is not None else self._pb["ceiling"],
                        "bos_time": z["born_time"],
                        "setups": [],
                    }
                    self._bump("h1_scan")
                    break

        if self._h1_scan is not None:
            self._h1_scan_step(m15_bar, m15_events, now, up, want)

    def _h1_zone_touched(self, b, z, up):
        bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])
        if up:
            if bc < z["low"]:
                z["h1_spent"] = True
                self._bump("h1_end_zone_far_break")
                return False
            return bl <= z["high"]
        else:
            if bc > z["high"]:
                z["h1_spent"] = True
                self._bump("h1_end_zone_far_break")
                return False
            return bh >= z["low"]

    def _h1_scan_step(self, b, m15_events, now, up, want):
        sc = self._h1_scan
        z = sc["zone"]
        bh, bl, bc = float(b["high"]), float(b["low"]), float(b["close"])

        # Cancel if H1 zone is invalidated by a close beyond its far edge
        if (up and bc < z["low"]) or ((not up) and bc > z["high"]):
            z["h1_spent"] = True
            self._bump("h1_scan_far_break")
            self._end_h1_scan(now, "zone_far_break")
            return

        # Cancel if scan exceeds 24 hours without filling an order
        if (now - sc["touch_time"]) > H1_SCAN_MAX_DURATION:
            z["h1_spent"] = True
            self._bump("h1_scan_expired_24h")
            self._end_h1_scan(now, "scan_expired_24h")
            return

        # Allow the M15 confirmation displacement leg to form up to 2.5x H1 ATR
        # beyond the H1 zone while tracking the new displacement extreme as ceiling
        c = sc["ceiling"]
        z_atr = float(z.get("atr") or 0.0)
        if up:
            runaway = max(float(c) if c is not None else bh, float(z["high"]) + H1_SCAN_RUNAWAY_ATR * z_atr)
            if z_atr > 0.0 and bh > runaway:
                self._bump("h1_scan_ceiling_break")
                self._end_h1_scan(now, "ceiling_break")
                return
            if c is None or bh > c:
                sc["ceiling"] = bh
        else:
            runaway = min(float(c) if c is not None else bl, float(z["low"]) - H1_SCAN_RUNAWAY_ATR * z_atr)
            if z_atr > 0.0 and bl < runaway:
                self._bump("h1_scan_ceiling_break")
                self._end_h1_scan(now, "ceiling_break")
                return
            if c is None or bl < c:
                sc["ceiling"] = bl

        # Strictly 1 trade per H1 zone: once touched/filled, mark H1 zone spent
        for o in self.zorders:
            if o["end_time"] is None and o.get("zone_tf") == "H1":
                if (o["side"] == "buy" and bl <= o["entry"]) or (
                    o["side"] == "sell" and bh >= o["entry"]
                ):
                    z["h1_spent"] = True
                    self._bump("h1_zone_spent")
                    for o2 in self.zorders:
                        if o2 is not o and o2["end_time"] is None and o2.get("zone_tf") == "H1":
                            o2["end_time"] = now
                            o2["end_reason"] = "zone_spent"
                    self._h1_scan = None
                    return

        for e in m15_events:
            if e.direction == want and e.origin == "BOS":
                for s in sc["setups"]:
                    if s["bos_time"] is None and not s["done"]:
                        s["bos_time"] = now
                        s["idm"] = self._find_idm(s["choch_time"], now, not up)
                        if s["idm"] is not None:
                            self._bump("h1_idm_set")
                        else:
                            self._bump("h1_ob_no_idm")
                            s["done"] = True

        for s in sc["setups"]:
            if not s["done"]:
                self._h1_try_setup(s, sc, b, now, up)

    def _h1_opposing_htf_zone_too_close(self, entry, risk, up):
        min_dist = H1_OPPOSING_HTF_MIN_R * risk
        for tf in ("H4", "D1"):
            book = self.books[tf]
            opposing_pool = book.bearish_obs if up else book.bullish_obs
            for ob in opposing_pool:
                if ob.status == "dead":
                    continue
                if up:
                    if float(ob.low) > entry and (float(ob.low) - entry) < min_dist:
                        return True
                else:
                    if float(ob.high) < entry and (entry - float(ob.high)) < min_dist:
                        return True
        return False

    def _h1_try_setup(self, s, sc, b, now, up):
        if s["bos_time"] is None:
            self._bump("h1_ob_no_bos")
            return
        idm = s["idm"]
        if idm is None:
            return
        swept = (float(b["low"]) < idm["price"]) if up else (float(b["high"]) > idm["price"])
        if not swept:
            return
        s["done"] = True
        s["idm_sweep_time"] = now
        box = self._find_choch_box(s["choch_time"], up)
        if box is None:
            self._bump("h1_no_choch_box")
            return
        if box.status == "dead":
            self._bump("h1_ob_box_dead")
            return
        if box.status != "fresh":
            self._bump("h1_ob_box_used")
            return
        if box.created_time >= now:
            self._bump("h1_ob_same_bar")
            return

        # Skip Asian session (00:00 - 05:59 UTC) for H1 continuation orders
        if now.hour < 6:
            self._bump("h1_asian_skipped")
            return

        # Filter M15 OB box width and inducement separation against M15 ATR
        atr = self.atrs["ltf"].current_atr
        if atr is not None and not pd.isna(atr) and float(atr) > 0.0:
            box_width = float(box.high) - float(box.low)
            if box_width < 0.25 * float(atr) or box_width > 1.75 * float(atr):
                self._bump("h1_ob_box_size_filtered")
                return
            entry_check = float(box.high) if up else float(box.low)
            idm_dist = (float(idm["price"]) - entry_check) if up else (entry_check - float(idm["price"]))
            if idm_dist < 0.50 * float(atr):
                self._bump("h1_ob_idm_too_close")
                return

        entry = float(box.high) if up else float(box.low)
        raw_stop = (
            float(box.low) - self.pip * config.OB_STOP_BUFFER_PIPS
            if up
            else float(box.high) + self.pip * config.OB_STOP_BUFFER_PIPS
        )
        min_risk = self.pip * float(config.MIN_STOP_PIPS)
        if abs(entry - raw_stop) < min_risk:
            stop = (entry - min_risk) if up else (entry + min_risk)
            self._bump("h1_ob_min_risk_padded")
        else:
            stop = raw_stop

        risk = abs(entry - stop)
        if self._h1_opposing_htf_zone_too_close(entry, risk, up):
            self._bump("h1_blocked_opposing_htf_zone")
            return

        # Avoid duplicating an active D1/H4 zone order at the same M15 OB box
        for o in self.zorders:
            if o["end_time"] is None and o.get("box_time") == box.created_time:
                self._bump("h1_duplicate_with_htf_zone_skipped")
                return

        self._h1_place(s, sc, box, "ob", entry, stop, now, up)

    def _h1_place(self, s, sc, box, kind, entry, stop, now, up):
        z = sc["zone"]
        risk = abs(entry - stop)
        t3r = (entry + 3.0 * risk) if up else (entry - 3.0 * risk)
        sw = self.ltf_struct.active_L if (not up) else self.ltf_struct.active_H
        liq = sorted(
            [float(x.price) for x in sw if (x.price > entry if up else x.price < entry)],
            reverse=(not up),
        )
        self.zorders.append({
            "id": f"ZO{len(self.zorders) + 1}",
            "leg": "zone",
            "pullback": self._pb["id"] if self._pb is not None else 0,
            "setup": s["id"],
            "variant": self.variant,
            "kind": kind,
            "side": "buy" if up else "sell",
            "placed_time": now,
            "end_time": None,
            "end_reason": None,
            "ceiling": sc["ceiling"],
            "ceiling_locked": sc["ceiling"] is not None,
            "entry": float(entry),
            "stop": float(stop),
            "target_3r": float(t3r),
            "liq": liq,
            "bos_time": sc["bos_time"],
            "zone_touch_time": sc["touch_time"],
            "zone_tf": "H1",
            "zone_low": z["low"],
            "zone_high": z["high"],
            "choch_time": s["choch_time"],
            "choch_level": s["choch_level"],
            "htf_bias": self.htf_bias,
            "box_low": float(box.low),
            "box_high": float(box.high),
            "box_time": box.created_time,
            "idm_level": float(s["idm"]["price"]) if s.get("idm") else None,
            "idm_sweep_time": s.get("idm_sweep_time"),
        })
        self._bump("h1_orders_" + kind)

    def finish(self, cutoff):
        super().finish(cutoff)
        for o in self.zorders:
            if o["end_time"] is None:
                o["end_time"] = cutoff
                o["end_reason"] = "cutoff"
