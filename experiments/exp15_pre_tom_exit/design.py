# IMPORT THE EXPERIMENT CONFIGURATION AND THE RULE-CODED CALENDAR
from experiments.exp15_pre_tom_exit import config as exp_config
from experiments.exp15_pre_tom_exit.calendar_rules import is_next_session_in_cash_window_bool
import pandas as pd

"""
Runner Design: exp15_pre_tom_exit (idea C2, pre-turn-of-month exit)

Invested by default. At the 15:58 decision of session s, the target weight held from the 15:59 fill of s to the
15:59 fill of the next session is 0 exactly when the next design-calendar session after s lies in the candidate's
pre-TOM cash window for that session's month; otherwise 1. The decision reads only the decision session's date.
Day counts use calendar_rules.py (scheduled NYSE holidays only). Unscheduled closures stay in the day count; when a
planned exit or re-entry lands on a closed market day, the position stays until the next real session's 15:59 fill.

Engine: fractional, targets in {0, 1}. Source: SPY_1MIN only. decide reads only view.session_date (from the bar
walk); no prices, volumes or TSDAY feature columns. TSDAY is dropped because the calendar rule does not use it
and the fractional engine runs with SPY_1MIN alone (same pattern as exp14).
"""

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FOLD_TRAIN_WINDOW_YEARS]}
CANDIDATE_LIST = list(exp_config.CANDIDATE_LIST)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("candidate", True)]}
CANDIDATE_TIE_VALUE_DICT = {}
DATA_SOURCE_LIST = ["SPY_1MIN"]
ENGINE_NAME = "fractional"
DEAD_BAND = float(exp_config.DEAD_BAND)
INITIAL_WEIGHT = float(exp_config.INITIAL_WEIGHT)


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Candidate name

    Returns:
        Design: Fresh object
    """
    # UNKNOWN NAMES ARE A DESIGN ERROR
    if str(candidate_in) not in exp_config.CANDIDATE_WINDOW_DICT:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return Design(str(candidate_in))


# CLASS: ONE PRE-TOM WINDOW AND SETTLEMENT RULE
class Design:
    """decide(view) returns target weight 0 or 1 from the decision date only."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME

    # FUNCTION: STORE THE CANDIDATE NAME
    def __init__(self, candidate_str_in):
        """
        Args:
            candidate_str_in (str): Candidate name
        """
        # THE CANDIDATE IS FIXED FOR THE STREAM
        self.candidate_str = str(candidate_str_in)

    # FUNCTION: TARGET WEIGHT AT THIS DECISION
    def decide(self, view_in):
        """
        Weight 0 when the next design-calendar session after this session's date is in the cash window; else 1.

        Args:
            view_in: DecisionView (only session_date is read)

        Returns:
            float: 0.0 or 1.0
        """
        # THE DATE OF THE DECISION BAR ONLY
        session_day = pd.Timestamp(view_in.session_date).date()
        if is_next_session_in_cash_window_bool(session_day, self.candidate_str):
            return 0.0
        return 1.0
