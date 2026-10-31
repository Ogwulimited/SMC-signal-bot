"""
Fix #7 regression tests: persistent anti-duplication memory
(self.traded_bos_times) must survive _reset_episode() and be cleared only
on a genuine bias flip or zone change inside on_d1_close -- never by the
H1 leg-ceiling check, OB-invalidation, or same-bar-ambiguous cancellation.

These tests are self-contained: they either manipulate PairSetup state
directly (no market data needed) or monkeypatch the module-level
functions/primitives that setups.py calls, so every expected outcome is
hand-calculated from values chosen in the test itself, not dependent on
real market data or on any other test file's fixtures.
"""

import pandas as pd
import pytest

from src.research import setups


def _bias(state, direction, time=None, label="BOS"):
    return {"state": state, "direction": direction, "time": time or pd.Timestamp("2022-12-01"), "label": label}


def _zone(zone_low, zone_high, confirm_time, timeframe="H4"):
    return {"timeframe": timeframe, "zone_low": zone_low, "zone_high": zone_high, "confirm_time": confirm_time}


# ---------------------------------------------------------------------------
# Direct state-manipulation tests (no market data needed)
# ---------------------------------------------------------------------------

def test_fix7_reset_episode_does_not_clear_traded_bos_times():
    ps = setups.PairSetup("EURUSD")
    t = pd.Timestamp("2022-12-22 17:00:00")
    ps.traded_bos_times = {t}
    ps.state = "ARMED"
    ps.h1_bos_event = {"time": t}

    ps._reset_episode()

    assert ps.state == "IDLE"          # confirms the reset actually ran
    assert ps.h1_bos_event is None      # confirms the reset actually ran
    # The key assertion: traded_bos_times is untouched by _reset_episode().
    assert ps.traded_bos_times == {t}


def test_fix7_cycle_reset_adds_to_traded_bos_times_cumulatively():
    ps = setups.PairSetup("EURUSD")
    earlier = pd.Timestamp("2022-12-01 00:00:00")
    new_bos = pd.Timestamp("2022-12-22 17:00:00")
    ps.traded_bos_times = {earlier}
    ps.h1_bos_event = {"time": new_bos}

    ps._cycle_reset()

    assert ps.state == "EPISODE"
    assert ps.last_traded_bos_time == new_bos
    # Cumulative union, not a replace -- hand-calculated expected value.
    assert ps.traded_bos_times == {earlier, new_bos}


# ---------------------------------------------------------------------------
# on_d1_close clearing-point tests (monkeypatch compute_d1_bias /
# select_htf_zone so the branch taken is fully controlled and deterministic)
# ---------------------------------------------------------------------------

def test_fix7_on_d1_close_clears_traded_bos_times_on_bias_flip(monkeypatch):
    ps = setups.PairSetup("EURUSD")
    ps.bias = _bias("bullish", "up")
    ps.zone = _zone(1.0, 1.01, pd.Timestamp("2022-12-01"))
    ps.traded_bos_times = {pd.Timestamp("2022-12-22 17:00:00")}

    monkeypatch.setattr(setups, "compute_d1_bias",
                         lambda d1_df: {"state": "none", "time": pd.NaT, "direction": None, "label": None})

    dummy_d1_df = pd.DataFrame({"close": [1.0]})
    ps.on_d1_close(dummy_d1_df, pd.DataFrame(), pd.DataFrame(), 0.0, 2.0)

    assert ps.zone is None
    # Hand-calculated expected: bias flip is an explicit clearing point.
    assert ps.traded_bos_times == set()


def test_fix7_on_d1_close_clears_traded_bos_times_on_zone_change(monkeypatch):
    ps = setups.PairSetup("EURUSD")
    ps.bias = _bias("bullish", "up", time=pd.Timestamp("2022-12-01"))
    ps.zone = _zone(1.0, 1.01, pd.Timestamp("2022-12-01"))
    ps.traded_bos_times = {pd.Timestamp("2022-12-22 17:00:00")}

    # Same bias (state + direction match -> bias_changed is False).
    monkeypatch.setattr(setups, "compute_d1_bias",
                         lambda d1_df: _bias("bullish", "up", time=pd.Timestamp("2022-12-01")))
    # Different zone (zone_low differs -> zone_changed is True).
    monkeypatch.setattr(setups, "select_htf_zone",
                         lambda *a, **k: _zone(1.5, 1.51, pd.Timestamp("2022-12-05")))

    dummy_d1_df = pd.DataFrame({"close": [1.6]})
    ps.on_d1_close(dummy_d1_df, pd.DataFrame(), pd.DataFrame(), 1.49, 1.52)

    assert ps.zone["zone_low"] == 1.5   # confirms the new zone was actually adopted
    # Hand-calculated expected: genuine zone change is an explicit clearing point.
    assert ps.traded_bos_times == set()


