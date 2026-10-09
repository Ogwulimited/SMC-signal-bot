# Experiment: M15 OB Refinement

**Generated:** 2026-10-09T12:56:25Z

## Hypothesis

Refining H1 OBs to a tighter M15 OB inside the same zone will improve R:R (tighter stop, same target) without reducing the signal count.

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles_requested | 6000 |
| m15_candles_requested | 24000 |
| m15_displacement_mult | 1.5 |
| m15_ob_tolerance_atr | 0.2 |
| buffer_atr | 0.2 |

## Overall Comparison

| Metric | Baseline (H1 entry) | Refined (M15 or fallback) | M15-only (refined cases) |
|--------|---------------------|---------------------------|---------------------------|
| Signals | 271 | 271 | 35 |
| Wins | 97 | 89 | 10 |
| Losses | 172 | 180 | 25 |
| Timeouts | 2 | 2 | 0 |
| **Win rate** | **36.1%** | **33.1%** | **28.6%** |
| Avg R:R (all) | 3.83 | 4.20 | 6.31 |
| Avg R:R (wins) | 3.20 | 3.56 | 6.06 |
| **Expectancy** | **+0.509 R** | **+0.504 R** | **+1.016 R** |
| Net R | +137.9 | +136.6 | +35.6 |

## Refinement Coverage

- Signals where M15 OB found (refined): **35**
- Signals with no M15 OB (fallback to H1): **236**
- Refinement rate: **12.9%**

## R:R Distribution

| Metric | Baseline | Refined (all) |
|--------|----------|---------------|
| min | 1.42 | 1.42 |
| p25 | 2.34 | 2.52 |
| median | 3.28 | 3.52 |
| p75 | 4.86 | 5.45 |
| max | 11.51 | 16.36 |
| mean | 3.83 | 4.20 |

## Per-Window Breakdown

| Window | Signals | Base WR | Base Exp | Refined WR | Refined Exp |
|--------|---------|---------|----------|------------|-------------|
| W1 | 58 | 32.8% | +0.224 | 25.9% | +0.136 |
| W2 | 101 | 36.0% | +0.491 | 34.0% | +0.480 |
| W3 | 52 | 40.4% | +0.615 | 38.5% | +0.688 |
| W4 | 60 | 35.6% | +0.724 | 33.9% | +0.741 |

## Verdict

❌ Refinement hurts expectancy (-0.005 R). Do not promote.
