# SMC Signal Bot — Walk-Forward Validation

**Generated:** 2026-10-02T09:37:31Z

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
| W1 | same_bar | 43 | 0 | 28 | 15 | 0 | 65.1% | +1.302 | +56.0 |
| W1 | next_bar_open | 16 | 27 | 6 | 10 | 0 | 37.5% | -0.329 | -5.3 |
| W1 | next_bar_limit | 9 | 34 | 0 | 9 | 0 | 0.0% | -1.000 | -9.0 |
| W1 | prepositioned_limit | 5370 | 2468 | 1437 | 3906 | 27 | 26.9% | +0.392 | +2103.3 |
| W1 | prepositioned_limit_confirmed | 2836 | 5002 | 1094 | 1701 | 41 | 39.1% | +0.057 | +161.7 |
| W2 | same_bar | 44 | 0 | 33 | 11 | 0 | 75.0% | +1.809 | +79.6 |
| W2 | next_bar_open | 19 | 25 | 11 | 8 | 0 | 57.9% | -0.087 | -1.7 |
| W2 | next_bar_limit | 4 | 40 | 2 | 2 | 0 | 50.0% | +0.291 | +1.2 |
| W2 | prepositioned_limit | 5538 | 2661 | 1487 | 4014 | 37 | 27.0% | +0.513 | +2843.4 |
| W2 | prepositioned_limit_confirmed | 2660 | 5539 | 1114 | 1516 | 30 | 42.4% | +0.098 | +260.3 |
| W3 | same_bar | 51 | 0 | 32 | 19 | 0 | 62.7% | +1.052 | +53.7 |
| W3 | next_bar_open | 23 | 28 | 7 | 16 | 0 | 30.4% | -0.396 | -9.1 |
| W3 | next_bar_limit | 7 | 44 | 0 | 7 | 0 | 0.0% | -1.000 | -7.0 |
| W3 | prepositioned_limit | 5743 | 1919 | 1457 | 4224 | 62 | 25.6% | +0.285 | +1636.8 |
| W3 | prepositioned_limit_confirmed | 2943 | 4719 | 1161 | 1724 | 58 | 40.2% | +0.076 | +225.1 |
| W4 | same_bar | 40 | 0 | 25 | 15 | 0 | 62.5% | +1.223 | +48.9 |
| W4 | next_bar_open | 19 | 21 | 9 | 10 | 0 | 47.4% | -0.140 | -2.7 |
| W4 | next_bar_limit | 4 | 36 | 0 | 4 | 0 | 0.0% | -1.000 | -4.0 |
| W4 | prepositioned_limit | 5951 | 2836 | 1374 | 4514 | 63 | 23.3% | +0.239 | +1420.1 |
| W4 | prepositioned_limit_confirmed | 3230 | 5557 | 1252 | 1931 | 47 | 39.3% | -0.037 | -120.4 |

## Aggregate Across All Windows

| Variant | Signals | Skipped | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|---------|---------|---------|------|--------|----------|-----|------------|-------|
| same_bar | 178 | 0 | 118 | 60 | 0 | 66.3% | +1.338 | +238.2 |
| next_bar_open | 77 | 101 | 33 | 44 | 0 | 42.9% | -0.243 | -18.7 |
| next_bar_limit | 24 | 154 | 2 | 22 | 0 | 8.3% | -0.785 | -18.8 |
| prepositioned_limit | 22602 | 9884 | 5755 | 16658 | 189 | 25.7% | +0.354 | +8003.5 |
| prepositioned_limit_confirmed | 11669 | 20817 | 4621 | 6872 | 176 | 40.2% | +0.045 | +526.6 |

## Random Baseline

- **Signals:** 10000
- **Wins / Losses / Timeouts:** 2025 / 7974 / 1
- **Win rate:** 20.3%
- **Expectancy:** +0.013 R
- **Net R:** +126.0

## Interpretation

- `same_bar`, `next_bar_open`, `next_bar_limit` = signal fires at retrace, enter immediately or next bar.
- `prepositioned_limit` = signal fires at BOS, limit at OB mid, wait up to N bars for retrace fill.
- `prepositioned_limit_confirmed` = same + require a direction-confirming candle after fill.

**Decision criteria:**
- If prepositioned variants beat random baseline with positive expectancy → zones are genuinely respected → real edge.
- If all variants lose to random baseline → base pattern has no edge as defined → pivot to adding FVG / session / HTF bias as core filters.