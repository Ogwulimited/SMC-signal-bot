"""Bias state machine for one timeframe (D1 or H4), fed with structure events.

First read: BIAS_FIRST_READ_SWINGS counted swings in one direction.
  Counted: a BOS, or a CHoCH that closes beyond the previous CHoCH's high
  (low for a down move). INIT is not counted. A plain CHoCH neither counts nor
  resets. A counted swing in the other direction resets the count.
After that: a CHoCH against the bias puts it on warning (the CHoCH high is the
  warning level). A BOS in the new direction while on warning flips the bias.
  A close back beyond the warning level clears the warning, bias unchanged.

htf_bias() combines the timeframes. config.BIAS_TIMEFRAMES = "both" (default):
D1 and H4 must agree. "h4": H4 alone decides.
"""
import math

from src import config

_OPP = {"up": "down", "down": "up"}


def _level(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(v) else v


def _beyond(close, level, direction):
    if level is None:
        return False
    return close > level if direction == "up" else close < level


class BiasTracker:
    def __init__(self, tf_name, log=None, first_read=None):
        self.tf_name = tf_name
        self.log = log
        self.first_read = int(config.BIAS_FIRST_READ_SWINGS if first_read is None
                              else first_read)
        self.bias = "none"          # "none", "bull" or "bear"
        self.warning = False
        self.history = []
        self.anomalies = 0
        self._warn_level = None
        self._count_dir = None
        self._count = 0
        self._last_choch = None     # (direction, level)

    @property
    def state(self):
        if self.bias == "none":
            return "none"
        name = "bullish" if self.bias == "bull" else "bearish"
        return name + (" (on warning)" if self.warning else "")

    def on_event(self, ev):
        before = (self.bias, self.warning)
        if self.bias == "none":
            reason = self._first_read(ev)
        else:
            reason = self._established(ev)
        if (self.bias, self.warning) == before:
            return None
        change = {"time": ev["time"], "known_at": ev["known_at"],
                  "bias": self.bias, "warning": self.warning, "reason": reason}
        self.history.append(change)
        if self.log is not None:
            self.log.add("bias_" + self.tf_name, ev["time"], ev["known_at"],
                         bias=self.bias, warning=self.warning, reason=reason)
        return change

    def _first_read(self, ev):
        label = ev["label"]
        d = ev["direction"]
        if label == "INIT":
            return None
        counted = False
        if label == "BOS":
            counted = True
        elif label == "CHoCH":
            last = self._last_choch
            if last is not None and last[0] == _OPP[d] and _beyond(float(ev["close"]), last[1], d):
                counted = True
            self._last_choch = (d, _level(ev["last_opposite_price"]))
        if not counted:
            return None
        if self._count_dir == d:
            self._count += 1
        else:
            self._count_dir = d
            self._count = 1
        if self._count >= self.first_read:
            self.bias = "bull" if d == "up" else "bear"
            self._count = 0
            self._count_dir = None
            return "first_read"
        return None

    def _established(self, ev):
        want = "up" if self.bias == "bull" else "down"
        d = ev["direction"]
        label = ev["label"]
        if d == want:
            if self.warning and _beyond(float(ev["close"]), self._warn_level, want):
                self.warning = False
                self._warn_level = None
                return "warning_cleared"
            return None
        if label == "CHoCH":
            self.warning = True
            self._warn_level = _level(ev["last_opposite_price"])
            return "warning"
        if label == "BOS":
            if self.warning:
                self.bias = "bear" if self.bias == "bull" else "bull"
                self.warning = False
                self._warn_level = None
                return "flip"
            self.anomalies += 1
        return None


def htf_bias(d1, h4):
    """'bull' or 'bear' or None (nothing trades).

    "both" (default): D1 and H4 must agree.
    "h4": H4 alone decides (D1 is ignored).
    """
    if getattr(config, "BIAS_TIMEFRAMES", "both") == "h4":
        return h4.bias if h4.bias != "none" else None
    if d1.bias != "none" and d1.bias == h4.bias:
        return d1.bias
    return None
