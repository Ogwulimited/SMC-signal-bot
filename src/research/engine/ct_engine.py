"""Experimental separate H1 continuation prototype, not a live strategy.

Requires D1/H4 agreement and H1 structure, displacement and at least one of
FVG, confirmed-swing sweep or HTF-zone proximity. An alternative HTF zone
entry uses recent H1 confirmation. Orders use ATR stops and 48-hour expiry.
No profitable edge or frequency is assumed; practice results must establish it.
"""
from bisect import bisect_left, bisect_right, insort
from collections import defaultdict, deque

import pandas as pd

from src import config
from src.research.engine import fvg as fvg_mod
from src.research.engine.bias import htf_bias
from src.research.engine.mapper import MapRecorder

SETTINGS = {"pip": 0.0001, "spread": 0.0}
LIQ_CAP = 100
STOP_BUF = 0.3            # x ATR(H1,14) beyond the far edge
DISP_BODY_ATR = 0.4       # displacement body minimum
BOX_MIN_ATR = 0.2
BOX_MAX_ATR = 2.0
ZONE_PROX_ATR = 0.75
RUNAWAY_ATR = 1.5
EXPIRY = pd.Timedelta(hours=48)
CONFIRM_WINDOW = pd.Timedelta(hours=10)
MAX_PER_ZONE = 3


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if v != v else v


