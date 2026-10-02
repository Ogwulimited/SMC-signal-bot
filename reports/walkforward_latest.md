# SMC Signal Bot — Walk-Forward Validation

**Generated:** 2026-10-02T08:24:23Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | M15 |
| symbols_count | 20 |
| candles_requested | 12000 |
| warmup_bars | 200 |
| detect_window | 500 |
| n_windows | 4 |
| random_trials | 500 |
| max_horizon_bars | 96 |
| spread_atr_frac | 0.04 |
| min_rr | 1.5 |
| min_ob_width_atr | 0.3 |
| min_target_atr | 1.0 |
| buffer_atr | 0.2 |

## Entry Variant Comparison — Per Window

| Window | Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|--------|---------|---------|------|--------|----------|-----|------------|-------|
| W1 | same_bar | 43 | 28 | 15 | 0 | 65.1% | +1.302 | +56.0 |
| W1 | next_bar_open | 16 | 6 | 10 | 0 | 37.5% | -0.329 | -5.3 |
| W1 | next_bar_limit | 9 | 0 | 9 | 0 | 0.0% | -1.000 | -9.0 |
| W2 | same_bar | 44 | 33 | 11 | 0 | 75.0% | +1.809 | +79.6 |
| W2 | next_bar_open | 19 | 11 | 8 | 0 | 57.9% | -0.087 | -1.7 |
| W2 | next_bar_limit | 4 | 2 | 2 | 0 | 50.0% | +0.291 | +1.2 |
| W3 | same_bar | 51 | 32 | 19 | 0 | 62.7% | +1.052 | +53.7 |
| W3 | next_bar_open | 23 | 7 | 16 | 0 | 30.4% | -0.396 | -9.1 |
| W3 | next_bar_limit | 7 | 0 | 7 | 0 | 0.0% | -1.000 | -7.0 |
| W4 | same_bar | 39 | 24 | 15 | 0 | 61.5% | +1.138 | +44.4 |
| W4 | next_bar_open | 18 | 8 | 10 | 0 | 44.4% | -0.210 | -3.8 |
| W4 | next_bar_limit | 4 | 0 | 4 | 0 | 0.0% | -1.000 | -4.0 |

## Aggregate Across All Windows

| Variant | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|---------|---------|------|--------|----------|-----|------------|-------|
| same_bar | 177 | 117 | 60 | 0 | 66.1% | +1.320 | +233.6 |
| next_bar_open | 76 | 32 | 44 | 0 | 42.1% | -0.261 | -19.8 |
| next_bar_limit | 24 | 2 | 22 | 0 | 8.3% | -0.785 | -18.8 |

## Random Baseline

- **Signals:** 10000
- **Wins / Losses / Timeouts:** 1906 / 8093 / 1
- **Win rate:** 19.1%
- **Expectancy:** -0.047 R
- **Net R:** -469.0

## Interpretation

- `same_bar` = fill on detection candle (best case, unrealistic)
- `next_bar_open` = fill at the open of the next candle (realistic market order)
- `next_bar_limit` = fill only if the next candle reaches OB mid (realistic limit order)

**Decision criteria:**
- If `next_bar_open` and `next_bar_limit` beat the random baseline by a clear margin AND stay positive across all 4 windows → real, tradable edge.
- If they collapse to random levels → the apparent edge was entry-timing bias.
- If `next_bar_limit` holds while `next_bar_open` collapses → the zones are genuinely respected; use limit-order strategy.