def test_fix7_on_d1_close_far_edge_beyond_does_not_clear_traded_bos_times(monkeypatch):
    ps = setups.PairSetup("EURUSD")
    ps.bias = _bias("bullish", "up", time=pd.Timestamp("2022-12-01"))
    ps.zone = _zone(1.0, 1.01, pd.Timestamp("2022-12-01"))
    ps.state = "EPISODE"  # non-IDLE, so the far-edge check block is reachable
    t = pd.Timestamp("2022-12-22 17:00:00")
    ps.traded_bos_times = {t}

    # Identical bias and identical zone -> bias_changed and zone_changed both False.
    monkeypatch.setattr(setups, "compute_d1_bias",
                         lambda d1_df: _bias("bullish", "up", time=pd.Timestamp("2022-12-01")))
    monkeypatch.setattr(setups, "select_htf_zone",
                         lambda *a, **k: _zone(1.0, 1.01, pd.Timestamp("2022-12-01")))

    # D1 close below far_edge (zone_low, bullish) -> the far-edge "beyond" check fires.
    dummy_d1_df = pd.DataFrame({"close": [0.99]})
    ps.on_d1_close(dummy_d1_df, pd.DataFrame(), pd.DataFrame(), 0.9, 1.1)

    assert ps.state == "IDLE"  # confirms _reset_episode() fired via the far-edge check
    # Key assertion: this trigger is deliberately NOT a clearing point.
    assert ps.traded_bos_times == {t}


# ---------------------------------------------------------------------------
# Integration-style reproduction of the actual bug: a stale, already-traded
# BOS must not be rediscovered by on_h1_close's countertrend-BOS scan, even
# immediately after a full _reset_episode() (simulating a failed-back
# leg-ceiling break).
# ---------------------------------------------------------------------------

def _make_h1_df():
    return pd.DataFrame({
        "timestamp": [pd.Timestamp("2022-12-27 08:00:00")],
        "open": [1.005],
        "high": [1.006],
        "low": [1.004],
        "close": [1.0055],
    })


def test_fix7_stale_bos_excluded_from_rescan_when_already_traded(monkeypatch):
    ps = setups.PairSetup("EURUSD")
    ps.bias = _bias("bullish", "up")
    ps.zone = _zone(1.0, 1.01, pd.Timestamp("2022-12-01"))
    ps.state = "IDLE"  # as it would be immediately after a ceiling-triggered reset
    ps.leg_ceiling_price = None  # also wiped by that reset

    stale_bos_time = pd.Timestamp("2022-12-22 17:00:00")
    ps.traded_bos_times = {stale_bos_time}  # already traded, before the reset happened

    crafted_events = pd.DataFrame({
        "time": [stale_bos_time],
        "direction": ["down"],      # sweep_dir for a bullish bias is "down"
        "label": ["BOS"],
        "last_opposite_price": [1.02],
    })
    monkeypatch.setattr(setups.primitives, "find_swings", lambda *a, **k: None)
    monkeypatch.setattr(setups.primitives, "detect_bos_choch", lambda *a, **k: crafted_events)

    ps.on_h1_close(_make_h1_df(), pd.DataFrame(), pd.Timedelta(hours=1))

    # Hand-calculated expected: the stale, already-traded BOS must be
    # excluded, so h1_bos_event stays None.
    assert ps.h1_bos_event is None


def test_fix7_bos_not_excluded_when_not_yet_traded(monkeypatch):
    """Control case: same setup, but the BOS has NOT already been traded.
    Proves the exclusion above is a real filter, not a test that would
    always pass regardless of traded_bos_times' contents."""
    ps = setups.PairSetup("EURUSD")
    ps.bias = _bias("bullish", "up")
    ps.zone = _zone(1.0, 1.01, pd.Timestamp("2022-12-01"))
    ps.state = "IDLE"
    ps.leg_ceiling_price = None
    ps.traded_bos_times = set()

    bos_time = pd.Timestamp("2022-12-22 17:00:00")
    crafted_events = pd.DataFrame({
        "time": [bos_time],
        "direction": ["down"],
        "label": ["BOS"],
        "last_opposite_price": [1.02],
    })
    monkeypatch.setattr(setups.primitives, "find_swings", lambda *a, **k: None)
    monkeypatch.setattr(setups.primitives, "detect_bos_choch", lambda *a, **k: crafted_events)

    ps.on_h1_close(_make_h1_df(), pd.DataFrame(), pd.Timedelta(hours=1))

    assert ps.h1_bos_event is not None
    assert ps.h1_bos_event["time"] == bos_time
