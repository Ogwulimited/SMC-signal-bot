import pandas as pd
import pytest

from src import config
from src.research.engine.poi import PoiBook
from src.research.lookahead_guard import Bar, DecisionLog

T0 = pd.Timestamp("2021-03-01 00:00", tz="UTC")
M15 = pd.Timedelta(minutes=15)
NAN = float("nan")


def bar(i, o, h, l, c, mir=False):
    """One M15 bar. mir=True mirrors every price (p -> 100 - p)."""
    if mir:
        o, h, l, c = 100.0 - o, 100.0 - l, 100.0 - h, 100.0 - c
    t = T0 + i * M15
    return Bar(tf="M15", open_time=t, close_time=t + M15,
               open=o, high=h, low=l, close=c)


def ev(label, direction, i, opp_i=None, mir=False):
    d = {"up": "down", "down": "up"}[direction] if mir else direction
    t = T0 + (i + 1) * M15
    return {"tf": "M15", "label": label, "direction": d, "time": t, "close": 0.0,
            "broken_swing_time": pd.NaT, "broken_swing_price": NAN,
            "last_opposite_time": pd.NaT if opp_i is None else T0 + opp_i * M15,
            "last_opposite_price": NAN, "known_at": t}


def feed(book, bars):
    for b in bars:
        book.on_bar_close(b)


def base_bars(mir):
    # bar 2 is the swing candle: closed down (right colour for a buy), box 10.0 - 12.0
    return [bar(0, 13.0, 13.5, 12.5, 13.2, mir), bar(1, 12.5, 12.8, 11.9, 12.0, mir),
            bar(2, 11.8, 12.0, 10.0, 10.2, mir), bar(3, 10.4, 13.0, 10.3, 12.9, mir)]


@pytest.mark.parametrize("mir", [False, True])
def test_box_is_the_swing_candle_wick_to_wick(mir):
    book = PoiBook("M15")
    feed(book, base_bars(mir))
    poi = book.on_event(ev("BOS", "up", 3, opp_i=2, mir=mir))
    assert poi.side == ("sell" if mir else "buy")
    assert (poi.low, poi.high) == ((88.0, 90.0) if mir else (10.0, 12.0))
    assert poi.origin == "BOS" and poi.state == "fresh"
    assert poi.shifted == 0 and poi.cap_hit is False
    assert poi.candle_time == T0 + 2 * M15
    print(f"POI box: wick to wick on the swing candle, side {poi.side}, mirror={mir}")


@pytest.mark.parametrize("mir", [False, True])
def test_wrong_colour_candle_moves_back_to_nearest_right_colour(mir, monkeypatch):
    monkeypatch.setattr(config, "WRONG_COLOUR_SEARCH_DIRECTION", "back")
    book = PoiBook("M15")
    feed(book, [bar(0, 12.5, 12.6, 11.0, 11.2, mir),     # closed down: right colour
                bar(1, 11.2, 11.8, 11.0, 11.6, mir),     # closed up
                bar(2, 10.5, 11.5, 10.0, 11.2, mir),     # swing candle, closed up = wrong
                bar(3, 11.3, 13.0, 11.2, 12.9, mir)])
    poi = book.on_event(ev("BOS", "up", 3, opp_i=2, mir=mir))
    assert poi.shifted == 2 and poi.candle_time == T0
    assert (poi.low, poi.high) == ((87.4, 89.0) if mir else (11.0, 12.6))
    assert book.counts["colour_shifted"] == 1


@pytest.mark.parametrize("mir", [False, True])
def test_forward_search_option(mir, monkeypatch):
    monkeypatch.setattr(config, "WRONG_COLOUR_SEARCH_DIRECTION", "forward")
    book = PoiBook("M15")
    feed(book, [bar(0, 12.5, 12.6, 11.0, 11.2, mir),
                bar(1, 10.5, 11.5, 10.0, 11.2, mir),     # swing candle, wrong colour
                bar(2, 12.0, 12.2, 10.8, 11.0, mir),     # closed down: right colour
                bar(3, 11.3, 13.0, 11.2, 12.9, mir)])
    poi = book.on_event(ev("BOS", "up", 3, opp_i=1, mir=mir))
    assert poi.shifted == 1 and poi.candle_time == T0 + 2 * M15


@pytest.mark.parametrize("mir", [False, True])
def test_cap_hit_keeps_the_swing_candle_and_is_counted(mir, monkeypatch):
    monkeypatch.setattr(config, "WRONG_COLOUR_SEARCH_DIRECTION", "back")
    n = int(config.OB_SEARCH_BACK_MAX) + 3
    book = PoiBook("M15")
    feed(book, [bar(i, 10.0 + i * 0.1, 11.0 + i * 0.1, 9.9 + i * 0.1, 10.9 + i * 0.1, mir)
                for i in range(n)])
    poi = book.on_event(ev("BOS", "up", n - 1, opp_i=n - 1, mir=mir))
    assert poi.cap_hit is True and poi.shifted == 0
    assert poi.candle_time == T0 + (n - 1) * M15
    assert book.counts["cap_hit"] == 1


