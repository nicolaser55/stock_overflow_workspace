"""
Synthetic minute design for runner 4b-2b tests.

Row-local signal: enter when x is above the candidate threshold. The model is the threshold itself.
"""

import pandas as pd

# MINUTE MODE
MODE = "minute"
# BARRIER ENGINE, START IN CASH
ENGINE_NAME = "barrier"
INITIAL_WEIGHT = 0.0
# FIXED DISTANCE
DELTA = 0.01
# FEATURE SOURCE PLANTED BY THE TEST
ROW_SOURCE_LIST = ["MINUTE_TEST_FEAT"]
FEATURE_COL_LIST = ["x"]
DATA_SOURCE_LIST = ["SPY_1MIN", "MINUTE_TEST_FEAT"]
# WEEKLY REFITS, EXPANDING WINDOW
RETRAIN_FREQUENCY_STR = "weekly"
TRAIN_WINDOW_STR = "ALL"
# TWO THRESHOLDS
CANDIDATE_LIST = ["lo", "hi"]
# DEVELOPMENT QUARTERS (TESTS INJECT PERIODS)
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
# POOL THE LAST TWO PERIODS
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("candidate", True)]}
# TRIAL LOG CONSTANTS
EXPERIMENT_NAME = "runner_minute_test"
PROTOCOL_VERSION = "4b-2b"
# SAMPLE ON THE 15-MINUTE ENTRY GRID
ROW_SAMPLE_EVERY_N_MINUTES = 15


# FUNCTION: A CANDIDATE THAT STORES ITS THRESHOLD
class MinuteThresholdDesign:
    """fit returns the threshold; signal is the module-level function."""

    # FUNCTION: STORE THE THRESHOLD
    def __init__(self, threshold_in):
        """
        Args:
            threshold_in (float): Enter when x is above this
        """
        # THE MODEL IS THIS NUMBER
        self.threshold_float = float(threshold_in)
        self.TRAIN_WINDOW_STR = "ALL"

    # FUNCTION: RETURN THE THRESHOLD AS THE MODEL
    def fit(self, train_rows_in):
        """
        Args:
            train_rows_in (pd.DataFrame): Training rows (unused besides existing)

        Returns:
            dict: threshold
        """
        # A FIXED MODEL
        _ = train_rows_in
        return {"threshold": float(self.threshold_float)}


# FUNCTION: ROW-LOCAL ENTER FLAG AND DISTANCE
def signal(rows_in, model_in):
    """
    One output per row from that row's x only.

    Args:
        rows_in (pd.DataFrame): Feature rows (shuffled)
        model_in (dict | None): Output of fit

    Returns:
        pd.DataFrame: enter, delta
    """
    # A MISSING MODEL NEVER ENTERS
    threshold_float = 0.0 if model_in is None else float(model_in["threshold"])
    enter_arr = rows_in["x"].to_numpy(dtype=float) > threshold_float
    return pd.DataFrame({"enter": enter_arr, "delta": [DELTA] * len(rows_in)})


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): lo or hi

    Returns:
        MinuteThresholdDesign: Fresh object
    """
    # TWO FIXED THRESHOLDS
    if str(candidate_in) == "lo":
        return MinuteThresholdDesign(0.0)
    if str(candidate_in) == "hi":
        return MinuteThresholdDesign(0.5)
    raise ValueError(f"unknown candidate {candidate_in!r}")
