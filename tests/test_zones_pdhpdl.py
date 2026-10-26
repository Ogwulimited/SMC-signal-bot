import pandas as pd
from src.research import zones
from conftest import _mk_df


def _make_fixture():
    opens  = [1.0, 1.1, 1.3, 1.35, 1.5, 1.1]
    highs  = [1.2, 1.5, 1.4, 1.6, 1.45, 1.3]
    lows   = [0.9, 0.8, 1.0, 1.2, 0.95, 1.05]
    closes = [1.1, 1.3, 1.35, 1.5, 1.1, 1.2]
    df = _mk_df(opens, highs, lows, closes, freq="1h", start="2023-01-01 20:00")
    return df


def test_find_pdh_pdl_splits_by_ny_day():
    df = _make_fixture()
    tf = pd.Timedelta(hours=1)
    result = zones.find_pdh_pdl(df, tf)

    assert len(result) == 4

    r0 = result.iloc[0]
    assert r0["bucket"] == "2022-12-31"
    assert r0["side"] == "high"
    assert r0["pool_price"] == 1.5
    assert r0["confirm_time"] == pd.Timestamp("2023-01-01 22:00:00", tz="UTC")
    assert r0["expires_at"] == pd.Timestamp("2023-01-04 22:00:00", tz="UTC")
    assert pd.isna(r0["swept_time"])
    assert r0["pool_type"] == "PDH"

    r1 = result.iloc[1]
    assert r1["bucket"] == "2022-12-31"
    assert r1["side"] == "low"
    assert r1["pool_price"] == 0.8
    assert r1["confirm_time"] == pd.Timestamp("2023-01-01 22:00:00", tz="UTC")
    assert r1["expires_at"] == pd.Timestamp("2023-01-04 22:00:00", tz="UTC")
    assert r1["pool_type"] == "PDL"

    r2 = result.iloc[2]
    assert r2["bucket"] == "2023-01-01"
    assert r2["side"] == "high"
    assert r2["pool_price"] == 1.6
    assert r2["confirm_time"] == pd.Timestamp("2023-01-02 02:00:00", tz="UTC")
    assert r2["expires_at"] == pd.Timestamp("2023-01-05 02:00:00", tz="UTC")
    assert r2["pool_type"] == "PDH"

    r3 = result.iloc[3]
    assert r3["bucket"] == "2023-01-01"
    assert r3["side"] == "low"
    assert r3["pool_price"] == 0.95
    assert r3["confirm_time"] == pd.Timestamp("2023-01-02 02:00:00", tz="UTC")
    assert r3["expires_at"] == pd.Timestamp("2023-01-05 02:00:00", tz="UTC")
    assert r3["pool_type"] == "PDL"


def test_find_pwh_pwl_single_week_bucket():
    df = _make_fixture()
    tf = pd.Timedelta(hours=1)
    result = zones.find_pwh_pwl(df, tf)

    assert len(result) == 2

    r0 = result.iloc[0]
    assert r0["bucket"] == "2022-W52"
    assert r0["side"] == "high"
    assert r0["pool_price"] == 1.6
    assert r0["confirm_time"] == pd.Timestamp("2023-01-02 02:00:00", tz="UTC")
    assert r0["expires_at"] == pd.Timestamp("2023-01-16 02:00:00", tz="UTC")
    assert r0["pool_type"] == "PWH"

    r1 = result.iloc[1]
    assert r1["bucket"] == "2022-W52"
    assert r1["side"] == "low"
    assert r1["pool_price"] == 0.8
    assert r1["confirm_time"] == pd.Timestamp("2023-01-02 02:00:00", tz="UTC")
    assert r1["expires_at"] == pd.Timestamp("2023-01-16 02:00:00", tz="UTC")
    assert r1["pool_type"] == "PWL"


def test_find_pmh_pml_single_month_bucket():
    df = _make_fixture()
    tf = pd.Timedelta(hours=1)
    result = zones.find_pmh_pml(df, tf)

    assert len(result) == 2

    r0 = result.iloc[0]
    assert r0["bucket"] == "2023-01"
    assert r0["side"] == "high"
    assert r0["pool_price"] == 1.6
    assert r0["confirm_time"] == pd.Timestamp("2023-01-02 02:00:00", tz="UTC")
    assert r0["expires_at"] == pd.Timestamp("2023-03-02 02:00:00", tz="UTC")
    assert r0["pool_type"] == "PMH"

    r1 = result.iloc[1]
    assert r1["bucket"] == "2023-01"
    assert r1["side"] == "low"
    assert r1["pool_price"] == 0.8
    assert r1["confirm_time"] == pd.Timestamp("2023-01-02 02:00:00", tz="UTC")
    assert r1["expires_at"] == pd.Timestamp("2023-03-02 02:00:00", tz="UTC")
    assert r1["pool_type"] == "PML"
