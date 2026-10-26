import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_equal_highs():
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
    print("\n--- EQUAL_HIGHS ---")
    print(result.to_string())
    assert True
