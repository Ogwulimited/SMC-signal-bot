"""Incremental major-structure BOS/CHoCH engine.

Gives the same events as src/research/structure_major.py (the reference), but
bar by bar through on_bar_close(). Order inside one bar:
  1. swings detected on EARLIER bars become usable,
  2. the bar's close is tested against the standing swings,
  3. the bar joins the swing window; a swing found now is usable from the
     next bar on (it is confirmed at this bar's close).
"""
from collections import deque

import numpy as np
import pandas as pd

from src import config
from src.research.lookahead_guard import LookaheadError


class IncrementalStructure:
    def __init__(self, n, tf, tf_name):
        if n < 1:
            raise ValueError("swing N must be at least 1")
        self.n = int(n)
        self.tf = pd.Timedelta(tf)
        self.tf_name = tf_name
        self._win = deque(maxlen=2 * self.n + 1)
        self._pending = []
        self._h_p, self._h_t, self._h_c = [], [], []
        self._l_p, self._l_t, self._l_c = [], [], []
        self._hi_max = None
        self._lo_min = None
        self._trend = "none"
        self._last_close = None

    def on_bar_close(self, bar):
        if bar.tf != self.tf_name:
            raise ValueError(f"engine {self.tf_name} got a {bar.tf} bar")
        t = bar.open_time
        if bar.close_time != t + self.tf:
            raise ValueError("bar length does not match the engine timeframe")
        if self._last_close is not None and bar.close_time <= self._last_close:
            raise ValueError("bars must arrive in time order")
        c = float(bar.close)

        # 1. swings found on earlier bars become usable
        for kind, p, ts, conf in self._pending:
            if kind == "high":
                self._h_p.append(p)
                self._h_t.append(ts)
                self._h_c.append(conf)
                if self._hi_max is None or p > self._hi_max:
                    self._hi_max = p
            else:
                self._l_p.append(p)
                self._l_t.append(ts)
                self._l_c.append(conf)
                if self._lo_min is None or p < self._lo_min:
                    self._lo_min = p
        self._pending = []

        # 2. break test
        event = None
        if self._hi_max is not None and c > self._hi_max:
            event = self._break_up(bar, c)
        elif self._lo_min is not None and c < self._lo_min:
            event = self._break_down(bar, c)

        # 3. this bar joins the window; a swing found now waits for the next bar
        self._win.append((t, float(bar.high), float(bar.low)))
        if len(self._win) == 2 * self.n + 1:
            self._find_swing(bar.close_time)
        self._last_close = bar.close_time
        return event

    def _find_swing(self, confirm_time):
        n = self.n
        highs = [x[1] for x in self._win]
        lows = [x[2] for x in self._win]
        ts = self._win[n][0]
        ch, cl = highs[n], lows[n]
        if ch == max(highs) and ch > max(highs[:n]) and ch > max(highs[n + 1:]):
            self._pending.append(("high", ch, ts, confirm_time))
        if cl == min(lows) and cl < min(lows[:n]) and cl < min(lows[n + 1:]):
            self._pending.append(("low", cl, ts, confirm_time))

    def _break_up(self, bar, c):
        ih = self._h_p.index(self._hi_max)          # earlier swing wins on equal price
        bt, bconf, bp = self._h_t[ih], self._h_c[ih], self._hi_max
        label = "INIT" if self._trend == "none" else ("BOS" if self._trend == "up" else "CHoCH")
        if label == "BOS":
            keep = [k for k in range(len(self._l_t)) if self._l_t[k] >= bt]
            self._l_p = [self._l_p[k] for k in keep]
            self._l_t = [self._l_t[k] for k in keep]
            self._l_c = [self._l_c[k] for k in keep]
            self._lo_min = min(self._l_p) if self._l_p else None
        if self._l_p:
            il = self._l_p.index(self._lo_min)
            opp_t, opp_p, opp_c = self._l_t[il], self._l_p[il], self._l_c[il]
        else:
            opp_t, opp_p, opp_c = pd.NaT, np.nan, None
        self._h_p, self._h_t, self._h_c, self._hi_max = [], [], [], None
        self._trend = "up"
        return self._event(bar, label, "up", c, bt, bp, opp_t, opp_p, [bconf, opp_c])

    def _break_down(self, bar, c):
        il = self._l_p.index(self._lo_min)
        bt, bconf, bp = self._l_t[il], self._l_c[il], self._lo_min
        label = "INIT" if self._trend == "none" else ("BOS" if self._trend == "down" else "CHoCH")
        if label == "BOS":
            keep = [k for k in range(len(self._h_t)) if self._h_t[k] >= bt]
            self._h_p = [self._h_p[k] for k in keep]
            self._h_t = [self._h_t[k] for k in keep]
            self._h_c = [self._h_c[k] for k in keep]
            self._hi_max = max(self._h_p) if self._h_p else None
        if self._h_p:
            ih = self._h_p.index(self._hi_max)
            opp_t, opp_p, opp_c = self._h_t[ih], self._h_p[ih], self._h_c[ih]
        else:
            opp_t, opp_p, opp_c = pd.NaT, np.nan, None
        self._l_p, self._l_t, self._l_c, self._lo_min = [], [], [], None
        self._trend = "down"
        return self._event(bar, label, "down", c, bt, bp, opp_t, opp_p, [bconf, opp_c])

    def _event(self, bar, label, direction, c, bt, bp, opp_t, opp_p, confs):
        known_at = max([bar.close_time] + [x for x in confs if x is not None])
        if known_at > bar.close_time:
            raise LookaheadError("structure event used information after its own bar close")
        return {
            "tf": self.tf_name, "label": label, "direction": direction,
            "time": bar.close_time, "close": c,
            "broken_swing_time": bt, "broken_swing_price": bp,
            "last_opposite_time": opp_t, "last_opposite_price": opp_p,
            "known_at": known_at,
        }


class StructureRecorder:
    """Strategy that runs M15, H4 and D1 structure and logs every event."""

    def __init__(self, log):
        self.log = log
        self.events = []
        self.engines = {
            "M15": IncrementalStructure(config.LTF_SWING_N, pd.Timedelta(minutes=15), "M15"),
            "H4": IncrementalStructure(config.H4_SWING_N, pd.Timedelta(hours=4), "H4"),
            "D1": IncrementalStructure(config.D1_SWING_N, pd.Timedelta(days=1), "D1"),
        }

    def on_bar_close(self, bar, feed):
        eng = self.engines.get(bar.tf)
        if eng is None:
            return
        ev = eng.on_bar_close(bar)
        if ev is None:
            return
        self.events.append(ev)
        self.log.add("structure_" + bar.tf, ev["time"], ev["known_at"],
                     label=ev["label"], direction=ev["direction"], close=ev["close"],
                     broken_swing_time=ev["broken_swing_time"],
                     broken_swing_price=ev["broken_swing_price"],
                     last_opposite_time=ev["last_opposite_time"],
                     last_opposite_price=ev["last_opposite_price"])


def run_structure_pipeline(m15):
    """Full Batch-1 pipeline: feed -> structure engines -> decisions."""
    from src.research.lookahead_guard import DataFeed, DecisionLog
    log = DecisionLog()
    DataFeed(m15, htf=("H4", "D1")).run(StructureRecorder(log))
    return log.items
