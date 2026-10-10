"""Continuation v3 — cascading multi-TF OB + flexible liquidity confluence.

Detection logic:
  1. D1 bias required (same as baseline).
  2. Try H1 OB first. If none clean, fall back to M15 OB.
  3. Confluence: at least ONE of {FVG, EQH/EQL, IDM, time-based liq} near OB.
  4. Target: nearest pool (any type) yielding R:R >= 1.5.

Does NOT modify src/continuation.py. Live bot keeps using v1.
"""

from dataclasses import dataclass
from typing import List, Optional

from ..smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    find_time_based_liquidity, compute_atr,
)
from ..fvg import find_fvgs_in_range
from ..config import (
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR,
    BUFFER_ATR, MIN_RR, MIN_TARGET_ATR, MIN_OB_WIDTH_ATR,
    MIN_CONT_FVG_ATR, CONT_LIQUIDITY_TOL_ATR, CONT_MAX_OB_AGE,
    CONT_MAX_BARS_BOS_TO_TOUCH, HTF_SWING_LOOKBACK,
    USE_TIME_BASED_LIQUIDITY,
)


SYNTHETIC_TARGET_ATR = 2.0

UPSIDE_KINDS = ("EQH", "swing_high", "PDH", "weekly_high",
                "asia_high", "london_high", "ny_high")
DOWNSIDE_KINDS = ("EQL", "swing_low", "PDL", "weekly_low",
                  "asia_low", "london_low", "ny_low")

CONFLUENCE_FVG = "FVG"
CONFLUENCE_EQ = "EQH/EQL"
CONFLUENCE_IDM = "IDM"
CONFLUENCE_TIME = "TIME_LIQ"


@dataclass
class ContinuationPatternV3:
    direction: str
    entry_tf: str             # "H1" or "M15"
    ob_index: int             # relative to the window for the entry TF
    bos_index: int
    touch_index: int          # relative to the H1 window (always)
    ob_high: float
    ob_low: float
    entry: float
    stop: float
    target: float
    rr: float
    confluences: List[str]
    target_kind: str
    target_is_synthetic: bool
    atr_entry: float


# ---------------- helpers ----------------

def detect_htf_bias(d1_candles) -> Optional[str]:
    if not d1_candles or len(d1_candles) < HTF_SWING_LOOKBACK * 2 + 10:
        return None
    swings = find_swings(d1_candles, HTF_SWING_LOOKBACK)
    if not swings:
        return None
    _, _, trend = detect_bos_choch(d1_candles, swings)
    if trend == "up":
        return "bullish"
    if trend == "down":
        return "bearish"
    return None


def _has_fvg(candles, ob_idx, bos_idx, direction, atr):
    fvgs = find_fvgs_in_range(candles, ob_idx, bos_idx, direction, atr)
    min_size = MIN_CONT_FVG_ATR * atr
    for f in fvgs:
        if (f["high"] - f["low"]) >= min_size:
            return True
    return False


def _eq_pool_nearby(pools, direction, ob_high, ob_low, atr):
    tol = CONT_LIQUIDITY_TOL_ATR * atr
    if direction == "bullish":
        for p in pools:
            if p.kind == "EQL" and p.price < ob_low:
                if (ob_low - p.price) <= tol:
                    return True
    else:
        for p in pools:
            if p.kind == "EQH" and p.price > ob_high:
                if (p.price - ob_high) <= tol:
                    return True
    return False


def _time_pool_nearby(pools, direction, ob_high, ob_low, atr):
    tol = CONT_LIQUIDITY_TOL_ATR * atr
    time_kinds_up = ("PDH", "weekly_high", "asia_high", "london_high", "ny_high")
    time_kinds_down = ("PDL", "weekly_low", "asia_low", "london_low", "ny_low")
    if direction == "bullish":
        for p in pools:
            if p.kind in time_kinds_down and p.price < ob_low:
                if (ob_low - p.price) <= tol:
                    return True
    else:
        for p in pools:
            if p.kind in time_kinds_up and p.price > ob_high:
                if (p.price - ob_high) <= tol:
                    return True
    return False


