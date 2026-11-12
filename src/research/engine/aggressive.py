"""Phase 4 aggressive entry (variant ag), practice years only.

His rules (confirmed): a separate run that only reads the D1 and H4 Major
zones in the bias direction (D1 and H4 must agree), refines each zone down to
H1, and rests a LIMIT at the H1 zone's near edge (buy: top, sell: bottom).
Stop = H1 far edge -/+ STOP_BUFFER_ATR x ATR(H1, 14). Static 1:5 target (the
simulator reads order["rr"]). No BOS, CHoCH, breaker or pullback logic.
"""
from bisect import bisect_left
from collections import defaultdict

import pandas as pd

from src import config
from src.research.engine.bias import htf_bias
from src.research.engine.mapper import MapRecorder
from src.research.engine.poi import PoiBook
from src.research.engine.structure import IncrementalStructure

SETTINGS = {"pip": None, "spread": None}
RR_AGG = 5.0


def _gap(p, prev):
    """Price distance between two boxes (0 when they touch or overlap)."""
    if p.high < prev.low:
        return prev.low - p.high
    if p.low > prev.high:
        return p.low - prev.high
    return 0.0


def _h1_clean(h1_book, p, upto):
    """True if H1 POI p is fresh and has zero H1 wick taps up to upto."""
    if p.dead_time is not None and p.dead_time <= upto:
        return False
    if p.used_time is not None and p.used_time <= upto:
        return False
    buy = p.side == "buy"
    edge = p.high if buy else p.low
    left_box = False
    i = bisect_left(h1_book._times, p.candle_time)
    n = len(h1_book._times)
    while i < n:
        t = h1_book._times[i]
        _o, h, l, c, ct = h1_book._bars[t]
        if ct > upto:
            break
        if ct >= p.born_time:
            if not left_box:
                if (buy and c > edge) or ((not buy) and c < edge):
                    left_box = True
            else:
                if (buy and l <= edge) or ((not buy) and h >= edge):
                    return False
        i += 1
    return True


def _h1_has_fvg(h1_book, p, upto, atr_at):
    """True if the H1 impulse leg from p created a valid FVG by upto."""
    buy = p.side == "buy"
    min_atr = float(config.FVG_MIN_SIZE_ATR)
    idx0 = bisect_left(h1_book._times, p.candle_time)
    n = len(h1_book._times)
    i = max(2, idx0 + 1)
    saw_after_born = False
    while i < n:
        t_a = h1_book._times[i - 2]
        t_b = h1_book._times[i - 1]
        t_c = h1_book._times[i]
        if t_b >= p.born_time:
            break
        _ao, ah, al, _ac, _act = h1_book._bars[t_a]
        _co, ch, cl, _cc, cct = h1_book._bars[t_c]
        if cct > upto:
            break
        if cct > p.born_time:
            saw_after_born = True
        atr = atr_at(cct)
        if atr is not None and atr > 0:
            need = min_atr * float(atr)
            if buy and cl > ah and (cl - ah) >= need:
                return True
            if (not buy) and al > ch and (al - ch) >= need:
                return True
        i += 1
    if not saw_after_born and p.born_time == upto:
        j = bisect_left(h1_book._times, p.born_time) - 1
        if 0 <= j < n:
            bo, _bh, _bl, bc, bct = h1_book._bars[h1_book._times[j]]
            atr = atr_at(bct)
            if atr is not None and atr > 0:
                need = min_atr * float(atr)
                if buy and (bc - bo) >= need:
                    return True
                if (not buy) and (bo - bc) >= need:
                    return True
    return False


def pick_h4_base(book, side, t0, t1, prev, counts):
    """Closest non-dead H4 candidate inside [t0, t1], ties to later candle."""
    best = None
    best_d = None
    for p in reversed(book.pois):
        if p.born_time > t1:
            continue
        if p.born_time < t0:
            break
        if p.side != side or p.candle_time < t0:
            continue
        if p.dead_time is not None and p.dead_time <= t1:
            counts["ag_h4_cand_dead"] += 1
            continue
        d = _gap(p, prev)
        if (best is None or d < best_d
                or (d == best_d and p.candle_time > best.candle_time)):
            best, best_d = p, d
    return best


def pick_h1_base(book, side, t0, t1, prev, atr_at, counts):
    """Closest fresh, untapped, FVG-backed H1 candidate inside [t0, t1]."""
    best = None
    best_d = None
    saw_raw = False
    saw_clean = False
    for p in reversed(book.pois):
        if p.born_time > t1:
            continue
        if p.born_time < t0:
            break
        if p.side != side or p.candle_time < t0:
            continue
        saw_raw = True
        if not _h1_clean(book, p, t1):
            counts["ag_h1_cand_mitigated"] += 1
            continue
        saw_clean = True
        if not _h1_has_fvg(book, p, t1, atr_at):
            counts["ag_h1_cand_no_fvg"] += 1
            continue
        d = _gap(p, prev)
        if (best is None or d < best_d
                or (d == best_d and p.candle_time > best.candle_time)):
            best, best_d = p, d
    if best is None:
        if saw_clean:
            counts["ag_h1_all_no_fvg"] += 1
        elif saw_raw:
            counts["ag_h1_all_mitigated"] += 1
    return best


