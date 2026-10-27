import pandas as pd
from src.research import setups
from conftest import _mk_df


def _build_d1_fixture():
    return _mk_df(
        opens=[9.5, 8.5, 7.5, 5.0, 8.0, 9.0, 10.0, 15.0, 10.0, 9.0, 7.0, 24.5],
        highs=[10, 9, 8, 6, 11, 12, 13, 20, 13, 12, 11, 26],
        lows=[9, 8, 7, 3, 7, 8, 9, 9, 8, 7, 3, 24],
        closes=[9.5, 8.5, 7.5, 4.5, 9.0, 10.0, 11.0, 16.0, 11.0, 10.0, 8.0, 25.0],
        freq="1D", start="2023-01-01",
    )


def _build_h1_fixture():
    opens  = [7.0]*14 + [7.0, 6.8, 6.9, 6.85, 6.2, 7.4, 8.4, 9.4, 10.0, 10.0,
                          9.9, 9.2, 9.3, 9.4, 8.5, 9.6, 10.2, 10.3, 10.0, 10.25]
    highs  = [7.2]*14 + [7.1, 7.0, 7.0, 6.9, 7.5, 8.5, 9.5, 10.1, 10.2, 10.2,
                          10.0, 9.5, 9.6, 9.5, 9.8, 10.3, 10.5, 10.4, 10.35, 10.8]
    lows   = [6.8]*14 + [6.5, 6.7, 6.75, 6.0, 6.1, 7.3, 8.3, 9.3, 9.8, 9.7,
                          9.0, 9.1, 9.2, 8.0, 8.4, 10.0, 10.1, 10.0, 10.0, 10.2]
    closes = [7.0]*14 + [6.8, 6.9, 6.85, 6.2, 7.4, 8.4, 9.4, 10.0, 10.0, 9.9,
                          9.2, 9.3, 9.4, 8.5, 9.6, 10.2, 10.3, 10.2, 10.25, 10.7]
    return _mk_df(opens, highs, lows, closes, freq="1h", start="2023-02-01")


def _build_m15_fixture():
    opens  = [100, 100, 99, 96, 97, 98, 98.5, 98.8, 104, 104.2, 104.5]
    highs  = [101, 101, 100, 98, 99, 99, 99, 105, 104.5, 104.8, 106]
    lows   = [99, 98, 95, 96, 96.5, 97.5, 98, 98.5, 103, 103.5, 104]
    closes = [100, 99, 96, 97, 98, 98.5, 98.8, 104, 104.2, 104.5, 105.8]
    return _mk_df(opens, highs, lows, closes, freq="15min", start="2023-02-02 03:00")


def test_pairsetup_model_a_diagnostic():
    d1_df = _build_d1_fixture()
    h1_df = _build_h1_fixture()
    m15_df = _build_m15_fixture()

    d1_zones = pd.DataFrame(columns=["direction", "zone_low", "zone_high", "confirm_time", "invalidated_at"])
    d1_zones["confirm_time"] = pd.to_datetime(d1_zones["confirm_time"], utc=True)
    d1_zones["invalidated_at"] = pd.to_datetime(d1_zones["invalidated_at"], utc=True)

    h4_zones = pd.DataFrame([
        {"direction": "bullish", "zone_low": 10.0, "zone_high": 10.5,
         "confirm_time": pd.Timestamp("2023-01-05", tz="UTC"), "invalidated_at": pd.NaT},
    ])
    h4_zones["invalidated_at"] = pd.to_datetime(h4_zones["invalidated_at"], utc=True)

    pools = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 9.0,
         "confirm_time": h1_df["timestamp"].iloc[5], "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    ps = setups.PairSetup("eurusd")

    ps.on_d1_close(d1_df, d1_zones, h4_zones, current_low=10.1, current_high=10.3)
    print("AFTER D1: state=", ps.state, "bias=", ps.bias, "zone=", ps.zone)

    for i in range(len(h1_df)):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        print(f"H1 bar {i} ts={h1_df['timestamp'].iloc[i]} close={h1_df['close'].iloc[i]} -> state={ps.state}")
        if ps.h1_bos_event is not None:
            print("   h1_bos_event time=", ps.h1_bos_event["time"],
                  "dir=", ps.h1_bos_event["direction"], "label=", ps.h1_bos_event["label"])
        if ps.h1_choch_event is not None:
            print("   h1_choch_event time=", ps.h1_choch_event["time"],
                  "dir=", ps.h1_choch_event["direction"], "label=", ps.h1_choch_event["label"])
        if ps.candidate_ob is not None:
            print("   candidate_ob l_base_time=", ps.candidate_ob["l_base_time"],
                  "l_base_price=", ps.candidate_ob["l_base_price"],
                  "ob_low=", ps.candidate_ob["ob_low"], "ob_high=", ps.candidate_ob["ob_high"],
                  "valid_pretouch=", ps.candidate_ob["valid_pretouch"])

    print("STATE BEFORE M15 LOOP:", ps.state)

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(f"M15 bar {i} ts={m15_df['timestamp'].iloc[i]} close={m15_df['close'].iloc[i]} -> state={ps.state}")
        if ps.state == "ARMED":
            print("   ARMED! m15_bos_time=", ps.m15_bos_time, "idm_price=", ps.idm_price, "idm_time=", ps.idm_time)
            print("   idm_swept_time=", ps.idm_swept_time, "touch_time=", ps.touch_time,
                  "same_bar_ambiguous=", ps.same_bar_ambiguous,
                  "invalid_h1_close_through=", ps.invalid_h1_close_through)

    assert True
