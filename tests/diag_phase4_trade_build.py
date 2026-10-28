"""
Diagnostic (print-only) test for build_trade_from_setup -- Phase 4.
Hand-derived predictions written BEFORE running CI.

SCENARIO 1 (OB winner, opened):
  h1_df: 20 hourly bars, all O=1.1000 H=1.1010 L=1.0990 C=1.1000 (constant
  true range 0.0020 every bar -> ATR(14) settles at exactly 0.0020).
  candidate_ob: bullish, ob_low=1.0950, ob_high=1.0970, ob_index=15.
  fill2_price=1.0975, touch_time=2023-01-31 23:45 UTC -> entry_time=00:00.
  stop = 1.0950 - 0.1*0.0020 = 1.0948. risk_r = 1.0975-1.0948 = 0.0027.
  spread(eurusd)=0.00010 -> spread_cost_r = 0.037037.
  Pools: near_test@1.1002 (r_gross=1.0, r_net=0.963 -> fails);
         far_test@1.1083 (r_gross=4.0, r_net=3.963 -> CHOSEN).
  t2_target = 1.0975 + 3*0.0027 = 1.1056.
  m15 path never hits stop (1.0948) or T1 (1.1083); hits T2 (1.1056) at
  bar index2 (high=1.1060).
  EXPECTED: status=opened, risk_r~=0.0027, spread_cost_r~=0.03704,
    t1_pool_type=far_test, t1_r_net~=3.963, skipped_no_t1=False,
    exit_reason_t1=time_stop, exit_price_t1=1.1050, r_result_t1~=2.778,
    exit_reason_t2=target, exit_price_t2=1.1056, r_result_t2~=3.0,
    ps.state after call == IDLE, ps.winner is None.

SCENARIO 2 (breaker winner, skipped_spread):
  br: bullish, limit_price=150.00, stop=149.90 -> risk_r=0.10.
  spread(gbpjpy)=0.030 -> spread_cost_r=0.30 > 0.15 -> SKIPPED.
  EXPECTED: status=skipped_spread, no t1/t2 fields computed,
    ps.state after call == IDLE, ps.winner is None.

SCENARIO 3 (breaker winner, opened):
  br: bullish, limit_price=1.1000, stop=1.0960 -> risk_r=0.0040.
  spread(eurusd)=0.00010 -> spread_cost_r=0.025.
  Pool: far_test@1.1200 (r_gross=5.0, r_net=4.975 -> CHOSEN).
  t2_target = 1.1000 + 3*0.0040 = 1.1120.
  m15 path: bar0 H=1.1010 (nothing hit); bar1 H=1.1130 (hits T2=1.1120,
  T1=1.1200 not reached).
  EXPECTED: status=opened, t1 ends time_stop at bar1 close, price=1.1125,
    r_result_t1~=3.125; t2 hits target at bar1, price=1.1120,
    r_result_t2=3.0 exactly.
"""
import pandas as pd
from conftest import _mk_df
from src.research.setups import PairSetup
from src.research.simulate import build_trade_from_setup

TF_M15 = pd.Timedelta(minutes=15)
TF_H1 = pd.Timedelta(hours=1)


def _mk_pool(price, side, pool_type, confirm_time):
    return {"pool_price": price, "side": side, "pool_type": pool_type,
            "confirm_time": pd.Timestamp(confirm_time, tz="UTC"),
            "expires_at": pd.NaT, "swept_time": pd.NaT}


