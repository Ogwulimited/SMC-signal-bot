import pandas as pd
from src.research import zones
from conftest import _mk_df


def test_diagnostic_print_pdh_pdl_family():
    # H1 bars straddling the NY 5pm (22:00 UTC in EST) session boundary,
    # so the fixture spans two distinct "trading days" under the
    # NY-session bucketing rule.
    opens  = [1.0, 1.1, 1.3, 1.35, 1.5, 1.1]
    highs  = [1.2, 1.5, 1.4, 1.6, 1.45, 1.3]
    lows   = [0.9, 0.8, 1.0, 1.2, 0.95, 1.05]
    closes = [1.1, 1.3, 1.35, 1.5, 1.1, 1.2]
    df = _mk_df(opens, highs, lows, closes, freq="1h", start="2023-01-01 20:00")
    tf = pd.Timedelta(hours=1)

    print("\n--- PDH/PDL ---")
    print(zones.find_pdh_pdl(df, tf).to_string())

    print("\n--- PWH/PWL ---")
    print(zones.find_pwh_pwl(df, tf).to_string())

    print("\n--- PMH/PML ---")
    print(zones.find_pmh_pml(df, tf).to_string())

    assert True
