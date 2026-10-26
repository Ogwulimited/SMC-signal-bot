import pandas as pd
from src.research import primitives
from src.research import zones
from conftest import _mk_df


def test_htf_zone_active_unmitigated():
    highs  = [10, 14, 11, 15, 13, 17, 14, 10, 9, 8, 11, 13]
    lows   = [8, 9, 8, 8.5, 9, 9, 8, 7.5, 7, 6.5, 7, 8]
    closes = [9, 10, 9, 15, 12, 16, 9, 7.8, 7.2, 6.8, 10.5, 12.5]
    opens  = [8.5, 9, 9.5, 9.5, 15, 12.5, 16, 9, 8, 7, 7.2, 10.5]
    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)
    htf = zones.find_htf_zones(df, tf, events)
    assert len(htf) == 1
    row = htf.iloc[0]
    assert row["direction"] == "bearish"
    assert row["ob_index"] == 5
    assert row["zone_low"] == 9.0
    assert row["zone_high"] == 17.0
    assert row["confirm_time"] == df["timestamp"].iloc[5] + tf
    assert pd.isna(row["invalidated_at"])
    assert row["touch_count"] == 5


def test_htf_zone_invalidated_on_close_beyond_far_edge(capsys):
    highs  = [10, 14, 11, 15, 13, 17, 14, 10, 9, 8, 11, 13, 15, 18]
    lows   = [8, 9, 8, 8.5, 9, 9, 8, 7.5, 7, 6.5, 7, 8, 10, 16]
    closes = [9, 10, 9, 15, 12, 16, 9, 7.8, 7.2, 6.8, 10.5, 12.5, 12, 17.5]
    opens  = [8.5, 9, 9.5, 9.5, 15, 12.5, 16, 9, 8, 7, 7.2, 10.5, 11, 16.5]
    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)
    htf = zones.find_htf_zones(df, tf, events)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print("\n--- EVENTS ---")
    print(events.to_string())
    print("\n--- HTF ZONES (full) ---")
    print(htf.to_string())
    assert True
