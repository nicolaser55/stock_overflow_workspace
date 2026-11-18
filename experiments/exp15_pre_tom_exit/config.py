from datetime import date
# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: exp15_pre_tom_exit (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants are READ from so.config, never copied. The trial-log
configuration hash covers both files (so.core.trial_log.get_config_hash_str).

Rule: once the first validation run exists, any change to a constant below is a new protocol version with a new
EXPERIMENT_NAME, recorded in PROTOCOL.md.

Review 1 (Claude, 2026-11-18) applied: fractional 0/1 engine, rule-coded calendar, 4-candidate grid, 10-year folds.
"""

"""
Experiment
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "exp15_pre_tom_exit"
PROTOCOL_VERSION = "1.0"

"""
Candidates (window width x settlement rule)
"""

# DEFINE THE FOUR CANDIDATES IN PROTOCOL ORDER
CANDIDATE_LIST = ["w84|fixed", "w84|shift", "w54|fixed", "w54|shift"]
# DEFINE THE BASE OFFSET WINDOW UNDER T+3 (INCLUSIVE START, END RELATIVE TO DAY T)
CANDIDATE_WINDOW_DICT = {
    "w84|fixed": (-8, -4),
    "w84|shift": (-8, -4),
    "w54|fixed": (-5, -4),
    "w54|shift": (-5, -4),
}
# DEFINE WHETHER THE WINDOW STAYS FIXED OR SHIFTS WITH SETTLEMENT
CANDIDATE_SETTLEMENT_DICT = {
    "w84|fixed": "fixed",
    "w84|shift": "shift",
    "w54|fixed": "fixed",
    "w54|shift": "shift",
}

"""
Settlement eras (SEC compliance dates; era of a month = era in force on that month's day T)
"""

# DEFINE THE FIRST SESSION OF EACH SHORTER SETTLEMENT CYCLE
SETTLEMENT_T2_START_DATE = date(2017, 9, 5)
SETTLEMENT_T1_START_DATE = date(2024, 5, 28)
# DEFINE HOW MANY TRADING DAYS LATER THE WINDOW MOVES UNDER shift (T+3 BASE = 0)
SETTLEMENT_SHIFT_DICT = {"t3": 0, "t2": 1, "t1": 2}

"""
Calendar
"""

# DEFINE THE FIRST YEAR JUNETEENTH IS A SCHEDULED NYSE HOLIDAY
JUNETEENTH_FIRST_YEAR_INT = 2022
# DOCUMENT UNSCHEDULED CLOSURES THAT STILL COUNT AS DESIGN-CALENDAR SESSIONS (NO LOOK-AHEAD EXCLUSION)
UNSCHEDULED_CLOSURE_DATE_TUPLE = (
    date(2007, 1, 2),
    date(2012, 10, 29),
    date(2012, 10, 30),
    date(2018, 12, 5),
)

"""
Engine
"""

# DEFINE THE DEAD BAND (0/1 TARGETS; ANY CHANGE REBALANCES)
DEAD_BAND = 0.0
# DEFINE THE STARTING WEIGHT (INVESTED BY DEFAULT)
INITIAL_WEIGHT = 1.0

"""
Schedule And Selection (shared conventions)
"""

# DEFINE THE EMBARGO BETWEEN WINDOWS (SESSIONS; THE LABEL HORIZON, READ FROM THE SHARED CONFIG)
EMBARGO_TRADING_DAYS = config.LABEL_HORIZON_SESSIONS
# DEFINE THE FOLD-SCHEDULE TRAINING LENGTH (YEARS). SCORED VALIDATION QUARTERS ARE THEN 2015-2024
FOLD_TRAIN_WINDOW_YEARS = 10
# DEFINE HOW MANY COMPLETED QUARTERS ARE POOLED WHEN A CANDIDATE IS CHOSEN
SELECTION_POOLED_QUARTER_COUNT = config.CANDIDATE_SELECTION_POOLED_QUARTERS_DEFAULT

"""
Holdout
"""

# THE DEVELOPMENT BOUNDARY IS NOT A DATE IN THIS FILE
# It is the session an embargo before the active holdout start (so.core.holdout.get_development_end_date).
# Validation folds come from so.core.schedule.get_development_fold_pdf (validation windows only).
# Holdout evaluation is run only by Nicolas, once per window (design.py and PROTOCOL.md, "Holdout evaluation").
