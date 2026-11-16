import numpy as np
import pandas as pd
# IMPORT THE EXPERIMENT CONFIGURATION
from experiments.exp14_last_half_hour_exit import config as exp_config

"""
Runner Design: exp14_last_half_hour_exit (last-half-hour exit on weak days)

Invested by default. At 15:30, sell (weight 0) when the chosen signal is strictly below -x. At 15:58, weight 1
(buy back at the 15:59 open). The cash spell is 15:31 through 15:59; the last minute and the close stay held.

    fh    previous session's last-bar close -> close of today's 09:59 bar (the 10:00 price)
    rod   previous session's last-bar close -> close of today's 15:30 bar
    skip  signal < -x, and not equal to -x within SIGNAL_EQUAL_ABS_TOL
    keep  NaN when the previous close or the exact end bar is missing. A nearby bar is not used

No model. State between calls lives on the Design object. Fractional engine, one intraday time (15:30).
"""

# THE SIX CANDIDATES, IN PROTOCOL ORDER
_CANDIDATE_DICT_LIST = [{"name": str(name_str), "signal": str(signal_str), "threshold": float(threshold_float)}
                        for name_str, signal_str, threshold_float in exp_config.CANDIDATE_SPEC_LIST]
_CANDIDATE_BY_NAME_DICT = {candidate_dict["name"]: candidate_dict for candidate_dict in _CANDIDATE_DICT_LIST}

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FOLD_TRAIN_WINDOW_YEARS]}
CANDIDATE_LIST = [candidate_dict["name"] for candidate_dict in _CANDIDATE_DICT_LIST]
# TIES: CANDIDATE NAME ASCENDING (THE SCORE TABLE ALREADY CARRIES THE NAME)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("candidate", True)]}
DATA_SOURCE_LIST = ["SPY_1MIN"]
ENGINE_NAME = "fractional"
DEAD_BAND = 0.0
INITIAL_WEIGHT = 1.0
# THE SAME LIST ON THE MODULE AND ON THE DESIGN CLASS (R4c)
INTRADAY_DECISION_TIME_LIST = [exp_config.INTRADAY_DECISION_TIME_STR]
# BAR CLOCKS
_FH_MINUTE_INT = int(exp_config.FH_BAR_MINUTE_OF_DAY_INT)
_ROD_MINUTE_INT = int(exp_config.ROD_BAR_MINUTE_OF_DAY_INT)
_SIGNAL_MINUTE_DICT = {"fh": _FH_MINUTE_INT, "rod": _ROD_MINUTE_INT}


# FUNCTION: MINUTES AFTER MIDNIGHT OF EACH BAR (NEW YORK CLOCK)
def get_bar_minute_arr(timestamp_arr_in):
    """
    Naive timestamps are already New York, as the runner stores them. Aware timestamps are converted.

    Args:
        timestamp_arr_in (array-like): Bar start times

    Returns:
        np.ndarray: Minutes after midnight
    """
    # THE SLICE THE CALLER PASSES IS THE SESSION RANGE, NOT THE WHOLE HISTORY
    ts_index = pd.DatetimeIndex(timestamp_arr_in)
    if ts_index.tz is not None:
        ts_index = ts_index.tz_convert("America/New_York")
    return np.asarray(ts_index.hour, dtype=np.int64) * 60 + np.asarray(ts_index.minute, dtype=np.int64)


# FUNCTION: THE LAST BAR OF A SESSION AT ONE CLOCK, AT OR BEFORE THE DECISION
def get_clock_bar_idx(bar_dict_in, session_idx_in, decision_bar_idx_in, minute_of_day_int_in):
    """
    Bars after decision_bar_idx_in are not visible, even if the array still holds them.

    Args:
        bar_dict_in (dict): View bar arrays
        session_idx_in (int): Session
        decision_bar_idx_in (int): Last bar the decision may use
        minute_of_day_int_in (int): Bar-start clock, minutes after midnight

    Returns:
        int: Bar index, or -1 when that clock is missing
    """
    # THE LIVE SESSION'S END IN THE VIEW IS THE DECISION BAR; CAP IT ANYWAY
    start_idx = int(bar_dict_in["session_start_idx_arr"][int(session_idx_in)])
    end_idx = min(int(bar_dict_in["session_end_idx_arr"][int(session_idx_in)]), int(decision_bar_idx_in))
    if end_idx < start_idx:
        return -1
    minute_arr = get_bar_minute_arr(np.asarray(bar_dict_in["timestamp_arr"])[start_idx:end_idx + 1])
    hit_idx_arr = np.flatnonzero(minute_arr == int(minute_of_day_int_in))
    if len(hit_idx_arr) == 0:
        return -1
    return start_idx + int(hit_idx_arr[-1])


