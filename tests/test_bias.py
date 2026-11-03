import pandas as pd
import pytest

from src.research.engine.bias import BiasTracker, htf_bias
from src.research.lookahead_guard import DecisionLog

T0 = pd.Timestamp("2021-01-04 00:00", tz="UTC")
H4 = pd.Timedelta(hours=4)
NAN = float("nan")
FLIP = {"up": "down", "down": "up"}
WANT = {"bull": "bear", "bear": "bull", "none": "none"}


class Seq:
    """Builds events. mir=True mirrors directions and prices (p -> 200 - p)."""

    def __init__(self, mir):
        self.mir = mir
        self.i = 0

    def e(self, label, d, close=100.0, opp=NAN):
        self.i += 1
        t = T0 + self.i * H4
        if self.mir:
            d, close, opp = FLIP[d], 200.0 - close, 200.0 - opp
        return {"tf": "H4", "label": label, "direction": d, "time": t, "close": close,
                "broken_swing_time": pd.NaT, "broken_swing_price": NAN,
                "last_opposite_time": pd.NaT, "last_opposite_price": opp, "known_at": t}

    def bias(self, name):
        return WANT[name] if self.mir else name

    def read(self, tracker, d="up"):
        tracker.on_event(self.e("INIT", d))
        for _ in range(5):
            tracker.on_event(self.e("BOS", d))


@pytest.mark.parametrize("mir", [False, True])
def test_first_read_needs_five_counted_swings(mir):
    s = Seq(mir)
    b = BiasTracker("H4", first_read=5)
    assert b.on_event(s.e("INIT", "up")) is None
    for _ in range(4):
        assert b.on_event(s.e("BOS", "up")) is None
    assert b.bias == "none"
    change = b.on_event(s.e("BOS", "up"))
    assert change["reason"] == "first_read" and b.bias == s.bias("bull")
    print(f"BIAS: five counted swings give the first read ({b.state}), mirror={mir}")


@pytest.mark.parametrize("through", [True, False])
@pytest.mark.parametrize("mir", [False, True])
def test_choch_counts_only_if_it_breaks_the_previous_choch_high(through, mir):
    s = Seq(mir)
    b = BiasTracker("H4", first_read=5)
    b.on_event(s.e("INIT", "up"))
    b.on_event(s.e("BOS", "up"))
    b.on_event(s.e("BOS", "up"))                                   # count 2
    b.on_event(s.e("CHoCH", "down", close=118.0, opp=120.0))       # plain CHoCH: not counted
    b.on_event(s.e("CHoCH", "up", close=125.0 if through else 115.0, opp=100.0))
    b.on_event(s.e("BOS", "up"))
    assert b.bias == "none"
    b.on_event(s.e("BOS", "up"))
    assert b.bias == (s.bias("bull") if through else "none")


@pytest.mark.parametrize("mir", [False, True])
def test_an_opposite_counted_swing_resets_the_count(mir):
    s = Seq(mir)
    b = BiasTracker("H4", first_read=5)
    b.on_event(s.e("INIT", "up"))
    for _ in range(4):
        b.on_event(s.e("BOS", "up"))
    b.on_event(s.e("BOS", "down"))
    for _ in range(4):
        b.on_event(s.e("BOS", "up"))
    assert b.bias == "none"
    b.on_event(s.e("BOS", "up"))
    assert b.bias == s.bias("bull")


@pytest.mark.parametrize("mir", [False, True])
def test_choch_puts_bias_on_warning_and_a_following_bos_flips_it(mir):
    s = Seq(mir)
    b = BiasTracker("H4", first_read=5)
    s.read(b, "up")
    assert b.bias == s.bias("bull") and not b.warning
    c = b.on_event(s.e("CHoCH", "down", close=108.0, opp=110.0))
    assert c["reason"] == "warning" and b.warning and b.bias == s.bias("bull")
    c = b.on_event(s.e("BOS", "down", close=105.0))
    assert c["reason"] == "flip" and b.bias == s.bias("bear") and not b.warning
    print(f"BIAS: CHoCH = warning, then BOS in the new direction flips the bias, mirror={mir}")


@pytest.mark.parametrize("mir", [False, True])
def test_a_close_back_through_the_choch_high_clears_the_warning(mir):
    s = Seq(mir)
    b = BiasTracker("H4", first_read=5)
    s.read(b, "up")
    b.on_event(s.e("CHoCH", "down", close=108.0, opp=110.0))
    assert b.on_event(s.e("CHoCH", "up", close=109.0, opp=100.0)) is None
    assert b.warning
    c = b.on_event(s.e("CHoCH", "up", close=111.0, opp=100.0))
    assert c["reason"] == "warning_cleared" and not b.warning and b.bias == s.bias("bull")


def test_htf_bias_needs_d1_and_h4_to_agree():
    s = Seq(False)
    d1 = BiasTracker("D1", first_read=5)
    h4 = BiasTracker("H4", first_read=5)
    assert htf_bias(d1, h4) is None
    s.read(d1, "up")
    assert htf_bias(d1, h4) is None
    s.read(h4, "up")
    assert htf_bias(d1, h4) == "bull"
    h4_bear = BiasTracker("H4", first_read=5)
    s.read(h4_bear, "down")
    assert htf_bias(d1, h4_bear) is None


def test_bias_changes_are_logged():
    s = Seq(False)
    log = DecisionLog()
    b = BiasTracker("H4", log=log, first_read=5)
    s.read(b, "up")
    assert [d.kind for d in log.items] == ["bias_H4"]
