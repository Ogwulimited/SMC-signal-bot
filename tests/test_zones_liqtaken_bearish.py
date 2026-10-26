import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_find_liquidity_taken_bearish():
    pools = pd.DataFrame([
        {"pool_type": "swing_high_A", "side": "high", "pool_price": 10.0,
         "confirm_time": pd.Timestamp("2023-01-01 05:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.Timestamp("2023-01-05 00:00:00", tz="UTC")},
        {"pool_type": "swing_high_B", "side": "high", "pool_price": 12.0,
         "confirm_time": pd.Timestamp("2023-01-01 06:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.Timestamp("2023-01-05 00:00:00", tz="UTC")},
        {"pool_type": "swing_low_C", "side": "low", "pool_price": 5.0,
         "confirm_time": pd.Timestamp("2023-01-01 05:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.Timestamp("2023-01-05 00:00:00", tz="UTC")},
    ])

    bos_open_time = pd.Timestamp("2023-01-01 09:00:00", tz="UTC")
    l_base_price = 9.0
    atr_at_bos = 1.0
    ob_upper_edge = 9.5

    result = zones.find_liquidity_taken(pools, bos_open_time, l_base_price, "bearish",
                                         atr_at_bos=atr_at_bos, ob_upper_edge=ob_upper_edge)
    print("\n--- LIQUIDITY_TAKEN BEARISH ---")
    print(result.to_string())
    assert True
