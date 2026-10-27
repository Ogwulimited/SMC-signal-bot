import pandas as pd
import pytest
from src.research import primitives, zones, setups
from conftest import _mk_df


def _build_fixture():
    warmup_n = 15
    opens  = [17.0] * warmup_n + [16.5, 16, 15.5, 15.5, 10, 12.5, 9, 17.0]
    highs  = [20.0] * warmup_n + [17, 16, 17, 16.5, 16, 16, 17, 17.5]
    lows   = [14.0] * warmup_n + [15, 11, 14, 10, 12, 8, 11, 17.0]
    closes = [17.0] * warmup_n + [16, 15, 16, 10, 13, 9, 16, 17.2]

    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)
    return df, tf, events


def test_find_candidate_obs_keeps_setup_with_matching_pool():
    df, tf, events = _build_fixture()

    pools = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 9.0,
         "confirm_time": pd.Timestamp("2023-01-01 10:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools["confirm_time"] = pd.to_datetime(pools["confirm_time"], utc=True)
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    result = setups.find_candidate_obs(df, tf, events, pools)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["direction"] == "bullish"
    assert row["l_base_price"] == 8.0
    assert row["ob_low"] == 8.0
    assert row["ob_high"] == 16.0
    assert row["valid_pretouch"] == True
    assert len(row["liquidity_pools"]) == 1
    pool = row["liquidity_pools"][0]
    assert pool["pool_type"] == "swing"
    assert pool["pool_price"] == 9.0
    assert pool["depth"] == pytest.approx(1.0)
    assert pool["depth_atr"] == pytest.approx(0.1830065359477124)
    assert pool["distance_atr"] == pytest.approx(1.2810457516339868)


def test_find_candidate_obs_drops_setup_with_no_matching_pool():
    df, tf, events = _build_fixture()

    pools = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 5.0,
         "confirm_time": pd.Timestamp("2023-01-01 10:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools["confirm_time"] = pd.to_datetime(pools["confirm_time"], utc=True)
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    result = setups.find_candidate_obs(df, tf, events, pools)

    assert result.empty
