# Experiment: Confluence Rule Comparison (A–G, AND logic)

**Generated:** 2026-10-11T19:47:32Z

## Hypothesis

Compare OB quality gates using AND logic (requiring combinations of confluences) under identical conditions. Determine whether requiring additional confluences on top of FVG improves quality, and whether FVG itself adds value (Rule G control).

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles | 2500 |
| warmup_bars | 400 |
| n_windows | 3 |
| note | Detection once at permissive level; AND filters applied post-hoc for each rule. |

## Rule Definitions (AND logic)

| Rule | Logic |
|------|-------|
| A_FVG_only | FVG only (current live bot) |
| B_FVG_AND_EQ | FVG AND EQH/EQL |
| C_FVG_AND_IDM | FVG AND inducement sweep |
| D_FVG_AND_TIME | FVG AND time-based liquidity |
| E_FVG_EQ_TIME | FVG AND EQH/EQL AND time-based liquidity |
| F_FVG_EQ_IDM_TIME | FVG AND EQH/EQL AND IDM AND time-based |
| G_EQ_only | EQH/EQL only (control — no FVG) |

## Results by Rule

| Rule | Signals | Wins | Losses | WR | Avg R:R (wins) | Avg Confl. | Expectancy | Net R |
|------|---------|------|--------|-----|----------------|------------|------------|-------|
| A_FVG_only | 300 | 106 | 189 | 35.9% | 1.86 | 2.63 | +0.026 | +7.9 |
| B_FVG_AND_EQ | 256 | 91 | 160 | 36.3% | 1.86 | 2.80 | +0.035 | +9.0 |
| C_FVG_AND_IDM | 32 | 18 | 14 | 56.2% | 1.89 | 3.22 | +0.626 | +20.0 |
| D_FVG_AND_TIME | 201 | 66 | 134 | 33.0% | 1.86 | 3.00 | -0.055 | -11.0 |
| E_FVG_EQ_TIME | 183 | 60 | 122 | 33.0% | 1.86 | 3.07 | -0.055 | -10.1 |
| F_FVG_EQ_IDM_TIME | 12 | 7 | 5 | 58.3% | 1.87 | 4.00 | +0.674 | +8.1 |
| G_EQ_only | 1208 | 536 | 639 | 45.6% | 2.01 | 1.90 | +0.365 | +440.9 |

## Confluence Coverage in the Full Set (any signal, regardless of rule)

| Confluence | Signals | % of Total | WR | Expectancy |
|------------|---------|------------|-----|------------|
| FVG | 300 | 22.9% | 35.9% | +0.026 |
| EQ | 1208 | 92.1% | 45.6% | +0.365 |
| IDM | 61 | 4.7% | 59.0% | +0.707 |
| TIME | 857 | 65.4% | 43.9% | +0.333 |

## Per-Window — Rule A (FVG only, current live)

| Window | Signals | WR | Expectancy |
|--------|---------|-----|------------|
| W1 | 101 | 32.7% | -0.069 |
| W2 | 74 | 37.8% | +0.087 |
| W3 | 125 | 37.5% | +0.067 |

## Per-Window — Rule G (EQH/EQL only)

| Window | Signals | WR | Expectancy |
|--------|---------|-----|------------|
| W1 | 383 | 47.8% | +0.399 |
| W2 | 409 | 50.2% | +0.440 |
| W3 | 416 | 39.0% | +0.260 |

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

- **Rule A (FVG only):** 300 signals, 35.9% WR, +0.026 R expectancy
- **Rule G (EQ only):** 1208 signals, 45.6% WR, +0.365 R expectancy
- Delta G vs A: WR +9.7 pp, expectancy +0.339 R
- **EQ-only beats FVG-only.** FVG is not the strongest confluence.

- **Rule B (FVG AND EQ):** 256 signals, 36.3% WR, +0.035 R expectancy
- Adding EQ to FVG is roughly neutral.

**Best rule by net R:** see the Results table above.
