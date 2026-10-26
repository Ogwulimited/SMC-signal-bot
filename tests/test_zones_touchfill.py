import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_touch_and_fill_bullish_normal_fill2():
    opens  = [11, 10.9, 10.5, 9.9]
    highs  = [11.2, 11.0, 10.6, 10.2]
    lows   = [10.8, 10.5, 9.8, 9.7]
    closes = [11.0, 10.6, 10.0, 10.1]
    m15_df = _mk_df(opens, highs, lows, closes, freq="15min", start="2023-01-01")
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = m15_df["timestamp"].iloc[1]

    result = zones.find_touch_and_fill(m15_df, tf_m15, idm_swept_time,
                                        ob_low=9.0, ob_high=10.0, direction="bullish")

    assert result is not None
    assert result["touch_time"] == pd.Timestamp("2023-01-01 00:45:00", tz="UTC")
    assert result["touch_index"] == 2
    assert result["fill1"] == 10.0
    assert result["fill2"] == 9.9
    assert result["fill2_skipped"] is False


def test_touch_and_fill_fill2_skipped_no_next_bar():
    opens  = [10.5]
    highs  = [10.6]
    lows   = [9.8]
    closes = [10.0]
    m15_df = _mk_df(opens, highs, lows, closes, freq="15min", start="2023-01-01")
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = m15_df["timestamp"].iloc[0]

    result = zones.find_touch_and_fill(m15_df, tf_m15, idm_swept_time,
                                        ob_low=9.0, ob_high=10.0, direction="bullish")

    assert result is not None
    assert result["touch_time"] == pd.Timestamp("2023-01-01 00:15:00", tz="UTC")
    assert result["touch_index"] == 0
    assert result["fill1"] == 10.0
    assert pd.isna(result["fill2"])
    assert result["fill2_skipped"] is True


def test_touch_and_fill_returns_none_when_no_touch():
    opens  = [11, 10.9, 10.5, 9.9]
    highs  = [11.2, 11.0, 10.6, 10.2]
    lows   = [10.8, 10.5, 9.8, 9.7]
    closes = [11.0, 10.6, 10.0, 10.1]
    m15_df = _mk_df(opens, highs, lows, closes, freq="15min", start="2023-01-01")
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = m15_df["timestamp"].iloc[1]

    result = zones.find_touch_and_fill(m15_df, tf_m15, idm_swept_time,
                                        ob_low=4.0, ob_high=5.0, direction="bullish")

    assert result is None
