"""Download 1-minute bid data from histdata.com using the `histdata` package.

API: from histdata import download_hist_data as dl
     from histdata.api import Platform as P, TimeFrame as TF
     dl(year='2023', month='1', pair='eurusd', time_frame=TF.ONE_MINUTE,
        platform=P.GENERIC_ASCII, output_directory='.')
"""

import os
import sys
import time
import glob
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from histdata import download_hist_data as dl
from histdata.api import Platform as P, TimeFrame as TF

PAIRS = [
    "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf",
    "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy"
]
START_YEAR = 2016
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
TEST_MODE = os.environ.get("TEST_MODE", "true").lower() == "true"
TEST_PAIR = os.environ.get("TEST_PAIR", "eurusd")
TEST_MONTH = os.environ.get("TEST_MONTH", "2023-01")


def latest_complete_month():
    now = datetime.now(timezone.utc)
    if now.month == 1:
        return now.year - 1, 12
    return now.year, now.month - 1


def extract_zip(zip_path, pair_dir):
    """Extract the CSV from the downloaded ZIP."""
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith(".csv"):
                    z.extract(name, pair_dir)
                    return os.path.join(pair_dir, name)
    except zipfile.BadZipFile:
        print(f"[WARN] Bad zip file: {zip_path}")
        return None
    return None


def download_month(pair, year, month):
    pair_dir = RAW_DIR / pair
    pair_dir.mkdir(parents=True, exist_ok=True)

    # Check if a non-empty CSV already exists for this month
    pattern = str(pair_dir / f"*{year}*{month:02d}*")
    existing = glob.glob(pattern)
    for f in existing:
        if os.path.getsize(f) > 0:
            print(f"[SKIP] {pair} {year}-{month:02d} (exists)")
            return True
        else:
            print(f"[CLEAN] Removing empty file: {f}")
            os.remove(f)

    for attempt in range(1, 4):
        try:
            print(f"[DL] {pair} {year}-{month:02d} (attempt {attempt})")
            filename = dl(
                year=str(year), month=str(month), pair=pair,
                time_frame=TF.ONE_MINUTE, platform=P.GENERIC_ASCII,
                output_directory=str(pair_dir), verbose=True
            )
            if filename and os.path.exists(filename) and os.path.getsize(filename) > 0:
                csv_path = extract_zip(filename, str(pair_dir))
                if csv_path and os.path.getsize(csv_path) > 0:
                    with open(csv_path, "r") as f:
                        rows = sum(1 for _ in f)
                    print(f"[OK] {pair} {year}-{month:02d}: {rows} rows, {os.path.getsize(csv_path)} bytes")
                    if rows == 0:
                        print(f"[FAIL] {pair} {year}-{month:02d}: 0 rows")
                        return False
                    return True
                else:
                    print(f"[FAIL] {pair} {year}-{month:02d}: empty CSV")
            else:
                print(f"[FAIL] {pair} {year}-{month:02d}: empty zip")
        except Exception as e:
            print(f"[ERROR] {pair} {year}-{month:02d}: {e}")

        time.sleep(3 * attempt)

    print(f"[GIVE UP] {pair} {year}-{month:02d}")
    return False


def main():
    if TEST_MODE:
        year, month = TEST_MONTH.split("-")
        year, month = int(year), int(month)
        print(f"TEST MODE: {TEST_PAIR} {year}-{month:02d}")
        ok = download_month(TEST_PAIR, year, month)
        if not ok:
            sys.exit(1)
            
        pattern = str(RAW_DIR / TEST_PAIR / f"*{year}*{month:02d}*.csv")
        files = glob.glob(pattern)
        if files:
            print("\n=== FIRST 3 LINES OF FILE ===")
            with open(files[0], "r") as f:
                for _ in range(3):
                    line = f.readline()
                    if line:
                        print(line.strip())
            print("=============================")
        print("TEST PASSED")
        return

    end_year, end_month = latest_complete_month()
    failed = []
    for pair in PAIRS:
        for year in range(START_YEAR, end_year + 1):
            month_start = 1
            month_end = 12
            if year == end_year:
                month_end = end_month
            for month in range(month_start, month_end + 1):
                ok = download_month(pair, year, month)
                if not ok:
                    failed.append(f"{pair} {year}-{month:02d}")
                time.sleep(3)

    if failed:
        print(f"\nFAILED MONTHS: {len(failed)}")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll downloads complete.")


if __name__ == "__main__":
    main()
