# Phase 4 versions ledger (practice years only)

Cap: 6 versions. Each version is written here and committed BEFORE it runs.
Rebuilding rules and measuring cost no version. Adopting a rule or switch
because a measurement favoured it costs one version.
Exam years (2022-07-01 to 2026-10-01) stay sealed until one version is locked.

Versions used: 4 of 6 (V1, V2, V3, V4).

Terms
- Pullback trade = counter-trend, always: a sell in a bull HTF bias, a buy in a
  bear HTF bias. Entry models: breaker and OB.
- Zone trade = with the trend: a buy at an HTF buy zone in an uptrend, a sell at
  an HTF sell zone in a downtrend. NOT built yet.

## V1 - pullback system as built (baseline, nothing tuned)

Scope
- Pullback (counter-trend) trades only, breaker model and OB model, plain
  variant (no FVG). In a bull HTF bias these are sells; in a bear HTF bias
  they are buys (exact mirror).
- Zone trades (with the trend) are NOT built. The result below is only the
  pullback half of the system.

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
- CHOSEN as the base to build zone trades on (his decision).

## V2 - first read 3 swings, D1 and H4 must agree

Why: he said 5 was chosen only for a strong confirmation, not a fixed law, and
asked to test 3.
Change from V1: first read = 3 counted swings on D1 and H4. D1 and H4 must agree.
Result (28 pairs, practice years, lookahead PASS)
- 2,315 resolved trades, Net R -29.21, win 27.2%, PF 0.98, expectancy -0.013R,
  max drawdown 106.08R, longest losing streak 20.
- Breaker 1,617 trades -52.09R (exp -0.032); OB 698 trades +22.88R (exp +0.033).
- All 28 pairs trade. Compared with V1: same quality, more coverage. A tie.
- Not chosen.

## V3 - first read 3 swings, H4 alone decides the bias

Why: he asked to see 4H as the only higher timeframe for bias.
Change from V1: first read = 3 swings, tradable bias = H4 bias alone, D1 ignored.
Assumption A9 (not confirmed): only the bias ignores D1. D1 BOS events can still
arm the cycle when the H4 bias agrees, and D1 zones are still remembered.
Result (28 pairs, practice years, lookahead PASS)
- 4,484 resolved trades, Net R -226.78, win 26.2%, PF 0.94, expectancy -0.051R,
  max drawdown 275.69R, longest losing streak 24.
- Breaker 3,070 trades -243.50R (exp -0.079); OB 1,414 trades +16.71R (exp +0.012).
- Only 2020 was positive. H4 bias flips 70-109 times per pair in 6.5 years.
- Rejected.

## V4 - V1 with OB entries only (breaker entries ignored)

Why: he asked to see pullback performance with OB entries only. In V1, V2 and
V3 the OB model was slightly positive and the breaker model negative; those
runs share most of their trades, so this is one observation, not three.
Change from V1 (nothing else changes)
- Only OB-model pullback orders are simulated. Breaker orders are dropped after
  the engine run, so the decision log and the lookahead check are as in V1.
- Bias: 5 swings, D1 and H4 agree (as V1).
Expected (from reading the code, not yet run): stacking numbers equal the OB row
of V1 (436 trades, -> +8.22R, win 27.8%). One-at-a-time numbers will differ.
Scope: pullback trades only; zone trades not built.
Run: all 28 pairs, practice years, LOOKAHEAD_CUTS=10.
Status: written before the run. Result: pending.

## How versions are judged
- Pullbacks are the side trade. His main trades are zone trades, which are not
  built yet. These tests only decide whether the reversal half is worth keeping
  and in what form.
- A variant counts as better only with lookahead PASS and a better expectancy
  and profit factor than V1 on the same practice years.
- Nothing is locked yet. Zone trades come first.
