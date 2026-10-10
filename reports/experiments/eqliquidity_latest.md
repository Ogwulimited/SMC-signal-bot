# Experiment: EQH/EQL as Preferred Targets

**Generated:** 2026-10-10T22:18:21Z

## Hypothesis

Treating equal highs (EQH) and equal lows (EQL) as preferred targets — alongside time-based pools — will improve expectancy, since these levels are highly visible to retail traders and attract clustered stops.

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles_requested | 6000 |
| prefer_major_liq_atr | 5.0 |

## Overall Comparison

| Metric | Baseline (time-based preferred) | v2 (EQH/EQL added) |
|--------|---------------------------------|---------------------|
| Signals | 275 | 98 |
| Wins | 97 | 37 |
| Losses | 176 | 61 |
| Timeouts | 2 | 0 |
| **Win rate** | **35.5%** | **37.8%** |
| Avg R:R (wins) | 3.19 | 2.86 |
| Avg R:R (all) | 3.82 | 3.02 |
| **Expectancy** | **+0.487 R** | **+0.458 R** |
| Net R | +133.8 | +44.9 |

## R:R Distribution

| Metric | Baseline | v2 |
|--------|----------|-----|
| min | 1.42 | 1.42 |
| p25 | 2.34 | 2.06 |
| median | 3.28 | 2.46 |
| p75 | 4.86 | 3.18 |
| max | 11.51 | 8.45 |
| mean | 3.82 | 3.02 |

## Target-Kind Breakdown — Baseline

| Kind | Trades | Wins | Losses | WR |
|------|--------|------|--------|-----|
| weekly_high | 44 | 9 | 35 | 20.5% |
| weekly_low | 39 | 12 | 26 | 31.6% |
| ny_high | 36 | 10 | 25 | 28.6% |
| asia_low | 29 | 16 | 13 | 55.2% |
| ny_low | 27 | 10 | 17 | 37.0% |
| asia_high | 25 | 11 | 14 | 44.0% |
| london_high | 22 | 7 | 15 | 31.8% |
| PDL | 18 | 7 | 11 | 38.9% |
| PDH | 18 | 8 | 10 | 44.4% |
| london_low | 13 | 4 | 9 | 30.8% |
| swing_low | 2 | 1 | 1 | 50.0% |
| synthetic | 1 | 1 | 0 | 100.0% |
| swing_high | 1 | 1 | 0 | 100.0% |

## Target-Kind Breakdown — v2

| Kind | Trades | Wins | Losses | WR |
|------|--------|------|--------|-----|
| EQH | 28 | 4 | 24 | 14.3% |
| EQL | 20 | 11 | 9 | 55.0% |
| asia_low | 9 | 5 | 4 | 55.6% |
| PDH | 8 | 5 | 3 | 62.5% |
| weekly_high | 6 | 2 | 4 | 33.3% |
| london_high | 6 | 2 | 4 | 33.3% |
| PDL | 5 | 2 | 3 | 40.0% |
| asia_high | 4 | 2 | 2 | 50.0% |
| ny_high | 3 | 0 | 3 | 0.0% |
| weekly_low | 3 | 1 | 2 | 33.3% |
| ny_low | 2 | 1 | 1 | 50.0% |
| swing_low | 1 | 0 | 1 | 0.0% |
| london_low | 1 | 0 | 1 | 0.0% |
| synthetic | 1 | 1 | 0 | 100.0% |
| swing_high | 1 | 1 | 0 | 100.0% |

## Per-Window Breakdown

| Window | Signals | Base WR | Base Exp | v2 WR | v2 Exp |
|--------|---------|---------|----------|-------|--------|
| W1 | 60 | 33.3% | +0.232 | 20.0% | -0.372 |
| W2 | 103 | 34.3% | +0.433 | 40.0% | +0.279 |
| W3 | 52 | 42.3% | +0.692 | 52.6% | +1.252 |
| W4 | 60 | 33.9% | +0.656 | 37.5% | +0.784 |

## Verdict

❌ v2 hurts expectancy (-0.028 R). Reject. Keep time-based pools as preferred targets.
