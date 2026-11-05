"""Phase 4 zone trades (with the trend), built on top of the cycle engine.

Zone BUY (bull bias); zone SELL is the exact mirror. Runs inside the cycle's
flow, cycle.py is NOT changed:
  HTF BOS arms -> M15 CHoCH down starts the pullback -> a wick touches a
  remembered HTF buy zone (the cycle's own touch) -> scan.
Zone rules (his teaching):
  * An M15 BOS down must exist before the CHoCH up (before the zone, on the
    touch, or inside the zone). The leg down must have touched the zone.
  * A body close above the BOS-down leg's high is the CHoCH up (structure.py).
  * Breaker buy: the CHoCH's "the" breaker (sell box of the last BOS down),
    limit at its near edge once it died. Stop = far edge - 0.2 x ATR.
  * OB buy: the CHoCH's own box. A BOS up after the CHoCH gives the inducement
    (its last_opposite_price); a wick clears it; limit at the box near edge.
  * Scan ends: body close beyond the ceiling, or through the zone's far edge,
    or bias lost. Pending orders are cancelled; filled trades keep running.
  * Each zone order is played twice by the simulator: static 1:3 and liquidity.

ASSUMPTIONS (not confirmed yet):
  Z1 touch = any wick reaching the zone near edge (cycle's own test).
  Z2 only fresh zones; the zone list is frozen at pullback start.
  Z3 CHoCH = the M15 structure's own CHoCH; level shown on the trade sheet.
  Z4 touch bar and CHoCH-close on the same bar is valid.
  Z5 a CHoCH with the trend before the touch clears the BOS memory.
  Z7 more attempts in the same scan are allowed.
  Z8 no CHoCH-down gate (a BOS down already implies an earlier CHoCH down).
  Z9 zone trades only inside the cycle flow above.
  Z10 BOS memory = a BOS against the trend since the last CHoCH with the trend.
  T1 liquidity = unswept M15 swing (N=LTF_SWING_N) between entry and ceiling,
     known at its confirm bar. T2 none >= 3R away: target = the ceiling.
"""
from bisect import bisect_left, bisect_right, insort
from collections import deque

from src import config
from src.research.engine import cycle as cy
from src.research.engine.bias import htf_bias

SETTINGS = {"enabled": False}
LIQ_CAP = 100


def _on():
    return bool(SETTINGS["enabled"])


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
        self._sw_hi = []   # unswept M15 swing highs, ascending
        self._sw_lo = []   # unswept M15 swing lows, ascending

    # ---- feed hooks ----------------------------------------------------
    def on_bar_close(self, bar, feed):
        if _on() and bar.tf == "M15":
            self._swings(bar)
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
        breaker = self.books["M15"].choch_breaker.get(ev["time"])
        s = {"id": f"{sc['pb_id']}-Z{self._n_z}", "choch_time": ev["time"],
             "choch_level": cy._num(ev["broken_swing_price"]), "box": box,
             "breaker": breaker, "br": "none", "ob": "none", "idm": None,
             "bos_time": self._zbos_time}
        sc["zsetups"].append(s)
        self.counts["z_setups"] += 1
        self._log("z_setup", now, setup=s["id"], choch_level=float(s["choch_level"] or 0.0))
        if breaker is None:
            self.counts["z_no_breaker"] += 1
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
                 "choch_level": s["choch_level"]}
        sc["zorders"].append(order)
        self.zorders.append(order)
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
