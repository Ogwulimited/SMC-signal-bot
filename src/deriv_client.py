"""Deriv WebSocket client — fetches OHLC candles."""

import asyncio
import json
import websockets

from .config import DERIV_WS_URL


async def _fetch(symbol, granularity, count):
    async with websockets.connect(DERIV_WS_URL, open_timeout=15) as ws:
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
            raw = await asyncio.wait_for(ws.recv(), timeout=20)
            data = json.loads(raw)

            if "error" in data:
                msg = data["error"].get("message", "unknown error")
                raise RuntimeError(f"Deriv error for {symbol}: {msg}")

            if data.get("msg_type") == "candles" and "candles" in data:
                return data["candles"]


def fetch_candles(symbol, granularity, count):
    """Synchronous wrapper. Returns list of dicts with epoch/open/high/low/close."""
    return asyncio.run(_fetch(symbol, granularity, count))
