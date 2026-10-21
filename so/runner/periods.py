import pandas as pd
# IMPORT THE DEVELOPMENT BOUNDARY, THE PERIOD BUILDERS AND THE QUARANTINE REFUSAL
from so.paths import check_quarantine_refused
from so.core.holdout import get_active_holdout_window_dict, get_date, NO_WINDOW_MESSAGE_STR
from so.core.schedule import get_development_fold_pdf
from so.core.continuous_replay import get_replay_period_pdf

"""
Development Periods (infrastructure step 4b-1a)

The development runner forms candidate periods from the design's PERIOD_RULE with the existing schedule code
(get_development_fold_pdf, then get_replay_period_pdf). It refuses the quarantine root (so.paths.check_quarantine_refused):
holdout evaluation is run_holdout_dict. Bars must end strictly before the active holdout start. No window registered
is a hard refuse.
"""


# FUNCTION: THE PERIOD RULE FROM A DESIGN MODULE
def get_period_rule_dict(design_module_in):
    """
    PERIOD_RULE.embargo_sessions (at least 1) and PERIOD_RULE.train_years (a non-empty list of years).

    Args:
        design_module_in (module): Design

    Returns:
        dict: embargo_sessions, train_years
    """
    # BOTH KEYS ARE REQUIRED
    if not hasattr(design_module_in, "PERIOD_RULE"):
        raise ValueError("design module is missing PERIOD_RULE.")
    rule_dict = dict(design_module_in.PERIOD_RULE)
    if "embargo_sessions" not in rule_dict or "train_years" not in rule_dict:
        raise ValueError("PERIOD_RULE needs embargo_sessions and train_years.")
    embargo_int = int(rule_dict["embargo_sessions"])
    train_years_list = [int(year_int) for year_int in list(rule_dict["train_years"])]
    if embargo_int < 1 or len(train_years_list) == 0:
        raise ValueError("PERIOD_RULE.embargo_sessions must be at least 1 and train_years must be non-empty.")
    return {"embargo_sessions": embargo_int, "train_years": train_years_list}


# FUNCTION: REFUSE BARS THAT REACH THE HOLDOUT START
def check_development_bars(session_date_list_in, window_dict_in):
    """
    Development bars end strictly before the active holdout start.

    Args:
        session_date_list_in (list): Session dates of the bars
        window_dict_in (dict): Active holdout window

    Returns:
        datetime.date: Holdout start
    """
    # THE LAST PRICE SESSION MUST NOT TOUCH THE WINDOW
    window_start = get_date(window_dict_in["start"])
    session_date_list = [get_date(session_date) for session_date in session_date_list_in]
    if not session_date_list:
        raise ValueError("development bars have no sessions.")
    if session_date_list[-1] >= window_start:
        raise ValueError("development bars must end strictly before the holdout start.")
    return window_start


# FUNCTION: DEVELOPMENT PERIODS FROM PERIOD_RULE
def get_development_run_period_pdf(design_module_in, session_date_list_in):
    """
    Validation quarters anchored on the development end (embargo before the holdout start), made non-overlapping.
    The holdout start is appended as a date so the embargo index is defined; its prices are not required.

    Args:
        design_module_in (module): Design (PERIOD_RULE)
        session_date_list_in (list): Sessions the bars actually contain (strictly before the holdout start)

    Returns:
        tuple: period_pdf, fold_pdf
    """
    # THE DEVELOPMENT VIEW NEVER OPENS THE QUARANTINE
    check_quarantine_refused()
    window_dict = get_active_holdout_window_dict()
    if window_dict is None:
        raise ValueError(NO_WINDOW_MESSAGE_STR)
    rule_dict = get_period_rule_dict(design_module_in)
    session_date_list = [get_date(session_date) for session_date in session_date_list_in]
    window_start = check_development_bars(session_date_list, window_dict)
    # THE ANCHOR LIST IS THE PRICE SESSIONS PLUS THE WINDOW START
    anchor_session_list = session_date_list + [window_start]
    fold_pdf = get_development_fold_pdf(anchor_session_list, int(rule_dict["embargo_sessions"]), list(rule_dict["train_years"]))
    if fold_pdf.empty:
        raise ValueError("the design has no development period on these sessions.")
    period_pdf = get_replay_period_pdf(fold_pdf, session_date_list)
    if period_pdf.empty:
        raise ValueError("the design has no development period on these sessions.")
    return period_pdf, fold_pdf


# FUNCTION: A DATE COLUMN TO datetime.date
def get_period_date(value_in):
    """
    Args:
        value_in: Date-like

    Returns:
        datetime.date: The date
    """
    # PANDAS TIMESTAMP AND datetime.date BOTH CONVERT
    return pd.Timestamp(value_in).date()
