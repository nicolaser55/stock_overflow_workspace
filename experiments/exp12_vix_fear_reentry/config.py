# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: exp12_vix_fear_reentry (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants are read from so.config. A change after a development run
is a new PROTOCOL_VERSION, recorded in PROTOCOL.md.
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "exp12_vix_fear_reentry"
PROTOCOL_VERSION = "1.0"

"""
Rules
"""

# DEFINE THE TWO EXITS: E1 = CLOSE BELOW THE 200-SESSION AVERAGE (BACK ABOVE IT RE-ENTERS); E2 = AT LEAST 4 OF exp07'S LIGHTS
E1_MA_DIST_COL_STR = "ma200_dist_pct"
E2_LIGHT_DICT = {
    "below_ma200": ("ma200_dist_pct", "<", 0.0),
    "return_250d_negative": ("return_250d", "<", 0.0),
    "volatility_rising": ("volatility_ratio_20_60", ">", 1.2),
    "ath_drawdown_10pct": ("ath_drawdown_pct", "<", -0.10),
    "high60_stale": ("sessions_since_high60", ">", 20),
}
E2_LIGHT_K = 4
EXIT_RULE_STR_LIST = ["E1", "E2"]
# DEFINE THE THREE VIX MODIFICATIONS
# M1: ALSO RE-ENTER WHEN vix_level_prev <= 0.85 x ITS MAXIMUM SINCE THE EXIT DECISION (THEN A NEW EXIT NEEDS A FRESH SIGNAL)
# M2: ALSO RE-ENTER WHEN vix_term_prev < 1 AFTER IT WAS >= 1 SINCE THE EXIT DECISION (FRESH SIGNAL AS M1)
# M3: IGNORE THE EXIT WHEN vix_term_prev >= 1 OR vix_pct250_prev >= 0.9
MODIFICATION_STR_LIST = ["M1", "M2", "M3"]
M1_FADE_RATIO = 0.85
M2_TERM_THRESHOLD = 1.0
M3_TERM_THRESHOLD = 1.0
M3_PCT250_THRESHOLD = 0.9
# DEFINE THE TIE ORDER (0 WINS)
TIE_ORDER_DICT = {"E2M3": 0, "E2M1": 1, "E2M2": 2, "E1M3": 3, "E1M1": 4, "E1M2": 5}
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
