import pandas as pd
from src.research import primitives, zones, setups
from conftest import _mk_df


def test_diagnostic_print_find_candidate_obs():
    warmup_n = 15
    opens  = [17.0] * warmup_n + [16.5, 16, 15.5, 15.5, 10, 12.5, 9, 17.0]
    highs  = [20.0] * warmup_n + [17, 16, 17, 16.5, 16, 16, 17, 17.5]
    lows   = [14.0] * warmup_n + [15, 11, 14, 10, 12, 8, 11, 17.0]
    closes = [17.0] * warmup_n + [16, 15, 16, 10, 13, 9, 16, 17.2]

    df = _mk_df(opens, highs, lows, closes)
    tf = pd.Timedelta(hours=1)
    swings = primitives.find_swings(df, n=1, tf=tf)
    events = primitives.detect_bos_choch(df, swings, tf)

    pools_match = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 9.0,
         "confirm_time": pd.Timestamp("2023-01-01 10:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools_match["confirm_time"] = pd.to_datetime(pools_match["confirm_time"], utc=True)
    pools_match["swept_time"] = pd.to_datetime(pools_match["swept_time"], utc=True)
    pools_match["expires_at"] = pd.to_datetime(pools_match["expires_at"], utc=True)

    result_match = setups.find_candidate_obs(df, tf, events, pools_match)
    print("\n--- CANDIDATE OBS WITH MATCHING POOL ---")
    print(result_match.to_string())

    pools_nomatch = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 5.0,
         "confirm_time": pd.Timestamp("2023-01-01 10:00:00", tz="UTC"),
         "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools_nomatch["confirm_time"] = pd.to_datetime(pools_nomatch["confirm_time"], utc=True)
    pools_nomatch["swept_time"] = pd.to_datetime(pools_nomatch["swept_time"], utc=True)
    pools_nomatch["expires_at"] = pd.to_datetime(pools_nomatch["expires_at"], utc=True)

    result_nomatch = setups.find_candidate_obs(df, tf, events, pools_nomatch)
    print("\n--- CANDIDATE OBS WITH NO MATCHING POOL ---")
    print(result_nomatch.to_string())

    assert True
