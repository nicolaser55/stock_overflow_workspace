# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: exp07_warning_lights_exit (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants (daily features, execution, costs, statistics, walk-forward
conventions, exploration period) are READ from so.config, never copied. The trial-log configuration hash covers both
files (so.core.trial_log.get_config_hash_str).

Rule: once the first validation run of step 02 exists, any change to a constant below is a new protocol version with a
new EXPERIMENT_NAME, recorded in PROTOCOL.md.
"""

"""
Experiment
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "exp07_warning_lights_exit"
PROTOCOL_VERSION = "1.0"

"""
Warning Lights (PROTOCOL.md §5; thresholds fixed by the roadmap, never fitted)
"""

# DEFINE THE LIGHTS: NAME -> (DAILY FEATURE, COMPARISON, THRESHOLD); A MISSING FEATURE IS AN OFF LIGHT
LIGHT_DICT = {
    "below_ma200": ("ma200_dist_pct", "<", 0.0),
    "return_250d_negative": ("return_250d", "<", 0.0),
    "volatility_rising": ("volatility_ratio_20_60", ">", 1.2),
    "ath_drawdown_10pct": ("ath_drawdown_pct", "<", -0.10),
    "high60_stale": ("sessions_since_high60", ">", 20),
}
# DEFINE THE EXIT THRESHOLDS k (EXIT WHEN AT LEAST k LIGHTS ARE ON; BUY BACK WHEN FEWER THAN k - 1 ARE ON)
LIGHT_K_LIST = [3, 4, 5]
# DEFINE THE MAXIMUM NUMBER OF CASH DECISIONS BEFORE A FORCED RE-ENTRY (None = NEVER: THE RULE ALONE DECIDES)
MAX_CASH_SESSIONS = None

"""
Replay (step 02): one continuous path over the validation quarters of the exp02-exp06 schedule
"""

# DEFINE THE EMBARGO AND THE FIXED TRAINING WINDOW USED TO BUILD THE SCHEDULE (NO MODEL; SAME 44 QUARTERS AS exp02-exp06)
EMBARGO_TRADING_DAYS = 20
FIXED_TRAIN_WINDOW_YEARS = 10
# DEFINE THE NUMBER OF PERIODS POOLED FOR THE SELECTION (CURRENT PERIOD + PREVIOUS PERIODS)
SELECTION_POOLED_QUARTER_COUNT = 4
# DEFINE THE FIRST DATE OF THE UNTOUCHED DATA (NO REPLAY MAY END ON OR AFTER IT)
UNTOUCHED_START_DATE_STR = "2026-05-14"

"""
Baselines And Statistics (PROTOCOL.md §7, §8)
"""

# DEFINE THE NUMBER OF RUNS PER RANDOM FAMILY AND THE SEED OFFSET OF THE RANDOM EXITS
RANDOM_RUN_COUNT = 20
RANDOM_EXIT_SEED_OFFSET = 1000
# DEFINE THE MONTHS PER BLOCK OF THE PRIMARY LOG-EXCESS BOOTSTRAP (THE 1-MONTH VERSION IS PRINTED ALONGSIDE)
BOOTSTRAP_BLOCK_MONTH_COUNT = 6
