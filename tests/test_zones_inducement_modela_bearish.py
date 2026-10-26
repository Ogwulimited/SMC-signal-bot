import pandas as pd
import pytest
from src.research import zones
from conftest import _mk_df


def test_inducement_model_a_bearish_sweep_touch():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    h1 = _mk_df(
        opens=[10, 10, 10, 10],
        highs=[10.5, 10.5, 10.5, 10.5],
        lows=[9.5, 9.5, 9.5, 9.5],
        closes=[10, 10, 10, 10],
        freq="1h", start="2023-01-01 00:00:00",
    )

    m15 = _mk_df(
        opens=[10.0, 9.8, 9.6, 9.9, 10.1, 9.7, 9.4, 9.2, 9.3, 9.4, 10.5],
        highs=[10.1, 9.9, 9.7, 10.2, 10.3, 9.8, 9.5, 9.3, 9.5, 10.6, 10.9],
        lows=[9.9, 9.7, 9.5, 9.8, 10.0, 9.6, 9.3, 9.1, 9.2, 9.3, 10.4],
        closes=[10.0, 9.8, 9.6, 10.1, 10.2, 9.7, 9.4, 9.2, 9.4, 10.5, 10.8],
        freq="15min", start="2023-01-01 00:00:00",
    )

    l_base_time = pd.Timestamp("2022-12-31 23:45:00", tz="UTC")
    choch_time = pd.Timestamp("2023-01-01 02:15:00", tz="UTC")
    ob_low, ob_high = 10.8, 11.0

    result = zones.find_inducement(h1, m15, tf_h1, tf_m15, choch_time, l_base_time,
                                    ob_low, ob_high, direction="bearish")

    assert result["model"] == "A"
    assert result["idm_price"] == pytest.approx(10.3)
    assert result["idm_time"] == pd.Timestamp("2023-01-01 01:45:00", tz="UTC")
    assert result["armed_time"] == pd.Timestamp("2023-01-01 01:45:00", tz="UTC")
    assert result["swept_time"] == pd.Timestamp("2023-01-01 02:30:00", tz="UTC")
    assert result["touch_time"] == pd.Timestamp("2023-01-01 02:45:00", tz="UTC")
    assert result["same_bar_ambiguous"] == False
    assert result["invalid_h1_close_through"] == False
