# SMC-signal-bot

An automated trading-signal bot that detects Smart Money Concepts (SMC) patterns on Deriv market data and delivers signals to a Telegram channel.

**Status:** In active development — v1 is signal-only (no trade execution).

---

## What it does

- Fetches live candle data from the Deriv API.
- Applies a deterministic SMC engine to detect the core pattern:
  - Liquidity sweep → Change of Character (CHoCH) → displacement → order block formation → retracement into the order block.
- Formats the signal and posts it to a Telegram channel.

## What it does NOT do (yet)

- It does **not** execute trades.
- It does **not** guarantee any specific signal frequency or profitability.
- It is **not** financial advice.

## Tech stack

- Python 3.11
- Deriv WebSocket API (market data)
- Telegram Bot API (signal delivery)
- GitHub Actions (scheduling and hosting)

## Roadmap

- **v1** — Single-pattern signal bot on 3 forex pairs, M15 timeframe.
- **v1.1** — Add FVG detection and expand to 30+ pairs / crypto.
- **v2** — Multi-timeframe bias pipeline and full backtesting.
- **v3** — Optional auto-execution on Deriv.

## Disclaimer

This project is for educational and research purposes. It is not financial advice. Trading involves risk. Use at your own discretion.
