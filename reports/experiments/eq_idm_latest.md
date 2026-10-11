# Experiment: Does IDM Add Value to EQ?

**Generated:** 2026-10-11T20:49:40Z

## Hypothesis

EQ-only was the strongest confluence rule in the prior experiment (45.6% WR, +0.365 R expectancy). This experiment tests whether adding IDM and/or FVG on top of EQ improves it, degrades it, or does nothing.

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles | 2500 |
| warmup_bars | 400 |
| n_windows | 3 |
| min_trades_for_verdict | 30 |

## Rule Definitions

| Rule | Logic |
|------|-------|
| EQ_only | EQH/EQL only (baseline — best from prior experiment) |
| EQ_AND_IDM | EQH/EQL AND inducement sweep |
| EQ_AND_FVG | EQH/EQL AND FVG |
| EQ_AND_IDM_AND_FVG | EQH/EQL AND IDM AND FVG |

## Results by Rule

| Rule | Signals | Wins | Losses | WR | Avg R:R (wins) | Expectancy | Net R |
|------|---------|------|--------|-----|----------------|------------|-------|
| EQ_only | 1208 | 535 | 640 | 45.5% | 2.02 | +0.363 | +438.4 |
| EQ_AND_IDM | 47 | 31 | 16 | 66.0% | 1.90 | +0.915 | +43.0 |
| EQ_AND_FVG | 256 | 91 | 160 | 36.3% | 1.86 | +0.035 | +9.0 |
| EQ_AND_IDM_AND_FVG | 22 | 14 | 8 | 63.6% | 1.91 | +0.849 | +18.7 |

## Deltas vs EQ-only (baseline)

| Rule | Δ Signals | Δ WR (pp) | Δ Expectancy (R) | Δ Net R | Sample OK? |
|------|-----------|-----------|------------------|---------|------------|
| EQ_AND_IDM | -1161 | +20.4 | +0.552 | -395.4 | ✓ |
| EQ_AND_FVG | -952 | -9.3 | -0.328 | -429.4 | ✓ |
| EQ_AND_IDM_AND_FVG | -1186 | +18.1 | +0.486 | -419.7 | ✗ |

**Sample OK** = at least 30 trades (below this, deltas are not statistically meaningful).

## Per-Window Breakdown

| Rule | W1 n | W1 WR | W2 n | W2 WR | W3 n | W3 WR |
|------|------|-------|------|-------|------|-------|
| EQ_only | 383 | 47.8% | 409 | 50.0% | 416 | 39.0% |
| EQ_AND_IDM | 9 | 66.7% | 13 | 61.5% | 25 | 68.0% |
| EQ_AND_FVG | 83 | 32.5% | 64 | 42.2% | 109 | 35.6% |
| EQ_AND_IDM_AND_FVG | 5 | 60.0% | 3 | 66.7% | 14 | 64.3% |

## Verdict

**Baseline (EQ-only):** 1208 signals, 45.5% WR, +0.363 R expectancy

**EQ + IDM:** Improves both WR (+20.4 pp) and expectancy (+0.552 R). **IDM adds value.** Worth considering as a filter if signal count (47) is acceptable.

**EQ + FVG:** Hurts expectancy (-0.328 R). Reject.

## Recommendation

Promote **EQ + IDM** to live. It improves both WR and expectancy with adequate sample.
