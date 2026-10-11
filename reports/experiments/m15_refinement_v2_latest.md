# Experiment: M15 OB Refinement

**Generated:** 2026-10-11T07:02:58Z

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
| Signals | 275 | 275 | 103 |
| Wins | 97 | 84 | 24 |
| Losses | 176 | 189 | 79 |
| Timeouts | 2 | 2 | 0 |
| **Win rate** | **35.5%** | **30.8%** | **23.3%** |
| Avg R:R (all) | 3.82 | 4.93 | 6.81 |
| Avg R:R (wins) | 3.19 | 3.95 | 5.62 |
| **Expectancy** | **+0.487 R** | **+0.521 R** | **+0.543 R** |
| Net R | +133.8 | +143.2 | +55.9 |

## Refinement Coverage

- Signals where M15 OB found (refined): **103**
- Signals with no M15 OB (fallback to H1): **172**
- Refinement rate: **37.5%**

## R:R Distribution

| Metric | Baseline | Refined (all) |
|--------|----------|---------------|
| min | 1.42 | 1.42 |
| p25 | 2.34 | 2.67 |
| median | 3.28 | 3.78 |
| p75 | 4.86 | 6.29 |
| max | 11.51 | 22.84 |
| mean | 3.82 | 4.93 |

## Per-Window Breakdown

| Window | Signals | Base WR | Base Exp | Refined WR | Refined Exp |
|--------|---------|---------|----------|------------|-------------|
| W1 | 60 | 33.3% | +0.232 | 26.7% | +0.245 |
| W2 | 103 | 34.3% | +0.433 | 31.4% | +0.496 |
| W3 | 52 | 42.3% | +0.692 | 36.5% | +0.903 |
| W4 | 60 | 33.9% | +0.656 | 28.8% | +0.507 |

## Verdict

⚖️ Marginal improvement (+0.034 R). Not enough to justify the added complexity yet.
