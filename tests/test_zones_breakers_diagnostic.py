import numpy as np
import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diag_bullish_with_fvg():
    """Reuse of existing bullish_basic fixture. Only limit_price should
    change under the fix (zone-midpoint -> FVG-midpoint).
    Hand-derived expectation: zone_low=9.9, zone_high=11.0,
    failed_at=2023-01-01 19:00, fvg_low=10.95, fvg_high=11.0,
    limit_price~=10.975, stop~=9.86, filled=True,
    fill_time=2023-01-01 19:45:00, cancelled=False.
    """
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
        "label": "BOS", "direction": "down",
        "time": h1_df["timestamp"].iloc[16] + tf_h1, "close": 9.5,
        "broken_swing_time": pd.NaT, "broken_swing_price": np.nan,
        "last_opposite_time": h1_df["timestamp"].iloc[15], "last_opposite_price": 11.0,
    }])
    bos_events["time"] = pd.to_datetime(bos_events["time"], utc=True)
    bos_events["last_opposite_time"] = pd.to_datetime(bos_events["last_opposite_time"], utc=True)

    result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_events)
    print("\n--- DIAG bullish_with_fvg ---")
    print(result.to_dict("records"))
    assert len(result) == 1


def test_diag_bearish_with_fvg():
    """New fixture: mirror of bullish_basic around x' = 20 - x (open/close
    map directly, high/low swap). Hand-derived expectation:
    direction=bearish, zone_low=9.0, zone_high=10.1,
    failed_at=2023-01-01 19:00, fvg_low=9.0, fvg_high=9.05,
    limit_price~=9.025, stop~=10.14, filled=True,
    fill_time=2023-01-01 19:45:00, cancelled=False.
    NOTE: idx21 (o=9.3,h=9.0) is an inherited cosmetic OHLC quirk mirrored
    from the original fixture's own idx21 quirk -- harmless, never read.
    """
    warmup_n = 15
    h1_opens  = [10.0]*warmup_n + [10.0, 10.0, 10.5, 11.0, 9.2, 9.4, 9.3, 8.8, 8.7]
    h1_highs  = [10.2]*warmup_n + [10.1, 10.7, 11.2, 11.1, 9.5, 9.45, 9.0, 8.9, 8.8]
    h1_lows   = [9.8]*warmup_n  + [9.0, 10.0, 10.4, 8.8, 9.05, 9.2, 8.7, 8.6, 8.5]
    h1_closes = [10.0]*warmup_n + [9.5, 10.5, 11.0, 8.95, 9.4, 9.3, 8.8, 8.7, 8.6]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")
    tf_h1 = pd.Timedelta(hours=1)

    m15_opens  = [7.5, 7.9, 8.8, 9.7, 9.5, 8.2, 7.7, 7.2]
    m15_highs  = [8.0, 9.0, 9.8, 9.9, 9.6, 8.3, 7.8, 7.3]
    m15_lows   = [7.4, 7.8, 8.7, 9.4, 8.0, 7.5, 7.0, 6.8]
    m15_closes = [7.9, 8.8, 9.7, 9.5, 8.2, 7.7, 7.2, 7.0]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 19:00")
    tf_m15 = pd.Timedelta(minutes=15)

    bos_events = pd.DataFrame([{
        "label": "BOS", "direction": "up",
        "time": h1_df["timestamp"].iloc[16] + tf_h1, "close": 10.5,
        "broken_swing_time": pd.NaT, "broken_swing_price": np.nan,
        "last_opposite_time": h1_df["timestamp"].iloc[15], "last_opposite_price": 9.0,
    }])
    bos_events["time"] = pd.to_datetime(bos_events["time"], utc=True)
    bos_events["last_opposite_time"] = pd.to_datetime(bos_events["last_opposite_time"], utc=True)

    result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_events)
    print("\n--- DIAG bearish_with_fvg ---")
    print(result.to_dict("records"))
    assert len(result) == 1


def test_diag_bullish_fvg_cancelled():
    """Extends bullish_basic with one more H1 bar closing below zone_low
    after the FVG forms. M15 held flat (never reaches limit_price) to
    isolate the cancel path from fill timing.
    Hand-derived expectation: fvg_overlap=True, fvg_low=10.95, fvg_high=11.0,
    limit_price~=10.975, stop~=9.86, filled=False,
    cancelled=True, cancel_time=2023-01-02 01:00:00.
    """
    warmup_n = 15
    h1_opens  = [10.0]*warmup_n + [10.0, 10.0, 9.5, 9.0, 10.8, 10.6, 10.7, 11.2, 11.3, 9.8]
    h1_highs  = [10.2]*warmup_n + [11.0, 10.0, 9.6, 11.2, 10.95, 10.8, 11.3, 11.4, 11.5, 9.9]
    h1_lows   = [9.8]*warmup_n  + [9.9, 9.3, 8.8, 8.9, 10.5, 10.55, 11.0, 11.1, 11.2, 9.3]
    h1_closes = [10.0]*warmup_n + [10.5, 9.5, 9.0, 11.05, 10.6, 10.7, 11.2, 11.3, 11.4, 9.5]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")
    tf_h1 = pd.Timedelta(hours=1)

    m15_df = _mk_df([12.0]*28, [12.0]*28, [12.0]*28, [12.0]*28, freq="15min", start="2023-01-01 19:00")
    tf_m15 = pd.Timedelta(minutes=15)

    bos_events = pd.DataFrame([{
        "label": "BOS", "direction": "down",
        "time": h1_df["timestamp"].iloc[16] + tf_h1, "close": 9.5,
        "broken_swing_time": pd.NaT, "broken_swing_price": np.nan,
        "last_opposite_time": h1_df["timestamp"].iloc[15], "last_opposite_price": 11.0,
    }])
    bos_events["time"] = pd.to_datetime(bos_events["time"], utc=True)
    bos_events["last_opposite_time"] = pd.to_datetime(bos_events["last_opposite_time"], utc=True)

    result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_events)
    print("\n--- DIAG bullish_fvg_cancelled ---")
    print(result.to_dict("records"))
    assert len(result) == 1