class CTEngine(MapRecorder):
    def __init__(self, log, first_read=3):
        super().__init__(log)
        for tr in self.bias.values():
            tr.first_read = int(first_read)
        self.counts = defaultdict(int)
        self.ctorders = []
        self._open_orders = {}
        self.orders = []          # alias so generic tooling sees orders
        self.pullbacks = []
        self.flips = []
        self._last_real = None
        self._n = 0
        self._ready_h1 = []
        self._zone_count = defaultdict(int)
        self._pending_zones = set()
        self._last_trend = {"up": None, "down": None}
        self._last_sweep = {"up": None, "down": None}
        # H1 swing lists for the liquidity target (same method as zone.py)
        n = int(config.LTF_SWING_N)
        self._swin = deque(maxlen=2 * n + 1)
        self._sw_hi = []
        self._sw_lo = []
        self._spread = float(SETTINGS.get("spread", 0.0))

    # ---- plumbing -----------------------------------------------------
    def _log(self, kind, now, **data):
        self.log.add(kind, now, now, **data)

    def on_bar_close(self, bar, feed):
        n0 = len(self.events)
        super().on_bar_close(bar, feed)
        if bar.tf == "H1":
            # Feed delivers H1 before its final M15. Defer decisions until
            # that M15 has been observed so a fill cannot be cancelled later.
            self._ready_h1.append((bar, self.events[n0:]))
        if bar.tf != "M15":
            return
        self._observe_fills(bar)
        hb = htf_bias(self.bias["D1"], self.bias["H4"])
        if hb is not None:
            if self._last_real is not None and hb != self._last_real:
                self.flips.append(feed.now)
            self._last_real = hb
        for h1, events in self._ready_h1:
            now = feed.now
            if any(h1.low < p < h1.close for p in self._sw_lo):
                self._last_sweep["up"] = now
            if any(h1.high > p > h1.close for p in self._sw_hi):
                self._last_sweep["down"] = now
            self._swings(h1)
            self._cancel_pending(h1, now)
            if h1.close_time == now:
                for ev in events:
                    self._on_ltf_event(ev, h1, now)
                self._try_zone_direct(h1, now)
            else:
                self.counts["ct_late_h1_skipped"] += 1
        self._ready_h1.clear()

    def _swings(self, bar):
        h, l = float(bar.high), float(bar.low)
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

    def _liq(self, entry, ceiling, tsell):
        if tsell:
            lo = self._sw_lo
            b = bisect_right(lo, ceiling)
            return [float(x) for x in reversed(lo[:b])][:LIQ_CAP]
        hi = self._sw_hi
        a = bisect_left(hi, ceiling)
        return [float(x) for x in hi[a:]][:LIQ_CAP]

    # ---- pending-order management ------------------------------------
    def _observe_fills(self, bar):
        # An order can fill on the final M15 bar before an H1-close cancellation.
        for o in list(self._open_orders.values()):
            if o.get("_touched") or bar.open_time < o["placed_time"]:
                continue
            if o["end_time"] is not None and bar.close_time >= o["end_time"]:
                continue
            touched = bar.high >= o["entry"] if o["side"] == "sell" else bar.low <= o["entry"]
            if touched:
                o["_touched"] = True
                self._pending_zones.discard(o["zone_id"])
                self._open_orders.pop(o["id"], None)
                self._log("ct_touch", bar.close_time, id=o["id"])

    def _cancel_pending(self, bar, now):
        hb = htf_bias(self.bias["D1"], self.bias["H4"])
        for o in list(self._open_orders.values()):
            if o["end_time"] is not None or o.get("_touched"):
                continue
            reason = None
            if hb is None or hb != o["htf_bias"]:
                reason = "bias_lost"
            elif now - o["placed_time"] >= EXPIRY:
                reason = "expired_48h"
            elif bar.close_time == now and bar.open_time >= o["placed_time"]:
                atr = float(o["atr"])
                entry = float(o["entry"])
                if o["side"] == "sell":
                    if float(bar.low) <= entry - RUNAWAY_ATR * atr:
                        reason = "ran_away"
                else:
                    if float(bar.high) >= entry + RUNAWAY_ATR * atr:
                        reason = "ran_away"
            if reason:
                # Simulator excludes the bar whose close equals end_time.
                # Cancellation is decided at H1 close, so include that last M15.
                o["end_time"] = now + pd.Timedelta(minutes=15)
                o["end_reason"] = reason
                self.counts["ct_cancel_" + reason] += 1
                self._pending_zones.discard(o.get("zone_id"))
                self._open_orders.pop(o["id"], None)
                self._log("ct_cancel", now, id=o["id"], reason=reason)

    # ---- entry generation --------------------------------------------
    def _on_ltf_event(self, ev, bar, now):
        if ev["label"] not in ("BOS", "CHoCH"):
            return
        hb = htf_bias(self.bias["D1"], self.bias["H4"])
        if hb is None:
            self.counts["ct_no_bias"] += 1
            return
        trend = "up" if hb == "bull" else "down"
        if ev["direction"] != trend:
            self.counts["ct_counter_trend_ignored"] += 1
            return
        self._last_trend[trend] = now
        side = "buy" if hb == "bull" else "sell"
        tsell = side == "sell"
        book = self.books["H1"]
        box = None
        if book.pois and book.pois[-1].born_time == ev["time"]:
            box = book.pois[-1]
        if box is None:
            self.counts["ct_no_box"] += 1
            return
        if box.state == "dead":
            self.counts["ct_box_dead"] += 1
            return
        atr = self.atr.value_at(box.candle_time)
        if atr is None or not atr > 0:
            self.counts["ct_no_atr"] += 1
            return
        atr = float(atr)
        width = float(box.high) - float(box.low)
        if width < BOX_MIN_ATR * atr or width > BOX_MAX_ATR * atr:
            self.counts["ct_box_width_filtered"] += 1
            return
        # displacement: event-bar body from the H1 window
        candles = book.window(now - pd.Timedelta(hours=3), now)
        if not candles:
            self.counts["ct_no_window"] += 1
            return
        last = candles[-1]
        body = abs(float(last.close) - float(last.open))
        if body < DISP_BODY_ATR * atr or (last.close <= last.open if not tsell else last.close >= last.open):
            self.counts["ct_no_displacement"] += 1
            return
        # confluences (need >= 1)
        conf = []
        fvgs = fvg_mod.find_fvgs(candles, self.atr.value_at)
        fdir = "down" if tsell else "up"
        if any(f.direction == fdir and f.low <= box.high and f.high >= box.low
               for f in fvgs):
            conf.append("FVG")
        sweep_time = self._last_sweep[trend]
        if sweep_time is not None and now - sweep_time <= CONFIRM_WINDOW:
            conf.append("SWEEP")
        zone = self._nearest_htf_zone(float(box.low), float(box.high), side, atr)
        if zone is not None:
            conf.append("HTF_ZONE")
        if not conf:
            self.counts["ct_no_confluence"] += 1
            return
        entry = float(box.low) if tsell else float(box.high)
        edge = float(box.high) if tsell else float(box.low)
        ahead = float(bar.close) < entry if tsell else float(bar.close) > entry
        if not ahead:
            self.counts["ct_entry_not_ahead"] += 1
            return
        zid = zone["id"] if zone is not None else f"H1-{box.id}"
        if self._zone_count[zid] >= MAX_PER_ZONE:
            self.counts["ct_zone_cap"] += 1
            return
        if zid in self._pending_zones:
            self.counts["ct_zone_pending"] += 1
            return
        self._place(side, tsell, box, entry, edge, atr, now, ev, zone, zid,
                    conf, kind="ob")

    def _try_zone_direct(self, bar, now):
        hb = htf_bias(self.bias["D1"], self.bias["H4"])
        if hb is None:
            return
        trend = "up" if hb == "bull" else "down"
        lt = self._last_trend[trend]
        if lt is None or now - lt > CONFIRM_WINDOW:
            return
        side = "buy" if hb == "bull" else "sell"
        tsell = side == "sell"
        for tf in ("D1", "H4"):
            for p in self.books[tf].usable(side, include_used=True):
                if self._zone_count[p.id] >= MAX_PER_ZONE:
                    continue
                if p.id in self._pending_zones:
                    continue
                atr = self.atr.value_at(p.candle_time)
                if atr is None or not atr > 0:
                    continue
                atr = float(atr)
                entry = float(p.low) if tsell else float(p.high)
                edge = float(p.high) if tsell else float(p.low)
                ahead = float(bar.close) < entry if tsell else float(bar.close) > entry
                if not ahead:
                    continue
                # only rest a limit if price is within 2 ATR of the zone
                if abs(float(bar.close) - entry) > 2.0 * atr:
                    continue
                zone = {"id": p.id, "tf": tf, "low": float(p.low),
                        "high": float(p.high), "poi": p}
                self._place(side, tsell, p, entry, edge, atr, now, None,
                            zone, p.id, ["HTF_ZONE", "TREND_CONFIRM"],
                            kind="ob")

    def _nearest_htf_zone(self, lo, hi, side, atr):
        best = None
        for tf in ("D1", "H4"):
            for p in self.books[tf].usable(side, include_used=True):
                zlo, zhi = float(p.low), float(p.high)
                overlap = not (hi < zlo or lo > zhi)
                dist = 0.0 if overlap else min(abs(lo - zhi), abs(hi - zlo))
                if overlap or dist <= ZONE_PROX_ATR * atr:
                    if best is None or dist < best[0]:
                        best = (dist, {"id": p.id, "tf": tf, "low": zlo,
                                       "high": zhi, "poi": p})
        return best[1] if best else None

    def _place(self, side, tsell, box, entry, edge, atr, now, ev, zone, zid,
               conf, kind):
        buf = STOP_BUF * atr
        stop = edge + buf if tsell else edge - buf
        risk = abs(entry - stop)
        if risk <= 0:
            self.counts["ct_bad_risk"] += 1
            return None
        ceiling = entry - 3.0 * risk if tsell else entry + 3.0 * risk
        self._n += 1
        self._zone_count[zid] += 1
        self._pending_zones.add(zid)
        order = {
            "id": f"CT{self._n}", "pullback": "CT", "setup": f"CT{self._n}",
            "variant": "ct", "kind": kind, "leg": "zone", "side": side,
            "htf_bias": "bear" if tsell else "bull",
            "placed_time": now, "entry": float(entry), "stop": float(stop),
            "stop_edge": float(edge), "box_low": float(box.low),
            "box_high": float(box.high), "box_time": box.candle_time,
            "atr": float(atr), "ceiling": float(ceiling),
            "ceiling_locked": True, "end_time": None, "end_reason": None,
            "fill": "limit", "liq": self._liq(entry, ceiling, tsell),
            "bos_time": ev["time"] if ev else None,
            "zone_touch_time": now,
            "zone_tf": "H1" if zone is None else zone["tf"],
            "zone_low": float(zone["low"]) if zone else float(box.low),
            "zone_high": float(zone["high"]) if zone else float(box.high),
            "choch_time": ev["time"] if ev else None,
            "choch_level": _num(ev.get("broken_swing_price")) if ev else None,
            "idm_level": _num(ev.get("last_opposite_price")) if ev else None,
            "idm_sweep_time": None, "zone_id": zid,
            "confluences": ",".join(conf),
        }
        self.ctorders.append(order)
        self._open_orders[order["id"]] = order
        self.orders.append(order)
        self.counts["ct_orders_" + kind] += 1
        self._log("ct_order", now, id=order["id"], side=side,
                  entry=order["entry"], stop=order["stop"],
                  conf=",".join(conf), atr=atr, ceiling=ceiling,
                  liq=tuple(order["liq"]), zone_id=zid, zone_tf=order["zone_tf"])
        return order

    def pullback_rows(self):
        return []
