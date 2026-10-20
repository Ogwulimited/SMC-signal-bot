"""Load Dukascopy M15 data, resample to H1/H4/D1, validate, save processed files.

Key rules:
- All timestamps are UTC and represent the OPEN time of the candle.
- Trading day (D1) is defined as 17:00 America/New_York to 17:00 America/New_York.
- No resampled bar uses data after its close.
"""

import os
import glob
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

RAW_DIR = Path(__file__).parent.parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
REPORT_DIR = Path(__file__).parent.parent.parent / "reports" / "data"

PAIRS = [
    "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf",
    "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy"
]

TIMEFRAMES = {"H1": "1h", "H4": "4h", "D1": "1D"}


def load_raw_pair(pair: str, price_type: str = "bid") -> pd.DataFrame:
    """Load all M15 CSVs for a pair and concatenate."""
    pattern = str(RAW_DIR / pair / "m15" / price_type / "*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No raw data found for {pair} {price_type}")

    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
            dfs.append(df)
        except Exception as e:
            print(f"[WARN] Failed to read {f}: {e}")

    if not dfs:
        raise ValueError(f"All files failed to read for {pair}")

    df = pd.concat(dfs, ignore_index=True)

    # Normalise columns
    # Dukascopy-node CSV columns: timestamp, open, high, low, close, volume
    if "timestamp" not in df.columns:
        # try common alternatives
        for c in ["time", "date", "datetime"]:
            if c in df.columns:
                df.rename(columns={c: "timestamp"}, inplace=True)
                break

    if "timestamp" not in df.columns:
        raise ValueError(f"No timestamp column in {pair}. Columns: {df.columns.tolist()}")

    # Convert timestamp: if numeric, assume milliseconds
    if pd.api.types.is_numeric_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    # Ensure numeric OHLC
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    # Remove duplicates
    before = len(df)
    df = df.drop_duplicates(subset=["timestamp"], keep="first")
    if len(df) < before:
        print(f"[{pair}] Removed {before - len(df)} duplicate rows")

    return df


def resample_timeframe(df: pd.DataFrame, rule: str, label: str = "left") -> pd.DataFrame:
    """Resample M15 to a higher timeframe using standard OHLC aggregation.

    For H1/H4, we resample from UTC directly.
    For D1, we use the 17:00 America/New_York trading day.
    """
    if rule == "1D":
        # Convert to NY time, shift by 7 hours so 17:00 becomes 00:00 next day
        ny = df.set_index("timestamp").tz_convert("America/New_York")
        ny["trading_day"] = (ny.index + pd.Timedelta(hours=7)).date
        grouped = ny.groupby("trading_day").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum") if "volume" in ny.columns else ("open", "count")
        ).reset_index()
        # Convert trading_day back to UTC timestamp (midnight UTC of that day)
        grouped["timestamp"] = pd.to_datetime(grouped["trading_day"], utc=True)
        grouped = grouped.drop(columns=["trading_day"])
        return grouped.sort_values("timestamp").reset_index(drop=True)

    # H1 and H4: standard UTC resampling
    df = df.set_index("timestamp")
    resampled = df.resample(rule, label=label, closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum") if "volume" in df.columns else ("open", "count")
    ).dropna(subset=["open"]).reset_index()
    return resampled


def validate(df: pd.DataFrame, pair: str, timeframe: str) -> dict:
    """Run validation checks and return a report dict."""
    issues = []

    # 1. Duplicate timestamps
    dupes = df[df.duplicated(subset=["timestamp"], keep=False)]
    if not dupes.empty:
        issues.append(f"DUPLICATE_TIMESTAMPS: {len(dupes)} rows")

    # 2. High < Low
    bad_hl = df[df["high"] < df["low"]]
    if not bad_hl.empty:
        issues.append(f"HIGH_LESS_THAN_LOW: {len(bad_hl)} rows")

    # 3. Missing bars (expected vs actual)
    if len(df) > 1:
        freq = {"H1": "1h", "H4": "4h", "D1": "1D"}[timeframe]
        expected = pd.date_range(start=df["timestamp"].min(), end=df["timestamp"].max(), freq=freq)
        missing = len(expected) - len(df)
        if missing > 0:
            issues.append(f"MISSING_BARS: {missing} (expected {len(expected)}, got {len(df)})")

    # 4. Weekend gaps (only for intraday)
    if timeframe in ("H1", "H4"):
        gaps = df["timestamp"].diff().dt.total_seconds() / 3600
        large_gaps = gaps[gaps > 60]  # more than 60 hours = likely weekend/holiday
        if len(large_gaps) > 0:
            issues.append(f"LARGE_GAPS: {len(large_gaps)} gaps > 60h")

    # 5. Timestamp monotonicity
    if not df["timestamp"].is_monotonic_increasing:
        issues.append("TIMESTAMPS_NOT_MONOTONIC")

    report = {
        "pair": pair,
        "timeframe": timeframe,
        "rows": len(df),
        "start": df["timestamp"].min().isoformat() if len(df) > 0 else None,
        "end": df["timestamp"].max().isoformat() if len(df) > 0 else None,
        "issues": issues
    }
    return report


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    all_reports = []
    failures = []

    for pair in PAIRS:
        print(f"\n=== Processing {pair} ===")
        try:
            raw = load_raw_pair(pair, price_type="bid")
        except Exception as e:
            print(f"[ERROR] {pair}: {e}")
            failures.append(f"{pair}: {e}")
            continue

        print(f"  Raw M15 rows: {len(raw)}")
        print(f"  First: {raw['timestamp'].min()}")
        print(f"  Last:  {raw['timestamp'].max()}")

        for tf_name, tf_rule in TIMEFRAMES.items():
            try:
                df = resample_timeframe(raw, tf_rule)
                report = validate(df, pair, tf_name)

                # Save processed
                out_path = PROCESSED_DIR / f"{pair}_{tf_name}.csv"
                df.to_csv(out_path, index=False)
                print(f"  Saved {tf_name}: {len(df)} rows -> {out_path}")

                all_reports.append(report)

                if report["issues"]:
                    print(f"  ⚠ Issues: {report['issues']}")
                else:
                    print(f"  ✓ No issues")

            except Exception as e:
                print(f"  [ERROR] {pair} {tf_name}: {e}")
                failures.append(f"{pair} {tf_name}: {e}")

    # Write validation report
    report_lines = [
        "# Data Validation Report",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "",
        "## Summary",
        f"- Pairs processed: {len(PAIRS)}",
        f"- Timeframes: {list(TIMEFRAMES.keys())}",
        f"- Failures: {len(failures)}",
        ""
    ]

    if failures:
        report_lines.append("## Failures")
        for f in failures:
            report_lines.append(f"- {f}")
        report_lines.append("")

    report_lines.append("## Per-Pair Results")
    report_lines.append("| Pair | TF | Rows | Start | End | Issues |")
    report_lines.append("|------|-----|------|-------|-----|--------|")
    for r in all_reports:
        issues_str = "; ".join(r["issues"]) if r["issues"] else "None"
        report_lines.append(
            f"| {r['pair']} | {r['timeframe']} | {r['rows']} | "
            f"{r['start'][:10] if r['start'] else '-'} | "
            f"{r['end'][:10] if r['end'] else '-'} | {issues_str} |"
        )

    report_path = REPORT_DIR / "validation_latest.md"
    report_path.write_text("\n".join(report_lines))
    print(f"\nValidation report written to {report_path}")

    if failures:
        print(f"\n⚠ {len(failures)} failures — exiting with error code 1")
        exit(1)
    else:
        print("\n✓ All pairs validated successfully")


if __name__ == "__main__":
    main()
