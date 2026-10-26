import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_inducement_model_b_bearish():
    h1_opens  = [10.7, 10.7, 10.7, 10.3, 7.7, 10.0, 10.8, 12.7, 11.3, 10.3, 9.3, 8.3, 6.7, 5.7, 4.7]
    h1_highs  = [11.0, 11.0, 11.0, 10.5, 8.0, 10.5, 11.0, 13.0, 11.5, 10.5, 9.5, 8.5, 7.0, 6.0, 5.0]
    h1_lows   = [10.0, 10.0, 10.0, 9.5, 7.0, 9.5, 10.0, 11.0, 10.5, 9.5, 8.5, 7.5, 6.0, 5.0, 4.0]
    h1_closes = [10.4, 10.3, 10.4, 9.8, 6.5, 9.7, 10.5, 12.2, 10.7, 9.6, 8.6, 7.6, 5.5, 4.5, 3.5]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")

    m15_opens  = [10.5, 10.2, 10.1, 11.0, 12.0, 12.2, 13.5, 13.2, 13.0, 12.8]
    m15_highs  = [11.0, 10.5, 11.0, 13.2, 12.5, 13.8, 14.0, 13.5, 13.2, 13.0]
    m15_lows   = [10.0, 9.5, 10.0, 10.8, 11.8, 12.0, 13.0, 12.8, 12.5, 12.4]
    m15_closes = [10.2, 10.1, 10.9, 12.0, 12.2, 13.5, 13.2, 13.0, 12.8, 12.6]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 12:30")

    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)
    choch_time = h1_df["timestamp"].iloc[0]
    l_base_time = h1_df["timestamp"].iloc[7]

    result = zones.find_inducement(h1_df, m15_df, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low=13.5, ob_high=14.5, direction="bearish")
    print("\n--- INDUCEMENT BEARISH MODEL B ---")
    print(result)
    assert True
