import pandas as pd
from src.research import primitives, zones
from conftest import _mk_df


def test_diagnostic_print_ob_fields_with_real_fvg():
    warmup_n = 15
    opens  = [17.0] * warmup_n + [16.5, 16, 15.5, 15.5, 10, 12.5, 9, 17.0]
    highs  = [20.0] * warmup_n + [17, 16, 17, 16.5, 16, 16, 17, 17.5]
    lows   = [14.0] * warmup_n + [15, 11, 14, 10, 12, 8, 11, 17.0]
    closes = [17.0] * warmup_n + [16, 15, 16, 10, 13, 9, 16, 17.2]

    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)
    obs = zones.detect_order_blocks(df, tf, events)
    print("\n--- OBS WITH REAL FVG ---")
    print(obs.to_string())
    assert True
