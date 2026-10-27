import pandas as pd
import pytest
from src.research import setups


def test_select_htf_zone_prefers_d1_when_price_overlaps():
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

    result = setups.select_htf_zone(d1_zones, h4_zones, "bullish", current_low=10.1, current_high=10.3)

    assert result["timeframe"] == "D1"
    assert result["zone_low"] == pytest.approx(10.0)
    assert result["zone_high"] == pytest.approx(10.5)
    assert result["confirm_time"] == pd.Timestamp("2023-01-05", tz="UTC")


def test_select_htf_zone_falls_back_to_nearest_h4():
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

    result = setups.select_htf_zone(d1_zones, h4_zones, "bullish", current_low=12.1, current_high=12.2)

    assert result["timeframe"] == "H4"
    assert result["zone_low"] == pytest.approx(12.0)
    assert result["zone_high"] == pytest.approx(12.3)
    assert result["confirm_time"] == pd.Timestamp("2023-01-06", tz="UTC")


def test_select_htf_zone_returns_none_on_bias_mismatch():
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

    result = setups.select_htf_zone(d1_zones, h4_zones, "bearish", current_low=10.1, current_high=10.3)

    assert result is None
