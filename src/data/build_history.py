"""Build M15/H1/H4/D1, find holes, explain duplicates."""
import pandas as pd
import glob
import os
import time
from pathlib import Path
from datetime import datetime, timezone
from ..research.primitives import resample_to_tf
from ..config import PAIRS as ALL_PAIRS, PAIR_COHORTS

RAW_DIR = Path(__file__).parent.parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
REPORT_DIR = Path(__file__).parent.parent.parent / "reports" / "data"

def load_m1(pair):
    files = sorted(glob.glob(str(RAW_DIR / pair / "*.csv")))
    if not files: raise FileNotFoundError(f"No raw data for {pair}")
    
    dfs = [pd.read_csv(f, sep=";", header=None, names=["timestamp", "open", "high", "low", "close", "volume"]) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y%m%d %H%M%S")
    
    # HistData raw stamps behave as America/New_York local time with DST.
    df["timestamp"] = df["timestamp"].dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
    
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)

def explain_duplicates(df):
    dupes_count = int(df.duplicated(subset=["timestamp"], keep="first").sum())
    dupes = df[df.duplicated(subset=["timestamp"], keep=False)]
    identical, different = 0, 0
    if not dupes.empty:
        groups = dupes.groupby("timestamp")
        identical = (groups.nunique().max(axis=1) == 1).sum()
        different = groups.ngroups - identical
    df = df.drop_duplicates(subset=["timestamp"], keep="first")
    return df, dupes_count, f"{identical} identical groups, {different} conflicting groups"

def resample_m1_to_m15(df):
    ny = df.set_index("timestamp").tz_convert("America/New_York")
    ny_naive = ny.tz_localize(None)
    origin = pd.Timestamp("2020-01-01 17:00:00")
    agg = {"open": ("open", "first"), "high": ("high", "max"), "low": ("low", "min"), "close": ("close", "last")}
    res = ny_naive.resample("15min", origin=origin, label="left", closed="left").agg(**agg).dropna(subset=["open"])
    
    last_m1_close = ny_naive.index.max() + pd.Timedelta(minutes=1)
    bin_end = res.index + pd.Timedelta(minutes=15)
    res = res[bin_end <= last_m1_close]
    
    res.index = res.index.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    res = res[res.index.notna()]
    return res.tz_convert("UTC").reset_index()

def get_bad_days_and_holidays(m15, pair):
    start, end = m15["timestamp"].min(), m15["timestamp"].max()
    expected = pd.date_range(start, end, freq="15min", tz="UTC")
    
    ny_idx = expected.tz_convert("America/New_York")
    is_weekend = ((ny_idx.dayofweek == 4) & (ny_idx.hour >= 17)) | (ny_idx.dayofweek == 5) | ((ny_idx.dayofweek == 6) & (ny_idx.hour < 17))
    expected_open = expected[~is_weekend]
    
    actual = m15["timestamp"].dt.floor("15min").unique()
    missing_mask = ~expected_open.isin(actual)
    missing = expected_open[missing_mask]
    
    missing_df = pd.DataFrame({"timestamp": missing})
    if missing_df.empty: return pd.DataFrame(), 0, 0
    
    missing_df["ny_date"] = (missing_df["timestamp"].dt.tz_convert("America/New_York") + pd.Timedelta(hours=7)).dt.date
    grouped = missing_df.groupby("ny_date").size().reset_index(name="missing_bars")
    
    bad_days = grouped[grouped["missing_bars"] >= 3]
    holidays = grouped[grouped["missing_bars"] >= 90]
    total_missing = grouped["missing_bars"].sum()
    
    return bad_days, len(holidays), total_missing

def process_pair(pair):
    start_time = time.time()
    print(f"Processing {pair}...", flush=True)
    
    df = load_m1(pair)
    m1_bars = len(df)
    df, dupes_removed, dupes_explanation = explain_duplicates(df)
    
    m15 = resample_m1_to_m15(df)
    m15_bars = len(m15)
    
    bad_days, holidays, total_missing = get_bad_days_and_holidays(m15, pair)
    if not bad_days.empty:
        bad_days.to_parquet(PROCESSED_DIR / f"bad_days_{pair}.parquet", index=False)
        
    years = (df["timestamp"].max() - df["timestamp"].min()).days / 365.25
    
    bad_days_2023 = len(bad_days[bad_days["ny_date"].astype(str).str.startswith("2023")]) if not bad_days.empty else 0
    missing_2023 = bad_days[bad_days["ny_date"].astype(str).str.startswith("2023")]["missing_bars"].sum() if not bad_days.empty else 0
    
    m15.to_parquet(PROCESSED_DIR / f"{pair}_m15.parquet", index=False)
    resample_to_tf(m15, "1h").to_parquet(PROCESSED_DIR / f"{pair}_h1.parquet", index=False)
    resample_to_tf(m15, "4h").to_parquet(PROCESSED_DIR / f"{pair}_h4.parquet", index=False)
    resample_to_tf(m15, "1D").to_parquet(PROCESSED_DIR / f"{pair}_d1.parquet", index=False)

    elapsed = time.time() - start_time
    print(f"Finished {pair} in {elapsed:.2f}s")
    
    return {
        "pair": pair, "cohort": PAIR_COHORTS[pair],
        "first": df["timestamp"].min().isoformat(), "last": df["timestamp"].max().isoformat(),
        "m1_bars": m1_bars, "m15_bars": m15_bars,
        "holes_per_year": round(total_missing / years) if years > 0 else 0,
        "dupes": dupes_removed, "dupes_explain": dupes_explanation,
        "bad_days": len(bad_days) if not bad_days.empty else 0,
        "holidays": holidays, "bad_days_2023": bad_days_2023, "missing_2023": missing_2023
    }

def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    
    target_pairs = [os.environ["PAIR"]] if "PAIR" in os.environ else ALL_PAIRS
    reports = []

    for pair in target_pairs:
        reports.append(process_pair(pair))

    # Only generate report if running all pairs (not matrix mode)
    if "PAIR" not in os.environ:
        lines = [
            "# HistData Validation Report\n",
            "| Pair | Cohort | First | Last | M1 Bars | M15 Bars | Holes/Yr | Bad Days | 2023 Missing |",
            "|---|---|---|---|---|---|---|---|---|"
        ]
        for r in reports:
            lines.append(
                f"| {r['pair']} | {r['cohort']} | {r['first'][:10]} | {r['last'][:10]} | {r['m1_bars']} | {r['m15_bars']} | "
                f"{r['holes_per_year']} | {r['bad_days']} | {r['missing_2023']} |"
            )
        (REPORT_DIR / "histdata_validation.md").write_text("\n".join(lines))
        print("Done.")

if __name__ == "__main__":
    main()
