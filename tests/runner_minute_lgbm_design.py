"""
Synthetic LightGBM minute design for the 4b-2b speed check.

Twelve candidates: three training windows times four thresholds. Weekly refits. Features are SPY close only.
"""

import numpy as np
import pandas as pd
import lightgbm as lgb

# MINUTE MODE
MODE = "minute"
# BARRIER ENGINE, START IN CASH
ENGINE_NAME = "barrier"
INITIAL_WEIGHT = 0.0
# FIXED DISTANCE
DELTA = 0.01
# SPY CLOSE IS THE ONLY FEATURE
ROW_SOURCE_LIST = ["SPY_1MIN"]
FEATURE_COL_LIST = ["close"]
DATA_SOURCE_LIST = ["SPY_1MIN"]
# WEEKLY REFITS
RETRAIN_FREQUENCY_STR = "weekly"
# TWELVE CANDIDATES: WINDOW THEN THRESHOLD
_YEAR_LIST = [3, 5, 10]
_THRESHOLD_LIST = [0.0, 0.25, 0.5, 0.75]
CANDIDATE_LIST = [f"{int(years)}Y|{float(threshold):.2f}" for years in _YEAR_LIST for threshold in _THRESHOLD_LIST]
# TIE COLUMNS
CANDIDATE_TIE_VALUE_DICT = {
    "years": {name_str: int(name_str.split("|")[0].replace("Y", "")) for name_str in CANDIDATE_LIST},
    "threshold": {name_str: float(name_str.split("|")[1]) for name_str in CANDIDATE_LIST},
}
# DEVELOPMENT QUARTERS (TESTS INJECT PERIODS)
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
# POOL THE LAST TWO PERIODS
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("years", True), ("threshold", False)]}
# TRIAL LOG CONSTANTS
EXPERIMENT_NAME = "runner_minute_lgbm_speed"
PROTOCOL_VERSION = "4b-2b"
# SAMPLE ON THE 15-MINUTE ENTRY GRID
ROW_SAMPLE_EVERY_N_MINUTES = 15
# SMALL MODEL
LGBM_PARAM_DICT = {"n_estimators": 8, "num_leaves": 4, "min_child_samples": 5, "verbosity": -1, "n_jobs": 1}


# FUNCTION: PARSE A CANDIDATE NAME
def parse_candidate_dict(candidate_str_in):
    """
    Args:
        candidate_str_in (str): Name

    Returns:
        dict: years, threshold
    """
    # WINDOW THEN THRESHOLD
    year_str, threshold_str = str(candidate_str_in).split("|")
    return {"years": int(year_str.replace("Y", "")), "threshold": float(threshold_str)}


# FUNCTION: A CANDIDATE WITH A WINDOW AND A THRESHOLD
class MinuteLgbmDesign:
    """Fits a small LightGBM classifier on close; signal enters when P(class 1) exceeds the threshold."""

    # FUNCTION: STORE THE WINDOW AND THE THRESHOLD
    def __init__(self, years_in, threshold_in):
        """
        Args:
            years_in (int): Training window in years
            threshold_in (float): Probability threshold
        """
        # THE FIT READS THE WINDOW; THE SIGNAL READS THE THRESHOLD FROM THE MODEL
        self.TRAIN_WINDOW_STR = f"{int(years_in)}Y"
        self.threshold_float = float(threshold_in)

    # FUNCTION: FIT A SMALL CLASSIFIER
    def fit(self, train_rows_in):
        """
        Args:
            train_rows_in (pd.DataFrame): Training rows with close

        Returns:
            dict: model, threshold
        """
        # Y IS A FEATURE SPLIT, NOT A FORWARD LABEL (SPEED CHECK ONLY)
        close_arr = train_rows_in["close"].to_numpy(dtype=float)
        median_float = float(np.median(close_arr)) if len(close_arr) else 0.0
        y_arr = (close_arr > median_float).astype(int)
        if int(np.unique(y_arr).size) < 2:
            return {"model": None, "threshold": float(self.threshold_float)}
        model = lgb.LGBMClassifier(**LGBM_PARAM_DICT)
        model.fit(train_rows_in[FEATURE_COL_LIST], y_arr)
        return {"model": model, "threshold": float(self.threshold_float)}


# FUNCTION: ROW-LOCAL PROBABILITY THRESHOLD
def signal(rows_in, model_in):
    """
    Args:
        rows_in (pd.DataFrame): Feature rows (shuffled)
        model_in (dict | None): Output of fit

    Returns:
        pd.DataFrame: enter, delta
    """
    # A MISSING MODEL NEVER ENTERS
    if model_in is None or model_in.get("model") is None:
        return pd.DataFrame({"enter": np.zeros(len(rows_in), dtype=bool), "delta": [DELTA] * len(rows_in)})
    proba_arr = model_in["model"].predict_proba(rows_in[FEATURE_COL_LIST])[:, 1]
    enter_arr = proba_arr > float(model_in["threshold"])
    return pd.DataFrame({"enter": enter_arr, "delta": [DELTA] * len(rows_in)})


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Name in CANDIDATE_LIST

    Returns:
        MinuteLgbmDesign: Fresh object
    """
    # PARSE THE GRID NAME
    candidate_dict = parse_candidate_dict(candidate_in)
    return MinuteLgbmDesign(candidate_dict["years"], candidate_dict["threshold"])
