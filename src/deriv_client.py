"""Deriv WebSocket client — fetches OHLC candles with retry + robust pagination."""

import asyncio
import json
import random
import websockets

from .config import DERIV_WS_URL


MAX_RETRIES = 3
BASE_DELAY = 2.0
BATCH_SIZE = 900


async def _fetch_once(symbol, granularity, count):
    async with websockets.connect(DERIV_WS_URL, open_timeout=20) as ws:
        request = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": "latest",
            "granularity": granularity,
            "style": "candles",
        }
        await ws.send(json.dumps(request))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=25)
            data = json.loads(raw)
            if "error" in data:
                msg = data["error"].get("message", "unknown error")
                raise RuntimeError(f"Deriv error for {symbol}: {msg}")
            if data.get("msg_type") == "candles" and "candles" in data:
                return data["candles"]


async def _fetch_with_retry(symbol, granularity, count):
    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await _fetch_once(symbol, granularity, count)
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES:
                delay = BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)
                print(f"[{symbol}] attempt {attempt} failed ({e}), retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
    raise RuntimeError(f"All {MAX_RETRIES} attempts failed for {symbol}: {last_error}")


def fetch_candles(symbol, granularity, count):
    """Synchronous wrapper with retries."""
    return asyncio.run(_fetch_with_retry(symbol, granularity, count))


# ---------- Robust pagination ----------

async def _fetch_batch(symbol, granularity, count, end):
    async with websockets.connect(DERIV_WS_URL, open_timeout=20) as ws:
        request = {
            "ticks_history": symbol,
            "adjust_start_time": 1,
            "count": count,
            "end": end,
            "granularity": granularity,
            "style": "candles",
        }
        await ws.send(json.dumps(request))
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=25)
            data = json.loads(raw)
            if "error" in data:
                msg = data["error"].get("message", "unknown error")
                raise RuntimeError(f"Deriv error for {symbol}: {msg}")
            if data.get("msg_type") == "candles" and "candles" in data:
                return data["candles"]


async def _paginate(symbol, granularity, total):
    """Paginate backward. Guarantees progress by filtering to strictly older candles."""
    all_candles = []
    seen_epochs = set()
    end = "latest"
    max_iters = 200
    stale_iters = 0

    for it in range(max_iters):
        try:
            batch = await _fetch_batch(symbol, granularity, BATCH_SIZE, end)
        except Exception as e:
            print(f"[{symbol}] batch {it+1} failed: {e}")
            break

        if not batch:
            print(f"[{symbol}] batch {it+1}: empty, stopping")
            break

        # Keep only candles strictly older than what we already have.
        # This guarantees forward progress regardless of how Deriv interprets `end`.
        if seen_epochs:
            oldest_seen = min(seen_epochs)
            batch = [c for c in batch if c["epoch"] < oldest_seen]

        if not batch:
            print(f"[{symbol}] batch {it+1}: no new candles, stopping (have {len(all_candles)})")
            break

        for c in batch:
            seen_epochs.add(c["epoch"])

        all_candles = batch + all_candles
        oldest = batch[0]["epoch"]
        end = oldest - granularity

        print(f"[{symbol}] batch {it+1}: +{len(batch)} (have {len(all_candles)}/{total})")

        if len(all_candles) >= total:
            break

        # Detect stalls
        if len(batch) < 10:
            stale_iters += 1
            if stale_iters >= 3:
                print(f"[{symbol}] detected stall, stopping (have {len(all_candles)})")
                break
        else:
            stale_iters = 0

    if len(all_candles) > total:
        all_candles = all_candles[-total:]

    print(f"[{symbol}] pagination complete: {len(all_candles)} candles")
    return all_candles


def fetch_candles_paginated(symbol, granularity, total):
    """Fetch up to `total` candles by paginating backward. For backtests."""
    return asyncio.run(_paginate(symbol, granularity, total))
