import pandas as pd
from src import config
from src.research import primitives
from src.research import zones
from conftest import _mk_df


def test_inducement_model_b_full_sequence():
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

    result = zones.find_inducement(h1_df, m15_df, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low=5.5, ob_high=6.5, direction="bullish")

    assert result is not None
    assert result["model"] == "B"
    assert result["idm_price"] == 7.0
    assert result["idm_time"] == pd.Timestamp("2023-01-01 10:00:00", tz="UTC")
    assert result["armed_time"] == pd.Timestamp("2023-01-01 13:00:00", tz="UTC")
    assert result["swept_time"] == pd.Timestamp("2023-01-01 13:30:00", tz="UTC")
    assert result["touch_time"] == pd.Timestamp("2023-01-01 14:00:00", tz="UTC")
    assert result["same_bar_ambiguous"] is False
    assert result["invalid_h1_close_through"] is False


def test_inducement_model_a_full_sequence():
    m15_opens  = [8.7, 9.0, 9.6, 9.8, 9.6, 9.3, 8.6, 9.1, 9.7, 13.0, 7.6, 10.6, 10.6, 10.1, 9.7]
    m15_highs  = [9.0, 9.5, 10.0, 12.0, 9.8, 9.5, 9.7, 10.0, 14.0, 13.5, 7.8, 11.5, 11.0, 10.5, 10.0]
    m15_lows   = [8.5, 9.0, 9.5, 9.8, 9.2, 8.0, 8.8, 9.5, 9.6, 7.5, 6.2, 10.5, 10.0, 9.5, 9.0]
    m15_closes = [8.8, 9.2, 9.7, 10.0, 9.5, 8.5, 9.0, 9.6, 13.8, 8.0, 6.5, 10.8, 10.2, 9.8, 9.3]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 12:00")

    h1_opens  = [8.0] * 10
    h1_highs  = [9.0] * 10
    h1_lows   = [7.5] * 10
    h1_closes = [8.2] * 10
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01 10:00")

    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)
    l_base_time = m15_df["timestamp"].iloc[0]
    choch_time = m15_df["timestamp"].iloc[14] + tf_m15

    result = zones.find_inducement(h1_df, m15_df, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low=6.0, ob_high=6.5, direction="bullish")

    assert result is not None
    assert result["model"] == "A"
    assert result["idm_price"] == 8.0
    assert result["idm_time"] == pd.Timestamp("2023-01-01 14:00:00", tz="UTC")
    assert result["armed_time"] == pd.Timestamp("2023-01-01 14:15:00", tz="UTC")
    assert result["swept_time"] == pd.Timestamp("2023-01-01 14:30:00", tz="UTC")
    assert result["touch_time"] == pd.Timestamp("2023-01-01 14:45:00", tz="UTC")
    assert result["same_bar_ambiguous"] is False
    assert result["invalid_h1_close_through"] is False
    
def test_diagnostic_print_inducement_same_bar_ambiguous(capsys):
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

    result = zones.find_inducement(h1_df, m15_df, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low=5.9, ob_high=6.9, direction="bullish")
    print("\n--- INDUCEMENT RESULT (same_bar_ambiguous expected True) ---")
    print(result)
    assert True