def test_diag_trade_build_ob_opened():
    opens = [1.1000] * 20
    highs = [1.1010] * 20
    lows = [1.0990] * 20
    closes = [1.1000] * 20
    h1_df = _mk_df(opens, highs, lows, closes, freq="1h", start="2023-01-01")

    ps = PairSetup("eurusd")
    ps.state = "TRIGGERED"
    ps.winner = "ob"
    ps.candidate_ob = {"direction": "bullish", "ob_low": 1.0950, "ob_high": 1.0970, "ob_index": 15}
    ps.fill2_price = 1.0975
    ps.touch_time = pd.Timestamp("2023-01-31 23:45", tz="UTC")

    m15_opens  = [1.0975, 1.0980, 1.0995]
    m15_highs  = [1.0985, 1.1000, 1.1060]
    m15_lows   = [1.0970, 1.0975, 1.0990]
    m15_closes = [1.0980, 1.0995, 1.1050]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-02-01 00:00")

    pools = pd.DataFrame([
        _mk_pool(1.1002, "high", "near_test", "2023-01-31 20:00"),
        _mk_pool(1.1083, "high", "far_test", "2023-01-31 20:00"),
    ])

    record = build_trade_from_setup(ps, "eurusd", h1_df, m15_df, pools, TF_H1, TF_M15)
    print("SCENARIO 1 RECORD:", record)
    print("SCENARIO 1 PS STATE AFTER:", ps.state, ps.winner, ps.candidate_ob)
    print("EXPECTED: risk_r~0.0027, spread_cost_r~0.03704, t1=far_test(r_net~3.963), "
          "exit_t1=time_stop@1.1050(r~2.778), exit_t2=target@1.1056(r=3.0), "
          "ps reset to IDLE/None")


def test_diag_trade_build_breaker_skipped_spread():
    ps = PairSetup("gbpjpy")
    ps.state = "ARMED"
    ps.winner = "breaker"
    ps.breaker = {"direction": "bullish", "limit_price": 150.00, "stop": 149.90,
                  "fill_time": pd.Timestamp("2023-02-01 00:00", tz="UTC")}

    h1_df = _mk_df([150.0]*5, [150.1]*5, [149.9]*5, [150.0]*5, freq="1h", start="2023-01-01")
    m15_df = _mk_df([150.0]*5, [150.1]*5, [149.9]*5, [150.0]*5, freq="15min", start="2023-02-01")
    pools = pd.DataFrame(columns=["pool_price", "side", "pool_type", "confirm_time", "expires_at", "swept_time"])

    record = build_trade_from_setup(ps, "gbpjpy", h1_df, m15_df, pools, TF_H1, TF_M15)
    print("SCENARIO 2 RECORD:", record)
    print("SCENARIO 2 PS STATE AFTER:", ps.state, ps.winner, ps.breaker)
    print("EXPECTED: status=skipped_spread (ratio=0.30 > 0.15), ps reset to IDLE/None")


def test_diag_trade_build_breaker_opened():
    ps = PairSetup("eurusd")
    ps.state = "ARMED"
    ps.winner = "breaker"
    ps.breaker = {"direction": "bullish", "limit_price": 1.1000, "stop": 1.0960,
                  "fill_time": pd.Timestamp("2023-03-01 00:00", tz="UTC")}

    h1_df = _mk_df([1.10]*5, [1.101]*5, [1.099]*5, [1.10]*5, freq="1h", start="2023-02-01")
    m15_opens  = [1.1000, 1.1005]
    m15_highs  = [1.1010, 1.1130]
    m15_lows   = [1.0990, 1.1000]
    m15_closes = [1.1005, 1.1125]
    m15_df = _mk_df(m15_opens, m15_highs, m15_lows, m15_closes, freq="15min", start="2023-03-01 00:00")

    pools = pd.DataFrame([_mk_pool(1.1200, "high", "far_test", "2023-02-28 20:00")])

    record = build_trade_from_setup(ps, "eurusd", h1_df, m15_df, pools, TF_H1, TF_M15)
    print("SCENARIO 3 RECORD:", record)
    print("SCENARIO 3 PS STATE AFTER:", ps.state, ps.winner, ps.breaker)
    print("EXPECTED: risk_r=0.0040, spread_cost_r=0.025, t1=far_test(r_net~4.975), "
          "exit_t1=time_stop@1.1125(r~3.125), exit_t2=target@1.1120(r=3.0)")
