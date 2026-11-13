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

ASSUMPTIONS (not confirmed yet):
  Z1 touch = any wick reaching the zone near edge (cycle's own test).
  Z2 only fresh zones; the zone list is frozen at pullback start.
     (rules on: fresh or used, never dead, and never spent.)
  Z3 CHoCH = the trading-TF structure's own CHoCH; level shown on the trade sheet.
  Z4 touch bar and CHoCH-close on the same bar is valid.
  Z5 a CHoCH with the trend before the touch clears the BOS memory.
  Z7 more attempts in the same scan are allowed.
  Z8 no CHoCH-down gate (a BOS down already implies an earlier CHoCH down).
  Z9 zone trades only inside the cycle flow above.
  Z10 BOS memory = a BOS against the trend since the last CHoCH with the trend.
  Z11 rules on: "used" in poi.py means wick-touched only. (poi.py now read: a
      POI becomes "used" on a BODY close inside the box, not a wick.)
  Z12 spent zones are keyed by the zone id (a refined D1 zone keeps its D1 id).
  Z13 other pending orders from a zone keep running after it is spent.
  Z14 a bar that touches the entry and also runs the cancel distance = cancelled.
  T1 liquidity = unswept swing (N=LTF_SWING_N, trading timeframe) between entry
     and ceiling, known at its confirm bar. T2 none >= 3R away: target = ceiling.
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
        return float(config.ZONE_CANCEL_PIPS) * float(SETTINGS["pip"])

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

    def _zone_touched(self, bar):
        if not _rules():
            return super()._zone_touched(bar)
        up = self.ctx["up"]
        best = None
        for z in self._pb["zones"]:
            if z["poi"].state not in ("fresh", "used") or z["id"] in self._spent:
                continue
            if up:
                hit = bar.low <= z["high"]
                near = z["high"]
            else:
                hit = bar.high >= z["low"]
                near = z["low"]
            if hit and (best is None or (near > best[0] if up else near < best[0])):
                best = (near, z)
        return best[1] if best is not None else None

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
        if _on() and self._zbos:
            self.counts["z_bos_cleared_by_choch"] += 1
            self._zbos = False
            self._zbos_time = None
        super()._on_choch_other(now)

    def _check_bias(self, now):
        if (_on() and self.state == cy.SCAN and self._scan is not None
                and htf_bias(self.bias["D1"], self.bias["H4"]) != self.ctx["bias"]):
            self._zend(self._scan, now, "bias_lost")
        super()._check_bias(now)

    def _mark_bos(self, ev, now):
        self._zbos = True
        self._zbos_time = ev["time"]
        self.counts["z_bos_seen"] += 1
        self._log("z_bos", now, direction=ev["direction"])

    # ---- the scan = zone trading --------------------------------------
    def _scan_step(self, bar, now):
        if not _on():
            return super()._scan_step(bar, now)
        sc = self._scan
        if "zorders" not in sc:
            sc["zorders"] = []
            sc["zsetups"] = []
            sc["pb_id"] = self._zpb_id
            sc["locked"] = self._zlocked
            sc["touch_time"] = now
            self.counts["z_scan"] += 1
            z = sc["zone"]
            self._log("z_touch", now, pb=sc["pb_id"], zone=z["id"], zone_tf=z["tf"],
                      zone_low=float(z["low"]), zone_high=float(z["high"]),
                      ceiling=float(sc["ceiling"]), bos_seen=bool(self._zbos))
        super()._scan_step(bar, now)
        if self._scan is None:
            why = "ceiling_break" if self.state == cy.ARMED else "zone_far_break"
            self._zend(sc, now, why)
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
        if box.state != "fresh" and not bool(config.TRADE_USED_POIS):
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
