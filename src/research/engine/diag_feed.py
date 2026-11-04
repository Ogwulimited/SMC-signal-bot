"""Diagnostic only. Changes nothing.
Finds where the feed's 'bin end = start + 24h' assumption breaks on real data."""
import os

import numpy as np
import pandas as pd

from src.research.lookahead_guard import TF_MINUTES, _bin_starts, _ns_utc, _NS_PER_MIN

NY = "America/New_York"
PAIR = os.environ.get("PAIR", "eurusd")
CUTOFF = pd.Timestamp("2022-07-01", tz="UTC")
OUT = []


def say(s=""):
    print(s)
    OUT.append(s)


def fmt(ns):
    t = pd.Timestamp(int(ns), unit="ns", tz="UTC")
    return f"{t.strftime('%Y-%m-%d %a %H:%M')} UTC | {t.tz_convert(NY).strftime('%a %H:%M %Z')}"


def load():
    df = pd.read_parquet(f"data/processed/{PAIR}_m15.parquet")
    if "timestamp" not in df.columns:
        df = df.reset_index()
    ts = pd.to_datetime(df["timestamp"])
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    else:
        ts = ts.dt.tz_convert("UTC")
    idx = pd.DatetimeIndex(ts).sort_values().unique()
    idx = idx[idx + pd.Timedelta(minutes=15) <= CUTOFF]
    return idx.as_unit("ns")


def main():
    idx = load()
    n = len(idx)
    open_ns = _ns_utc(idx)
    say(f"## Feed bin diagnostic - {PAIR}")
    say(f"bars: {n}  first {idx[0]}  last {idx[-1]}")
    say("")

    for name in ("D1", "H4", "H1"):
        minutes = TF_MINUTES[name]
        starts, valid = _bin_starts(idx, minutes)
        acc = None
        hits = []
        n_invalid = int((~valid).sum())
        for i in range(n):
            close_ns = int(open_ns[i]) + 15 * _NS_PER_MIN
            start = int(starts[i]) if valid[i] else -1
            if acc is not None and acc != start:
                if acc + minutes * _NS_PER_MIN > close_ns:
                    hits.append((i, acc, start))
                acc = None
            if start != -1:
                if acc is None:
                    acc = start
                if close_ns >= start + minutes * _NS_PER_MIN:
                    acc = None
        say(f"### {name}: breaks = {len(hits)}   bars in invalid bins = {n_invalid}")
        years = {}
        for i, a, s in hits:
            y = pd.Timestamp(int(open_ns[i]), unit="ns", tz="UTC").year
            years[y] = years.get(y, 0) + 1
        say(f"breaks per year: {years}")
        for i, a, s in hits[:12]:
            say(f"- bin start      : {fmt(a)}")
            say(f"  previous bar   : {fmt(open_ns[i - 1])}")
            say(f"  current bar    : {fmt(open_ns[i])}")
            say(f"  new bin start  : {'INVALID (DST hour)' if s == -1 else fmt(s)}")
        say("")

    # weekend window check, New York clock
    loc = idx.tz_convert(NY)
    dow = np.asarray(loc.day_of_week)
    hr = np.asarray(loc.hour)
    sat = dow == 5
    sun_early = (dow == 6) & (hr < 17)
    fri_late = (dow == 4) & (hr >= 17)
    say("### Weekend window (New York clock)")
    say(f"bars on Saturday: {int(sat.sum())}")
    say(f"bars on Sunday before 17:00: {int(sun_early.sum())}")
    say(f"bars on Friday at or after 17:00: {int(fri_late.sum())}")
    bad = np.where(sat | sun_early)[0]
    for i in bad[:10]:
        say(f"- {fmt(open_ns[i])}")
    say("")

    # how does the market open after a weekend gap?
    gaps = np.diff(open_ns) > 24 * 60 * _NS_PER_MIN
    opens = np.where(gaps)[0] + 1
    rows = {}
    for i in opens:
        t = pd.Timestamp(int(open_ns[i]), unit="ns", tz="UTC")
        off = t.tz_convert(NY).strftime("%Z")
        key = (off, t.strftime("%H:%M UTC"), t.tz_convert(NY).strftime("%a %H:%M"))
        rows[key] = rows.get(key, 0) + 1
    say("### First bar after a gap over 24h: (NY zone, UTC time, NY time) -> count")
    for k, v in sorted(rows.items(), key=lambda kv: -kv[1])[:12]:
        say(f"- {k}: {v}")
    say("")

    # last bar before each gap
    closes = np.where(gaps)[0]
    rows = {}
    for i in closes:
        t = pd.Timestamp(int(open_ns[i]), unit="ns", tz="UTC")
        off = t.tz_convert(NY).strftime("%Z")
        key = (off, t.strftime("%H:%M UTC"), t.tz_convert(NY).strftime("%a %H:%M"))
        rows[key] = rows.get(key, 0) + 1
    say("### Last bar before a gap over 24h: (NY zone, UTC time, NY time) -> count")
    for k, v in sorted(rows.items(), key=lambda kv: -kv[1])[:12]:
        say(f"- {k}: {v}")

    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(OUT) + "\n")


if __name__ == "__main__":
    main()
