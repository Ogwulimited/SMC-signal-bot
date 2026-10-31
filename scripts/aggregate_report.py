"""Aggregate per-pair report rows (written by build_history.py's
process_pair(), one JSON file per pair in data/processed/) into the
single histdata_validation.md report.

Needed because histdata.yml's `build` job runs one pair per matrix job/
runner -- no single process ever sees all 28 pairs' data at once, unlike
the legacy 11-pair pipeline (histdata_pipeline.yml), where
build_history.py's main() loops over all pairs in one job and writes the
table directly. This script runs once, in the test_and_report job, after
all 28 pairs' processed caches (including their *_report_row.json files)
have been restored onto the same runner.

Must be invoked with PYTHONPATH=. so `from src.config import ...`
resolves correctly -- this script lives in scripts/, not src/, so
sys.path[0] is scripts/ by default when invoked as
`python scripts/aggregate_report.py` from the repo root.
"""
import json
from pathlib import Path
from src.config import PAIRS as ALL_PAIRS

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
REPORT_DIR = Path(__file__).parent.parent / "reports" / "data"

def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    missing_pairs = []
    for pair in ALL_PAIRS:
        f = PROCESSED_DIR / f"{pair}_report_row.json"
        if not f.exists():
            missing_pairs.append(pair)
            continue
        with open(f) as fh:
            rows.append(json.load(fh))

    if missing_pairs:
        print(f"[WARN] Missing report rows for: {', '.join(missing_pairs)} "
              f"(their processed cache may not have been restored, or their "
              f"build job may have failed). Report will be generated for "
              f"the {len(rows)} pairs that are present.")

    lines = [
        "# HistData Validation Report\n",
        "| Pair | Cohort | First | Last | M1 Bars | M15 Bars | Holes/Yr | Bad Days | 2023 Missing |",
        "|---|---|---|---|---|---|---|---|---|"
    ]
    for r in rows:
        lines.append(
            f"| {r['pair']} | {r['cohort']} | {r['first'][:10]} | {r['last'][:10]} | {r['m1_bars']} | {r['m15_bars']} | "
            f"{r['holes_per_year']} | {r['bad_days']} | {r['missing_2023']} |"
        )
    (REPORT_DIR / "histdata_validation.md").write_text("\n".join(lines))
    print(f"Done. Aggregated {len(rows)}/{len(ALL_PAIRS)} pairs.")

if __name__ == "__main__":
    main()
