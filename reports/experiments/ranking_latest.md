# Experiment: Daily Cap + Ranking Formulas

**Generated:** 2026-10-11T21:31:03Z

## Hypothesis

Given ~12 EQ signals per day, capping at 5/day via a ranking formula should preserve or improve per-trade quality while cutting signal volume to a manageable level.

## Configuration

| Parameter | Value |
|-----------|-------|
| pairs | 19 |
| h1_candles | 2500 |
| warmup_bars | 400 |
| n_windows | 3 |
| daily_cap | 5 |
| total_signals_after_eq_filter | 1207 |
| total_days | 101 |

## Ranking Formulas

| Formula | Description |
|---------|-------------|
| F1_RR_only | Rank by planned R:R (highest first) |
| F2_ConfluenceCount | Rank by number of confluences, tiebreak by R:R |
| F3_IDM_priority | Signals with IDM first, then by R:R |
| F4_Detailed | R:R + 3×IDM + 1×EQ + 0.5×FVG + 0.5×TIME |
| F5_Random | Random selection (control) |

## Unfiltered Baseline (all EQ signals, no cap)

- Signals: 1207
- WR: 45.7%
- Expectancy: +0.366 R
- Net R: +441.9
- Avg R:R on wins: 2.01

## Capped to Top 5/day by Formula

| Formula | Signals | Days | Avg/day | Wins | Losses | WR | Avg R:R (wins) | Expectancy | Net R |
|---------|---------|------|---------|------|--------|-----|----------------|------------|-------|
| F1_RR_only | 461 | 101 | 4.6 | 186 | 246 | 43.1% | 2.33 | +0.408 | +188.0 |
| F2_ConfluenceCount | 461 | 101 | 4.6 | 176 | 260 | 40.4% | 2.24 | +0.290 | +133.8 |
| F3_IDM_priority | 461 | 101 | 4.6 | 189 | 244 | 43.6% | 2.33 | +0.425 | +195.8 |
| F4_Detailed | 461 | 101 | 4.6 | 173 | 259 | 40.0% | 2.36 | +0.324 | +149.5 |
| F5_Random | 461 | 101 | 4.6 | 201 | 243 | 45.3% | 2.07 | +0.377 | +173.9 |

## Deltas vs Unfiltered Baseline

| Formula | Δ Signals | Δ WR (pp) | Δ Expectancy (R) | Δ Net R |
|---------|-----------|-----------|------------------|---------|
| F1_RR_only | -746 | -2.6 | +0.042 | -253.8 |
| F2_ConfluenceCount | -746 | -5.3 | -0.076 | -308.0 |
| F3_IDM_priority | -746 | -2.0 | +0.059 | -246.1 |
| F4_Detailed | -746 | -5.6 | -0.042 | -292.3 |
| F5_Random | -746 | -0.4 | +0.011 | -268.0 |

## Verdict

- **Best by expectancy:** F3_IDM_priority (+0.425 R, n=461)
- **Best by net R:** F3_IDM_priority (+195.8 R, n=461)

**Recommendation:** promote **F3_IDM_priority** as the live ranking formula. It wins on both per-trade quality and total profit.

Ranking WR is within 2.0 pp of unfiltered baseline — selection is roughly neutral.
