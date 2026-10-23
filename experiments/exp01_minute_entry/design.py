import numpy as np
import pandas as pd
# IMPORT THE EXPERIMENT CONFIGURATION AND THE MODEL
from experiments.exp01_minute_entry import config as exp_config
from experiments.exp01_minute_entry.model import MODEL_FEATURE_COL_LIST, fit_delta_model_dict, get_policy_pdf

"""
Runner Design: exp01_minute_entry (minute mode)

Every 15 minutes (entries at 10:00, 10:15, ...) a model of P(take profit first) for 21 symmetric distances gives each
distance's expected net return at the decision-bar close. Enter at the next minute's open when the best one clears the
candidate's threshold, with that distance as take profit and RR_RATIO x it as stop loss (barrier engine: one position
at a time, time limit MAX_HOLD_TRADING_DAYS). The models are refit weekly on the candidate's window of earlier rows
(TRAIN_ROW_HISTORY_BOOL: rows before the scored span count), using only labels known before the refit.

Candidates with the same window fit the same models (FIT_KEY_STR): the runner fits once per run and shares the fit.
"""

# MINUTE MODE, BARRIER ENGINE, START IN CASH
MODE = "minute"
ENGINE_NAME = "barrier"
INITIAL_WEIGHT = 0.0
# ROWS: SPY PLUS THE THREE FEATURE CACHES; LABELS: THE BARRIER CELLS
ROW_SOURCE_LIST = ["SPY_1MIN"] + list(exp_config.FEATURE_SOURCE_LIST)
LABEL_SOURCE_LIST = ["TSBAR"]
DATA_SOURCE_LIST = ROW_SOURCE_LIST + LABEL_SOURCE_LIST
FEATURE_COL_LIST = list(MODEL_FEATURE_COL_LIST) + ["close"]
ROW_SAMPLE_EVERY_N_MINUTES = exp_config.SAMPLE_EVERY_N_MINUTES
TRAIN_ROW_HISTORY_BOOL = True
RETRAIN_FREQUENCY_STR = exp_config.RETRAIN_FREQUENCY_STR

# THE 12 CANDIDATES: WINDOW, THEN THRESHOLD
CANDIDATE_LIST = [f"{int(years)}Y|{float(threshold):.4f}" for years in exp_config.TRAIN_WINDOW_YEARS_LIST for threshold in exp_config.EV_THRESHOLD_LIST]
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
# THE PREVIOUS QUARTER; TIES: THE SHORTER WINDOW, THEN THE HIGHER THRESHOLD
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("years", True), ("threshold", False)]}
CANDIDATE_TIE_VALUE_DICT = {"years": {name: int(name.split("|")[0].replace("Y", "")) for name in CANDIDATE_LIST},
                            "threshold": {name: float(name.split("|")[1]) for name in CANDIDATE_LIST}}


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): "<years>Y|<threshold>"

    Returns:
        Design: Fresh object
    """
    # UNKNOWN NAMES ARE A DESIGN ERROR
    if str(candidate_in) not in CANDIDATE_LIST:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    year_str, threshold_str = str(candidate_in).split("|")
    return Design(int(year_str.replace("Y", "")), float(threshold_str))


# CLASS: ONE WINDOW AND ONE THRESHOLD
class Design:
    """fit_shared depends on the window only; finish_fit attaches the threshold the signal reads."""

    # FUNCTION: STORE THE WINDOW AND THE THRESHOLD
    def __init__(self, years_in, threshold_in):
        """
        Args:
            years_in (int): Training window in years
            threshold_in (float): Expected net return threshold
        """
        # THE RUNNER READS TRAIN_WINDOW_STR AND FIT_KEY_STR FROM THE OBJECT
        self.TRAIN_WINDOW_STR = f"{int(years_in)}Y"
        self.FIT_KEY_STR = f"{int(years_in)}Y"
        self.threshold_float = float(threshold_in)

    # FUNCTION: THE MODELS OF ONE REFIT (SHARED BY THE FOUR THRESHOLDS)
    def fit_shared(self, train_rows_in):
        """
        Args:
            train_rows_in (pd.DataFrame): Rows the runner allows at this refit

        Returns:
            dict: delta -> classifier
        """
        # ONE CLASSIFIER PER DISTANCE
        return fit_delta_model_dict(train_rows_in)

    # FUNCTION: THE MODEL THE SIGNAL RECEIVES
    def finish_fit(self, shared_model_in):
        """
        Args:
            shared_model_in (dict): Output of fit_shared

        Returns:
            dict: models, threshold
        """
        # THE THRESHOLD IS THE CANDIDATE'S
        return {"models": shared_model_in, "threshold": float(self.threshold_float)}

    # FUNCTION: FIT WITHOUT THE SHARED CACHE
    def fit(self, train_rows_in):
        """
        Args:
            train_rows_in (pd.DataFrame): Training rows

        Returns:
            dict: models, threshold
        """
        # THE SAME OBJECT AS THE SHARED PATH
        return self.finish_fit(self.fit_shared(train_rows_in))


# FUNCTION: ROW-LOCAL ENTRY DECISION
def signal(rows_in, model_in):
    """
    Args:
        rows_in (pd.DataFrame): FEATURE_COL_LIST rows, in any order
        model_in (dict | None): Output of finish_fit

    Returns:
        pd.DataFrame: enter, delta
    """
    # NO MODEL: NO ENTRY
    if model_in is None or not model_in.get("models"):
        return pd.DataFrame({"enter": np.zeros(len(rows_in), dtype=bool), "delta": [None] * len(rows_in)})
    policy_pdf = get_policy_pdf(rows_in, model_in["models"])
    expected_arr = policy_pdf["expected_return"].to_numpy(dtype=float)
    enter_arr = np.isfinite(expected_arr) & (expected_arr > float(model_in["threshold"]))
    return pd.DataFrame({"enter": enter_arr, "delta": [float(delta) if enter_bool else None
                                                        for delta, enter_bool in zip(policy_pdf["delta"], enter_arr)]})
