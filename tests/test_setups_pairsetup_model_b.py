"""
Diagnostic: can PairSetup actually arm via Model B (H1-only) when Model A
(M15-based) cannot resolve on the same CHOCH_SEEN candidate?

Reuses the locked Model-A happy-path D1/H1 fixtures through CHoCH
(index 33), then extends h1_df further with new bars engineered to produce
a Model B SH1 -> IDM -> BOS sequence per zones.find_inducement's
_model_b(). M15 data is flat/constant so _model_a() has no price variation
to form any swing -- cand is structurally guaranteed empty, so Model A
returns None regardless of window timing, isolating this test to Model B.

Does not modify setups.py or zones.py. Diagnostic-only: prints +
assert True. Exact-value assertions will be derived from real CI output
in a follow-up commit per mandatory discipline.
"""

import pandas as pd
import pytest
from src.research import setups
from conftest import _mk_df


def _build_d1_bullish_happy():
    return _mk_df(
        opens=[9.5, 8.5, 7.5, 5.0, 8.0, 9.0, 10.0, 15.0, 10.0, 9.0, 7.0, 24.5],
        highs=[10, 9, 8, 6, 11, 12, 13, 20, 13, 12, 11, 26],
        lows=[9, 8, 7, 3, 7, 8, 9, 9, 8, 7, 3, 24],
        closes=[9.5, 8.5, 7.5, 4.5, 9.0, 10.0, 11.0, 16.0, 11.0, 10.0, 8.0, 25.0],
        freq="1D", start="2023-01-01",
    )


def _build_h1_through_choch():
    """Bars 0-33: identical to the locked Model-A happy-path fixture, up
    through CHoCH confirmation at index 33."""
    opens  = [7.0]*14 + [7.0, 6.8, 6.9, 6.85, 6.2, 7.4, 8.4, 9.4, 10.0, 10.0,
                          9.9, 9.2, 9.3, 9.4, 8.5, 9.6, 10.2, 10.3, 10.0, 10.25]
    highs  = [7.2]*14 + [7.1, 7.0, 7.0, 6.9, 7.5, 8.5, 9.5, 10.1, 10.2, 10.2,
                          10.0, 9.5, 9.6, 9.5, 9.8, 10.3, 10.5, 10.4, 10.35, 10.8]
    lows   = [6.8]*14 + [6.5, 6.7, 6.75, 6.0, 6.1, 7.3, 8.3, 9.3, 9.8, 9.7,
                          9.0, 9.1, 9.2, 8.0, 8.4, 10.0, 10.1, 10.0, 10.0, 10.2]
    closes = [7.0]*14 + [6.8, 6.9, 6.85, 6.2, 7.4, 8.4, 9.4, 10.0, 10.0, 9.9,
                          9.2, 9.3, 9.4, 8.5, 9.6, 10.2, 10.3, 10.2, 10.25, 10.7]
    return opens, highs, lows, closes


def _build_h1_extended_for_model_b():
    """Bars 0-33 unchanged, then 9 new bars (34-42) engineered to produce:
    - a swing high at idx36 (high=12.0) confirmed ~idx38, acting as SH1
    - a swing low at idx39 (low=9.0) confirmed ~idx41, acting as the IDM
      candidate between SH1 and the BOS bar
    - a close above 12.0 at idx42 (close=12.8), acting as Model B's BOS
    """
    opens, highs, lows, closes = _build_h1_through_choch()

    opens  += [10.7, 10.8, 10.9, 11.8, 11.2, 11.0, 9.5, 9.8, 10.0]
    highs  += [10.9, 11.0, 12.0, 11.9, 11.3, 11.1, 10.0, 10.2, 13.0]
    lows   += [10.6, 10.7, 10.8, 11.0, 10.9, 9.0,  9.4, 9.6, 9.9]
    closes += [10.8, 10.9, 11.8, 11.2, 11.0, 9.5,  9.8, 10.0, 12.8]

    return _mk_df(opens, highs, lows, closes, freq="1h", start="2023-02-01")


def _build_h4_zone_bullish():
    h4_zones = pd.DataFrame([
        {"direction": "bullish", "zone_low": 10.0, "zone_high": 10.5,
         "confirm_time": pd.Timestamp("2023-01-05", tz="UTC"), "invalidated_at": pd.NaT},
    ])
    h4_zones["invalidated_at"] = pd.to_datetime(h4_zones["invalidated_at"], utc=True)
    return h4_zones


def _build_empty_d1_zones():
    d1_zones = pd.DataFrame(columns=["direction", "zone_low", "zone_high", "confirm_time", "invalidated_at"])
    d1_zones["confirm_time"] = pd.to_datetime(d1_zones["confirm_time"], utc=True)
    d1_zones["invalidated_at"] = pd.to_datetime(d1_zones["invalidated_at"], utc=True)
    return d1_zones


def _build_m15_flat_noise(n=20, start="2023-02-02 03:00"):
    """Deliberately flat -- no price variation means no M15 swing can ever
    form, so _model_a()'s `cand` is always empty and it returns None,
    regardless of window timing. This isolates the test to Model B only."""
    opens  = [100.0] * n
    highs  = [100.1] * n
    lows   = [99.9] * n
    closes = [100.0] * n
    return _mk_df(opens, highs, lows, closes, freq="15min", start=start)


def test_pairsetup_model_b_arming_diagnostic():
    d1_df = _build_d1_bullish_happy()
    opens, highs, lows, closes = _build_h1_through_choch()
    h1_df_choch_only = _mk_df(opens, highs, lows, closes, freq="1h", start="2023-02-01")

    pools = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 9.0,
         "confirm_time": h1_df_choch_only["timestamp"].iloc[5], "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    ps = setups.PairSetup("nzdusd")

    ps.on_d1_close(d1_df, _build_empty_d1_zones(), _build_h4_zone_bullish(), current_low=10.1, current_high=10.3)
    print(f"\nAfter D1: state={ps.state} bias={ps.bias}")

    for i in range(len(h1_df_choch_only)):
        ps.on_h1_close(h1_df_choch_only.iloc[:i + 1], pools, tf_h1)

    print(f"After H1 loop (through index 33): state={ps.state}")
    print(f"candidate_ob: {ps.candidate_ob}")
    print(f"h1_choch_event: {ps.h1_choch_event}")

    assert True  # diagnostic checkpoint -- confirm we reach CHOCH_SEEN before proceeding

    h1_df_extended = _build_h1_extended_for_model_b()
    m15_df = _build_m15_flat_noise()

    from src.research import primitives
    swings_check = primitives.find_swings(h1_df_extended, 2, tf_h1)
    print("\n=== Extended H1 swings (checking SH1 / IDM candidates exist) ===")
    print(swings_check[swings_check["timestamp"] >= pd.Timestamp("2023-02-02 10:00:00", tz="UTC")].to_string())

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df_extended, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(f"\n[m15 step {i}, ts={m15_df['timestamp'].iloc[i]}] "
              f"state={ps.state} model={ps.model} "
              f"m15_bos_time={ps.m15_bos_time} idm_price={ps.idm_price} idm_time={ps.idm_time} "
              f"idm_swept_time={ps.idm_swept_time} touch_time={ps.touch_time} "
              f"same_bar_ambiguous={ps.same_bar_ambiguous} invalid_h1_close_through={ps.invalid_h1_close_through}")

    print(f"\n=== FINAL: state={ps.state} model={ps.model} ===")
    assert True  # diagnostic only -- exact assertions derived from real CI output next
