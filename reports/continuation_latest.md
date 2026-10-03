# SMC Signal Bot — Continuation Model Backtest (D1+H4+H1)

**Generated:** 2026-10-03T21:29:17Z

## Configuration

| Parameter | Value |
|-----------|-------|
| symbols_count | 25 |
| failed_symbols | 0 |
| stack | D1 bias + H4 alignment + H1 OB entry |
| detect_window | 1000 |
| candles_per_symbol | 10000 |
| max_horizon_bars | 48 |

## Per-Window Results

| Window | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|--------|---------|------|--------|----------|-----|------------|-------|
| W1 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W2 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W3 | 4 | 2 | 2 | 0 | 50.0% | +0.578 | +2.3 |
| W4 | 11 | 3 | 8 | 0 | 27.3% | -0.155 | -1.7 |

## Aggregate

- Signals: 15
- Wins / Losses / Timeouts: 5 / 10 / 0
- Win rate: 33.3%
- Expectancy: +0.041 R
- Net R: +0.6

## R:R Distribution (all trades)

| Metric | Value |
|--------|-------|
| Trades | 15 |
| Min R:R | 1.42 |
| 25th pct | 1.54 |
| Median R:R | 1.75 |
| 75th pct | 2.21 |
| Max R:R | 3.59 |
| Mean R:R | 2.05 |

## Winners vs Losers

- Full TP hits: **5**
- Avg R:R on wins: **2.12**
- Best win R:R: 3.26
- Worst win R:R: 1.42
- Losses (all −1.00 R): 10
- Timeouts (0 R): 0

## R:R Buckets

| R:R Range | Trades | Wins | Losses | WR |
|-----------|--------|------|--------|-----|
| 1.5-2.0 | 7 | 1 | 6 | 14.3% |
| 2.0-3.0 | 3 | 1 | 2 | 33.3% |
| 3.0-5.0 | 2 | 1 | 1 | 50.0% |
| 5.0+ | 0 | 0 | 0 | 0.0% |

## Random Baseline

- Signals: 12500
- WR: 19.7%
- Expectancy: -0.014 R
