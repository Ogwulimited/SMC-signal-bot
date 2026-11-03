import pandas as pd
import pytest

from src.research.lookahead_guard import DataFeed, DecisionLog, LookaheadError
from src.research.poison import make_synthetic_m15
from src.research.primitives import resample_to_tf


class Collector:
    def __init__(self):
        self.seq = []
        self.bars = {}

    def on_bar_close(self, bar, feed):
        self.seq.append((bar.tf, bar.close_time, feed.now))
        self.bars.setdefault(bar.tf, []).append(bar)


@pytest.mark.parametrize("name,rule", [("H1", "1h"), ("H4", "4h"), ("D1", "1D")])
def test_feed_htf_bars_equal_resample_to_tf(name, rule):
    m15 = make_synthetic_m15(weeks=14, seed=3)   # crosses the March daylight-saving change
    col = Collector()
    DataFeed(m15, htf=("H1", "H4", "D1")).run(col)
    got = [(b.open_time.value, b.open, b.high, b.low, b.close) for b in col.bars[name]]
    ref = resample_to_tf(m15, rule)
    exp = [(pd.Timestamp(r.timestamp).value, float(r.open), float(r.high),
            float(r.low), float(r.close)) for r in ref.itertuples(index=False)]
    print(f"FEED {name}: {len(got)} bars, identical to resample_to_tf: {got == exp}")
    assert len(got) > 10
    assert got == exp


def test_no_bar_is_delivered_before_it_closes_and_htf_comes_first():
    m15 = make_synthetic_m15(weeks=6, seed=4)
    col = Collector()
    DataFeed(m15, htf=("H1", "H4", "D1")).run(col)
    for k, (tf, ct, now) in enumerate(col.seq):
        assert ct <= now, f"{tf} bar closing {ct} delivered at {now}"
        if tf == "M15":
            later = [x for x in col.seq[k + 1:k + 4] if x[0] != "M15" and x[1] == ct]
            assert not later, "an H1/H4/D1 bar closing at the same instant came after the M15 bar"
    print(f"FEED order: {len(col.seq)} deliveries, none early, higher timeframes first")


def test_future_access_raises():
    m15 = make_synthetic_m15(weeks=2, seed=5)
    state = {"m15": 0, "checked": False}

    class Peeker:
        def on_bar_close(self, bar, feed):
            if bar.tf != "M15":
                return
            state["m15"] += 1
            if state["m15"] == 200:
                with pytest.raises(LookaheadError):
                    feed.bar("M15", feed.count("M15"))       # the next M15 bar
                with pytest.raises(LookaheadError):
                    feed.bar("H4", feed.count("H4"))         # an H4 bar not closed yet
                assert feed.bar("M15", -1) == bar
                state["checked"] = True

    DataFeed(m15, htf=("H1", "H4")).run(Peeker())
    assert state["checked"]
    print("FEED: asking for a bar that has not closed raises LookaheadError")


def test_decision_log_rejects_known_at_after_time():
    t = pd.Timestamp("2024-01-01 10:00", tz="UTC")
    log = DecisionLog()
    log.add("ok", t, t)
    log.add("ok_earlier", t, t - pd.Timedelta(minutes=15))
    with pytest.raises(LookaheadError):
        log.add("cheat", t, t + pd.Timedelta(minutes=15))
    with pytest.raises(LookaheadError):
        log.add("missing", t, None)
    print("DECISION LOG: known_at later than the decision time raises")


def test_feed_rejects_unsorted_or_naive_data():
    m15 = make_synthetic_m15(weeks=2, seed=6)
    with pytest.raises(ValueError):
        DataFeed(m15.iloc[::-1].reset_index(drop=True))
    naive = m15.copy()
    naive["timestamp"] = naive["timestamp"].dt.tz_localize(None)
    with pytest.raises(ValueError):
        DataFeed(naive)
