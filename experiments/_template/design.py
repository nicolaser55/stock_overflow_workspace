# IMPORT THE EXPERIMENT CONFIGURATION
from experiments._template import config as exp_config
import numpy as np
import pandas as pd

"""
Runner Design (template, fractional-exposure family, rolling retrain)

The design turns a DecisionView into a target weight. The runner walks time, scores candidates, selects, builds the
prior-only path, baselines, look-ahead, verdict and report. This file does not copy that machinery.

This template is the model-based example. A logistic regression on two daily features is refit weekly on each
pre-registered training window. Features are computed from the view's SPY bars. Labels come through
view.get_labels("TSDAY_FWD"): the 20-session sign, known at the decision of the horizon session. An unfinished or
redacted label is dropped, never filled. The weight is the predicted probability.
"""

# DEFINE HOW CANDIDATE PERIODS ARE FORMED (DEVELOPMENT QUARTERS, EXTENDED THROUGH THE HOLDOUT BY THE RUNNER)
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FOLD_TRAIN_WINDOW_YEARS]}
# DEFINE THE CANDIDATES (ONE ROLLING MODEL PER TRAINING WINDOW) AND THE SELECTION RULE
CANDIDATE_LIST = list(exp_config.TRAIN_WINDOW_CANDIDATE_LIST)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT,
                  "tie_break": [("train_window_months", False), ("candidate", True)]}
# DEFINE THE TIE COLUMN THE RUNNER ATTACHES (LONGER WINDOW FIRST)
CANDIDATE_TIE_VALUE_DICT = {"train_window_months": dict(exp_config.TRAIN_WINDOW_TIE_DICT)}
# DEFINE THE ENGINE AND THE DEAD BAND (0: THE WEIGHT TRACKS THE PREDICTED PROBABILITY)
ENGINE_NAME = "fractional"
DEAD_BAND = 0.0
INITIAL_WEIGHT = 1.0
# COPY THE NAME AND THE PROTOCOL VERSION (THE TRIAL LOG AND THE DESIGN HASH READ THEM)
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
# BARS FOR FEATURES; THE FIXED-HORIZON SIGN FOR TRAINING
DATA_SOURCE_LIST = ["SPY_1MIN", "TSDAY_FWD"]
# THE RETRAINING SETTINGS THE LEDGER ROW COPIES
RETRAIN_FREQUENCY_STR = exp_config.RETRAIN_FREQUENCY_STR
TRAIN_WINDOW_CANDIDATE_LIST = list(exp_config.TRAIN_WINDOW_CANDIDATE_LIST)
MIN_TRAIN_ROW_COUNT = exp_config.MIN_TRAIN_ROW_COUNT
FEATURE_COL_LIST = list(exp_config.FEATURE_COL_LIST)
LABEL_COL_STR = exp_config.LABEL_COL_STR
LABEL_SOURCE_STR = "TSDAY_FWD"


# FUNCTION: FIT A CONSTANT PROBABILITY WHEN THE WINDOW HAS ONE CLASS
def fit_template_logistic_dict(train_pdf_in, feature_col_list_in, label_col_str_in, seed_int_in):
    """
    Logistic regression of the label on the feature columns. A window with one class returns that class's rate. The
    seed is the logistic random_state. This is the model's defined behaviour, not a fallback training window.

    Args:
        train_pdf_in (pd.DataFrame): Training rows
        feature_col_list_in (list[str]): Feature columns
        label_col_str_in (str): Label column
        seed_int_in (int): Seed

    Returns:
        dict: kind "logistic" or "constant"
    """
    # IMPORT THE ESTIMATOR HERE
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    # A ONE-CLASS WINDOW HAS A DEFINED PROBABILITY
    label_arr = train_pdf_in[label_col_str_in].to_numpy(dtype=int)
    if len(np.unique(label_arr)) < 2:
        return {"kind": "constant", "probability": float(np.mean(label_arr))}
    # FIT THE SCALED LOGISTIC REGRESSION
    model = Pipeline([("scaler", StandardScaler()),
                      ("logistic", LogisticRegression(C=float(exp_config.LOGISTIC_C), solver="liblinear", max_iter=200,
                                                      random_state=int(seed_int_in)))])
    model.fit(train_pdf_in[list(feature_col_list_in)].to_numpy(dtype=float), label_arr)
    return {"kind": "logistic", "model": model}


