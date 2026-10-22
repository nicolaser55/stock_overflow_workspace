import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config as so_config
from experiments.exp02_stop_reentry import config as exp_config
from experiments.exp02_stop_reentry.model import (fit_reentry_model_dict, predict_reentry_proba_arr,
                                                  get_candidate_name_str, parse_candidate_dict)

"""
Runner Design: exp02_stop_reentry_v2_1

Runner port of protocol 2.0 (rules of protocol 1.0). Invested by default. A volatility trailing stop exits (the
trailing-stop engine checks it minute by minute). A logistic model of the 20-session forward return buys back when its
probability clears the refit's training base rate plus the candidate's offset. The model is refit weekly on the
candidate's window (10 years, or all history) through the label door; an unfinished label never reaches the fit.

decide(view) is position-independent: target weight 1 when P >= p* (the engine buys only while in cash), NaN
otherwise (keep). Every decision also carries the candidate's k and today's daily_volatility. The engine applies them
from this decision's fill until the next decision's fill (docs/RUNNER_DESIGN.md, stop parameters).

Inputs, all through the view:
    TSDAY      today's 16 daily features (available at the decision moment), including daily_volatility
    TSDAY_FWD  training rows: the same features plus y_fwd_positive, served once label_known_ts is before the moment

Refit schedule (as protocol 2.0): the first session of each ISO week on which today's features are finite, and the
first such session of the stream.
"""

# DEFINE HOW CANDIDATE PERIODS ARE FORMED
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FOLD_TRAIN_WINDOW_YEARS]}
# DEFINE THE 18 CANDIDATES IN THE PROTOCOL ORDER (WINDOW, THEN k, THEN OFFSET)
CANDIDATE_LIST = [get_candidate_name_str(window_str, stop_k, offset)
                  for window_str in exp_config.TRAIN_WINDOW_CANDIDATE_LIST
                  for stop_k in exp_config.STOP_K_LIST
                  for offset in exp_config.REENTRY_THRESHOLD_OFFSET_LIST]
# DEFINE THE SELECTION RULE (MEAN OF THE LAST 4 QUARTERS; TIES: LARGER k, HIGHER OFFSET, THEN THE SHORTER WINDOW)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT,
                  "tie_break": [("stop_k", False), ("threshold_offset", False), ("train_window_months", True)]}
