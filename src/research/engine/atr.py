"""Incremental ATR on closed bars: simple average of true range.

Feed it H1 bars as they close. value_at(t) gives the ATR built only from H1
bars that closed at or before t. For a box candle opening at t this is the
last H1 bar closed before it, which is the "shifted one bar" rule.
"""
from bisect import bisect_right
from collections import deque


class ATRTracker:
    def __init__(self, period=14):
        if period < 1:
            raise ValueError("ATR period must be at least 1")
        self.period = int(period)
        self._trs = deque(maxlen=self.period)
        self._prev_close = None
        self._close_times = []
        self._values = []

    def on_bar_close(self, bar):
        if self._close_times and bar.close_time <= self._close_times[-1]:
            raise ValueError("bars must arrive in time order")
        h = float(bar.high)
        l = float(bar.low)
        pc = self._prev_close
        if pc is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - pc), abs(l - pc))
        self._trs.append(tr)
        self._prev_close = float(bar.close)
        if len(self._trs) == self.period:
            value = sum(self._trs) / self.period
        else:
            value = None
        self._close_times.append(bar.close_time)
        self._values.append(value)

    def value_at(self, t):
        k = bisect_right(self._close_times, t) - 1
        if k < 0:
            return None
        return self._values[k]
