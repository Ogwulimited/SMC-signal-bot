"""Configuration for the SMC signal bot — LIVE (v1)."""

# Frozen model: only the 19 recommended pairs from the per-symbol backtest.
RECOMMENDED_PAIRS = [
    "frxAUDNZD",
    "frxNZDCHF",
    "frxEURAUD",
    "frxGBPAUD",
    "frxEURNZD",
    "frxNZDCAD",
    "frxAUDJPY",
    "frxGBPUSD",
    "cryETHUSD",
    "frxNZDJPY",
    "cryBTCUSD",
    "frxGBPCHF",
    "frxEURCHF",
    "frxEURUSD",
    "frxGBPNZD",
    "frxUSDCHF",
    "frxAUDCAD",
    "frxUSDJPY",
    "frxCADJPY",
]

# Backwards-compat alias (backtests use SYMBOLS)
SYMBOLS = RECOMMENDED_PAIRS

GRANULARITY = 3600
TIMEFRAME_LABEL = "H1"

CANDLE_COUNT = 200
DERIV_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

# ----- SMC parameters -----
SWING_LOOKBACK = 2
ATR_PERIOD = 14
EQ_TOLERANCE_ATR = 0.15
BUFFER_ATR = 0.20
DISPLACEMENT_ATR_MULT = 1.5
MIN_RR = 1.5
PATTERN_LOOKBACK_BARS = 30

MIN_OB_WIDTH_ATR = 0.30
MIN_TARGET_ATR = 1.00

MIN_FVG_ATR = 0.0

# ----- Continuation model -----
MIN_CONT_FVG_ATR = 0.05
CONT_LIQUIDITY_TOL_ATR = 3.0
CONT_MAX_OB_AGE = 800
CONT_MAX_BARS_BOS_TO_TOUCH = 150
CONT_CONFIRMATION_WAIT_BARS = 5

# ----- Target selection -----
PREFER_MAJOR_LIQ_ATR = 5.0

# ----- Time-based liquidity -----
USE_TIME_BASED_LIQUIDITY = True

# ----- Backtest performance -----
DETECT_WINDOW = 1000

# ----- Entry wait window (reversal model) -----
MAX_WAIT_FOR_FILL_BARS = 30

# ----- HTF bias (D1) -----
HTF_GRANULARITY = 86400
HTF_CANDLE_COUNT = 500
HTF_SWING_LOOKBACK = 3

# ----- Backtest outcome simulation -----
MAX_HORIZON_BARS = 48
SPREAD_ATR_FRAC = 0.04

# ----- Telegram -----
TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

# ----- State -----
STATE_FILE = "state.json"
SIGNAL_COOLDOWN_SECONDS = 3600  # 1 hour between same symbol+direction

# ----- Trade monitor -----
TRADES_FILE = "trades.json"
MONITOR_GRANULARITY = 900                    # M15 bars for outcome checks
MAX_TRADE_DURATION_SECONDS = 48 * 3600       # 48h timeout → 0R
MONITOR_CANDLE_COUNT = 300                   # ~3 days of M15 candles per check

# ----- Reports -----
REPORTS_DIR = "reports"
