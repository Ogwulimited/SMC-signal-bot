from bisect import bisect_left, bisect_right, insort
from collections import deque
import pandas as pd
from src import config
from src.research.engine import cycle as cy
from src.research.engine.bias import htf_bias
SETTINGS = {"enabled": False, "rules": False, "pip": 0.0001, "spread": 0.0}
LIQ_CAP = 100
H1_OPPOSING_HTF_MIN_R = 1.5
H1_ZONE_MAX_AGE = pd.Timedelta(hours=96)
H1_SCAN_MAX_DURATION = pd.Timedelta(hours=48)
H1_ORDER_EXPIRY = pd.Timedelta(hours=48)
def _on():
    return bool(SETTINGS["enabled"])
def _rules():
    return bool(SETTINGS["enabled"]) and bool(SETTINGS.get("rules", False))
class ZoneRecorder(cy.CycleRecorder):
    def __init__(self, log, first_read=None):
        super().__init__(log, first_read)
        self._spread = float(SETTINGS.get("spread", 0.0))
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
        self._sw_hi = []
        self._sw_lo = []
        self._spent = set()
        self._watch = []
        self._prev15 = None
        # --- 1H Continuation Zone stream state ---
        self._h1_q = []
        self._h1_zones = []
        self._h1_scan = None
        self._h1_bos = False
        self._h1_bos_time = None
        self._h1_bias = None
        self._n_h1_scan = 0
        if _rules():
            if not (float(SETTINGS.get("pip", 0.0)) > 0.0
                    and float(SETTINGS.get("spread", 0.0)) > 0.0):
                raise ValueError("zone rules on: set SETTINGS pip and spread first")
    def on_bar_close(self, bar, feed):
        if _on():
            if bar.tf == self.ltf:
                self._swings(bar)
            if _rules() and bar.tf == "M15":
                if self._prev15 is not None:
                    self._watch_orders(self._prev15, bar)
                self._resolve_fills(bar)
                self._prev15 = bar
        n0 = len(self.events)
        super().on_bar_close(bar, feed)
        if _on() and _rules() and bar.tf == "H1":
            new_h1 = self.events[n0:]
            if new_h1:
                self._h1_q.extend(new_h1)
    def _swings(self, bar):
        h = float(bar.high)
        l = float(bar.low)
        if self._sw_hi:
            k = bisect_left(self._sw_hi, h)
            if k:
                del self._sw_hi[:k]
        if self._sw_lo:
            k = bisect_right(self._sw_lo, l)
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
    def _cancel_dist(self):
        return float(config.ZONE_CANCEL_PIPS) * float(SETTINGS["pip"])
    def _resolve_fills(self, bar):
        if not self._watch:
            return
        keep = []
        now = bar.close_time
        spent_now = set()
        spent_sell_now = set()
        for w in self._watch:
            o = w["o"]
            zid = o["zone_id"]
            sell = o["side"] == "sell"
            is_h1 = (o.get("zone_tf") == "H1")
            if (sell and (zid in self._spent or zid in spent_sell_now)) or (
                is_h1 and (zid in self._spent or zid in spent_now)
            ):
                if o["end_time"] is None:
                    o["end_time"] = now
                    o["end_reason"] = "zone_spent"
                continue
            if w["st"] != "touched":
                keep.append(w)
                continue
            fill = float(bar.open)
            stop = float(o["stop"])
            if (sell and fill >= stop) or ((not sell) and fill <= stop):
                self.counts["z_fill_beyond_stop"] += 1
                continue
            risk = abs(fill - stop)
            if float(SETTINGS["spread"]) / risk > float(config.MAX_SPREAD_RISK_RATIO):
                self.counts["z_fill_skipped_spread"] += 1
                continue
            if zid not in self._spent:
                self._spent.add(zid)
                self.counts["z_zone_spent"] += 1
                if is_h1:
                    self.counts["h1_zone_spent"] += 1
                self._log("z_spent", now, zone=zid, order=o["id"])
            spent_now.add(zid)
            if sell:
                spent_sell_now.add(zid)
        if spent_now:
            still = []
            for w in keep:
                o = w["o"]
                zid = o["zone_id"]
                is_h1 = (o.get("zone_tf") == "H1")
                if (o["side"] == "sell" and zid in spent_sell_now) or (is_h1 and zid in spent_now):
                    if o["end_time"] is None:
                        o["end_time"] = now
                        o["end_reason"] = "zone_spent"
                    continue
                still.append(w)
            keep = still
            if (self.state == cy.SCAN and self._scan is not None
                    and self._scan["zone"]["id"] in spent_sell_now):
                sc = self._scan
                for s in sc.get("zsetups", []):
                    s["br"] = "none"
                    s["ob"] = "none"
                self._zend(sc, now, "zone_spent")
            if self._h1_scan is not None and self._h1_scan["zone"]["id"] in spent_now:
                hsc = self._h1_scan
                for s in hsc.get("zsetups", []):
                    s["br"] = "none"
                    s["ob"] = "none"
                self._h1_end(hsc, now, "zone_spent")
                self._h1_scan = None
        self._watch = keep
    def _watch_orders(self, p, arrival):
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
                keep.append(w)
                continue
            if (o.get("zone_tf") == "H1" and o["end_time"] is None
                    and pclose - o["placed_time"] >= H1_ORDER_EXPIRY):
                o["end_time"] = pclose
                o["end_reason"] = "h1_expired_24h"
                self.counts["h1_orders_expired_24h"] += 1
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
        if _on() and _rules() and self.ltf == "M15":
            self._h1_step(bar, ev, bar.close_time)
    def _start_pullback(self, bar, ev, now):
        unlock_sell = _rules() and (not self.ctx["up"])
        self._zbos = unlock_sell
        self._zbos_time = ev["time"] if unlock_sell else None
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
        if _on() and self._zbos and (not _rules() or self.ctx["up"]):
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
        if _rules() and (not self.ctx["up"]) and sc["zone"]["id"] in self._spent:
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
            if not c["up"]:
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
            if _rules() and (not c["up"]):
                self._mark_bos(ev, now)
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
             "idm_sweep_time": None, "bos_time": self._zbos_time}
        sc["zsetups"].append(s)
        self.counts["z_setups"] += 1
        self._log("z_setup", now, setup=s["id"], choch_level=float(s["choch_level"] or 0.0))
        skip_br_buy = _rules() and self.ltf == "M15" and self.ctx["up"]
        skip_br_sell = _rules() and (not self.ctx["up"])
        if breaker is None:
            self.counts["z_no_breaker"] += 1
        elif skip_br_buy:
            self.counts["z_breaker_buy_skipped"] += 1
        elif skip_br_sell:
            self.counts["z_breaker_sell_skipped"] += 1
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
        s["idm_sweep_time"] = now
        if box.state != "fresh" and not bool(config.TRADE_USED_POIS):
            self.counts["z_ob_box_used"] += 1
            return
        near = box.low if tsell else box.high
        touched = bar.high >= near if tsell else bar.low <= near
        if touched:
            self.counts["z_ob_same_bar"] += 1
            if not tsell:
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
        tsell = not self.ctx["up"]
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
        if self._spread > 0.0:
            min_risk = (self._spread / float(config.MAX_SPREAD_RISK_RATIO)) * 1.0001
            if abs(entry - stop) < min_risk:
                stop = entry + min_risk if tsell else entry - min_risk
                self.counts["z_" + kind + "_min_risk_padded"] += 1
        ceiling = float(sc["ceiling"])
        z = sc["zone"]
        self._n_zo += 1
        order = {"id": f"ZO{self._n_zo}", "pullback": sc["pb_id"], "setup": s["id"],
                 "variant": "plain", "kind": kind, "leg": "zone",
                 "side": "sell" if tsell else "buy",
                 "htf_bias": self.ctx["bias"],
                 "placed_time": now, "entry": float(entry), "stop": float(stop),
                 "stop_edge": float(edge), "box_low": float(p.low),
                 "box_high": float(p.high), "box_time": p.candle_time,
                 "atr": float(atr),
                 "ceiling": ceiling, "ceiling_locked": bool(sc["locked"]),
                 "end_time": None, "end_reason": None,
                 "liq": self._liq(entry, ceiling, tsell),
                 "bos_time": s["bos_time"], "zone_touch_time": sc["touch_time"],
                 "zone_tf": z["tf"], "zone_low": float(z["low"]),
                 "zone_high": float(z["high"]), "choch_time": s["choch_time"],
                 "choch_level": s["choch_level"],
                 "idm_level": cy._num(s.get("idm")),
                 "idm_sweep_time": s.get("idm_sweep_time"),
                 "zone_id": z["id"]}
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
    # =========================================================================
    # 1H Continuation Zone Stream (Addition 1 + Addition 2: Persistent HTF Trend)
    # =========================================================================
    def _h1_step(self, bar, ev, now):
        hb = htf_bias(self.bias["D1"], self.bias["H4"])
        q, self._h1_q = self._h1_q, []
        # Step 1: Persistent Daily/H4 Trend Permission (require D1 + H4 alignment)
        if hb not in ("bull", "bear"):
            if self._h1_scan is not None:
                self._h1_end(self._h1_scan, now, "bias_lost")
                self._h1_scan = None
            self._h1_zones = []
            self._h1_bos = False
            self._h1_bos_time = None
            self._h1_bias = None
            return
        if self._h1_bias != hb:
            if self._h1_scan is not None:
                self._h1_end(self._h1_scan, now, "bias_lost")
                self._h1_scan = None
            self._h1_zones = []
            self._h1_bos = False
            self._h1_bos_time = None
            self._h1_bias = hb
        up = (hb == "bull")
        htf_dir = "up" if up else "down"
        zone_side = "buy" if up else "sell"
        choch_dir = "down" if up else "up"
        # Step 2: Register new H1 Continuation Zones from confirmed pro-trend H1 BOS
        for hev in q:
            if hev["label"] == "BOS" and hev["direction"] == htf_dir:
                self.counts["h1_bos_aligned"] += 1
                pois = self.books["H1"].pois
                if (pois and pois[-1].origin == "BOS"
                        and pois[-1].born_time == hev["time"]
                        and pois[-1].side == zone_side
                        and pois[-1].state == "fresh"):
                    p = pois[-1]
                    c_init = (
                        max(float(hev["close"]), float(hev["broken_swing_price"] or hev["close"]))
                        if up else
                        min(float(hev["close"]), float(hev["broken_swing_price"] or hev["close"]))
                    )
                    z = {"id": p.id, "tf": "H1", "poi": p,
                         "low": float(p.low), "high": float(p.high),
                         "born_time": hev["time"], "ceiling": c_init}
                    self._h1_zones.append(z)
                    self.counts["h1_zones_born"] += 1
        # Update dynamic impulse ceiling on waiting H1 zones & prune stale (>96h), used, or dead zones
        alive_zones = []
        for z in self._h1_zones:
            if z["poi"].state == "dead" or z["id"] in self._spent:
                continue
            if now - z["born_time"] > H1_ZONE_MAX_AGE:
                self.counts["h1_zone_expired_48h"] += 1
                continue
            if up and float(bar.high) > z["ceiling"]:
                z["ceiling"] = float(bar.high)
            elif (not up) and float(bar.low) < z["ceiling"]:
                z["ceiling"] = float(bar.low)
            alive_zones.append(z)
        self._h1_zones = alive_zones
        # Track counter-trend M15 BOS or CHoCH that precedes or accompanies a return into the H1 zone
        if ev is not None:
            if ev["label"] in ("BOS", "CHoCH") and ev["direction"] == choch_dir:
                self._h1_bos = True
                self._h1_bos_time = ev["time"]
        # Step 3: Check for first return to a FRESH H1 zone if not currently scanning one
        if self._h1_scan is None:
            touched_z = self._h1_zone_touched(bar, up, now)
            if touched_z is not None:
                self._n_h1_scan += 1
                self._h1_scan = {
                    "zone": touched_z,
                    "ceiling": float(touched_z["ceiling"]),
                    "locked": True,
                    "pb_id": f"H1C{self._n_h1_scan}",
                    "touch_time": now,
                    "zorders": [],
                    "zsetups": [],
                }
                self.counts["h1_scan"] += 1
                self._log("h1_touch", now, pb=self._h1_scan["pb_id"],
                          zone=touched_z["id"], zone_tf="H1",
                          zone_low=float(touched_z["low"]),
                          zone_high=float(touched_z["high"]),
                          ceiling=float(touched_z["ceiling"]))
        if self._h1_scan is not None:
            self._h1_scan_step(bar, ev, now, up)
    def _h1_zone_touched(self, bar, up, now):
        best = None
        for z in self._h1_zones:
            # Strict freshness: only fresh H1 zones can initiate a continuation scan
            if z["poi"].state != "fresh" or z["id"] in self._spent:
                continue
            if now <= z["born_time"]:
                continue
            if up:
                hit = float(bar.low) <= z["high"]
                near = z["high"]
            else:
                hit = float(bar.high) >= z["low"]
                near = z["low"]
            if hit and (best is None or (near > best[0] if up else near < best[0])):
                best = (near, z)
        return best[1] if best is not None else None
    def _h1_scan_step(self, bar, ev, now, up):
        sc = self._h1_scan
        z = sc["zone"]
        # Expire stale H1 scan if M15 confirmation hasn't completed within 48h of zone touch
        if now - sc["touch_time"] > H1_SCAN_MAX_DURATION and not sc["zorders"]:
            self.counts["h1_scan_expired_24h"] += 1
            self._h1_end(sc, now, "scan_expired_24h")
            self._h1_scan = None
            return
        # Ceiling / runaway check:
        # Before an order is placed (while M15 CHoCH -> BOS confirmation is forming out of the H1 zone),
        # allow price up to 0.5x cancel_dist (75 pips) beyond the H1 zone edge and expand sc["ceiling"]
        # to the confirmation peak. Once an order is placed, lock sc["ceiling"] at that peak.
        if not sc["zorders"]:
            max_run = 0.5 * self._cancel_dist()
            run_limit = (float(z["high"]) + max_run) if up else (float(z["low"]) - max_run)
            if max_run > 0.0 and cy._beyond(bar.close, run_limit, up):
                self.counts["h1_scan_ceiling_break"] += 1
                self._h1_end(sc, now, "ceiling_break")
                self._h1_scan = None
                return
            if up and float(bar.high) > sc["ceiling"]:
                sc["ceiling"] = float(bar.high)
            elif (not up) and float(bar.low) < sc["ceiling"]:
                sc["ceiling"] = float(bar.low)
        else:
            if cy._beyond(bar.close, sc["ceiling"], up):
                self.counts["h1_scan_ceiling_break"] += 1
                self._h1_end(sc, now, "ceiling_break")
                self._h1_scan = None
                return
        far = z["low"] if up else z["high"]
        if cy._beyond(bar.close, far, not up) or z["poi"].state == "dead":
            z["poi"].state = "dead"
            self.counts["h1_scan_far_break"] += 1
            self._h1_end(sc, now, "zone_far_break")
            self._h1_scan = None
            return
        if z["id"] in self._spent:
            self._h1_end(sc, now, "zone_spent")
            self._h1_scan = None
            return
        # Step 4: Run M15 confirmation setups inside the H1 zone
        for s in sc["zsetups"]:
            if s["ob"] == "wait_sweep":
                self._h1_try_ob(s, sc, bar, now, up)
        if ev is None:
            return
        lab = ev["label"]
        d = ev["direction"]
        choch_dir = "down" if up else "up"
        other_dir = "up" if up else "down"
        if lab == "BOS" and d == choch_dir:
            self._h1_bos = True
            self._h1_bos_time = ev["time"]
        elif lab == "CHoCH" and d == other_dir:
            # Precedence rule: if deep D1/H4 zone scan is active on this exact M15 CHoCH, let D1/H4 take it
            if self.state == cy.SCAN and self._scan is not None and self._zbos:
                self.counts["h1_duplicate_with_htf_zone_skipped"] += 1
                return
            if self._h1_bos and self._h1_bos_time is not None:
                self._h1_new_choch(sc, bar, ev, now, up)
            else:
                self.counts["h1_choch_no_bos"] += 1
            if not up:
                self._h1_bos = False
                self._h1_bos_time = None
        elif lab == "BOS" and d == other_dir:
            for s in sc["zsetups"]:
                if s["ob"] == "wait_bos" and s["choch_time"] < ev["time"]:
                    p = cy._num(ev["last_opposite_price"])
                    if p is None:
                        s["ob"] = "none"
                        self.counts["h1_ob_no_idm"] += 1
                    else:
                        s["idm"] = p
                        s["ob"] = "wait_sweep"
                        self.counts["h1_idm_set"] += 1
        elif lab == "CHoCH" and d == choch_dir:
            self._h1_bos = True
            self._h1_bos_time = ev["time"]
            for s in sc["zsetups"]:
                if s["ob"] == "wait_bos":
                    s["ob"] = "none"
                    self.counts["h1_ob_no_bos"] += 1
    def _h1_new_choch(self, sc, bar, ev, now, up):
        self._n_z += 1
        box = self._choch_poi(ev)
        s = {"id": f"{sc['pb_id']}-Z{self._n_z}", "choch_time": ev["time"],
             "choch_level": cy._num(ev["broken_swing_price"]), "box": box,
             "breaker": None, "br": "none", "ob": "none", "idm": None,
             "idm_sweep_time": None, "bos_time": self._h1_bos_time}
        sc["zsetups"].append(s)
        self.counts["h1_setups"] += 1
        self._log("h1_setup", now, setup=s["id"], choch_level=float(s["choch_level"] or 0.0))
        if box is None:
            self.counts["h1_no_choch_box"] += 1
        else:
            s["ob"] = "wait_bos"
    def _h1_try_ob(self, s, sc, bar, now, up):
        tsell = not up
        box = s["box"]
        if box.state == "dead":
            s["ob"] = "none"
            self.counts["h1_ob_box_dead"] += 1
            return
        idm = s["idm"]
        swept = bar.high > idm if tsell else bar.low < idm
        if not swept:
            return
        s["ob"] = "none"
        s["idm_sweep_time"] = now
        if box.state != "fresh" and not bool(config.TRADE_USED_POIS):
            self.counts["h1_ob_box_used"] += 1
            return
        near = box.low if tsell else box.high
        touched = bar.high >= near if tsell else bar.low <= near
        if touched:
            self.counts["h1_ob_same_bar"] += 1
            if not tsell:
                return
        self._h1_place(s, sc, "ob", box, bar, now, up)
    def _h1_blocked_by_opposing_htf_zone(self, entry, risk, tsell):
        need = float(H1_OPPOSING_HTF_MIN_R) * risk
        opp_side = "buy" if tsell else "sell"
        for tf in ("D1", "H4"):
            for p in self.books[tf].usable(opp_side, include_used=True):
                if tsell:
                    if float(p.high) < entry and (entry - float(p.high)) < need:
                        return True
                else:
                    if float(p.low) > entry and (float(p.low) - entry) < need:
                        return True
        return False
    def _h1_place(self, s, sc, kind, p, bar, now, up):
        tsell = not up
        # Skip low-liquidity Asian session (00:00 - 05:59 UTC) on H1 continuation placements
        if now.hour < 6:
            self.counts["h1_asian_skipped"] += 1
            return None
        atr = self.atr.value_at(p.candle_time)
        if atr is None:
            self.counts["h1_" + kind + "_no_atr"] += 1
            return None
        entry = p.low if tsell else p.high
        edge = p.high if tsell else p.low
        ahead = bar.close < entry if tsell else bar.close > entry
        if not ahead:
            self.counts["h1_" + kind + "_entry_not_ahead"] += 1
            return None
        box_w = float(p.high) - float(p.low)
        if box_w < 0.25 * float(atr) or box_w > 1.75 * float(atr):
            self.counts["h1_ob_box_size_filtered"] += 1
            return None
        if s.get("idm") is not None:
            idm_dist = (float(entry) - float(s["idm"])) if tsell else (float(s["idm"]) - float(entry))
            if idm_dist < 0.50 * float(atr):
                self.counts["h1_ob_idm_too_close"] += 1
                return None
        buf = float(config.STOP_BUFFER_ATR) * float(atr)
        stop = edge + buf if tsell else edge - buf
        if self._spread > 0.0:
            min_risk = (self._spread / float(config.MAX_SPREAD_RISK_RATIO)) * 1.0001
            if abs(entry - stop) < min_risk:
                stop = entry + min_risk if tsell else entry - min_risk
                self.counts["h1_" + kind + "_min_risk_padded"] += 1
        risk = abs(float(entry) - float(stop))
        if risk > 0 and self._h1_blocked_by_opposing_htf_zone(float(entry), risk, tsell):
            self.counts["h1_blocked_opposing_htf_zone"] += 1
            return None
        ceiling = float(sc["ceiling"])
        z = sc["zone"]
        self._n_zo += 1
        order = {"id": f"ZO{self._n_zo}", "pullback": sc["pb_id"], "setup": s["id"],
                 "variant": "plain", "kind": kind, "leg": "zone",
                 "side": "sell" if tsell else "buy",
                 "htf_bias": "bull" if up else "bear",
                 "placed_time": now, "entry": float(entry), "stop": float(stop),
                 "stop_edge": float(edge), "box_low": float(p.low),
                 "box_high": float(p.high), "box_time": p.candle_time,
                 "atr": float(atr),
                 "ceiling": ceiling, "ceiling_locked": True,
                 "end_time": None, "end_reason": None,
                 "liq": self._liq(entry, ceiling, tsell),
                 "bos_time": s["bos_time"], "zone_touch_time": sc["touch_time"],
                 "zone_tf": "H1", "zone_low": float(z["low"]),
                 "zone_high": float(z["high"]), "choch_time": s["choch_time"],
                 "choch_level": s["choch_level"],
                 "idm_level": cy._num(s.get("idm")),
                 "idm_sweep_time": s.get("idm_sweep_time"),
                 "zone_id": z["id"]}
        sc["zorders"].append(order)
        self.zorders.append(order)
        if _rules():
            self._watch.append({"o": order, "st": "pending"})
        self.counts["z_orders_" + kind] += 1
        self.counts["h1_orders_" + kind] += 1
        self._log("z_order", now, id=order["id"], order_kind=kind, side=order["side"],
                  entry=order["entry"], stop=order["stop"], setup=s["id"],
                  zone_tf="H1", liq_n=len(order["liq"]))
        return order
    def _h1_end(self, sc, now, reason):
        n = 0
        for o in sc.get("zorders", []):
            if o["end_time"] is None:
                o["end_time"] = now
                o["end_reason"] = reason
                n += 1
        self.counts["h1_end_" + reason] += 1
        self._log("h1_end", now, reason=reason, cancelled=n)
