"""Configuration for the SMC signal bot."""

SYMBOLS = [
    # Forex majors (7)
    "frxEURUSD", "frxGBPUSD", "frxAUDUSD", "frxUSDCAD", "frxUSDCHF",
    "frxUSDJPY", "frxNZDUSD",
    # Forex crosses (10)
    "frxEURGBP", "frxEURJPY", "frxGBPJPY", "frxAUDJPY", "frxEURAUD",
    "frxGBPAUD", "frxCADJPY", "frxNZDJPY", "frxGBPCHF", "frxEURNZD",
    # Metals (2)
    "frxXAUUSD", "frxXAGUSD",
    # Crypto (5)
    "cryBTCUSD", "cryETHUSD", "cryLTCUSD", "cryXRPUSD", "crySOLUSD",
    # Volatility indices (1 — always-on sanity check)
    "R_100",
]

# ----- Timeframe stack: H1 entry, D1 bias -----
GRANULARITY = 3600
TIMEFRAME_LABEL = "H1"

CANDLE_COUNT = 200
DERIV_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

# ----- SMC parameters (shared primitives) -----
SWING_LOOKBACK = 2
ATR_PERIOD = 14
EQ_TOLERANCE_ATR = 0.15
BUFFER_ATR = 0.20
DISPLACEMENT_ATR_MULT = 1.5
MIN_RR = 1.5
PATTERN_LOOKBACK_BARS = 30

MIN_OB_WIDTH_ATR = 0.30
MIN_TARGET_ATR = 0.50

MIN_FVG_ATR = 0.0

# ----- Continuation model parameters -----
MIN_CONT_FVG_ATR = 0.05
CONT_LIQUIDITY_TOL_ATR = 3.0
CONT_MAX_OB_AGE = 800
CONT_MAX_BARS_BOS_TO_TOUCH = 150
CONT_CONFIRMATION_WAIT_BARS = 5

# ----- Backtest performance -----
# Rolling window: only scan this many H1 bars per detection call.
# Must be > CONT_MAX_OB_AGE + CONT_MAX_BARS_BOS_TO_TOUCH to be safe.
DETECT_WINDOW = 1000

# ----- Entry wait window (reversal model) -----
MAX_WAIT_FOR_FILL_BARS = 30

# ----- HTF bias -----
HTF_GRANULARITY = 86400
HTF_CANDLE_COUNT = 500
HTF_SWING_LOOKBACK = 3

# ----- Backtest outcome simulation -----
MAX_HORIZON_BARS = 48
SPREAD_ATR_FRAC = 0.04

TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

STATE_FILE = "state.json"
SIGNAL_COOLDOWN_SECONDS = 4 * 3600

REPORTS_DIR = "reports"
