"""One FVG rule for the new engine (CHoCH only; the caller decides where to look).

A bullish gap: candle 3 low is above candle 1 high. A bearish gap: candle 3
high is below candle 1 low. The gap must be at least FVG_MIN_SIZE_ATR times
the ATR known when candle 3 closed.
"""
from collections import namedtuple
from dataclasses import dataclass

from src import config

Candle = namedtuple("Candle", "open_time open high low close close_time")


@dataclass(frozen=True)
class Fvg:
    direction: str      # "up" = bullish gap, "down" = bearish gap
    low: float
    high: float
    time: object        # close time of the third candle (when it became known)

    @property
    def mid(self):
        return (self.low + self.high) / 2.0


def find_fvgs(candles, atr_at, min_atr=None):
    """All gaps in a list of closed candles. atr_at(t) -> ATR known at t, or None."""
    if min_atr is None:
        min_atr = config.FVG_MIN_SIZE_ATR
    found = []
    for i in range(2, len(candles)):
        a = candles[i - 2]
        c = candles[i]
        atr = atr_at(c.close_time)
        if atr is None or not atr > 0:
            continue
        need = min_atr * atr
        if c.low > a.high and (c.low - a.high) >= need:
            found.append(Fvg("up", a.high, c.low, c.close_time))
        elif a.low > c.high and (a.low - c.high) >= need:
            found.append(Fvg("down", c.high, a.low, c.close_time))
    return found


def pick_for_breaker(fvgs, direction, box_low, box_high):
    """The gap used by the ICT Unicorn (Breaker + overlapping FVG) entry.

    direction is the trade direction: "up" = breaker buy, "down" = breaker sell.
    The gap must directly overlap [box_low, box_high]. If multiple gaps overlap
    the breaker box, the most recent one is chosen. None if there is none.
    """
    ok = [f for f in fvgs
          if f.direction == direction and f.low <= box_high and f.high >= box_low]
    return ok[-1] if ok else None
