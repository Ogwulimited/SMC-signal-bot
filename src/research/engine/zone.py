"""Phase 4 zone trades (with the trend), built on top of the cycle engine.

Zone BUY (bull bias); zone SELL is the exact mirror. Runs inside the cycle's
flow, cycle.py holds the state machine:
  HTF BOS arms -> trading-TF CHoCH down starts the pullback -> a wick touches a
  remembered HTF buy zone (the cycle's own touch) -> scan.
The trading timeframe (self.ltf) is M15 or H1 (config.LTF_TF). Touches and
fills of zone orders are always tracked on M15 bars, like simulate_orders.py.
Zone rules (his teaching):
  * A BOS down must exist before the CHoCH up (before the zone, on the
    touch, or inside the zone). The leg down must have touched the zone.
  * A body close above the BOS-down leg's high is the CHoCH up (structure.py).
  * Breaker buy: the CHoCH's "the" breaker (sell box of the last BOS down),
    limit at its near edge once it died. Stop = far edge - 0.2 x ATR.
  * OB buy: the CHoCH's own box. A BOS up after the CHoCH gives the inducement
    (its last_opposite_price); a wick clears it; limit at the box near edge.
  * Scan ends: body close beyond the ceiling, or through the zone's far edge,
    or bias lost. Pending orders are cancelled; filled trades keep running.
  * Each zone order is played twice by the simulator: static 1:3 and liquidity.

RULES SWITCH (SETTINGS["rules"], used by variants mz and mh; off otherwise):
  * Used-zone rule B: the first time a trade is TAKEN (order filled, same tests
    as simulate_orders.py: touch, next open, not beyond stop, spread ok) from a
    zone, that zone is spent and never used again. A zone touched but never
    taken (order cancelled, skipped, or no setup) is NOT spent.
  * Cancel rule: a pending zone order whose entry has not been touched is
    cancelled (end_reason "ran_away") when a wick runs ZONE_CANCEL_PIPS beyond
    the entry in the trade direction. Needs SETTINGS["pip"] (0.0001 / 0.01 JPY).
  * SETTINGS["spread"] = config.SPREAD_PRICE[pair] (price units).
  * Tracking timing: each M15 bar is handled when the NEXT M15 bar arrives, so
    every end/cancel set by trading-timeframe bars up to its close is already
    known. Window rule = the simulator's: a bar counts if its close is before
    the order's end (on it too, for a ceiling_break end).
"""
from bisect import bisect_left, bisect_right, insort
from collections import deque

from src import config
from src.research.engine import cycle as cy
from src.research.engine.bias import htf_bias

SETTINGS = {"enabled": False, "rules": False, "pip": 0.0001, "spread": 0.0}
LIQ_CAP = 100


def _on():
    return bool(SETTINGS["enabled"])


def _rules():
    return bool(SETTINGS["enabled"]) and bool(SETTINGS.get("rules", False))


