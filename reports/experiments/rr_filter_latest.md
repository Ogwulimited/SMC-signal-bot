# Experiment: Minimum R:R Filter

**Generated:** 2026-10-19T08:32:04Z

## Hypothesis

Filtering out low R:R trades (e.g. 1:1.5) will reduce signal count but improve Win Rate and overall Expectancy, because the bot is only taking trades with highly asymmetric payouts.

## Results by Minimum R:R

| MIN_RR | Signals | Wins | Losses | WR | Avg R:R (wins) | Expectancy | Net R |
|--------|---------|------|--------|-----|----------------|------------|-------|
| 1.5 | 420 | 167 | 252 | 39.9% | 3.06 | +0.617 | +259.1 |
| 2.0 | 381 | 141 | 239 | 37.1% | 3.31 | +0.599 | +228.2 |
| 2.5 | 300 | 96 | 203 | 32.1% | 3.89 | +0.570 | +170.9 |
| 3.0 | 237 | 72 | 164 | 30.5% | 4.33 | +0.622 | +147.4 |
| 3.5 | 189 | 52 | 136 | 27.7% | 4.82 | +0.608 | +114.8 |
| 4.0 | 148 | 35 | 112 | 23.8% | 5.44 | +0.531 | +78.5 |

## Verdict

- **Baseline (1.5):** 420 signals, +0.617 R exp, +259.1 Net R.
- **Best Expectancy:** MIN_RR = 3.0 (+0.622 R).
- **Best Total Profit (Net R):** MIN_RR = 1.5 (+259.1 Net R).

**Decision:** If you value per-trade quality, choose the Best Expectancy. If you value total account growth, choose the Best Net R.
