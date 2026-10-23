# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: exp01_minute_entry (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants are read from so.config. A change after a development run
is a new PROTOCOL_VERSION, recorded in PROTOCOL.md.
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "exp01_minute_entry"
PROTOCOL_VERSION = "1.0"

"""
Rows And Labels
"""

# DEFINE THE DECISION GRID (ONE ROW EVERY 15 MINUTES: ENTRIES AT 10:00, 10:15, ...)
SAMPLE_EVERY_N_MINUTES = 15
# DEFINE THE FEATURE SOURCES AND THE SCALE TYPES USED BY THE MODEL
FEATURE_SOURCE_LIST = ["TSIND", "TSSEG", "TSCTX"]
MODEL_FEATURE_SCALE_TYPE_LIST = ["ratio", "bounded", "categorical", "count", "time"]
# DEFINE THE TAKE-PROFIT DISTANCES MODELLED (ONE CLASSIFIER EACH; THE STOP IS RR_RATIO x THE DISTANCE)
MODEL_DELTA_LIST = list(config.TRAIN_DELTA_LIST)

"""
Model: one LightGBM classifier per distance, P(take profit first), uniqueness-weighted
"""

# DEFINE THE RETRAINING FREQUENCY, THE TRAINING-WINDOW CANDIDATES AND THE MINIMUM ROWS OF A REFIT
RETRAIN_FREQUENCY_STR = "weekly"
TRAIN_WINDOW_YEARS_LIST = [3, 5, 10]
MIN_TRAIN_ROW_COUNT = 200
# DEFINE THE LIGHTGBM PARAMETERS (FIXED THREADS AND deterministic SO A REFIT IS REPRODUCIBLE)
LGBM_PARAM_DICT = {
    "n_estimators": 300,
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 200,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "reg_lambda": 1.0,
    "verbosity": -1,
    "n_jobs": 4,
    "deterministic": True,
    "force_col_wise": True,
    "random_state": config.RANDOM_SEED,
}

"""
Entry Policy
"""

# DEFINE THE EXPECTED NET RETURN THRESHOLDS (FRACTION PER TRADE): ENTER WHEN THE BEST DISTANCE'S EXPECTED NET RETURN IS ABOVE
EV_THRESHOLD_LIST = [0.0, 0.0002, 0.0005, 0.001]

"""
Schedule And Selection
"""

# DEFINE THE EMBARGO (SESSIONS; THE 10-SESSION HOLDING LIMIT) AND THE FOLD TRAINING LENGTH OF THE PERIOD SCHEDULE
EMBARGO_TRADING_DAYS = 10
FIXED_TRAIN_WINDOW_YEARS = 10
# DEFINE HOW MANY COMPLETED PERIODS ARE POOLED WHEN A CANDIDATE IS CHOSEN (THE PREVIOUS QUARTER)
SELECTION_POOLED_QUARTER_COUNT = 1
