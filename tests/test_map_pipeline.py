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
        if p.role == "the":
            assert p.origin == "BOS" and p.breaker_for is not None

    m15_events = [e for e in rec.events if e["tf"] == "M15"]
    choch_events = [e for e in m15_events if e["label"] == "CHoCH"]
    c = book.counts
    assert c["the_breaker"] + c["no_the_breaker"] == len(choch_events)
    assert len(book.choch_breaker) == len(choch_events)
    assert c["breaker_dead_before"] + c["breaker_dead_at"] + c["breaker_alive"] == c["the_breaker"]
    assert c["the_breaker"] > 0
    # one box serves one CHoCH only
    used_boxes = [p.id for p in book.choch_breaker.values() if p is not None]
    assert len(used_boxes) == len(set(used_boxes))

    # why a CHoCH has no breaker (rebuilt from the events, in time order)
    box_times = {p.born_time for p in book.pois if p.origin == "BOS"}
    last_bos = {"up": None, "down": None}
    why = {"no BOS yet": 0, "last BOS had no box": 0, "box already used": 0}
    for e in m15_events:
        if e["label"] == "BOS":
            last_bos[e["direction"]] = e["time"]
        elif e["label"] == "CHoCH":
            if book.choch_breaker.get(e["time"]) is not None:
                continue
            prior = "up" if e["direction"] == "down" else "down"
            t = last_bos[prior]
            if t is None:
                why["no BOS yet"] += 1
            elif t not in box_times:
                why["last BOS had no box"] += 1
            else:
                why["box already used"] += 1
    assert sum(why.values()) == c["no_the_breaker"]

    choch_pois = {p.born_time: p for p in book.pois if p.origin == "CHoCH"}
    fvg_found = 0
    with_breaker = 0
    for e in choch_events:
        the = book.choch_breaker.get(e["time"])
        q = choch_pois.get(e["time"])
        if the is None or q is None:
            continue
        with_breaker += 1
        leg = book.window(q.swing_time, q.born_time)
        fvgs = find_fvgs(leg, rec.atr.value_at)
        direction = "up" if q.side == "buy" else "down"
        if pick_for_breaker(fvgs, direction, the.low, the.high) is not None:
            fvg_found += 1

    states = {s: len([p for p in book.pois if p.state == s]) for s in ("fresh", "used", "dead")}
    print(f"POI M15: {len(book.pois)} boxes, {states['fresh']} fresh, {states['used']} used, "
          f"{states['dead']} dead; colour moved {c['colour_shifted']}, "
          f"cap hit {c['cap_hit']}, INIT skipped {c['init_skipped']}, "
          f"no opposite swing {c['no_opposite']}")
    print(f"BREAKER: found for {c['the_breaker']} of {len(choch_events)} CHoCH "
          f"(box dead before the CHoCH bar {c['breaker_dead_before']}, "
          f"on it {c['breaker_dead_at']}, still alive {c['breaker_alive']}); "
          f"FVG variant has a gap for {fvg_found} of {with_breaker}")
    print(f"NO BREAKER: {c['no_the_breaker']} CHoCH had none: "
          f"no BOS yet {why['no BOS yet']}, "
          f"last BOS had no box {why['last BOS had no box']}, "
          f"box already used {why['box already used']}")
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
