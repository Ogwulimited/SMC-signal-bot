"""Formats and sends continuation signals to a Telegram channel."""

import os
import requests


TARGET_KIND_LABELS = {
    "PDH": "Prev Day High",
    "PDL": "Prev Day Low",
    "weekly_high": "Weekly High",
    "weekly_low": "Weekly Low",
    "asia_high": "Asia High",
    "asia_low": "Asia Low",
    "london_high": "London High",
    "london_low": "London Low",
    "ny_high": "NY High",
    "ny_low": "NY Low",
    "EQH": "Equal Highs",
    "EQL": "Equal Lows",
    "swing_high": "Swing High",
    "swing_low": "Swing Low",
    "synthetic": "Synthetic Target",
}


def _pretty_symbol(deriv_symbol):
    if deriv_symbol.startswith("frx") or deriv_symbol.startswith("cry"):
        return deriv_symbol[3:].upper()
    return deriv_symbol.upper()


def _pretty_target_kind(kind):
    return TARGET_KIND_LABELS.get(kind, kind)


def _asset_tag(symbol_display):
    if symbol_display in ("BTCUSD", "ETHUSD"):
        return "Crypto"
    if symbol_display in ("XAUUSD", "XAGUSD"):
        return "Metals"
    return "Forex"


def _format_signal(symbol_display, direction, entry, stop, target, rr,
                   target_kind, bias):
    arrow = "🟢" if direction == "bullish" else "🔴"
    dir_label = "BUY" if direction == "bullish" else "SELL"
    bias_label = "Bullish" if bias == "bullish" else "Bearish"
    asset = _asset_tag(symbol_display)

    return (
        f"🔔 NEW SIGNAL\n\n"
        f"{arrow} Pair: {symbol_display}\n"
        f"Direction: {dir_label}\n"
        f"Timeframe: H1\n"
        f"Bias (D1): {bias_label}\n\n"
        f"Entry: {entry:.5f}\n"
        f"Stop Loss: {stop:.5f}\n"
        f"Take Profit: {target:.5f}\n"
        f"R:R 1:{rr:.2f}\n"
        f"Target: {_pretty_target_kind(target_kind)}\n\n"
        f"#{asset} #{symbol_display} #{dir_label} #SMC"
    )


def send_signal(symbol, direction, entry, stop, target, rr, target_kind, bias):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")

    text = _format_signal(
        _pretty_symbol(symbol), direction, entry, stop, target, rr,
        target_kind, bias,
    )
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }, timeout=15)
    resp.raise_for_status()
    return resp.json()
