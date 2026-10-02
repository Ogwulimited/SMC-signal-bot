# SMC Signal Bot — Walk-Forward with HTF Bias Split

**Generated:** 2026-10-02T14:42:38Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | H1 |
| symbols_count | 20 |
| htf_granularity_sec | 86400 |
| htf_swing_lookback | 3 |
| max_wait_for_fill_bars | 30 |
| min_fvg_atr | 0.0 (disabled) |

## Aggregate by HTF Bias Class

`aligned` = LTF signal direction matches HTF trend  |  `counter` = opposite  |  `neutral` = no HTF trend

| Variant | Class | Signals | Wins | Losses | Timeouts | WR | Expectancy | Net R |
|---------|-------|---------|------|--------|----------|-----|------------|-------|
| prepositioned_limit | aligned | 119 | 25 | 94 | 0 | 21.0% | -0.196 | -23.3 |
| prepositioned_limit | counter | 116 | 36 | 79 | 1 | 31.3% | +0.182 | +21.2 |
| prepositioned_limit | neutral | 1 | 0 | 1 | 0 | 0.0% | -1.000 | -1.0 |
| prepositioned_limit | ALL | 236 | 61 | 174 | 1 | 26.0% | -0.013 | -3.1 |
| prepositioned_limit_confirmed | aligned | 52 | 18 | 34 | 0 | 34.6% | -0.273 | -14.2 |
| prepositioned_limit_confirmed | counter | 52 | 22 | 30 | 0 | 42.3% | -0.066 | -3.4 |
| prepositioned_limit_confirmed | neutral | 0 | 0 | 0 | 0 | 0.0% | +0.000 | +0.0 |
| prepositioned_limit_confirmed | ALL | 104 | 40 | 64 | 0 | 38.5% | -0.170 | -17.6 |