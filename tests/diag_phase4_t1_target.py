"""
Diagnostic (print-only) test for select_t1_target -- Phase 4.
Run via CI, compare printed actual values against the hand-derived
predictions written below BEFORE this was run.

Setup: bullish trade, entry_price=1.1000, risk_r=0.0020 (1R=20 pips),
spread_cost_r=0.05.

Pools (side="high" is the relevant side for a bullish target):
  A: price=1.1030 -> distance=0.0030 -> r_gross=1.5 -> r_net=1.45  (fails 3R, reported as "nearest")
  B: price=1.1070 -> distance=0.0070 -> r_gross=3.5 -> r_net=3.45  (qualifies -> should be CHOSEN)
  C: price=1.1100 -> distance=0.0100 -> r_gross=5.0 -> r_net=4.95  (qualifies but farther -> NOT chosen)
  D: side="low", price=1.0900 -> wrong side -> excluded
  E: side="high", price=1.1050, confirm_time AFTER entry_time -> excluded (lookahead)
  F: side="high", price=1.1060, swept_time BEFORE entry_time -> excluded (already swept)
  G: side="high", price=1.1055, expires_at BEFORE entry_time -> excluded (expired)
  H: side="high", price=1.0990 (behind entry) -> excluded (wrong direction)

PREDICTION scenario 1 (all pools present):
  nearest_pool_type="A_test", nearest_r_net~=1.45
  chosen_pool_type="B_test", chosen_r_gross~=3.5, chosen_r_net~=3.45, skipped_no_t1=False

PREDICTION scenario 2 (only pool A present):
  nearest_pool_type="A_test", nearest_r_net~=1.45
  chosen_pool_type=None, skipped_no_t1=True

PREDICTION scenario 3 (bearish mirror):
  A': price=1.0970 -> distance=0.0030 -> r_net=1.45 (nearest, fails)
  B': price=1.0930 -> distance=0.0070 -> r_net=3.45 (chosen)
  Same shape as scenario 1, mirrored.
"""
import pandas as pd
from src.research.simulate import select_t1_target


def _mk_pool(price, side, pool_type, confirm_time, swept_time=pd.NaT, expires_at=pd.NaT):
    return {"pool_price": price, "side": side, "pool_type": pool_type,
            "confirm_time": pd.Timestamp(confirm_time, tz="UTC"),
            "expires_at": pd.Timestamp(expires_at, tz="UTC") if pd.notna(expires_at) else pd.NaT,
            "swept_time": pd.Timestamp(swept_time, tz="UTC") if pd.notna(swept_time) else pd.NaT}


def test_diag_t1_target_scenario1():
    entry_time = pd.Timestamp("2023-01-10 12:00", tz="UTC")
    entry_price = 1.1000
    risk_r = 0.0020
    spread_cost_r = 0.05

    pools = pd.DataFrame([
        _mk_pool(1.1030, "high", "A_test", "2023-01-10 10:00"),
        _mk_pool(1.1070, "high", "B_test", "2023-01-10 10:00"),
        _mk_pool(1.1100, "high", "C_test", "2023-01-10 10:00"),
        _mk_pool(1.0900, "low", "D_test", "2023-01-10 10:00"),
        _mk_pool(1.1050, "high", "E_test", "2023-01-10 13:00"),
        _mk_pool(1.1060, "high", "F_test", "2023-01-10 10:00", swept_time="2023-01-10 11:00"),
        _mk_pool(1.1055, "high", "G_test", "2023-01-10 10:00", expires_at="2023-01-10 11:00"),
        _mk_pool(1.0990, "high", "H_test", "2023-01-10 10:00"),
    ])

    result = select_t1_target(pools, entry_time, entry_price, "bullish", risk_r, spread_cost_r)
    print("SCENARIO 1 RESULT:", result)
    print("EXPECTED: nearest=A_test(~1.45), chosen=B_test(gross~3.5, net~3.45), skipped=False")


def test_diag_t1_target_scenario2():
    entry_time = pd.Timestamp("2023-01-10 12:00", tz="UTC")
    entry_price = 1.1000
    risk_r = 0.0020
    spread_cost_r = 0.05

    pools = pd.DataFrame([
        _mk_pool(1.1030, "high", "A_test", "2023-01-10 10:00"),
    ])

    result = select_t1_target(pools, entry_time, entry_price, "bullish", risk_r, spread_cost_r)
    print("SCENARIO 2 RESULT:", result)
    print("EXPECTED: nearest=A_test(~1.45), chosen=None, skipped=True")


def test_diag_t1_target_scenario3_bearish():
    entry_time = pd.Timestamp("2023-01-10 12:00", tz="UTC")
    entry_price = 1.1000
    risk_r = 0.0020
    spread_cost_r = 0.05

    pools = pd.DataFrame([
        _mk_pool(1.0970, "low", "A_test", "2023-01-10 10:00"),
        _mk_pool(1.0930, "low", "B_test", "2023-01-10 10:00"),
    ])

    result = select_t1_target(pools, entry_time, entry_price, "bearish", risk_r, spread_cost_r)
    print("SCENARIO 3 RESULT:", result)
    print("EXPECTED: nearest=A_test(~1.45), chosen=B_test(gross~3.5, net~3.45), skipped=False")
