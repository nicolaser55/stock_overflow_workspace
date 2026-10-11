# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: expNN_<name> (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants are READ from so.config, never copied. The trial-log
configuration hash covers both files (so.core.trial_log.get_config_hash_str).

Rule: once the first validation run exists, any change to a constant below is a new protocol version with a new
EXPERIMENT_NAME, recorded in PROTOCOL.md.
"""

"""
Experiment
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "expNN_name"
PROTOCOL_VERSION = "1.0"

"""
Rules / Model / Walk-Forward / Baselines (one section per topic, every constant commented)
"""

# DEFINE THE EMBARGO BETWEEN WINDOWS (SESSIONS; MUST BE >= THE LONGEST LABEL OR HOLDING HORIZON)
EMBARGO_TRADING_DAYS = 20
# DEFINE THE FIXED TRAINING WINDOW THAT A FOLD MUST FIT (YEARS)
FIXED_TRAIN_WINDOW_YEARS = 10
# DEFINE THE NUMBER OF VALIDATION QUARTERS POOLED FOR THE SELECTION
SELECTION_POOLED_QUARTER_COUNT = 4

"""
Holdout
"""

# THE DEVELOPMENT BOUNDARY IS NOT A DATE IN THIS FILE
# It is the session an embargo before the active holdout start (so.core.holdout.get_development_end_date).
# Validation folds come from so.core.schedule.get_development_fold_pdf (validation windows only).
# Holdout evaluation is run only by Nicolas, once per window (design.py and PROTOCOL.md, "Holdout evaluation").
