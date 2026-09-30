"""SMC structural primitives: swings, BOS/CHoCH, liquidity, sweeps, order blocks."""

from dataclasses import dataclass
from typing import List, Optional


# ---------- Data objects ----------

@dataclass
class Swing:
    index: int
    price: float
    kind: str  # "high" or "low"


@dataclass
class BOS:
    index: int
    direction: str  # "up" or "down"
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
    kind: str              # "EQH" | "EQL" | "swing_high" | "swing_low"
    price: float
    swing_indices: List[int]
    swept: bool = False
    swept_index: Optional[int] = None


@dataclass
class Sweep:
    index: int
    direction: str         # "up" (swept a high) | "down" (swept a low)
    pool_price: float
    pool_kind: str


@dataclass
class OrderBlock:
    direction: str         # "bullish" | "bearish"
    index: int             # bar index of the OB candle
    high: float
    low: float
    bos_index: int
    mitigated: bool = False


# ---------- ATR ----------

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


# ---------- Swings ----------

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


# ---------- BOS / CHoCH ----------

def detect_bos_choch(candles, swings):
    """State machine: the latest unconsumed swing high/low is the active reference.

    A close above the active high reference:
      - if already in an uptrend -> BOS up
      - otherwise -> CHoCH up (trend flips to up)
    Symmetric for the low reference.

    On trend flip, stale unconsumed references on the opposite side are discarded.
    """
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


# ---------- Liquidity pools ----------

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


# ---------- Sweeps ----------

def detect_sweeps(candles, pools, atr):
    sweeps: List[Sweep] = []
    for pool in pools:
        if pool.swept:
            continue
        earliest_allowed = (max(pool.swing_indices) + 3) if pool.swing_indices else 0
        for i, c in enumerate(candles):
            if i < earliest_allowed:
                continue
            if pool.kind in ("EQH", "swing_high"):
                if c["high"] > pool.price and c["close"] < pool.price:
                    sweeps.append(Sweep(i, "up", pool.price, pool.kind))
                    pool.swept = True
                    pool.swept_index = i
                    break
            elif pool.kind in ("EQL", "swing_low"):
                if c["low"] < pool.price and c["close"] > pool.price:
                    sweeps.append(Sweep(i, "down", pool.price, pool.kind))
                    pool.swept = True
                    pool.swept_index = i
                    break
    return sweeps


# ---------- Order blocks ----------

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
