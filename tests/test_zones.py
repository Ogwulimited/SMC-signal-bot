import pandas as pd
from src import config
from src.research import primitives
from src.research import zones


def _mk_df(opens, highs, lows, closes, freq="1h", start="2023-01-01"):
    n = len(opens)
    ts = pd.date_range(start, periods=n, freq=freq, tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open": opens, "high": highs, "low": lows, "close": closes})


# --- CRITICAL REGRESSION: direction mapping (the Round-5 bug) --------------
# NOTE: opens[] are my own addition (Phase 1's fixtures only had H/L/C).
# highs/lows/closes below are UNCHANGED from the locked Phase 1 fixtures.
# n=1 matches Phase 1's real test_bos_choch_sequence/test_bos_choch_mirror
# source exactly -- NOT config.STRUCTURE_SWING_N (that was my earlier bug).

def test_order_block_direction_bearish_on_choch_down():
    highs  = [10, 14, 11, 15, 13, 17, 14, 10]
    lows   = [8, 9, 8, 8.5, 9, 9, 8, 7.5]
    closes = [9, 10, 9, 15, 12, 16, 9, 7.8]
    opens  = [8.5, 9, 9.5, 9.5, 15, 12.5, 16, 9]
    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)
    obs = zones.detect_order_blocks(df, tf, events)
    assert not obs.empty
    assert not (obs["direction"] == "bullish").any()
    assert (obs["direction"] == "bearish").any()


def test_order_block_direction_bullish_on_choch_up():
    highs  = [17, 16, 17, 16.5, 16, 16, 17, 17.5]
    lows   = [15, 11, 14, 10, 12, 8, 11, 15]
    closes = [16, 15, 16, 10, 13, 9, 16, 17.2]
    opens  = [16.5, 16, 15.5, 15.5, 10, 12.5, 9, 16]
    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)
    obs = zones.detect_order_blocks(df, tf, events)
    assert not obs.empty
    assert not (obs["direction"] == "bearish").any()
    assert (obs["direction"] == "bullish").any()


# --- FVG: safely-above / safely-below margin (exact 0.05 boundary is ATR-
# shift-sensitive; tightening to a razor boundary should be done after one
# real CI run confirms the exact computed ATR, not hand-derived blind). -----

def test_fvg_above_min_size_is_detected():
    opens = [100.0] * 16 + [100.0, 102.0, 104.0]
    highs = [101.0] * 16 + [101.0, 104.5, 104.7]
    lows  = [99.0] * 16 + [99.0, 101.5, 101.3]
    closes = [100.0] * 16 + [100.0, 104.0, 104.5]
    df = _mk_df(opens, highs, lows, closes)
    fvgs = zones.detect_fvgs(df, pd.Timedelta(hours=1))
    match = fvgs[(fvgs["a_index"] == 16) & (fvgs["c_index"] == 18)]
    assert not match.empty
    assert match.iloc[0]["size_atr"] >= config.FVG_MIN_SIZE_ATR


def test_fvg_below_min_size_is_rejected():
    opens = [100.0] * 16 + [100.0, 102.0, 104.0]
    highs = [101.0] * 16 + [101.0, 104.5, 104.6]
    lows  = [99.0] * 16 + [99.0, 101.5, 101.05]
    closes = [100.0] * 16 + [100.0, 104.0, 104.5]
    df = _mk_df(opens, highs, lows, closes)
    fvgs = zones.detect_fvgs(df, pd.Timedelta(hours=1))
    match = fvgs[(fvgs["a_index"] == 16) & (fvgs["c_index"] == 18)]
    assert match.empty


# --- Sweep with / without reclaim ------------------------------------------

def test_sweep_with_same_bar_reclaim():
    df = _mk_df(opens=[100, 99, 100], highs=[101, 100, 101],
                lows=[99.5, 98.5, 99], closes=[100, 99.5, 100])
    r = zones.detect_sweep(df, pd.Timedelta(hours=1), pool_price=99.0,
                           confirm_time=df["timestamp"].iloc[0], side="low")
    assert r is not None and r["swept_index"] == 1 and r["reclaim_same_bar"] is True


def test_sweep_without_reclaim():
    df = _mk_df(opens=[100, 99, 98, 98, 98], highs=[101, 100, 98.5, 98.5, 98.5],
                lows=[99.5, 98.5, 97.5, 97.8, 97.6], closes=[100, 98.6, 98.0, 98.2, 98.1])
    r = zones.detect_sweep(df, pd.Timedelta(hours=1), pool_price=99.0,
                           confirm_time=df["timestamp"].iloc[0], side="low")
    assert r is not None and r["reclaim_same_bar"] is False and r["reclaim_3"] is False


