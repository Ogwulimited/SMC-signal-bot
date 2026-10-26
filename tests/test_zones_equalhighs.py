import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_find_equal_highs_clusters_close_peaks_excludes_isolated():
    n = 30
    opens = [9.0] * n
    highs = [9.5] * n
    lows = [8.5] * n
    closes = [9.0] * n
    highs[16] = 12.0
    highs[21] = 12.05
    highs[26] = 20.0
    df = _mk_df(opens, highs, lows, closes, freq="1h", start="2023-01-01")
    tf = pd.Timedelta(hours=1)

    result = zones.find_equal_highs(df, tf)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["pool_price"] == 12.05
    assert row["confirm_time"] == pd.Timestamp("2023-01-02 00:00:00", tz="UTC")
    assert pd.isna(row["expires_at"])
    assert pd.isna(row["swept_time"])
    assert row["cluster_size"] == 2
    assert row["member_indexes"] == [16, 21]
    assert row["side"] == "high"
    assert row["pool_type"] == "equal_highs"
