"""
Locks the Model B lookahead-safety fix inside find_inducement()'s _model_b().

Fixture is deliberately a "lookahead trap": the only swing low that sits
between s1 (swing high) and the H1 BOS bar, by bar index, has a confirm_time
that falls AFTER armed_time (the BOS bar's close time). Before the fix,
_model_b() selected this swing anyway (lookahead bias -- using information
not yet knowable at armed_time). After the fix, the confirm_time <= armed_time
filter excludes it, so no valid IDM remains and find_inducement() returns None.

This test independently re-derives the swing values and armed_time from the
raw fixture (not from zones.py internals) to prove the trap is genuine, then
asserts find_inducement() refuses it. If the confirm_time filter is ever
removed or weakened, this test will start failing (result would resolve to
model B with idm_price == 2.0 instead of None).
"""

import pandas as pd
import pytest
from conftest import _mk_df
from src.research import zones
from src.research import primitives


def _build_h1():
    n = 30
    opens  = [1.0 + i * 0.1 for i in range(20)]
    highs  = [o + 0.15 for o in opens]
    lows   = [o - 0.05 for o in opens]
    closes = [o + 0.08 for o in opens]

    opens.append(3.00);  highs.append(5.00);  lows.append(2.90);  closes.append(3.10)
    opens.append(3.10);  highs.append(3.20);  lows.append(2.80);  closes.append(2.85)
    opens.append(2.85);  highs.append(2.90);  lows.append(2.70);  closes.append(2.75)
    opens.append(2.75);  highs.append(2.85);  lows.append(2.65);  closes.append(2.80)
    opens.append(2.80);  highs.append(2.82);  lows.append(2.00);  closes.append(2.50)
    opens.append(2.50);  highs.append(5.50);  lows.append(2.45);  closes.append(5.20)
    opens.append(5.20);  highs.append(5.30);  lows.append(5.00);  closes.append(5.10)
    for i in range(3):
        opens.append(5.10 + i*0.1);  highs.append(5.25 + i*0.1)
        lows.append(5.00 + i*0.1);   closes.append(5.15 + i*0.1)

    return _mk_df(opens, highs, lows, closes, freq="1h", start="2023-03-01")


def _build_m15_empty():
    n = 50
    flat = 3.0
    opens  = [flat] * n
    highs  = [flat + 0.001] * n
    lows   = [flat - 0.001] * n
    closes = [flat] * n
    return _mk_df(opens, highs, lows, closes, freq="15min", start="2023-03-01")


def test_model_b_lookahead_rejects_unconfirmed_idm():
    h1_df = _build_h1()
    m15_df = _build_m15_empty()
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    choch_time = h1_df["timestamp"].iloc[19] + tf_h1
    l_base_time = h1_df["timestamp"].iloc[15]
    ob_low, ob_high = 2.00, 2.50

    # Independently verify the fixture's swing structure -- not via
    # find_inducement's internal path -- to prove the trap is genuine.
    swings = primitives.find_swings(h1_df, 2, tf_h1)
    highs = swings[swings["kind"] == "high"].reset_index(drop=True)
    lows = swings[swings["kind"] == "low"].reset_index(drop=True)

    assert len(highs) == 2
    assert highs.loc[0, "index"] == 20
    assert highs.loc[0, "price"] == pytest.approx(5.0)
    assert highs.loc[0, "confirm_time"] == pd.Timestamp("2023-03-01 23:00:00", tz="UTC")

    assert len(lows) == 1
    assert lows.loc[0, "index"] == 24
    assert lows.loc[0, "price"] == pytest.approx(2.0)
    idm_confirm_time = lows.loc[0, "confirm_time"]
    assert idm_confirm_time == pd.Timestamp("2023-03-02 03:00:00", tz="UTC")

    # BOS bar: first H1 close after s1's confirm_time exceeding s1's price (5.0).
    # Verified directly against raw fixture closes, independent of zones.py.
    assert h1_df.loc[23, "close"] == pytest.approx(2.80)
    assert h1_df.loc[24, "close"] == pytest.approx(2.50)
    assert h1_df.loc[25, "close"] == pytest.approx(5.20)
    bos_bar_time = h1_df.loc[25, "timestamp"]
    armed_time = bos_bar_time + tf_h1
    assert armed_time == pd.Timestamp("2023-03-02 02:00:00", tz="UTC")

    # The trap: IDM candidate's confirm_time is strictly AFTER armed_time.
    assert idm_confirm_time > armed_time

    # find_inducement() must refuse this candidate rather than use it.
    result = zones.find_inducement(
        h1_df, m15_df, tf_h1, tf_m15,
        choch_time=choch_time,
        l_base_time=l_base_time,
        ob_low=ob_low, ob_high=ob_high,
        direction="bullish",
    )
    assert result is None
