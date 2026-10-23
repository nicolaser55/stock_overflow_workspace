import numpy as np
# IMPORT THE EXPERIMENT CONFIGURATION AND THE DAILY HISTORY
from experiments.exp05_vol_scaled_exposure import config as exp_config
from so.features.view_history import DailyHistory, get_day

"""
Runner Design: exp05_vol_scaled_exposure

Hold w = min(1, max(floor, sigma_target / sigma_hat)) of the account in SPY, decided at 15:58, filled at 15:59.
    sigma_hat     today's daily_volatility (std of the previous 20 daily close-to-close returns)
    sigma_target  the q-quantile of every daily_volatility value of the sessions before the current calendar quarter's
                  first session, fixed for the quarter (at least MIN_TARGET_HISTORY_SESSIONS values, otherwise w = 1)
A missing sigma_hat gives w = 1. Fractional engine with a dead band.
"""

# THE 4 CANDIDATES: FLOOR, THEN QUANTILE
_CANDIDATE_DICT_LIST = [{"floor": float(floor), "target_quantile": float(quantile), "name": f"{float(floor):.2f}|{float(quantile):.2f}"}
                        for floor in exp_config.FLOOR_LIST for quantile in exp_config.TARGET_QUANTILE_LIST]
_CANDIDATE_BY_NAME_DICT = {candidate_dict["name"]: candidate_dict for candidate_dict in _CANDIDATE_DICT_LIST}

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
CANDIDATE_LIST = [candidate_dict["name"] for candidate_dict in _CANDIDATE_DICT_LIST]
# TIES: THE HIGHER FLOOR, THEN THE HIGHER QUANTILE (MORE INVESTED)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("floor", False), ("target_quantile", False)]}
CANDIDATE_TIE_VALUE_DICT = {"floor": {name: _CANDIDATE_BY_NAME_DICT[name]["floor"] for name in CANDIDATE_LIST},
                            "target_quantile": {name: _CANDIDATE_BY_NAME_DICT[name]["target_quantile"] for name in CANDIDATE_LIST}}
DATA_SOURCE_LIST = ["SPY_1MIN", "TSDAY"]
ENGINE_NAME = "fractional"
DEAD_BAND = exp_config.DEAD_BAND
INITIAL_WEIGHT = 1.0


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


# CLASS: ONE FLOOR AND ONE TARGET QUANTILE
class Design:
    """decide(view) returns the target weight."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME

    # FUNCTION: STORE THE CANDIDATE
    def __init__(self, candidate_dict_in):
        """
        Args:
            candidate_dict_in (dict): floor, target_quantile
        """
        # THE TARGET IS FIXED PER CALENDAR QUARTER
        self.floor_float = float(candidate_dict_in["floor"])
        self.quantile_float = float(candidate_dict_in["target_quantile"])
        self.history = DailyHistory(["daily_volatility"])
        self.quarter_tuple = None
        self.target_float = np.nan

    # FUNCTION: THE WEIGHT AT THIS DECISION
    def decide(self, view_in):
        """
        Args:
            view_in: DecisionView

        Returns:
            float: Target weight in [floor, 1]
        """
        # TODAY'S VOLATILITY; THE HISTORY ENDS WITH TODAY'S ROW
        row_dict = self.history.update(view_in)
        if row_dict is None:
            return np.nan
        session_day = get_day(view_in.session_date)
        quarter_tuple = (session_day.year, (session_day.month - 1) // 3)
        if quarter_tuple != self.quarter_tuple:
            # EVERY VALUE BEFORE THE QUARTER'S FIRST SESSION (THE STREAM'S FIRST DECISION MAY BE MID-QUARTER)
            quarter_start = session_day.replace(month=3 * quarter_tuple[1] + 1, day=1)
            date_arr = np.asarray(self.history.date_list, dtype=object)
            earlier_arr = self.history.value_arr("daily_volatility")[date_arr < quarter_start]
            earlier_arr = earlier_arr[np.isfinite(earlier_arr)]
            self.target_float = float(np.quantile(earlier_arr, self.quantile_float)) if len(earlier_arr) >= int(exp_config.MIN_TARGET_HISTORY_SESSIONS) else np.nan
            self.quarter_tuple = quarter_tuple
        volatility_float = float(row_dict["daily_volatility"])
        if not np.isfinite(volatility_float) or volatility_float <= 0 or not np.isfinite(self.target_float):
            return 1.0
        return float(min(1.0, max(self.floor_float, self.target_float / volatility_float)))
