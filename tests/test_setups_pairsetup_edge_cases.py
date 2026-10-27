import pandas as pd
from src.research import setups
from conftest import _mk_df


# ---------- Scenario A: bearish mirror of the bullish happy path ----------

def _build_d1_bearish():
    return _mk_df(
        opens=[20.5, 21.5, 22.5, 25.0, 22.0, 21.0, 20.0, 15.0, 20.0, 21.0, 23.0, 5.5],
        highs=[21, 22, 23, 27, 23, 22, 21, 21, 22, 23, 27, 6],
        lows=[20, 21, 22, 24, 19, 18, 17, 10, 17, 18, 19, 4],
        closes=[20.5, 21.5, 22.5, 25.5, 21.0, 20.0, 19.0, 14.0, 19.0, 20.0, 22.0, 5.0],
        freq="1D", start="2023-01-01",
    )


def _build_h1_bearish():
    opens  = [13.0]*14 + [13.0, 13.2, 13.1, 13.15, 13.8, 12.6, 11.6, 10.6, 10.0, 10.0,
                          10.1, 10.8, 10.7, 10.6, 11.5, 10.4, 9.8, 9.7, 10.0, 9.75]
    highs  = [13.2]*14 + [13.5, 13.3, 13.25, 14.0, 13.9, 12.7, 11.7, 10.7, 10.2, 10.3,
                          11.0, 10.9, 10.8, 12.0, 11.6, 10.0, 9.9, 10.0, 10.0, 9.8]
    lows   = [12.8]*14 + [12.9, 13.0, 13.0, 13.1, 12.5, 11.5, 10.5, 9.9, 9.8, 9.8,
                          10.0, 10.5, 10.4, 10.5, 10.2, 9.7, 9.5, 9.6, 9.65, 9.2]
    closes = [13.0]*14 + [13.2, 13.1, 13.15, 13.8, 12.6, 11.6, 10.6, 10.0, 10.0, 10.1,
                          10.8, 10.7, 10.6, 11.5, 10.4, 9.8, 9.7, 9.8, 9.75, 9.3]
    return _mk_df(opens, highs, lows, closes, freq="1h", start="2023-02-01")


def _build_m15_bearish():
    opens  = [100, 100, 101, 104, 103, 102, 101.5, 101.2, 96, 95.8, 95.5]
    highs  = [101, 102, 105, 104, 103.5, 102.5, 102, 101.5, 97, 96.5, 96]
    lows   = [99, 99, 100, 102, 101, 101, 101, 95, 95.5, 95.2, 94]
    closes = [100, 101, 104, 103, 102, 101.5, 101.2, 96, 95.8, 95.5, 94.2]
    return _mk_df(opens, highs, lows, closes, freq="15min", start="2023-02-02 03:00")


