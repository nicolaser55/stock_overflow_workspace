# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: exp01_minute_entry (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants (features, execution, costs, statistics, walk-forward
conventions) are READ from so.config, never copied. The trial-log configuration hash covers both files
(so.core.trial_log.get_config_hash_str), so a change to either changes the hash.

Rule: once the first validation run of step 03 exists, any change to a constant below is a new protocol version with a
new EXPERIMENT_NAME (e.g. "exp01_minute_entry_v1_1"), recorded in PROTOCOL.md.
"""

"""
Experiment
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "exp01_minute_entry"
PROTOCOL_VERSION = "1.0"

"""
Sampling And Weights (step 01 / model_dataset.py)
"""

# DEFINE THE SAMPLING MODE OF TRAINING ROWS ("all", "interval", or "event")
SAMPLING_MODE = "interval"
# DEFINE THE INTERVAL BETWEEN SAMPLED ENTRIES (minutes after the first allowed entry)
SAMPLE_EVERY_N_MINUTES = 15
# DEFINE THE SAMPLE WEIGHT MODE ("none" or "uniqueness")
SAMPLE_WEIGHT_MODE = "uniqueness"

"""
Walk-Forward (step 03 / walk_forward.py; window lengths and step are the shared conventions of so.config)
"""

# DEFINE THE EMBARGO BETWEEN TRAINING, VALIDATION AND TEST (sessions; must be >= config.MAX_HOLD_TRADING_DAYS)
EMBARGO_TRADING_DAYS = 10
# DEFINE THE TRAINING WINDOW LENGTH CANDIDATES (years; selected on validation)
TRAIN_WINDOW_YEARS_LIST = [3, 5, 10]
# DEFINE WHETHER THE FINAL MODEL OF A FOLD IS REFIT ON THE WINDOW ENDING JUST BEFORE THE TEST EMBARGO
REFIT_BEFORE_TEST = True

"""
Model And Decision Policy (walk_forward.py)
"""

# DEFINE THE DELTAS THAT RECEIVE A TAKE PROFIT PROBABILITY MODEL
MODEL_DELTA_LIST = config.TRAIN_DELTA_LIST
# DEFINE THE FEATURE SCALE TYPES ALLOWED INTO THE MODEL ("absolute" is excluded until the scaling design is done)
MODEL_FEATURE_SCALE_TYPE_LIST = ["ratio", "bounded", "categorical", "count", "time"]
# DEFINE THE LIGHTGBM PARAMETERS (one binary classifier per delta)
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
}
# DEFINE THE EXPECTED NET RETURN THRESHOLDS TESTED ON VALIDATION (fraction per trade)
EV_THRESHOLD_LIST = [0.0, 0.0002, 0.0005, 0.001]
# DEFINE THE VALIDATION SELECTION METRIC (single validation quarter; ties: shorter window, higher threshold)
SELECTION_METRIC_STR = "total_return"

"""
Baselines (same simulator, same costs)
"""

# DEFINE THE NUMBER OF RANDOM ENTRY BASELINE RUNS PER WINDOW
RANDOM_BASELINE_RUN_COUNT = 20
# DEFINE THE FIXED DELTA USED BY THE FIXED-TIME BASELINE
FIXED_TIME_BASELINE_DELTA = 0.005
# DEFINE THE FIXED-TIME BASELINE DECISION TIME (decision row "09:59" -> entry at the 10:00 open)
FIXED_TIME_BASELINE_DECISION_TIME_STR = "09:59"

"""
Signal Check (step 02 / signal_check.py): base-rate version (protocol 1.0, changed from the break-even check of v1)
"""

# DEFINE THE NUMBER OF QUANTILE BINS PER NUMERIC FEATURE
SIGNAL_CHECK_BIN_COUNT = 10
# DEFINE THE MINIMUM NUMBER OF LABELED TRAINING ROWS IN A BIN BEFORE IT COUNTS AS A TEST
SIGNAL_CHECK_MIN_BIN_COUNT = 200
# DEFINE THE MINIMUM NUMBER OF DISTINCT CALENDAR MONTHS OF A BIN, IN EACH WINDOW, BEFORE ITS PASS COUNTS
SIGNAL_CHECK_MIN_MONTH_COUNT = 6
# DEFINE THE TRAINING WINDOW LENGTH OF THE SIGNAL CHECK (years; window of the first pooled fold)
SIGNAL_CHECK_TRAIN_WINDOW_YEARS = 10
# DEFINE THE NUMBER OF MOST RECENT VALIDATION QUARTERS POOLED AS THE SIGNAL CHECK VALIDATION WINDOW
SIGNAL_CHECK_POOLED_QUARTER_COUNT = 4
# DEFINE THE DELTA LIST TESTED BY THE SIGNAL CHECK
SIGNAL_CHECK_DELTA_LIST = config.TRAIN_DELTA_LIST
# DEFINE THE BOOTSTRAP BLOCK OF THE SIGNAL CHECK ("week" or "day"; trades last up to 10 sessions)
SIGNAL_CHECK_BOOTSTRAP_BLOCK_STR = "week"

"""
Honest Reporting (step 03)
"""

# DEFINE THE NUMBER OF VALIDATION QUARTERS USED BY THE PRIOR-ONLY SELECTION (v1 rule: the previous quarter only)
PRIOR_SELECTION_QUARTER_COUNT = 1
