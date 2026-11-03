# Phase 4 rules ledger

His rules as built into the engine. If a line is wrong, say so before the cycle code is written.

1. BOS, CHoCH and POI boxes are wick to wick. Fresh, used and dead follow body closes only.
2. The breaker is any broken BOS POI. "THE breaker" dies on the same bar as the CHoCH; the others are stack breakers. A broken CHoCH-born POI is not an entry. Entry is the near edge.
3. FVG belongs to CHoCH only, before or within the breaker box. The FVG variant enters at the gap midpoint and the plain breaker is traded as well. A BOS never carries an FVG. A BOS right after a CHoCH is the inducement.
4. The OB entry is the CHoCH's own POI. It is placed when the inducement prints and enters at the near edge. It hunts the breaker's stops.
5. The ceiling is one object, fixed at the CHoCH down, never moving. A body close above it ends the buy scan; that close is the HTF BOS and the next pullback starts.
6. Static 1:3 first. Stop = far edge -/+ 0.2 x ATR(H1,14).
7. Bias comes from the table logic: bullish, bearish or reversing.

## Engine conventions (lookahead guard)

- A swing is confirmed at the close of the bar N bars after it and is usable from the next bar.
- A structure event is stamped with the close time of the breaking bar.
- H1/H4/D1 bars are delivered only after they close, on the New York 17:00 clock, before the M15 bar that closes at the same instant.
- Every decision stores known_at, the latest bar close it used, and known_at must not be later than the decision time.
- Signal code lives in src/research/engine and cannot import the trade simulator. The CI grep enforces the bans there.
