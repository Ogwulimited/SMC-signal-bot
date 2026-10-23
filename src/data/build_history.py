"""Build M15/H1/H4/D1 from raw histdata.com 1-minute CSVs.

Raw format: YYYYMMDD HHMMSS;open;high;low;close;volume
Timestamps are fixed UTC-5 (EST, no DST). Add 5 hours for UTC.

Anchors are in America/New_York:
  D1 opens 17:00 NY
  H4 opens 17, 21, 01, 05, 09, 13 NY
  Week opens Sunday 17:00 NY
"""

import os
import glob
import json
import math
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
REPORT_DIR = Path(__file__).parent.parent.parent / "reports" / "data"

PAIRS = [
    "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf",
    "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy"
]

# Timeframes in minutes
TF_MINUTES = {"M15": 15, "H1": 60, "H4": 240, "D1": 1440}


def load_m1(pair):
    """Load all raw 1-minute CSVs for a pair."""
    pattern = str(RAW_DIR / pair / "*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No raw data for {pair}")

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(
                f, sep=";", header=None,
                names=["timestamp", "open", "high", "low", "close", "volume"]
            )
            dfs.append(df)
        except Exception as e:
            print(f"[WARN] Failed to read {f}: {e}")

    if not dfs:
        raise ValueError(f"All files failed for {pair}")

    df = pd.concat(dfs, ignore_index=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y%m%d %H%M%S")
    df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=5)
    df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    return df


def clean_m1(df):
    """Validate and clean M1 data. Returns (df, report_dict)."""
    report = {"duplicates_removed": 0, "flagged_jumps": 0, "bad_hl": 0, "bad_ohlc": 0}

    before = len(df)
    df = df.drop_duplicates(subset=["timestamp"], keep="first")
    report["duplicates_removed"] = before - len(df)

    df = df.sort_values("timestamp").reset_index(drop=True)

    bad_hl = df[df["high"] < df["low"]]
    report["bad_hl"] = len(bad_hl)
    df = df.drop(bad_hl.index)

    bad_ohlc = df[
        (df["high"] < df["open"]) | (df["high"] < df["close"]) |
        (df["low"] > df["open"]) | (df["low"] > df["close"])
    ]
    report["bad_ohlc"] = len(bad_ohlc)
    df = df.drop(bad_ohlc.index)

    # Flag 1-minute price jumps > 3%
    df = df.sort_values("timestamp").reset_index(drop=True)
    pct_change = df["close"].pct_change().abs()
    flagged = df[pct_change > 0.03]
    report["flagged_jumps"] = len(flagged)
    report["flagged_indices"] = flagged["timestamp"].tolist()

    return df, report


def resample_m15(df):
    """Resample M1 to M15 using UTC 15-minute bins. No forward fill."""
    df = df.set_index("timestamp")
    m15 = df.resample("15min", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        n_m1=("open", "count"),
    ).dropna(subset=["open"]).reset_index()
    m15["thin"] = m15["n_m1"] < 10
    m15["open_time"] = m15["timestamp"]
    m15["close_time"] = m15["open_time"] + pd.Timedelta(minutes=15)
    return m15


def _ny_resample(m15, rule, offset_hours=0):
    """Resample M15 in America/New_York time.

    If offset_hours is given, shift the index forward by that amount so
    the anchor aligns with a multiple of the rule, resample, then shift back.
    """
    ny = m15.set_index("timestamp").tz_convert("America/New_York")
    if offset_hours:
        ny.index = ny.index + pd.Timedelta(hours=offset_hours)

    agg = {
        "open": ("open", "first"),
        "high": ("high", "max"),
        "low": ("low", "min"),
        "close": ("close", "last"),
        "volume": ("volume", "sum"),
        "n_m1": ("n_m1", "sum"),
    }
    resampled = ny.resample(rule, label="left", closed="left").agg(**agg).dropna(subset=["open"])

    if offset_hours:
        resampled.index = resampled.index - pd.Timedelta(hours=offset_hours)

    resampled = resampled.reset_index()
    resampled = resampled.rename(columns={"index": "timestamp"})
    resampled["thin"] = resampled["n_m1"] < 10
    return resampled


def build_h1(m15):
    """Resample M15 to H1 in NY time (aligned with 17:00 NY anchor)."""
    h1 = _ny_resample(m15, "1h", offset_hours=0)
    h1["open_time"] = h1["timestamp"]
    h1["close_time"] = h1["open_time"] + pd.Timedelta(hours=1)
    return h1


def build_h4(m15):
    """Resample M15 to H4 with anchors at 17, 21, 01, 05, 09, 13 NY."""
    h4 = _ny_resample(m15, "4h", offset_hours=7)
    h4["open_time"] = h4["timestamp"]
    h4["close_time"] = h4["open_time"] + pd.Timedelta(hours=4)
    return h4


def build_d1(m15):
    """Resample M15 to D1 with open at 17:00 NY."""
    ny = m15.set_index("timestamp").tz_convert("America/New_York")
    shifted = ny.copy()
    shifted.index = shifted.index + pd.Timedelta(hours=7)

    d1 = shifted.groupby(shifted.index.date).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        n_m1=("n_m1", "sum"),
    ).reset_index()
    d1.columns = ["trade_date", "open", "high", "low", "close", "volume", "n_m1"]

    d1["open_time"] = pd.to_datetime(d1["trade_date"]).dt.tz_localize("America/New_York") - pd.Timedelta(hours=7)
    d1["open_time"] = d1["open_time"].dt.tz_convert("UTC")
    d1["close_time"] = d1["open_time"] + pd.Timedelta(days=1)
    d1["thin"] = d1["n_m1"] < 10
    d1 = d1.drop(columns=["trade_date"])
    return d1


