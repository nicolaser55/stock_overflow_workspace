import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp04_trend_exit import config as exp_config
from experiments.exp04_trend_exit.rules import get_rule_candidate_list

"""
Runner Design: exp04_trend_exit_v2_1

Machinery-only port of protocol 2.0 onto the point-in-time runner. Sell after the close has stayed more than x below
the 200-session average for n decisions. Buy back when it is more than x above the average. No model is trained.

decide() is position-independent: 0 on an exit signal, 1 on a re-entry signal, NaN otherwise (keep). The engine turns
those into trades. The n consecutive decisions are counted on the data, whatever the position.
"""

# THE 9 RULES, IN THE PROTOCOL ORDER
_RULE_LIST = get_rule_candidate_list()


# FUNCTION: THE CANDIDATE NAME
def get_candidate_name_str(candidate_dict_in):
    """
    Names one rule. The buffer is printed with two decimals.

    Args:
        candidate_dict_in (dict): One element of get_rule_candidate_list

    Returns:
        str: Name
    """
    # RETURN THE NAME
    return f"{float(candidate_dict_in['buffer']):.2f}|{int(candidate_dict_in['confirmation'])}"


# FUNCTION: PARSE A CANDIDATE NAME
def parse_candidate_dict(candidate_str_in):
    """
    Recovers the rule dictionary from its name.

    Args:
        candidate_str_in (str): Name

    Returns:
        dict: The rule
    """
    # MATCH THE NAME
    for candidate_dict in _RULE_LIST:
        if get_candidate_name_str(candidate_dict) == str(candidate_str_in):
            return candidate_dict
    raise ValueError(f"unknown candidate '{candidate_str_in}'.")


# DEFINE HOW CANDIDATE PERIODS ARE FORMED
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
# DEFINE THE 9 CANDIDATES
CANDIDATE_LIST = [get_candidate_name_str(candidate_dict) for candidate_dict in _RULE_LIST]
# DEFINE THE SELECTION RULE (MEAN OF THE LAST 4 QUARTERS; TIES: LARGER BUFFER, THEN LARGER CONFIRMATION)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT,
                  "tie_break": [("buffer", False), ("confirmation", False)]}
# DEFINE THE TIE COLUMNS THE RUNNER ATTACHES
CANDIDATE_TIE_VALUE_DICT = {
    "buffer": {get_candidate_name_str(candidate_dict): float(candidate_dict["buffer"]) for candidate_dict in _RULE_LIST},
    "confirmation": {get_candidate_name_str(candidate_dict): int(candidate_dict["confirmation"]) for candidate_dict in _RULE_LIST},
}
# COPY THE NAME AND THE PROTOCOL VERSION
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
# EVERY INPUT IS READ THROUGH THE VIEW (SPY BARS ONLY)
DATA_SOURCE_LIST = ["SPY_1MIN"]
# FRACTIONAL ENGINE, BINARY 0/1/KEEP, NO DEAD BAND, START INVESTED
ENGINE_NAME = "fractional"
DEAD_BAND = 0.0
INITIAL_WEIGHT = 1.0
MAX_CASH_SESSIONS = exp_config.MAX_CASH_SESSIONS


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE RULE
def get_candidate_design(candidate_in):
    """
    One buffer/confirmation pair. The runner calls this once per candidate stream.

    Args:
        candidate_in (str): Candidate name

    Returns:
        Design: Fresh object
    """
    # A NEW OBJECT SO PARALLEL STREAMS DO NOT SHARE THE RUNNING AVERAGE
    return Design(parse_candidate_dict(candidate_in))


