"""Phase 4 cycle engine, rebuild 2: pullbacks / reversals.

Sell side in a bull context; the buy side is the exact mirror. Bar by bar, no
lookahead. Sits on top of MapRecorder (structure, POI books, bias, ATR).

The trading timeframe is self.ltf (M15 by default, H1 when config.LTF_TF is
"H1"). Method names such as _on_m15 keep their old names; they run on bars of
the trading timeframe.
"""
from bisect import bisect_left
from collections import defaultdict
import math

import pandas as pd

from src import config
from src.research.engine import poi as poi_mod
from src.research.engine.bias import htf_bias
from src.research.engine.mapper import MapRecorder
from src.research.lookahead_guard import DataFeed, DecisionLog

IDLE = "idle"
ARMED = "armed"
PULL = "pullback"
SCAN = "buy_scan"

_CTX = {
    "sell": {"side": "sell", "bias": "bull", "htf_dir": "up", "choch_dir": "down",
             "other_dir": "up", "zone_side": "buy", "up": True},
    "buy": {"side": "buy", "bias": "bear", "htf_dir": "down", "choch_dir": "up",
            "other_dir": "down", "zone_side": "sell", "up": False},
}


def _num(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _beyond(price, level, up):
    return price > level if up else price < level


class CycleRecorder(MapRecorder):
    def __init__(self, log, first_read=None):
        super().__init__(log)
        if first_read is not None:
            for tr in self.bias.values():
                tr.first_read = int(first_read)
        self.counts = defaultdict(int)
        self.orders = []
        self.pullbacks = []
        self.state = IDLE
        self.ctx = None
        self._pb = None
        self._scan = None
        self._htf_q = []
        self._h4 = {}
        self._h4_times = []
        self._n_pb = 0
        self._n_setup = 0
        self._n_order = 0
        self._spread = 0.0

    def on_bar_close(self, bar, feed):
        n0 = len(self.events)
        super().on_bar_close(bar, feed)
        if bar.tf == "H4":
            self._h4[bar.open_time] = bar
            self._h4_times.append(bar.open_time)
        new = self.events[n0:]
        if bar.tf in ("H4", "D1"):
            self._htf_q.extend(new)
        elif bar.tf == self.ltf:
            self._on_m15(bar, new[0] if new else None)

    def _log(self, kind, now, **data):
        self.log.add(kind, now, now, **data)

    def _on_m15(self, bar, ev):
        now = bar.close_time
        queue, self._htf_q = self._htf_q, []
        for hev in queue:
            self._on_htf_event(hev, now)
        self._check_bias(now)
        if ev is not None and ev["label"] == "CHoCH" and self.state == IDLE:
            self.counts["choch_idle"] += 1
        if self.state == ARMED:
            self._armed_step(bar, ev, now)
        elif self.state == PULL:
            self._pull_step(bar, ev, now)
        elif self.state == SCAN:
            self._scan_step(bar, now)

    def _on_htf_event(self, ev, now):
        if ev["label"] != "BOS":
            return
        if self.state in (PULL, SCAN):
            self.counts["htf_bos_ignored_in_pullback"] += 1
            return
        if self.state == ARMED:
            return
        hb = htf_bias(self.bias["D1"], self.bias["H4"])
        for c in _CTX.values():
            if hb == c["bias"] and ev["direction"] == c["htf_dir"]:
                self.ctx = c
                self.state = ARMED
                self.counts["htf_arm"] += 1
                self._log("pb_armed", now, tf=ev["tf"], side=c["side"])
                return
        self.counts["htf_bos_no_arm"] += 1

    def _check_bias(self, now):
        if self.state == IDLE:
            return
        if htf_bias(self.bias["D1"], self.bias["H4"]) == self.ctx["bias"]:
            return
        if self.state == PULL:
            self._end_pullback(now, "bias_lost")
        self._scan = None
        self.state = IDLE
        self.counts["disarmed_bias"] += 1
        self._log("pb_disarm", now, reason="bias_lost")

    def _armed_step(self, bar, ev, now):
        if ev is None or ev["label"] != "CHoCH" or ev["direction"] != self.ctx["choch_dir"]:
            return
        self.counts["choch_armed"] += 1
        self._start_pullback(bar, ev, now)

    def _start_pullback(self, bar, ev, now):
        self._n_pb += 1
        zones = self._freeze_zones()
        pb = {"id": f"PB{self._n_pb}", "side": self.ctx["side"], "start": now,
              "zones": zones, "ceiling": None, "locked": False, "attempt": None,
              "setups": [], "orders": [], "end_time": None, "end_reason": None}
        self._pb = pb
        self.pullbacks.append(pb)
        self.state = PULL
        self.counts["pullbacks"] += 1
        if not zones:
            self.counts["no_zone"] += 1
        self._log("pb_start", now, id=pb["id"], side=pb["side"], zones=len(zones))
        self._new_choch(bar, ev, now)

    def _freeze_zones(self):
        buy_zone = self.ctx["zone_side"] == "buy"
        inc = bool(config.TRADE_USED_POIS)
        out = []
        for tf in ("D1", "H4"):
            for p in self.books[tf].usable(self.ctx["zone_side"], include_used=inc):
                out.append(self._refine(p, buy_zone))
        return out

    def _refine(self, p, buy_zone):
        zone = {"id": p.id, "tf": p.tf, "poi": p, "low": p.low, "high": p.high,
                "refined": False}
        if p.tf != "D1":
            return zone
        t0 = p.candle_time
        t1 = t0 + pd.Timedelta(days=1)
        i = bisect_left(self._h4_times, t0)
        bars = []
        while i < len(self._h4_times) and self._h4_times[i] < t1:
            bars.append(self._h4[self._h4_times[i]])
            i += 1
        if not bars:
            self.counts["refine_none"] += 1
            return zone
        if buy_zone:
            k = min(range(len(bars)), key=lambda j: bars[j].low)
        else:
            k = max(range(len(bars)), key=lambda j: bars[j].high)

        def right(b):
            return b.close < b.open if buy_zone else b.close > b.open

        pick = k
        if poi_mod.REQUIRE_COLOUR and not right(bars[k]):
            step = -1 if config.WRONG_COLOUR_SEARCH_DIRECTION == "back" else 1
            pick = None
            for d in range(1, int(config.OB_SEARCH_BACK_MAX) + 1):
                j = k + step * d
                if j < 0 or j >= len(bars):
                    break
                if right(bars[j]):
                    pick = j
                    break
            if pick is None:
                pick = k
                self.counts["refine_cap"] += 1
        b = bars[pick]
        zone["low"] = b.low
        zone["high"] = b.high
        zone["refined"] = True
        return zone

    def _choch_poi(self, ev):
        pois = self.books[self.ltf].pois
        if pois and pois[-1].origin == "CHoCH" and pois[-1].born_time == ev["time"]:
            return pois[-1]
        return None

    def _new_choch(self, bar, ev, now):
        pb = self._pb
        if pb["ceiling"] is None:
            c = _num(ev["last_opposite_price"])
            if c is None:
                self.counts["no_ceiling"] += 1
                return
            pb["ceiling"] = c
            pb["locked"] = False
            pb["attempt"] = {"choch_time": ev["time"], "after": 0}
            self._log("pb_ceiling", now, id=pb["id"], ceiling=c, locked=False)
        else:
            self.counts["choch_in_pullback"] += 1
        self._n_setup += 1
        box = self._choch_poi(ev)
        breaker = self.books[self.ltf].choch_breaker.get(ev["time"])
        setup = {"id": f"{pb['id']}-S{self._n_setup}", "choch_time": ev["time"],
                 "box": box, "breaker": breaker,
                 "attempt": None if pb["locked"] else pb["attempt"],
                 "br": "none", "ob": "none", "idm": None}
        pb["setups"].append(setup)
        self.counts["setups"] += 1
        skip_br_sell = bool(getattr(config, "MAJOR_HTF", False)) and self.ctx["side"] == "sell"
        if breaker is None:
            self.counts["no_breaker"] += 1
        elif skip_br_sell:
            self.counts["breaker_sell_skipped"] += 1
        else:
            setup["br"] = "wait"
            self._try_breaker(setup, bar, now, first=True)
            if setup["br"] == "wait":
                self.counts["breaker_wait"] += 1
        if box is None:
            self.counts["no_choch_box"] += 1
        else:
            setup["ob"] = "wait_bos"

    def _try_breaker(self, s, bar, now, first):
        p = s["breaker"]
        if p.state != "dead":
            return
        s["br"] = "none"
        if self._place(s, "breaker", p, bar, now) is not None and not first:
            self.counts["breaker_late"] += 1

    def _try_ob(self, s, bar, now):
        up = self.ctx["up"]
        box = s["box"]
        if box.state == "dead":
            s["ob"] = "none"
            self.counts["ob_box_dead"] += 1
            return
        idm = s["idm"]
        swept = bar.high > idm if up else bar.low < idm
        if not swept:
            return
        s["ob"] = "none"
        allow_used = bool(config.TRADE_USED_POIS) or bool(getattr(config, "MAJOR_HTF", False))
        if box.state != "fresh" and not allow_used:
            self.counts["ob_box_used"] += 1
            return
        near = box.low if up else box.high
        touched = bar.high >= near if up else bar.low <= near
        if touched:
            self.counts["ob_same_bar"] += 1
            return
        self._place(s, "ob", box, bar, now)

    def _place(self, setup, kind, p, bar, now):
        up = self.ctx["up"]
        atr = self.atr.value_at(p.candle_time)
        if atr is None:
            self.counts[kind + "_no_atr"] += 1
            return None
        entry = p.low if up else p.high
        edge = p.high if up else p.low
        ahead = bar.close < entry if up else bar.close > entry
        if not ahead:
            self.counts[kind + "_entry_not_ahead"] += 1
            return None
        buf = float(config.STOP_BUFFER_ATR) * float(atr)
        stop = edge + buf if up else edge - buf
        # Stage 1A: min_risk stop padding only on Pullback OB SELL
        if self._spread > 0.0 and kind == "ob" and up:
            min_risk = (self._spread / float(config.MAX_SPREAD_RISK_RATIO)) * 1.0001
            if abs(entry - stop) < min_risk:
                stop = entry + min_risk if up else entry - min_risk
                self.counts[kind + "_min_risk_padded"] += 1
        pb = self._pb
        self._n_order += 1
        breaker = setup["breaker"]
        order = {"id": f"O{self._n_order}", "pullback": pb["id"], "setup": setup["id"],
                 "variant": "plain", "kind": kind, "side": self.ctx["side"],
                 "placed_time": now, "entry": float(entry), "stop": float(stop),
                 "stop_edge": float(edge), "box_low": float(p.low),
                 "box_high": float(p.high), "atr": float(atr),
                 "ceiling": pb["ceiling"], "ceiling_locked": pb["locked"],
                 "breaker_id": breaker.id if breaker is not None else None,
                 "anchor_id": None, "end_time": None, "end_reason": None,
                 "fill": "limit" if kind == "ob" else "next_open"}
        self.orders.append(order)
        pb["orders"].append(order)
        self.counts["orders_" + kind] += 1
        self._log("pb_order", now, id=order["id"], order_kind=kind,
                  side=order["side"], entry=order["entry"], stop=order["stop"],
                  setup=setup["id"])
        return order

    def _pull_step(self, bar, ev, now):
        pb = self._pb
        up = self.ctx["up"]
        if pb["ceiling"] is not None and _beyond(bar.close, pb["ceiling"], up):
            if pb["locked"]:
                self._end_pullback(now, "ceiling_break")
                self.counts["end_ceiling_break"] += 1
                self.state = ARMED
                self.counts["rearm"] += 1
                self._log("pb_rearm", now, id=pb["id"])
                return
            self._fail_attempt(now, "ceiling_break")
            return
        z = self._zone_touched(bar)
        if z is not None:
            ceiling = pb["ceiling"]
            self._end_pullback(now, "zone")
            self.counts["end_zone"] += 1
            if ceiling is None:
                self.state = IDLE
                self.counts["zone_no_ceiling"] += 1
            else:
                self.state = SCAN
                self._scan = {"zone": z, "ceiling": ceiling}
                self._log("pb_zone", now, id=pb["id"], zone=z["id"], tf=z["tf"])
                self._scan_step(bar, now)
            return
        for s in pb["setups"]:
            if s["br"] == "wait":
                self._try_breaker(s, bar, now, first=False)
            if s["ob"] == "wait_sweep":
                self._try_ob(s, bar, now)
        if ev is None:
            return
        lab = ev["label"]
        d = ev["direction"]
        if lab == "CHoCH" and d == self.ctx["choch_dir"]:
            self._new_choch(bar, ev, now)
        elif lab == "BOS" and d == self.ctx["choch_dir"]:
            self._on_bos(ev, now)
        elif lab == "CHoCH" and d == self.ctx["other_dir"]:
            self._on_choch_other(now)

    def _on_bos(self, ev, now):
        pb = self._pb
        for s in pb["setups"]:
            if s["ob"] == "wait_bos" and s["choch_time"] < ev["time"]:
                p = _num(ev["last_opposite_price"])
                if p is None:
                    s["ob"] = "none"
                    self.counts["ob_no_idm"] += 1
                else:
                    s["idm"] = p
                    s["ob"] = "wait_sweep"
                    self.counts["idm_set"] += 1
        a = pb["attempt"]
        if not pb["locked"] and a is not None:
            a["after"] += 1
            if a["after"] >= 2:
                self._lock(now)

    def _on_choch_other(self, now):
        pb = self._pb
        for s in pb["setups"]:
            if s["ob"] == "wait_bos":
                s["ob"] = "none"
                self.counts["ob_no_bos"] += 1
        a = pb["attempt"]
        if not pb["locked"] and a is not None:
            if a["after"] == 0:
                self._fail_attempt(now, "choch_against")
            else:
                self._lock(now)

    def _lock(self, now):
        pb = self._pb
        pb["locked"] = True
        self.counts["ceiling_locked"] += 1
        self._log("pb_lock", now, id=pb["id"], ceiling=pb["ceiling"])

    def _fail_attempt(self, now, why):
        pb = self._pb
        a = pb["attempt"]
        ids = set()
        for s in pb["setups"]:
            if a is not None and s["attempt"] is a:
                s["br"] = "none"
                s["ob"] = "none"
                ids.add(s["id"])
        reason = "ceiling_break" if why == "ceiling_break" else "attempt_failed"
        for o in pb["orders"]:
            if o["setup"] in ids and o["end_time"] is None:
                o["end_time"] = now
                o["end_reason"] = reason
        pb["ceiling"] = None
        pb["attempt"] = None
        pb["locked"] = False
        self.counts["attempt_failed_" + why] += 1
        self._log("pb_fail", now, id=pb["id"], why=why)

    def _end_pullback(self, now, reason):
        pb = self._pb
        for o in pb["orders"]:
            if o["end_time"] is None:
                o["end_time"] = now
                o["end_reason"] = reason
        pb["end_time"] = now
        pb["end_reason"] = reason
        self._log("pb_end", now, id=pb["id"], reason=reason)
        self._pb = None

    def _zone_touched(self, bar):
        up = self.ctx["up"]
        ok = ("fresh", "used") if config.TRADE_USED_POIS else ("fresh",)
        best = None
        for z in self._pb["zones"]:
            if z["poi"].state not in ok:
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

    def _scan_step(self, bar, now):
        sc = self._scan
        up = self.ctx["up"]
        if _beyond(bar.close, sc["ceiling"], up):
            self.counts["scan_ceiling_break"] += 1
            self.counts["rearm"] += 1
            self.state = ARMED
            self._scan = None
            self._log("pb_scan_end", now, reason="ceiling_break")
            return
        far = sc["zone"]["low"] if up else sc["zone"]["high"]
        if _beyond(bar.close, far, not up):
            self.counts["scan_far_break"] += 1
            self.state = IDLE
            self._scan = None
            self._log("pb_scan_end", now, reason="far_edge_break")

    def funnel(self):
        return dict(self.counts)

    def pullback_rows(self):
        return [{"id": pb["id"], "side": pb["side"], "start": pb["start"],
                 "end_time": pb["end_time"], "end_reason": pb["end_reason"],
                 "ceiling": pb["ceiling"], "locked": pb["locked"],
                 "zones": len(pb["zones"]), "setups": len(pb["setups"]),
                 "orders": len(pb["orders"])} for pb in self.pullbacks]


def run_cycle(m15, first_read=None):
    log = DecisionLog()
    rec = CycleRecorder(log, first_read)
    DataFeed(m15, htf=("H1", "H4", "D1")).run(rec)
    return rec, log


def run_cycle_pipeline(m15):
    return run_cycle(m15)[1].items
