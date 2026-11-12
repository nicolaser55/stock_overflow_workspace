"""
Synthetic design for the intraday decision time tests (R4c, 2026-11-11).

Three candidates, called at 12:00 and 15:30 as well as at 15:58 (fractional engine):
    drop    at 15:30, sell everything when the close is below the previous session's close; back to weight 1 at 15:58
    keep    "keep" at every intraday call; weight 1 at 15:58 (must equal a daily-only weight-1 design)
    packed  at every intraday call, a weight that moves with the close (any leak changes it); weight 1 at 15:58
No file I/O. Tests inject periods.
"""

# THE THREE CANDIDATES
CANDIDATE_LIST = ["drop", "keep", "packed"]
# DEVELOPMENT QUARTERS (TESTS INJECT PERIODS)
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
# POOL THE LAST TWO PERIODS
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("candidate", True)]}
# TRIAL LOG CONSTANTS
EXPERIMENT_NAME = "runner_intraday_test"
PROTOCOL_VERSION = "r4c"
# SPY BARS ONLY
DATA_SOURCE_LIST = ["SPY_1MIN"]
# ENGINE CONSTANTS
ENGINE_NAME = "fractional"
DEAD_BAND = 0.0
INITIAL_WEIGHT = 1.0
# THE INTRADAY DECISION TIMES (MODULE AND CLASS)
INTRADAY_DECISION_TIME_LIST = ["12:00", "15:30"]


# FUNCTION: A WEIGHT IN (0, 1) THAT MOVES WITH THE CLOSE
def get_packed_weight_float(close_float_in):
    """
    Args:
        close_float_in (float): Close of the call's bar

    Returns:
        float: Weight
    """
    # CLOSE IS O(100)
    packed_float = 0.5 + (float(close_float_in) - 100.0) / 1000.0
    return min(max(packed_float, 0.01), 0.99)


# CLASS: ONE RULE
class IntradayDesign:
    """decide(view) at 12:00, 15:30 and 15:58."""

    # SPY ONLY; THE SAME TIMES AS THE MODULE
    DATA_SOURCE_LIST = ["SPY_1MIN"]
    INTRADAY_DECISION_TIME_LIST = ["12:00", "15:30"]

    # FUNCTION: STORE THE RULE
    def __init__(self, rule_str_in):
        """
        Args:
            rule_str_in (str): drop, keep or packed
        """
        # THE CANDIDATE'S RULE
        self.rule_str = str(rule_str_in)

    # FUNCTION: DECIDE
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float | None: Target weight (None = keep)
        """
        # THE 15:58 CALL: BACK TO FULLY INVESTED
        time_str = view_in.intraday_time_str
        if time_str is None:
            return 1.0
        bar_dict = view_in.get_bar_array_dict()
        close_float = float(bar_dict["close_arr"][-1])
        if self.rule_str == "keep":
            return None
        if self.rule_str == "packed":
            return get_packed_weight_float(close_float)
        if time_str != "15:30":
            return None
        start_idx = int(bar_dict["session_start_idx_arr"][-1])
        if start_idx < 1:
            return None
        previous_close_float = float(bar_dict["close_arr"][start_idx - 1])
        return 0.0 if close_float < previous_close_float else None


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Name in CANDIDATE_LIST

    Returns:
        IntradayDesign: Fresh object
    """
    # UNKNOWN NAMES ARE A TEST ERROR
    if str(candidate_in) not in CANDIDATE_LIST:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return IntradayDesign(str(candidate_in))
