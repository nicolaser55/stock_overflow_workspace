# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: exp02_stop_reentry (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants (daily features, execution, costs, statistics, walk-forward
conventions, exploration period) are READ from so.config, never copied. The trial-log configuration hash covers both
files (so.core.trial_log.get_config_hash_str).

Rule: once the first validation run of step 04 exists, any change to a constant below is a new protocol version with a
new EXPERIMENT_NAME, recorded in PROTOCOL.md.
"""

"""
Experiment
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "exp02_stop_reentry"
PROTOCOL_VERSION = "1.0"

"""
Strategy Rules (PROTOCOL.md §5; trading rules identical to stop_reentry_v2)
"""

# DEFINE THE TRAILING STOP MULTIPLIER CANDIDATES (STOP DISTANCE = k x daily_volatility)
STOP_K_LIST = [3, 4, 5]
# DEFINE THE RE-ENTRY THRESHOLD OFFSETS (p* = TRAINING BASE RATE + OFFSET)
REENTRY_THRESHOLD_OFFSET_LIST = [-0.05, 0.0, 0.05]
# DEFINE THE MAXIMUM NUMBER OF DECISIONS IN CASH BEFORE A FORCED RE-ENTRY
MAX_CASH_SESSIONS = 60

"""
Walk-Forward (step 04; window lengths and step are the shared conventions of so.config)
"""

# DEFINE THE EMBARGO BETWEEN WINDOWS (SESSIONS; MUST BE >= config.LABEL_HORIZON_SESSIONS)
EMBARGO_TRADING_DAYS = 20
# DEFINE THE LENGTH OF THE FIXED TRAINING WINDOW (YEARS; THE SCHEDULE IS BUILT WITH IT AND THE FOLD MUST FIT IT)
FIXED_TRAIN_WINDOW_YEARS = 10
# DEFINE THE TRAINING WINDOW CANDIDATES ("10y" = FIXED_TRAIN_WINDOW_YEARS, "all" = every session since the start of the data)
TRAIN_WINDOW_LIST = ["10y", "all"]
# DEFINE THE NUMBER OF VALIDATION QUARTERS POOLED FOR THE SELECTION (CURRENT FOLD + PREVIOUS FOLDS)
SELECTION_POOLED_QUARTER_COUNT = 4

"""
Model (PROTOCOL.md §8)
"""

# DEFINE THE PRIMARY MODEL ("logistic") AND THE DIAGNOSTIC MODEL ("lgbm")
PRIMARY_MODEL_STR = "logistic"
DIAGNOSTIC_MODEL_STR = "lgbm"
# DEFINE THE LOGISTIC REGRESSION INVERSE REGULARIZATION STRENGTH (SMALLER = STRONGER REGULARIZATION)
LOGISTIC_C = 0.1
# DEFINE THE LIGHTGBM PARAMETERS (SHALLOW, STRONGLY REGULARIZED: ABOUT 2,500 DAILY ROWS PER 10 YEARS)
LGBM_PARAM_DICT = {
    "n_estimators": 200,
    "learning_rate": 0.02,
    "num_leaves": 4,
    "max_depth": 2,
    "min_child_samples": 100,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 5.0,
    "random_state": config.RANDOM_SEED,
    "verbose": -1,
}

"""
Baselines (PROTOCOL.md §10)
"""

# DEFINE THE FIXED-DELAY RE-ENTRY BASELINES (CASH DECISIONS BEFORE RE-ENTRY)
FIXED_DELAY_SESSION_LIST = [1, 5, 20]
# DEFINE THE NUMBER OF RANDOM RE-ENTRY RUNS
RANDOM_REENTRY_RUN_COUNT = 20
# DEFINE THE MOVING AVERAGE OF THE TEXTBOOK TREND RULE (SESSIONS)
TREND_RULE_MA_SESSIONS = 200

"""
Signal Check (step 02, PROTOCOL.md §11.1)
"""

# DEFINE THE NUMBER OF QUANTILE BINS PER FEATURE
DAILY_SIGNAL_CHECK_BIN_COUNT = 5
# DEFINE THE MINIMUM NUMBER OF ROWS IN A TRAINING BIN BEFORE IT COUNTS AS A TEST
DAILY_SIGNAL_CHECK_MIN_BIN_COUNT = 40
# DEFINE THE MINIMUM NUMBER OF DISTINCT CALENDAR MONTHS OF A BIN, IN EACH WINDOW, BEFORE ITS PASS COUNTS (NEW IN exp02 1.0)
DAILY_SIGNAL_CHECK_MIN_MONTH_COUNT = 6
