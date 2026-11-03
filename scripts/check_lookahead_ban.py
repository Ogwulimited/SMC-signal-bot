#!/usr/bin/env python3
"""CI grep: fails the build if banned lookahead patterns appear in engine code.

Usage: python scripts/check_lookahead_ban.py [folder ...]
Default folder: src/research/engine
A line can be allowed with:  # lookahead-ok: <reason>
Full-comment lines are skipped.
"""
import re
import sys
from pathlib import Path

PATTERNS = [
    ("shift with a negative step", re.compile(r"shift\(\s*-")),
    ("center=True", re.compile(r"center\s*=\s*True")),
    ("bfill / backfill", re.compile(r"\b(bfill|backfill)\b")),
    ("label='right' resampling", re.compile(r"label\s*=\s*['\"]right['\"]")),
    ("iloc[-1] on a frame", re.compile(r"\.iloc\[\s*-1\s*\]")),
    ("full-series max/min/mean/quantile", re.compile(r"\.(max|min|mean|quantile)\s*\(")),
    ("engine imports the trade simulator", re.compile(r"^\s*(from|import)\b.*\btradesim\b")),
]
OK_TAG = re.compile(r"#\s*lookahead-ok:\s*\S")


def scan(root):
    problems = []
    files = sorted(Path(root).rglob("*.py"))
    for f in files:
        for no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#") or OK_TAG.search(line):
                continue
            for name, rx in PATTERNS:
                if rx.search(line):
                    problems.append(f"{f}:{no}: [{name}] {line.strip()}")
    return files, problems


def main():
    default = Path(__file__).resolve().parents[1] / "src" / "research" / "engine"
    roots = [Path(a) for a in sys.argv[1:]] or [default]
    all_files, all_problems = [], []
    for r in roots:
        if not r.exists():
            print(f"LOOKAHEAD BAN: folder not found: {r}")
            return 1
        files, problems = scan(r)
        all_files += files
        all_problems += problems
    if all_problems:
        print(f"LOOKAHEAD BAN: {len(all_problems)} violation(s)")
        for p in all_problems:
            print("  " + p)
        return 1
    print(f"LOOKAHEAD BAN: clean ({len(all_files)} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
