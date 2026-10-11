# Experiment: H1-Only Flexible Confluence Cascade

**Generated:** 2026-10-11T17:13:17Z

## Hypothesis

Relaxing the confluence requirement on H1 from 'must have FVG' to 'any one of {FVG, EQH/EQL, IDM, time-based liq}' will add signals without hurting WR — as long as we stay on H1 (no M15 cascade).

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles | 2500 |
| warmup_bars | 400 |
| n_windows | 3 |
| note | H1-only, no M15 fetch, flexible confluence |

## Overall Comparison

| Metric | Baseline (v1) | H1 flexible confluence |
|--------|---------------|------------------------|
| Signals | 111 | 1311 |
| Wins | 44 | 573 |
| Losses | 65 | 705 |
| Timeouts | 2 | 33 |
| **Win rate** | **40.4%** | **44.8%** |
| Avg R:R (wins) | 3.95 | 2.00 |
| Avg R:R (all) | 3.93 | 3.09 |
| **Expectancy** | **+0.980 R** | **+0.339 R** |
| Net R | +108.8 | +443.8 |

## R:R Distribution

| Metric | Baseline | Flexible |
|--------|----------|----------|
| min | 1.48 | 1.36 |
| p25 | 2.46 | 1.84 |
| median | 3.53 | 1.87 |
| p75 | 4.43 | 1.91 |
| max | 11.51 | 41.95 |
| mean | 3.93 | 3.09 |

## Flexible Confluence-Type Breakdown

(A trade can have multiple confluences; counts can exceed signal count.)

| Confluence | Trades | Wins | Losses | WR |
|------------|--------|------|--------|-----|
| EQH/EQL | 1208 | 536 | 639 | 45.6% |
| TIME_LIQ | 857 | 372 | 475 | 43.9% |
| FVG | 300 | 106 | 189 | 35.9% |
| IDM | 61 | 36 | 25 | 59.0% |

## Per-Window Breakdown

| Window | Base n | Base WR | Base Exp | New n | New WR | New Exp |
|--------|--------|---------|----------|-------|--------|---------|
| W1 | 37 | 45.9% | +0.842 | 423 | 47.1% | +0.375 |
| W2 | 22 | 36.4% | +0.200 | 430 | 48.5% | +0.390 |
| W3 | 52 | 38.0% | +1.409 | 458 | 39.4% | +0.257 |

## Verdict

❌ Flexible confluence hurts expectancy (-0.642 R). Reject.
