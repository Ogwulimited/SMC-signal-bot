import pandas as pd
import numpy as np
import pytest
from src.research import zones
from conftest import _mk_df


def test_breaker_bullish_cancelled():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    h1 = _mk_df(
        opens=[10.0, 9.8, 10.5, 10.6, 10.7, 9.2],
        highs=[10.1, 9.9, 10.6, 10.8, 10.9, 9.5],
        lows=[9.7, 9.7, 10.4, 10.5, 10.6, 9.0],
        closes=[9.8, 9.85, 10.55, 10.75, 10.85, 9.1],
        freq="1h", start="2023-01-01 00:00:00",
    )

    m15 = _mk_df(
        opens=[10.5] * 24,
        highs=[10.6] * 24,
        lows=[10.4] * 24,
        closes=[10.5] * 24,
        freq="15min", start="2023-01-01 04:00:00",
    )

    bos_choch_events = pd.DataFrame([
        {"label": "BOS", "direction": "down", "time": pd.Timestamp("2023-01-01 02:00:00", tz="UTC"),
         "last_opposite_time": pd.Timestamp("2023-01-01 01:00:00", tz="UTC"), "last_opposite_price": 9.9},
    ])

    result = zones.detect_breakers(h1, tf_h1, m15, tf_m15, bos_choch_events)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["direction"] == "bullish"
    assert row["zone_low"] == 9.7
    assert row["zone_high"] == 9.9
    assert row["failed_at"] == pd.Timestamp("2023-01-01 03:00:00", tz="UTC")
    assert row["fvg_overlap"] == False
    assert row["limit_price"] == pytest.approx(9.8)
    assert np.isnan(row["stop"])
    assert row["filled"] == False
    assert pd.isna(row["fill_time"])
    assert row["cancelled"] == True
    assert row["cancel_time"] == pd.Timestamp("2023-01-01 06:00:00", tz="UTC")
