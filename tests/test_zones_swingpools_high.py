import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_find_swing_pools_high():
    tf = pd.Timedelta(hours=1)

    df = _mk_df(
        opens=[10.0, 10.2, 10.5, 10.8, 10.5, 10.2, 10.0],
        highs=[10.3, 10.6, 10.9, 11.5, 10.9, 10.6, 10.3],
        lows=[9.8, 10.0, 10.3, 10.5, 10.3, 10.0, 9.8],
        closes=[10.2, 10.5, 10.8, 11.0, 10.6, 10.3, 10.1],
        freq="1h", start="2023-01-01 00:00:00",
    )

    result = zones.find_swing_pools(df, tf, "H1", "high")
    print("\n--- SWING POOLS HIGH ---")
    print(result.to_string())
    assert True