def test_pairsetup_model_a_bearish_mirror_diagnostic():
    d1_df = _build_d1_bearish()
    h1_df = _build_h1_bearish()
    m15_df = _build_m15_bearish()

    d1_zones = pd.DataFrame(columns=["direction", "zone_low", "zone_high", "confirm_time", "invalidated_at"])
    d1_zones["confirm_time"] = pd.to_datetime(d1_zones["confirm_time"], utc=True)
    d1_zones["invalidated_at"] = pd.to_datetime(d1_zones["invalidated_at"], utc=True)

    h4_zones = pd.DataFrame([
        {"direction": "bearish", "zone_low": 9.5, "zone_high": 10.0,
         "confirm_time": pd.Timestamp("2023-01-05", tz="UTC"), "invalidated_at": pd.NaT},
    ])
    h4_zones["invalidated_at"] = pd.to_datetime(h4_zones["invalidated_at"], utc=True)

    pools = pd.DataFrame([
        {"pool_type": "swing", "side": "high", "pool_price": 11.0,
         "confirm_time": h1_df["timestamp"].iloc[5], "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    ps = setups.PairSetup("gbpusd")

    ps.on_d1_close(d1_df, d1_zones, h4_zones, current_low=9.7, current_high=9.9)
    print("[BEAR] AFTER D1: state=", ps.state, "bias=", ps.bias, "zone=", ps.zone)

    for i in range(len(h1_df)):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        print(f"[BEAR] H1 bar {i} ts={h1_df['timestamp'].iloc[i]} close={h1_df['close'].iloc[i]} -> state={ps.state}")
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
                  "direction=", ps.candidate_ob["direction"],
                  "valid_pretouch=", ps.candidate_ob["valid_pretouch"])

    print("[BEAR] STATE BEFORE M15 LOOP:", ps.state)

    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(f"[BEAR] M15 bar {i} ts={m15_df['timestamp'].iloc[i]} close={m15_df['close'].iloc[i]} -> state={ps.state}")
        if ps.state == "ARMED":
            print("   ARMED! m15_bos_time=", ps.m15_bos_time, "idm_price=", ps.idm_price, "idm_time=", ps.idm_time)
            print("   idm_swept_time=", ps.idm_swept_time, "touch_time=", ps.touch_time,
                  "same_bar_ambiguous=", ps.same_bar_ambiguous,
                  "invalid_h1_close_through=", ps.invalid_h1_close_through)

    assert True


# ---------- Scenario B: CHoCH fires but no matching pool -> expect reset to IDLE ----------

def _build_d1_bullish_happy():
    return _mk_df(
        opens=[9.5, 8.5, 7.5, 5.0, 8.0, 9.0, 10.0, 15.0, 10.0, 9.0, 7.0, 24.5],
        highs=[10, 9, 8, 6, 11, 12, 13, 20, 13, 12, 11, 26],
        lows=[9, 8, 7, 3, 7, 8, 9, 9, 8, 7, 3, 24],
        closes=[9.5, 8.5, 7.5, 4.5, 9.0, 10.0, 11.0, 16.0, 11.0, 10.0, 8.0, 25.0],
        freq="1D", start="2023-01-01",
    )


def _build_h1_happy():
    opens  = [7.0]*14 + [7.0, 6.8, 6.9, 6.85, 6.2, 7.4, 8.4, 9.4, 10.0, 10.0,
                          9.9, 9.2, 9.3, 9.4, 8.5, 9.6, 10.2, 10.3, 10.0, 10.25]
    highs  = [7.2]*14 + [7.1, 7.0, 7.0, 6.9, 7.5, 8.5, 9.5, 10.1, 10.2, 10.2,
                          10.0, 9.5, 9.6, 9.5, 9.8, 10.3, 10.5, 10.4, 10.35, 10.8]
    lows   = [6.8]*14 + [6.5, 6.7, 6.75, 6.0, 6.1, 7.3, 8.3, 9.3, 9.8, 9.7,
                          9.0, 9.1, 9.2, 8.0, 8.4, 10.0, 10.1, 10.0, 10.0, 10.2]
    closes = [7.0]*14 + [6.8, 6.9, 6.85, 6.2, 7.4, 8.4, 9.4, 10.0, 10.0, 9.9,
                          9.2, 9.3, 9.4, 8.5, 9.6, 10.2, 10.3, 10.2, 10.25, 10.7]
    return _mk_df(opens, highs, lows, closes, freq="1h", start="2023-02-01")


def _build_h4_zone_bullish():
    h4_zones = pd.DataFrame([
        {"direction": "bullish", "zone_low": 10.0, "zone_high": 10.5,
         "confirm_time": pd.Timestamp("2023-01-05", tz="UTC"), "invalidated_at": pd.NaT},
    ])
    h4_zones["invalidated_at"] = pd.to_datetime(h4_zones["invalidated_at"], utc=True)
    return h4_zones


def _build_empty_d1_zones():
    d1_zones = pd.DataFrame(columns=["direction", "zone_low", "zone_high", "confirm_time", "invalidated_at"])
    d1_zones["confirm_time"] = pd.to_datetime(d1_zones["confirm_time"], utc=True)
    d1_zones["invalidated_at"] = pd.to_datetime(d1_zones["invalidated_at"], utc=True)
    return d1_zones


def test_pairsetup_resets_when_no_matching_pool_diagnostic():
    d1_df = _build_d1_bullish_happy()
    h1_df = _build_h1_happy()

    pools = pd.DataFrame(columns=["pool_type", "side", "pool_price", "confirm_time", "swept_time", "expires_at"])
    pools["confirm_time"] = pd.to_datetime(pools["confirm_time"], utc=True)
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    tf_h1 = pd.Timedelta(hours=1)
    ps = setups.PairSetup("audusd")

    ps.on_d1_close(d1_df, _build_empty_d1_zones(), _build_h4_zone_bullish(), current_low=10.1, current_high=10.3)
    print("[RESET] AFTER D1: state=", ps.state)

    for i in range(len(h1_df)):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)
        print(f"[RESET] H1 bar {i} ts={h1_df['timestamp'].iloc[i]} -> state={ps.state}")
        if i == 33:
            print("   AFTER BAR33: episode_start_time=", ps.episode_start_time,
                  "h1_bos_event=", None if ps.h1_bos_event is None else ps.h1_bos_event["time"],
                  "h1_choch_event=", None if ps.h1_choch_event is None else ps.h1_choch_event["time"],
                  "candidate_ob=", ps.candidate_ob)

    print("[RESET] FINAL STATE:", ps.state)
    assert True


# ---------- Scenario C: CHoCH_SEEN reached, Model A never resolves -> stuck? ----------

def _build_m15_flat_noise():
    opens  = [100, 100, 100, 100, 100]
    highs  = [100.1, 100.1, 100.1, 100.1, 100.1]
    lows   = [99.9, 99.9, 99.9, 99.9, 99.9]
    closes = [100, 100, 100, 100, 100]
    return _mk_df(opens, highs, lows, closes, freq="15min", start="2023-02-02 10:15")


def test_pairsetup_stuck_in_choch_seen_when_model_a_unresolved_diagnostic():
    d1_df = _build_d1_bullish_happy()
    h1_df = _build_h1_happy()

    pools = pd.DataFrame([
        {"pool_type": "swing", "side": "low", "pool_price": 9.0,
         "confirm_time": h1_df["timestamp"].iloc[5], "swept_time": pd.NaT, "expires_at": pd.NaT},
    ])
    pools["swept_time"] = pd.to_datetime(pools["swept_time"], utc=True)
    pools["expires_at"] = pd.to_datetime(pools["expires_at"], utc=True)

    tf_h1 = pd.Timedelta(hours=1)
    tf_m15 = pd.Timedelta(minutes=15)

    ps = setups.PairSetup("usdjpy")

    ps.on_d1_close(d1_df, _build_empty_d1_zones(), _build_h4_zone_bullish(), current_low=10.1, current_high=10.3)

    for i in range(len(h1_df)):
        ps.on_h1_close(h1_df.iloc[:i + 1], pools, tf_h1)

    print("[STUCK] STATE BEFORE M15 LOOP:", ps.state)

    m15_df = _build_m15_flat_noise()
    for i in range(len(m15_df)):
        ps.on_m15_close(h1_df, m15_df.iloc[:i + 1], tf_h1, tf_m15)
        print(f"[STUCK] M15 bar {i} ts={m15_df['timestamp'].iloc[i]} -> state={ps.state}")

    print("[STUCK] FINAL STATE:", ps.state)
    assert True
