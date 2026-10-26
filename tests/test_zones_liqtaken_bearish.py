import pandas as pd
import pytest
from src.research import zones
from conftest import _mk_df


def test_find_liquidity_taken_bearish_matches_pool():
    pools = pd.DataFrame([
        {"pool_type": "swing_high_A", "side": "high", "pool_price": 8.0,
         "confirm_time": pd.Timestamp("2023-01-01 05:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.Timestamp("2023-01-05 00:00:00", tz="UTC")},
        {"pool_type": "swing_high_B", "side": "high", "pool_price": 12.0,
         "confirm_time": pd.Timestamp("2023-01-01 06:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.Timestamp("2023-01-05 00:00:00", tz="UTC")},
        {"pool_type": "swing_low_C", "side": "low", "pool_price": 5.0,
         "confirm_time": pd.Timestamp("2023-01-01 05:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.Timestamp("2023-01-05 00:00:00", tz="UTC")},
    ])
    pools["confirm_time"] = pd.to_datetime(pools["confirm_time"], utc=True)
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    bos_open_time = pd.Timestamp("2023-01-01 09:00:00", tz="UTC")
    l_base_price = 9.0
    atr_at_bos = 1.0
    ob_upper_edge = 8.5

    result = zones.find_liquidity_taken(pools, bos_open_time, l_base_price, "bearish",
                                         atr_at_bos=atr_at_bos, ob_upper_edge=ob_upper_edge)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["pool_type"] == "swing_high_A"
    assert row["pool_price"] == 8.0
    assert row["depth"] == pytest.approx(1.0)
    assert row["depth_atr"] == pytest.approx(1.0)
    assert row["distance_atr"] == pytest.approx(0.5)
