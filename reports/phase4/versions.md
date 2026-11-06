# Phase 4 versions ledger (practice years only)

Cap: 6 versions. Each version is written here and committed BEFORE it runs.
Rebuilding rules and measuring cost no version. Adopting a rule or switch
because a measurement favoured it costs one version.
Exam years (2022-07-01 to 2026-10-01) stay sealed until one version is locked.

Versions used: 4 of 6 (V1, V2, V3, V4).
ZT and MZ are rebuilds from his rules and chart checks, not tuning versions.

Terms
- Pullback trade = counter-trend, always: a sell in a bull HTF bias, a buy in a
  bear HTF bias. Entry models: breaker and OB.
- Zone trade = with the trend: a buy at an HTF buy zone in an uptrend, a sell at
  an HTF sell zone in a downtrend. His MAIN trades (built in ZT, rebuilt in MZ).

## V1 - pullback system as built (baseline, nothing tuned)

Scope
- Pullback (counter-trend) trades only, breaker model and OB model, plain
  variant (no FVG). In a bull HTF bias these are sells; in a bear HTF bias
  they are buys (exact mirror).
- Zone trades (with the trend) were not built then. The result below is only the
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
Result (28 pairs, practice years, lookahead PASS)
- 436 resolved trades, Net R +8.22, win 27.8%, PF 1.02, expectancy +0.019R,
  max drawdown 39.20R, longest losing streak 15. Equals the V1 OB row exactly.
- One-at-a-time: 429 trades, +3.87R, PF 1.01.
- By year: 2016 +0.90, 2017 +12.08, 2018 +7.07, 2019 -20.70, 2020 -9.05,
  2021 +15.04, 2022 (Jan-Jun) +2.89.
- Verdict: WEAK / NOT PROVEN. The gain over V1 is inside the noise
  (about +/-40R for 436 trades) and mostly comes from dropping the breaker rows.
- His decision: breaker and OB both on standby, to come back to. V4 is NOT
  adopted; V1 stays the base.

## ZT - zone trades built on V1 (variant "zt")  [not a tuning version]

Why: zone trades (with the trend) are his MAIN trades and were not built. This
is his rule being built on the V1 base he chose, not a switch adopted because a
measurement favoured it. Versions used stays 4 of 6.
Bias and pullback rules: exactly V1 (5 swings, D1 and H4 agree, breaker + OB).
Zone buy, in order (sells are the mirror):
1. Bias up. HTF BOS arms the cycle, an M15 CHoCH down starts the pullback.
2. An M15 BOS down forms (before the zone, on the touch, or inside the zone).
3. A wick touches a remembered fresh HTF buy zone (touch is MANDATORY and must
   come before the CHoCH up closes).
4. A body closes above the high of the BOS-down leg = CHoCH up.
5. Breaker buy: "the" breaker of that CHoCH, limit at its near edge once dead.
   OB buy: the CHoCH's own box; a BOS up after it gives the inducement; a wick
   clears it; limit at the box near edge. Stop = far edge -/+ 0.2 x ATR.
6. Scan ends on a body close beyond the ceiling, through the zone's far edge,
   or bias lost. Pending orders are cancelled; filled trades keep running.
Targets (two scorecards, same entry and stop):
- Static 1:3.
- Liquidity: nearest unswept M15 swing at least 3R away (between entry and the
  ceiling); if none, the ceiling.
Assumptions (not confirmed by him)
- Z1 touch = any wick reaching the zone near edge.
- Z2 fresh zones only; the zone list is frozen at pullback start (a live read at
  the touch was dropped because it would change the pullback numbers).
- Z3 CHoCH = the M15 structure's own CHoCH; its level is printed on the sheet.
- Z4 touch and CHoCH-close on the same bar is valid.
- Z5 a CHoCH with the trend before the touch clears the BOS memory.
- Z7 more attempts in the same scan are allowed.
- Z8 no CHoCH-down gate needed (read from structure.py).
- Z9 zone trades only inside the cycle flow (HTF BOS, M15 CHoCH against, touch).
  A touch without that pullback is not traded.
- Z10 BOS memory = a BOS against the trend since the last CHoCH with the trend.
- T1 liquidity = unswept M15 swing (N=2), known at its confirm bar, up to the ceiling.
- T2 no swing at least 3R away: target = ceiling even if closer than 3R.
Checks for the run
- Lookahead PASS (zone steps are in the decision log).
- Pullback scorecard equals V1 exactly: 1,455 trades, -21.13R.
Run: all 28 pairs, practice years, LOOKAHEAD_CUTS=10, variant zt.
Result (28 pairs, practice years; a measurement, not a tuning signal)
- Lookahead PASS (3,196,569 decisions, 10 cuts per pair).
- Pullback card equals V1 exactly: 1,455 trades, -21.13R (check passed).
- MAIN card (zone, static 1:3): 284 trades, Net R +10.00, win 28.2%, PF 1.04,
  expectancy +0.035R, avg R:R 2.66, max drawdown 23.69R, longest losing
  streak 14, about 3.65 trades per month. Verdict: WEAK / NOT PROVEN.