# --- Mitigated vs unmitigated OB (direct check on helper) ------------------

def test_ob_unmitigated_before_touch_helper():
    assert zones.ob_unmitigated_before_touch(pd.NaT, pd.Timestamp("2023-01-01", tz="UTC")) is True
    t_mit = pd.Timestamp("2023-01-02", tz="UTC")
    t_touch = pd.Timestamp("2023-01-01", tz="UTC")
    assert zones.ob_unmitigated_before_touch(t_mit, t_touch) is True   # mitigated AFTER touch -> fine
    assert zones.ob_unmitigated_before_touch(t_touch, t_mit) is False  # mitigated BEFORE touch -> invalid


# --- NOT YET SAFE TO HAND-LOCK (flagged honestly, not guessed) -------------
# same_bar_ambiguous (find_inducement) and breaker FVG-overlap depend on the
# full multi-timeframe pipeline (H1+M15 swings/BOS interacting). Recommend:
# run the above tests first in CI, confirm green, THEN construct these two
# fixtures from REAL printed intermediate output rather than hand-derivation.

def test_find_swing_pools_low_basic():
    lows = [15, 14, 10, 14, 15, 15, 15]
    highs = [20] * 7
    opens = lows[:]
    closes = lows[:]
    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    pools = zones.find_swing_pools(df, tf, "H1", "low")
    assert len(pools) == 1
    row = pools.iloc[0]
    assert row["index"] == 2
    assert row["pool_price"] == 10
    expected_confirm = df["timestamp"].iloc[4] + tf
    assert row["confirm_time"] == expected_confirm
    assert row["expires_at"] == expected_confirm + config.SWING_POOL_MAX_AGE_H1 * tf
    assert row["side"] == "low"
    assert row["timeframe"] == "H1"
    assert row["pool_type"] == "swing"
    assert pd.isna(row["swept_time"])


def test_equal_lows_in_and_out_of_tolerance():
    n = 35
    opens = [100.0] * n
    highs = [100.5] * n
    lows = [99.5] * n
    closes = [100.0] * n
    lows[15] = 90.0
    closes[15] = 95.0
    lows[20] = 89.95
    closes[20] = 95.0
    lows[30] = 50.0
    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    eql = zones.detect_equal_lows(df, tf)
    assert len(eql) == 1
    row = eql.iloc[0]
    assert row["cluster_size"] == 2
    assert abs(row["pool_price"] - 89.95) < 1e-9
    assert row["pool_type"] == "equal_lows"
    assert pd.isna(row["expires_at"])


def test_find_liquidity_taken_bullish_logs_matching_pool():
    pools = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 95.0,
         "confirm_time": pd.Timestamp("2023-01-01 00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.NaT},
        {"pool_type": "swing", "side": "low", "pool_price": 105.0,
         "confirm_time": pd.Timestamp("2023-01-01 00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.NaT},
        {"pool_type": "swing", "side": "high", "pool_price": 95.0,
         "confirm_time": pd.Timestamp("2023-01-01 00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    bos_open_time = pd.Timestamp("2023-01-02 00:00", tz="UTC")
    result = zones.find_liquidity_taken(pools, bos_open_time, l_base_price=90.0,
                                         direction="bullish", atr_at_bos=2.0, ob_upper_edge=92.0)
    assert len(result) == 1
    assert result.iloc[0]["pool_type"] == "swing"
    assert result.iloc[0]["pool_price"] == 95.0
    assert abs(result.iloc[0]["depth"] - 5.0) < 1e-9
    assert abs(result.iloc[0]["depth_atr"] - 2.5) < 1e-9


def test_diagnostic_print_bos_choch_for_htf_zones(capsys):
    highs  = [10, 14, 11, 15, 13, 17, 14, 10, 9, 8, 11, 13]
    lows   = [8, 9, 8, 8.5, 9, 9, 8, 7.5, 7, 6.5, 7, 8]
    closes = [9, 10, 9, 15, 12, 16, 9, 7.8, 7.2, 6.8, 10.5, 12.5]
    opens  = [8.5, 9, 9.5, 9.5, 15, 12.5, 16, 9, 8, 7, 7.2, 10.5]
    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)
    print("\n--- SWINGS ---")
    print(swings.to_string())
    print("\n--- EVENTS ---")
    print(events.to_string())
    htf = zones.find_htf_zones(df, tf, events)
    print("\n--- HTF ZONES ---")
    print(htf.to_string())
    assert True
