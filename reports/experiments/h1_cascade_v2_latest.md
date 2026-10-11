# Experiment: H1 Flexible Confluence at RR Thresholds

**Generated:** 2026-10-11T18:09:55Z

## Hypothesis

Filtering flexible-confluence signals by higher R:R thresholds will improve expectancy per trade, at the cost of fewer signals. Find the threshold that maximizes net R.

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles | 2500 |
| warmup_bars | 400 |
| n_windows | 3 |
| rr_thresholds_tested | [1.5, 2.0, 2.5, 3.0] |
| note | Detection run once at MIN_RR=1.5; signals filtered post-hoc by RR. |

## Baseline (v1 — FVG required)

- Signals: 111
- WR: 40.4%
- Expectancy: +0.980 R
- Net R: +108.8

## Flexible Confluence at RR Thresholds

| MIN_RR | Signals | Wins | Losses | WR | Avg R:R (wins) | Expectancy | Net R |
|--------|---------|------|--------|-----|----------------|------------|-------|
| 1.5 | 1311 | 573 | 705 | 44.8% | 2.00 | +0.338 | +443.5 |
| 2.0 | 1240 | 531 | 676 | 44.0% | 2.04 | +0.330 | +408.8 |
| 2.5 | 130 | 13 | 85 | 13.3% | 8.83 | +0.229 | +29.8 |
| 3.0 | 128 | 12 | 84 | 12.5% | 9.37 | +0.222 | +28.4 |

## Per-Window — Best Threshold vs Baseline

**Best threshold by expectancy: MIN_RR = 1.5**

| Window | Base n | Base WR | Base Exp | Best n | Best WR | Best Exp |
|--------|--------|---------|----------|--------|---------|----------|
| W1 | 37 | 45.9% | +0.842 | 423 | 47.1% | +0.375 |
| W2 | 22 | 36.4% | +0.200 | 430 | 48.5% | +0.390 |
| W3 | 52 | 38.0% | +1.409 | 458 | 39.4% | +0.256 |

## Verdict

⚖️ MIN_RR=1.5 keeps WR near baseline (44.8%) while delivering 1311 signals (+1200). Trade-off: more signals, similar quality.