# DEFINE THE TIE COLUMNS THE RUNNER ATTACHES
CANDIDATE_TIE_VALUE_DICT = {
    "stop_k": {name_str: parse_candidate_dict(name_str)["stop_k"] for name_str in CANDIDATE_LIST},
    "threshold_offset": {name_str: parse_candidate_dict(name_str)["threshold_offset"] for name_str in CANDIDATE_LIST},
    "train_window_months": {name_str: int(exp_config.TRAIN_WINDOW_TIE_DICT[parse_candidate_dict(name_str)["train_window"]]) for name_str in CANDIDATE_LIST},
}
# COPY THE NAME AND THE PROTOCOL VERSION
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
# BARS, TODAY'S DAILY FEATURES, AND THE 20-SESSION LABEL FOR TRAINING
DATA_SOURCE_LIST = ["SPY_1MIN", "TSDAY", "TSDAY_FWD"]
FEATURE_SOURCE_STR = "TSDAY"
LABEL_SOURCE_STR = "TSDAY_FWD"
# TRAILING-STOP ENGINE: START INVESTED, FORCED RE-ENTRY AFTER 60 CASH DECISIONS
ENGINE_NAME = "trailing_stop"
INITIAL_WEIGHT = 1.0
MAX_CASH_SESSIONS = exp_config.MAX_CASH_SESSIONS
# THE RETRAINING SETTINGS THE LEDGER ROW COPIES
RETRAIN_FREQUENCY_STR = exp_config.RETRAIN_FREQUENCY_STR
TRAIN_WINDOW_CANDIDATE_LIST = list(exp_config.TRAIN_WINDOW_CANDIDATE_LIST)
MIN_TRAIN_ROW_COUNT = exp_config.MIN_TRAIN_ROW_COUNT
FEATURE_COL_LIST = list(so_config.DAILY_FEATURE_COL_STR_LIST)
LABEL_COL_STR = exp_config.LABEL_COL_STR
# THE STOP VOLATILITY COLUMN (ONE OF THE 16 FEATURES; THE SAME COLUMN PROTOCOL 1.0 USED)
VOLATILITY_COL_STR = "daily_volatility"


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    One (window, k, offset) candidate. The runner calls this once per candidate stream.

    Args:
        candidate_in (str): Candidate name

    Returns:
        Design: Fresh object
    """
    # UNKNOWN NAMES ARE A DESIGN ERROR
    if str(candidate_in) not in CANDIDATE_LIST:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return Design(str(candidate_in))


# FUNCTION: A DATE-LIKE CELL TO A DAY ORDINAL
def get_day_ordinal_int(value_in):
    """
    Args:
        value_in: str, date or Timestamp

    Returns:
        int: date.toordinal()
    """
    # ONE PARSE PER ROW (ROWS ARRIVE ONE SESSION AT A TIME AFTER THE FIRST CALL)
    return int(pd.Timestamp(value_in).date().toordinal())


# CLASS: ONE STOP / RE-ENTRY CANDIDATE
class Design:
    """One window, one k, one offset. decide(view) refits weekly through the label door and returns a decision dict."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME
    RETRAIN_FREQUENCY_STR = RETRAIN_FREQUENCY_STR

    # FUNCTION: STORE THE CANDIDATE AND EMPTY STATE
    def __init__(self, candidate_str_in):
        """
        Args:
            candidate_str_in (str): Candidate name
        """
        # THE CANDIDATE IS FIXED FOR THE STREAM
        candidate_dict = parse_candidate_dict(candidate_str_in)
        self.candidate_str = str(candidate_str_in)
        self.train_window_str = str(candidate_dict["train_window"])
        self.stop_k_float = float(candidate_dict["stop_k"])
        self.offset_float = float(candidate_dict["threshold_offset"])
        # TRAINING ROWS RECEIVED SO FAR (ARRIVAL ORDER = SESSION ORDER, BECAUSE label_known_ts IS MONOTONE)
        self.label_day_list = []
        self.label_feature_list = []
        self.label_value_list = []
        # THE MODEL IN FORCE
        self.model = None
        self.model_id_int = -1
        self.balance_float = np.nan
        self.last_refit_week_tuple = None
        # ONE ROW PER DECISION AND PER REFIT (READ BY THE CALIBRATION SCRIPT FROM THE CHECKPOINT)
        self.decision_log_list = []
        self.refit_log_list = []

    # FUNCTION: APPEND THE TRAINING ROWS THAT BECAME KNOWN SINCE THE LAST CALL
    def _receive_labels(self, view_in):
        """
        Args:
            view_in: DecisionView

        Returns:
            None
        """
        # ONLY THE NEW ROWS ARE COPIED
        new_pdf = view_in.get_new(LABEL_SOURCE_STR, columns_in=["date"] + FEATURE_COL_LIST + [LABEL_COL_STR])
        if len(new_pdf) == 0:
            return
        feature_arr = new_pdf[FEATURE_COL_LIST].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        label_arr = pd.to_numeric(new_pdf[LABEL_COL_STR], errors="coerce").to_numpy(dtype=float)
        self.label_day_list.extend(get_day_ordinal_int(day) for day in new_pdf["date"])
        self.label_feature_list.extend(list(feature_arr))
        self.label_value_list.extend(label_arr.tolist())

    # FUNCTION: TODAY'S FEATURE ROW
    def _get_today_feature_arr(self, view_in):
        """
        The newest TSDAY row, if it is today's session. NaNs when today's row is missing.

        Args:
            view_in: DecisionView

        Returns:
            np.ndarray: 16 features in FEATURE_COL_LIST order
        """
        # THE ROWS SINCE THE LAST CALL END WITH TODAY'S (AVAILABLE AT THE DECISION MOMENT)
        new_pdf = view_in.get_new(FEATURE_SOURCE_STR, columns_in=["date"] + FEATURE_COL_LIST)
        if len(new_pdf) == 0 or pd.Timestamp(new_pdf["date"].iloc[-1]).date() != pd.Timestamp(view_in.session_date).date():
            return np.full(len(FEATURE_COL_LIST), np.nan)
        return pd.to_numeric(new_pdf[FEATURE_COL_LIST].iloc[-1], errors="coerce").to_numpy(dtype=float)

    # FUNCTION: REFIT ON THE ROWS INSIDE THE WINDOW
    def _refit(self, view_in, today_ordinal_int_in):
        """
        Rows dated in [decision day - window, decision day] with finite features and label (labels were already
        filtered by the door: label_known_ts strictly before this moment). Fewer than the minimum raises.

        Args:
            view_in: DecisionView
            today_ordinal_int_in (int): Today's day ordinal

        Returns:
            None
        """
        # IMPORT THE WINDOW START HERE
        from so.core.rolling_retrain import get_train_window_start_ts
        start_ts = get_train_window_start_ts(view_in.decision_ts, self.train_window_str)
        start_ordinal = None if start_ts is None else int(start_ts.date().toordinal())
        day_arr = np.asarray(self.label_day_list, dtype=np.int64)
        feature_arr = np.asarray(self.label_feature_list, dtype=float).reshape(len(self.label_day_list), len(FEATURE_COL_LIST))
        label_arr = np.asarray(self.label_value_list, dtype=float)
        date_mask_arr = day_arr <= int(today_ordinal_int_in)
        if start_ordinal is not None:
            date_mask_arr &= day_arr >= start_ordinal
        keep_mask_arr = date_mask_arr & np.isfinite(feature_arr).all(axis=1) & np.isfinite(label_arr)
        if int(keep_mask_arr.sum()) < int(MIN_TRAIN_ROW_COUNT):
            raise ValueError(f"refit on {view_in.session_date} ({self.train_window_str}) has {int(keep_mask_arr.sum())} "
                             f"training rows, below the minimum {int(MIN_TRAIN_ROW_COUNT)}.")
        # THE SAME ESTIMATOR, COLUMNS AND SEED AS PROTOCOL 2.0
        train_pdf = pd.DataFrame(feature_arr[keep_mask_arr], columns=FEATURE_COL_LIST)
        train_pdf[LABEL_COL_STR] = label_arr[keep_mask_arr]
        self.model = fit_reentry_model_dict(train_pdf, FEATURE_COL_LIST, LABEL_COL_STR, int(exp_config.MODEL_SEED))
        self.model_id_int += 1
        self.balance_float = float(np.mean(train_pdf[LABEL_COL_STR].to_numpy(dtype=float)))
        self.refit_log_list.append({"model_id": self.model_id_int, "retrain_session": pd.Timestamp(view_in.session_date).date(),
                                    "decision_ts": view_in.decision_ts, "train_window": self.train_window_str,
                                    "rows_used": int(keep_mask_arr.sum()), "label_balance": self.balance_float})

    # FUNCTION: THE DECISION AT THIS MOMENT
    def decide(self, view_in):
        """
        Refit when due, predict on today's features, and return the re-entry flag with this candidate's stop.

        Args:
            view_in: DecisionView

        Returns:
            dict: target_weight (1 or NaN), trail_multiple, volatility, reentry_reason
        """
        # LABELS FIRST (THEY NEVER INCLUDE TODAY), THEN TODAY'S FEATURES
        self._receive_labels(view_in)
        feature_arr = self._get_today_feature_arr(view_in)
        volatility_float = float(feature_arr[FEATURE_COL_LIST.index(VOLATILITY_COL_STR)])
        session_day = pd.Timestamp(view_in.session_date).date()
        proba_float, threshold_float = np.nan, np.nan
        if np.isfinite(feature_arr).all():
            # WEEKLY: THE FIRST SESSION OF EACH ISO WEEK WITH FINITE FEATURES
            week_tuple = tuple(session_day.isocalendar()[:2])
            if self.model is None or week_tuple != self.last_refit_week_tuple:
                self._refit(view_in, int(session_day.toordinal()))
                self.last_refit_week_tuple = week_tuple
            feature_pdf = pd.DataFrame([feature_arr], columns=FEATURE_COL_LIST)
            proba_float = float(np.asarray(predict_reentry_proba_arr(self.model, feature_pdf, FEATURE_COL_LIST), dtype=float).reshape(-1)[0])
            threshold_float = float(self.balance_float + self.offset_float)
        reentry_bool = bool(np.isfinite(proba_float) and np.isfinite(threshold_float) and proba_float >= threshold_float)
        self.decision_log_list.append({"session": session_day, "proba": proba_float, "threshold": threshold_float,
                                       "model_id": self.model_id_int, "volatility": volatility_float})
        return {"target_weight": 1.0 if reentry_bool else np.nan, "trail_multiple": self.stop_k_float,
                "volatility": volatility_float, "reentry_reason": "model", "flatten_bool": False}
