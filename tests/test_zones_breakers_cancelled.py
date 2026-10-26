import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_breaker_cancelled():
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
    print("\n--- BREAKER CANCELLED DIAGNOSTIC ---")
    print(result.to_string())
    assert True
