"""Configuration for the SMC signal bot."""

SYMBOLS = [
    "frxEURUSD", "frxGBPUSD", "frxAUDUSD", "frxUSDCAD", "frxUSDCHF",
    "frxUSDJPY", "frxNZDUSD", "frxEURGBP", "frxEURJPY", "frxGBPJPY",
    "frxAUDJPY", "frxEURAUD", "frxGBPAUD", "frxCADJPY", "frxNZDJPY",
    "cryBTCUSD", "cryETHUSD", "cryLTCUSD", "cryXRPUSD", "crySOLUSD",
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
MIN_TARGET_ATR = 1.00

# Legacy FVG threshold — kept for backwards compatibility with fvg.py import.
# Set > 0 to enable FVG filtering in the reversal pattern (v2).
# The continuation model uses MIN_CONT_FVG_ATR instead.
MIN_FVG_ATR = 0.0

# ----- Continuation model parameters -----
# Displacement leg must contain an FVG at least this size (fraction of ATR).
MIN_CONT_FVG_ATR = 0.15

# Liquidity pool must be within this many ATR of the OB for the OB to qualify.
CONT_LIQUIDITY_TOL_ATR = 2.0

# OB must be no more than this many bars old when the touch fires.
CONT_MAX_OB_AGE = 200

# For the "confirmed" entry: wait up to this many bars after the touch for
# a confirming close above OB high (bullish) / below OB low (bearish).
CONT_CONFIRMATION_WAIT_BARS = 5

# ----- Entry wait window (reversal model) -----
MAX_WAIT_FOR_FILL_BARS = 30

# ----- HTF bias -----
HTF_GRANULARITY = 86400        # D1
HTF_CANDLE_COUNT = 500         # ~1.4 years of daily bars
HTF_SWING_LOOKBACK = 3

# ----- Backtest outcome simulation -----
MAX_HORIZON_BARS = 48          # 48 H1 bars = 48 hours
SPREAD_ATR_FRAC = 0.04

TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

STATE_FILE = "state.json"
SIGNAL_COOLDOWN_SECONDS = 4 * 3600

REPORTS_DIR = "reports"
