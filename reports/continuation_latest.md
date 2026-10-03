# SMC Signal Bot — Continuation Model Backtest

**Generated:** 2026-10-03T08:13:19Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | H1 |
| htf_granularity_sec | 86400 |
| symbols_count | 20 |
| candles_requested | 8000 |
| max_horizon_bars | 48 |
| spread_atr_frac | 0.04 |
| min_cont_fvg_atr | 0.15 |
| cont_liquidity_tol_atr | 2.0 |
| cont_confirmation_wait_bars | 5 |

## Per-Window Results

| Window | Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|--------|---------|---------|------|--------|----------|-----|------------|-------|
| W1 | aggressive | 4 | 3 | 1 | 0 | 75.0% | +1.041 | +4.2 |
| W1 | confirmed | 3 | 2 | 1 | 0 | 66.7% | -0.165 | -0.5 |
| W2 | aggressive | 9 | 4 | 5 | 0 | 44.4% | +0.211 | +1.9 |
| W2 | confirmed | 7 | 5 | 2 | 0 | 71.4% | +0.068 | +0.5 |
| W3 | aggressive | 2 | 2 | 0 | 0 | 100.0% | +2.317 | +4.6 |
| W3 | confirmed | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W4 | aggressive | 3 | 2 | 1 | 0 | 66.7% | +0.863 | +2.6 |
| W4 | confirmed | 1 | 1 | 0 | 0 | 100.0% | +0.446 | +0.4 |

## Aggregate

| Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|---------|---------|------|--------|----------|-----|------------|-------|
| aggressive | 18 | 11 | 7 | 0 | 61.1% | +0.738 | +13.3 |
| confirmed | 11 | 8 | 3 | 0 | 72.7% | +0.039 | +0.4 |

## Random Baseline

- Signals: 10000
- W/L/T: 1928/8062/10
- WR: 19.3%
- Expectancy: -0.035 R
- Net R: -350.0