# FUNCTION: PREDICT THE PROBABILITY OF THE POSITIVE CLASS
def predict_template_logistic_arr(model_in, feature_pdf_in, feature_col_list_in):
    """
    One probability per feature row. A constant model repeats its rate.

    Args:
        model_in (dict): Output of fit_template_logistic_dict
        feature_pdf_in (pd.DataFrame): Feature rows
        feature_col_list_in (list[str]): Feature columns

    Returns:
        np.ndarray: Probabilities
    """
    # THE ONE-CLASS RATE
    if model_in["kind"] == "constant":
        return np.full(len(feature_pdf_in), float(model_in["probability"]))
    # THE PROBABILITY OF CLASS 1
    proba_arr = model_in["model"].predict_proba(feature_pdf_in[list(feature_col_list_in)].to_numpy(dtype=float))
    class_arr = list(model_in["model"].named_steps["logistic"].classes_)
    class_idx = class_arr.index(1) if 1 in class_arr else None
    if class_idx is None:
        return np.zeros(len(feature_pdf_in))
    return proba_arr[:, class_idx]


# FUNCTION: CLIP A PROBABILITY INTO A WEIGHT
def get_weight_float(prediction_float_in):
    """
    The target weight is the predicted probability, clipped to [0, 1].

    Args:
        prediction_float_in (float): Probability

    Returns:
        float: Weight
    """
    # CLIP
    return float(min(1.0, max(0.0, prediction_float_in)))


# FUNCTION: TODAY'S TWO DAILY FEATURES FROM THE VIEW BARS
def get_view_feature_dict(view_in):
    """
    intraday_return_pct is decision close over this session's open. prev_day_return_pct is the previous complete
    session's close-to-close return. Both are knowable at the decision bar.

    Args:
        view_in: DecisionView

    Returns:
        dict: Feature name -> float (NaN when the history is too short)
    """
    # THE VIEW ENDS AT THE DECISION BAR
    bar_dict = view_in.get_bar_array_dict()
    close_arr = np.asarray(bar_dict["close_arr"], dtype=float)
    open_arr = np.asarray(bar_dict["open_arr"], dtype=float)
    start_idx_arr = np.asarray(bar_dict["session_start_idx_arr"], dtype=int)
    session_count = len(bar_dict["session_date_list"])
    if session_count < 1 or len(close_arr) < 1:
        return {"intraday_return_pct": np.nan, "prev_day_return_pct": np.nan}
    decision_close = float(close_arr[-1])
    session_open = float(open_arr[int(start_idx_arr[-1])])
    intraday_float = decision_close / session_open - 1.0 if session_open > 0 else np.nan
    # PREVIOUS COMPLETE CLOSE OVER THE CLOSE BEFORE THAT (LAST BAR BEFORE EACH SESSION START)
    if session_count < 3:
        return {"intraday_return_pct": float(intraday_float), "prev_day_return_pct": np.nan}
    prev_close = float(close_arr[int(start_idx_arr[-1]) - 1])
    prev_prev_close = float(close_arr[int(start_idx_arr[-2]) - 1])
    prev_day_float = prev_close / prev_prev_close - 1.0 if prev_prev_close > 0 else np.nan
    return {"intraday_return_pct": float(intraday_float), "prev_day_return_pct": float(prev_day_float)}


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE TRAINING WINDOW
def get_candidate_design(candidate_in):
    """
    One rolling-retrain candidate. The runner calls this once per candidate stream.

    Args:
        candidate_in (str): Training window ("6M", "2Y" or "10Y")

    Returns:
        Design: Fresh object
    """
    # A NEW OBJECT SO PARALLEL STREAMS DO NOT SHARE A FITTED MODEL
    return Design(str(candidate_in))