- Zone liquidity card: 283 trades, +3.04R, PF 1.01.
- Buys 125 trades -11.73R; sells 159 trades +21.74R.
- Orders: filled 284, skipped_spread 358, fill_beyond_stop 25, unfilled_cancelled 57.
- By year (MAIN): 2016 +12.98, 2017 +0.93, 2018 +1.28, 2019 -4.11,
  2020 +9.61, 2021 -15.27, 2022 (Jan-Jun) +4.59.
- His chart check of the first 10 zone trades (all sells): trade 1 (CHFJPY)
  perfect; trades 2-9 all GBPCAD from one zone and one touch (7 losses, 1 win),
  with trade 2 left unfilled while price fell about 275 pips, then filled on a
  spike back and stopped; trade 10 (EURNZD) used an internal H4 zone while the
  next major D1 low was still unbroken. These three findings led to MZ.

## MZ - rebuild from his chart rules (variant "mz")  [not a tuning version]

Why: his chart check of the ZT trades showed three things the system did wrong.
These are his rules corrected, not a switch adopted because a number favoured it.
Versions used stays 4 of 6. V1-V4 and ZT become history (they used N=2/3 swings).

Change 1 - Major swings for H4 and D1 (bias and HTF zones)
- H4 and D1 use N=8 swings (config MAJOR_H4_SWING_N, MAJOR_D1_SWING_N), matching
  his approved TradingView script.
- A major low is the lowest point of a whole leg; a major high is the highest
  point of the pullback between two major lows. Smaller swings are internal.
- BOS = body close beyond the last major swing; only then is a POI drawn.
  Breaking an internal swing does nothing. Uptrend is the mirror.
- Bias first read = 3 counted Major swings (config MAJOR_BIAS_FIRST_READ). D1 and
  H4 must agree.
- M15 stays N=2 and is never filtered to Major (breaker and OB entries as before).
- Switch: config.MAJOR_HTF (False for every older variant, True for mz).

Change 2 - used-zone rule B (zone trades only)
1. A zone is touched when a wick reaches it (body close not needed).
2. The first time a trade is TAKEN from a zone, the zone is spent. "Taken" =
   the order really fills: touched, next open not beyond the stop, spread/risk
   not above 0.15 (the same tests as the simulator).
3. A spent zone is never used again; later taps are ignored.
4. After the first trade, hunting continues in the same move: new BOS, CHoCH,
   breaker and OB setups still count, no new touch needed.
5. Hunting stops only on a ceiling break, bias lost, or a body close through
   the far edge of the zone; then look for a different fresh zone.
6. If an order is cancelled before filling, the zone is NOT spent.

Change 3 - cancel rule (zone orders only)
- A pending zone order is cancelled (end reason "ran_away") if a wick runs 150
  pips beyond its entry in the trade-target direction before the entry is
  touched. Sell: price falls 150 pips below entry. Buy: price rises 150 above.
- Pip size: 0.0001, or 0.01 for JPY pairs (150 pips = 0.0150 or 1.50).
- Applies to breaker and OB zone orders alike. Pullback orders are unchanged.
- The zone is not spent by a cancelled order.

What stays the same as ZT: breaker and OB entries, stop = far edge -/+ 0.2 x ATR,
static 1:3 and liquidity targets, ceiling rules, spread skip, fill at next open.
Variant mz passes no first_read override, so the first read stays 3.

Assumptions (not confirmed by him)
- Z11 "used" in poi.py means wick-touched only (poi.py not read). With rules on,
  zones that are fresh or used (never dead) and not spent can be touched.
- Z12 spent zones are keyed by the zone id (a D1 zone refined to an H4 candle
  keeps its D1 id).
- Z13 other pending orders from a zone keep running after it is spent.
- Z14 a bar that touches the entry and also runs 150 pips = cancelled.
- The 150-pip check starts on the first bar after placement.
- Z1-Z10 and T1-T2 as in ZT.

Checks for the run
- Lookahead PASS (all zone rule steps are in the decision log).
- Pullback numbers are a NEW baseline (Major swings change bias and zones).
  They will NOT equal V1 (1,455 trades, -21.13R). That is expected, not a failure.
- Old tests should still pass (MAJOR_HTF and zone rules are off by default).

Measure after the run (not decisions)
- Pair funnel: does N=8 on D1 delay or block the 3-swing first read on some pairs?
- How many orders ended "ran_away", and how many zones were spent.
- Whether same-zone overtrading (GBPCAD style) fell.

Run: all 28 pairs, practice years, LOOKAHEAD_CUTS=10, variant mz.
Status: written before the run. Result: pending.

## How versions are judged
- Pullbacks are the side trade. His main trades are zone trades. The ZT and MZ
  runs measure them; they are not tuning choices.
- A variant counts as better only with lookahead PASS and a better expectancy
  and profit factor than V1 on the same practice years. MZ changes the bias
  engine, so it starts a new baseline and is compared as a rebuild.
- Nothing is locked yet.