@pytest.mark.parametrize("mir", [False, True])
def test_fresh_used_dead_follow_body_closes_only(mir):
    book = PoiBook("M15")
    feed(book, base_bars(mir))
    poi = book.on_event(ev("BOS", "up", 3, opp_i=2, mir=mir))
    book.on_bar_close(bar(4, 12.9, 13.0, 11.0, 12.8, mir))   # wick into the box, body outside
    assert poi.state == "fresh"
    book.on_bar_close(bar(5, 12.8, 12.9, 10.8, 11.0, mir))   # body closes inside
    assert poi.state == "used" and poi.used_time == T0 + 6 * M15
    book.on_bar_close(bar(6, 11.0, 12.6, 10.9, 12.5, mir))
    assert poi.state == "used"
    book.on_bar_close(bar(7, 12.5, 12.6, 9.0, 11.5, mir))    # wick through the far edge, body inside
    assert poi.state == "used"
    assert book.fresh() == [] and len(book.usable(include_used=True)) == 1
    book.on_bar_close(bar(8, 11.5, 11.6, 9.2, 9.5, mir))     # body closes beyond the far edge
    assert poi.state == "dead" and poi.dead_time == T0 + 9 * M15
    assert book.usable(include_used=True) == []
    assert poi.is_breaker and poi.role == "stack"
    assert [p.id for p in book.breakers] == [poi.id]
    if mir:
        assert poi.breaker_side == "buy"
        assert (poi.breaker_entry, poi.breaker_stop_edge) == (90.0, 88.0)
    else:
        assert poi.breaker_side == "sell"
        assert (poi.breaker_entry, poi.breaker_stop_edge) == (10.0, 12.0)
    book.on_bar_close(bar(9, 9.5, 11.5, 9.4, 11.0, mir))     # a dead POI stays dead
    assert poi.state == "dead"
    print("POI states: wick does nothing, body inside = used, body beyond far edge = dead")


@pytest.mark.parametrize("mir", [False, True])
def test_a_close_straight_through_kills_without_using(mir):
    book = PoiBook("M15")
    feed(book, base_bars(mir))
    poi = book.on_event(ev("BOS", "up", 3, opp_i=2, mir=mir))
    book.on_bar_close(bar(4, 12.9, 13.0, 9.0, 9.5, mir))
    assert poi.state == "dead" and poi.used_time is None


@pytest.mark.parametrize("mir", [False, True])
def test_the_breaker_stack_breakers_and_choch_poi(mir):
    log = DecisionLog()
    book = PoiBook("M15", log)
    # base scenario = sell side: two BOS-down POIs, then a CHoCH up kills both on one bar
    feed(book, [bar(0, 23.0, 23.2, 22.4, 22.5, mir), bar(1, 22.5, 22.6, 21.4, 21.5, mir),
                bar(2, 19.8, 22.0, 19.5, 21.0, mir),             # A: closed up, box 19.5 - 22.0
                bar(3, 21.0, 21.2, 18.0, 18.2, mir)])
    a = book.on_event(ev("BOS", "down", 3, opp_i=2, mir=mir))
    feed(book, [bar(4, 18.2, 18.5, 16.0, 16.2, mir),
                bar(5, 16.7, 19.0, 16.5, 17.5, mir),             # B: closed up, box 16.5 - 19.0
                bar(6, 17.5, 17.6, 14.0, 14.2, mir)])
    b = book.on_event(ev("BOS", "down", 6, opp_i=5, mir=mir))
    feed(book, [bar(7, 14.2, 14.5, 13.0, 13.2, mir)])            # base of the CHoCH leg
    book.on_bar_close(bar(8, 13.2, 23.0, 13.0, 22.5, mir))       # body closes above both boxes
    choch = ev("CHoCH", "up", 8, opp_i=7, mir=mir)
    q = book.on_event(choch)
    assert a.state == "dead" and b.state == "dead"
    assert a.dead_time == b.dead_time == choch["time"]
    assert b.role == "the" and a.role == "stack"
    assert q.origin == "CHoCH" and q.role is None and q.state == "fresh"
    assert (q.low, q.high) == ((85.5, 87.0) if mir else (13.0, 14.5))
    assert book.counts["the_breaker"] == 1 and book.counts["no_the_breaker"] == 0
    book.on_bar_close(bar(9, 22.5, 22.6, 12.0, 12.5, mir))       # the CHoCH's own POI breaks
    assert q.state == "dead" and q.is_breaker is False
    assert {p.id for p in book.breakers} == {a.id, b.id}
    kinds = [d.kind for d in log.items]
    assert kinds.count("poi_born") == 3 and kinds.count("poi_dead") == 3
    assert kinds.count("poi_the_breaker") == 1
    print("POI breakers: last BOS before the CHoCH = the breaker, other = stack, CHoCH POI = no entry")


def test_init_and_missing_opposite_make_no_poi():
    book = PoiBook("M15")
    feed(book, base_bars(False))
    assert book.on_event(ev("INIT", "up", 3, opp_i=2)) is None
    assert book.on_event(ev("BOS", "up", 3, opp_i=None)) is None
    assert book.counts["init_skipped"] == 1 and book.counts["no_opposite"] == 1
    assert book.pois == []


def test_bars_must_arrive_in_order():
    book = PoiBook("M15")
    book.on_bar_close(bar(1, 10.0, 11.0, 9.0, 10.5))
    with pytest.raises(ValueError):
        book.on_bar_close(bar(0, 10.0, 11.0, 9.0, 10.5))
