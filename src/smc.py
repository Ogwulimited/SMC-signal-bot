"""SMC structural primitives: swings, BOS/CHoCH, liquidity, sweeps, order blocks."""

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Swing:
    index: int
    price: float
    kind: str


@dataclass
class BOS:
    index: int
    direction: str
    broken_swing_index: int
    broken_price: float


@dataclass
class CHoCH:
    index: int
    direction: str
    from_trend: str
    broken_swing_index: int
    broken_price: float


@dataclass
class LiquidityPool:
    kind: str
    price: float
    swing_indices: List[int]
    swept: bool = False
    swept_index: Optional[int] = None


@dataclass
class Sweep:
    index: int
    direction: str
    pool_price: float
    pool_kind: str


@dataclass
class OrderBlock:
    direction: str
    index: int
    high: float
    low: float
    bos_index: int
    mitigated: bool = False


def compute_atr(candles, period=14):
    if len(candles) < period + 1:
        return None
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period


def find_swings(candles, n=2):
    swings = []
    for i in range(n, len(candles) - n):
        high = candles[i]["high"]
        low = candles[i]["low"]
        is_high = all(candles[j]["high"] < high for j in range(i - n, i)) and \
                  all(candles[j]["high"] < high for j in range(i + 1, i + n + 1))
        is_low = all(candles[j]["low"] > low for j in range(i - n, i)) and \
                 all(candles[j]["low"] > low for j in range(i + 1, i + n + 1))
        if is_high:
            swings.append(Swing(index=i, price=high, kind="high"))
        if is_low:
            swings.append(Swing(index=i, price=low, kind="low"))
    return swings


def detect_bos_choch(candles, swings):
    bos_events: List[BOS] = []
    choch_events: List[CHoCH] = []
    trend = None
    swings_sorted = sorted(swings, key=lambda s: s.index)
    consumed = set()

    for i, c in enumerate(candles):
        sh = None
        sl = None
        for s in reversed(swings_sorted):
            if s.index >= i or s.index in consumed:
                continue
            if s.kind == "high" and sh is None:
                sh = s
            elif s.kind == "low" and sl is None:
                sl = s
            if sh is not None and sl is not None:
                break

        if sh is not None and c["close"] > sh.price:
            if trend == "up":
                bos_events.append(BOS(i, "up", sh.index, sh.price))
            else:
                choch_events.append(CHoCH(i, "up", trend or "none", sh.index, sh.price))
                trend = "up"
                for s in swings_sorted:
                    if s.kind == "low" and s.index < i:
                        consumed.add(s.index)
            consumed.add(sh.index)

        if sl is not None and c["close"] < sl.price:
            if trend == "down":
                bos_events.append(BOS(i, "down", sl.index, sl.price))
            else:
                choch_events.append(CHoCH(i, "down", trend or "none", sl.index, sl.price))
                trend = "down"
                for s in swings_sorted:
                    if s.kind == "high" and s.index < i:
                        consumed.add(s.index)
            consumed.add(sl.index)

    return bos_events, choch_events, trend


def find_liquidity_pools(candles, swings, atr, eq_tol_atr=0.15):
    pools: List[LiquidityPool] = []
    highs = [s for s in swings if s.kind == "high"]
    lows = [s for s in swings if s.kind == "low"]
    tol = (atr * eq_tol_atr) if atr else 0.0

    used = set()
    for i, s1 in enumerate(highs):
        if i in used:
            continue
        group = [s1]
        for j in range(i + 1, len(highs)):
            if j in used:
                continue
            if abs(highs[j].price - s1.price) <= tol:
                group.append(highs[j])
                used.add(j)
        if len(group) >= 2:
            pools.append(LiquidityPool(
                kind="EQH",
                price=sum(s.price for s in group) / len(group),
                swing_indices=[s.index for s in group],
            ))

    used = set()
    for i, s1 in enumerate(lows):
        if i in used:
            continue
        group = [s1]
        for j in range(i + 1, len(lows)):
            if j in used:
                continue
            if abs(lows[j].price - s1.price) <= tol:
                group.append(lows[j])
                used.add(j)
        if len(group) >= 2:
            pools.append(LiquidityPool(
                kind="EQL",
                price=sum(s.price for s in group) / len(group),
                swing_indices=[s.index for s in group],
            ))

    for s in swings:
        pools.append(LiquidityPool(
            kind="swing_high" if s.kind == "high" else "swing_low",
            price=s.price,
            swing_indices=[s.index],
        ))

    return pools


# ---------- Time-based liquidity (PDH/PDL, weekly, sessions) ----------

def _utc_hour(epoch):
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc).hour


def _utc_day_start(epoch):
    d = dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp())


def _utc_week_start(epoch):
    d = dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)
    day_start = dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc)
    monday = day_start - dt.timedelta(days=d.weekday())
    return int(monday.timestamp())