class AggRecorder(MapRecorder):
    def __init__(self, log, first_read=None):
        super().__init__(log)
        if self.ltf != "H1":
            raise ValueError("ag needs config.LTF_TF = 'H1'")
        if SETTINGS["pip"] is None or SETTINGS["spread"] is None:
            raise ValueError("ag needs aggressive.SETTINGS pip and spread set")
        self.pip = float(SETTINGS["pip"])
        self.spread = float(SETTINGS["spread"])
        self.h4s = IncrementalStructure(config.LTF_SWING_N, pd.Timedelta(hours=4), "H4")
        self.h4s_book = PoiBook("H4", None)
        self.counts = defaultdict(int)
        self.orders = []
        self.pullbacks = []
        self.aorders = []
        self.slots = {}
        self._map = {}
        self._spent = set()
        self._closed = set()
        self._pend = []
        self._scan_key = None
        self._rescan = False
        self._n_order = 0

    def on_bar_close(self, bar, feed):
        super().on_bar_close(bar, feed)
        if bar.tf == "H4":
            self._h4_small(bar)
        elif bar.tf == "H1":
            self._on_h1(bar)
        elif bar.tf == "M15":
            self._on_m15(bar)

    def _log(self, kind, now, **data):
        self.log.add(kind, now, now, **data)

    def _h4_small(self, bar):
        ev = self.h4s.on_bar_close(bar)
        self.h4s_book.on_bar_close(bar)
        if ev is None:
            return
        self.log.add("agstruct_H4", ev["time"], ev["known_at"], label=ev["label"],
                     direction=ev["direction"], close=ev["close"])
        self.h4s_book.on_event(ev)

    def _refine(self, htf):
        side = htf.side
        if htf.tf == "D1":
            h4 = pick_h4_base(self.h4s_book, side, htf.candle_time,
                              htf.born_time, htf, self.counts)
            if h4 is None:
                self.counts["ag_no_h4_candidate"] += 1
                return None, None
            h1 = pick_h1_base(self.books["H1"], side, h4.candle_time,
                              htf.born_time, h4, self.atr.value_at, self.counts)
        else:
            h4 = None
            h1 = pick_h1_base(self.books["H1"], side, htf.candle_time,
                              htf.born_time, htf, self.atr.value_at, self.counts)
        if h1 is None:
            self.counts["ag_no_h1_candidate"] += 1
        return h4, h1

    def _on_m15(self, bar):
        now = bar.close_time
        self._pend.append((bar.open_time, now, float(bar.open), float(bar.high),
                           float(bar.low), float(bar.close)))
        self._resolve(now)
        hb = htf_bias(self.bias["D1"], self.bias["H4"])
        warn = (hb is not None) and (self.bias["D1"].warning or self.bias["H4"].warning)
        need = {"bull": "buy", "bear": "sell"}.get(hb) if not warn else None
        if hb is None:
            for key in list(self.slots):
                self._cancel(key, now, "bias_lost", True)
            self._scan_key = None
        elif warn:
            for key in list(self.slots):
                self._cancel(key, now, "bias_warning", True)
            self._scan_key = None
        else:
            for key in list(self.slots):
                if self.slots[key]["side"] != need:
                    self._cancel(key, now, "bias_lost", True)
        for key in list(self.slots):
            s = self.slots[key]
            if s["order"] is not None:
                continue
            if s["htf"].state != "fresh":
                self._drop(key, "ag_wait_htf_not_fresh")
            elif (s["h4"] is not None and s["h4"].dead_time is not None
                  and s["h4"].dead_time <= now):
                self._drop(key, "ag_drop_h4_dead")
            elif not _h1_clean(self.books["H1"], s["h1"], now):
                self._drop(key, "ag_drop_h1_mitigated")
            else:
                self._try_place(s, bar, now)
        if need is not None:
            k = (hb, len(self.books["D1"].pois), len(self.books["H4"].pois))
            if k != self._scan_key or self._rescan:
                self._scan_key = k
                self._rescan = False
                self._scan(need, hb, bar, now)

    def _scan(self, side, hb, bar, now):
        for tf in ("D1", "H4"):
            all_fresh = self.books[tf].fresh(side)
            if any(p.born_time >= now for p in all_fresh):
                self._rescan = True
            for htf in all_fresh:
                if htf.born_time >= now:
                    continue
                if htf.id in self._map:
                    h4, h1 = self._map[htf.id]
                else:
                    h4, h1 = self._refine(htf)
                    self._map[htf.id] = (h4, h1)
                    self.counts["ag_zones_" + tf] += 1
                if h1 is None:
                    continue
                hid = h1.id
                if hid in self.slots or hid in self._spent or hid in self._closed:
                    continue
                if h4 is not None and h4.dead_time is not None and h4.dead_time <= now:
                    self._closed.add(hid)
                    self.counts["ag_drop_h4_dead"] += 1
                    continue
                if not _h1_clean(self.books["H1"], h1, now):
                    self._closed.add(hid)
                    self.counts["ag_drop_h1_mitigated"] += 1
                    continue
                slot = {"tf": tf, "htf": htf, "h4": h4, "h1": h1, "side": side,
                        "order": None, "waited": False}
                self.slots[hid] = slot
                self.counts["ag_slots"] += 1
                self._try_place(slot, bar, now)

    def _drop(self, key, counter):
        self.slots.pop(key, None)
        self._closed.add(key)
        self.counts[counter] += 1

    def _try_place(self, slot, bar, now):
        h1 = slot["h1"]
        buy = slot["side"] == "buy"
        entry = float(h1.high if buy else h1.low)
        close = float(bar.close)
        ahead = close > entry if buy else close < entry
        if not ahead:
            if not slot["waited"]:
                slot["waited"] = True
                self.counts["ag_wait_not_ahead"] += 1
            return
        atr = self.atr.value_at(h1.candle_time)
        if atr is None:
            self._drop(h1.id, "ag_no_atr")
            return
        edge = float(h1.low if buy else h1.high)
        buf = float(config.STOP_BUFFER_ATR) * float(atr)
        stop = edge - buf if buy else edge + buf
        htf = slot["htf"]
        self._n_order += 1
        order = {"id": f"AG{self._n_order}", "pullback": None,
                 "setup": f"{htf.id}>{h1.id}", "variant": "ag", "kind": "aggressive",
                 "side": slot["side"], "placed_time": now, "entry": entry,
                 "stop": float(stop), "ceiling": None, "ceiling_locked": None,
                 "end_time": None, "end_reason": None, "leg": "aggressive",
                 "fill": "limit", "rr": RR_AGG, "zone_tf": htf.tf,
                 "zone_low": float(h1.low), "zone_high": float(h1.high),
                 "bos_time": htf.born_time, "zone_touch_time": None,
                 "choch_time": None, "choch_level": None}
        slot["order"] = order
        self.aorders.append(order)
        self.counts["ag_orders"] += 1
        self._log("ag_order", now, id=order["id"], side=order["side"],
                  entry=order["entry"], stop=order["stop"], htf=htf.id, h1=h1.id)

    def _resolve(self, upto):
        todo = [b for b in self._pend if b[1] < upto]
        if not todo:
            return
        self._pend = [b for b in self._pend if b[1] >= upto]
        for b in todo:
            self._touch_bar(b, upto)

    def _touch_bar(self, b, now):
        ot, _ct, o, h, l, _c = b
        for key, s in list(self.slots.items()):
            od = s["order"]
            if od is None or ot < od["placed_time"]:
                continue
            buy = s["side"] == "buy"
            entry = od["entry"]
            if not ((l <= entry) if buy else (h >= entry)):
                continue
            stop = od["stop"]
            at_open = (o <= entry) if buy else (o >= entry)
            fill = o if at_open else entry
            del self.slots[key]
            if (buy and fill <= stop) or ((not buy) and fill >= stop):
                self._closed.add(key)
                self.counts["ag_skip_beyond_stop"] += 1
                self._log("ag_skip", now, id=od["id"], why="beyond_stop")
                continue
            risk = abs(fill - stop)
            if self.spread / risk > float(config.MAX_SPREAD_RISK_RATIO):
                self._closed.add(key)
                self.counts["ag_skip_spread"] += 1
                self._log("ag_skip", now, id=od["id"], why="spread")
                continue
            self._spent.add(key)
            self.counts["ag_zone_spent"] += 1
            if at_open:
                self.counts["ag_fill_at_open"] += 1
            self._log("ag_fill", now, id=od["id"], fill=float(fill))

    def _cancel(self, key, now, reason, permanent):
        s = self.slots.pop(key)
        od = s["order"]
        if od is not None:
            od["end_time"] = now
            od["end_reason"] = reason
            self.counts["ag_cancel_" + reason] += 1
            self._log("ag_cancel", now, id=od["id"], why=reason)
        else:
            self.counts["ag_slot_drop_" + reason] += 1
        if permanent:
            self._closed.add(key)

    def _on_h1(self, bar):
        now = bar.close_time
        self._resolve(now)
        c = float(bar.close)
        for key, s in list(self.slots.items()):
            h1 = s["h1"]
            beyond = c < h1.low if s["side"] == "buy" else c > h1.high
            if beyond:
                self._cancel(key, now, "zone_far_break", True)

    def funnel(self):
        return dict(self.counts)

    def pullback_rows(self):
        return []
