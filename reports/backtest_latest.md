# SMC Signal Bot — Backtest Report

**Generated:** 2026-10-01T11:42:21Z

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
| frxEURUSD | 5000 | 5 | 3 | 2 | 1:2.93 | 72.28 | 2.1 | 0.5 |
| frxGBPUSD | 5000 | 8 | 7 | 1 | 1:1.93 | 72.28 | 3.4 | 0.8 |
| frxAUDUSD | 5000 | 9 | 5 | 4 | 1:2.58 | 72.28 | 3.8 | 0.9 |

## Performance

| Symbol | Wins | Losses | Timeouts | Win Rate | Expectancy (R) | Net R | Profit Factor | Avg Bars to Win | Avg Bars to Loss |
|--------|------|--------|----------|----------|----------------|-------|---------------|-----------------|------------------|
| frxEURUSD | 4 | 1 | 0 | 80.0% | +1.666 | +8.33 | 9.33 | 1.2 | 0.0 |
| frxGBPUSD | 7 | 1 | 0 | 87.5% | +1.615 | +12.92 | 13.92 | 1.7 | 0.0 |
| frxAUDUSD | 6 | 3 | 0 | 66.7% | +1.470 | +13.23 | 5.41 | 3.8 | 0.0 |

## Aggregate (all symbols)

- **Total signals:** 22
- **Wins / Losses / Timeouts:** 17 / 5 / 0
- **Overall win rate:** 77.3%
- **Overall expectancy:** +1.567 R per signal
- **Net R:** +34.48

**Notes:**
- Fill assumed only when entry bar's range reached the OB midpoint.
- If the entry bar also pierced the stop, counted as a loss (worst-case same-bar).
- If a future candle touches both SL and TP, counted as a loss (worst-case).
- Max horizon: 96 bars.
- Win rate excludes timeouts.