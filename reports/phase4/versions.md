# Phase 4 versions ledger (practice years only)

Cap: 6 versions. Each version is written here and committed BEFORE it runs.
Rebuilding rules and measuring cost no version. Adopting a rule or switch
because a measurement favoured it costs one version.
Exam years (2022-07-01 to 2026-10-01) stay sealed until one version is locked.

Versions used: 4 of 6 (V1, V2, V3, V4).
ZT, MZ, MH and AG are rebuilds from his rules and chart checks, not tuning versions.

Terms
- Pullback trade = counter-trend, always: a sell in a bull HTF bias, a buy in a
  bear HTF bias. Entry models: breaker and OB.
- Zone trade = with the trend: a buy at an HTF buy zone in an uptrend, a sell at
  an HTF sell zone in a downtrend. His MAIN trades (built in ZT, rebuilt in MZ,
  trading timeframe moved to H1 in MH).
- Aggressive entry = a separate run (AG): limit at the edge of a refined H1 zone
  inside an HTF zone, no CHoCH or BOS wait, static 1:5 target.

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
  (Corrected later, see MH: poi.py was read and "used" is a BODY close inside.)
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
Status: the full run was done. He called the results "poorer than anticipated"
and said he found many errors, which he will list. The mz numbers were not
written up here before it was superseded by MH. mz is not a candidate version.

## MH - trading timeframe H1 (variant "mh")  [rule change, not a tuning version]

Why: after seeing the mz results he asked for one rule change: the trading
timeframe moves from M15 to H1, so the system uses D1, H4 and H1 and no longer
M15. His words: "This is not a tuning this is a rule change." It is his rule,
not a switch picked by comparing numbers. Versions used stays 4 of 6.
Honest note: the request came after he saw a poor mz result, and mh runs on the
same practice years as mz. If mh is later chosen because it looks better than mz,
that is a choice between variants and the cap must be counted again.

Change (the only change from mz)
- Trading timeframe = H1 (config.LTF_TF = "H1"). BOS, CHoCH, breaker, OB,
  inducement and ceiling now come from H1 bars. The H1 structure uses the same
  swing size as before (LTF_SWING_N = 2) and the H1 bars have their own POI book.
- D1 and H4 stay the bias and the HTF zones (Major swings, N=8, first read 3).
- Switch: config.LTF_TF, default "M15" (read with a default, config.py is not
  edited). Every older variant sets "M15" explicitly, so they are unchanged.

What stays the same as mz
- Major swings for H4/D1, used-zone rule B, 150-pip cancel of zone orders.
- Breaker and OB entries, stop = far edge -/+ 0.2 x ATR(H1,14), static 1:3 and
  liquidity targets, ceiling rules, spread skip.

Where M15 data is still used (price replay only, no signals)
- The simulator plays every order on M15 bars (touch, fill at next open, stop,
  target). The zone code tracks touches, fills, the 150-pip cancel and spent
  zones on the same M15 bars, so it matches the simulator. The bias-flip list
  is also timed on M15 bars.

Assumptions (not confirmed by him)
- H1 swing size N = LTF_SWING_N = 2 (not tuned for H1).
- H2 Orders are placed at H1 closes but touched, filled and stopped on M15 bars.
- H3 The 150-pip cancel and the spent-zone test are checked on M15 bars, as in
  the simulator.
- H4 Stop buffer (0.2 x ATR H1 14) and spread skip are unchanged.
- H5 Liquidity swings (N=2) are built from H1 bars.
- H6 Bias-lost and ceiling checks run at each H1 close.
- H7 Z11 corrected: poi.py was read. "Used" = a BODY close inside the box, not a
  wick. No behaviour change (fresh and used are both accepted with rules on).
- H8 Bars reach the engine in time order. The lookahead check is the test.
- Z12-Z14 and Z1-Z10, T1-T2 as before.

Checks for the run
- Lookahead PASS. If it is not PASS, ignore every number.
- Pullback and zone numbers are a NEW baseline. They will not equal V1 or mz.
  The report may print its old "pullback card equals V1" line as NO. Expected.
- Old tests may need a look (switches default off): handled one at a time, a
  test is never weakened.

Measure after the run (not decisions)
- Pair funnel: does N=8 on D1 block or delay the 3-swing first read on some pairs?
- Orders ended "ran_away", zones spent (z_zone_spent, z_ran_away, z_spent_skipped).
- Whether same-zone overtrading (GBPCAD style) fell.
- Skipped-for-spread count (estimate, not run: wider H1 boxes should mean wider
  stops and fewer spread skips, and fewer setups overall).

Run: all 28 pairs, practice years, LOOKAHEAD_CUTS=10, variant mh.
Status: written before the run. Result: pending.

## ZONE REFINEMENT - his rules (used by AG only)  [rebuild, not a tuning version]

Why: his AUDUSD pictures showed how a D1 zone is refined to an H4 zone and then
to an H1 zone, and that the refined zone need not sit inside the previous box.
He confirmed YES on lines 1-7 and answered the detail questions. These are his
rules, not a switch picked by comparing numbers. Versions used stays 4 of 6.
1. A POI is the last opposite candle in the base before an impulsive move, wick
   to wick.
2. The D1 POI is the starting zone.
3. H4: look around the D1 zone and find the last opposite candle before an
   impulsive move. It must be the one CLOSEST to the D1 zone; it need NOT sit
   inside the D1 box.
4. H1: the same around the H4 zone.
5. The D1 and H4 zones are only steps; the H1 zone is the point of interest and
   the entry.
