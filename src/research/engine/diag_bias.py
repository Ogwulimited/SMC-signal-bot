"""READ-ONLY diagnostic: why do some pairs never get a tradable HTF bias?

Loads data exactly like run_cycle (load_m15 incl. drop_weekend), replays the
real engine once (FlipRecorder subclass), and prints per pair:
  - D1 and H4 bias changes with dates
  - D1 and H4 events seen by the bias tracker, by label and direction
  - first-read progress (sequence of counted swings, longest run vs needed)
  - share of M15 bars where D1/H4 are unset, agree (bull/bear), or split
  - the same share per year
  - a few funnel counters
No engine file is changed. No lookahead cuts are run.

Usage (repo root):  PAIR=usdjpy python -m src.research.engine.diag_bias
"""
import os
import textwrap
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from src import config
from src.research.engine.bias import htf_bias
from src.research.engine.run_cycle import FlipRecorder, load_m15
from src.research.lookahead_guard import DataFeed, DecisionLog

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data" / "diag_bias"
TFS = ("D1", "H4")
FUNNEL_KEYS = ("htf_arm", "htf_bos_no_arm", "htf_bos_ignored_in_pullback",
               "choch_idle", "choch_armed", "disarmed_bias", "pullbacks")


class DiagRecorder(FlipRecorder):
    def __init__(self, log):
        super().__init__(log)
        self.ev_counts = {tf: Counter() for tf in TFS}
        self.seq = {tf: [] for tf in TFS}
        self.combo = Counter()
        self.year = defaultdict(Counter)
        self._wrapped = set()
        self._ensure_wrapped()

    def _ensure_wrapped(self):
        trackers = getattr(self, "bias", None)
        if not trackers:
            return
        for tf in TFS:
            if tf in self._wrapped or tf not in trackers:
                continue
            self._wrap(tf, trackers[tf])
            self._wrapped.add(tf)

    def _wrap(self, tf, tr):
        orig = tr.on_event

        def wrapped(ev):
            was_none = tr.bias == "none"
            before = (getattr(tr, "_count_dir", None), getattr(tr, "_count", 0))
            res = orig(ev)
            self.ev_counts[tf][(ev["label"], ev["direction"])] += 1
            if was_none:
                after = (getattr(tr, "_count_dir", None), getattr(tr, "_count", 0))
                letter = "U" if ev["direction"] == "up" else "D"
                if tr.bias != "none":
                    self.seq[tf].append(letter)
                    self.seq[tf].append("|")
                elif after != before:
                    self.seq[tf].append(letter)
            return res

        tr.on_event = wrapped

    def on_bar_close(self, bar, feed):
        self._ensure_wrapped()
        super().on_bar_close(bar, feed)
        if bar.tf == "M15":
            d1 = self.bias["D1"]
            h4 = self.bias["H4"]
            self.combo[(d1.bias, h4.bias)] += 1
            if d1.bias == "none" or h4.bias == "none":
                tag = "unset"
            elif d1.bias == h4.bias:
                tag = d1.bias
            else:
                tag = "split"
            self.year[bar.close_time.year][tag] += 1


def pct(n, tot):
    return "0.0%" if not tot else f"{100.0 * n / tot:.1f}%"


def longest_run(seq):
    best = cur = 0
    last = None
    for ch in seq:
        if ch == "|":
            continue
        cur = cur + 1 if ch == last else 1
        last = ch
        best = max(best, cur)
    return best


def hist_lines(tr, cap=40):
    rows = []
    for h in tr.history:
        w = " W" if h["warning"] else ""
        rows.append(f"{str(h['time'])[:10]} {h['bias']}{w} {h['reason']}")
    if len(rows) > cap:
        half = cap // 2
        rows = rows[:half] + [f"... {len(rows) - cap} more ..."] + rows[-half:]
    return rows


def diagnose(pair):
    cutoff = pd.Timestamp(config.PRACTICE_END, tz="UTC")
    m15 = load_m15(pair, cutoff)
    log = DecisionLog()
    rec = DiagRecorder(log)
    DataFeed(m15, htf=("H1", "H4", "D1")).run(rec)

    L = []
    L.append(f"##### {pair}  bars {len(m15)}  decisions {len(log.items)}")
    L.append(f"first read needs {rec.bias['D1'].first_read} counted swings")

    for tf in TFS:
        tr = rec.bias[tf]
        L.append("")
        L.append(f"--- {tf} final: {tr.state}")
        L.append(f"{tf} changes: {len(tr.history)}  anomalies: {tr.anomalies}")
        total_ev = sum(rec.ev_counts[tf].values())
        if total_ev == 0:
            L.append(f"{tf} NOTE: wrapper saw 0 events (hook missed?)")
        labels = sorted({k[0] for k in rec.ev_counts[tf]})
        for lab in labels:
            u = rec.ev_counts[tf][(lab, "up")]
            d = rec.ev_counts[tf][(lab, "down")]
            L.append(f"{tf} {lab:5} up {u}  dn {d}")
        seq = "".join(rec.seq[tf])
        L.append(f"{tf} counted-swing run before first read:")
        L.append(f"  longest run {longest_run(seq)}  counted {len(seq.replace('|', ''))}")
        if "|" not in seq:
            L.append(f"  NEVER formed. count now: "
                     f"{getattr(tr, '_count_dir', None)} x {getattr(tr, '_count', 0)}")
        for part in textwrap.wrap(seq, 40) or ["(none)"]:
            L.append("  " + part)
        L.append(f"{tf} bias changes:")
        rows = hist_lines(tr)
        L.extend("  " + r for r in rows) if rows else L.append("  (none)")

    tot = sum(rec.combo.values())
    L.append("")
    L.append(f"--- share of {tot} M15 closes")
    for i, tf in enumerate(TFS):
        none = sum(v for k, v in rec.combo.items() if k[i] == "none")
        bull = sum(v for k, v in rec.combo.items() if k[i] == "bull")
        bear = sum(v for k, v in rec.combo.items() if k[i] == "bear")
        L.append(f"{tf}: none {pct(none, tot)} bull {pct(bull, tot)} bear {pct(bear, tot)}")
    ab = rec.combo[("bull", "bull")]
    ar = rec.combo[("bear", "bear")]
    sp = rec.combo[("bull", "bear")] + rec.combo[("bear", "bull")]
    un = tot - ab - ar - sp
    L.append(f"agree bull {pct(ab, tot)}  agree bear {pct(ar, tot)}")
    L.append(f"split (both set, differ) {pct(sp, tot)}")
    L.append(f"unset (one or both none) {pct(un, tot)}")

    L.append("")
    L.append("--- per year (agree bull/bear, split, unset)")
    for y in sorted(rec.year):
        c = rec.year[y]
        n = sum(c.values())
        L.append(f"{y}: bull {pct(c['bull'], n)} bear {pct(c['bear'], n)} "
                 f"split {pct(c['split'], n)} unset {pct(c['unset'], n)}")

    L.append("")
    L.append("--- funnel counters")
    counts = getattr(rec, "counts", {})
    L.append("  ".join(f"{k}={int(counts.get(k, 0))}" for k in FUNNEL_KEYS[:4]))
    L.append("  ".join(f"{k}={int(counts.get(k, 0))}" for k in FUNNEL_KEYS[4:]))
    L.append(f"bias flips (D1+H4 agree, bull<->bear): {len(rec.flips)}")
    return "\n".join(L)


if __name__ == "__main__":
    pair = os.environ.get("PAIR", "eurusd")
    text = diagnose(pair)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{pair}.txt").write_text(text + "\n")
    print(text, flush=True)
