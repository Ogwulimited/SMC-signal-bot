import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_inducement_bearish_same_bar_ambiguous():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    h1 = _mk_df(
        opens=[10.0, 10.0, 9.8, 9.5, 9.8, 10.5, 10.0],
        highs=[10.2, 10.1, 9.9, 10.0, 10.8, 10.6, 10.1],
        lows=[9.8, 9.6, 9.0, 9.4, 9.7, 9.9, 8.5],
        closes=[10.0, 9.8, 9.5, 9.8, 10.5, 10.0, 8.7],
        freq="1h", start="2023-01-01 00:00:00",
    )

    m15 = _mk_df(
        opens=[10.0, 10.2, 10.6],
        highs=[10.5, 10.9, 10.7],
        lows=[9.8, 10.0, 10.3],
        closes=[10.2, 10.6, 10.4],
        freq="15min", start="2023-01-01 07:00:00",
    )

    choch_time = pd.Timestamp("2023-01-01 01:00:00", tz="UTC")
    l_base_time = pd.Timestamp("2022-12-31 23:00:00", tz="UTC")
    ob_low, ob_high = 10.5, 11.0

    result = zones.find_inducement(h1, m15, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low, ob_high, direction="bearish")
    print("\n--- INDUCEMENT BEARISH SAME_BAR_AMBIGUOUS ---")
    print(result)
    assert True


def test_diagnostic_print_inducement_bearish_invalid_h1_close_through():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    h1 = _mk_df(
        opens=[10.0, 10.0, 9.8, 9.5, 9.8, 10.5, 10.0, 8.7, 8.5, 10.0],
        highs=[10.2, 10.1, 9.9, 10.0, 10.8, 10.6, 10.1, 8.9, 8.7, 11.5],
        lows=[9.8, 9.6, 9.0, 9.4, 9.7, 9.9, 8.5, 8.3, 8.1, 9.9],
        closes=[10.0, 9.8, 9.5, 9.8, 10.5, 10.0, 8.7, 8.5, 8.3, 11.2],
        freq="1h", start="2023-01-01 00:00:00",
    )

    m15_opens, m15_highs, m15_lows, m15_closes = [], [], [], []
    base_vals = [
        (10.0, 10.5, 9.8, 10.2), (10.2, 10.9, 10.0, 10.5), (10.5, 10.6, 10.2, 10.4),
        (10.4, 10.6, 10.1, 10.3), (10.3, 10.5, 10.0, 10.2), (10.2, 10.4, 9.9, 10.1),
        (10.1, 10.3, 9.8, 10.0), (10.0, 10.2, 9.7, 9.9), (9.9, 10.1, 9.6, 9.8),
        (9.8, 10.0, 9.5, 9.7), (9.7, 9.9, 9.4, 9.6), (9.6, 9.8, 9.3, 9.5),
        (9.5, 9.7, 9.2, 9.4), (9.4, 11.2, 9.1, 10.0), (10.0, 10.1, 9.8, 9.9),
        (9.9, 10.0, 9.7, 9.8),
    ]
    for o, h, l, c in base_vals:
        m15_opens.append(o); m15_highs.append(h); m15_lows.append(l); m15_closes.append(c)

    m15 = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes,
                 freq="15min", start="2023-01-01 07:00:00")

    choch_time = pd.Timestamp("2023-01-01 01:00:00", tz="UTC")
    l_base_time = pd.Timestamp("2022-12-31 23:00:00", tz="UTC")
    ob_low, ob_high = 11.0, 11.1

    result = zones.find_inducement(h1, m15, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low, ob_high, direction="bearish")
    print("\n--- INDUCEMENT BEARISH INVALID_H1_CLOSE_THROUGH ---")
    print(result)
    assert True
