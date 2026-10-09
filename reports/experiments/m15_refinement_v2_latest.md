# Experiment: M15 OB Refinement

**Generated:** 2026-10-09T20:46:25Z

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
| Signals | 272 | 272 | 102 |
| Wins | 97 | 84 | 24 |
| Losses | 173 | 186 | 78 |
| Timeouts | 2 | 2 | 0 |
| **Win rate** | **35.9%** | **31.1%** | **23.5%** |
| Avg R:R (all) | 3.83 | 4.93 | 6.80 |
| Avg R:R (wins) | 3.19 | 3.96 | 5.62 |
| **Expectancy** | **+0.503 R** | **+0.538 R** | **+0.558 R** |
| Net R | +136.9 | +146.2 | +56.9 |

## Refinement Coverage

- Signals where M15 OB found (refined): **102**
- Signals with no M15 OB (fallback to H1): **170**
- Refinement rate: **37.5%**

## R:R Distribution

| Metric | Baseline | Refined (all) |
|--------|----------|---------------|
| min | 1.42 | 1.42 |
| p25 | 2.34 | 2.67 |
| median | 3.27 | 3.78 |
| p75 | 4.88 | 6.29 |
| max | 11.51 | 22.84 |
| mean | 3.83 | 4.93 |

## Per-Window Breakdown

| Window | Signals | Base WR | Base Exp | Refined WR | Refined Exp |
|--------|---------|---------|----------|------------|-------------|
| W1 | 59 | 32.2% | +0.203 | 25.4% | +0.184 |
| W2 | 102 | 35.6% | +0.476 | 32.7% | +0.558 |
| W3 | 51 | 43.1% | +0.725 | 37.3% | +0.941 |
| W4 | 60 | 33.9% | +0.656 | 28.8% | +0.507 |

## Verdict

⚖️ Marginal improvement (+0.034 R). Not enough to justify the added complexity yet.