# CLASS: ONE TREND-EXIT CANDIDATE
class Design:
    """Buffer x and confirmation n. decide(view) returns 0, 1 or NaN from the 200-session distance."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME

    # FUNCTION: STORE THE RULE AND EMPTY HISTORY
    def __init__(self, candidate_dict_in):
        """
        Args:
            candidate_dict_in (dict): buffer, confirmation
        """
        # THE RULE IS FIXED FOR THE STREAM
        self.buffer_float = float(candidate_dict_in["buffer"])
        self.confirmation_int = int(candidate_dict_in["confirmation"])
        self.complete_close_list = []
        self.below_list = []
        self.seeded_bool = False

    # FUNCTION: CATCH THE COMPLETE-CLOSE AND BELOW HISTORY UP TO THIS VIEW
    def _update_history(self, view_in):
        """
        Previous sessions' complete closes (15:59) and below-x flags, then today's distance. Counted on the data.

        Args:
            view_in: DecisionView

        Returns:
            float: Today's ma200_dist_pct (NaN before 200 complete closes)
        """
        # THE VIEW ENDS AT THE DECISION BAR. A FINISHED SESSION'S LAST BAR IS THE BAR BEFORE THE NEXT START.
        bar_dict = view_in.get_bar_array_dict()
        close_arr = np.asarray(bar_dict["close_arr"], dtype=float)
        start_idx_arr = np.asarray(bar_dict["session_start_idx_arr"], dtype=int)
        session_count = len(bar_dict["session_date_list"])
        offset_int = int(config.DECISION_BAR_OFFSET_FROM_END)
        if session_count < 1 or len(close_arr) < 1:
            return np.nan
        # COMPLETE CLOSES OF EVERY FINISHED SESSION IN THE VIEW (THE 15:59 BAR, WHICH IS IN THE SLICE)
        finished_count = session_count - 1
        while len(self.complete_close_list) < finished_count:
            session_idx = len(self.complete_close_list)
            complete_idx = int(start_idx_arr[session_idx + 1]) - 1
            self.complete_close_list.append(float(close_arr[complete_idx]))
        # BELOW FLAGS FOR PRIOR SESSIONS, FROM THEIR 15:58 CLOSE OVER THE PREVIOUS 200 COMPLETE CLOSES
        while len(self.below_list) < finished_count:
            session_idx = len(self.below_list)
            if session_idx < 200:
                self.below_list.append(False)
                continue
            complete_idx = int(start_idx_arr[session_idx + 1]) - 1
            decision_idx = max(int(start_idx_arr[session_idx]), complete_idx - offset_int)
            decision_close = float(close_arr[decision_idx])
            mean_close = float(np.mean(self.complete_close_list[session_idx - 200:session_idx]))
            dist_float = decision_close / mean_close - 1.0 if mean_close > 0 else np.nan
            self.below_list.append(bool(np.nan_to_num(dist_float, nan=0.0) < -self.buffer_float))
        # TODAY: DECISION CLOSE OVER THE PREVIOUS 200 COMPLETE CLOSES
        if finished_count < 200:
            today_dist = np.nan
        else:
            today_close = float(close_arr[-1])
            mean_close = float(np.mean(self.complete_close_list[finished_count - 200:finished_count]))
            today_dist = today_close / mean_close - 1.0 if mean_close > 0 else np.nan
        today_below = bool(np.nan_to_num(today_dist, nan=0.0) < -self.buffer_float)
        if len(self.below_list) == finished_count:
            self.below_list.append(today_below)
        else:
            self.below_list[-1] = today_below
        self.seeded_bool = True
        return today_dist

    # FUNCTION: TARGET WEIGHT AT THIS DECISION
    def decide(self, view_in):
        """
        0 when the last n distances are below -x, 1 when today's distance is above +x, NaN otherwise.

        Args:
            view_in: DecisionView

        Returns:
            float: 0, 1 or NaN
        """
        # SIGNALS ARE COUNTED ON THE DATA, WHATEVER THE POSITION
        today_dist = self._update_history(view_in)
        n_int = self.confirmation_int
        if n_int <= len(self.below_list) and all(self.below_list[-n_int:]):
            return 0.0
        if np.nan_to_num(today_dist, nan=0.0) > self.buffer_float:
            return 1.0
        return np.nan
