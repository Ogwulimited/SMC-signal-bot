"""Load Dukascopy M15 data, resample to H1/H4/D1, validate, save processed files."""
import os
import glob
import pandas as pd
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
    pattern = str(RAW_DIR / pair / "m15" / price_type / "*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        raise FileNotFoundError(f"No raw data found for {pair} {price_type}")

    dfs = []
    for f in files:
        if os.path.getsize(f) == 0:
            print(f"[WARN] Empty file skipped: {os.path.basename(f)}")
            continue
            
        try:
            # Dukascopy-node CSV format: timestamp,open,high,low,close,volume
            df = pd.read_csv(f, header=None, names=["timestamp", "open", "high", "low", "close", "volume"])
            dfs.append(df)
        except Exception as e:
            print(f"[WARN] Failed to read {os.path.basename(f)}: {e}")

    if not dfs:
        raise ValueError(f"All files empty or failed to read for {pair}")

    df = pd.concat(dfs, ignore_index=True)

    if pd.api.types.is_numeric_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    df = df.sort_values("timestamp").reset_index(drop=True)
    df = df.drop_duplicates(subset=["timestamp"], keep="first")
    return df

def resample_timeframe(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if rule == "1D":
        # Shift by 7 hours to handle 17:00 NY close
        ny = df.set_index("timestamp").tz_convert("America/New_York")
        ny["trading_day"] = (ny.index + pd.Timedelta(hours=7)).date
        grouped = ny.groupby("trading_day").agg(
            open=("open", "first"), high=("high", "max"),
            low=("low", "min"), close=("close", "last"),
            volume=("volume", "sum") if "volume" in ny.columns else ("open", "count")
        ).reset_index()
        grouped["timestamp"] = pd.to_datetime(grouped["trading_day"], utc=True)
        return grouped.drop(columns=["trading_day"]).sort_values("timestamp").reset_index(drop=True)

    df = df.set_index("timestamp")
    resampled = df.resample(rule, label="left", closed="left").agg(
        open=("open", "first"), high=("high", "max"),
        low=("low", "min"), close=("close", "last"),
        volume=("volume", "sum") if "volume" in df.columns else ("open", "count")
    ).dropna(subset=["open"]).reset_index()
    return resampled

def validate(df: pd.DataFrame, pair: str, timeframe: str) -> dict:
    issues = []
    dupes = df[df.duplicated(subset=["timestamp"], keep=False)]
    if not dupes.empty: issues.append(f"DUPLICATES: {len(dupes)}")
    
    bad_hl = df[df["high"] < df["low"]]
    if not bad_hl.empty: issues.append(f"HIGH<LOW: {len(bad_hl)}")
    
    if len(df) > 1:
        freq = {"H1": "1h", "H4": "4h", "D1": "1D"}[timeframe]
        expected = pd.date_range(start=df["timestamp"].min(), end=df["timestamp"].max(), freq=freq)
        missing = len(expected) - len(df)
        if missing > 0: issues.append(f"MISSING: {missing}")

    return {
        "pair": pair, "timeframe": timeframe, "rows": len(df),
        "start": df["timestamp"].min().isoformat() if len(df) > 0 else None,
        "end": df["timestamp"].max().isoformat() if len(df) > 0 else None,
        "issues": issues
    }

def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    all_reports, failures = [], []

    for pair in PAIRS:
        print(f"\n=== Processing {pair} ===")
        try:
            raw = load_raw_pair(pair, price_type="bid")
            print(f"  Raw M15 rows: {len(raw)}")
        except Exception as e:
            print(f"[ERROR] {pair}: {e}")
            failures.append(f"{pair}: {e}")
            continue

        for tf_name, tf_rule in TIMEFRAMES.items():
            try:
                df = resample_timeframe(raw, tf_rule)
                report = validate(df, pair, tf_name)
                df.to_csv(PROCESSED_DIR / f"{pair}_{tf_name}.csv", index=False)
                all_reports.append(report)
                if report["issues"]:
                    print(f"  ⚠ {tf_name}: {report['issues']}")
                else:
                    print(f"  ✓ {tf_name}: {len(df)} rows")
            except Exception as e:
                failures.append(f"{pair} {tf_name}: {e}")

    report_lines = [
        "# Data Validation Report",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        "", "## Summary",
        f"- Failures: {len(failures)}", ""
    ]
    if failures:
        report_lines.append("## Failures")
        for f in failures: report_lines.append(f"- {f}")
        report_lines.append("")

    report_lines.append("## Per-Pair Results")
    report_lines.append("| Pair | TF | Rows | Start | End | Issues |")
    report_lines.append("|------|-----|------|-------|-----|--------|")
    for r in all_reports:
        issues_str = "; ".join(r["issues"]) if r["issues"] else "None"
        report_lines.append(f"| {r['pair']} | {r['timeframe']} | {r['rows']} | {r['start'][:10] if r['start'] else '-'} | {r['end'][:10] if r['end'] else '-'} | {issues_str} |")

    (REPORT_DIR / "validation_latest.md").write_text("\n".join(report_lines))
    print(f"\nValidation report written to {REPORT_DIR}/validation_latest.md")
    
    if failures: exit(1)

if __name__ == "__main__":
    main()
