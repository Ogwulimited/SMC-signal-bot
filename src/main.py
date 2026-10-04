"""Live orchestrator — runs hourly on the GitHub Actions schedule.

Fetches H1 + D1 for each recommended pair, runs the continuation detector,
sends signals to Telegram when a fresh OB touch fires on the last completed
H1 candle, and records each sent signal as a pending trade for the monitor.
"""

import time
import traceback

from .config import (
    RECOMMENDED_PAIRS, GRANULARITY, HTF_GRANULARITY,
    CANDLE_COUNT, HTF_CANDLE_COUNT,
)
from .deriv_client import fetch_candles
from .continuation import detect_continuation_signals
from .telegram_client import send_signal
from .state_store import (
    load_state, save_state, already_sent, in_cooldown, record_sent,
    add_pending_trade,
)


def _drop_in_progress(candles, granularity, now):
    return [c for c in candles if c["epoch"] + granularity <= now]


def main():
    now = int(time.time())
    state = load_state()
    total_sent = 0
    total_checked = 0

    for symbol in RECOMMENDED_PAIRS:
        try:
            h1 = fetch_candles(symbol, GRANULARITY, CANDLE_COUNT + 20)
            d1 = fetch_candles(symbol, HTF_GRANULARITY, HTF_CANDLE_COUNT)
        except Exception as e:
            print(f"[{symbol}] fetch failed: {e}")
            continue

        # Use only fully-closed candles
        h1 = _drop_in_progress(h1, GRANULARITY, now)
        d1 = _drop_in_progress(d1, HTF_GRANULARITY, now)

        if len(h1) < 60 or len(d1) < 20:
            print(f"[{symbol}] insufficient bars (h1={len(h1)}, d1={len(d1)})")
            continue

        try:
            pats = detect_continuation_signals(h1, d1)
        except Exception:
            print(f"[{symbol}] detect failed:\n{traceback.format_exc()}")
            continue

        last_idx = len(h1) - 1
        fresh_touches = [p for p in pats if p.touch_index == last_idx]
        total_checked += len(fresh_touches)

        for p in fresh_touches:
            direction_label = "bullish" if p.direction == "bullish" else "bearish"
            sig = f"{symbol}|{direction_label}|{round(p.entry, 5)}"

            if already_sent(state, sig):
                print(f"[{symbol}] skip (already sent): {sig}")
                continue
            if in_cooldown(state, symbol, direction_label, now):
                print(f"[{symbol}] skip (cooldown active for {direction_label})")
                continue

            try:
                send_signal(
                    symbol=symbol,
                    direction=p.direction,
                    entry=p.entry,
                    stop=p.stop,
                    target=p.target,
                    rr=p.rr,
                    target_kind=p.target_kind,
                    bias=p.direction,
                )
                record_sent(state, symbol, direction_label, sig, now)
                add_pending_trade(
                    state=state,
                    symbol=symbol,
                    direction=p.direction,
                    entry=p.entry,
                    stop=p.stop,
                    target=p.target,
                    rr=p.rr,
                    target_kind=p.target_kind,
                    sent_epoch=now,
                )
                total_sent += 1
                print(
                    f"[{symbol}] SENT {p.direction} "
                    f"entry={p.entry:.5f} sl={p.stop:.5f} "
                    f"tp={p.target:.5f} rr=1:{p.rr:.2f} "
                    f"target_kind={p.target_kind}"
                )
            except Exception as e:
                print(f"[{symbol}] telegram send failed: {e}")

        if len(pats) > 0:
            print(f"[{symbol}] checked: {len(pats)} patterns, "
                  f"{len(fresh_touches)} fresh touches")

    save_state(state)
    print(f"\nRun complete — {total_sent} signals sent, "
          f"{total_checked} fresh touches evaluated across "
          f"{len(RECOMMENDED_PAIRS)} symbols.")


if __name__ == "__main__":
    main()
