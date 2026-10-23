"""Download 1-minute bid data from histdata.com using the `histdata` package.

API: from histdata import download_hist_data as dl
     from histdata.api import Platform as P, TimeFrame as TF
     
     - Past years: dl(year='2023', month=None, pair='eurusd', ...)
     - Current year: dl(year='2026', month='1', pair='eurusd', ...)
"""

import os
import sys
import time
import glob
import zipfile
import requests
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
TEST_YEAR = os.environ.get("TEST_YEAR", "2023")


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


def validate_file(csv_path, pair, year, month=None):
    """Print file details and check row counts."""
    if not csv_path or not os.path.exists(csv_path):
        return False
    if os.path.getsize(csv_path) == 0:
        print(f"[FAIL] {pair} {year}{'-' + str(month) if month else ''}: empty file")
        return False

    size_mb = os.path.getsize(csv_path) / (1024 * 1024)
    with open(csv_path, "r") as f:
        lines = f.readlines()
        row_count = len(lines)
        if row_count == 0:
            print(f"[FAIL] {pair} {year}{'-' + str(month) if month else ''}: 0 rows")
            return False
        first_ts = lines[0].strip().split(";")[0]
        last_ts = lines[-1].strip().split(";")[0]

    print(f"[OK] {pair} {year}{'-' + str(month) if month else ''}: "
          f"{size_mb:.2f} MB, {row_count} rows, "
          f"first={first_ts}, last={last_ts}")

    # Warning for full year row count
    if month is None and year >= 2016:
        if not (350000 <= row_count <= 375000):
            print(f"  ⚠️ WARNING: Row count {row_count} is outside expected "
                  f"350k-375k range for a full year of {pair}.")

    return True


def download_with_retry(pair, year, month=None, retries=3):
    """Download with retry for network errors only."""
    pair_dir = RAW_DIR / pair
    pair_dir.mkdir(parents=True, exist_ok=True)

    # Check if we already have a valid file
    pattern = str(pair_dir / f"*{year}*")
    if month:
        pattern = str(pair_dir / f"*{year}*{month:02d}*")
    
    existing = glob.glob(pattern)
    for f in existing:
        if os.path.getsize(f) > 0:
            print(f"[SKIP] {pair} {year}{'-' + str(month) if month else ''} (exists)")
            return True
        else:
            print(f"[CLEAN] Removing empty file: {f}")
            os.remove(f)

    for attempt in range(1, retries + 1):
        try:
            print(f"[DL] {pair} {year}{'-' + str(month) if month else ''} (attempt {attempt})")
            
            # Pass month=None for full year, or str(month) for monthly
            kwargs = {
                "year": str(year),
                "pair": pair,
                "time_frame": TF.ONE_MINUTE,
                "platform": P.GENERIC_ASCII,
                "output_directory": str(pair_dir),
                "verbose": True,
            }
            if month is not None:
                kwargs["month"] = str(month)
            else:
                kwargs["month"] = None

            filename = dl(**kwargs)

            if filename and os.path.exists(filename) and os.path.getsize(filename) > 0:
                csv_path = extract_zip(filename, str(pair_dir))
                if validate_file(csv_path, pair, year, month):
                    return True
                else:
                    return False
            else:
                print(f"[FAIL] {pair} {year}{'-' + str(month) if month else ''}: empty zip")

        except AssertionError as e:
            # Validation error from the library (e.g., invalid month for current year)
            # Do NOT retry, fail immediately.
            print(f"[FATAL] {pair} {year}{'-' + str(month) if month else ''}: {e}")
            return False
        except requests.exceptions.RequestException as e:
            # Network error, safe to retry
            print(f"[RETRY] {pair} {year}{'-' + str(month) if month else ''}: Network error: {e}")
        except Exception as e:
            # Unknown error, treat as fatal
            print(f"[FATAL] {pair} {year}{'-' + str(month) if month else ''}: Unexpected error: {e}")
            return False

        time.sleep(3 * attempt)

    print(f"[GIVE UP] {pair} {year}{'-' + str(month) if month else ''}")
    return False


def main():
    if TEST_MODE:
        print(f"TEST MODE: {TEST_PAIR} full year {TEST_YEAR}")
        ok = download_with_retry(TEST_PAIR, int(TEST_YEAR), month=None)
        if not ok:
            sys.exit(1)
        
        # Print first 3 lines for test mode
        pattern = str(RAW_DIR / TEST_PAIR / f"*{TEST_YEAR}*.csv")
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
        # 1. Past years: full year download (month=None)
        for year in range(START_YEAR, end_year):
            ok = download_with_retry(pair, year, month=None)
            if not ok:
                failed.append(f"{pair} {year} (full year)")
            time.sleep(3)

        # 2. Current year: monthly downloads up to last complete month
        for month in range(1, end_month + 1):
            ok = download_with_retry(pair, end_year, month=month)
            if not ok:
                failed.append(f"{pair} {end_year}-{month:02d}")
            time.sleep(3)

    if failed:
        print(f"\nFAILED DOWNLOADS: {len(failed)}")
        for f in failed:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll downloads complete.")


if __name__ == "__main__":
    main()
