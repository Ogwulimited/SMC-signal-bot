# SMC Signal Bot — Continuation Backtest (D1+H1 + liquidity)

**Generated:** 2026-10-03T22:24:09Z

## Configuration

| Parameter | Value |
|-----------|-------|
| symbols_count | 25 |
| failed_symbols | 0 |
| stack | D1 bias + H1 OB entry + time-based liquidity |
| detect_window | 1000 |
| candles_per_symbol | 10000 |
| max_horizon_bars | 48 |

## Per-Window Results

| Window | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|--------|---------|------|--------|----------|-----|------------|-------|
| W1 | 6 | 4 | 2 | 0 | 66.7% | +0.928 | +5.6 |
| W2 | 10 | 4 | 6 | 0 | 40.0% | +0.082 | +0.8 |
| W3 | 6 | 4 | 2 | 0 | 66.7% | +0.998 | +6.0 |
| W4 | 14 | 4 | 10 | 0 | 28.6% | -0.101 | -1.4 |

## Aggregate

- Signals: 36
- Wins / Losses / Timeouts: 16 / 20 / 0
- Win rate: 44.4%
- Expectancy: +0.305 R
- Net R: +11.0

## R:R Distribution

| Metric | Value |
|--------|-------|
| Trades | 36 |
| Min R:R | 1.40 |
| 25th pct | 1.54 |
| Median R:R | 1.75 |
| 75th pct | 2.21 |
| Max R:R | 3.26 |
| Mean R:R | 1.94 |

## Winners vs Losers

- Full TP hits: **16**
- Avg R:R on wins: **1.93**
- Best win R:R: 3.26
- Worst win R:R: 1.42
- Losses (all −1.00 R): 20
- Timeouts (0 R): 0

## R:R Buckets

| R:R Range | Trades | Wins | Losses | WR |
|-----------|--------|------|--------|-----|
| 1.5-2.0 | 21 | 10 | 11 | 47.6% |
| 2.0-3.0 | 9 | 3 | 6 | 33.3% |
| 3.0-5.0 | 2 | 1 | 1 | 50.0% |
| 5.0+ | 0 | 0 | 0 | 0.0% |

## Target-Kind Breakdown

How often each liquidity type was the take-profit target.

| Target Kind | Trades | Wins | Losses | WR |
|-------------|--------|------|--------|-----|
| swing_low | 20 | 10 | 10 | 50.0% |
| swing_high | 15 | 5 | 10 | 33.3% |
| synthetic | 1 | 1 | 0 | 100.0% |

## Random Baseline

- Signals: 12500
- WR: 19.7%
- Expectancy: -0.016 R
