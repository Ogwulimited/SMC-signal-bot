"""Detects the Reversal_SingleSweep SMC pattern and derives entry/SL/TP."""

from dataclasses import dataclass
from typing import List

from .smc import Sweep, CHoCH, BOS, OrderBlock
from .config import (
    PATTERN_LOOKBACK_BARS, BUFFER_ATR, MIN_RR,
    MIN_SWEEP_PENETRATION_ATR, MAX_BARS_SWEEP_TO_ENTRY, MAX_OB_AGE_BARS,
)


@dataclass
class Pattern:
    direction: str
    sweep: Sweep
    choch: CHoCH
    bos: BOS
    ob: OrderBlock
    entry: float
    stop: float
    target: float
    rr: float
    retrace_index: int


def _nearest_target_above(pools, price):
    candidates = [
        p for p in pools
        if p.price > price and not p.swept
        and p.kind in ("EQH", "swing_high")
    ]
    return min(candidates, key=lambda p: p.price).price if candidates else None


def _nearest_target_below(pools, price):
    candidates = [
        p for p in pools
        if p.price < price and not p.swept
        and p.kind in ("EQL", "swing_low")
    ]
    return max(candidates, key=lambda p: p.price).price if candidates else None


def _sweep_penetration(candles, sweep):
    c = candles[sweep.index]
    if sweep.direction == "up":
        return c["high"] - sweep.pool_price
    return sweep.pool_price - c["low"]


def _ob_already_tapped(candles, ob, before_idx):
    for k in range(ob.index + 1, before_idx):
        c = candles[k]
        if c["low"] <= ob.high and c["high"] >= ob.low:
            return True
    return False


def detect_patterns(candles, sweeps, chochs, boss, obs, pools, atr):
    """Return patterns where the CURRENT bar produced a REAL fill at entry.

    A fill is real only if the bar's range actually reached the entry price
    (OB midpoint), not just the outer edge of the OB zone.
    """
    if atr is None or not candles:
        return []

    patterns: List[Pattern] = []
    last_idx = len(candles) - 1
    last_candle = candles[last_idx]
    buffer = BUFFER_ATR * atr
    min_pen = MIN_SWEEP_PENETRATION_ATR * atr

    for sweep in sweeps:
        if last_idx - sweep.index > MAX_BARS_SWEEP_TO_ENTRY:
            continue
        if _sweep_penetration(candles, sweep) < min_pen:
            continue

        # ---- Bullish reversal ----
        if sweep.direction == "down":
            choch = next(
                (c for c in chochs
                 if c.direction == "up"
                 and sweep.index < c.index <= sweep.index + PATTERN_LOOKBACK_BARS),
                None,
            )
            if choch is None:
                continue
            bos = next(
                (b for b in boss
                 if b.direction == "up"
                 and choch.index < b.index <= choch.index + PATTERN_LOOKBACK_BARS),
                None,
            )
            if bos is None:
                continue
            ob = next(
                (o for o in obs
                 if o.direction == "bullish" and o.bos_index == bos.index),
                None,
            )
            if ob is None:
                continue

            if last_idx - ob.index > MAX_OB_AGE_BARS:
                continue
            if _ob_already_tapped(candles, ob, last_idx):
                continue

            # FILL REALISM: current bar's low must have reached entry (OB mid)
            entry = (ob.high + ob.low) / 2
            if last_candle["low"] > entry:
                continue  # bar only grazed the top of the OB — no fill

            stop = ob.low - buffer
            target = _nearest_target_above(pools, entry)
            if target is None or target <= entry or entry <= stop:
                continue
            rr = (target - entry) / (entry - stop)
            if rr < MIN_RR:
                continue

            patterns.append(Pattern(
                direction="bullish", sweep=sweep, choch=choch, bos=bos, ob=ob,
                entry=entry, stop=stop, target=target, rr=rr, retrace_index=last_idx,
            ))

        # ---- Bearish reversal ----
        elif sweep.direction == "up":
            choch = next(
                (c for c in chochs
                 if c.direction == "down"
                 and sweep.index < c.index <= sweep.index + PATTERN_LOOKBACK_BARS),
                None,
            )
            if choch is None:
                continue
            bos = next(
                (b for b in boss
                 if b.direction == "down"
                 and choch.index < b.index <= choch.index + PATTERN_LOOKBACK_BARS),
                None,
            )
            if bos is None:
                continue
            ob = next(
                (o for o in obs
                 if o.direction == "bearish" and o.bos_index == bos.index),
                None,
            )
            if ob is None:
                continue

            if last_idx - ob.index > MAX_OB_AGE_BARS:
                continue
            if _ob_already_tapped(candles, ob, last_idx):
                continue

            # FILL REALISM: current bar's high must have reached entry (OB mid)
            entry = (ob.high + ob.low) / 2
            if last_candle["high"] < entry:
                continue  # bar only grazed the bottom of the OB — no fill

            stop = ob.high + buffer
            target = _nearest_target_below(pools, entry)
            if target is None or target >= entry or stop <= entry:
                continue
            rr = (entry - target) / (stop - entry)
            if rr < MIN_RR:
                continue

            patterns.append(Pattern(
                direction="bearish", sweep=sweep, choch=choch, bos=bos, ob=ob,
                entry=entry, stop=stop, target=target, rr=rr, retrace_index=last_idx,
            ))

    return patterns


def pattern_signature(symbol: str, timeframe: str, p: Pattern) -> str:
    return f"{symbol}|{timeframe}|{p.direction}|{p.sweep.index}|{p.ob.index}"
