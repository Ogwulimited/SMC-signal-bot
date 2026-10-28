import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_breaker_bearish_no_fvg_rejected():
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

    assert len(result) == 0
