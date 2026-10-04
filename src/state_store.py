"""Persistent state across live bot runs — dedup and cooldown."""

import json
import os
import time

from .config import STATE_FILE, SIGNAL_COOLDOWN_SECONDS


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
