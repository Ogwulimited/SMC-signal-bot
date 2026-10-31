"""Temporary diagnostic: inspect 2023 data gaps per pair to see if they cluster
(provider outage) or scatter (something else). Reads bad_days_{pair}.parquet
produced by build_history.py. Not part of the test suite — ad hoc investigation."""
import pandas as pd
from pathlib import Path

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

PAIRS = [
    "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad",
    "usdchf", "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy"
]

def main():
    for pair in PAIRS:
        f = PROCESSED_DIR / f"bad_days_{pair}.parquet"
        if not f.exists():
            print(f"\n=== {pair}: no bad_days file at all (no days with >=3 missing bars) ===")
            continue
        df = pd.read_parquet(f)
        df["ny_date"] = pd.to_datetime(df["ny_date"])
        df_2023 = df[df["ny_date"].dt.year == 2023].sort_values("ny_date")
        total_missing = df_2023["missing_bars"].sum()
        print(f"\n=== {pair}: {len(df_2023)} bad days in 2023, {total_missing} total missing bars ===")
        for _, row in df_2023.iterrows():
            print(f"  {row['ny_date'].date()}  missing={row['missing_bars']}")

if __name__ == "__main__":
    main()