class ZoneRecorder(cy.CycleRecorder):
    def __init__(self, log, first_read=None):
        super().__init__(log, first_read)
        self.zorders = []
        self._n_z = 0
        self._n_zo = 0
        self._ev = None
        self._zpb_id = None
        self._zlocked = False
        self._zbos = False
        self._zbos_time = None
        n = int(config.LTF_SWING_N)
        self._swin = deque(maxlen=2 * n + 1)
        self._sw_hi = []   # unswept swing highs (trading TF), ascending
        self._sw_lo = []   # unswept swing lows (trading TF), ascending
        self._spent = set()   # zone ids spent by a real fill (rules on)
        self._watch = []      # zone orders tracked for touch / fill (rules on)
        self._prev15 = None   # last M15 bar, handled when the next one arrives
        if _rules():
            if not (float(SETTINGS.get("pip", 0.0)) > 0.0
                    and float(SETTINGS.get("spread", 0.0)) > 0.0):
                raise ValueError("zone rules on: set SETTINGS pip and spread first")

    # ---- feed hooks ----------------------------------------------------
    def on_bar_close(self, bar, feed):
        if _on():
            if bar.tf == self.ltf:
                self._swings(bar)
            if _rules() and bar.tf == "M15":
                if self._prev15 is not None:
                    self._watch_orders(self._prev15, bar)
                self._resolve_fills(bar)
                self._prev15 = bar
        super().on_bar_close(bar, feed)

    def _swings(self, bar):
        h = float(bar.high)
        l = float(bar.low)
        if self._sw_hi:
            k = bisect_left(self._sw_hi, h)       # highs below this bar's high are swept
            if k:
                del self._sw_hi[:k]
        if self._sw_lo:
            k = bisect_right(self._sw_lo, l)      # lows above this bar's low are swept
            if k < len(self._sw_lo):
                del self._sw_lo[k:]
        self._swin.append((h, l))
        n = int(config.LTF_SWING_N)
        if len(self._swin) == 2 * n + 1:
            highs = [x[0] for x in self._swin]
            lows = [x[1] for x in self._swin]
            ch, cl = highs[n], lows[n]
            if ch == max(highs) and ch > max(highs[:n]) and ch > max(highs[n + 1:]):
                insort(self._sw_hi, ch)
            if cl == min(lows) and cl < min(lows[:n]) and cl < min(lows[n + 1:]):
                insort(self._sw_lo, cl)

    # ---- rules: fill tracking, cancel, spent zones ---------------------
    def _cancel_dist(self):
        if bool(getattr(config, "MAJOR_HTF", False)):
            return 0.0
        return float(config.ZONE_CANCEL_PIPS) * float(SETTINGS["pip"])

    def _zone_warn(self, z):
        if not _rules() or z is None:
            return False
        d1_w = bool(self.bias["D1"].warning)
        h4_w = bool(self.bias["H4"].warning)
        return d1_w if z["tf"] == "D1" else (d1_w or h4_w)

    def _resolve_fills(self, bar):
        """Orders touched on the previous M15 bar fill at THIS bar's open
        (same tests as the simulator). Called after _watch_orders(previous)."""
        if not self._watch:
            return
        keep = []
        now = bar.close_time
        for w in self._watch:
            if w["st"] != "touched":
                keep.append(w)
                continue
            o = w["o"]
            sell = o["side"] == "sell"
            fill = float(bar.open)
            stop = float(o["stop"])
            if (sell and fill >= stop) or ((not sell) and fill <= stop):
                self.counts["z_fill_beyond_stop"] += 1
                continue
            risk = abs(fill - stop)
            if float(SETTINGS["spread"]) / risk > float(config.MAX_SPREAD_RISK_RATIO):
                self.counts["z_fill_skipped_spread"] += 1
                continue
            zid = o["zone_id"]
            if zid not in self._spent:
                self._spent.add(zid)
                self.counts["z_zone_spent"] += 1
                self._log("z_spent", now, zone=zid, order=o["id"])
        self._watch = keep

    def _watch_orders(self, p, arrival):
        """Handle M15 bar p (called when the next M15 bar 'arrival' comes):
        window check, 150-pip cancel, touch."""
        if not self._watch:
            return
        pclose = p.close_time
        cancel = self._cancel_dist()
        keep = []
        for w in self._watch:
            if w["st"] != "pending":
                keep.append(w)
                continue
            o = w["o"]
            if pclose <= o["placed_time"]:
                keep.append(w)          # bars up to the placing close never count
                continue
            end = o["end_time"]
            if end is not None:
                if o["end_reason"] == "ceiling_break":
                    live = pclose <= end
                else:
                    live = pclose < end
                if not live:
                    continue
            sell = o["side"] == "sell"
            entry = float(o["entry"])
            if (end is None or end > pclose) and cancel > 0.0:
                if sell:
                    ran = float(p.low) <= entry - cancel
                else:
                    ran = float(p.high) >= entry + cancel
                if ran:
                    o["end_time"] = pclose
                    o["end_reason"] = "ran_away"
                    self.counts["z_ran_away"] += 1
                    self._log("z_ran_away", arrival.close_time,
                              order=o["id"], zone=o["zone_id"])
                    continue
            touched = float(p.high) >= entry if sell else float(p.low) <= entry
            if touched:
                w["st"] = "touched"
                keep.append(w)
            elif end is None or pclose < end:
                keep.append(w)
        self._watch = keep

    def _freeze_zones(self):
        if not _rules():
            return super()._freeze_zones()
        buy_zone = self.ctx["zone_side"] == "buy"
        out = []
        for tf in ("D1", "H4"):
            for p in self.books[tf].usable(self.ctx["zone_side"], include_used=True):
                if p.id in self._spent:
                    self.counts["z_spent_skipped"] += 1
                    continue
                out.append(self._refine(p, buy_zone))
        return out

    def _zone_alive(self, z):
        if not _rules():
            return super()._zone_alive(z)
        return z["poi"].state in ("fresh", "used") and z["id"] not in self._spent

    def _on_m15(self, bar, ev):
        self._ev = ev
        super()._on_m15(bar, ev)

    # ---- cycle hooks (all pass straight through when zone trades are off) --
    def _start_pullback(self, bar, ev, now):
        self._zbos = False
        self._zbos_time = None
        super()._start_pullback(bar, ev, now)

    def _pull_step(self, bar, ev, now):
        if _on() and self._pb is not None:
            self._zpb_id = self._pb["id"]
            self._zlocked = bool(self._pb["locked"])
        super()._pull_step(bar, ev, now)

    def _on_bos(self, ev, now):
        if _on():
            self._mark_bos(ev, now)
        super()._on_bos(ev, now)

    def _on_choch_other(self, now):
        if _on() and self._zbos and not _rules():
            self.counts["z_bos_cleared_by_choch"] += 1
            self._zbos = False
            self._zbos_time = None
        super()._on_choch_other(now)

    def _check_bias(self, now):
        if _on() and self.state == cy.SCAN and self._scan is not None:
            if htf_bias(self.bias["D1"], self.bias["H4"]) != self.ctx["bias"]:
                if self._scan.get("zone") is not None and "zorders" in self._scan:
                    self._zend(self._scan, now, "bias_lost")
            elif self._scan.get("zone") is not None and "zorders" in self._scan:
                if self._zone_warn(self._scan["zone"]):
                    if not self._scan.get("warned"):
                        self._scan["warned"] = True
                        self._zend(self._scan, now, "bias_warning")
                else:
                    self._scan["warned"] = False
        super()._check_bias(now)

    def _mark_bos(self, ev, now):
        self._zbos = True
        self._zbos_time = ev["time"]
        self.counts["z_bos_seen"] += 1
        self._log("z_bos", now, direction=ev["direction"])

    def _init_zscan(self, sc, now):
        sc["zorders"] = []
        sc["zsetups"] = []
        sc["pb_id"] = self._zpb_id
        sc["locked"] = bool(sc.get("locked", self._zlocked))
        sc["touch_time"] = now
        sc["warned"] = False
        self.counts["z_scan"] += 1
        z = sc["zone"]
        self._log("z_touch", now, pb=sc["pb_id"], zone=z["id"], zone_tf=z["tf"],
                  zone_low=float(z["low"]), zone_high=float(z["high"]),
                  ceiling=float(sc["ceiling"]), bos_seen=bool(self._zbos))

    # ---- the scan = zone trading --------------------------------------
    def _scan_step(self, bar, now):
        if not _on():
            return super()._scan_step(bar, now)
        sc = self._scan
        if sc.get("zone") is None:
            if (self._ev is not None and self._ev["label"] == "BOS"
                    and self._ev["direction"] == self.ctx["choch_dir"]):
                self._mark_bos(self._ev, now)
            super()._scan_step(bar, now)
            if self._scan is None or self._scan.get("zone") is None:
                return
            sc = self._scan
            self._init_zscan(sc, now)
            if self._zone_warn(sc["zone"]):
                sc["warned"] = True
            self._z_event(sc, bar, now)
            return

        if "zorders" not in sc:
            self._init_zscan(sc, now)
            if self._zone_warn(sc["zone"]):
                sc["warned"] = True
        super()._scan_step(bar, now)
        if self._scan is not sc:
            why = "ceiling_break" if self.state == cy.ARMED else "zone_far_break"
            self._zend(sc, now, why)
            if self._scan is None or self._scan.get("zone") is None:
                if (self._scan is not None and self._ev is not None
                        and self._ev["label"] == "BOS"
                        and self._ev["direction"] == self.ctx["choch_dir"]):
                    self._mark_bos(self._ev, now)
                return
            sc = self._scan
            self._init_zscan(sc, now)
            if self._zone_warn(sc["zone"]):
                sc["warned"] = True
            self._z_event(sc, bar, now)
            return
        for s in sc["zsetups"]:
            if s["br"] == "wait":
                self._z_try_breaker(s, sc, bar, now)
            if s["ob"] == "wait_sweep":
                self._z_try_ob(s, sc, bar, now)
        self._z_event(sc, bar, now)

    def _z_event(self, sc, bar, now):
        ev = self._ev
        if ev is None:
            return
        lab = ev["label"]
        d = ev["direction"]
        c = self.ctx
        if lab == "BOS" and d == c["choch_dir"]:
            self._mark_bos(ev, now)
        elif lab == "CHoCH" and d == c["other_dir"]:
            if self._zbos:
                self._z_new_choch(sc, bar, ev, now)
            else:
                self.counts["z_choch_no_bos"] += 1
            self._zbos = False
            self._zbos_time = None
        elif lab == "BOS" and d == c["other_dir"]:
            for s in sc["zsetups"]:
                if s["ob"] == "wait_bos" and s["choch_time"] < ev["time"]:
                    p = cy._num(ev["last_opposite_price"])
                    if p is None:
                        s["ob"] = "none"
                        self.counts["z_ob_no_idm"] += 1
                    else:
                        s["idm"] = p
                        s["ob"] = "wait_sweep"
                        self.counts["z_idm_set"] += 1
        elif lab == "CHoCH" and d == c["choch_dir"]:
            for s in sc["zsetups"]:
                if s["ob"] == "wait_bos":
                    s["ob"] = "none"
                    self.counts["z_ob_no_bos"] += 1

    def _z_new_choch(self, sc, bar, ev, now):
        if self._zone_warn(sc.get("zone")):
            self.counts["z_skip_bias_warning"] += 1
            return
        self._n_z += 1
        box = self._choch_poi(ev)
        breaker = self.books[self.ltf].choch_breaker.get(ev["time"])
        s = {"id": f"{sc['pb_id']}-Z{self._n_z}", "choch_time": ev["time"],
             "choch_level": cy._num(ev["broken_swing_price"]), "box": box,
             "breaker": breaker, "br": "none", "ob": "none", "idm": None,
             "bos_time": self._zbos_time}
        sc["zsetups"].append(s)
        self.counts["z_setups"] += 1
        self._log("z_setup", now, setup=s["id"], choch_level=float(s["choch_level"] or 0.0))
        skip_m15_br_buy = _rules() and self.ltf == "M15" and self.ctx["up"]
        if breaker is None:
            self.counts["z_no_breaker"] += 1
        elif skip_m15_br_buy:
            self.counts["z_breaker_buy_skipped"] += 1
        else:
            s["br"] = "wait"
            self._z_try_breaker(s, sc, bar, now)
        if box is None:
            self.counts["z_no_choch_box"] += 1
        else:
            s["ob"] = "wait_bos"

    def _z_try_breaker(self, s, sc, bar, now):
        p = s["breaker"]
        if p.state != "dead":
            return
        s["br"] = "none"
        self._zplace(s, sc, "breaker", p, bar, now)

    def _z_try_ob(self, s, sc, bar, now):
        tsell = not self.ctx["up"]
        box = s["box"]
        if box.state == "dead":
            s["ob"] = "none"
            self.counts["z_ob_box_dead"] += 1
            return
        idm = s["idm"]
        swept = bar.high > idm if tsell else bar.low < idm
        if not swept:
            return
        s["ob"] = "none"
        allow_used = bool(config.TRADE_USED_POIS) or _rules()
        if box.state != "fresh" and not allow_used:
            self.counts["z_ob_box_used"] += 1
            return
        near = box.low if tsell else box.high
        touched = bar.high >= near if tsell else bar.low <= near
        if touched:
            self.counts["z_ob_same_bar"] += 1
            return
        self._zplace(s, sc, "ob", box, bar, now)

    def _liq(self, entry, ceiling, tsell):
        if tsell:
            lo = self._sw_lo
            a = bisect_left(lo, ceiling)
            b = bisect_left(lo, entry)
            return [float(x) for x in reversed(lo[a:b])][:LIQ_CAP]
        hi = self._sw_hi
        a = bisect_right(hi, entry)
        b = bisect_right(hi, ceiling)
        return [float(x) for x in hi[a:b]][:LIQ_CAP]

    def _zplace(self, s, sc, kind, p, bar, now):
        if self._zone_warn(sc.get("zone")):
            self.counts["z_skip_bias_warning"] += 1
            return None
        tsell = not self.ctx["up"]   # True = the zone trade is a SELL
        atr = self.atr.value_at(p.candle_time)
        if atr is None:
            self.counts["z_" + kind + "_no_atr"] += 1
            return None
        entry = p.low if tsell else p.high
        edge = p.high if tsell else p.low
        ahead = bar.close < entry if tsell else bar.close > entry
        if not ahead:
            self.counts["z_" + kind + "_entry_not_ahead"] += 1
            return None
        buf = float(config.STOP_BUFFER_ATR) * float(atr)
        stop = edge + buf if tsell else edge - buf
        ceiling = float(sc["ceiling"])
        z = sc["zone"]
        self._n_zo += 1
        order = {"id": f"ZO{self._n_zo}", "pullback": sc["pb_id"], "setup": s["id"],
                 "variant": "plain", "kind": kind, "leg": "zone",
                 "side": "sell" if tsell else "buy",
                 "placed_time": now, "entry": float(entry), "stop": float(stop),
                 "stop_edge": float(edge), "box_low": float(p.low),
                 "box_high": float(p.high), "atr": float(atr),
                 "ceiling": ceiling, "ceiling_locked": bool(sc["locked"]),
                 "end_time": None, "end_reason": None,
                 "liq": self._liq(entry, ceiling, tsell),
                 "bos_time": s["bos_time"], "zone_touch_time": sc["touch_time"],
                 "zone_tf": z["tf"], "zone_low": float(z["low"]),
                 "zone_high": float(z["high"]), "choch_time": s["choch_time"],
                 "choch_level": s["choch_level"], "zone_id": z["id"]}
        sc["zorders"].append(order)
        self.zorders.append(order)
        if _rules():
            self._watch.append({"o": order, "st": "pending"})
        self.counts["z_orders_" + kind] += 1
        self._log("z_order", now, id=order["id"], order_kind=kind, side=order["side"],
                  entry=order["entry"], stop=order["stop"], setup=s["id"],
                  liq_n=len(order["liq"]))
        return order

    def _zend(self, sc, now, reason):
        n = 0
        for o in sc.get("zorders", []):
            if o["end_time"] is None:
                o["end_time"] = now
                o["end_reason"] = reason
                n += 1
        self.counts["z_end_" + reason] += 1
        self._log("z_end", now, reason=reason, cancelled=n)
