import pandas as pd
import pytest

from src import config
from src.research.engine.structure import (IncrementalStructure, StructureRecorder)
from src.research.lookahead_guard import Bar, DataFeed, DecisionLog
from src.research.poison import make_synthetic_m15
from src.research.primitives import find_swings, resample_to_tf
from src.research.structure_major import detect_bos_choch_major

OHLC = ["open", "high", "low", "close"]


def _t(x):
    return None if pd.isna(x) else pd.Timestamp(x).value


def _f(x):
    return None if pd.isna(x) else float(x)


def rowkey(label, direction, time, close, bt, bp, ot, op):
    return (str(label), str(direction), _t(time), _f(close), _t(bt), _f(bp), _t(ot), _f(op))


def ev_key(ev):
    return rowkey(ev["label"], ev["direction"], ev["time"], ev["close"],
                  ev["broken_swing_time"], ev["broken_swing_price"],
                  ev["last_opposite_time"], ev["last_opposite_price"])


def ref_keys(df, n, tf):
    ref = detect_bos_choch_major(df, find_swings(df, n, tf), tf)
    return [rowkey(*r) for r in ref.itertuples(index=False)], list(ref["label"])


def run_engine(df, n, name, tf):
    eng = IncrementalStructure(n, tf, name)
    events = []
    for r in df.itertuples(index=False):
        bar = Bar(name, r.timestamp, r.timestamp + tf, float(r.open), float(r.high),
                  float(r.low), float(r.close))
        ev = eng.on_bar_close(bar)
        if ev is not None:
            events.append(ev)
    return events


@pytest.mark.parametrize("seed,n,ties", [(1, 2, False), (2, 2, True), (3, 3, False)])
def test_incremental_equals_reference_on_m15(seed, n, ties):
    df = make_synthetic_m15(weeks=20, seed=seed)
    if ties:                                   # many equal prices -> equal swing highs/lows
        for col in OHLC:
            df[col] = df[col].round(4)
    tf = pd.Timedelta(minutes=15)
    exp, labels = ref_keys(df, n, tf)
    events = run_engine(df, n, "M15", tf)
    got = [ev_key(e) for e in events]
    print(f"EQUIVALENCE M15 seed={seed} n={n} ties={ties}: {len(got)} events, "
          f"identical to structure_major: {got == exp}")
    assert got == exp
    # the data must exercise every case, otherwise the match proves little
    assert labels[0] == "INIT"
    assert labels.count("BOS") > 5 and labels.count("CHoCH") > 5
    assert any(a == "CHoCH" and b == "BOS" for a, b in zip(labels, labels[1:]))
    for e in events:
        assert e["known_at"] <= e["time"]


@pytest.mark.parametrize("name,rule,tf,n", [
    ("H4", "4h", pd.Timedelta(hours=4), config.H4_SWING_N),
    ("D1", "1D", pd.Timedelta(days=1), config.D1_SWING_N),
])
def test_htf_structure_through_the_feed_equals_reference(name, rule, tf, n):
    m15 = make_synthetic_m15(weeks=30, seed=5)
    log = DecisionLog()
    rec = StructureRecorder(log)
    DataFeed(m15, htf=("H4", "D1")).run(rec)
    got = [ev_key(e) for e in rec.events if e["tf"] == name]
    htf = resample_to_tf(m15, rule)
    exp, _ = ref_keys(htf, n, tf)
    print(f"EQUIVALENCE {name} via feed: {len(got)} events, identical to structure_major "
          f"on resample_to_tf: {got == exp}")
    assert len(got) > 2
    assert got == exp


def _bars(rows):
    start = pd.Timestamp("2024-01-01 00:00", tz="UTC")
    step = pd.Timedelta(minutes=15)
    out = []
    for i, (h, l, c) in enumerate(rows):
        o = pd.Timestamp(start + i * step)
        out.append(Bar("M15", o, o + step, (h + l) / 2, float(h), float(l), float(c)))
    return start, step, out


def test_close_between_two_standing_highs_prints_nothing():
    # swing highs 95 then 93 stand. A close at 94 prints nothing, a close at 100 breaks 95.
    start, step, bars = _bars([(90, 85, 88), (95, 88, 92), (91, 86, 87), (93, 87, 90),
                               (92, 88, 89), (94, 89, 94), (101, 93, 100)])
    eng = IncrementalStructure(1, step, "M15")
    events = [e for e in (eng.on_bar_close(b) for b in bars) if e is not None]
    assert len(events) == 1
    e = events[0]
    assert e["label"] == "INIT" and e["direction"] == "up"
    assert e["time"] == start + 7 * step
    assert e["broken_swing_price"] == 95 and e["broken_swing_time"] == start + 1 * step
    assert e["last_opposite_price"] == 86 and e["last_opposite_time"] == start + 2 * step


def test_break_with_no_opposite_swing_has_no_opposite():
    start, step, bars = _bars([(10, 9, 9.5), (12, 9.5, 11), (11, 10, 10.5), (13, 10.5, 12.5)])
    eng = IncrementalStructure(1, step, "M15")
    events = [e for e in (eng.on_bar_close(b) for b in bars) if e is not None]
    assert len(events) == 1
    assert events[0]["label"] == "INIT"
    assert pd.isna(events[0]["last_opposite_time"])
    assert pd.isna(events[0]["last_opposite_price"])
