"""Persistent state across live bot runs — dedup, cooldown, open trades."""

import json
import os
import time

from .config import STATE_FILE, SIGNAL_COOLDOWN_SECONDS, TRADES_FILE


# ---------------- state.json (bot runtime state) ----------------

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    else:
        data = {}

    if "sent" not in data or not isinstance(data["sent"], list):
        data["sent"] = []
    if "last_sent" not in data or not isinstance(data["last_sent"], dict):
        data["last_sent"] = {}
    if "pending_trades" not in data or not isinstance(data["pending_trades"], list):
        data["pending_trades"] = []
    return data


def save_state(state):
    if len(state["sent"]) > 2000:
        state["sent"] = state["sent"][-1000:]
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def already_sent(state, signature):
    return signature in state["sent"]


def in_cooldown(state, symbol, direction, now=None):
    if now is None:
        now = int(time.time())
    key = f"{symbol}|{direction}"
    last = state["last_sent"].get(key, 0)
    return (now - last) < SIGNAL_COOLDOWN_SECONDS


def record_sent(state, symbol, direction, signature, now=None):
    if now is None:
        now = int(time.time())
    if signature not in state["sent"]:
        state["sent"].append(signature)
    state["last_sent"][f"{symbol}|{direction}"] = now


# ---------------- pending trades ----------------

def add_pending_trade(state, symbol, direction, entry, stop, target, rr,
                       target_kind, sent_epoch):
    trade_id = f"{symbol}|{direction}|{int(sent_epoch)}|{round(entry, 5)}"
    trade = {
        "id": trade_id,
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "rr": rr,
        "target_kind": target_kind,
        "sent_epoch": int(sent_epoch),
    }
    state["pending_trades"].append(trade)
    return trade


def get_pending_trades(state):
    return state.get("pending_trades", [])


def remove_pending_trade(state, trade_id):
    state["pending_trades"] = [
        t for t in state.get("pending_trades", []) if t["id"] != trade_id
    ]


# ---------------- trades.json (permanent record) ----------------

def load_trades_file():
    if os.path.exists(TRADES_FILE):
        try:
            with open(TRADES_FILE, "r") as f:
                data = json.load(f)
        except Exception:
            data = {"trades": []}
    else:
        data = {"trades": []}
    if "trades" not in data or not isinstance(data["trades"], list):
        data["trades"] = []
    return data


def save_trades_file(trades_data):
    with open(TRADES_FILE, "w") as f:
        json.dump(trades_data, f, indent=2)


def append_closed_trade(closed_trade):
    data = load_trades_file()
    data["trades"].append(closed_trade)
    save_trades_file(data)
