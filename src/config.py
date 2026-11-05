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

# --- Practice / exam split (LOCKED, never move) ---
# Practice years: 2016-01-03 up to (not including) PRACTICE_END -- free tuning.
# Exam years: PRACTICE_END onward -- sealed, run once per locked strategy version.
# The Phase 4 practice runner only loads bars that have fully CLOSED by this time.
PRACTICE_END = "2022-07-01"

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

# ======================================================================
# Phase 4 rebuild (SMC cycle engine) -- ADDITIONS ONLY, nothing above changed
# ======================================================================
STOP_BUFFER_ATR = 0.2          # stop = far edge -/+ 0.2 x ATR(H1,14) (replaces the old 0.1)
H4_SWING_N = 2                 # candles each side for H4 swings
LTF_TF = "M15"                 # lower timeframe of the cycle
LTF_SWING_N = 2                # candles each side for M15 swings
BIAS_FIRST_READ_SWINGS = 5     # counted swings for the first read of bias
RR_STATIC = 3.0                # static target = 3R

# --- Switches (defaults; each one is measured, not guessed) ---
TRADE_USED_POIS = False            # False = fresh POIs only; True = used POIs may trade too
PULLBACK_SELL_REQUIRES_FVG = False # FVG not needed for the pullback sell
OB_NO_IDM_REQUIRES_FVG = True      # OB entry without inducement needs an FVG in the CHoCH leg
LTF_STACK_ENTRIES = False          # LTF stack-breaker buys: off by default, measured
ALLOW_STACKING = True              # several zone buys may be open at once
WRONG_COLOUR_SEARCH_DIRECTION = "back"  # assumption 21: look back for the right-colour candle

# --- Bias timeframes (V3 test; default keeps V1 behaviour) ---
# "both" = D1 and H4 must agree.  "h4" = H4 alone decides the bias.
BIAS_TIMEFRAMES = "both"
