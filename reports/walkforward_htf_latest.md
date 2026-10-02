# SMC Signal Bot — Walk-Forward with HTF Bias Split

**Generated:** 2026-10-02T14:00:41Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | M15 |
| symbols_count | 20 |
| htf_granularity_sec | 14400 |
| htf_swing_lookback | 3 |
| max_wait_for_fill_bars | 50 |
| min_fvg_atr | 0.0 (disabled) |

## Aggregate by HTF Bias Class

`aligned` = LTF signal direction matches HTF trend  |  `counter` = opposite  |  `neutral` = no HTF trend

| Variant | Class | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|---------|-------|---------|------|--------|----------|-----|------------|-------|
| prepositioned_limit | aligned | 68 | 18 | 50 | 0 | 26.5% | -0.002 | -0.2 |
| prepositioned_limit | counter | 84 | 16 | 68 | 0 | 19.0% | -0.322 | -27.1 |
| prepositioned_limit | neutral | 49 | 11 | 38 | 0 | 22.4% | -0.145 | -7.1 |
| prepositioned_limit | ALL | 201 | 45 | 156 | 0 | 22.4% | -0.171 | -34.4 |
| prepositioned_limit_confirmed | aligned | 28 | 11 | 17 | 0 | 39.3% | -0.170 | -4.8 |
| prepositioned_limit_confirmed | counter | 33 | 8 | 25 | 0 | 24.2% | -0.637 | -21.0 |
| prepositioned_limit_confirmed | neutral | 20 | 6 | 14 | 0 | 30.0% | -0.321 | -6.4 |
| prepositioned_limit_confirmed | ALL | 81 | 25 | 56 | 0 | 30.9% | -0.398 | -32.2 |