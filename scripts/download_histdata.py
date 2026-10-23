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

PAIR = os.environ.get("PAIR")
START_YEAR = 2016
RAW_DIR = Path(__file__).parent.parent / "data" / "raw"

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

def download(pair, year, month=None):
    pair_dir = RAW_DIR / pair
    pair_dir.mkdir(parents=True, exist_ok=True)
    
    # FIXED: Convert path to string before adding string suffixes
    if month:
        pattern = str(pair_dir) + f"/*{year}*{month:02d}*"
    else:
        pattern = str(pair_dir) + f"/*{year}*"
        
    if glob.glob(pattern):
        print(f"[SKIP] {pair} {year}-{month if month else 'Full'}")
        return True

    for attempt in range(1, 4):
        try:
            kwargs = {
                "year": str(year), "pair": pair, "time_frame": TF.ONE_MINUTE,
                "platform": P.GENERIC_ASCII, "output_directory": str(pair_dir), "verbose": True
            }
            if month: kwargs["month"] = str(month)
            else: kwargs["month"] = None

            filename = dl(**kwargs)
            if filename and os.path.getsize(filename) > 0:
                csv_path = extract_zip(filename, str(pair_dir))
                if csv_path and os.path.getsize(csv_path) > 0:
                    print(f"[OK] {pair} {year}-{month if month else 'Full'}")
                    return True
        except requests.exceptions.RequestException:
            time.sleep(3 * attempt)
        except Exception as e:
            print(f"[FATAL] {e}")
            return False
    return False

def main():
    end_year, end_month = latest_complete_month()
    for year in range(START_YEAR, end_year):
        download(PAIR, year, month=None)
    for month in range(1, end_month + 1):
        download(PAIR, end_year, month=month)

if __name__ == "__main__":
    main()
