"""Orchestrator — runs on each GitHub Actions schedule tick."""

import json
import os
import time
import traceback

from .config import (
    SYMBOLS, GRANULARITY, TIMEFRAME_LABEL, CANDLE_COUNT,
    SWING_LOOKBACK, ATR_PERIOD, EQ_TOLERANCE_ATR, DISPLACEMENT_ATR_MULT,
    STATE_FILE, SIGNAL_COOLDOWN_SECONDS,
)
from .deriv_client import fetch_candles
from .smc import (
    find_swings, detect_bos_choch, find_liquidity_pools,
    detect_sweeps, detect_order_blocks, compute_atr,
)
from .patterns import detect_patterns, pattern_signature
from .telegram_client import send_signal


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}

    # Backward compat + schema upgrade
    if isinstance(data, list):
        data = {"sent": data, "last_sent": {}}
    if "sent" not in data or not isinstance(data["sent"], list):
        data["sent"] = []
    if "last_sent" not in data or not isinstance(data["last_sent"], dict):
        data["last_sent"] = {}
    return data


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def in_cooldown(state, symbol, direction):
    key = f"{symbol}|{direction}"
    last = state["last_sent"].get(key)
    if last is None:
        return False
    return (time.time() - last) < SIGNAL_COOLDOWN_SECONDS


def record_sent(state, symbol, direction, sig):
    if sig not in state["sent"]:
        state["sent"].append(sig)
    state["last_sent"][f"{symbol}|{direction}"] = int(time.time())
    # Cap growth to keep state.json small
    if len(state["sent"]) > 5000:
        state["sent"] = state["sent"][-2500:]


def process_symbol(symbol, state):
    try:
        candles = fetch_candles(symbol, GRANULARITY, CANDLE_COUNT)
    except Exception as e:
        print(f"[{symbol}] fetch failed: {e}")
        return

    if not candles or len(candles) < 50:
        print(f"[{symbol}] not enough candles")
        return

    atr = compute_atr(candles, ATR_PERIOD)
    swings = find_swings(candles, SWING_LOOKBACK)
    bos_events, choch_events, trend = detect_bos_choch(candles, swings)
    pools = find_liquidity_pools(candles, swings, atr, EQ_TOLERANCE_ATR)
    sweeps = detect_sweeps(candles, pools, atr)
    obs = detect_order_blocks(candles, bos_events, atr, DISPLACEMENT_ATR_MULT)

    patterns = detect_patterns(candles, sweeps, choch_events, bos_events, obs, pools, atr)

    print(f"[{symbol}] swings={len(swings)} bos={len(bos_events)} "
          f"choch={len(choch_events)} pools={len(pools)} "
          f"sweeps={len(sweeps)} obs={len(obs)} patterns={len(patterns)}")

    # Dedupe within this run: same direction + same entry + same target = same signal
    seen_this_run = set()
    deduped = []
    for p in patterns:
        key = (p.direction, round(p.entry, 5), round(p.target, 5))
        if key in seen_this_run:
            continue
        seen_this_run.add(key)
        deduped.append(p)

    if len(deduped) != len(patterns):
        print(f"[{symbol}] deduped within run: {len(patterns)} -> {len(deduped)}")

    for p in deduped:
        direction_label = "buy" if p.direction == "bullish" else "sell"
        sig = pattern_signature(symbol, TIMEFRAME_LABEL, p)

        if sig in state["sent"]:
            print(f"[{symbol}] skip (already sent): {sig}")
            continue

        if in_cooldown(state, symbol, direction_label):
            print(f"[{symbol}] skip (cooldown active for {direction_label})")
            continue

        try:
            send_signal(
                symbol=symbol,
                direction=direction_label,
                timeframe=TIMEFRAME_LABEL,
                entry=p.entry,
                stop=p.stop,
                target=p.target,
                rr=p.rr,
            )
            record_sent(state, symbol, direction_label, sig)
            print(f"[{symbol}] SIGNAL sent: {p.direction} entry={p.entry:.5f} "
                  f"sl={p.stop:.5f} tp={p.target:.5f} rr=1:{p.rr:.2f}")
        except Exception as e:
            print(f"[{symbol}] telegram send failed: {e}")


def main():
    state = load_state()
    for symbol in SYMBOLS:
        try:
            process_symbol(symbol, state)
        except Exception:
            print(f"[{symbol}] unhandled error:\n{traceback.format_exc()}")
    save_state(state)


if __name__ == "__main__":
    main()
