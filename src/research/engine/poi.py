"""Incremental POI book (order blocks) for one timeframe.

Every BOS leaves a POI and every CHoCH leaves its own. The box is the candle at
last_opposite_time, wick to wick (moved to the nearest right-colour candle if
that candle has the wrong colour). INIT makes no POI.

Side: an "up" event makes a buy POI, a "down" event makes a sell POI.
States follow body closes only:
  fresh: no body has closed inside the box
  used:  a body closed inside the box (edges included)
  dead:  a body closed beyond the far edge (buy: below the low, sell: above the high)
A dead BOS POI is a breaker. The BOS POI that dies on the same bar as a CHoCH
(the last BOS before it) is "the" breaker, the others are "stack" breakers.
A dead CHoCH-born POI is not a breaker.
"""
from bisect import bisect_left
from dataclasses import dataclass

import pandas as pd

from src import config
from src.research.engine.fvg import Candle

# Assumption 25: a buy POI needs a candle that closed down, a sell POI one that
# closed up. Set to False to use the swing candle whatever its colour.
REQUIRE_COLOUR = True
_INF = float("inf")


@dataclass
class Poi:
    id: str
    tf: str
    origin: str          # "BOS" or "CHoCH"
    side: str            # "buy" or "sell"
    low: float
    high: float
    candle_time: object  # open time of the candle the box was drawn on
    swing_time: object   # last_opposite_time of the event
    born_time: object    # close time of the event bar
    shifted: int         # candles moved for the colour rule (0 = none)
    cap_hit: bool        # no right-colour candle found; swing candle kept
    state: str = "fresh"
    used_time: object = None
    dead_time: object = None
    role: object = None  # None, "the" or "stack" (breakers only)

    @property
    def is_breaker(self):
        return self.origin == "BOS" and self.state == "dead"

    @property
    def breaker_side(self):
        return "sell" if self.side == "buy" else "buy"

    @property
    def breaker_entry(self):
        """Near edge of the breaker trade = the edge that was broken."""
        return self.low if self.side == "buy" else self.high

    @property
    def breaker_stop_edge(self):
        return self.high if self.side == "buy" else self.low