# CLASS: ONE ROLLING LOGISTIC CANDIDATE
class Design:
    """One training window. decide(view) refits on the weekly schedule through view.get_labels and returns a weight."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME
    RETRAIN_FREQUENCY_STR = RETRAIN_FREQUENCY_STR

    # FUNCTION: STORE THE WINDOW AND EMPTY MODEL STATE
    def __init__(self, train_window_str_in):
        """
        Args:
            train_window_str_in (str): Training window
        """
        # THE WINDOW IS FIXED FOR THE STREAM
        self.train_window_str = str(train_window_str_in)
        self.RETRAIN_FREQUENCY_STR = RETRAIN_FREQUENCY_STR
        self.model = None
        self.retrain_session_set = None
        self.refit_log_list = []

    # FUNCTION: TARGET WEIGHT AT THIS DECISION
    def decide(self, view_in):
        """
        Refit on a retraining session (and always on the first call) using labels known before this moment, then
        predict on today's two features.

        Args:
            view_in: DecisionView

        Returns:
            float: Target weight in [0, 1]
        """
        # IMPORT THE RETRAIN SCHEDULE AND THE WINDOW START HERE
        from so.core.rolling_retrain import get_retrain_session_list, get_train_window_start_ts
        session_date = pd.Timestamp(view_in.session_date).date()
        bar_dict = view_in.get_bar_array_dict()
        session_date_list = [pd.Timestamp(day).date() for day in bar_dict["session_date_list"]]
        # WEEKLY: THE FIRST SESSION OF EACH ISO WEEK IN THE VIEW. THE FIRST CALL ALWAYS REFITS.
        retrain_session_set = set(get_retrain_session_list(session_date_list, session_date_list[0],
                                                          session_date_list[-1], RETRAIN_FREQUENCY_STR))
        self.retrain_session_set = retrain_session_set
        if self.model is None or session_date in retrain_session_set:
            label_pdf = view_in.get_labels(LABEL_SOURCE_STR)
            if label_pdf is None or len(label_pdf) == 0:
                raise ValueError(f"refit on {session_date} ({self.train_window_str}) has 0 training rows, below the minimum {int(MIN_TRAIN_ROW_COUNT)}.")
            train_pdf = label_pdf.copy()
            if "date" in train_pdf.columns:
                row_day_arr = np.asarray([pd.Timestamp(day).date() for day in train_pdf["date"]])
            elif "session" in train_pdf.columns:
                row_day_arr = np.asarray([pd.Timestamp(day).date() for day in train_pdf["session"]])
            else:
                raise ValueError("TSDAY_FWD rows need a date or session column.")
            start_ts = get_train_window_start_ts(view_in.decision_ts, self.train_window_str)
            start_day = None if start_ts is None else start_ts.date()
            date_mask_arr = np.asarray([(start_day is None or row_day >= start_day) and row_day <= session_date
                                        for row_day in row_day_arr], dtype=bool)
            feature_arr = train_pdf[list(FEATURE_COL_LIST)].to_numpy(dtype=float)
            label_arr = pd.to_numeric(train_pdf[LABEL_COL_STR], errors="coerce").to_numpy(dtype=float)
            finite_mask_arr = date_mask_arr & np.isfinite(feature_arr).all(axis=1) & np.isfinite(label_arr)
            fit_pdf = train_pdf.loc[finite_mask_arr].copy()
            purged_count = int((date_mask_arr & ~np.isfinite(label_arr)).sum())
            if len(fit_pdf) < int(MIN_TRAIN_ROW_COUNT):
                raise ValueError(f"refit on {session_date} ({self.train_window_str}) has {len(fit_pdf)} training rows, below the minimum {int(MIN_TRAIN_ROW_COUNT)}.")
            self.model = fit_template_logistic_dict(fit_pdf, FEATURE_COL_LIST, LABEL_COL_STR, int(exp_config.MODEL_SEED))
            last_known_ts = max(pd.Timestamp(label_ts) for label_ts in fit_pdf["label_known_ts"].to_numpy())
            self.refit_log_list.append({
                "retrain_session": session_date, "decision_ts": view_in.decision_ts,
                "train_window": self.train_window_str, "rows_used": int(len(fit_pdf)),
                "rows_purged": purged_count, "last_label_known_ts": last_known_ts,
            })
        if self.model is None:
            raise ValueError(f"no fitted model for decision session {session_date}.")
        # TODAY'S FEATURES FROM THE BARS, NOT FROM A LABEL ROW
        feature_dict = get_view_feature_dict(view_in)
        feature_pdf = pd.DataFrame([feature_dict])
        if not np.isfinite(feature_pdf[list(FEATURE_COL_LIST)].to_numpy(dtype=float)).all():
            return np.nan
        prediction_arr = predict_template_logistic_arr(self.model, feature_pdf, FEATURE_COL_LIST)
        return get_weight_float(float(prediction_arr[0]))
