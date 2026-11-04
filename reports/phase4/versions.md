# Phase 4 versions ledger (practice years only)

Cap: 6 versions. Each version is written here and committed BEFORE it runs.
Rebuilding rules and measuring cost no version. Adopting a rule or switch
because a measurement favoured it costs one version.
Exam years (2022-07-01 to 2026-10-01) stay sealed until one version is locked.

Versions used: 1 of 6.

## V1 - pullback system as built (baseline, nothing tuned)

Scope
- Pullback sells only: breaker sell and OB sell, plain variant (no FVG).
- Zone buys are NOT built. Result is not the whole system.

Rules
- Entry: sell limit at the near edge of the breaker box (breaker model) or of the CHoCH box (OB model).
- Stop: far edge + 0.2 x ATR(H1,14). Target: static 1:3.
- Fill at the next M15 open after the touch. Stop wins a same-bar tie.
- Spread skip when spread/risk > 0.15. Net R = gross R - one spread cost.
- Gap loss can exceed 1R. No management after entry. No time stop.
- Ceiling: temporary after the CHoCH, locked after two M15 events.
  A CHoCH up as the first event throws the attempt away.
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

Status: written before the 28-pair run. Result: pending.