def _idm_swept(candles, ob_idx, bos_idx, direction, entry, swings,
                max_sweep_age=30):
    """Inducement: minor opposite-direction swing between BOS and current
    that has since been swept."""
    last_idx = len(candles) - 1
    if direction == "bullish":
        candidates = [s for s in swings if s.kind == "low"
                      and bos_idx < s.index < last_idx and s.price > entry]
        for c in candidates:
            start = max(c.index + 1, last_idx - max_sweep_age)
            for j in range(start, last_idx):
                if candles[j]["low"] < c.price:
                    return True
        return False
    else:
        candidates = [s for s in swings if s.kind == "high"
                      and bos_idx < s.index < last_idx and s.price < entry]
        for c in candidates:
            start = max(c.index + 1, last_idx - max_sweep_age)
            for j in range(start, last_idx):
                if candles[j]["high"] > c.price:
                    return True
        return False


def _nearest_target_with_min_rr(pools, direction, entry, stop):
    """Return (target_price, kind, rr, is_synthetic) with the nearest pool
    that yields R:R >= MIN_RR. Falls back to synthetic."""
    if direction == "bullish":
        cands = sorted([p for p in pools if p.price > entry and not p.swept
                        and p.kind in UPSIDE_KINDS],
                       key=lambda p: p.price)
        for c in cands:
            rr = (c.price - entry) / (entry - stop) if entry > stop else 0
            if rr >= MIN_RR:
                if (c.price - entry) >= MIN_TARGET_ATR * 1.0:
                    return c.price, c.kind, rr, False
        # Fallback synthetic
        syn = entry + SYNTHETIC_TARGET_ATR * (entry - stop)
        rr = (syn - entry) / (entry - stop)
        if rr >= MIN_RR:
            return syn, "synthetic", rr, True
    else:
        cands = sorted([p for p in pools if p.price < entry and not p.swept
                        and p.kind in DOWNSIDE_KINDS],
                       key=lambda p: -p.price)
        for c in cands:
            rr = (entry - c.price) / (stop - entry) if stop > entry else 0
            if rr >= MIN_RR:
                if (entry - c.price) >= MIN_TARGET_ATR * 1.0:
                    return c.price, c.kind, rr, False
        syn = entry - SYNTHETIC_TARGET_ATR * (stop - entry)
        rr = (entry - syn) / (stop - entry)
        if rr >= MIN_RR:
            return syn, "synthetic", rr, True
    return None, None, 0, False


def _find_ob_before_bos(candles, bos_idx, direction, max_lookback=15):
    for j in range(bos_idx - 1, max(0, bos_idx - max_lookback) - 1, -1):
        c = candles[j]
        if direction == "bullish" and c["close"] < c["open"]:
            return j
        if direction == "bearish" and c["close"] > c["open"]:
            return j
    return None


def _confluences_present(candles, entry_tf, ob_idx, bos_idx, direction,
                          entry, ob_high, ob_low, pools, swings, atr):
    """Return the set of confluences present for this OB."""
    found = []
    if _has_fvg(candles, ob_idx, bos_idx, direction, atr):
        found.append(CONFLUENCE_FVG)
    if _eq_pool_nearby(pools, direction, ob_high, ob_low, atr):
        found.append(CONFLUENCE_EQ)
    if _idm_swept(candles, ob_idx, bos_idx, direction, entry, swings):
        found.append(CONFLUENCE_IDM)
    if _time_pool_nearby(pools, direction, ob_high, ob_low, atr):
        found.append(CONFLUENCE_TIME)
    return found


