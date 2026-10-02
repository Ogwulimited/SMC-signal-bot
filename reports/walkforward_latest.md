# SMC Signal Bot — Walk-Forward Validation (v2)

**Generated:** 2026-10-02T12:57:48Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | M15 |
| symbols_count | 20 |
| candles_requested | 12000 |
| n_windows | 4 |
| random_trials | 500 |
| max_horizon_bars | 96 |
| max_wait_for_fill_bars | 50 |
| spread_atr_frac | 0.04 |
| min_rr | 1.5 |
| min_ob_width_atr | 0.3 |
| min_target_atr | 1.0 |

## Entry Variant Comparison — Per Window

| Window | Variant | Signals | Skipped | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|--------|---------|---------|---------|------|--------|----------|-----|------------|-------|
| W1 | same_bar | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W1 | next_bar_open | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W1 | next_bar_limit | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W1 | prepositioned_limit | 107 | 111 | 22 | 85 | 0 | 20.6% | -0.213 | -22.8 |
| W1 | prepositioned_limit_confirmed | 50 | 168 | 23 | 27 | 0 | 46.0% | +0.112 | +5.6 |
| W2 | same_bar | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W2 | next_bar_open | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W2 | next_bar_limit | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W2 | prepositioned_limit | 197 | 144 | 65 | 132 | 0 | 33.0% | +0.159 | +31.4 |
| W2 | prepositioned_limit_confirmed | 82 | 259 | 28 | 54 | 0 | 34.1% | -0.467 | -38.3 |
| W3 | same_bar | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W3 | next_bar_open | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W3 | next_bar_limit | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W3 | prepositioned_limit | 172 | 67 | 30 | 142 | 0 | 17.4% | -0.367 | -63.2 |
| W3 | prepositioned_limit_confirmed | 73 | 166 | 11 | 62 | 0 | 15.1% | -0.730 | -53.3 |
| W4 | same_bar | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W4 | next_bar_open | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W4 | next_bar_limit | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| W4 | prepositioned_limit | 159 | 139 | 16 | 143 | 0 | 10.1% | -0.627 | -99.7 |
| W4 | prepositioned_limit_confirmed | 65 | 233 | 8 | 57 | 0 | 12.3% | -0.843 | -54.8 |

## Aggregate Across All Windows

| Variant | Signals | Skipped | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|---------|---------|---------|------|--------|----------|-----|------------|-------|
| same_bar | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| next_bar_open | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| next_bar_limit | 0 | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| prepositioned_limit | 635 | 461 | 133 | 502 | 0 | 20.9% | -0.243 | -154.3 |
| prepositioned_limit_confirmed | 270 | 826 | 70 | 200 | 0 | 25.9% | -0.521 | -140.8 |

## Random Baseline

- **Signals:** 10000
- **Wins / Losses / Timeouts:** 1994 / 8003 / 3
- **Win rate:** 19.9%
- **Expectancy:** -0.003 R
- **Net R:** -27.0

## Interpretation

- `same_bar`: fill on the retrace candle (fantasy benchmark, unrealistic).
- `next_bar_open`: fill at next candle open (chase entry).
- `next_bar_limit`: limit at OB mid, only next candle (chase entry).
- `prepositioned_limit`: signal at BOS, limit at OB mid, wait N bars (realistic SMC entry).
- `prepositioned_limit_confirmed`: same + require confirmation candle after fill.

**Fixed in v2:** BOS signals only fire when the BOS bar is the current bar — no re-emission.
