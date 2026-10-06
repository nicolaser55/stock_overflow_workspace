# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Experiment Configuration: exp06_capped_regret_reentry (PROTOCOL.md of this folder)

Every constant specific to this experiment. Shared constants (daily features, execution, costs, statistics, walk-forward
conventions, exploration period) are READ from so.config, never copied. The trial-log configuration hash covers both
files (so.core.trial_log.get_config_hash_str).

DATA-DEPENDENT FOLLOW-UP: the design (an exit signal paired with a buy-stop) was suggested by exp03's validation results
(exit timing better than random exits, buy-back worse than random buy-backs). It is labelled so in PROTOCOL.md.

Rule: once the first validation run of step 02 exists, any change to a constant below is a new protocol version with a
new EXPERIMENT_NAME, recorded in PROTOCOL.md.
"""

"""
Experiment
"""

# DEFINE THE EXPERIMENT NAME (TRIAL LOG AND DATA FOLDER) AND THE PROTOCOL VERSION
EXPERIMENT_NAME = "exp06_capped_regret_reentry"
PROTOCOL_VERSION = "1.0"

"""
Rules (PROTOCOL.md §5): 2 exit signals x 3 buy-stops x 2 cooling-offs = 12 candidates
"""

# DEFINE THE EXIT SIGNALS: NAME -> ORDER (THE ORDER IS A TIE-BREAK: FEWER EXITS FIRST)
#   trend_ma200   15:58 close below the 200-session average (exp04's textbook rule, x = 0, n = 1)
#   ath_1pct      15:58 close within 1% of the all-time high (the middle threshold of exp03's grid)
EXIT_SIGNAL_ORDER_DICT = {"trend_ma200": 0, "ath_1pct": 1}
# DEFINE THE ATH THRESHOLD OF THE ath_1pct SIGNAL
ATH_WITHIN = 0.01
# DEFINE THE BUY-STOPS (BUY BACK WHEN THE 15:58 CLOSE IS AT LEAST b ABOVE THE SALE FILL PRICE)
BUY_STOP_LIST = [0.01, 0.02, 0.03]
# DEFINE THE COOLING-OFF PERIODS (DECISIONS WITHOUT EXIT AFTER A BUY-STOP RE-ENTRY)
COOLING_LIST = [0, 20]
# DEFINE THE MAXIMUM NUMBER OF CASH DECISIONS BEFORE A FORCED RE-ENTRY (None = NEVER: THE RULE ALONE DECIDES)
MAX_CASH_SESSIONS = None

"""
Replay (step 02): one continuous path over the validation quarters of the exp02-exp05 schedule
"""

# DEFINE THE EMBARGO AND THE FIXED TRAINING WINDOW USED TO BUILD THE SCHEDULE (NO MODEL; SAME 44 QUARTERS AS exp02-exp05)
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
