from src.research.engine.fvg import find_fvgs, pick_for_breaker
from src.research.engine.mapper import MapRecorder, run_map_pipeline
from src.research.engine.structure import run_structure_pipeline
from src.research.lookahead_guard import DataFeed, DecisionLog
from src.research.poison import format_result, make_synthetic_m15, poison_test


def test_structure_decisions_are_unchanged_by_the_new_layers():
    m15 = make_synthetic_m15(weeks=10, seed=11)
    a = [d.key() for d in run_map_pipeline(m15) if d.kind.startswith("structure_")]
    b = [d.key() for d in run_structure_pipeline(m15)]
    assert a == b and len(a) > 50
    print(f"MAP: structure decisions identical to Batch 1 ({len(a)} events)")


def test_poi_invariants_on_synthetic_data():
    m15 = make_synthetic_m15(weeks=10, seed=21)
    rec = MapRecorder(DecisionLog())
    DataFeed(m15, htf=("H1", "H4", "D1")).run(rec)
    book = rec.books["M15"]
    assert len(book.pois) > 50
    n_struct = len([e for e in rec.events if e["tf"] == "M15"])
    assert len(book.pois) + book.counts["no_opposite"] + book.counts["init_skipped"] == n_struct

    for p in book.pois:
        o, h, l, c, _ct = book._bars[p.candle_time]
        assert (p.low, p.high) == (l, h)
        if not p.cap_hit:
            assert (c < o) if p.side == "buy" else (c > o)
        if p.state == "dead":
            assert p.dead_time > p.born_time
        if p.used_time is not None:
            assert p.used_time > p.born_time
        if p.origin == "CHoCH":
            assert p.role is None
        if p.origin == "BOS" and p.state == "dead":
            assert p.role in ("the", "stack")

    choch_pois = [p for p in book.pois if p.origin == "CHoCH"]
    assert book.counts["the_breaker"] + book.counts["no_the_breaker"] == len(choch_pois)

    the_by_time = {p.dead_time: p for p in book.pois if p.role == "the"}
    fvg_found = 0
    with_breaker = 0
    for q in choch_pois:
        the = the_by_time.get(q.born_time)
        if the is None:
            continue
        with_breaker += 1
        leg = book.window(q.swing_time, q.born_time)
        fvgs = find_fvgs(leg, rec.atr.value_at)
        direction = "up" if q.side == "buy" else "down"
        if pick_for_breaker(fvgs, direction, the.low, the.high) is not None:
            fvg_found += 1

    states = {s: len([p for p in book.pois if p.state == s]) for s in ("fresh", "used", "dead")}
    print(f"POI M15: {len(book.pois)} boxes, {states['fresh']} fresh, {states['used']} used, "
          f"{states['dead']} dead; colour moved {book.counts['colour_shifted']}, "
          f"cap hit {book.counts['cap_hit']}, INIT skipped {book.counts['init_skipped']}, "
          f"no opposite swing {book.counts['no_opposite']}")
    print(f"BREAKER: 'the breaker' found for {book.counts['the_breaker']} of {len(choch_pois)} CHoCH; "
          f"FVG variant has a gap for {fvg_found} of {with_breaker}")
    for tf in ("H4", "D1"):
        t = rec.bias[tf]
        print(f"BIAS {tf}: {len(t.history)} changes, final state {t.state}")
    assert rec.atr.value_at(m15["timestamp"].iloc[0] + (m15["timestamp"].iloc[-1] - m15["timestamp"].iloc[0])) is not None


def test_map_pipeline_passes_the_poison_test():
    m15 = make_synthetic_m15(weeks=10, seed=5)
    res = poison_test(run_map_pipeline, m15, n_cuts=100, seed=0)
    print(format_result("MAP POISON (structure + POI + bias, synthetic data)", res))
    assert res.mismatches == 0
    assert res.decisions_compared > 0
