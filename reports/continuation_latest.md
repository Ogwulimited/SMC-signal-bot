# SMC Signal Bot — Continuation Model Backtest

**Generated:** 2026-10-03T11:40:06Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | H1 |
| htf_granularity_sec | 86400 |
| symbols_count | 20 |
| candles_requested | 15000 |
| max_horizon_bars | 48 |
| spread_atr_frac | 0.04 |
| min_cont_fvg_atr | 0.15 |
| cont_liquidity_tol_atr | 2.0 |
| cont_confirmation_wait_bars | 5 |

## Per-Window Results

| Window | Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|--------|---------|---------|------|--------|----------|-----|------------|-------|
| W1 | aggressive | 5 | 3 | 2 | 0 | 60.0% | +0.607 | +3.0 |
| W1 | confirmed | 2 | 1 | 1 | 0 | 50.0% | -0.469 | -0.9 |
| W2 | aggressive | 10 | 5 | 5 | 0 | 50.0% | +0.387 | +3.9 |
| W2 | confirmed | 8 | 6 | 2 | 0 | 75.0% | +0.114 | +0.9 |
| W3 | aggressive | 2 | 2 | 0 | 0 | 100.0% | +2.317 | +4.6 |
| W3 | confirmed | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W4 | aggressive | 2 | 1 | 1 | 0 | 50.0% | +0.244 | +0.5 |
| W4 | confirmed | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |

## Aggregate

| Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|---------|---------|------|--------|----------|-----|------------|-------|
| aggressive | 19 | 11 | 8 | 0 | 57.9% | +0.633 | +12.0 |
| confirmed | 10 | 7 | 3 | 0 | 70.0% | -0.002 | -0.0 |

## Random Baseline

- Signals: 10000
- W/L/T: 1899/8095/6
- WR: 19.0%
- Expectancy: -0.050 R
- Net R: -499.0
