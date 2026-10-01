# SMC Signal Bot — Backtest Report

**Generated:** 2026-10-01T18:27:45Z

## Configuration

| Parameter | Value |
|-----------|-------|
| timeframe | M15 |
| granularity_sec | 900 |
| candles_requested | 12000 |
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
| min_ob_width_atr | 0.3 |
| min_target_atr | 1.0 |

## Frequency & Setup Quality

| Symbol | Candles | Signals | Bull | Bear | Avg R:R (after spread) | Span (days) | Signals/Month |
|--------|---------|---------|------|------|------------------------|-------------|---------------|
| frxEURUSD | 12000 | 7 | 5 | 2 | 1:2.63 | 176.03 | 1.2 |
| frxGBPUSD | 12000 | 8 | 6 | 2 | 1:2.12 | 176.03 | 1.4 |
| frxAUDUSD | 12000 | 11 | 5 | 6 | 1:2.48 | 176.03 | 1.9 |
| frxUSDCAD | 12000 | 5 | 3 | 2 | 1:2.95 | 176.03 | 0.9 |
| frxUSDCHF | 12000 | 11 | 6 | 5 | 1:2.77 | 176.03 | 1.9 |
| frxUSDJPY | 12000 | 7 | 1 | 6 | 1:2.27 | 176.03 | 1.2 |
| frxNZDUSD | 12000 | 6 | 5 | 1 | 1:3.61 | 176.03 | 1.0 |
| frxEURGBP | 12000 | 8 | 3 | 5 | 1:2.31 | 176.03 | 1.4 |
| frxEURJPY | 12000 | 11 | 6 | 5 | 1:3.61 | 176.03 | 1.9 |
| frxGBPJPY | 12000 | 7 | 4 | 3 | 1:3.15 | 176.03 | 1.2 |
| frxAUDJPY | 12000 | 12 | 9 | 3 | 1:3.57 | 176.03 | 2.1 |
| frxEURAUD | 12000 | 14 | 8 | 6 | 1:3.62 | 176.03 | 2.4 |
| frxGBPAUD | 12000 | 14 | 10 | 4 | 1:2.94 | 176.03 | 2.4 |
| frxCADJPY | 12000 | 9 | 4 | 5 | 1:2.29 | 176.03 | 1.6 |
| frxNZDJPY | 12000 | 8 | 2 | 6 | 1:2.52 | 176.03 | 1.4 |
| cryBTCUSD | 12000 | 11 | 4 | 7 | 1:3.65 | 122.92 | 2.7 |
| cryETHUSD | 12000 | 9 | 5 | 4 | 1:3.16 | 122.92 | 2.2 |
| cryLTCUSD | 12000 | 6 | 2 | 4 | 1:3.92 | 122.92 | 1.5 |
| cryXRPUSD | 12000 | 11 | 4 | 7 | 1:3.01 | 122.92 | 2.7 |
| crySOLUSD | 12000 | 9 | 2 | 7 | 1:3.14 | 122.92 | 2.2 |

## Performance

| Symbol | Wins | Losses | Timeouts | Win Rate | Expectancy (R) | Net R | Profit Factor |
|--------|------|--------|----------|----------|----------------|-------|---------------|
| frxEURUSD | 5 | 2 | 0 | 71.4% | +1.231 | +8.62 | 5.31 |
| frxGBPUSD | 6 | 2 | 0 | 75.0% | +1.317 | +10.54 | 6.27 |
| frxAUDUSD | 8 | 3 | 0 | 72.7% | +1.313 | +14.45 | 5.82 |
| frxUSDCAD | 4 | 1 | 0 | 80.0% | +2.124 | +10.62 | 11.62 |
| frxUSDCHF | 6 | 5 | 0 | 54.5% | +0.692 | +7.62 | 2.52 |
| frxUSDJPY | 6 | 1 | 0 | 85.7% | +1.641 | +11.48 | 12.48 |
| frxNZDUSD | 4 | 2 | 0 | 66.7% | +1.923 | +11.54 | 6.77 |
| frxEURGBP | 5 | 3 | 0 | 62.5% | +1.058 | +8.47 | 3.82 |
| frxEURJPY | 6 | 5 | 0 | 54.5% | +0.806 | +8.86 | 2.77 |
| frxGBPJPY | 5 | 2 | 0 | 71.4% | +1.879 | +13.15 | 7.58 |
| frxAUDJPY | 7 | 5 | 0 | 58.3% | +0.784 | +9.41 | 2.88 |
| frxEURAUD | 8 | 6 | 0 | 57.1% | +1.239 | +17.35 | 3.89 |
| frxGBPAUD | 12 | 2 | 0 | 85.7% | +2.515 | +35.20 | 18.6 |
| frxCADJPY | 6 | 3 | 0 | 66.7% | +0.946 | +8.51 | 3.84 |
| frxNZDJPY | 5 | 3 | 0 | 62.5% | +0.846 | +6.77 | 3.26 |
| cryBTCUSD | 6 | 5 | 0 | 54.5% | +1.191 | +13.10 | 3.62 |
| cryETHUSD | 4 | 5 | 0 | 44.4% | +0.262 | +2.36 | 1.47 |
| cryLTCUSD | 5 | 1 | 0 | 83.3% | +2.992 | +17.95 | 18.95 |
| cryXRPUSD | 7 | 4 | 0 | 63.6% | +1.075 | +11.82 | 3.96 |
| crySOLUSD | 6 | 3 | 0 | 66.7% | +1.456 | +13.11 | 5.37 |

## Aggregate (all symbols)

- **Total signals:** 184
- **Wins / Losses / Timeouts:** 121 / 63 / 0
- **Overall win rate:** 65.8%
- **Overall expectancy:** +1.309 R per signal
- **Net R:** +240.93