class PoiBook:
    def __init__(self, tf_name, log=None):
        self.tf_name = tf_name
        self.log = log
        self.pois = []
        self.breakers = []
        self.counts = {"born": 0, "init_skipped": 0, "no_opposite": 0,
                       "colour_shifted": 0, "cap_hit": 0,
                       "the_breaker": 0, "no_the_breaker": 0}
        self._live = []
        self._times = []
        self._bars = {}
        self._idx = {}
        self._died_now = []
        self._buy_top = -_INF
        self._sell_bot = _INF
        self._n = 0

    # ---- bars ---------------------------------------------------------
    def on_bar_close(self, bar):
        """Store the bar, then move POI states. Call BEFORE on_event for the same bar."""
        if bar.tf != self.tf_name:
            raise ValueError(f"book {self.tf_name} got a {bar.tf} bar")
        if self._times and bar.open_time <= self._times[-1]:
            raise ValueError("bars must arrive in time order")
        o = float(bar.open)
        h = float(bar.high)
        l = float(bar.low)
        c = float(bar.close)
        self._idx[bar.open_time] = len(self._times)
        self._times.append(bar.open_time)
        self._bars[bar.open_time] = (o, h, l, c, bar.close_time)
        self._died_now = []
        changes = []
        # nothing can change if the close is above every live buy box and
        # below every live sell box
        if c > self._buy_top and c < self._sell_bot:
            return changes
        removed = False
        for p in self._live:
            if p.born_time >= bar.close_time:
                continue
            if p.side == "buy":
                if c < p.low:
                    self._kill(p, bar)
                    changes.append((p, "dead"))
                    removed = True
                elif p.state == "fresh" and c <= p.high:
                    self._use(p, bar)
                    changes.append((p, "used"))
            else:
                if c > p.high:
                    self._kill(p, bar)
                    changes.append((p, "dead"))
                    removed = True
                elif p.state == "fresh" and c >= p.low:
                    self._use(p, bar)
                    changes.append((p, "used"))
        if removed:
            self._live = [p for p in self._live if p.state != "dead"]
            self._recompute_edges()
        return changes

    def _use(self, p, bar):
        p.state = "used"
        p.used_time = bar.close_time
        self._log("poi_used", bar.close_time, bar.close_time,
                  id=p.id, side=p.side, origin=p.origin)

    def _kill(self, p, bar):
        p.state = "dead"
        p.dead_time = bar.close_time
        if p.origin == "BOS":
            p.role = "stack"
            self.breakers.append(p)
        self._died_now.append(p)
        self._log("poi_dead", bar.close_time, bar.close_time,
                  id=p.id, side=p.side, origin=p.origin)

    def _recompute_edges(self):
        buys = [p.high for p in self._live if p.side == "buy"]
        sells = [p.low for p in self._live if p.side == "sell"]
        self._buy_top = max(buys) if buys else -_INF
        self._sell_bot = min(sells) if sells else _INF

    # ---- events -------------------------------------------------------
    def on_event(self, ev):
        """Create the POI for a structure event. Returns the Poi or None."""
        label = ev["label"]
        if label == "INIT":
            self.counts["init_skipped"] += 1
            return None
        opp_t = ev["last_opposite_time"]
        if pd.isna(opp_t):
            self.counts["no_opposite"] += 1
            return None
        side = "buy" if ev["direction"] == "up" else "sell"
        k, shifted, cap_hit = self._pick_candle(opp_t, side)
        t = self._times[k]
        _o, h, l, _c, _ct = self._bars[t]
        self._n += 1
        poi = Poi(id=f"{self.tf_name}-{self._n}", tf=self.tf_name, origin=label,
                  side=side, low=l, high=h, candle_time=t, swing_time=opp_t,
                  born_time=ev["time"], shifted=shifted, cap_hit=cap_hit)
        self.pois.append(poi)
        self._live.append(poi)
        if side == "buy":
            self._buy_top = max(self._buy_top, poi.high)
        else:
            self._sell_bot = min(self._sell_bot, poi.low)
        self.counts["born"] += 1
        if shifted:
            self.counts["colour_shifted"] += 1
        if cap_hit:
            self.counts["cap_hit"] += 1
        self._log("poi_born", ev["time"], ev["known_at"], id=poi.id, side=side,
                  origin=label, low=l, high=h, candle_time=t,
                  shifted=shifted, cap_hit=cap_hit)
        if label == "CHoCH":
            self._tag_the_breaker(ev)
        return poi

    def _tag_the_breaker(self, ev):
        opposite = "sell" if ev["direction"] == "up" else "buy"
        cands = [p for p in self._died_now
                 if p.origin == "BOS" and p.side == opposite
                 and p.dead_time == ev["time"]]
        if not cands:
            self.counts["no_the_breaker"] += 1
            return
        the = max(cands, key=lambda p: p.born_time)
        the.role = "the"
        self.counts["the_breaker"] += 1
        self._log("poi_the_breaker", ev["time"], ev["known_at"],
                  id=the.id, side=the.side)

    def _right_colour(self, k, side):
        o, _h, _l, c, _ct = self._bars[self._times[k]]
        return c < o if side == "buy" else c > o

    def _pick_candle(self, opp_t, side):
        if opp_t not in self._idx:
            raise ValueError(f"{self.tf_name}: swing candle {opp_t} was never delivered")
        i = self._idx[opp_t]
        if not REQUIRE_COLOUR or self._right_colour(i, side):
            return i, 0, False
        step = -1 if config.WRONG_COLOUR_SEARCH_DIRECTION == "back" else 1
        for d in range(1, int(config.OB_SEARCH_BACK_MAX) + 1):
            k = i + step * d
            if k < 0 or k >= len(self._times):
                break
            if self._right_colour(k, side):
                return k, d, False
        return i, 0, True

    # ---- queries ------------------------------------------------------
    def fresh(self, side=None):
        return [p for p in self._live
                if p.state == "fresh" and (side is None or p.side == side)]

    def usable(self, side=None, include_used=False):
        ok = ("fresh", "used") if include_used else ("fresh",)
        return [p for p in self._live
                if p.state in ok and (side is None or p.side == side)]

    def window(self, t_start, t_end):
        """Closed candles with open_time >= t_start and close_time <= t_end."""
        i = bisect_left(self._times, t_start)
        out = []
        while i < len(self._times):
            t = self._times[i]
            o, h, l, c, ct = self._bars[t]
            if ct > t_end:
                break
            out.append(Candle(t, o, h, l, c, ct))
            i += 1
        return out

    def _log(self, kind, time, known_at, **data):
        if self.log is not None:
            self.log.add(kind, time, known_at, **data)
