# Experiment: EQ Model on 32 Forex Pairs

**Generated:** 2026-10-19T12:54:25Z

## Hypothesis

Testing the live EQ-gated continuation model across all 32 standard Forex pairs to identify top performers, eliminate losers, and diagnose failure modes.

## Overall Results (Ranked by Expectancy)

| Symbol | Signals | Wins | Losses | WR | Expectancy | Net R |
|--------|---------|------|--------|-----|------------|-------|
| frxNZDCHF | 7 | 5 | 2 | 71.4% | +2.806 | +19.6 |
| frxNZDUSD | 13 | 7 | 6 | 53.8% | +2.234 | +29.0 |
| frxEURUSD | 13 | 6 | 7 | 46.2% | +1.818 | +23.6 |
| frxUSDSEK | 10 | 7 | 3 | 70.0% | +1.806 | +18.1 |
| frxAUDNZD | 27 | 9 | 18 | 33.3% | +1.783 | +48.1 |
| frxGBPJPY | 5 | 3 | 2 | 60.0% | +1.736 | +8.7 |
| frxAUDJPY | 13 | 5 | 8 | 38.5% | +1.617 | +21.0 |
| frxEURCAD | 8 | 5 | 3 | 62.5% | +1.580 | +12.6 |
| frxGBPCHF | 20 | 11 | 9 | 55.0% | +1.462 | +29.2 |
| frxGBPCAD | 12 | 5 | 7 | 41.7% | +1.177 | +14.1 |
| frxGBPAUD | 14 | 7 | 7 | 50.0% | +1.110 | +15.5 |
| frxUSDCHF | 25 | 8 | 16 | 33.3% | +1.093 | +27.3 |
| frxUSDJPY | 13 | 6 | 7 | 46.2% | +1.005 | +13.1 |
| frxNZDJPY | 17 | 7 | 10 | 41.2% | +0.889 | +15.1 |
| frxCADJPY | 16 | 7 | 9 | 43.8% | +0.758 | +12.1 |
| frxAUDCHF | 22 | 9 | 13 | 40.9% | +0.750 | +16.5 |
| frxUSDCAD | 19 | 7 | 12 | 36.8% | +0.653 | +12.4 |
| frxCHFJPY | 19 | 6 | 12 | 33.3% | +0.398 | +7.6 |
| frxEURNZD | 17 | 5 | 12 | 29.4% | +0.219 | +3.7 |
| frxEURSGD | 16 | 3 | 13 | 18.8% | +0.203 | +3.2 |
| frxAUDUSD | 13 | 4 | 9 | 30.8% | +0.156 | +2.0 |
| frxNZDCAD | 12 | 3 | 9 | 25.0% | +0.156 | +1.9 |
| frxEURJPY | 9 | 2 | 7 | 22.2% | +0.048 | +0.4 |
| frxGBPNZD | 20 | 5 | 13 | 27.8% | +0.025 | +0.5 |
| frxAUDCAD | 14 | 3 | 11 | 21.4% | +0.001 | +0.0 |
| frxEURAUD | 21 | 4 | 17 | 19.0% | -0.007 | -0.1 |
| frxUSDNOK | 12 | 2 | 10 | 16.7% | -0.171 | -2.1 |
| frxEURCHF | 14 | 2 | 12 | 14.3% | -0.211 | -2.9 |
| frxCADCHF | 12 | 2 | 10 | 16.7% | -0.281 | -3.4 |
| frxEURGBP | 6 | 1 | 5 | 16.7% | -0.398 | -2.4 |
| frxGBPUSD | 14 | 0 | 14 | 0.0% | -1.000 | -14.0 |
| frxUSDTRY | 5 | 0 | 5 | 0.0% | -1.000 | -5.0 |

## Diagnosis: Why are pairs failing?

Based on the data, here is why the bottom performers fail:

### 1. The Choppy Losers (Negative Expectancy)
These pairs generate signals but lose money. They are likely ranging heavily, hitting stop losses on fake breakouts, or suffering from spread drag.
- **frxEURAUD**: 21 signals, 19.0% WR. The edges are getting chopped up.
- **frxUSDNOK**: 12 signals, 16.7% WR. The edges are getting chopped up.
- **frxEURCHF**: 14 signals, 14.3% WR. The edges are getting chopped up.
- **frxCADCHF**: 12 signals, 16.7% WR. The edges are getting chopped up.
- **frxEURGBP**: 6 signals, 16.7% WR. The edges are getting chopped up.

### 3. The Exotics (Spread Drag)
Pairs like USDNOK, USDSEK, and USDTRY have wide spreads. Our backtest assumes a tight 0.04 ATR spread. In reality, these spreads will eat into the 2.5R profits significantly.