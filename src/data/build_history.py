"""Build M15/H1/H4/D1, find holes, explain duplicates."""
import pandas as pd
import glob
from pathlib import Path
from datetime import datetime, timezone

RAW_DIR = Path(__file__).parent.parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent.parent / "data" / "processed"
REPORT_DIR = Path(__file__).parent.parent.parent / "reports" / "data"

PAIRS = ["eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy"]

def load_m1(pair):
    files = sorted(glob.glob(str(RAW_DIR / pair / "*.csv")))
    if not files: raise FileNotFoundError(f"No raw data for {pair}")
    
    dfs = [pd.read_csv(f, sep=";", header=None, names=["timestamp", "open", "high", "low", "close", "volume"]) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    
    # NY Local Time -> Drop Ambiguous/Nonexistent -> UTC
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="%Y%m%d %H%M%S")
    df["timestamp"] = df["timestamp"].dt.tz_localize("America/New_York", ambiguous="NaT", nonexistent="NaT")
    df = df.dropna(subset=["timestamp"])
    df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")
    
    for col in ["open", "high", "low", "close"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)

def explain_duplicates(df):
    before = len(df)
    dupes = df[df.duplicated(subset=["timestamp"], keep=False)]
    removed = before - len(df[df.duplicated(subset=["timestamp"], keep="first")])
    
    identical, different = 0, 0
    if not dupes.empty:
        groups = dupes.groupby("timestamp")
        identical = (groups.nunique().max(axis=1) == 1).sum()
        different = groups.ngroups - identical
            
    df = df.drop_duplicates(subset=["timestamp"], keep="first")
    return df, removed, f"{identical} identical, {different} conflicting (kept first)"

def get_bad_days(df, pair):
    start, end = df["timestamp"].min(), df["timestamp"].max()
    expected = pd.date_range(start, end, freq="15min", tz="UTC")
    
    ny_idx = expected.tz_convert("America/New_York")
    is_weekend = ((ny_idx.dayofweek == 4) & (ny_idx.hour >= 17)) | ((ny_idx.dayofweek == 5)) | ((ny_idx.dayofweek == 6) & (ny_idx.hour < 17))
    expected_open = expected[~is_weekend]
    
    actual = df["timestamp"].dt.floor("15min").unique()
    missing_mask = ~expected_open.isin(actual)
    missing = expected_open[missing_mask]
    
    if len(missing) == 0: return pd.DataFrame()
    
    missing_df = pd.DataFrame({"timestamp": missing})
    missing_df["ny_date"] = (missing_df["timestamp"].dt.tz_convert("America/New_York") + pd.Timedelta(hours=7)).dt.date
    bad_days = missing_df.groupby("ny_date").size().reset_index(name="missing_bars")
    bad_days["pair"] = pair
    return bad_days

def resample(df, rule, offset_hours=0):
    ny = df.set_index("timestamp").tz_convert("America/New_York")
    if offset_hours: ny.index = ny.index + pd.Timedelta(hours=offset_hours)
    
    agg = {"open": ("open", "first"), "high": ("high", "max"), "low": ("low", "min"), "close": ("close", "last")}
    res = ny.resample(rule, label="left", closed="left").agg(**agg).dropna(subset=["open"])
    
    if offset_hours: res.index = res.index - pd.Timedelta(hours=offset_hours)
    
    # CRITICAL FIX: Convert back to UTC before returning
    res = res.tz_convert("UTC")
    res = res.reset_index()
    return res

def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    reports = []

    for pair in PAIRS:
        print(f"Processing {pair}...", flush=True)
        
        df = load_m1(pair)
        df, dupes_removed, dupes_explanation = explain_duplicates(df)
        
        bad_days = get_bad_days(df, pair)
        if not bad_days.empty:
            bad_days.to_parquet(PROCESSED_DIR / f"bad_days_{pair}.parquet", index=False)
            
        total_holes = bad_days["missing_bars"].sum() if not bad_days.empty else 0
        years = (df["timestamp"].max() - df["timestamp"].min()).days / 365.25

        resample(df, "1h").to_parquet(PROCESSED_DIR / f"{pair}_h1.parquet", index=False)
        resample(df, "4h", 7).to_parquet(PROCESSED_DIR / f"{pair}_h4.parquet", index=False)
        resample(df, "1D", 7).to_parquet(PROCESSED_DIR / f"{pair}_d1.parquet", index=False)

        reports.append({
            "pair": pair, "first": df["timestamp"].min().isoformat(), "last": df["timestamp"].max().isoformat(),
            "m15_bars": len(df), "holes_per_year": round(total_holes / years) if years > 0 else 0,
            "dupes": dupes_removed, "dupes_explain": dupes_explanation
        })

    lines = ["# HistData Validation Report\n", "| Pair | First | Last | M15 Bars | Holes/Yr | Dupes Removed | Explanation |", "|---|---|---|---|---|---|---|"]
    for r in reports:
        lines.append(f"| {r['pair']} | {r['first'][:10]} | {r['last'][:10]} | {r['m15_bars']} | {r['holes_per_year']} | {r['dupes']} | {r['dupes_explain']} |")
    (REPORT_DIR / "histdata_validation.md").write_text("\n".join(lines))
    print("Done.")

if __name__ == "__main__":
    main()
