# Phase 4 versions ledger (practice years only)

Cap: 6 versions. Each version is written here and committed BEFORE it runs.
Rebuilding rules and measuring cost no version. Adopting a rule or switch
because a measurement favoured it costs one version.
Exam years (2022-07-01 to 2026-10-01) stay sealed until one version is locked.

Versions used: 3 of 6 (V1, V2, V3).

## V1 - pullback system as built (baseline, nothing tuned)

Scope
- Pullback (counter-trend) trades only, breaker model and OB model, plain
  variant (no FVG). In a bull HTF bias these are sells; in a bear HTF bias
  they are buys (exact mirror).
- Zone trades (with the trend: buys in an uptrend, sells in a downtrend) are
  NOT built. The result below is only the pullback half of the system.

Rules
- Bias: first read needs 5 counted swings on D1 and on H4. D1 and H4 must agree.
- Entry: limit at the near edge of the breaker box (breaker model) or of the CHoCH box (OB model).
- Stop: far edge +/- 0.2 x ATR(H1,14). Target: static 1:3.
- Fill at the next M15 open after the touch. Stop wins a same-bar tie.
- Spread skip when spread/risk > 0.15. Net R = gross R - one spread cost.
- Gap loss can exceed 1R. No management after entry. No time stop.
- Ceiling: temporary after the CHoCH, locked after two M15 events.
  A CHoCH against as the first event throws the attempt away.
- Bad days NOT excluded.
- M15 bars outside the New York trading week are dropped at load.
- Spreads for the 17 new pairs are assumed, not measured.

Unconfirmed assumptions (his answers pending)
- A1 inducement = last opposite swing of the first BOS.
- A2 OB needs a fresh CHoCH box; same-bar sweep and touch is skipped.
- A3 target zones are frozen at pullback start.
- A4 refined H4 candle = the one holding the D1 base extreme, with the colour rule.
- A5 zone touched before the lock uses the temporary ceiling; no ceiling means idle.
- A6 bias lost cancels orders and goes idle.
- A7 after a far-edge break in the scan, idle until the next HTF BOS.
- A8 FVG variant not built.
- "One box serves one CHoCH" not confirmed.

Result (28 pairs, practice years, lookahead PASS; a measurement, not a tuning signal)
- 1,455 resolved trades, Total Net R -21.13, win 27.1%, PF 0.98,
  expectancy -0.015R, max drawdown 86.11R, longest losing streak 20.
- Breaker 1,019 trades -29.35R; OB 436 trades +8.22R.
- Verdict: NEGATIVE on practice years.
- Three pairs (eurgbp, audnzd, cadjpy) had 0 orders and usdjpy only 9.
  Cause found by a read-only diagnostic (no version cost): the D1 first read
  (5 counted swings in a row) never completed on those three pairs in 6.5 years,
  so D1 and H4 never agreed. usdjpy D1 formed only on 2022-04-28.
- This is the baseline that V2 and V3 are compared against. If neither is
  better, we go back to V1.

## V2 - first read 3 swings, D1 and H4 must agree

Why: he said 5 was chosen only for a strong confirmation, not a fixed law, and
asked to test 3.

Change from V1 (nothing else changes)
- BIAS first read = 3 counted swings (V1: 5), on both D1 and H4.
- D1 and H4 must still agree for a tradable bias.

Scope: same as V1 (pullback trades only, zone trades not built).
Run: all 28 pairs, practice years, LOOKAHEAD_CUTS=10, one dispatch with V3.
Status: written before the run. Result: pending.

## V3 - first read 3 swings, H4 alone decides the bias

Why: he asked to see 4H as the only higher timeframe for bias.

Change from V1 (nothing else changes)
- BIAS first read = 3 counted swings.
- Tradable bias = the H4 bias alone. D1 bias is ignored.

Assumption A9 (not confirmed): only the bias ignores D1. D1 BOS events can still
arm the cycle when the H4 bias agrees with their direction, and D1 zones are
still remembered as pullback targets.

Scope: same as V1 (pullback trades only, zone trades not built).
Run: all 28 pairs, practice years, LOOKAHEAD_CUTS=10, one dispatch with V2.
Status: written before the run. Result: pending.

## How V2 and V3 are judged
- Pullbacks are the side trade. His main trades are zone trades, which are not
  built yet. This test only decides whether the reversal half is worth keeping.
- A variant counts as better than V1 only with lookahead PASS and a better
  expectancy and profit factor than V1 on the same practice years.
- The best of V1, V2, V3 is not locked yet. Zone trades come first.
