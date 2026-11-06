"""Batch 2 strategy: structure + POI books + bias, all incremental.

Runs M15, H4 and D1 structure. Each timeframe has a POI book. H4 and D1 also
have a bias tracker. H1 bars feed the ATR tracker. Everything is logged as
decisions so the poison test can check it.

config.MAJOR_HTF (default False): when True, H4 and D1 use the Major swing
sizes (MAJOR_H4_SWING_N, MAJOR_D1_SWING_N) and the bias trackers use
MAJOR_BIAS_FIRST_READ. M15 never changes.
"""
import pandas as pd

from src import config
from src.research.engine.atr import ATRTracker
from src.research.engine.bias import BiasTracker
from src.research.engine.poi import PoiBook
from src.research.engine.structure import IncrementalStructure
from src.research.lookahead_guard import DataFeed, DecisionLog


class MapRecorder:
    def __init__(self, log):
        self.log = log
        self.events = []
        self.atr = ATRTracker(config.ATR_PERIOD)
        major = bool(getattr(config, "MAJOR_HTF", False))
        h4_n = config.MAJOR_H4_SWING_N if major else config.H4_SWING_N
        d1_n = config.MAJOR_D1_SWING_N if major else config.D1_SWING_N
        first = config.MAJOR_BIAS_FIRST_READ if major else None
        self.engines = {
            "M15": IncrementalStructure(config.LTF_SWING_N, pd.Timedelta(minutes=15), "M15"),
            "H4": IncrementalStructure(h4_n, pd.Timedelta(hours=4), "H4"),
            "D1": IncrementalStructure(d1_n, pd.Timedelta(days=1), "D1"),
        }
        self.books = {tf: PoiBook(tf, log) for tf in self.engines}
        self.bias = {"H4": BiasTracker("H4", log, first),
                     "D1": BiasTracker("D1", log, first)}

    def on_bar_close(self, bar, feed):
        if bar.tf == "H1":
            self.atr.on_bar_close(bar)
            return
        eng = self.engines.get(bar.tf)
        if eng is None:
            return
        ev = eng.on_bar_close(bar)
        book = self.books[bar.tf]
        book.on_bar_close(bar)
        if ev is None:
            return
        self.events.append(ev)
        self.log.add("structure_" + bar.tf, ev["time"], ev["known_at"],
                     label=ev["label"], direction=ev["direction"], close=ev["close"],
                     broken_swing_time=ev["broken_swing_time"],
                     broken_swing_price=ev["broken_swing_price"],
                     last_opposite_time=ev["last_opposite_time"],
                     last_opposite_price=ev["last_opposite_price"])
        book.on_event(ev)
        tracker = self.bias.get(bar.tf)
        if tracker is not None:
            tracker.on_event(ev)


def run_map_pipeline(m15):
    """Feed -> structure, POI books, bias -> decisions (used by the poison test)."""
    log = DecisionLog()
    DataFeed(m15, htf=("H1", "H4", "D1")).run(MapRecorder(log))
    return log.items
