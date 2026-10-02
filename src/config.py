"""Configuration for the SMC signal bot."""

SYMBOLS = [
    "frxEURUSD", "frxGBPUSD", "frxAUDUSD", "frxUSDCAD", "frxUSDCHF",
    "frxUSDJPY", "frxNZDUSD", "frxEURGBP", "frxEURJPY", "frxGBPJPY",
    "frxAUDJPY", "frxEURAUD", "frxGBPAUD", "frxCADJPY", "frxNZDJPY",
    "cryBTCUSD", "cryETHUSD", "cryLTCUSD", "cryXRPUSD", "crySOLUSD",
]

GRANULARITY = 900
TIMEFRAME_LABEL = "M15"

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

MIN_SWEEP_PENETRATION_ATR = 0.20
MAX_BARS_SWEEP_TO_ENTRY = 80
MAX_OB_AGE_BARS = 80
MIN_OB_WIDTH_ATR = 0.30
MIN_TARGET_ATR = 1.00

# ----- Entry wait window for prepositioned limit orders -----
MAX_WAIT_FOR_FILL_BARS = 50

# ----- Backtest outcome simulation -----
MAX_HORIZON_BARS = 96
SPREAD_ATR_FRAC = 0.04

TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

STATE_FILE = "state.json"
SIGNAL_COOLDOWN_SECONDS = 4 * 3600

REPORTS_DIR = "reports"
