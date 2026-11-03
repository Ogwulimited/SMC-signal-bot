import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_lookahead_ban.py"


def run(folder):
    return subprocess.run([sys.executable, str(SCRIPT), str(folder)],
                          capture_output=True, text=True)


BAD_LINES = [
    "x = df['a'].shift(-1)",
    "x = s.rolling(5, center=True).mean2",
    "x = df.bfill()",
    "x = df.resample('1h', label='right').last()",
    "x = df.iloc[-1]",
    "x = df['a'].max()",
    "x = df['a'].min()",
    "x = df['a'].mean()",
    "x = df['a'].quantile(0.9)",
    "from src.research.tradesim import simulate",
    "from src.research import tradesim",
]


@pytest.mark.parametrize("line", BAD_LINES)
def test_each_banned_pattern_fails_the_build(tmp_path, line):
    (tmp_path / "bad.py").write_text(line + "\n")
    r = run(tmp_path)
    assert r.returncode == 1, r.stdout


def test_clean_code_and_override_pass(tmp_path):
    (tmp_path / "ok.py").write_text(
        "x = max([1, 2])\n"
        "# a comment about shift(-1) is fine\n"
        "y = df['a'].max()  # lookahead-ok: reference table built before the run\n")
    r = run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_engine_folder_is_clean():
    r = run(ROOT / "src" / "research" / "engine")
    print(r.stdout.strip())
    assert r.returncode == 0, r.stdout
