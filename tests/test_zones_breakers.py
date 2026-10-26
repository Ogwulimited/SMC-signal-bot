import numpy as np
import pandas as pd
from src import config
from src.research import primitives
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_detect_breakers(capsys):
    warmup_n = 15
    h1_opens  = [10.0]*warmup_n + [10.0, 10.0, 9.5, 9.0, 10.8, 10.6, 10.7, 11.2, 11.3]
    h1_highs  = [10.2]*warmup_n + [11.0, 10.0, 9.6, 11.2, 10.95, 10.8, 11.3, 11.4, 11.5]
    h1_lows   = [9.8]*warmup_n  + [9.9, 9.3, 8.8, 8.9, 10.5, 10.55, 11.0, 11.1, 11.2]
    h1_closes = [10.0]*warmup_n + [10.5, 9.5, 9.0, 11.05, 10.6, 10.7, 11.2, 11.3, 11.4]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")
    tf_h1 = pd.Timedelta(hours=1)

    m15_opens  = [12.5, 12.1, 11.2, 10.3, 10.5, 11.8, 12.3, 12.8]
    m15_highs  = [12.6, 12.2, 11.3, 10.6, 12.0, 12.5, 13.0, 13.2]
    m15_lows   = [12.0, 11.0, 10.2, 10.1, 10.4, 11.7, 12.2, 12.7]
    m15_closes = [12.1, 11.2, 10.3, 10.5, 11.8, 12.3, 12.8, 13.0]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 19:00")
    tf_m15 = pd.Timedelta(minutes=15)

    bos_events = pd.DataFrame([{
        "label": "BOS",
        "direction": "down",
        "time": h1_df["timestamp"].iloc[16] + tf_h1,
        "close": 9.5,
        "broken_swing_time": pd.NaT,
        "broken_swing_price": np.nan,
        "last_opposite_time": h1_df["timestamp"].iloc[15],
        "last_opposite_price": 11.0,
    }])
    bos_events["time"] = pd.to_datetime(bos_events["time"], utc=True)
    bos_events["last_opposite_time"] = pd.to_datetime(bos_events["last_opposite_time"], utc=True)

    result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_events)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print("\n--- BREAKERS RESULT ---")
    print(result.to_string())
    assert True
