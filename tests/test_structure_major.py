"""Tests for src/research/structure_major.py (major-structure BOS/CHoCH)."""
import numpy as np
import pandas as pd

from src.research.primitives import find_swings, detect_bos_choch
from src.research.structure_major import detect_bos_choch_major

TF = pd.Timedelta(hours=1)
N = 1


def make_df(bars):
    """bars = list of (high, low, close). One bar per hour."""
    ts = pd.date_range("2020-01-01", periods=len(bars), freq="1h", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": [b[2] for b in bars],
        "high": [float(b[0]) for b in bars],
        "low": [float(b[1]) for b in bars],
        "close": [float(b[2]) for b in bars],
    })


# 95 -> 93 -> 100 example. Swing highs 95 (bar 1) and 93 (bar 4).
# Bar 6 closes at 94 (above 93, below 95). Bar 7 closes at 100.
EXAMPLE_95_93_100 = [
    (80, 70, 75),
    (95, 85, 90),
    (85, 75, 80),
    (88, 78, 82),
    (93, 83, 88),
    (89, 79, 84),
    (94.5, 88, 94),
    (101, 92, 100),
    (98, 90, 95),
]

# INIT up (bar 7), BOS up (bar 12), CHoCH down (bar 14)
STRUCTURE_PATH = [
    (15, 11, 13),   # 0
    (14, 10, 12),   # 1  swing low 10
    (18, 12, 17),   # 2
    (20, 16, 17),   # 3  swing high 20
    (17, 14, 15),   # 4
    (16, 13, 15),   # 5  swing low 13
    (18, 15, 17),   # 6
    (22, 17, 21),   # 7  close 21 > 20  -> INIT up
    (30, 21, 28),   # 8  swing high 30
    (27, 24, 25),   # 9
    (26, 22, 24),   # 10 swing low 22 (the HL)
    (29, 25, 27),   # 11
    (33, 26, 32),   # 12 close 32 > 30  -> BOS up
    (31, 24, 26),   # 13
    (28, 20, 21),   # 14 close 21 < 22  -> CHoCH down
]


def run_major(bars):
    df = make_df(bars)
    sw = find_swings(df, N, TF)
    return df, detect_bos_choch_major(df, sw, TF)


def test_95_93_100_line_starts_at_95_not_93():
    df, ev = run_major(EXAMPLE_95_93_100)
    assert len(ev) == 1
    row = ev.iloc[0]
    assert row["direction"] == "up"
    assert row["label"] == "INIT"
    assert row["broken_swing_price"] == 95.0
    assert row["broken_swing_time"] == df["timestamp"].iloc[1]
    assert row["time"] == df["timestamp"].iloc[7] + TF


def test_old_nearest_rule_fires_at_93_for_comparison():
    df = make_df(EXAMPLE_95_93_100)
    sw = find_swings(df, N, TF)
    old = detect_bos_choch(df, sw, TF)
    assert old.iloc[0]["broken_swing_price"] == 93.0
    assert old.iloc[0]["time"] == df["timestamp"].iloc[6] + TF


def test_close_between_93_and_95_prints_nothing():
    _, ev = run_major(EXAMPLE_95_93_100[:7])   # stops after the 94 close
    assert len(ev) == 0


def test_init_bos_choch_sequence():
    df, ev = run_major(STRUCTURE_PATH)
    assert list(ev["label"]) == ["INIT", "BOS", "CHoCH"]
    assert list(ev["direction"]) == ["up", "up", "down"]
    assert list(ev["time"]) == [df["timestamp"].iloc[k] + TF for k in (7, 12, 14)]


def test_init_breaks_highest_high_and_keeps_lows():
    df, ev = run_major(STRUCTURE_PATH)
    r = ev.iloc[0]
    assert r["broken_swing_price"] == 20.0
    # lows are kept after INIT, lowest standing low is 10
    assert r["last_opposite_price"] == 10.0
    assert r["last_opposite_time"] == df["timestamp"].iloc[1]


def test_bos_drops_older_lows_and_protects_the_pullback_low():
    df, ev = run_major(STRUCTURE_PATH)
    r = ev.iloc[1]
    assert r["broken_swing_price"] == 30.0
    # lows 10 and 13 are older than the broken high, only 22 remains
    assert r["last_opposite_price"] == 22.0
    assert r["last_opposite_time"] == df["timestamp"].iloc[10]


def test_choch_down_breaks_the_hl_and_keeps_the_leg_top():
    df, ev = run_major(STRUCTURE_PATH)
    r = ev.iloc[2]
    assert r["label"] == "CHoCH"
    assert r["broken_swing_price"] == 22.0
    assert r["broken_swing_time"] == df["timestamp"].iloc[10]
    # leg top 33 stays protected
    assert r["last_opposite_price"] == 33.0
    assert r["last_opposite_time"] == df["timestamp"].iloc[12]


def test_same_columns_as_old_function():
    df = make_df(STRUCTURE_PATH)
    sw = find_swings(df, N, TF)
    old = detect_bos_choch(df, sw, TF)
    new = detect_bos_choch_major(df, sw, TF)
    assert list(new.columns) == list(old.columns)


def test_empty_input_gives_empty_events_with_columns():
    df = make_df([(10, 9, 9.5), (11, 10, 10.5)])
    sw = find_swings(df, N, TF)
    ev = detect_bos_choch_major(df, sw, TF)
    assert len(ev) == 0
    assert list(ev.columns) == ["label", "direction", "time", "close",
                                "broken_swing_time", "broken_swing_price",
                                "last_opposite_time", "last_opposite_price"]


def test_no_lookahead_events_do_not_change_when_future_is_added():
    full_df = make_df(STRUCTURE_PATH)
    full = detect_bos_choch_major(full_df, find_swings(full_df, N, TF), TF)
    cut_df = make_df(STRUCTURE_PATH[:10])
    cut = detect_bos_choch_major(cut_df, find_swings(cut_df, N, TF), TF)
    cutoff = cut_df["timestamp"].iloc[-1] + TF
    full_early = full[full["time"] <= cutoff].reset_index(drop=True)
    pd.testing.assert_frame_equal(full_early, cut.reset_index(drop=True))
