# Experiment: Confluence Rule Comparison (A–F)

**Generated:** 2026-10-11T19:20:22Z

## Hypothesis

Compare OB quality gates under identical conditions to answer: is the flexible rule profitable because the extra confluences identify better setups, or simply because it generates more trades?

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles | 2500 |
| warmup_bars | 400 |
| n_windows | 3 |
| note | Detection once at rule E; filtering applied post-hoc for each rule. |

## Rule Definitions

| Rule | Logic |
|------|-------|
| A | FVG required only |
| B | FVG OR EQH/EQL |
| C | FVG OR inducement sweep |
| D | FVG OR time-based liquidity |
| E | Any of the four (current flexible rule) |
| F2 | At least 2 of the four |
| F3 | At least 3 of the four |
| F4 | All 4 present |

## Results by Rule

| Rule | Signals | Wins | Losses | WR | Avg R:R (wins) | Avg Confl. | Expectancy | Net R |
|------|---------|------|--------|-----|----------------|------------|------------|-------|
| A_FVG_only | 300 | 106 | 189 | 35.9% | 1.86 | 2.63 | +0.026 | +7.9 |
| B_FVG_or_EQ | 1252 | 551 | 668 | 45.2% | 2.01 | 1.89 | +0.351 | +439.8 |
| C_FVG_or_IDM | 329 | 124 | 200 | 38.3% | 1.86 | 2.62 | +0.094 | +31.0 |
| D_FVG_or_TIME | 956 | 412 | 530 | 43.7% | 2.03 | 2.16 | +0.318 | +304.4 |
| E_any_of_four | 1311 | 573 | 705 | 44.8% | 2.00 | 1.85 | +0.339 | +443.9 |
| F2_score_at_least_2 | 889 | 392 | 483 | 44.8% | 2.03 | 2.25 | +0.353 | +314.2 |
| F3_score_at_least_3 | 214 | 78 | 135 | 36.6% | 1.88 | 3.06 | +0.053 | +11.3 |
| F4_score_all_four | 12 | 7 | 5 | 58.3% | 1.87 | 4.00 | +0.674 | +8.1 |

## Confluence Coverage in the Full Flexible Set (Rule E)

| Confluence | Signals | % of Total | WR | Expectancy |
|------------|---------|------------|-----|------------|
| FVG | 300 | 22.9% | 35.9% | +0.026 |
| EQ | 1208 | 92.1% | 45.6% | +0.365 |
| IDM | 61 | 4.7% | 59.0% | +0.707 |
| TIME | 857 | 65.4% | 43.9% | +0.333 |

## Per-Window — Rule E (any of four)

| Window | Signals | WR | Expectancy |
|--------|---------|-----|------------|
| W1 | 423 | 47.1% | +0.375 |
| W2 | 430 | 48.5% | +0.390 |
| W3 | 458 | 39.4% | +0.257 |

## Look-Ahead Audit

Signal generation verified to use only historical data up to the current bar:

| Component | Data Used | Verdict |
|-----------|-----------|---------|
| Swing detection | Confirmed swings only (n bars after required, index ≤ current − n) | ✅ |
| BOS/CHoCH | Prior swings only (index < current) | ✅ |
| Liquidity pools | Built from confirmed swings | ✅ |
| PDH/PDL/weekly/session | Bars strictly before `as_of_epoch` | ✅ |
| Order block | Backward scan from BOS | ✅ |
| FVG detection | Bounded range (OB → BOS) | ✅ |
| Inducement sweep | Between BOS and current bar | ✅ |
| Touch trigger | Current bar's low/high vs OB mid | ✅ |
| Exit simulation | Future bars (intentional — measures outcome) | ✅ |

All signal-generation paths use only data available at the current bar. The exit simulation intentionally uses future bars to measure outcomes — this is correct.

## Verdict

- Rule E vs Rule A: **4.4× more signals**, WR +8.9 pp, **56.1× net R**
- Flexible rule is NOT just more trades — its WR is higher than FVG-only.

**Best rule by net R:** see the Results table above.
