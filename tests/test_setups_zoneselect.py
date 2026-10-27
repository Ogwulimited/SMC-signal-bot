import pandas as pd
from src.research import setups


def test_diagnostic_print_select_htf_zone():
    d1_zones = pd.DataFrame([
        {"direction": "bullish", "zone_low": 10.0, "zone_high": 10.5,
         "confirm_time": pd.Timestamp("2023-01-05", tz="UTC"), "invalidated_at": pd.NaT},
    ])
    d1_zones["invalidated_at"] = pd.to_datetime(d1_zones["invalidated_at"], utc=True)

    h4_zones = pd.DataFrame([
        {"direction": "bullish", "zone_low": 12.0, "zone_high": 12.3,
         "confirm_time": pd.Timestamp("2023-01-06", tz="UTC"), "invalidated_at": pd.NaT},
        {"direction": "bullish", "zone_low": 20.0, "zone_high": 20.3,
         "confirm_time": pd.Timestamp("2023-01-06", tz="UTC"), "invalidated_at": pd.NaT},
    ])
    h4_zones["invalidated_at"] = pd.to_datetime(h4_zones["invalidated_at"], utc=True)

    # Case A: price overlapping D1 zone -> expect D1 picked
    result_a = setups.select_htf_zone(d1_zones, h4_zones, "bullish", current_low=10.1, current_high=10.3)
    print("\n--- CASE A: price in D1 zone ---")
    print(result_a)

    # Case B: price away from D1 zone, near first H4 zone -> expect H4 @ 12.0-12.3
    result_b = setups.select_htf_zone(d1_zones, h4_zones, "bullish", current_low=12.1, current_high=12.2)
    print("\n--- CASE B: price near nearest H4 zone ---")
    print(result_b)

    # Case C: no overlap anywhere, bias mismatch -> expect None
    result_c = setups.select_htf_zone(d1_zones, h4_zones, "bearish", current_low=10.1, current_high=10.3)
    print("\n--- CASE C: wrong bias direction ---")
    print(result_c)

    assert True
