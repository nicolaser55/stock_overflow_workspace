# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: exp07_warning_lights_exit (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants are read from so.config. A change after a development run
is a new PROTOCOL_VERSION, recorded in PROTOCOL.md.
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "exp07_warning_lights_exit"
PROTOCOL_VERSION = "1.0"

"""
Rules
"""

# DEFINE THE FIVE WARNING LIGHTS (FEATURE, COMPARISON, THRESHOLD; A MISSING FEATURE IS AN OFF LIGHT)
LIGHT_DICT = {
    "below_ma200": ("ma200_dist_pct", "<", 0.0),
    "return_250d_negative": ("return_250d", "<", 0.0),
    "volatility_rising": ("volatility_ratio_20_60", ">", 1.2),
    "ath_drawdown_10pct": ("ath_drawdown_pct", "<", -0.10),
    "high60_stale": ("sessions_since_high60", ">", 20),
}
# DEFINE THE EXIT THRESHOLDS k (EXIT WHEN AT LEAST k LIGHTS ARE ON; BUY BACK WHEN FEWER THAN k - 1 ARE ON)
LIGHT_K_LIST = [3, 4, 5]
# NO FORCED BUY-BACK
MAX_CASH_SESSIONS = None

"""
Schedule And Selection (shared conventions)
"""

# DEFINE THE EMBARGO AND THE FOLD TRAINING LENGTH THAT FORM THE CANDIDATE PERIODS (VALIDATION QUARTERS)
EMBARGO_TRADING_DAYS = 20
FIXED_TRAIN_WINDOW_YEARS = 10
# DEFINE HOW MANY COMPLETED PERIODS ARE POOLED WHEN A CANDIDATE IS CHOSEN
SELECTION_POOLED_QUARTER_COUNT = config.CANDIDATE_SELECTION_POOLED_QUARTERS_DEFAULT
