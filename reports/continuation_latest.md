# SMC Signal Bot — Continuation Backtest (D1+H1 + liquidity)

**Generated:** 2026-10-04T06:30:46Z

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
| W1 | 87 | 29 | 57 | 1 | 33.7% | +0.327 | +28.5 |
| W2 | 112 | 34 | 78 | 0 | 30.4% | +0.176 | +19.7 |
| W3 | 78 | 23 | 54 | 1 | 29.9% | +0.036 | +2.8 |
| W4 | 67 | 19 | 48 | 0 | 28.4% | +0.134 | +9.0 |

## Aggregate

- Signals: 344
- Wins / Losses / Timeouts: 105 / 237 / 2
- Win rate: 30.7%
- Expectancy: +0.174 R
- Net R: +59.9

## R:R Distribution

| Metric | Value |
|--------|-------|
| Trades | 344 |
| Min R:R | 1.42 |
| 25th pct | 2.14 |
| Median R:R | 2.91 |
| 75th pct | 4.39 |
| Max R:R | 10.04 |
| Mean R:R | 3.57 |

## Winners vs Losers

- Full TP hits: **105**
- Avg R:R on wins: **2.83**
- Best win R:R: 7.69
- Worst win R:R: 1.45
- Losses (all −1.00 R): 237
- Timeouts (0 R): 2

## R:R Buckets

| R:R Range | Trades | Wins | Losses | WR |
|-----------|--------|------|--------|-----|
| 1.5-2.0 | 58 | 27 | 31 | 46.6% |
| 2.0-3.0 | 116 | 40 | 76 | 34.5% |
| 3.0-5.0 | 101 | 26 | 75 | 25.7% |
| 5.0+ | 63 | 9 | 52 | 14.8% |

## Target-Kind Breakdown

How often each liquidity type was the take-profit target.

| Target Kind | Trades | Wins | Losses | WR |
|-------------|--------|------|--------|-----|
| weekly_high | 53 | 5 | 48 | 9.4% |
| ny_high | 44 | 11 | 32 | 25.6% |
| ny_low | 42 | 14 | 28 | 33.3% |
| asia_low | 38 | 13 | 25 | 34.2% |
| weekly_low | 34 | 11 | 22 | 33.3% |
| PDL | 32 | 13 | 19 | 40.6% |
| london_low | 26 | 8 | 18 | 30.8% |
| PDH | 25 | 8 | 17 | 32.0% |
| london_high | 24 | 11 | 13 | 45.8% |
| asia_high | 22 | 8 | 14 | 36.4% |
| swing_low | 2 | 1 | 1 | 50.0% |
| swing_high | 1 | 1 | 0 | 100.0% |
| synthetic | 1 | 1 | 0 | 100.0% |

## Random Baseline

- Signals: 12500
- WR: 19.5%
- Expectancy: -0.024 R
