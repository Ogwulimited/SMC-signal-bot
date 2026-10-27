import pandas as pd
from src.research import setups
from conftest import _mk_df


def test_d1_bias_bullish_after_init():
    d1 = _mk_df(
        opens=[9.5, 8.5, 7.5, 5.0, 8.0, 9.0, 10.0, 15.0, 10.0, 9.0, 7.0, 24.5],
        highs=[10, 9, 8, 6, 11, 12, 13, 20, 13, 12, 11, 26],
        lows=[9, 8, 7, 3, 7, 8, 9, 9, 8, 7, 3, 24],
        closes=[9.5, 8.5, 7.5, 4.5, 9.0, 10.0, 11.0, 16.0, 11.0, 10.0, 8.0, 25.0],
        freq="1D", start="2023-01-01",
    )

    result = setups.compute_d1_bias(d1)

    assert result["state"] == "bullish"
    assert result["label"] == "INIT"
    assert result["direction"] == "up"
    assert result["time"] == pd.Timestamp("2023-01-13 00:00:00", tz="UTC")


def test_d1_bias_reversing_after_choch():
    d1 = _mk_df(
        opens=[9.5, 8.5, 7.5, 5.0, 8.0, 9.0, 10.0, 15.0, 10.0, 9.0, 7.0, 24.5, 15.0, 3.0],
        highs=[10, 9, 8, 6, 11, 12, 13, 20, 13, 12, 11, 26, 16, 3.5],
        lows=[9, 8, 7, 3, 7, 8, 9, 9, 8, 7, 3, 24, 14, 0.5],
        closes=[9.5, 8.5, 7.5, 4.5, 9.0, 10.0, 11.0, 16.0, 11.0, 10.0, 8.0, 25.0, 15.0, 1.0],
        freq="1D", start="2023-01-01",
    )

    result = setups.compute_d1_bias(d1)

    assert result["state"] == "reversing"
    assert result["label"] == "CHoCH"
    assert result["direction"] == "down"
    assert result["time"] == pd.Timestamp("2023-01-15 00:00:00", tz="UTC")