6. Do not refine too far.
7. A zone that starts on H4 goes H4 then H1. Sells are the mirror.
- There is NO distance number for "closest" or "too far".
Details he confirmed
- "Impulsive" = a body-close break in the trade direction (BOS or CHoCH up for
  buys, down for sells) on that timeframe. No size numbers.
- Search window = the lower-timeframe bars from the open of the previous zone's
  candle to the close of the break that made the zone. Pick the candidate
  closest in price to the previous box (touching or inside counts as closest).
  Ties go to the later candle. Only bars already closed are used.
- Refinement break swing size: N=2 on both H4 and H1. The D1/H4 zones themselves
  stay Major N=8.
Added by me, accepted
- A zone that starts on H4 uses the window from the H4 zone candle to the close
  of the H4 break, then goes to H1.
- If no candidate is found at a step, that zone gets no limit and no trade.
Scope: refinement code lives in aggressive.py. cycle.py and its old refinement
(D1 zone to one H4 candle) are NOT changed, so mz and mh are unaffected.

## AG - aggressive entry (variant "ag")  [rebuild, not a tuning version]

Why: he wants a separate run that "only looks for HTF zones, refines it and
enters on the tap to continue the move to TP". It shares nothing with the zone
trades (no CHoCH, BOS, breaker or pullback logic, no shared spent list). His
rules, confirmed YES on all lines. Versions used stays 4 of 6.
Honest note: AG is a different entry style, not a tuned switch. If AG is later
chosen because its numbers look better than the zone trades, that is a choice
between variants and the cap must be counted again.

Rules
1. D1 and H4 must agree on bias, or no trade. Buys only at buy zones in a bull
   bias, sells only at sell zones in a bear bias. Bias and HTF zones come from
   Major N=8 BOS/CHoCH (first read 3), as in mz and mh.
2. Entry = limit at the H1 zone's near edge (top for buys, bottom for sells).
3. Stop = H1 far edge -/+ 0.2 x ATR(H1, 14).
4. Target = static 1:5, measured from the fill price. No liquidity target.
5. The limit rests from the moment the H1 zone exists and fills at the edge
   when a wick reaches it.
6. A bar that opens past the edge fills at that open (like a real broker). If
   that open is beyond the stop, the order is skipped and the zone is not spent.
7. Rule B: one fill spends the zone.
8. The limit is cancelled, and the zone is not spent, if bias is lost, or a body
   closes through the far edge, or a wick runs 150 pips beyond the edge in the
   target direction before the touch ("we missed entry").
9. No CHoCH, BOS, breaker or pullback logic.
10. (mine, accepted) Spread skip stays: skipped if spread > 0.15 of the risk.
11. (mine, accepted) Every fresh zone in the bias direction gets its own limit
    at the same time.
12. The scorecard is aggressive/static 1:5, on its own, never mixed with the
    zone or pullback cards. Break-even win rate at 1:5 is about 16.7% before
    spread cost.

Mechanics
- Trading timeframe H1 (as mh). The simulator plays orders on M15 bars, with
  "fill": "limit" (open fill if the bar opens at or past the entry, otherwise
  the edge). Fill-bar convention (mine, simulator): after a mid-bar edge fill
  the stop counts in that bar but the target does not; after an open fill the
  whole bar counts.
- Report: report_ag.py (its own six sections and Extras).
- Lookahead check re-runs the whole engine on cut data, same as the other variants.

Assumptions (mine, not confirmed by him)
- AG1 The limit is placed at the first M15 close after the HTF break closed.
- AG2 If price has not yet gone beyond the edge, the order waits. If price is
  already 150 or more pips past the edge when it would be placed, it is missed
  (ag_missed_far) and no order is made.
- AG3 The candidate's state (fresh/used/dead) is ignored. The candle must open
  inside the search window.
- AG4 Far edge = the H1 zone's far edge, checked on H1 body closes.
- AG5 A touched order that is skipped (spread or gap) ends; the zone is not
  spent, but no second limit is placed.
- AG6 A cancel at time t: the M15 bar closing at t cannot touch; touches are
  resolved with a one-bar delay.
- AG7 Spent and closed zones are keyed by the H1 box. Two HTF zones that refine
  to the same H1 candle give one limit.

Checks for the run
- Lookahead PASS. If it is not PASS, ignore every number.
- Numbers are a NEW scorecard. They cannot be compared to the zone or pullback
  numbers as a tie-break without counting a version.
- Old tests untouched. No existing file besides run_cycle.py and the workflow
  was changed.

Measure after the run (not decisions)
- ag_zones_D1, ag_zones_H4, ag_no_h4_candidate, ag_no_h1_candidate.
- ag_missed_far (estimate, not run: a D1 zone is usually born after price has
  already run far above it, so many D1 zones may be missed at birth).
- ag_orders, ag_zone_spent, ag_skip_spread, ag_skip_beyond_stop, ag_cancel_*.
- Statuses of the trades file and the first 10 trades on a chart (his method:
  look them up, say what the system did wrong, fix it).
- Estimates (not run): many more trades than the CHoCH entries, tight stops
  because H1 boxes are small, many orders skipped for spread.

Run: all 28 pairs, practice years, LOOKAHEAD_CUTS=10, variant ag, mode full.
Status: written before the run. Result: pending.

## How versions are judged
- Pullbacks are the side trade. His main trades are zone trades. The ZT, MZ, MH
  and AG runs measure them; they are not tuning choices.
- A variant counts as better only with lookahead PASS and a better expectancy
  and profit factor than V1 on the same practice years. MZ and MH change the
  bias engine and the trading timeframe, and AG is a separate entry style with
  its own 1:5 card, so they start new baselines and are compared as rebuilds.
- Nothing is locked yet.
