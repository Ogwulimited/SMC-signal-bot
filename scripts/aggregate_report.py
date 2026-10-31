"""Aggregate per-pair report rows (written by build_history.py's
process_pair(), one JSON file per pair in data/processed/) into the
single histdata_validation.md report.

Needed because histdata.yml's `build` job runs one pair per matrix job/
runner -- no single process ever sees all 28 pairs' data at once, unlike
the legacy 11-pair pipeline (histdata_pipeline.yml), where
build_history.py's main() loops over all pairs in one job and writes the
table directly. This script runs once, in the test_and_report job, after
all pairs' processed caches (including their *_report_row.json files)
have been restored onto the same runner.

Environment variables:
  PAIRS_OVERRIDE  Optional comma-separated pair list (used by smoke mode).
                  If empty/unset, all of config.PAIRS is expected.
  STRICT          If "true", exit non-zero BEFORE writing any report when
                  any expected pair's report row is missing. Otherwise a
                  missing pair only prints a warning.

Must be invoked with PYTHONPATH=. so `from src.config import ...`
resolves correctly -- this script lives in scripts/, not src/, so
sys.path[0] is scripts/ by default when invoked as
`python scripts/aggregate_report.py` from the repo root.
"""
import json
import os
import sys
from pathlib import Path
from src.config import PAIRS as ALL_PAIRS

PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
REPORT_DIR = Path(__file__).parent.parent / "reports" / "data"

def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    override = os.environ.get("PAIRS_OVERRIDE", "")
    if override.strip():
        target_pairs = [p.strip() for p in override.split(",") if p.strip()]
    else:
        target_pairs = ALL_PAIRS
    strict = os.environ.get("STRICT", "false").lower() == "true"

    rows = []
    missing_pairs = []
    for pair in target_pairs:
        f = PROCESSED_DIR / f"{pair}_report_row.json"
        if not f.exists():
            missing_pairs.append(pair)
            continue
        with open(f) as fh:
            rows.append(json.load(fh))

    if missing_pairs:
        msg = (f"Missing report rows for: {', '.join(missing_pairs)} "
               f"(processed cache not restored, or build failed).")
        if strict:
            print(f"[ERROR] {msg} STRICT mode: failing before writing any report.")
            sys.exit(1)
        print(f"[WARN] {msg} Report will be generated for the {len(rows)} pairs present.")

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
    print(f"Done. Aggregated {len(rows)}/{len(target_pairs)} pairs.")

if __name__ == "__main__":
    main()
