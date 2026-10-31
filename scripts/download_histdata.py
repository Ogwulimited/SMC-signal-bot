"""Download 1-minute bid data from histdata.com. Runs per pair."""
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

# All 28 pairs
PAIRS = [
    "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy",
    "eurchf", "eurcad", "euraud", "eurnzd", "gbpchf", "gbpcad", "gbpaud", "gbpnzd",
    "audcad", "audchf", "audnzd", "nzdjpy", "nzdcad", "nzdchf", "cadjpy", "cadchf", "chfjpy"
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
    try:
        with zipfile.ZipFile(zip_path, "r") as z:
            for name in z.namelist():
                if name.lower().endswith(".csv"):
                    z.extract(name, pair_dir)
                    return os.path.join(pair_dir, name)
    except zipfile.BadZipFile:
        return None
    return None

def validate_file(csv_path, pair, year, month=None):
    if not csv_path or not os.path.exists(csv_path): return False
    if os.path.getsize(csv_path) == 0: return False

    size_mb = os.path.getsize(csv_path) / (1024 * 1024)
    with open(csv_path, "r") as f:
        lines = f.readlines()
        row_count = len(lines)
        if row_count == 0: return False
        first_ts = lines[0].strip().split(";")[0]
        last_ts = lines[-1].strip().split(";")[0]

    print(f"[OK] {pair} {year}{'-' + str(month) if month else ''}: {size_mb:.2f} MB, {row_count} rows")
    return True

def download_with_retry(pair, year, month=None, retries=3):
    pair_dir = RAW_DIR / pair
    pair_dir.mkdir(parents=True, exist_ok=True)

    # Fix: build the glob pattern as a plain string FIRST (both parts are
    # strings), then join onto pair_dir exactly once. The previous version
    # did `pair_dir / f"*{year}*" + (...)` -- `pair_dir / "..."` evaluates
    # to a PosixPath, and Path objects do not support `+` with a plain
    # string (TypeError), so this crashed unconditionally on every single
    # call regardless of pair/year/mode.
    year_part = f"*{year}*"
    month_part = f"*{month:02d}*" if month else "*"
    pattern = str(pair_dir / (year_part + month_part))
    existing = glob.glob(pattern)
    for f in existing:
        if os.path.getsize(f) > 0:
            print(f"[SKIP] {pair} {year}{'-' + str(month) if month else ''} (exists)")
            return True
        else:
            os.remove(f)

    for attempt in range(1, retries + 1):
        try:
            kwargs = {
                "year": str(year), "pair": pair, "time_frame": TF.ONE_MINUTE,
                "platform": P.GENERIC_ASCII, "output_directory": str(pair_dir), "verbose": False
            }
            if month is not None: kwargs["month"] = str(month)
            else: kwargs["month"] = None

            filename = dl(**kwargs)
            if filename and os.path.exists(filename) and os.path.getsize(filename) > 0:
                csv_path = extract_zip(filename, str(pair_dir))
                if validate_file(csv_path, pair, year, month):
                    return True
        except AssertionError as e:
            print(f"[FATAL] {pair} {year}: {e}")
            return False
        except requests.exceptions.RequestException:
            time.sleep(3 * attempt)
        except Exception as e:
            print(f"[RETRY] {pair} {year}: {e}")
        time.sleep(2)
    return False

def main():
    if TEST_MODE:
        print(f"TEST MODE: {TEST_PAIR} {TEST_YEAR}")
        ok = download_with_retry(TEST_PAIR, int(TEST_YEAR), month=None)
        if not ok: sys.exit(1)
        return

    end_year, end_month = latest_complete_month()

    # Check if running in matrix mode (single pair) or all pairs
    target_pairs = [os.environ["PAIR"]] if "PAIR" in os.environ else PAIRS

    for pair in target_pairs:
        # Full years
        for year in range(START_YEAR, end_year):
            download_with_retry(pair, year, month=None)
        # Current year months
        for month in range(1, end_month + 1):
            download_with_retry(pair, end_year, month=month)

if __name__ == "__main__":
    main()
