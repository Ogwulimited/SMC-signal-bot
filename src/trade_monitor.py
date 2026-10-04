"""Checks pending trades against recent candles.

Runs every 15 min. For each open trade:
  - Fetch recent M15 candles for the symbol
  - Walk forward from sent_epoch
  - Detect first touch of SL or TP
  - Send Telegram outcome and log to trades.json
  - Remove from pending_trades

Timeouts close at MAX_TRADE_DURATION_SECONDS with 0R.
"""

import time
import traceback

from .config import (
    MONITOR_GRANULARITY, MAX_TRADE_DURATION_SECONDS, MONITOR_CANDLE_COUNT,
)
from .deriv_client import fetch_candles
from .telegram_client import send_trade_outcome
from .state_store import (
    load_state, save_state,
    get_pending_trades, remove_pending_trade,
    append_closed_trade,
)


def _walk_outcome(candles, start_epoch, direction, stop, target):
    """Return (outcome, exit_price, exit_epoch, extreme) or None if unresolved.

    outcome in {"win", "loss"}
    extreme: best favorable / worst adverse price in the window (for messaging)
    """
    best_high = None
    best_low = None

    for c in candles:
        if c["epoch"] < start_epoch:
            continue
        if best_high is None or c["high"] > best_high:
            best_high = c["high"]
        if best_low is None or c["low"] < best_low:
            best_low = c["low"]

        # Same-candle conflict: check SL first (conservative)
        if direction == "bullish":
            if c["low"] <= stop:
                return "loss", stop, c["epoch"], best_low
            if c["high"] >= target:
                return "win", target, c["epoch"], best_high
        else:
            if c["high"] >= stop:
                return "loss", stop, c["epoch"], best_high
            if c["low"] <= target:
                return "win", target, c["epoch"], best_low

    return None


def _process_trade(trade, now):
    symbol = trade["symbol"]
    direction = trade["direction"]
    entry = trade["entry"]
    stop = trade["stop"]
    target = trade["target"]
    rr = trade["rr"]
    sent_epoch = trade["sent_epoch"]

    try:
        candles = fetch_candles(symbol, MONITOR_GRANULARITY, MONITOR_CANDLE_COUNT)
    except Exception as e:
        print(f"[{symbol}] fetch failed: {e}")
        return None

    if not candles:
        return None

    # Only closed candles
    candles = [c for c in candles if c["epoch"] + MONITOR_GRANULARITY <= now]

    result = _walk_outcome(candles, sent_epoch, direction, stop, target)

    if result is None:
        elapsed = now - sent_epoch
        if elapsed >= MAX_TRADE_DURATION_SECONDS:
            # Timeout
            last_close = candles[-1]["close"] if candles else entry
            return {
                "outcome": "timeout",
                "exit_price": last_close,
                "exit_epoch": now,
                "extreme": None,
                "note": f"{int(MAX_TRADE_DURATION_SECONDS/3600)}h horizon",
            }
        return None  # still open

    outcome, exit_price, exit_epoch, extreme = result

    if outcome == "win":
        note = f"TP reached (extreme {extreme:.5f})" if extreme else "TP reached"
        rr_actual = rr
    else:
        note = f"SL hit (extreme {extreme:.5f})" if extreme else "SL hit"
        rr_actual = -1.0

    return {
        "outcome": outcome,
        "exit_price": exit_price,
        "exit_epoch": exit_epoch,
        "extreme": extreme,
        "note": note,
        "rr_actual": rr_actual,
    }


def main():
    now = int(time.time())
    state = load_state()
    pending = get_pending_trades(state)

    print(f"Trade monitor — {len(pending)} open trades")

    if not pending:
        return

    closed_count = 0

    for trade in list(pending):
        try:
            result = _process_trade(trade, now)
        except Exception:
            print(f"[{trade['symbol']}] monitor error:\n{traceback.format_exc()}")
            continue

        if result is None:
            continue

        outcome = result["outcome"]
        exit_price = result["exit_price"]
        exit_epoch = result["exit_epoch"]
        rr_actual = result.get("rr_actual",
                               (trade["rr"] if outcome == "win"
                                else (-1.0 if outcome == "loss" else 0.0)))
        duration = exit_epoch - trade["sent_epoch"]
        note = result.get("note", "")

        closed_trade = {
            "id": trade["id"],
            "symbol": trade["symbol"],
            "direction": trade["direction"],
            "entry": trade["entry"],
            "stop": trade["stop"],
            "target": trade["target"],
            "rr_planned": trade["rr"],
            "target_kind": trade.get("target_kind", "unknown"),
            "sent_epoch": trade["sent_epoch"],
            "exit_epoch": exit_epoch,
            "exit_price": exit_price,
            "outcome": outcome,
            "rr_actual": rr_actual,
            "duration_seconds": duration,
            "note": note,
        }

        try:
            send_trade_outcome(
                symbol=trade["symbol"],
                direction=trade["direction"],
                outcome=outcome,
                exit_price=exit_price,
                rr_actual=rr_actual,
                duration_seconds=duration,
                note=note,
            )
        except Exception as e:
            print(f"[{trade['symbol']}] telegram outcome send failed: {e}")

        append_closed_trade(closed_trade)
        remove_pending_trade(state, trade["id"])
        closed_count += 1

        print(f"[{trade['symbol']}] {outcome.upper()} "
              f"exit={exit_price:.5f} rr={rr_actual:+.2f} "
              f"duration={int(duration)}s")

    save_state(state)
    print(f"\nMonitor complete — {closed_count} trades closed, "
          f"{len(get_pending_trades(state))} still open.")


if __name__ == "__main__":
    main()