def build_weekly(d1):
    """Build weekly bars opening Sunday 17:00 NY."""
    d1 = d1.set_index("open_time")
    ny = d1.tz_convert("America/New_York")
    shifted = ny.copy()
    shifted.index = shifted.index + pd.Timedelta(hours=7)

    # Week starts on Monday in the shifted index
    weekly = shifted.resample("W-MON", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        n_m1=("n_m1", "sum"),
    ).dropna(subset=["open"])

    weekly.index = weekly.index - pd.Timedelta(hours=7)
    weekly = weekly.reset_index().rename(columns={"index": "open_time"})
    weekly["close_time"] = weekly["open_time"] + pd.Timedelta(days=7)
    return weekly


def build_monthly(d1):
    """Build monthly bars using NY calendar month."""
    d1 = d1.set_index("open_time")
    ny = d1.tz_convert("America/New_York")
    shifted = ny.copy()
    shifted.index = shifted.index + pd.Timedelta(hours=7)

    monthly = shifted.resample("MS", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        n_m1=("n_m1", "sum"),
    ).dropna(subset=["open"])

    monthly.index = monthly.index - pd.Timedelta(hours=7)
    monthly = monthly.reset_index().rename(columns={"index": "open_time"})
    monthly["close_time"] = monthly["open_time"] + pd.offsets.MonthEnd(1)
    return monthly


def save_m15(pair, m15):
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    out = PROCESSED_DIR / f"{pair}_m15.parquet"
    m15.to_parquet(out, index=False)
    return out


def load_m15(pair):
    path = PROCESSED_DIR / f"{pair}_m15.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run build first.")
    return pd.read_parquet(path)


def get_h1(pair):
    return build_h1(load_m15(pair))


def get_h4(pair):
    return build_h4(load_m15(pair))


def get_d1(pair):
    return build_d1(load_m15(pair))


def get_weekly(pair):
    return build_weekly(get_d1(pair))


def get_monthly(pair):
    return build_monthly(get_d1(pair))


def prior_day_high_low(pair, t):
    d1 = get_d1(pair)
    t_ny = t.tz_convert("America/New_York")
    day = d1[d1["open_time"] <= t].iloc[-1]
    prev = d1[d1["open_time"] < day["open_time"]].iloc[-1]
    return prev["high"], prev["low"]


def prior_week_high_low(pair, t):
    wk = get_weekly(pair)
    week = wk[wk["open_time"] <= t].iloc[-1]
    prev = wk[wk["open_time"] < week["open_time"]].iloc[-1]
    return prev["high"], prev["low"]


def prior_month_high_low(pair, t):
    mo = get_monthly(pair)
    month = mo[mo["open_time"] <= t].iloc[-1]
    prev = mo[mo["open_time"] < month["open_time"]].iloc[-1]
    return prev["high"], prev["low"]


def bars_available_at(df, t):
    """Return rows where close_time <= t (no lookahead)."""
    return df[df["close_time"] <= t].copy()


def generate_report(pair_reports, out_path):
    lines = [
        "# HistData Validation Report",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        f"- Pairs processed: {len(pair_reports)}",
        f"- Data is **bid-only** (histdata.com Generic ASCII 1-minute bid bars).",
        "",
        "## Per-Pair Results",
        "| Pair | First Date | Last Date | M15 Bars | Missing Weeks | Largest Gap (h) | Thin % | Flagged Jumps | Dupes Removed |",
        "|------|-----------|-----------|----------|---------------|-----------------|--------|---------------|---------------|"
    ]
    for r in pair_reports:
        lines.append(
            f"| {r['pair']} | {r['first'][:10]} | {r['last'][:10]} | {r['m15_bars']} | "
            f"{r['missing_weeks']} | {r['largest_gap_h']:.1f} | {r['thin_pct']:.1f}% | "
            f"{r['flagged_jumps']} | {r['duplicates_removed']} |"
        )
    out_path.write_text("\n".join(lines))


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    pair_reports = []
    for pair in PAIRS:
        print(f"\n=== {pair} ===")
        try:
            raw = load_m1(pair)
            print(f"  Raw M1 rows: {len(raw)}")
        except Exception as e:
            print(f"  [ERROR] {e}")
            continue

        clean, report = clean_m1(raw)
        print(f"  Clean M1 rows: {len(clean)}")
        print(f"  Duplicates removed: {report['duplicates_removed']}")
        print(f"  Flagged jumps: {report['flagged_jumps']}")
        print(f"  Bad HL: {report['bad_hl']}, Bad OHLC: {report['bad_ohlc']}")

        m15 = resample_m15(clean)
        save_m15(pair, m15)
        print(f"  M15 bars: {len(m15)} -> saved")

        # Compute stats
        first = clean["timestamp"].min()
        last = clean["timestamp"].max()
        thin_pct = m15["thin"].mean() * 100

        # Missing weeks
        weeks = pd.date_range(first, last, freq="W-MON")
        present_weeks = m15.set_index("timestamp").resample("W-MON").count()["open"]
        missing_weeks = int((present_weeks == 0).sum())

        # Largest gap
        gaps = m15["timestamp"].diff().dt.total_seconds() / 3600
        largest_gap = gaps.max() if len(gaps) > 1 else 0

        pair_reports.append({
            "pair": pair,
            "first": first.isoformat(),
            "last": last.isoformat(),
            "m15_bars": len(m15),
            "missing_weeks": missing_weeks,
            "largest_gap_h": largest_gap,
            "thin_pct": thin_pct,
            "flagged_jumps": report["flagged_jumps"],
            "duplicates_removed": report["duplicates_removed"],
        })

    report_path = REPORT_DIR / "histdata_validation.md"
    generate_report(pair_reports, report_path)
    print(f"\nReport written to {report_path}")


if __name__ == "__main__":
    main()
