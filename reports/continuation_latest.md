# SMC Signal Bot — Continuation Backtest (D1+H1 + liquidity)

**Generated:** 2026-10-04T07:09:55Z

## Configuration

| Parameter | Value |
|-----------|-------|
| symbols_count | 31 |
| failed_symbols | 0 |
| stack | D1 bias + H1 OB entry + time-based liquidity |
| detect_window | 1000 |
| candles_per_symbol | 10000 |
| max_horizon_bars | 48 |

## Per-Window Results

| Window | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|--------|---------|------|--------|----------|-----|------------|-------|
| W1 | 94 | 29 | 65 | 0 | 30.9% | +0.250 | +23.5 |
| W2 | 133 | 43 | 90 | 0 | 32.3% | +0.243 | +32.3 |
| W3 | 99 | 31 | 67 | 1 | 31.6% | +0.150 | +14.9 |
| W4 | 89 | 28 | 60 | 1 | 31.8% | +0.513 | +45.7 |

## Aggregate

- Signals: 415
- Wins / Losses / Timeouts: 131 / 282 / 2
- Win rate: 31.7%
- Expectancy: +0.281 R
- Net R: +116.4

## R:R Distribution

| Metric | Value |
|--------|-------|
| Trades | 415 |
| Min R:R | 1.42 |
| 25th pct | 2.25 |
| Median R:R | 3.10 |
| 75th pct | 4.77 |
| Max R:R | 11.51 |
| Mean R:R | 3.72 |

## Winners vs Losers

- Full TP hits: **131**
- Avg R:R on wins: **3.04**
- Best win R:R: 10.02
- Worst win R:R: 1.45
- Losses (all −1.00 R): 282
- Timeouts (0 R): 2

## R:R Buckets

| R:R Range | Trades | Wins | Losses | WR |
|-----------|--------|------|--------|-----|
| 1.5-2.0 | 68 | 34 | 34 | 50.0% |
| 2.0-3.0 | 122 | 41 | 81 | 33.6% |
| 3.0-5.0 | 132 | 39 | 93 | 29.5% |
| 5.0+ | 86 | 14 | 70 | 16.7% |

## Target-Kind Breakdown

How often each liquidity type was the take-profit target.

| Target Kind | Trades | Wins | Losses | WR |
|-------------|--------|------|--------|-----|
| weekly_high | 74 | 12 | 62 | 16.2% |
| weekly_low | 51 | 15 | 35 | 30.0% |
| ny_high | 50 | 10 | 39 | 20.4% |
| ny_low | 47 | 17 | 30 | 36.2% |
| asia_low | 45 | 20 | 25 | 44.4% |
| asia_high | 32 | 14 | 18 | 43.8% |
| london_high | 31 | 11 | 20 | 35.5% |
| PDH | 27 | 12 | 15 | 44.4% |
| PDL | 26 | 10 | 16 | 38.5% |
| london_low | 24 | 6 | 18 | 25.0% |
| swing_high | 4 | 2 | 2 | 50.0% |
| swing_low | 3 | 1 | 2 | 33.3% |
| synthetic | 1 | 1 | 0 | 100.0% |

## Random Baseline

- Signals: 15500
- WR: 19.1%
- Expectancy: -0.047 R
