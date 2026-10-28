"""SMC Research Engine Configuration."""

PAIRS = ["eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy"]

GRANULARITY = 900
ATR_PERIOD = 14

STRUCTURE_SWING_N = 2
LIQUIDITY_SWING_N = 2

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

REPORTS_DIR = "reports"
D1_SWING_N = 3

# --- Phase 4: assumed typical retail spreads (NOT real broker data) ---
# Values are in raw price units (already pip-size-adjusted per pair),
# i.e. directly comparable to price differences in OHLC data.
# Source: generic mid-tier retail broker approximations, logged as an
# explicit assumption per Standing Rules. Revisit if real broker spread
# data becomes available at zero cost.
SPREAD_PRICE = {
    "eurusd": 0.00010,  # 1.0 pip
    "gbpusd": 0.00015,  # 1.5 pip
    "usdjpy": 0.010,    # 1.0 pip (JPY pip = 0.01)
    "audusd": 0.00012,  # 1.2 pip
    "usdcad": 0.00015,  # 1.5 pip
    "usdchf": 0.00018,  # 1.8 pip
    "nzdusd": 0.00020,  # 2.0 pip
    "eurjpy": 0.020,    # 2.0 pip
    "gbpjpy": 0.030,    # 3.0 pip
    "eurgbp": 0.00018,  # 1.8 pip
    "audjpy": 0.020,    # 2.0 pip
}

MAX_SPREAD_RISK_RATIO = 0.15
MIN_TARGET_R = 3.0
TIME_STOP_H1_BARS = 48
