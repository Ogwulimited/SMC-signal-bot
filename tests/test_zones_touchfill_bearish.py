import numpy as np
import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_touch_and_fill_bearish_normal():
    m15 = _mk_df(
        opens=[9.0, 9.3, 9.8, 10.5, 10.6],
        highs=[9.4, 9.5, 10.2, 10.6, 10.8],
        lows=[8.9, 9.2, 9.7, 10.3, 10.4],
        closes=[9.3, 9.4, 10.0, 10.5, 10.7],
        freq="15min", start="2023-01-01 00:00:00",
    )
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = pd.Timestamp("2023-01-01 00:20:00", tz="UTC")

    result = zones.find_touch_and_fill(m15, tf_m15, idm_swept_time,
                                        ob_low=10.0, ob_high=11.0, direction="bearish")
    print("\n--- TOUCH_AND_FILL BEARISH NORMAL ---")
    print(result)
    assert True


def test_diagnostic_print_touch_and_fill_bearish_skipped_no_next_bar():
    m15 = _mk_df(
        opens=[9.0, 9.2, 9.4],
        highs=[9.3, 9.5, 10.2],
        lows=[8.8, 9.0, 9.3],
        closes=[9.2, 9.4, 10.0],
        freq="15min", start="2023-01-01 00:00:00",
    )
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = pd.Timestamp("2022-12-31 23:50:00", tz="UTC")

    result = zones.find_touch_and_fill(m15, tf_m15, idm_swept_time,
                                        ob_low=10.0, ob_high=11.0, direction="bearish")
    print("\n--- TOUCH_AND_FILL BEARISH SKIPPED (no next bar) ---")
    print(result)
    assert True


def test_diagnostic_print_touch_and_fill_bearish_no_touch():
    m15 = _mk_df(
        opens=[9.0, 9.1, 9.2],
        highs=[9.3, 9.4, 9.5],
        lows=[8.8, 8.9, 9.0],
        closes=[9.1, 9.2, 9.3],
        freq="15min", start="2023-01-01 00:00:00",
    )
    tf_m15 = pd.Timedelta(minutes=15)
    idm_swept_time = pd.Timestamp("2022-12-31 23:50:00", tz="UTC")

    result = zones.find_touch_and_fill(m15, tf_m15, idm_swept_time,
                                        ob_low=10.0, ob_high=11.0, direction="bearish")
    print("\n--- TOUCH_AND_FILL BEARISH NO TOUCH (expect None) ---")
    print(result)
    assert True