# FUNCTION: THE PREVIOUS SESSION'S LAST CLOSE, IF THAT BAR IS ALREADY KNOWABLE
def get_previous_close_float(bar_dict_in, session_idx_in, decision_bar_idx_in):
    """
    Args:
        bar_dict_in (dict): View bar arrays
        session_idx_in (int): Session of the decision
        decision_bar_idx_in (int): Last bar the decision may use

    Returns:
        float: Close, or NaN
    """
    # THE FIRST SESSION HAS NO PREVIOUS CLOSE
    if int(session_idx_in) < 1:
        return np.nan
    end_idx = int(bar_dict_in["session_end_idx_arr"][int(session_idx_in) - 1])
    if end_idx < 0 or end_idx > int(decision_bar_idx_in):
        return np.nan
    close_float = float(bar_dict_in["close_arr"][end_idx])
    if not np.isfinite(close_float) or close_float <= 0.0:
        return np.nan
    return close_float


# FUNCTION: THE SIGNAL RETURN, OR NaN WHEN AN EXACT PRICE IS MISSING
def get_signal_return_float(view_in, signal_str_in):
    """
    fh uses the 09:59 close. rod uses the 15:30 close. Neither uses a neighbouring bar.

    Args:
        view_in: DecisionView
        signal_str_in (str): "fh" or "rod"

    Returns:
        float: End / previous close - 1, or NaN
    """
    # BOTH PRICES HAVE TO BE IN THE VIEW AT OR BEFORE THE DECISION BAR
    if str(signal_str_in) not in _SIGNAL_MINUTE_DICT:
        raise ValueError(f"unknown signal {signal_str_in!r}")
    bar_dict = view_in.get_bar_array_dict()
    session_idx = int(view_in.session_idx)
    decision_idx = int(view_in.decision_bar_idx)
    prev_close_float = get_previous_close_float(bar_dict, session_idx, decision_idx)
    if not np.isfinite(prev_close_float):
        return np.nan
    bar_idx = get_clock_bar_idx(bar_dict, session_idx, decision_idx, _SIGNAL_MINUTE_DICT[str(signal_str_in)])
    if bar_idx < 0:
        return np.nan
    end_close_float = float(bar_dict["close_arr"][bar_idx])
    if not np.isfinite(end_close_float) or end_close_float <= 0.0:
        return np.nan
    return end_close_float / prev_close_float - 1.0


# FUNCTION: TRUE ONLY WHEN THE SIGNAL IS STRICTLY BELOW -x
def get_weak_day_bool(signal_float_in, threshold_float_in):
    """
    A return equal to -x does not skip. Binary division of an exact ratio can sit just below -x; that
    still counts as equal.

    Args:
        signal_float_in (float): Signal return
        threshold_float_in (float): x, as a positive return

    Returns:
        bool: Skip
    """
    # A MISSING SIGNAL NEVER SKIPS
    if not np.isfinite(signal_float_in) or not np.isfinite(threshold_float_in):
        return False
    bound_float = -float(threshold_float_in)
    if np.isclose(float(signal_float_in), bound_float, rtol=0.0, atol=float(exp_config.SIGNAL_EQUAL_ABS_TOL)):
        return False
    return float(signal_float_in) < bound_float


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
    return Design(_CANDIDATE_BY_NAME_DICT[str(candidate_in)])


# CLASS: ONE SIGNAL AND ONE THRESHOLD
class Design:
    """decide(view) returns 0, 1, or NaN. Call history stays on this object."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME
    INTRADAY_DECISION_TIME_LIST = INTRADAY_DECISION_TIME_LIST

    # FUNCTION: STORE THE CANDIDATE AND EMPTY CALL STATE
    def __init__(self, candidate_dict_in):
        """
        Args:
            candidate_dict_in (dict): name, signal, threshold
        """
        # THE RULE IS FIXED FOR THE STREAM
        self.candidate_str = str(candidate_dict_in["name"])
        self.signal_str = str(candidate_dict_in["signal"])
        self.threshold_float = float(candidate_dict_in["threshold"])
        self.last_intraday_time_str = None
        self.last_signal_return_float = np.nan
        self.last_weight_float = np.nan
        self.call_log_list = []

    # FUNCTION: TARGET WEIGHT AT THIS DECISION
    def decide(self, view_in):
        """
        15:30 sells only on a strict weak signal. 15:58 is weight 1. Any other intraday time keeps.

        Args:
            view_in: DecisionView

        Returns:
            float: Target weight, or NaN to keep
        """
        # THE DAILY CALL BUYS BACK (OR STAYS INVESTED) AND DOES NOT READ A LATER BAR
        time_str = view_in.intraday_time_str
        if time_str is None:
            signal_float = np.nan
            weight_float = 1.0
        elif str(time_str) == exp_config.INTRADAY_DECISION_TIME_STR:
            signal_float = get_signal_return_float(view_in, self.signal_str)
            if get_weak_day_bool(signal_float, self.threshold_float):
                weight_float = 0.0
            elif np.isfinite(signal_float):
                weight_float = 1.0
            else:
                weight_float = np.nan
        else:
            signal_float = np.nan
            weight_float = np.nan
        # STATE STAYS ON THE OBJECT, NOT IN A MODULE GLOBAL
        self.last_intraday_time_str = None if time_str is None else str(time_str)
        self.last_signal_return_float = float(signal_float)
        self.last_weight_float = float(weight_float)
        self.call_log_list.append({
            "session_date": view_in.session_date,
            "intraday_time_str": self.last_intraday_time_str,
            "signal_return_float": self.last_signal_return_float,
            "weight_float": self.last_weight_float,
        })
        return weight_float
