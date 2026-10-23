import numpy as np
# IMPORT THE EXPERIMENT CONFIGURATION AND THE SHARED RULE DESIGN
from experiments.exp04_trend_exit import config as exp_config
from so.features.rule_design import RuleDesign, get_value_float

"""
Runner Design: exp04_trend_exit

Invested by default. Sell at 15:59 after the 15:58 close has been more than x below the 200-session average for n
consecutive decisions (counted on the data, whatever the position). Buy back when it is more than x above the
average. A missing distance (the first 200 sessions) never signals. Trailing-stop engine without a stop.
"""

# THE 9 CANDIDATES: BUFFER, THEN CONFIRMATION
_CANDIDATE_DICT_LIST = [{"buffer": float(buffer), "confirmation": int(confirmation), "name": f"{float(buffer):.2f}|{int(confirmation)}"}
                        for buffer in exp_config.BUFFER_LIST for confirmation in exp_config.CONFIRMATION_LIST]
_CANDIDATE_BY_NAME_DICT = {candidate_dict["name"]: candidate_dict for candidate_dict in _CANDIDATE_DICT_LIST}

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
CANDIDATE_LIST = [candidate_dict["name"] for candidate_dict in _CANDIDATE_DICT_LIST]
# TIES: LARGER BUFFER, THEN LARGER CONFIRMATION
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("buffer", False), ("confirmation", False)]}
CANDIDATE_TIE_VALUE_DICT = {"buffer": {name: _CANDIDATE_BY_NAME_DICT[name]["buffer"] for name in CANDIDATE_LIST},
                            "confirmation": {name: _CANDIDATE_BY_NAME_DICT[name]["confirmation"] for name in CANDIDATE_LIST}}
DATA_SOURCE_LIST = ["SPY_1MIN", "TSDAY"]
ENGINE_NAME = "trailing_stop"
INITIAL_WEIGHT = 1.0
MAX_CASH_SESSIONS = exp_config.MAX_CASH_SESSIONS


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Candidate name

    Returns:
        Design: Fresh object
    """
    # UNKNOWN NAMES ARE A DESIGN ERROR
    if str(candidate_in) not in _CANDIDATE_BY_NAME_DICT:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return Design(str(candidate_in), _CANDIDATE_BY_NAME_DICT[str(candidate_in)])


# CLASS: ONE BUFFER AND ONE CONFIRMATION
class Design(RuleDesign):
    """Exit after n decisions below -x; buy back above +x."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME
    COLUMN_LIST = ["ma200_dist_pct"]

    # FUNCTION: THE LAST n DISTANCES BELOW -x
    def get_exit_bool(self, row_in, view_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView

        Returns:
            bool: Exit signal
        """
        # THE HISTORY ENDS WITH TODAY; A MISSING DISTANCE COUNTS AS 0 (NOT BELOW)
        n_int = int(self.candidate_dict["confirmation"])
        dist_arr = np.nan_to_num(self.history.value_arr("ma200_dist_pct")[-n_int:], nan=0.0)
        return len(dist_arr) == n_int and bool((dist_arr < -self.candidate_dict["buffer"]).all())

    # FUNCTION: MORE THAN x ABOVE THE AVERAGE
    def get_reentry_dict(self, row_in, view_in, state_dict_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView
            state_dict_in (dict): Engine snapshot

        Returns:
            dict: reentry_bool
        """
        # A MISSING DISTANCE NEVER RE-ENTERS
        return {"reentry_bool": get_value_float(row_in, "ma200_dist_pct", 0.0) > self.candidate_dict["buffer"], "reentry_reason": "rule"}
