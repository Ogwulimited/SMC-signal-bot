"""SMC Research Engine Configuration."""

# ----- Pairs (28 total: 11 original + 17 crosses) -----
PAIRS = [
    # Original 11
    "eurusd", "gbpusd", "usdjpy", "audusd", "usdcad", "usdchf", "nzdusd", "eurjpy", "gbpjpy", "eurgbp", "audjpy",
    # New 17 Crosses
    "eurchf", "eurcad", "euraud", "eurnzd", "gbpchf", "gbpcad", "gbpaud", "gbpnzd",
    "audcad", "audchf", "audnzd", "nzdjpy", "nzdcad", "nzdchf", "cadjpy", "cadchf", "chfjpy"
]

PAIR_GROUPS = {
    "eurusd": "usd_major", "gbpusd": "usd_major", "usdjpy": "usd_major", "audusd": "usd_major",
    "usdcad": "usd_major", "usdchf": "usd_major", "nzdusd": "usd_major",
    "eurgbp": "eur_cross", "eurjpy": "eur_cross", "eurchf": "eur_cross", "eurcad": "eur_cross",
    "euraud": "eur_cross", "eurnzd": "eur_cross",
    "gbpchf": "gbp_cross", "gbpcad": "gbp_cross", "gbpaud": "gbp_cross", "gbpnzd": "gbp_cross",
    "audjpy": "jpy_cross", "gbpjpy": "jpy_cross", "nzdjpy": "jpy_cross", "cadjpy": "jpy_cross", "chfjpy": "jpy_cross",
    "audcad": "commodity_cross", "audchf": "commodity_cross", "audnzd": "commodity_cross",
    "nzdcad": "commodity_cross", "nzdchf": "commodity_cross", "cadchf": "commodity_cross"
}

PAIR_COHORTS = {p: ("original_11" if p in PAIRS[:11] else "new_17") for p in PAIRS}

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
SPREAD_PRICE = {
    # Original 11
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
    # New 17 Crosses (typical retail spread ~2.0 pips)
    "eurchf": 0.00020,
    "eurcad": 0.00020,
    "euraud": 0.00020,
    "eurnzd": 0.00020,
    "gbpchf": 0.00020,
    "gbpcad": 0.00020,
    "gbpaud": 0.00020,
    "gbpnzd": 0.00020,
    "audcad": 0.00020,
    "audchf": 0.00020,
    "audnzd": 0.00020,
    "nzdjpy": 0.020,
    "nzdcad": 0.00020,
    "nzdchf": 0.00020,
    "cadjpy": 0.020,
    "cadchf": 0.00020,
    "chfjpy": 0.020,
}

MAX_SPREAD_RISK_RATIO = 0.15
MIN_TARGET_R = 3.0
TIME_STOP_H1_BARS = 48
