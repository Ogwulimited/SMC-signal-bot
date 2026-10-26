import pandas as pd
from src import config
from src.research import primitives
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_inducement_model_b(capsys):
    h1_opens  = [9.3, 9.3, 9.3, 9.7, 12.3, 10.0, 9.2, 7.3, 8.7, 9.7, 10.7, 11.7, 13.3, 14.3, 15.3]
    h1_highs  = [10, 10, 10, 11, 14, 11, 10, 9, 10, 11, 12, 13, 15, 16, 17]
    h1_lows   = [9, 9, 9, 9.5, 12, 9.5, 9, 7, 8.5, 9.5, 10.5, 11.5, 13, 14, 15]
    h1_closes = [9.6, 9.7, 9.6, 10.2, 13.5, 10.3, 9.5, 7.8, 9.3, 10.4, 11.4, 12.4, 14.5, 15.5, 16.5]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")

    m15_opens  = [9.5, 9.8, 9.9, 9.0, 8.0, 7.8, 6.5, 6.8, 7.0, 7.2]
    m15_highs  = [10, 10, 10, 9.5, 8.2, 8.0, 7.0, 7.2, 7.5, 7.6]
    m15_lows   = [9.0, 9.5, 9.0, 6.8, 7.5, 6.2, 6.0, 6.5, 6.8, 7.0]
    m15_closes = [9.8, 9.9, 9.5, 8.0, 7.8, 6.5, 6.8, 7.0, 7.2, 7.4]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 12:30")

    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)
    choch_time = h1_df["timestamp"].iloc[0]
    l_base_time = h1_df["timestamp"].iloc[7]

    swings = primitives.find_swings(h1_df, config.STRUCTURE_SWING_N, tf_h1)
    print("\n--- H1 SWINGS ---")
    print(swings.to_string())

    print("\n--- H1 DF ---")
    print(h1_df.to_string())
    print("\n--- M15 DF ---")
    print(m15_df.to_string())

    result = zones.find_inducement(h1_df, m15_df, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low=5.5, ob_high=6.5, direction="bullish")
    print("\n--- INDUCEMENT RESULT (Model B expected) ---")
    print(result)
    assert True
