"""
Locks PairSetup's Model B (H1-only) arming path with real exact-value
assertions, derived from real CI output (not hand-traced). Proves, for the
first time, that state can reach ARMED with model == "B" when Model A
cannot resolve (flat M15 data guarantees no M15 swing can ever form).

Reuses the locked Model-A happy-path D1/H1 fixtures through CHoCH
(index 33), then extends h1_df with 9 further bars producing a genuine
Model B SH1 -> IDM -> BOS sequence per zones.find_inducement's _model_b().
"""

import pandas as pd
import pytest
from src.research import setups
from src.research import primitives
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
    opens  = [100.0] * n
    highs  = [100.1] * n
    lows   = [99.9] * n
    closes = [100.0] * n
    return _mk_df(opens, highs, lows, closes, freq="15min", start=start)


def test_pairsetup_model_b_arming():
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
    assert ps.state == "IDLE"
    assert ps.bias["state"] == "bullish"
    assert ps.bias["direction"] == "up"

    for i in range(len(h1_df_choch_only)):
        ps.on_h1_close(h1_df_choch_only.iloc[:i + 1], pools, tf_h1)

    assert ps.state == "CHOCH_SEEN"
    assert ps.candidate_ob["bos_time"] == pd.Timestamp("2023-02-02 04:00:00", tz="UTC")
    assert ps.candidate_ob["choch_time"] == pd.Timestamp("2023-02-02 10:00:00", tz="UTC")
    assert ps.candidate_ob["l_base_time"] == pd.Timestamp("2023-02-02 03:00:00", tz="UTC")
    assert ps.candidate_ob["l_base_price"] == pytest.approx(8.0)
    assert ps.candidate_ob["ob_low"] == pytest.approx(8.0)
    assert ps.candidate_ob["ob_high"] == pytest.approx(9.5)
    assert ps.candidate_ob["direction"] == "bullish"
    assert ps.candidate_ob["valid_pretouch"] == True

    h1_df_extended = _build_h1_extended_for_model_b()
    m15_df = _build_m15_flat_noise()

    # Sanity-check the extended fixture actually produces the intended
    # SH1 / IDM candidate swings (derived from real CI output, not guessed).
    swings_check = primitives.find_swings(h1_df_extended, 2, tf_h1)
    post_choch = swings_check[swings_check["timestamp"] >= pd.Timestamp("2023-02-02 10:00:00", tz="UTC")]
    sh1_rows = post_choch[post_choch["kind"] == "high"]
    idm_rows = post_choch[post_choch["kind"] == "low"]
    assert len(sh1_rows) == 1
    assert sh1_rows.iloc[0]["price"] == pytest.approx(12.0)
    assert sh1_rows.iloc[0]["confirm_time"] == pd.Timestamp("2023-02-02 15:00:00", tz="UTC")
    assert len(idm_rows) == 1
    assert idm_rows.iloc[0]["price"] == pytest.approx(9.0)
    assert idm_rows.iloc[0]["confirm_time"] == pd.Timestamp("2023-02-02 18:00:00", tz="UTC")

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df_extended, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        # Resolves on the very first M15 step: Model B depends only on H1
        # data (passed whole, not incrementally sliced), and the flat M15
        # fixture guarantees Model A's swing search is always empty.
        assert ps.state == "ARMED"
        assert ps.model == "B"
        assert ps.m15_bos_time == pd.Timestamp("2023-02-02 19:00:00", tz="UTC")
        assert ps.idm_price == pytest.approx(9.0)
        assert ps.idm_time == pd.Timestamp("2023-02-02 18:00:00", tz="UTC")
        assert pd.isna(ps.idm_swept_time)
        assert pd.isna(ps.touch_time)
        assert ps.same_bar_ambiguous == False
        assert ps.invalid_h1_close_through == False
