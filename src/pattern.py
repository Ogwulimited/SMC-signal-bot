"""Detects the Reversal_SingleSweep SMC pattern and derives entry/SL/TP."""

from dataclasses import dataclass
from typing import List, Optional

from .smc import Sweep, CHoCH, BOS, OrderBlock, LiquidityPool
from .config import PATTERN_LOOKBACK_BARS, BUFFER_ATR, MIN_RR


@dataclass
class Pattern:
    direction: str          # "bullish" | "bearish"
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


def detect_patterns(candles, sweeps, chochs, boss, obs, pools, atr):
    """Return patterns whose OB zone is retraced by the latest candle."""
    if atr is None or not candles:
        return []

    patterns: List[Pattern] = []
    last_idx = len(candles) - 1
    last_candle = candles[last_idx]
    buffer = BUFFER_ATR * atr

    for sweep in sweeps:
        # ---- Bullish reversal: swept a low, expecting CHoCH up + BOS up ----
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

            # Retrace: latest candle tapped the OB zone
            if not (last_candle["low"] <= ob.high and last_candle["high"] >= ob.low):
                continue

            entry = (ob.high + ob.low) / 2
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

        # ---- Bearish reversal: swept a high, expecting CHoCH down + BOS down ----
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

            if not (last_candle["low"] <= ob.high and last_candle["high"] >= ob.low):
                continue

            entry = (ob.high + ob.low) / 2
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
    """Unique key for dedupe via state.json."""
    return f"{symbol}|{timeframe}|{p.direction}|{p.sweep.index}|{p.ob.index}"