def find_time_based_liquidity(candles, as_of_epoch):
    """Return PDH/PDL, prior-week high/low, and prior-session extremes.

    Uses ONLY candles strictly before as_of_epoch. No look-ahead.
    Sessions use UTC windows:
      Asia:   00:00-06:00
      London: 07:00-16:00
      NY:     12:00-21:00
    """
    pools: List[LiquidityPool] = []

    # We only need the last ~10 days of bars
    cutoff = as_of_epoch - 10 * 86400
    recent = [c for c in candles if cutoff <= c["epoch"] < as_of_epoch]
    if not recent:
        return pools

    cur_day_start = _utc_day_start(as_of_epoch)

    # --- Previous completed day ---
    pd_start = cur_day_start - 86400
    pd_bars = [c for c in recent if pd_start <= c["epoch"] < cur_day_start]
    if pd_bars:
        pdh = max(c["high"] for c in pd_bars)
        pdl = min(c["low"] for c in pd_bars)
        pools.append(LiquidityPool(kind="PDH", price=pdh, swing_indices=[]))
        pools.append(LiquidityPool(kind="PDL", price=pdl, swing_indices=[]))

    # --- Previous completed ISO week ---
    cur_monday = _utc_week_start(as_of_epoch)
    prev_monday = cur_monday - 7 * 86400
    pw_bars = [c for c in recent if prev_monday <= c["epoch"] < cur_monday]
    if pw_bars:
        pwh = max(c["high"] for c in pw_bars)
        pwl = min(c["low"] for c in pw_bars)
        pools.append(LiquidityPool(kind="weekly_high", price=pwh, swing_indices=[]))
        pools.append(LiquidityPool(kind="weekly_low", price=pwl, swing_indices=[]))

    # --- Previous session extremes (from previous completed day) ---
    if pd_bars:
        sessions = [("asia", 0, 6), ("london", 7, 16), ("ny", 12, 21)]
        for name, sh, eh in sessions:
            s_bars = [c for c in pd_bars if sh <= _utc_hour(c["epoch"]) < eh]
            if s_bars:
                s_high = max(c["high"] for c in s_bars)
                s_low = min(c["low"] for c in s_bars)
                pools.append(LiquidityPool(kind=f"{name}_high", price=s_high, swing_indices=[]))
                pools.append(LiquidityPool(kind=f"{name}_low", price=s_low, swing_indices=[]))

    return pools


def detect_sweeps(candles, pools, atr):
    sweeps: List[Sweep] = []
    for pool in pools:
        if pool.swept:
            continue
        earliest_allowed = (max(pool.swing_indices) + 3) if pool.swing_indices else 0
        for i, c in enumerate(candles):
            if i < earliest_allowed:
                continue
            if pool.kind in ("EQH", "swing_high", "PDH", "weekly_high",
                             "asia_high", "london_high", "ny_high"):
                if c["high"] > pool.price and c["close"] < pool.price:
                    sweeps.append(Sweep(i, "up", pool.price, pool.kind))
                    pool.swept = True
                    pool.swept_index = i
                    break
            elif pool.kind in ("EQL", "swing_low", "PDL", "weekly_low",
                               "asia_low", "london_low", "ny_low"):
                if c["low"] < pool.price and c["close"] > pool.price:
                    sweeps.append(Sweep(i, "down", pool.price, pool.kind))
                    pool.swept = True
                    pool.swept_index = i
                    break
    return sweeps


def detect_order_blocks(candles, bos_events, atr, displacement_mult=1.5):
    obs: List[OrderBlock] = []
    if atr is None:
        return obs

    for bos in bos_events:
        bos_idx = bos.index
        if bos_idx < 5:
            continue

        lookback_start = max(0, bos_idx - 10)
        ob_idx = None

        if bos.direction == "up":
            for j in range(bos_idx - 1, lookback_start - 1, -1):
                if candles[j]["close"] < candles[j]["open"]:
                    ob_idx = j
                    break
            if ob_idx is None or ob_idx + 1 >= len(candles):
                continue
            disp = candles[ob_idx + 1]
            if (disp["high"] - disp["low"]) < displacement_mult * atr:
                continue
            obs.append(OrderBlock(
                direction="bullish",
                index=ob_idx,
                high=candles[ob_idx]["high"],
                low=candles[ob_idx]["low"],
                bos_index=bos_idx,
            ))

        elif bos.direction == "down":
            for j in range(bos_idx - 1, lookback_start - 1, -1):
                if candles[j]["close"] > candles[j]["open"]:
                    ob_idx = j
                    break
            if ob_idx is None or ob_idx + 1 >= len(candles):
                continue
            disp = candles[ob_idx + 1]
            if (disp["high"] - disp["low"]) < displacement_mult * atr:
                continue
            obs.append(OrderBlock(
                direction="bearish",
                index=ob_idx,
                high=candles[ob_idx]["high"],
                low=candles[ob_idx]["low"],
                bos_index=bos_idx,
            ))

    return obs