def test_diag_bearish_basic_no_fvg_rejected():
    """Original test_detect_breakers_bearish_basic fixture, verbatim --
    this fixture has fvg_overlap=False. Under the fix, expect len==0
    (no row at all, not a filled row)."""
    warmup_n = 15
    h1_opens  = [10.0]*warmup_n + [10.0, 10.0, 10.5, 11.0, 9.2, 9.4, 9.3, 8.8, 8.7]
    h1_highs  = [10.2]*warmup_n + [10.1, 10.7, 11.2, 11.1, 9.5, 9.45, 9.9, 8.9, 8.8]
    h1_lows   = [9.8]*warmup_n  + [9.9, 9.95, 10.4, 9.8, 9.05, 9.3, 9.0, 8.6, 8.5]
    h1_closes = [10.0]*warmup_n + [9.95, 10.5, 11.05, 9.4, 9.3, 9.4, 8.8, 8.7, 8.6]
    h1_df = _mk_df(h1_opens, h1_highs, h1_lows, h1_closes, freq="1h", start="2023-01-01")
    tf_h1 = pd.Timedelta(hours=1)

    m15_opens  = [8.0, 8.4, 9.3, 10.2, 10.0, 8.7, 8.2, 7.7]
    m15_highs  = [8.1, 8.5, 9.4, 10.3, 10.5, 8.8, 8.3, 7.8]
    m15_lows   = [7.5, 8.3, 9.2, 9.7, 9.5, 8.2, 7.7, 7.6]
    m15_closes = [8.4, 9.3, 10.2, 10.0, 8.7, 8.2, 7.7, 7.5]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-01-01 19:00")
    tf_m15 = pd.Timedelta(minutes=15)

    bos_events = pd.DataFrame([{
        "label": "BOS", "direction": "up",
        "time": h1_df["timestamp"].iloc[16] + tf_h1, "close": 10.5,
        "broken_swing_time": pd.NaT, "broken_swing_price": np.nan,
        "last_opposite_time": h1_df["timestamp"].iloc[15], "last_opposite_price": 9.9,
    }])
    bos_events["time"] = pd.to_datetime(bos_events["time"], utc=True)
    bos_events["last_opposite_time"] = pd.to_datetime(bos_events["last_opposite_time"], utc=True)

    result = zones.detect_breakers(h1_df, tf_h1, m15_df, tf_m15, bos_events)
    print("\n--- DIAG bearish_basic_no_fvg_rejected ---")
    print(result.to_dict("records"))
    assert len(result) == 0


def test_diag_bullish_cancelled_no_fvg_rejected():
    """Original test_breaker_bullish_cancelled fixture, verbatim -- this
    fixture has fvg_overlap=False. Under the fix, expect len==0."""
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
        opens=[10.5]*24, highs=[10.6]*24, lows=[10.4]*24, closes=[10.5]*24,
        freq="15min", start="2023-01-01 04:00:00",
    )
    bos_choch_events = pd.DataFrame([{
        "label": "BOS", "direction": "down", "time": pd.Timestamp("2023-01-01 02:00:00", tz="UTC"),
        "last_opposite_time": pd.Timestamp("2023-01-01 01:00:00", tz="UTC"), "last_opposite_price": 9.9,
    }])

    result = zones.detect_breakers(h1, tf_h1, m15, tf_m15, bos_choch_events)
    print("\n--- DIAG bullish_cancelled_no_fvg_rejected ---")
    print(result.to_dict("records"))
    assert len(result) == 0


def test_diag_bearish_cancelled_no_fvg_rejected():
    """Original test_breaker_bearish_cancelled fixture, verbatim -- this
    fixture has fvg_overlap=False. Under the fix, expect len==0."""
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
        opens=[9.5]*24, highs=[9.6]*24, lows=[9.4]*24, closes=[9.5]*24,
        freq="15min", start="2023-01-01 03:00:00",
    )
    bos_choch_events = pd.DataFrame([{
        "label": "BOS", "direction": "up", "time": pd.Timestamp("2023-01-01 02:00:00", tz="UTC"),
        "last_opposite_time": pd.Timestamp("2023-01-01 01:00:00", tz="UTC"), "last_opposite_price": 10.1,
    }])

    result = zones.detect_breakers(h1, tf_h1, m15, tf_m15, bos_choch_events)
    print("\n--- DIAG bearish_cancelled_no_fvg_rejected ---")
    print(result.to_dict("records"))
    assert len(result) == 0
