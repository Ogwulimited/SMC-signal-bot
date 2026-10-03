"""Configuration for the SMC signal bot."""

SYMBOLS = [
    # Forex majors
    "frxEURUSD", "frxGBPUSD", "frxAUDUSD", "frxUSDCAD", "frxUSDCHF",
    "frxUSDJPY", "frxNZDUSD",
    # Forex crosses
    "frxEURGBP", "frxEURJPY", "frxGBPJPY", "frxAUDJPY", "frxEURAUD",
    "frxGBPAUD", "frxCADJPY", "frxNZDJPY", "frxGBPCHF", "frxGBPNZD",
    "frxGBPCAD", "frxAUDCAD", "frxAUDCHF", "frxAUDNZD", "frxEURCAD",
    "frxEURCHF", "frxEURNZD", "frxCHFJPY",
    # Metals
    "frxXAUUSD", "frxXAGUSD",
    # Crypto
    "cryBTCUSD", "cryETHUSD", "cryLTCUSD", "cryXRPUSD", "crySOLUSD",
    "cryBCHUSD", "cryADAUSD", "cryDOTUSD", "cryMATICUSD", "cryBNBUSD",
    # Volatility indices (24/7 — always-on testing)
    "R_10", "R_25", "R_50", "R_75", "R_100",
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

# Legacy FVG threshold — kept for backwards compat with fvg.py import.
MIN_FVG_ATR = 0.0

# ----- Continuation model parameters -----
# Displacement leg must contain an FVG at least this size (fraction of ATR).
# Loosened from 0.08 to 0.05 for more signals.
MIN_CONT_FVG_ATR = 0.05

# Liquidity pool must be within this many ATR of the OB.
CONT_LIQUIDITY_TOL_ATR = 3.0

# OB must be no more than this many bars old when the touch fires.
CONT_MAX_OB_AGE = 800

# Only consider BOS events that fired within the last N bars.
# Tightened from 200 to 150 to skip stale BOS after the retrace window.
CONT_MAX_BARS_BOS_TO_TOUCH = 150

# For the "confirmed" entry: wait up to this many bars after the touch.
CONT_CONFIRMATION_WAIT_BARS = 5

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
