"""Deriv WebSocket client — fetches OHLC candles with retry + pagination."""

import asyncio
import json
import random
import websockets

from .config import DERIV_WS_URL


MAX_RETRIES = 3
BASE_DELAY = 2.0  # seconds


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
    """Synchronous wrapper with retries. Returns list of candle dicts."""
    return asyncio.run(_fetch_with_retry(symbol, granularity, count))


# ---------- Paginated fetch (for backtesting) ----------

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
    all_candles = []
    seen_epochs = set()
    end = "latest"
    max_iters = 30
    iters = 0
    batch_size = 900  # safely under Deriv's per-request soft cap

    while len(all_candles) < total and iters < max_iters:
        iters += 1
        try:
            batch = await _fetch_batch(symbol, granularity, batch_size, end)
        except Exception as e:
            print(f"[{symbol}] pagination batch {iters} failed: {e}")
            break

        print(f"[{symbol}] batch {iters}: {len(batch)} candles (have {len(all_candles)}/{total})")

        if not batch:
            break

        new = [c for c in batch if c["epoch"] not in seen_epochs]
        if not new:
            print(f"[{symbol}] no new candles — stopping pagination")
            break

        for c in new:
            seen_epochs.add(c["epoch"])

        all_candles = new + all_candles
        end = new[0]["epoch"] - granularity

    if len(all_candles) > total:
        all_candles = all_candles[-total:]

    print(f"[{symbol}] pagination complete: {len(all_candles)} candles")
    return all_candles


def fetch_candles_paginated(symbol, granularity, total):
    """Fetch up to `total` candles by paginating backward. For backtests."""
    return asyncio.run(_paginate(symbol, granularity, total))