def _scan_tf_for_signals(candles, entry_tf, bias, atr, all_pools, swings):
    """Try to find a fresh touch signal on this TF. Returns list of patterns."""
    if atr is None or atr <= 0:
        return []

    bos_events, _, trend = detect_bos_choch(candles, swings)
    if bias == "bullish" and trend == "down":
        return []
    if bias == "bearish" and trend == "up":
        return []

    last_idx = len(candles) - 1
    last = candles[last_idx]
    out = []

    for bos in bos_events:
        if last_idx - bos.index > CONT_MAX_BARS_BOS_TO_TOUCH:
            continue
        if bias == "bullish" and bos.direction != "up":
            continue
        if bias == "bearish" and bos.direction != "down":
            continue

        ob_idx = _find_ob_before_bos(candles, bos.index, bias)
        if ob_idx is None:
            continue

        ob = candles[ob_idx]
        ob_high = ob["high"]
        ob_low = ob["low"]

        if (ob_high - ob_low) < MIN_OB_WIDTH_ATR * atr:
            continue
        if last_idx - ob_idx > CONT_MAX_OB_AGE:
            continue

        entry = (ob_high + ob_low) / 2

        # Fresh touch on this bar
        if bias == "bullish":
            if last["low"] > entry:
                continue
        else:
            if last["high"] < entry:
                continue

        # Prior touch check
        touched_before = False
        for k in range(bos.index + 1, last_idx):
            c = candles[k]
            if c["low"] <= entry <= c["high"]:
                touched_before = True
                break
        if touched_before:
            continue

        # Confluence check — ANY ONE
        confluences = _confluences_present(
            candles, entry_tf, ob_idx, bos.index, bias,
            entry, ob_high, ob_low, all_pools, swings, atr,
        )
        if not confluences:
            continue

        # Build stop
        if bias == "bullish":
            stop = ob_low - BUFFER_ATR * atr
            if entry <= stop:
                continue
        else:
            stop = ob_high + BUFFER_ATR * atr
            if stop <= entry:
                continue

        # Target: nearest pool with R:R >= 1.5
        target, target_kind, rr, syn = _nearest_target_with_min_rr(
            all_pools, bias, entry, stop,
        )
        if target is None:
            continue

        out.append(ContinuationPatternV3(
            direction=bias,
            entry_tf=entry_tf,
            ob_index=ob_idx,
            bos_index=bos.index,
            touch_index=last_idx,
            ob_high=ob_high,
            ob_low=ob_low,
            entry=entry,
            stop=stop,
            target=target,
            rr=rr,
            confluences=confluences,
            target_kind=target_kind,
            target_is_synthetic=syn,
            atr_entry=atr,
        ))

    return out


def detect_continuation_signals_v3(h1_window, m15_window, d1_candles):
    """Cascading multi-TF detection.

    Returns list of patterns firing on the last H1 bar. Signals carry
    a .touch_index relative to the H1 window (for downstream simulation).

    If an H1 signal exists → return only H1 signals (H1 wins).
    Otherwise → return M15 signals mapped to the H1 window.
    """
    bias = detect_htf_bias(d1_candles)
    if bias is None:
        return []

    if len(h1_window) < SWING_LOOKBACK * 2 + ATR_PERIOD + 50:
        return []

    atr_h1 = compute_atr(h1_window, ATR_PERIOD)
    if atr_h1 is None:
        return []

    h1_swings = find_swings(h1_window, SWING_LOOKBACK)
    if not h1_swings:
        return []

    h1_pools = find_liquidity_pools(h1_window, h1_swings, atr_h1, EQ_TOLERANCE_ATR)
    if USE_TIME_BASED_LIQUIDITY:
        h1_pools = h1_pools + find_time_based_liquidity(
            h1_window, h1_window[-1]["epoch"]
        )

    # --- Try H1 first ---
    h1_signals = _scan_tf_for_signals(
        h1_window, "H1", bias, atr_h1, h1_pools, h1_swings,
    )
    if h1_signals:
        return h1_signals

    # --- Fall back to M15 ---
    if not m15_window or len(m15_window) < 50:
        return []

    last_h1_epoch = h1_window[-1]["epoch"]
    # M15 window through the same time as the last H1 bar
    m15_window_cut = [c for c in m15_window if c["epoch"] <= last_h1_epoch]
    if len(m15_window_cut) < 50:
        return []

    atr_m15 = compute_atr(m15_window_cut, ATR_PERIOD)
    if atr_m15 is None:
        return []

    m15_swings = find_swings(m15_window_cut, SWING_LOOKBACK)
    if not m15_swings:
        return []

    m15_pools = find_liquidity_pools(
        m15_window_cut, m15_swings, atr_m15, EQ_TOLERANCE_ATR,
    )
    if USE_TIME_BASED_LIQUIDITY:
        m15_pools = m15_pools + find_time_based_liquidity(
            m15_window_cut, m15_window_cut[-1]["epoch"]
        )

    m15_signals = _scan_tf_for_signals(
        m15_window_cut, "M15", bias, atr_m15, m15_pools, m15_swings,
    )

    # Map M15 touch_index to H1 index
    # Find the last H1 bar whose epoch <= m15 signal's touch epoch
    for s in m15_signals:
        touch_m15_epoch = m15_window_cut[s.touch_index]["epoch"]
        # Find H1 index of last H1 bar with epoch <= touch_m15_epoch
        # In practice: the last H1 bar (index -1) is the one we simulate from
        # because we're checking "did M15 fire inside the current H1 bar"
        s.touch_index = len(h1_window) - 1

    return m15_signals