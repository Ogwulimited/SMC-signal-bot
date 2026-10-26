import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_touch_and_fill_bullish(capsys):
    opens  = [11, 10.9, 10.5, 9.9]
    highs  = [11.2, 11.0, 10.6, 10.2]
    lows   = [10.8, 10.5, 9.8, 9.7]
    closes = [11.0, 10.6, 10.0, 10.1]
    m15_df = _mk_df(opens, highs, lows, closes, freq="15min", start="2023-01-01")
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = m15_df["timestamp"].iloc[1]

    result = zones.find_touch_and_fill(m15_df, tf_m15, idm_swept_time,
                                        ob_low=9.0, ob_high=10.0, direction="bullish")
    print("\n--- TOUCH_AND_FILL (normal fill2) ---")
    print(result)
    assert True


def test_diagnostic_print_touch_and_fill_skipped(capsys):
    opens  = [10.5]
    highs  = [10.6]
    lows   = [9.8]
    closes = [10.0]
    m15_df = _mk_df(opens, highs, lows, closes, freq="15min", start="2023-01-01")
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = m15_df["timestamp"].iloc[0]

    result = zones.find_touch_and_fill(m15_df, tf_m15, idm_swept_time,
                                        ob_low=9.0, ob_high=10.0, direction="bullish")
    print("\n--- TOUCH_AND_FILL (fill2 skipped, no next bar) ---")
    print(result)
    assert True


def test_diagnostic_print_touch_and_fill_none(capsys):
    opens  = [11, 10.9, 10.5, 9.9]
    highs  = [11.2, 11.0, 10.6, 10.2]
    lows   = [10.8, 10.5, 9.8, 9.7]
    closes = [11.0, 10.6, 10.0, 10.1]
    m15_df = _mk_df(opens, highs, lows, closes, freq="15min", start="2023-01-01")
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = m15_df["timestamp"].iloc[1]

    result = zones.find_touch_and_fill(m15_df, tf_m15, idm_swept_time,
                                        ob_low=4.0, ob_high=5.0, direction="bullish")
    print("\n--- TOUCH_AND_FILL (expect None) ---")
    print(result)
    assert True
