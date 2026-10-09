# Experiment: Inducement (IDM) Sweep Filter

**Generated:** 2026-10-09T21:31:03Z

## Hypothesis

Requiring a minor liquidity pool to be swept between the BOS and the OB touch will improve WR and expectancy at the cost of fewer signals.

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles_requested | 6000 |
| max_sweep_age_bars | 30 |
| swing_lookback | 2 |

## Overall Comparison

| Metric | Baseline (all signals) | IDM-swept only | No IDM (rejected) |
|--------|------------------------|----------------|--------------------|
| Signals | 275 | 45 | 230 |
| Wins | 97 | 14 | 83 |
| Losses | 176 | 30 | 146 |
| Timeouts | 2 | 1 | 1 |
| **Win rate** | **35.5%** | **31.8%** | **36.2%** |
| Avg R:R (wins) | 3.19 | 3.53 | 3.14 |
| **Expectancy** | **+0.487 R** | **+0.431 R** | **+0.498 R** |
| Net R | +133.8 | +19.4 | +114.4 |

## IDM Coverage

- Signals with swept IDM: **45** (16.4%)
- Signals without swept IDM: **230**

## R:R Distribution

| Metric | Baseline | IDM-filtered |
|--------|----------|--------------|
| min | 1.42 | 1.48 |
| p25 | 2.34 | 2.65 |
| median | 3.28 | 3.68 |
| p75 | 4.86 | 5.25 |
| max | 11.51 | 10.04 |
| mean | 3.82 | 4.23 |

## Per-Window Breakdown

| Window | Signals | Base WR | Base Exp | IDM WR | IDM Exp |
|--------|---------|---------|----------|--------|---------|
| W1 | 59 | 32.2% | +0.203 | 10.0% | -0.635 |
| W2 | 104 | 35.0% | +0.448 | 28.6% | +0.077 |
| W3 | 52 | 42.3% | +0.692 | 42.9% | +0.604 |
| W4 | 60 | 33.9% | +0.656 | 46.2% | +1.461 |

## Verdict

❌ IDM filter hurts expectancy (-0.055 R). Reject.
