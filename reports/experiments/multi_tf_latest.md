# Experiment: Multi-TF Cascade + Flexible Confluence (v3, small sample)

**Generated:** 2026-10-11T14:35:36Z

> **Note:** reduced sample (1200 H1 bars, 3 windows, sampled v3). Directional signal only — not a full statistical result.

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles | 1200 |
| m15_candles | 5000 |
| warmup_bars | 300 |
| n_windows | 3 |
| v3_sample_every | 2 |

## Overall Comparison

| Metric | Baseline (v1) | v3 (multi-TF + flex confl) |
|--------|---------------|-----------------------------|
| Signals | 56 | 568 |
| Wins | 20 | 197 |
| Losses | 34 | 367 |
| Timeouts | 2 | 4 |
| **Win rate** | **37.0%** | **34.9%** |
| Avg R:R (wins) | 5.30 | 2.36 |
| Avg R:R (all) | 4.39 | 4.60 |
| **Expectancy** | **+1.286 R** | **+0.173 R** |
| Net R | +72.0 | +98.1 |

## v3 — Confluence-Type Breakdown

| Confluence | Trades | Wins | Losses | WR |
|------------|--------|------|--------|-----|
| EQH/EQL | 528 | 185 | 339 | 35.3% |
| TIME_LIQ | 292 | 124 | 165 | 42.9% |
| FVG | 108 | 33 | 75 | 30.6% |
| IDM | 33 | 11 | 22 | 33.3% |

## v3 — Entry Timeframe Breakdown

| TF | Trades | Wins | Losses | WR |
|----|--------|------|--------|-----|
| H1 | 266 | 114 | 150 | 43.2% |
| M15 | 302 | 83 | 217 | 27.7% |

## Per-Window Breakdown

| Window | Base n | Base WR | Base Exp | v3 n | v3 WR | v3 Exp |
|--------|--------|---------|----------|------|-------|--------|
| W1 | 9 | 11.1% | -0.693 | 201 | 34.7% | +0.171 |
| W2 | 25 | 44.0% | +2.304 | 182 | 32.2% | +0.003 |
| W3 | 22 | 40.0% | +0.939 | 185 | 37.8% | +0.342 |

## Verdict

❌ v3 hurts expectancy (-1.113 R).
