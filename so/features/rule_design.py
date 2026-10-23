import numpy as np
# IMPORT THE DAILY HISTORY
from so.features.view_history import DailyHistory, get_day

"""
Exit / Re-entry Rule Designs On The Trailing-Stop Engine (shared by the daily rule experiments)

A rule design is invested by default. At each 15:58 decision it reports:
    flatten_bool   the exit signal of today (the engine sells at 15:59 only while invested; it also uses the flag for
                   a fresh-exit requirement while in cash)
    target_weight  1 when the re-entry rule fires (the engine buys at 15:59 only while in cash), NaN otherwise
plus optional exit_block_sessions (cooling-off after this re-entry) and require_fresh_exit. No stop: trail_multiple
and volatility are None. A forced buy-back after MAX_CASH_SESSIONS cash decisions is the engine's (design module
constant).

A subclass sets COLUMN_LIST (TSDAY columns it reads) and implements get_exit_bool(row, view) and
get_reentry_dict(row, view, state). It may override update_extra(view) to keep another history (VIX).
Engine state (view.get_engine_state_dict): in_position, last_exit_session (the session of the last sale fill),
last_exit_fill_price, cash_session_count (this decision included).
"""


# FUNCTION: A FEATURE VALUE OR A DEFAULT WHEN IT IS MISSING
def get_value_float(row_in, column_str_in, nan_value_in):
    """
    Args:
        row_in (dict): Today's row
        column_str_in (str): Column
        nan_value_in (float): Value used when the cell is NaN

    Returns:
        float: Value
    """
    # A MISSING FEATURE TAKES THE RULE'S NEUTRAL VALUE
    value_float = float(row_in.get(column_str_in, np.nan))
    return float(nan_value_in) if not np.isfinite(value_float) else value_float


# FUNCTION: HOW MANY LIGHTS ARE ON
def get_light_count_int(row_in, light_dict_in):
    """
    A light is (feature, "<" or ">", threshold). A missing feature is an off light.

    Args:
        row_in (dict): Today's row
        light_dict_in (dict): Light name -> (feature, comparison, threshold)

    Returns:
        int: Lights on
    """
    # COUNT THE LIGHTS THAT ARE ON
    count_int = 0
    for feature_str, comparison_str, threshold in light_dict_in.values():
        value_float = float(row_in.get(feature_str, np.nan))
        if not np.isfinite(value_float):
            continue
        count_int += int(value_float < threshold if comparison_str == "<" else value_float > threshold)
    return count_int


# CLASS: THE SHARED DECIDE OF AN EXIT / RE-ENTRY RULE
class RuleDesign:
    """Subclasses define COLUMN_LIST, get_exit_bool and get_reentry_dict."""

    COLUMN_LIST = []

    # FUNCTION: STORE THE CANDIDATE AND AN EMPTY HISTORY
    def __init__(self, candidate_str_in, candidate_dict_in):
        """
        Args:
            candidate_str_in (str): Candidate name
            candidate_dict_in (dict): Candidate parameters
        """
        # THE CANDIDATE IS FIXED FOR THE STREAM
        self.candidate_str = str(candidate_str_in)
        self.candidate_dict = dict(candidate_dict_in)
        self.history = DailyHistory(list(self.COLUMN_LIST))
        self.decision_count_int = 0

    # FUNCTION: OTHER HISTORIES (DEFAULT NONE)
    def update_extra(self, view_in):
        """
        Args:
            view_in: DecisionView

        Returns:
            None
        """
        # NOTHING BY DEFAULT
        return None

    # FUNCTION: TODAY'S EXIT SIGNAL
    def get_exit_bool(self, row_in, view_in):
        """
        Args:
            row_in (dict): Today's TSDAY row
            view_in: DecisionView

        Returns:
            bool: Exit signal
        """
        # SUBCLASSES DEFINE IT
        raise NotImplementedError("get_exit_bool")

    # FUNCTION: TODAY'S RE-ENTRY DECISION (CALLED ONLY IN CASH)
    def get_reentry_dict(self, row_in, view_in, state_dict_in):
        """
        Args:
            row_in (dict): Today's TSDAY row
            view_in: DecisionView
            state_dict_in (dict): Engine snapshot

        Returns:
            dict: reentry_bool and optional exit_block_sessions, require_fresh_exit, reentry_reason
        """
        # SUBCLASSES DEFINE IT
        raise NotImplementedError("get_reentry_dict")

    # FUNCTION: THE DECISION AT THIS MOMENT
    def decide(self, view_in):
        """
        Args:
            view_in: DecisionView

        Returns:
            dict: target_weight, flatten_bool, exit_block_sessions, require_fresh_exit, reentry_reason
        """
        # HISTORIES FIRST, THEN TODAY'S ROW AND THE ENGINE SNAPSHOT
        row_dict = self.history.update(view_in)
        self.update_extra(view_in)
        self.decision_count_int += 1
        if row_dict is None:
            return {"target_weight": np.nan, "flatten_bool": False}
        state_dict = view_in.get_engine_state_dict()
        exit_bool = bool(self.get_exit_bool(row_dict, view_in))
        decision_dict = {"target_weight": np.nan, "flatten_bool": exit_bool, "trail_multiple": None, "volatility": None}
        if not state_dict["in_position"] and state_dict.get("last_exit_session") is not None:
            reentry_dict = self.get_reentry_dict(row_dict, view_in, state_dict)
            if reentry_dict.get("reentry_bool"):
                decision_dict.update({"target_weight": 1.0,
                                      "exit_block_sessions": int(reentry_dict.get("exit_block_sessions", 0)),
                                      "require_fresh_exit": bool(reentry_dict.get("require_fresh_exit", False)),
                                      "reentry_reason": str(reentry_dict.get("reentry_reason", "rule"))})
        return decision_dict

    # FUNCTION: A COLUMN'S VALUES FROM THE LAST EXIT SESSION THROUGH TODAY
    def get_since_exit_arr(self, column_str_in, state_dict_in):
        """
        Args:
            column_str_in (str): Column in COLUMN_LIST
            state_dict_in (dict): Engine snapshot (last_exit_session)

        Returns:
            np.ndarray: Values of the sessions on or after the exit session
        """
        # THE HISTORY IS IN DATE ORDER
        exit_day = get_day(state_dict_in["last_exit_session"])
        date_arr = np.asarray(self.history.date_list, dtype=object)
        start_idx = int(np.searchsorted(date_arr, exit_day, side="left"))
        return self.history.value_arr(column_str_in)[start_idx:]
