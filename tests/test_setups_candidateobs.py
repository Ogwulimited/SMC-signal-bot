import pandas as pd
from src.research import primitives, zones
from conftest import _mk_df


def test_diagnostic_print_ob_fields_for_known_bullish_fixture():
    highs  = [17, 16, 17, 16.5, 16, 16, 17, 17.5]
    lows   = [15, 11, 14, 10, 12, 8, 11, 15]
    closes = [16, 15, 16, 10, 13, 9, 16, 17.2]
    opens  = [16.5, 16, 15.5, 15.5, 10, 12.5, 9, 16]
    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)
    obs = zones.detect_order_blocks(df, tf, events)
    print("\n--- OBS FOR KNOWN BULLISH FIXTURE ---")
    print(obs.to_string())
    assert True
