import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_inducement_model_a_bearish():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    h1 = _mk_df(
        opens=[10, 10, 10, 10],
        highs=[10.5, 10.5, 10.5, 10.5],
        lows=[9.5, 9.5, 9.5, 9.5],
        closes=[10, 10, 10, 10],
        freq="1h", start="2023-01-01 00:00:00",
    )

    # M15 bars: need swing low (l_base area), swing high (IDM for bearish),
    # then a close below the swing low to confirm "BOS" on M15, before choch_time.
    m15 = _mk_df(
        opens=[10.0, 9.8, 9.6, 9.9, 10.1, 9.7, 9.4, 9.2],
        highs=[10.1, 9.9, 9.7, 10.2, 10.3, 9.8, 9.5, 9.3],
        lows=[9.9, 9.7, 9.5, 9.8, 10.0, 9.6, 9.3, 9.1],
        closes=[10.0, 9.8, 9.6, 10.1, 10.2, 9.7, 9.4, 9.2],
        freq="15min", start="2023-01-01 00:00:00",
    )

    l_base_time = pd.Timestamp("2023-01-01 00:30:00", tz="UTC")
    choch_time = pd.Timestamp("2023-01-01 02:15:00", tz="UTC")
    ob_low, ob_high = 9.0, 9.5

    result = zones.find_inducement(h1, m15, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low, ob_high, direction="bearish")
    print("\n--- INDUCEMENT MODEL A BEARISH ---")
    print(result)
    assert True
