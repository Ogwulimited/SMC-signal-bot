import pandas as pd
from src.research import setups
from conftest import _mk_df


def test_diagnostic_print_d1_bias():
    d1 = _mk_df(
        opens=[9.5, 8.5, 7.5, 5.0, 8.0, 9.0, 10.0, 15.0, 10.0, 9.0, 7.0, 24.5, 15.0, 3.0],
        highs=[10, 9, 8, 6, 11, 12, 13, 20, 13, 12, 11, 26, 16, 3.5],
        lows=[9, 8, 7, 3, 7, 8, 9, 9, 8, 7, 3, 24, 14, 0.5],
        closes=[9.5, 8.5, 7.5, 4.5, 9.0, 10.0, 11.0, 16.0, 11.0, 10.0, 8.0, 25.0, 15.0, 1.0],
        freq="1D", start="2023-01-01",
    )

    bias_partial = setups.compute_d1_bias(d1.iloc[:12].reset_index(drop=True))
    print("\n--- D1 BIAS AFTER BAR 11 (expect bullish) ---")
    print(bias_partial)

    bias_full = setups.compute_d1_bias(d1)
    print("\n--- D1 BIAS AFTER BAR 13 (expect reversing) ---")
    print(bias_full)

    assert True
