"""Test tools for the lookahead guard: synthetic data, poison test.

POISON TEST: for random cut times t, keep every bar that closed by t, replace
all later bars with random noise, rerun the pipeline. Every decision with a
time <= t must be identical to the real run. Only decisions are compared,
never exits.
"""
import time as _time
from dataclasses import dataclass

import numpy as np
import pandas as pd


def make_synthetic_m15(weeks=10, seed=1, start="2021-01-04"):
    """Fake M15 data: weekends closed, random single-bar holes, one longer hole.
    Starts on a Monday; 11+ weeks cross the US daylight-saving change."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=weeks * 7 * 96, freq="15min", tz="UTC")
    dow = idx.dayofweek.to_numpy()
    hour = idx.hour.to_numpy()
    market_open = ~((dow == 5) | ((dow == 4) & (hour >= 22)) | ((dow == 6) & (hour < 22)))
    keep = market_open.copy()
    keep &= rng.random(len(idx)) > 0.01
    s = int(rng.integers(len(idx) // 4, len(idx) // 2))
    keep[s:s + 150] = False
    idx = idx[keep]
    m = len(idx)
    close = 1.10 + np.cumsum(rng.normal(0, 0.0004, m))
    open_ = np.concatenate([[1.10], close[:-1]])
    high = np.maximum(open_, close) + np.abs(rng.normal(0, 0.0002, m))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, 0.0002, m))
    return pd.DataFrame({"timestamp": idx, "open": open_, "high": high,
                         "low": low, "close": close})


def make_poisoned(m15, p, rng):
    """Keep bars 0..p, replace bars p+1.. with random noise (same timestamps)."""
    out = m15.reset_index(drop=True).copy()
    k = len(out) - (p + 1)
    if k <= 0:
        return out
    hi = out["high"].to_numpy()
    lo = out["low"].to_numpy()
    cl = out["close"].to_numpy()
    scale = float(np.median(hi[:p + 1] - lo[:p + 1]))
    new_close = cl[p] + np.cumsum(rng.normal(0, 6 * scale, k))
    new_open = np.concatenate([[cl[p]], new_close[:-1]])
    new_high = np.maximum(new_open, new_close) + np.abs(rng.normal(0, 3 * scale, k))
    new_low = np.minimum(new_open, new_close) - np.abs(rng.normal(0, 3 * scale, k))
    for col, arr in (("open", new_open), ("high", new_high),
                     ("low", new_low), ("close", new_close)):
        full = out[col].to_numpy().copy()
        full[p + 1:] = arr
        out[col] = full
    return out


@dataclass
class PoisonResult:
    n_cuts: int
    mismatches: int
    decisions_compared: int
    first_mismatch: object
    seconds: float


def poison_test(run_fn, m15, n_cuts=100, seed=0, warmup=400):
    """run_fn(m15_frame) -> list of Decision. Returns a PoisonResult."""
    t0 = _time.perf_counter()
    m15 = m15.reset_index(drop=True)
    base = run_fn(m15)
    rng = np.random.default_rng(seed)
    last_p = len(m15) - 2
    pool = np.arange(warmup, last_p)
    cuts = sorted(rng.choice(pool, size=min(n_cuts, len(pool)), replace=False).tolist())
    close_times = m15["timestamp"] + pd.Timedelta(minutes=15)
    mismatches = 0
    compared = 0
    first = None
    for p in cuts:
        t = close_times.iloc[p]
        got = run_fn(make_poisoned(m15, p, rng))
        a = [d.key() for d in base if d.time <= t]
        b = [d.key() for d in got if d.time <= t]
        compared += len(a)
        if a != b:
            mismatches += 1
            if first is None:
                j = 0
                while j < min(len(a), len(b)) and a[j] == b[j]:
                    j += 1
                first = f"cut {t}: real run {len(a)} decisions, poisoned run {len(b)}, first difference at #{j}"
    return PoisonResult(len(cuts), mismatches, compared, first,
                        _time.perf_counter() - t0)


def format_result(label, res):
    status = "PASS" if res.mismatches == 0 else "FAIL"
    return (f"{label}: {res.mismatches} of {res.n_cuts} cut times differ "
            f"({res.decisions_compared} decisions compared, {res.seconds:.1f}s) -> {status}")
