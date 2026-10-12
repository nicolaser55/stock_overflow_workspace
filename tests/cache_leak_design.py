import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Synthetic design (tests only). The fit reads the close one session ahead of the second-to-last session and caches
that number under the training-window name, ignoring which bars were passed. A fresh module per replay recomputes
it. A cache that survived from the full run would hide the leak.
"""

# DEFINE THE PERIODS, THE ONE CANDIDATE AND THE SELECTION RULE
PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
CANDIDATE_LIST = ["only"]
SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}
# COPY THE NAME AND THE PROTOCOL VERSION (THE TRIAL LOG READS THEM)
EXPERIMENT_NAME = "exp_cache_leak"
PROTOCOL_VERSION = "1.0"
# THE CACHE KEY IS THE WINDOW NAME ALONE
_fit_cache_dict = {}

# FUNCTION: THE CLOSE ONE SESSION AHEAD OF THE SECOND-TO-LAST SESSION
def get_one_session_ahead_float(ohlcv_array_dict_in):
    """
    The last session close. That close is one session ahead of the second-to-last session, and it moves when the
    series is truncated or the last bars are perturbed.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        float: Close
    """
    # THE LAST SESSION CLOSE
    session_close_arr = ohlcv_array_dict_in["close_arr"][ohlcv_array_dict_in["session_end_idx_arr"]]
    return float(session_close_arr[-1])

# FUNCTION: THE CACHED FIT, KEYED BY THE WINDOW AND NOT BY THE BARS
def get_cached_weight_float(ohlcv_array_dict_in):
    """
    Returns the cached weight when this window was already fit. The first call stores the one-session-ahead close.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        float: Weight
    """
    # THE WINDOW NAME IS THE ONLY KEY
    if "only" not in _fit_cache_dict:
        _fit_cache_dict["only"] = get_one_session_ahead_float(ohlcv_array_dict_in)
    return float(_fit_cache_dict["only"])

# FUNCTION: REPLAY ONE CANDIDATE OVER ONE PERIOD
def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
    """
    A one-row equity. The score is not the leak. Fitting here fills the same window cache the path reads.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Period bounds
        candidate_in (str): Candidate
        data_context_in (DataContext | None): Unused

    Returns:
        dict: daily_equity_pdf, trade_pdf
    """
    # FILL THE CACHE, THEN RETURN A FLAT EQUITY
    get_cached_weight_float(ohlcv_array_dict_in)
    return {"daily_equity_pdf": pd.DataFrame({"date": [pd.Timestamp(date2_in).date()], "equity": [config.INITIAL_CAPITAL], "in_position": [True], "weight": [1.0]}),
            "trade_pdf": pd.DataFrame()}

# FUNCTION: REPLAY THE CONTINUOUS PATH
def run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
    """
    Every session in the span gets the cached weight. On a fresh module that weight is this bar set's own
    one-session-ahead close.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Unused (one candidate)
        data_context_in (DataContext | None): Unused

    Returns:
        dict: daily_equity_pdf, trade_pdf, target_weight_arr, signal_arr, decision_session_list
    """
    # THE CACHED LEAK
    weight_float = get_cached_weight_float(ohlcv_array_dict_in)
    date1 = pd.Timestamp(period_pdf_in["period_start"].iloc[0]).date()
    date2 = pd.Timestamp(period_pdf_in["period_end"].iloc[-1]).date()
    row_dict_list, weight_list, session_list = [], [], []
    for session_date in ohlcv_array_dict_in["session_date_list"]:
        session_day = pd.Timestamp(session_date).date()
        if not (date1 <= session_day <= date2):
            continue
        row_dict_list.append({"date": session_day, "equity": config.INITIAL_CAPITAL, "in_position": True, "weight": weight_float})
        weight_list.append(weight_float)
        session_list.append(session_day)
    weight_arr = np.asarray(weight_list, dtype=float)
    return {"daily_equity_pdf": pd.DataFrame(row_dict_list), "trade_pdf": pd.DataFrame(),
            "target_weight_arr": weight_arr, "signal_arr": weight_arr.copy(), "decision_session_list": session_list}

# FUNCTION: THE UNINFORMED BASELINE
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in):
    """
    A flat baseline. The runner names the holdout only.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span

    Returns:
        dict: baseline name -> total return
    """
    # ZERO
    return {"flat": 0.0}
