# SMC Signal Bot — Backtest Report

**Generated:** 2026-10-01T17:32:46Z

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
| frxEURUSD | 6000 | 4 | 3 | 1 | 1:2.59 | 85.91 | 1.4 | 0.3 |
| frxGBPUSD | 6000 | 6 | 6 | 0 | 1:2.06 | 85.91 | 2.1 | 0.5 |
| frxAUDUSD | 6000 | 6 | 3 | 3 | 1:2.22 | 85.91 | 2.1 | 0.5 |

## Performance

| Symbol | Wins | Losses | Timeouts | Win Rate | Expectancy (R) | Net R | Profit Factor | Avg Bars to Win | Avg Bars to Loss |
|--------|------|--------|----------|----------|----------------|-------|---------------|-----------------|------------------|
| frxEURUSD | 3 | 1 | 0 | 75.0% | +1.363 | +5.45 | 6.45 | 1.3 | 0.0 |
| frxGBPUSD | 5 | 1 | 0 | 83.3% | +1.499 | +8.99 | 9.99 | 2.0 | 0.0 |
| frxAUDUSD | 6 | 0 | 0 | 100.0% | +2.215 | +13.29 | 999.0 | 3.8 | 0 |

## Aggregate (all symbols)

- **Total signals:** 16
- **Wins / Losses / Timeouts:** 14 / 2 / 0
- **Overall win rate:** 87.5%
- **Overall expectancy:** +1.733 R per signal
- **Net R:** +27.73

**Notes:**
- Spread modeled as 0.04 × ATR, half on entry, half on exit.
- Rolling detection window to keep runtime manageable.
- Same-bar SL: counted as loss if entry bar pierced stop.
- Future bar hitting both SL and TP: counted as loss.
- Max horizon: 96 bars.
- Win rate excludes timeouts.
- Per-trade log: `reports/backtest_trades.csv`