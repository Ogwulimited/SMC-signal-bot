import math

import numpy as np
import pandas as pd

from src.research.engine.atr import ATRTracker
from src.research.engine.fvg import Candle, Fvg, find_fvgs, pick_for_breaker
from src.research.lookahead_guard import Bar

T0 = pd.Timestamp("2021-03-01 00:00", tz="UTC")
M15 = pd.Timedelta(minutes=15)


def cd(i, o, h, l, c):
    t = T0 + i * M15
    return Candle(t, o, h, l, c, t + M15)


def one(_t):
    return 1.0


def test_bullish_gap_is_found_with_its_midpoint():
    cs = [cd(0, 9.5, 10.0, 9.0, 9.8), cd(1, 9.8, 11.0, 9.7, 10.9), cd(2, 10.9, 11.5, 10.5, 11.2)]
    got = find_fvgs(cs, one)
    assert got == [Fvg("up", 10.0, 10.5, cs[2].close_time)]
    assert got[0].mid == 10.25
    print("FVG: bullish gap 10.0-10.5 found, midpoint 10.25")


def test_gap_below_the_size_threshold_is_ignored():
    cs = [cd(0, 9.5, 10.0, 9.0, 9.8), cd(1, 9.8, 11.0, 9.7, 10.9), cd(2, 10.9, 11.5, 10.04, 11.2)]
    assert find_fvgs(cs, one) == []          # gap 0.04 < 0.05 x ATR(1.0)


def test_bearish_gap_is_found():
    cs = [cd(0, 10.5, 11.0, 10.0, 10.2), cd(1, 10.2, 10.3, 9.0, 9.1), cd(2, 9.1, 9.5, 8.5, 8.8)]
    assert find_fvgs(cs, one) == [Fvg("down", 9.5, 10.0, cs[2].close_time)]


def test_no_atr_means_no_gap():
    cs = [cd(0, 9.5, 10.0, 9.0, 9.8), cd(1, 9.8, 11.0, 9.7, 10.9), cd(2, 10.9, 11.5, 10.5, 11.2)]
    assert find_fvgs(cs, lambda t: None) == []


def test_pick_for_breaker_buy_and_sell():
    t = T0
    ups = [Fvg("up", 10.0, 10.5, t), Fvg("up", 11.0, 11.6, t), Fvg("up", 12.0, 12.5, t),
           Fvg("down", 11.1, 11.3, t)]
    # box 11.2 - 12.2: the 12.0-12.5 gap pokes above the box top, so it is out
    assert pick_for_breaker(ups, "up", 11.2, 12.2) == ups[1]
    assert pick_for_breaker([ups[2]], "up", 11.2, 12.2) is None
    downs = [Fvg("down", 12.0, 12.4, t), Fvg("down", 10.5, 10.9, t),
             Fvg("down", 11.5, 11.9, t), Fvg("up", 11.6, 11.8, t)]
    # box 11.0 - 12.0: the 10.5-10.9 gap lies below the box bottom, so it is out
    assert pick_for_breaker(downs, "down", 11.0, 12.0) == downs[2]
    assert pick_for_breaker([downs[1]], "down", 11.0, 12.0) is None


def test_atr_tracker_matches_pandas_rolling_mean_of_true_range():
    rng = np.random.default_rng(3)
    n = 40
    close = 100 + np.cumsum(rng.normal(0, 0.3, n))
    high = close + rng.uniform(0.1, 0.5, n)
    low = close - rng.uniform(0.1, 0.5, n)
    times = [T0 + i * pd.Timedelta(hours=1) for i in range(n)]
    tracker = ATRTracker(14)
    for i in range(n):
        tracker.on_bar_close(Bar(tf="H1", open_time=times[i],
                                 close_time=times[i] + pd.Timedelta(hours=1),
                                 open=float((high[i] + low[i]) / 2), high=float(high[i]),
                                 low=float(low[i]), close=float(close[i])))
    s_close = pd.Series(close)
    s_high = pd.Series(high)
    s_low = pd.Series(low)
    pc = s_close.shift(1)
    tr = pd.concat([s_high - s_low, (s_high - pc).abs(), (s_low - pc).abs()], axis=1).max(axis=1)
    ref = tr.rolling(14).mean()
    ok = True
    for i in range(n):
        close_t = times[i] + pd.Timedelta(hours=1)
        v = tracker.value_at(close_t)
        if i < 13:
            ok = ok and v is None
        else:
            ok = ok and math.isclose(v, float(ref[i]), rel_tol=1e-9)
            assert math.isclose(tracker.value_at(close_t + pd.Timedelta(minutes=30)), float(ref[i]), rel_tol=1e-9)
    assert tracker.value_at(T0) is None
    print(f"ATR: tracker equals pandas rolling mean of true range on {n} H1 bars: {ok}")
    assert ok
