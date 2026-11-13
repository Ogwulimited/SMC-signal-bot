"""Aggressive-entry track (Step 3b — Option A hybrid lock).

Rules locked with the trader:
  * Same Major HTF bias gate (D1 + H4 agree, 3 swings first read, N=8).
  * Every fresh D1 and H4 POI opened in the bias direction is refined:
        D1 -> H4 -> H1   over [D1 candle open, D1 break close]
        H4 -> H1         over [H4 candle open, H4 break close]
    Inside the window, structure uses N=2 swings and picks the closest
    opposite-colour base candle before an impulsive break.
    - H4 candidate must not be dead (no H4 body close beyond far edge).
    - H1 candidate must be fresh (no H1 body close inside/beyond) AND
      completely untouched by any H1 wick after leaving the box (_h1_clean).
  * No 150-pip distance cap and no ran-away cancel.
  * All fresh D1 and H4 zones stay active (no newer_zone cancel).
  * Timeframe-specific Major CHoCH warning protection (permanent=True):
    - D1 zones only cancel if D1 bias enters warning (ignoring H4 pullback
      warnings on the way to the D1 zone).
    - H4 zones cancel if either D1 or H4 bias enters warning.
  * Target = static 1:5 R:R (RR_AGG = 5.0).
  * Used-zone Rule B: first real FILL spends the D1/H4 zone.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .. import config
from . import poi as poi_mod
from .atr import AtrTracker
from .bias import BiasTracker
from .poi import Poi, PoiBook
from .refinement import pick_base
from .swings import SwingTracker

PIP_DEFAULT = 0.0001
PIP_JPY = 0.01

RR_AGG = 5.0


def pip_size(pair: str) -> float:
    return PIP_JPY if pair.lower().endswith("jpy") else PIP_DEFAULT


@dataclass
class AggSlot:
    htf: Poi
    h4_pick: Optional[Poi]
    h1: Poi
    order: Optional[dict] = None
    spent: bool = False
    cancelled: bool = False


class AggressiveEngine:
    """Runs alongside ZoneEngine or standalone to emit aggressive orders."""

    def __init__(self, pair: str) -> None:
        self.pair = pair
        self.pip = pip_size(pair)
        n_h4 = config.MAJOR_H4_SWING_N if config.MAJOR_HTF else None
        n_d1 = config.MAJOR_D1_SWING_N if config.MAJOR_HTF else None
        first_read = (
            config.MAJOR_BIAS_FIRST_READ if config.MAJOR_HTF
            else config.BIAS_SWINGS_FIRST_READ
        )
        self.swings = {
            "D1": SwingTracker(n_d1),
            "H4": SwingTracker(n_h4),
            "H1": SwingTracker(config.SWING_N["H1"]),
        }
        self.atr = {
            "D1": AtrTracker(), "H4": AtrTracker(), "H1": AtrTracker(),
        }
        self.bias = {
            "D1": BiasTracker(first_read=first_read),
            "H4": BiasTracker(first_read=first_read),
        }
        self.pois = {
            "D1": PoiBook("D1"), "H4": PoiBook("H4"), "H1": PoiBook("H1"),
        }
        # Map from HTF POI id (e.g. "D1-3" or "H4-12") to AggSlot.
        self.slots: Dict[str, AggSlot] = {}
        self.rejected: set[str] = set()
        self.orders: List[dict] = []
        self.flips: List[Tuple[int, str]] = []
        self.counts: Counter = Counter()
        self._last_bias: Optional[str] = None
        self._last_h1: Optional[Tuple[int, float, float, float, float, int]] = None
        self._scan_key: Optional[Tuple] = None

    def current_bias(self) -> Optional[str]:
        b1, b4 = self.bias["D1"].bias, self.bias["H4"].bias
        return b1 if (b1 is not None and b1 == b4) else None

    def _h1_clean(self, h1_poi: Poi, as_of: Optional[int] = None) -> bool:
        """True if no closed H1 candle after the break candle has wicked into the H1 box."""
        book = self.pois["H1"]
        times = book._times
        bars = book._bars
        lo, hi = h1_poi.low, h1_poi.high
        born_open = h1_poi.born_time - 3_600_000
        idx = poi_mod._bsearch_Floor(times, born_open)
        for j in range(idx + 1, len(times)):
            o, h, l, c, ct = bars[times[j]]
            if as_of is not None and ct > as_of:
                break
            if h >= lo and l <= hi:
                return False
        return True

    def _h1_ok(self, c: Poi, as_of: Optional[int] = None) -> bool:
        """True if H1 candidate has no body close inside/beyond and zero wick taps."""
        if c.state != "fresh":
            return False
        if not self._h1_clean(c, as_of=as_of):
            return False
        return True

    def on_bar(self, tf: str, o: float, h: float, l: float, c: float,
               open_time: int, close_time: int) -> None:
        if tf not in self.swings:
            return
        self.atr[tf].update(h, l, c)
        atr_now = self.atr[tf].value
        self.pois[tf].Push_bar(open_time, o, h, l, c, close_time)
        new_sw = self.swings[tf].update(open_time, h, l)

        if tf in ("D1", "H4"):
            for s in new_sw:
                self.bias[tf].on_swing(s)
            ev = self.bias[tf].on_bar_close(c, close_time, atr_now)
            if ev is not None:
                kind, side, s_time = ev
                p = self.pois[tf].Create_on_break(
                    kind, side, s_time, open_time, close_time
                )
                if p is not None:
                    self.counts[f"ag_zones_{tf}"] += 1
            self.pois[tf].Update_states_on_close(c, close_time)
            hb = self.current_bias()
            if hb != self._last_bias:
                if self._last_bias is not None:
                    self.flips.append((close_time, hb or "none"))
                self._last_bias = hb
            return

        # H1 bar: record structure events so H1 PoiBook has the N=2 POIs
        # inside every HTF impulse window.
        for s in new_sw:
            pass
        self._update_h1_pois(c, open_time, close_time, atr_now)
        self.pois["H1"].Update_states_on_close(c, close_time)
        self._last_h1 = (open_time, o, h, l, c, close_time)
        self._step_h1(o, h, l, c, open_time, close_time)

    # ---- lightweight N=2 BOS/CHoCH detector on H1 for PoiBook population ----
    def _update_h1_pois(self, c: float, open_time: int, close_time: int,
                        atr_now: Optional[float]) -> None:
        if not hasattr(self, "_h1_struct"):
            self._h1_struct = BiasTracker(first_read=1)
        for s in self.swings["H1"].swings[-2:]:
            if getattr(self, "_h1_last_sw", -1) < s.index:
                self._h1_struct.on_swing(s)
                self._h1_last_sw = s.index
        ev = self._h1_struct.on_bar_close(c, close_time, atr_now)
        if ev is not None:
            kind, side, s_time = ev
            self.pois["H1"].Create_on_break(
                kind, side, s_time, open_time, close_time
            )

    # ---- per-H1-bar aggressive slot management ----
    def _step_h1(self, o: float, h: float, l: float, c: float,
                 open_time: int, close_time: int) -> None:
        hb = self.current_bias()
        d1_warn = self.bias["D1"].warning
        h4_warn = self.bias["H4"].warning

        # Check active orders for fills / cancels on this H1 bar.
        for key, slot in list(self.slots.items()):
            if slot.spent or slot.cancelled or slot.order is None:
                continue
            want = "buy" if slot.htf.side == "bull" else "sell"
            if hb is None or (hb == "bull" and want != "buy") or (
                hb == "bear" and want != "sell"
            ):
                self._cancel(key, close_time, "bias_lost", True)
                continue

            # D1 zones only cancel on D1 warning; H4 zones cancel on D1 or H4 warning.
            warn_now = d1_warn if slot.htf.tf == "D1" else (d1_warn or h4_warn)
            if warn_now:
                self._cancel(key, close_time, "bias_warning", True)
                continue

            if slot.htf.state == "dead":
                self._cancel(key, close_time, "zone_far_break", True)
                continue
            # Did this H1 bar reach the entry edge?
            od = slot.order
            touched = (l <= od["entry"]) if want == "buy" else (h >= od["entry"])
            if touched:
                self._try_fill_or_skip(slot, o, h, l, close_time)

        if hb is None:
            self._scan_key = None
            return

        # Re-scan only when bias, warnings, or POI count changes.
        key_now = (
            hb,
            d1_warn,
            h4_warn,
            len(self.pois["D1"].all()),
            len(self.pois["H4"].all()),
        )
        if key_now == self._scan_key:
            return
        self._scan_key = key_now
        self._scan(hb, d1_warn, h4_warn, close_time)

    def _scan(self, hb: str, d1_warn: bool, h4_warn: bool, now: int) -> None:
        want_side = "bull" if hb == "bull" else "bear"
        atr_h1 = self.atr["H1"].value
        if atr_h1 is None or atr_h1 <= 0:
            return

        for tf in ("D1", "H4"):
            # Timeframe-specific warning gate before placing new orders
            if tf == "D1" and d1_warn:
                continue
            if tf == "H4" and (d1_warn or h4_warn):
                continue

            for p in self.pois[tf].all():
                if p.side != want_side or p.state != "fresh":
                    continue
                if p.id in self.slots or p.id in self.rejected:
                    continue
                slot = self._refine(p, now)
                if slot is None:
                    self.rejected.add(p.id)
                    continue
                self._place(slot, atr_h1, now)
                self.slots[p.id] = slot

    def _refine(self, p: Poi, now: int) -> Optional[AggSlot]:
        if p.tf == "D1":
            h4_all = self.pois["H4"].Candidates_in(
                p.candle_time, p.born_time, p.side
            )
            if not h4_all:
                self.counts["ag_no_h4_candidate"] += 1
                return None
            h4_cands = []
            for c in h4_all:
                if c.state != "dead":
                    h4_cands.append(c)
                else:
                    self.counts["ag_h4_cand_dead"] += 1
            if not h4_cands:
                self.counts["ag_h4_all_dead"] += 1
                return None
            h4_pick = pick_base(p.low, p.high, h4_cands)
            if h4_pick is None:
                return None

            h1_all = self.pois["H1"].Candidates_in(
                h4_pick.candle_time, p.born_time, p.side
            )
            if not h1_all:
                self.counts["ag_no_h1_candidate"] += 1
                return None
            h1_cands = []
            for c in h1_all:
                if self._h1_ok(c, as_of=now):
                    h1_cands.append(c)
                else:
                    self.counts["ag_h1_cand_mitigated"] += 1
            if not h1_cands:
                self.counts["ag_h1_all_mitigated"] += 1
                return None
            h1_pick = pick_base(h4_pick.low, h4_pick.high, h1_cands)
            if h1_pick is None:
                return None
            return AggSlot(htf=p, h4_pick=h4_pick, h1=h1_pick)

        # H4 zone -> H1 directly.
        h1_all = self.pois["H1"].Candidates_in(
            p.candle_time, p.born_time, p.side
        )
        if not h1_all:
            self.counts["ag_no_h1_candidate"] += 1
            return None
        h1_cands = []
        for c in h1_all:
            if self._h1_ok(c, as_of=now):
                h1_cands.append(c)
            else:
                self.counts["ag_h1_cand_mitigated"] += 1
        if not h1_cands:
            self.counts["ag_h1_all_mitigated"] += 1
            return None
        h1_pick = pick_base(p.low, p.high, h1_cands)
        if h1_pick is None:
            return None
        return AggSlot(htf=p, h4_pick=None, h1=h1_pick)

    def _place(self, slot: AggSlot, atr_h1: float, now: int) -> None:
        # Final safety check before arming limit: ensure H4/H1 boxes are still unmitigated at 'now'.
        if slot.h4_pick is not None and slot.h4_pick.state == "dead":
            slot.cancelled = True
            self.counts["ag_drop_h4_dead"] += 1
            return
        if not self._h1_ok(slot.h1, as_of=now):
            slot.cancelled = True
            self.counts["ag_drop_h1_mitigated"] += 1
            return

        h1 = slot.h1
        direction = "buy" if slot.htf.side == "bull" else "sell"
        buf = config.STOP_BUFFER_ATR * atr_h1
        if direction == "buy":
            entry = h1.high
            stop = h1.low - buf
            risk = entry - stop
            target = entry + RR_AGG * risk
        else:
            entry = h1.low
            stop = h1.high + buf
            risk = stop - entry
            target = entry - RR_AGG * risk
        if risk <= 0:
            slot.cancelled = True
            self.counts["ag_bad_risk"] += 1
            return

        chain = (
            f"{slot.htf.id}->{slot.h4_pick.id}->{h1.id}"
            if slot.h4_pick is not None else f"{slot.htf.id}->{h1.id}"
        )
        od = {
            "pair": self.pair,
            "leg": "aggressive",
            "entry_type": "ag_ob",
            "direction": direction,
            "fill": "limit",
            "placed_time": now,
            "entry": entry,
            "stop": stop,
            "risk": risk,
            "rr": RR_AGG,
            "target_static": target,
            "target_liq": target,
            "htf_poi_id": slot.htf.id,
            "htf_tf": slot.htf.tf,
            "htf_born": slot.htf.born_time,
            "h4_poi_id": slot.h4_pick.id if slot.h4_pick else None,
            "h1_poi_id": h1.id,
            "h1_low": h1.low,
            "h1_high": h1.high,
            "chain": chain,
            "cancel_time": None,
            "cancel_reason": None,
        }
        slot.order = od
        self.orders.append(od)
        self.counts["ag_slots"] += 1
        self.counts["ag_orders"] += 1

    def _try_fill_or_skip(self, slot: AggSlot, o: float, h: float, l: float,
                          now: int) -> None:
        """Mirror simulator's fill / spread-skip / beyond-stop decision so
        Used-zone Rule B marks the HTF zone spent ONLY on a real fill."""
        from .. import simulate_orders as sim
        od = slot.order
        spread = sim.get_spread_pips(self.pair) * self.pip
        if spread / od["risk"] > config.MAX_SPREAD_RISK_RATIO:
            # Simulator will skip_spread this order and retry on a later touch
            # if we kept it open — so cancel this order at open of bar and
            # leave the HTF zone unspent (Rule B).
            od["cancel_time"] = now - 1
            od["cancel_reason"] = "spread_skip"
            slot.order = None
            slot.cancelled = True
            self.counts["ag_skip_spread"] += 1
            return
        want = od["direction"]
        fill_at_open = (o <= od["entry"]) if want == "buy" else (o >= od["entry"])
        if fill_at_open:
            fill_px = o
            beyond = (fill_px <= od["stop"]) if want == "buy" else (
                fill_px >= od["stop"]
            )
            if beyond:
                slot.order = None
                slot.cancelled = True
                self.counts["ag_skip_beyond_stop"] += 1
                return
            self.counts["ag_fill_at_open"] += 1
        # Real fill -> Rule B spends the HTF zone permanently.
        slot.spent = True
        slot.htf.state = "used"
        slot.htf.used_time = now
        self.counts["ag_zone_spent"] += 1

    def _cancel(self, key: str, now: int, reason: str,
                permanent: bool) -> None:
        slot = self.slots[key]
        if slot.order is not None and slot.order["cancel_time"] is None:
            slot.order["cancel_time"] = now
            slot.order["cancel_reason"] = reason
        slot.order = None
        slot.cancelled = True
        self.counts[f"ag_cancel_{reason}"] += 1
        if not permanent:
            del self.slots[key]
