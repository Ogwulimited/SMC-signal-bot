"""
Diagnostic (print-only) test for scan_trade_exit -- Phase 4.
Hand-derived predictions written BEFORE running CI, compared against printed
actual output.

All scenarios: bullish trade, entry_price=1.1000, stop=1.0980 (risk_r=0.0020),
15-min bars. bar0 = entry bar (not scanned, close time == entry_time).
tf_m15=15min, tf_h1=1h.
"""
import pandas as pd
from conftest import _mk_df
from src.research.simulate import scan_trade_exit

TF_M15 = pd.Timedelta(minutes=15)
TF_H1 = pd.Timedelta(hours=1)


def test_diag_exit_stop_hit():
    # bar1 low=1.0975 hits stop; high=1.1010 doesn't reach target 1.1060.
    opens  = [1.1000, 1.1000, 1.0980]
    highs  = [1.1005, 1.1010, 1.0990]
    lows   = [1.0995, 1.0975, 1.0970]
    closes = [1.1000, 1.0980, 1.0975]
    df = _mk_df(opens, highs, lows, closes, freq="15min")
    entry_time = df["timestamp"].iloc[0] + TF_M15

    result = scan_trade_exit(df, TF_M15, TF_H1, entry_time, 1.1000, "bullish",
                              stop_price=1.0980, target_price=1.1060)
    print("STOP HIT RESULT:", result)
    print("EXPECTED: reason=stop, exit_price=1.0980, exit_time=bar1 close")


def test_diag_exit_target_hit():
    # bar1 high=1.1065 hits target; low=1.0995 doesn't reach stop.
    opens  = [1.1000, 1.1000, 1.1060]
    highs  = [1.1005, 1.1065, 1.1070]
    lows   = [1.0995, 1.0995, 1.1050]
    closes = [1.1000, 1.1060, 1.1065]
    df = _mk_df(opens, highs, lows, closes, freq="15min")
    entry_time = df["timestamp"].iloc[0] + TF_M15

    result = scan_trade_exit(df, TF_M15, TF_H1, entry_time, 1.1000, "bullish",
                              stop_price=1.0980, target_price=1.1060)
    print("TARGET HIT RESULT:", result)
    print("EXPECTED: reason=target, exit_price=1.1060, exit_time=bar1 close")


def test_diag_exit_same_candle_stop_wins():
    # bar1 hits BOTH stop (low=1.0970) and target (high=1.1070) -> stop wins.
    opens  = [1.1000, 1.1000, 1.0980]
    highs  = [1.1005, 1.1070, 1.0990]
    lows   = [1.0995, 1.0970, 1.0970]
    closes = [1.1000, 1.1000, 1.0975]
    df = _mk_df(opens, highs, lows, closes, freq="15min")
    entry_time = df["timestamp"].iloc[0] + TF_M15

    result = scan_trade_exit(df, TF_M15, TF_H1, entry_time, 1.1000, "bullish",
                              stop_price=1.0980, target_price=1.1060)
    print("SAME-CANDLE RESULT:", result)
    print("EXPECTED: reason=stop (stop wins), exit_price=1.0980, exit_time=bar1 close")


def test_diag_exit_time_stop():
    # Override time_stop to 1 H1 bar (4 M15 bars). Neither stop nor target
    # ever touched within that window -> exit at bar4's close (the 4th bar
    # after entry, whose close time == entry_time + 1h exactly).
    opens  = [1.1000, 1.1000, 1.1005, 1.1010, 1.1008, 1.1200]
    highs  = [1.1005, 1.1020, 1.1015, 1.1020, 1.1018, 1.1300]
    lows   = [1.0995, 1.0990, 1.0995, 1.1000, 1.0998, 1.0900]
    closes = [1.1000, 1.1005, 1.1010, 1.1008, 1.1012, 1.1200]
    df = _mk_df(opens, highs, lows, closes, freq="15min")
    entry_time = df["timestamp"].iloc[0] + TF_M15

    result = scan_trade_exit(df, TF_M15, TF_H1, entry_time, 1.1000, "bullish",
                              stop_price=1.0980, target_price=1.1060,
                              time_stop_h1_bars=1)
    print("TIME STOP RESULT:", result)
    print("EXPECTED: reason=time_stop, exit_price=1.1012, exit_time=entry_time+1h "
          "(bar5's extreme move at 1.1300/1.0900 must be IGNORED -- it's past cutoff)")


def test_diag_exit_t1_vs_t2_divergence():
    # Same price path, two different targets -> must diverge independently.
    opens  = [1.1000, 1.1000, 1.1040]
    highs  = [1.1005, 1.1045, 1.1065]
    lows   = [1.0995, 1.0995, 1.1030]
    closes = [1.1000, 1.1040, 1.1060]
    df = _mk_df(opens, highs, lows, closes, freq="15min")
    entry_time = df["timestamp"].iloc[0] + TF_M15

    t1_result = scan_trade_exit(df, TF_M15, TF_H1, entry_time, 1.1000, "bullish",
                                 stop_price=1.0980, target_price=1.1040)
    t2_result = scan_trade_exit(df, TF_M15, TF_H1, entry_time, 1.1000, "bullish",
                                 stop_price=1.0980, target_price=1.1060)
    print("T1 RESULT:", t1_result)
    print("T2 RESULT:", t2_result)
    print("EXPECTED: T1 hits at bar1 close (price=1.1040); "
          "T2 hits at bar2 close (price=1.1060) -- genuinely different exits "
          "from the same entry, same price path")
