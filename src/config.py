"""Configuration for the SMC signal bot."""

# ----- Symbols to monitor (v1 scope: 3 forex pairs) -----
SYMBOLS = [
    "frxEURUSD",
    "frxGBPUSD",
    "frxAUDUSD",
]

# ----- Timeframe -----
# Deriv granularity in seconds: 60=M1, 300=M5, 900=M15, 3600=H1, 14400=H4
GRANULARITY = 900
TIMEFRAME_LABEL = "M15"

# ----- Data -----
CANDLE_COUNT = 200

# Deriv production WebSocket endpoint
DERIV_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

# ----- SMC parameters -----
SWING_LOOKBACK = 2                  # bars before/after to confirm a swing
ATR_PERIOD = 14
EQ_TOLERANCE_ATR = 0.15             # equal highs/lows tolerance (fraction of ATR)
BUFFER_ATR = 0.20                   # stop-loss buffer beyond structural level
DISPLACEMENT_ATR_MULT = 1.5         # displacement candle range vs ATR
MIN_RR = 1.5                        # minimum structural R:R to fire a signal
PATTERN_LOOKBACK_BARS = 30          # max bars between sweep -> CHoCH -> BOS

# Quality filters
MIN_SWEEP_PENETRATION_ATR = 0.20    # sweep must pierce pool by at least this * ATR
MAX_BARS_SWEEP_TO_ENTRY = 80        # sweep must be within last 80 bars of entry
MAX_OB_AGE_BARS = 80                # OB must be created within last 80 bars
MIN_OB_WIDTH_ATR = 0.30             # OB zone must be at least this * ATR wide
MIN_TARGET_ATR = 1.00               # TP must be at least this * ATR away from entry

# ----- Backtest outcome simulation -----
MAX_HORIZON_BARS = 96               # 24 hours on M15

# Spread cost as a fraction of ATR. Applied to both entry and exit.
# 0.04 ATR ≈ 0.5 pip on M15 FX with 12-pip ATR. Conservative and realistic.
SPREAD_ATR_FRAC = 0.04

# ----- Telegram -----
TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

# ----- State -----
STATE_FILE = "state.json"
SIGNAL_COOLDOWN_SECONDS = 4 * 3600  # 4 hours

# ----- Reports -----
REPORTS_DIR = "reports"
