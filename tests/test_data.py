import pytest
import pandas as pd
import glob
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"

@pytest.fixture
def h1():
    return pd.read_parquet(PROCESSED_DIR / "eurusd_h1.parquet")

def test_weekend_open(h1):
    # 1. Spot checks on clean weeks
    # Winter 2022-01-09 (expect 22:00 UTC)
    w1 = h1[h1["timestamp"] >= pd.Timestamp("2022-01-09", tz="UTC")].iloc[0]["timestamp"]
    assert w1.strftime("%H:%M") == "22:00", f"Winter 2022 failed: {w1}"
    
    # Winter 2024-01-07 (expect 22:00 UTC)
    w2 = h1[h1["timestamp"] >= pd.Timestamp("2024-01-07", tz="UTC")].iloc[0]["timestamp"]
    assert w2.strftime("%H:%M") == "22:00", f"Winter 2024 failed: {w2}"
    
    # Summer 2022-07-03 (expect 21:00 UTC)
    s1 = h1[h1["timestamp"] >= pd.Timestamp("2022-07-03", tz="UTC")].iloc[0]["timestamp"]
    assert s1.strftime("%H:%M") == "21:00", f"Summer 2022 failed: {s1}"
    
    # Summer 2024-07-07 (expect 21:00 UTC)
    s2 = h1[h1["timestamp"] >= pd.Timestamp("2024-07-07", tz="UTC")].iloc[0]["timestamp"]
    assert s2.strftime("%H:%M") == "21:00", f"Summer 2024 failed: {s2}"

    # 2. Statistical check over ALL weekends, excluding bad_days
    # Find the first bar of every week (gap > 24h)
    weekend_opens = h1[h1["timestamp"].diff() > pd.Timedelta(hours=24)].copy()
    
    # Add the very first bar if it's a Sunday open
    if h1["timestamp"].iloc[0].tz_convert("America/New_York").dayofweek == 6:
        weekend_opens = pd.concat([h1.iloc[[0]], weekend_opens])

    # Exclude bad_days if the file exists
    bad_days_file = PROCESSED_DIR / "bad_days_eurusd.parquet"
    if bad_days_file.exists():
        bad_df = pd.read_parquet(bad_days_file)
        # bad_days ny_date is string YYYY-MM-DD
        bad_dates = set(bad_df["ny_date"].astype(str).unique())
        weekend_opens["ny_date"] = (weekend_opens["timestamp"].dt.tz_convert("America/New_York") + pd.Timedelta(hours=7)).dt.date.astype(str)
        weekend_opens = weekend_opens[~weekend_opens["ny_date"].isin(bad_dates)]

    weekend_opens["year"] = weekend_opens["timestamp"].dt.year
    weekend_opens["month"] = weekend_opens["timestamp"].dt.month
    weekend_opens["hour"] = weekend_opens["timestamp"].dt.hour

    print("\n--- Statistical Weekend Open Check (EURUSD) ---")
    for year in sorted(weekend_opens["year"].unique()):
        # Winter: Dec, Jan, Feb
        w_data = weekend_opens[(weekend_opens["year"] == year) & (weekend_opens["month"].isin([12, 1, 2]))]
        if not w_data.empty:
            w_pct = (w_data["hour"] == 22).mean() * 100
            print(f"  {year} Winter (Dec-Feb): {w_pct:.1f}% at 22:00 UTC (n={len(w_data)})")
            assert w_pct >= 95.0, f"Winter {year} failed threshold: {w_pct:.1f}%"
        
        # Summer: Jun, Jul, Aug
        s_data = weekend_opens[(weekend_opens["year"] == year) & (weekend_opens["month"].isin([6, 7, 8]))]
        if not s_data.empty:
            s_pct = (s_data["hour"] == 21).mean() * 100
            print(f"  {year} Summer (Jun-Aug): {s_pct:.1f}% at 21:00 UTC (n={len(s_data)})")
            assert s_pct >= 95.0, f"Summer {year} failed threshold: {s_pct:.1f}%"
    print("------------------------------------------------\n")

    # 3. Print 3 raw sample rows from a summer weekend open
    raw_files = glob.glob(str(RAW_DIR / "eurusd" / "*2022*.csv"))
    if raw_files:
        raw_df = pd.read_csv(raw_files[0], sep=";", header=None, names=["raw", "open", "high", "low", "close", "vol"])
        sample = raw_df[raw_df["raw"].astype(str).str.startswith("20220703 1700")].head(3)
        if not sample.empty:
            print("\n--- Raw Sample Rows (Summer Weekend Open 2022-07-03) ---")
            for _, row in sample.iterrows():
                ts = pd.to_datetime(str(row["raw"]), format="%Y%m%d %H%M%S")
                loc = ts.tz_localize("America/New_York")
                utc = loc.tz_convert("UTC")
                print(f"Raw: {row['raw']} | Localized: {loc} | UTC: {utc}")
            print("---------------------------------------------------------\n")

def test_london_jump(h1):
    # London jump winter is 07:00 UTC (Jan 11, 2022), summer is 06:00 UTC (July 12, 2022)
    w_day = h1[(h1["timestamp"].dt.date == pd.Timestamp("2022-01-11").date()) & (h1["timestamp"].dt.hour == 7)]
    s_day = h1[(h1["timestamp"].dt.date == pd.Timestamp("2022-07-12").date()) & (h1["timestamp"].dt.hour == 6)]
    assert len(w_day) > 0, "Missing 07:00 UTC in Winter"
    assert len(s_day) > 0, "Missing 06:00 UTC in Summer"

def test_nfp_spike(h1):
    # NFP spike winter is 13:00 UTC (Jan 7, 2022), summer is 12:00 UTC (July 8, 2022)
    w_nfp = h1[(h1["timestamp"] == pd.Timestamp("2022-01-07 13:00:00", tz="UTC"))]
    s_nfp = h1[(h1["timestamp"] == pd.Timestamp("2022-07-08 12:00:00", tz="UTC"))]
    assert not w_nfp.empty, "Missing Winter NFP (13:30 UTC)"
    assert not s_nfp.empty, "Missing Summer NFP (12:30 UTC)"
