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

# Deriv public WebSocket endpoint (app_id=1089 is the public/demo id)
DERIV_WS_URL = "wss://api.derivws.com/trading/v1/options/ws/public"

# ----- SMC parameters -----
SWING_LOOKBACK = 2              # bars before/after to confirm a swing
ATR_PERIOD = 14
EQ_TOLERANCE_ATR = 0.15         # equal highs/lows tolerance (fraction of ATR)
BUFFER_ATR = 0.10               # stop-loss buffer beyond structural level
DISPLACEMENT_ATR_MULT = 1.5     # displacement candle range vs ATR
MIN_RR = 1.0                    # minimum structural R:R to fire a signal
PATTERN_LOOKBACK_BARS = 30      # max bars between sweep -> CHoCH -> BOS

# ----- Telegram -----
TELEGRAM_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
TELEGRAM_CHAT_ID_ENV = "TELEGRAM_CHAT_ID"

# ----- State -----
STATE_FILE = "state.json"
