# SMC Signal Bot — Backtest Report

**Generated:** 2026-10-01T16:56:34Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | M15 |
| granularity_sec | 900 |
| candles_requested | 6000 |
| warmup_bars | 200 |
| detect_window | 500 |
| max_horizon_bars | 96 |
| spread_atr_frac | 0.04 |
| swing_lookback | 2 |
| atr_period | 14 |
| eq_tolerance_atr | 0.15 |
| displacement_atr_mult | 1.5 |
| min_rr | 1.5 |
| min_sweep_penetration_atr | 0.2 |
| max_bars_sweep_to_entry | 80 |
| max_ob_age_bars | 80 |

## Frequency & Setup Quality

| Symbol | Candles | Signals | Bull | Bear | Avg R:R (after spread) | Span (days) | Signals/Month | Signals/Week |
|--------|---------|---------|------|------|------------------------|-------------|---------------|--------------|
| frxEURUSD | 6000 | 5 | 3 | 2 | 1:2.75 | 85.91 | 1.8 | 0.4 |
| frxGBPUSD | 6000 | 10 | 9 | 1 | 1:2.07 | 85.91 | 3.5 | 0.8 |
| frxAUDUSD | 6000 | 11 | 6 | 5 | 1:2.31 | 85.91 | 3.9 | 0.9 |

## Performance

| Symbol | Wins | Losses | Timeouts | Win Rate | Expectancy (R) | Net R | Profit Factor | Avg Bars to Win | Avg Bars to Loss |
|--------|------|--------|----------|----------|----------------|-------|---------------|-----------------|------------------|
| frxEURUSD | 4 | 1 | 0 | 80.0% | +1.563 | +7.82 | 8.82 | 1.2 | 0.0 |
| frxGBPUSD | 9 | 1 | 0 | 90.0% | +1.673 | +16.73 | 17.73 | 1.6 | 0.0 |
| frxAUDUSD | 8 | 3 | 0 | 72.7% | +1.469 | +16.15 | 6.38 | 3.1 | 0.0 |

## Aggregate (all symbols)

- **Total signals:** 26
- **Wins / Losses / Timeouts:** 21 / 5 / 0
- **Overall win rate:** 80.8%
- **Overall expectancy:** +1.565 R per signal
- **Net R:** +40.70

**Notes:**
- Spread modeled as 0.04 × ATR, half on entry, half on exit.
- Rolling detection window to keep runtime manageable.
- Same-bar SL: counted as loss if entry bar pierced stop.
- Future bar hitting both SL and TP: counted as loss.
- Max horizon: 96 bars.
- Win rate excludes timeouts.
- Per-trade log: `reports/backtest_trades.csv`