"""
Synthetic minute design for the training-history and shared-fit tests (tests/test_runner_minute.py).

Rows from MINUTE_TEST_FEAT, labels from MINUTE_TEST_LABEL. Training uses rows before the scored span
(TRAIN_ROW_HISTORY_BOOL). Both candidates share one fit per refit (FIT_KEY_STR). FIT_CALL_LIST records every real fit.
"""

import pandas as pd

# MINUTE MODE, BARRIER ENGINE, START IN CASH
MODE = "minute"
ENGINE_NAME = "barrier"
INITIAL_WEIGHT = 0.0
DELTA = 0.01
ROW_SOURCE_LIST = ["MINUTE_TEST_FEAT"]
LABEL_SOURCE_LIST = ["MINUTE_TEST_LABEL"]
DATA_SOURCE_LIST = ["SPY_1MIN", "MINUTE_TEST_FEAT", "MINUTE_TEST_LABEL"]
FEATURE_COL_LIST = ["x"]
RETRAIN_FREQUENCY_STR = "weekly"
TRAIN_ROW_HISTORY_BOOL = True
ROW_SAMPLE_EVERY_N_MINUTES = 15
CANDIDATE_LIST = ["lo", "hi"]
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("candidate", True)]}
EXPERIMENT_NAME = "runner_minute_shared_test"
PROTOCOL_VERSION = "test"
# ROW COUNT OF EVERY REAL FIT IN THIS PROCESS
FIT_CALL_LIST = []


# CLASS: ONE THRESHOLD, ONE SHARED FIT
class SharedDesign:
    """fit_shared counts the rows; finish_fit adds the threshold."""

    # FUNCTION: STORE THE THRESHOLD
    def __init__(self, threshold_in):
        """
        Args:
            threshold_in (float): Enter when x is above this
        """
        # THE WINDOW AND THE FIT KEY ARE THE SAME FOR BOTH CANDIDATES
        self.threshold_float = float(threshold_in)
        self.TRAIN_WINDOW_STR = "ALL"
        self.FIT_KEY_STR = "all"

    # FUNCTION: THE SHARED PART OF THE FIT
    def fit_shared(self, train_rows_in):
        """
        Args:
            train_rows_in (pd.DataFrame): Training rows

        Returns:
            dict: rows, first_decision_ts
        """
        # RECORD THE CALL
        FIT_CALL_LIST.append(int(len(train_rows_in)))
        first_ts = train_rows_in["decision_ts"].iloc[0] if len(train_rows_in) else None
        return {"rows": int(len(train_rows_in)), "first_decision_ts": first_ts}

    # FUNCTION: ADD THE CANDIDATE'S THRESHOLD
    def finish_fit(self, shared_model_in):
        """
        Args:
            shared_model_in (dict): Output of fit_shared

        Returns:
            dict: rows, first_decision_ts, threshold
        """
        # THE SHARED PART IS NOT CHANGED
        return {**shared_model_in, "threshold": float(self.threshold_float)}

    # FUNCTION: FIT WITHOUT SHARING
    def fit(self, train_rows_in):
        """
        Args:
            train_rows_in (pd.DataFrame): Training rows

        Returns:
            dict: Model
        """
        # SAME OBJECT AS THE SHARED PATH
        return self.finish_fit(self.fit_shared(train_rows_in))


# FUNCTION: ROW-LOCAL THRESHOLD RULE
def signal(rows_in, model_in):
    """
    Args:
        rows_in (pd.DataFrame): x
        model_in (dict | None): Model

    Returns:
        pd.DataFrame: enter, delta
    """
    # NO MODEL: NO ENTRY
    threshold = 2.0 if model_in is None else float(model_in["threshold"])
    return pd.DataFrame({"enter": rows_in["x"].to_numpy(dtype=float) > threshold, "delta": [DELTA] * len(rows_in)})


# FUNCTION: A FRESH DESIGN OBJECT
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): lo or hi

    Returns:
        SharedDesign: Fresh object
    """
    # TWO THRESHOLDS
    return SharedDesign(0.3 if str(candidate_in) == "lo" else 0.7)
