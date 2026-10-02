# SMC Signal Bot — Walk-Forward Validation (v2)

**Generated:** 2026-10-02T10:16:05Z

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
| W1 | same_bar | 165 | 0 | 109 | 56 | 0 | 66.1% | +1.334 | +220.1 |
| W1 | next_bar_open | 58 | 107 | 26 | 32 | 0 | 44.8% | -0.206 | -11.9 |
| W1 | next_bar_limit | 30 | 135 | 0 | 30 | 0 | 0.0% | -1.000 | -30.0 |
| W1 | prepositioned_limit | 280 | 221 | 66 | 214 | 0 | 23.6% | -0.211 | -59.0 |
| W1 | prepositioned_limit_confirmed | 109 | 392 | 46 | 63 | 0 | 42.2% | -0.079 | -8.7 |
| W2 | same_bar | 179 | 0 | 122 | 57 | 0 | 68.2% | +1.748 | +312.9 |
| W2 | next_bar_open | 94 | 85 | 54 | 40 | 0 | 57.4% | -0.177 | -16.6 |
| W2 | next_bar_limit | 9 | 170 | 3 | 6 | 0 | 33.3% | -0.132 | -1.2 |
| W2 | prepositioned_limit | 493 | 206 | 117 | 376 | 0 | 23.7% | -0.148 | -72.9 |
| W2 | prepositioned_limit_confirmed | 200 | 499 | 60 | 140 | 0 | 30.0% | -0.416 | -83.1 |
| W3 | same_bar | 191 | 0 | 117 | 74 | 0 | 61.3% | +1.037 | +198.0 |
| W3 | next_bar_open | 100 | 91 | 31 | 69 | 0 | 31.0% | -0.407 | -40.7 |
| W3 | next_bar_limit | 21 | 170 | 0 | 21 | 0 | 0.0% | -1.000 | -21.0 |
| W3 | prepositioned_limit | 439 | 132 | 97 | 342 | 0 | 22.1% | -0.068 | -30.0 |
| W3 | prepositioned_limit_confirmed | 192 | 379 | 58 | 134 | 0 | 30.2% | -0.377 | -72.4 |
| W4 | same_bar | 161 | 0 | 97 | 64 | 0 | 60.2% | +1.034 | +166.4 |
| W4 | next_bar_open | 77 | 84 | 32 | 45 | 0 | 41.6% | -0.304 | -23.4 |
| W4 | next_bar_limit | 15 | 146 | 0 | 15 | 0 | 0.0% | -1.000 | -15.0 |
| W4 | prepositioned_limit | 436 | 208 | 92 | 342 | 2 | 21.2% | -0.156 | -67.8 |
| W4 | prepositioned_limit_confirmed | 187 | 457 | 55 | 130 | 2 | 29.7% | -0.347 | -64.9 |

## Aggregate Across All Windows

| Variant | Signals | Skipped | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|---------|---------|---------|------|--------|----------|-----|------------|-------|
| same_bar | 696 | 0 | 445 | 251 | 0 | 63.9% | +1.289 | +897.5 |
| next_bar_open | 329 | 367 | 143 | 186 | 0 | 43.5% | -0.282 | -92.7 |
| next_bar_limit | 75 | 621 | 3 | 72 | 0 | 4.0% | -0.896 | -67.2 |
| prepositioned_limit | 1648 | 767 | 372 | 1274 | 2 | 22.6% | -0.139 | -229.6 |
| prepositioned_limit_confirmed | 688 | 1727 | 219 | 467 | 2 | 31.9% | -0.333 | -229.1 |

## Random Baseline

- **Signals:** 10000
- **Wins / Losses / Timeouts:** 2009 / 7990 / 1
- **Win rate:** 20.1%
- **Expectancy:** +0.005 R
- **Net R:** +46.0

## Interpretation

- `same_bar`: fill on the retrace candle (fantasy benchmark, unrealistic).
- `next_bar_open`: fill at next candle open (chase entry).
- `next_bar_limit`: limit at OB mid, only next candle (chase entry).
- `prepositioned_limit`: signal at BOS, limit at OB mid, wait N bars (realistic SMC entry).
- `prepositioned_limit_confirmed`: same + require confirmation candle after fill.

**Fixed in v2:** BOS signals only fire when the BOS bar is the current bar — no re-emission.
