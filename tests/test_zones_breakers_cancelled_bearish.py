import pandas as pd
import numpy as np
from src.research import zones
from conftest import _mk_df


def test_breaker_bearish_cancelled():
    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    h1 = _mk_df(
        opens=[10.0, 10.2, 9.5, 9.4, 9.3, 10.8],
        highs=[10.3, 10.3, 9.6, 9.5, 9.4, 11.0],
        lows=[9.9, 10.1, 9.4, 9.2, 9.2, 10.7],
        closes=[10.2, 10.15, 9.45, 9.25, 9.15, 10.9],
        freq="1h", start="2023-01-01 00:00:00",
    )

    m15 = _mk_df(
        opens=[9.5] * 24,
        highs=[9.6] * 24,
        lows=[9.4] * 24,
        closes=[9.5] * 24,
        freq="15min", start="2023-01-01 03:00:00",
    )

    bos_choch_events = pd.DataFrame([
        {"label": "BOS", "direction": "up", "time": pd.Timestamp("2023-01-01 02:00:00", tz="UTC"),
         "last_opposite_time": pd.Timestamp("2023-01-01 01:00:00", tz="UTC"), "last_opposite_price": 10.1},
    ])

    result = zones.detect_breakers(h1, tf_h1, m15, tf_m15, bos_choch_events)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["direction"] == "bearish"
    assert row["swing_time"] == pd.Timestamp("2023-01-01 01:00:00", tz="UTC")
    assert row["swing_price"] == 10.1
    assert row["bos_time"] == pd.Timestamp("2023-01-01 02:00:00", tz="UTC")
    assert row["zone_index"] == 1
    assert row["zone_low"] == 10.1
    assert row["zone_high"] == 10.3
    assert row["failed_at"] == pd.Timestamp("2023-01-01 03:00:00", tz="UTC")
    assert row["fvg_overlap"] == False
    assert row["limit_price"] == 10.2
    assert np.isnan(row["stop"])
    assert row["filled"] == False
    assert pd.isna(row["fill_time"])
    assert row["cancelled"] == True
    assert row["cancel_time"] == pd.Timestamp("2023-01-01 06:00:00", tz="UTC")
