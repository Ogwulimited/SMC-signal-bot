# SMC Signal Bot — Backtest Report

**Generated:** 2026-10-01T02:01:07Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | M15 |
| granularity_sec | 900 |
| candles_requested | 5000 |
| warmup_bars | 100 |
| max_horizon_bars | 96 |
| swing_lookback | 2 |
| atr_period | 14 |
| eq_tolerance_atr | 0.15 |
| displacement_atr_mult | 1.5 |
| min_rr | 1.5 |
| min_sweep_penetration_atr | 0.2 |
| max_bars_sweep_to_entry | 80 |
| max_ob_age_bars | 80 |

## Frequency & Setup Quality

| Symbol | Candles | Signals | Bull | Bear | Avg R:R | Span (days) | Signals/Month | Signals/Week |
|--------|---------|---------|------|------|---------|-------------|---------------|--------------|
| frxEURUSD | 5000 | 6 | 4 | 2 | 1:3.11 | 72.28 | 2.5 | 0.6 |
| frxGBPUSD | 5000 | 10 | 8 | 2 | 1:2.02 | 72.28 | 4.2 | 1.0 |
| frxAUDUSD | 5000 | 9 | 5 | 4 | 1:2.58 | 72.28 | 3.8 | 0.9 |

## Performance

| Symbol | Wins | Losses | Timeouts | Win Rate | Expectancy (R) | Net R | Profit Factor | Avg Bars to Win | Avg Bars to Loss |
|--------|------|--------|----------|----------|----------------|-------|---------------|-----------------|------------------|
| frxEURUSD | 5 | 1 | 0 | 83.3% | +2.058 | +12.35 | 13.35 | 1.2 | 2.0 |
| frxGBPUSD | 9 | 1 | 0 | 90.0% | +1.751 | +17.51 | 18.51 | 1.6 | 1.0 |
| frxAUDUSD | 8 | 1 | 0 | 88.9% | +2.187 | +19.68 | 20.68 | 3.1 | 1.0 |

## Aggregate (all symbols)

- **Total signals:** 25
- **Wins / Losses / Timeouts:** 22 / 3 / 0
- **Overall win rate:** 88.0%
- **Overall expectancy:** +1.982 R per signal
- **Net R:** +49.54

**Notes:**
- Win rate excludes timeouts (signals that hit neither TP nor SL within the horizon).
- Conservative assumption: if a single candle touches both SL and TP, it is counted as a loss.
- Max horizon: 96 bars.