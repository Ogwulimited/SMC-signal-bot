"""Formats and sends signals to a Telegram channel."""

import os
import requests


def _pretty_symbol(deriv_symbol: str) -> str:
    if deriv_symbol.startswith("frx") or deriv_symbol.startswith("cry"):
        return deriv_symbol[3:].upper()
    return deriv_symbol.upper()


def _format_signal(symbol_display, direction, timeframe, entry, stop, target, rr):
    arrow = "🟢" if direction.lower() == "buy" else "🔴"
    return (
        f"🔔 NEW FOREX SIGNAL\n\n"
        f"{arrow} Pair: {symbol_display}\n"
        f"Direction: {direction.upper()}\n"
        f"Timeframe: {timeframe}\n"
        f"Entry: {entry:.5f}\n"
        f"Stop Loss: {stop:.5f}\n"
        f"Take Profit: {target:.5f}\n"
        f"Risk/Reward: 1:{rr:.1f}\n\n"
        f"#Forex #{symbol_display} #{direction.upper()}"
    )


def send_signal(symbol, direction, timeframe, entry, stop, target, rr):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    text = _format_signal(_pretty_symbol(symbol), direction, timeframe,
                          entry, stop, target, rr)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()
