"""SMC Research Engine Configuration."""

# ----- Pairs -----
PAIRS = ["eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy"]

# ----- Timeframes & Data -----
GRANULARITY = 900  # M15 base
ATR_PERIOD = 14

# ----- Phase 1: Primitives -----
STRUCTURE_SWING_N = 2
LIQUIDITY_SWING_N = 2

# ----- Phase 2: Zones -----
FVG_MIN_SIZE_ATR = 0.05

EQ_LOWS_TOLERANCE_ATR = 0.15
EQ_LOWS_MIN_BARS = 4
EQ_LOWS_MAX_BARS = 120
EQ_LOWS_MIN_CLUSTER = 2

SWING_POOL_MAX_AGE_H1 = 240
SWING_POOL_MAX_AGE_H4 = 60

PDH_PDL_LOOKBACK_DAYS = 3
PWH_PWL_LOOKBACK_WEEKS = 2
PMH_PML_LOOKBACK_MONTHS = 2

OB_MITIGATION_START_OFFSET = 3
OB_SEARCH_BACK_MAX = 5
OB_BREAKER_SEARCH_BACK = 10

SWEEP_RECLAIM_WINDOW = 3

# ----- Reports -----
REPORTS_DIR = "reports"
