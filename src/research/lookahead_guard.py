"""Lookahead guard: the bar feed, the error type and the decision log.

The feed is the ONLY place that holds the full price table. Strategy code gets
one closed bar at a time through on_bar_close(bar, feed) and can read only
bars that were already delivered.

Delivery order at the same instant: D1, H4, H1, then M15.
An H1/H4/D1 bar is delivered when its last M15 bar has closed. If that last
M15 slot is missing in the data, the bar is delivered together with the first
M15 bar of a later bin (late, never early).
H1/H4/D1 bars are built from M15 on the New York 17:00 clock, the same way as
primitives.resample_to_tf.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

TF_MINUTES = {"M15": 15, "H1": 60, "H4": 240, "D1": 1440}
_NY = "America/New_York"
_ORIGIN = pd.Timestamp("2020-01-01 17:00:00")
_NS_PER_MIN = 60 * 1_000_000_000


class LookaheadError(Exception):
    """Raised when code touches information from the future."""


@dataclass(frozen=True, slots=True)
class Bar:
    tf: str
    open_time: pd.Timestamp
    close_time: pd.Timestamp
    open: float
    high: float
    low: float
    close: float


def _norm(v):
    """Make a value comparable (NaN == NaN, Timestamps as integers)."""
    if isinstance(v, pd.Timestamp):
        return ("ts", v.value)
    if v is pd.NaT:
        return ("nat",)
    if isinstance(v, (float, np.floating)):
        return ("nan",) if v != v else float(v)
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    return v


@dataclass(frozen=True)
class Decision:
    kind: str
    time: pd.Timestamp
    known_at: pd.Timestamp
    data: tuple

    def key(self):
        return (self.kind, self.time.value, self.known_at.value,
                tuple((k, _norm(v)) for k, v in self.data))


class DecisionLog:
    """Every decision stores known_at, the latest bar close it used.
    known_at later than the decision time is a lookahead and raises."""

    def __init__(self):
        self.items = []

    def add(self, kind, time, known_at, **data):
        if known_at is None or known_at is pd.NaT:
            raise LookaheadError(f"{kind}: known_at is missing")
        if known_at > time:
            raise LookaheadError(
                f"{kind}: known_at {known_at} is later than decision time {time}")
        self.items.append(Decision(kind, time, known_at, tuple(sorted(data.items()))))


def _ns_utc(index):
    return index.tz_convert("UTC").values.astype("datetime64[ns]").astype("int64")


def _bin_starts(ts, minutes):
    """Start (UTC ns) of the New York 17:00-anchored bin of every M15 bar.
    Bins that start in a DST-ambiguous or missing hour are invalid (-> valid=False),
    which is what resample_to_tf does (it drops them)."""
    naive = ts.tz_convert(_NY).tz_localize(None)
    step = pd.Timedelta(minutes=minutes)
    k = np.asarray((naive - _ORIGIN) // step, dtype="int64")
    start_naive = _ORIGIN + pd.to_timedelta(k * minutes, unit="min")
    start_local = pd.DatetimeIndex(start_naive).tz_localize(
        _NY, ambiguous="NaT", nonexistent="NaT")
    valid = ~np.asarray(start_local.isna())
    start_ns = _ns_utc(start_local.tz_convert("UTC"))
    return start_ns, valid


class DataFeed:
    def __init__(self, m15, htf=("H1", "H4", "D1")):
        for col in ("timestamp", "open", "high", "low", "close"):
            if col not in m15.columns:
                raise ValueError(f"M15 frame needs column '{col}'")
        ts = pd.DatetimeIndex(m15["timestamp"])
        if ts.tz is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        if not ts.is_monotonic_increasing or not ts.is_unique:
            raise ValueError("M15 timestamps must be strictly increasing")
        for name in htf:
            if name == "M15" or name not in TF_MINUTES:
                raise ValueError(f"unsupported higher timeframe: {name}")
        self._n = len(ts)
        self._open_ns = _ns_utc(ts)
        self._o = m15["open"].to_numpy(dtype="float64")
        self._h = m15["high"].to_numpy(dtype="float64")
        self._l = m15["low"].to_numpy(dtype="float64")
        self._c = m15["close"].to_numpy(dtype="float64")
        self._htf = sorted(htf, key=lambda k: -TF_MINUTES[k])
        self._bins = {name: _bin_starts(ts, TF_MINUTES[name]) for name in self._htf}
        self._acc = {name: None for name in self._htf}
        self._delivered = {"M15": []}
        for name in self._htf:
            self._delivered[name] = []
        self.now = None

    # ---- what strategy code may read -------------------------------------
    def count(self, tf):
        """How many bars of this timeframe have been delivered so far."""
        return len(self._delivered[tf])

    def bar(self, tf, index):
        """A delivered bar by position (negative counts from the newest).
        Asking for a bar that has not closed yet raises LookaheadError."""
        if self.now is None:
            raise LookaheadError("feed has not started")
        lst = self._delivered[tf]
        if index >= len(lst) or index < -len(lst):
            raise LookaheadError(f"{tf} bar {index} has not closed yet (now={self.now})")
        b = lst[index]
        if b.close_time > self.now:
            raise LookaheadError(f"{tf} bar closes {b.close_time} after now={self.now}")
        return b

    def last(self, tf, k=1):
        """The last k delivered bars (oldest first)."""
        return list(self._delivered[tf][-k:])

    # ---- the clock -------------------------------------------------------
    def run(self, strategy):
        step15 = pd.Timedelta(minutes=15)
        for i in range(self._n):
            open_ns = int(self._open_ns[i])
            open_time = pd.Timestamp(open_ns, unit="ns", tz="UTC")
            bar15 = Bar("M15", open_time, open_time + step15,
                        float(self._o[i]), float(self._h[i]),
                        float(self._l[i]), float(self._c[i]))
            self.now = bar15.close_time
            for hb in self._advance_htf(i, open_ns + 15 * _NS_PER_MIN):
                self._deliver(hb)
                strategy.on_bar_close(hb, self)
            self._deliver(bar15)
            strategy.on_bar_close(bar15, self)

    def _deliver(self, bar):
        if bar.close_time > self.now:
            raise LookaheadError(f"{bar.tf} bar delivered before its close time")
        self._delivered[bar.tf].append(bar)

    def _finish(self, name, acc, now_ns):
        minutes = TF_MINUTES[name]
        end_ns = acc[0] + minutes * _NS_PER_MIN
        if end_ns > now_ns:
            raise LookaheadError(f"{name} bar would be delivered before it closes")
        open_time = pd.Timestamp(acc[0], unit="ns", tz="UTC")
        bar = Bar(name, open_time, open_time + pd.Timedelta(minutes=minutes),
                  acc[1], acc[2], acc[3], acc[4])
        return end_ns, bar

    def _advance_htf(self, i, close_ns):
        ready = []
        o, h, l, c = float(self._o[i]), float(self._h[i]), float(self._l[i]), float(self._c[i])
        for name in self._htf:
            starts, valid = self._bins[name]
            start = int(starts[i]) if valid[i] else -1
            acc = self._acc[name]
            if acc is not None and acc[0] != start:
                # a later bin has started: the old bin is finished
                ready.append(self._finish(name, acc, close_ns))
                acc = None
            if start != -1:
                if acc is None:
                    acc = [start, o, h, l, c]
                else:
                    if h > acc[2]:
                        acc[2] = h
                    if l < acc[3]:
                        acc[3] = l
                    acc[4] = c
                if close_ns >= start + TF_MINUTES[name] * _NS_PER_MIN:
                    ready.append(self._finish(name, acc, close_ns))
                    acc = None
            self._acc[name] = acc
        ready.sort(key=lambda x: (x[0], -TF_MINUTES[x[1].tf]))
        return [b for _, b in ready]
