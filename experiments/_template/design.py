# IMPORT THE EXPERIMENT CONFIGURATION
from experiments._template import config as exp_config
import numpy as np
import pandas as pd

"""
Holdout Design (template, fractional-exposure family, rolling retrain)

The holdout result is the design's frozen prior-only path from its development start, continued without interruption
through the holdout window: same code, same decision bar (15:58) and fill (15:59), same costs, dead band and cash
rules, same candidate periods and selection rule, selection history and position carried over from development. Only
the holdout sessions are reported. Every decision uses only information available at its decision bar.

This template is the model-based example. A logistic regression on two daily features is refit weekly
(so.core.rolling_retrain.run_rolling_retrain_dict) on each pre-registered training window. The label is the sign of
the 20-session forward return. An unfinished label is dropped, never filled. The weight is the predicted probability.
An exit-family design implements run_prior_only_path_dict by calling
so.core.replay_walk_forward.run_prior_only_replay_dict instead of the fractional simulator.
"""

# DEFINE HOW CANDIDATE PERIODS ARE FORMED (DEVELOPMENT QUARTERS, EXTENDED THROUGH THE HOLDOUT BY THE RUNNER)
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FOLD_TRAIN_WINDOW_YEARS]}
# DEFINE THE CANDIDATES (ONE ROLLING MODEL PER TRAINING WINDOW) AND THE SELECTION RULE
CANDIDATE_LIST = list(exp_config.TRAIN_WINDOW_CANDIDATE_LIST)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT,
                  "tie_break": [("train_window_months", False), ("candidate", True)]}
# DEFINE THE TIE COLUMN THE RUNNER ATTACHES (LONGER WINDOW FIRST)
CANDIDATE_TIE_VALUE_DICT = {"train_window_months": dict(exp_config.TRAIN_WINDOW_TIE_DICT)}
# DEFINE THE DEAD BAND (0: THE WEIGHT TRACKS THE PREDICTED PROBABILITY)
DEAD_BAND = 0.0
# COPY THE NAME AND THE PROTOCOL VERSION (THE TRIAL LOG AND THE DESIGN HASH READ THEM)
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
# EVERY INPUT IS READ THROUGH THE POINT-IN-TIME CONTEXT (SPY BARS ONLY)
DATA_SOURCE_LIST = ["SPY_1MIN"]
# THE RETRAINING SETTINGS THE LEDGER ROW COPIES
RETRAIN_FREQUENCY_STR = exp_config.RETRAIN_FREQUENCY_STR
TRAIN_WINDOW_CANDIDATE_LIST = list(exp_config.TRAIN_WINDOW_CANDIDATE_LIST)
MIN_TRAIN_ROW_COUNT = exp_config.MIN_TRAIN_ROW_COUNT
FEATURE_COL_LIST = list(exp_config.FEATURE_COL_LIST)
LABEL_COL_STR = exp_config.LABEL_COL_STR
# CACHES ARE ALLOWED WITHIN ONE REPLAY ONLY. THE RUNNER GIVES EVERY REPLAY A FRESH MODULE.
# KEYED BY THE BAR ARRAY, SO LATER PERIOD SCORES AND THE PATH REUSE THE FIRST FIT OF THESE BARS.
_retrain_cache_dict = {}

# FUNCTION: A CHEAP KEY FOR ONE BAR ARRAY
def get_bar_key_tuple(ohlcv_array_dict_in):
    """
    Identifies a bar array so a later call on the same bars reuses the fit. A truncated or perturbed array differs
    in length or in the close sum.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        tuple: Length, first close, last close, close sum
    """
    # THE CLOSE SUM MOVES WHEN A LATER BAR IS PERTURBED
    close_arr = np.asarray(ohlcv_array_dict_in["close_arr"], dtype=float)
    return (int(len(close_arr)), round(float(close_arr[0]), 8), round(float(close_arr[-1]), 8), round(float(close_arr.sum()), 4))

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

# FUNCTION: ONE LABELLED ROW PER SESSION
def get_labelled_row_pdf(ohlcv_array_dict_in):
    """
    Daily features, the fixed-horizon label, and the clocks the rolling fit requires. decision_ts and available_ts
    are the decision moment (the end of the 15:58 bar). label_known_ts is the decision moment of the session
    LABEL_HORIZON_SESSIONS later. The last horizon sessions have no clock and a missing label.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.DataFrame: Rows for run_rolling_retrain_dict
    """
    # IMPORT THE CLOCKS AND THE DAILY FEATURES HERE
    from so import config
    from so.core.point_in_time import get_decision_ts
    from so.core.rolling_retrain import get_fixed_horizon_label_known_ts_arr
    from so.features.daily_features import get_daily_feature_pdf
    # THE DAILY TABLE, THEN THE DECISION MOMENT IN PLACE OF THE BAR-START LABEL
    daily_pdf = get_daily_feature_pdf(ohlcv_array_dict_in, config.LABEL_HORIZON_SESSIONS).copy()
    decision_list = [get_decision_ts(bar_ts) for bar_ts in daily_pdf["decision_ts"]]
    daily_pdf["decision_ts"] = decision_list
    daily_pdf["row_ts"] = decision_list
    daily_pdf["available_ts"] = decision_list
    daily_pdf["session"] = [pd.Timestamp(day).date() for day in daily_pdf["date"]]
    daily_pdf["label_known_ts"] = get_fixed_horizon_label_known_ts_arr(decision_list, config.LABEL_HORIZON_SESSIONS)
    return daily_pdf

# FUNCTION: DECISION SESSIONS LATE ENOUGH THAT THE FIRST REFIT MEETS THE MINIMUM
def get_decision_session_list(row_pdf_in):
    """
    Sessions from the warmup index onward. The first of them is always a refit.

    Args:
        row_pdf_in (pd.DataFrame): Labelled rows

    Returns:
        list: Session dates
    """
    # THE WARMUP COVERS THE MINIMUM, THE HORIZON, AND A SMALL EXTRA
    from so import config
    start_idx = int(exp_config.MIN_TRAIN_ROW_COUNT + config.LABEL_HORIZON_SESSIONS + exp_config.FIRST_DECISION_EXTRA_SESSIONS)
    if start_idx >= len(row_pdf_in):
        raise ValueError(f"the series has {len(row_pdf_in)} sessions, shorter than the warmup {start_idx}.")
    return list(row_pdf_in["session"].iloc[start_idx:])

# FUNCTION: FIT ONE TRAINING WINDOW, REUSING A PREVIOUS FIT OF THE SAME BARS
def get_window_retrain_dict(ohlcv_array_dict_in, train_window_str_in):
    """
    Weekly rolling logistic regression for one training window. The same bars return the cached fit.

    Args:
        ohlcv_array_dict_in (dict): Bars
        train_window_str_in (str): "6M", "2Y" or "10Y"

    Returns:
        dict: prediction_pdf, refit_log_pdf
    """
    # IMPORT THE WALKER HERE
    from so.core.rolling_retrain import run_rolling_retrain_dict
    # REUSE THE FIT WHEN THE BARS HAVE NOT CHANGED
    cache_key = (get_bar_key_tuple(ohlcv_array_dict_in), str(train_window_str_in))
    if cache_key in _retrain_cache_dict:
        return _retrain_cache_dict[cache_key]
    # BUILD THE ROWS AND WALK THE DECISIONS
    row_pdf = get_labelled_row_pdf(ohlcv_array_dict_in)
    decision_list = get_decision_session_list(row_pdf)
    result_dict = run_rolling_retrain_dict(row_pdf, FEATURE_COL_LIST, LABEL_COL_STR, fit_template_logistic_dict,
                                           predict_template_logistic_arr, decision_list, train_window_str_in,
                                           RETRAIN_FREQUENCY_STR, int(exp_config.MODEL_SEED), int(MIN_TRAIN_ROW_COUNT), True)
    _retrain_cache_dict[cache_key] = result_dict
    return result_dict

# FUNCTION: READ SPY THROUGH THE CONTEXT SO THE ACCESS LOG RECORDS IT
def read_context_inputs(ohlcv_array_dict_in, data_context_in):
    """
    Reads SPY_1MIN as of the last decision in this bar set. The model uses the daily features built from the same bars.

    Args:
        ohlcv_array_dict_in (dict): Bars
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        None
    """
    # SPY THROUGH THE CONTEXT, AS OF THE LAST DECISION MOMENT
    if data_context_in is None or not data_context_in.has_source_bool("SPY_1MIN") or not len(ohlcv_array_dict_in["session_date_list"]):
        return
    from so.core.point_in_time import get_decision_ts
    from so.features.daily_features import get_session_decision_idx_dict
    decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][-1])
    decision_ts = get_decision_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])
    data_context_in.set_decision_ts(decision_ts)
    data_context_in.get("SPY_1MIN", decision_ts, columns_in=["timestamp", "close", "available_ts"])
    data_context_in.set_decision_ts(None)

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

# FUNCTION: WRITE ONE CANDIDATE'S PREDICTIONS ONTO A DATE SPAN
def get_span_weight_arr(ohlcv_array_dict_in, prediction_pdf_in, date1_in, date2_in):
    """
    Target weight per session position. Sessions outside the span, and sessions before the first model, stay NaN.

    Args:
        ohlcv_array_dict_in (dict): Bars
        prediction_pdf_in (pd.DataFrame): session, prediction
        date1_in, date2_in: Span

    Returns:
        np.ndarray: Weights
    """
    # MAP THE PREDICTIONS AND FILL THE SPAN
    pred_dict = {pd.Timestamp(session_date).date(): float(prediction) for session_date, prediction in zip(prediction_pdf_in["session"], prediction_pdf_in["prediction"])}
    start_date, end_date = pd.Timestamp(date1_in).date(), pd.Timestamp(date2_in).date()
    target_arr = np.full(len(ohlcv_array_dict_in["session_date_list"]), np.nan)
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        session_day = pd.Timestamp(session_date).date()
        if start_date <= session_day <= end_date and session_day in pred_dict:
            target_arr[session_idx] = get_weight_float(pred_dict[session_day])
    return target_arr

# FUNCTION: REPLAY ONE CANDIDATE OVER ONE PERIOD
def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
    """
    The rolling model of candidate_in (a training window), simulated over the period. The fit uses only rows whose
    label was knowable before each retraining decision.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Period bounds
        candidate_in (str): Training window
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, metric_dict
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.fractional_exposure import simulate_fractional_exposure_dict
    # READ SPY THROUGH THE CONTEXT, THEN THE CACHED ROLLING MODEL
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    result_dict = get_window_retrain_dict(ohlcv_array_dict_in, str(candidate_in))
    target_arr = get_span_weight_arr(ohlcv_array_dict_in, result_dict["prediction_pdf"], date1_in, date2_in)
    finite_idx_arr = np.flatnonzero(np.isfinite(target_arr))
    if len(finite_idx_arr) == 0:
        raise ValueError(f"candidate {candidate_in} has no prediction between {date1_in} and {date2_in}.")
    initial_weight_float = float(target_arr[finite_idx_arr[0]])
    return simulate_fractional_exposure_dict(ohlcv_array_dict_in, date1_in, date2_in, target_arr, DEAD_BAND, initial_weight_float)

# FUNCTION: THE CANDIDATE IN FORCE ON ONE SESSION
def get_session_candidate_str(session_date_in, period_pdf_in, selection_pdf_in):
    """
    The governing candidate of the period that contains the session, or None when the session is outside every period.

    Args:
        session_date_in (datetime.date): Session
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force

    Returns:
        str | None: Candidate
    """
    # THE PERIOD THAT COVERS THE SESSION
    session_day = pd.Timestamp(session_date_in).date()
    cover_pdf = period_pdf_in[(period_pdf_in["period_start"].map(lambda value: pd.Timestamp(value).date()) <= session_day)
                              & (period_pdf_in["period_end"].map(lambda value: pd.Timestamp(value).date()) >= session_day)]
    if cover_pdf.empty:
        return None
    period_id = int(cover_pdf["period_id"].iloc[-1])
    return selection_pdf_in.loc[selection_pdf_in["period_id"] == period_id, "candidate"].iloc[0]

# FUNCTION: REPLAY THE CONTINUOUS PRIOR-ONLY PATH
def run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
    """
    One fractional-exposure replay from the first period through the last. Each session uses the latest weekly model
    of the candidate in force. The refit log is the models actually used, one block per candidate.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force per period
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, target_weight_arr, signal_arr, decision_session_list, refit_log_pdf
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.fractional_exposure import simulate_fractional_exposure_dict
    # READ SPY AND FIT EACH WINDOW ONCE
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    window_dict = {window_str: get_window_retrain_dict(ohlcv_array_dict_in, window_str) for window_str in CANDIDATE_LIST}
    # THE SPAN OF THE PATH
    date1 = period_pdf_in["period_start"].iloc[0]
    date2 = period_pdf_in["period_end"].iloc[-1]
    start_date, end_date = pd.Timestamp(date1).date(), pd.Timestamp(date2).date()
    # PREDICTION LOOKUP PER WINDOW
    pred_dict, model_dict = {}, {}
    for window_str, result_dict in window_dict.items():
        prediction_pdf = result_dict["prediction_pdf"]
        pred_dict[window_str] = {pd.Timestamp(session_date).date(): float(prediction)
                                 for session_date, prediction in zip(prediction_pdf["session"], prediction_pdf["prediction"])}
        model_dict[window_str] = {pd.Timestamp(session_date).date(): int(model_id)
                                  for session_date, model_id in zip(prediction_pdf["session"], prediction_pdf["model_id"])}
    # WRITE THE GOVERNING PREDICTION ON EACH SESSION OF THE SPAN
    target_arr = np.full(len(ohlcv_array_dict_in["session_date_list"]), np.nan)
    signal_arr = np.full(len(ohlcv_array_dict_in["session_date_list"]), np.nan)
    used_id_dict = {window_str: set() for window_str in CANDIDATE_LIST}
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        session_day = pd.Timestamp(session_date).date()
        if not (start_date <= session_day <= end_date):
            continue
        candidate_str = get_session_candidate_str(session_day, period_pdf_in, selection_pdf_in)
        if candidate_str is None or session_day not in pred_dict[str(candidate_str)]:
            continue
        prediction_float = pred_dict[str(candidate_str)][session_day]
        target_arr[session_idx] = get_weight_float(prediction_float)
        signal_arr[session_idx] = prediction_float
        used_id_dict[str(candidate_str)].add(model_dict[str(candidate_str)][session_day])
    # REPLAY ONCE SO THE POSITION CARRIES ACROSS PERIODS
    finite_idx_arr = np.flatnonzero(np.isfinite(target_arr))
    if len(finite_idx_arr) == 0:
        raise ValueError("the prior-only path has no prediction.")
    initial_weight_float = float(target_arr[finite_idx_arr[0]])
    simulation_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, date1, date2, target_arr, DEAD_BAND, initial_weight_float)
    # ATTACH THE TARGETS AND THE MODELS THE PATH USED (MODEL IDS ARE UNIQUE ONLY WITHIN A CANDIDATE)
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    path_idx_list = [idx for idx, session_date in enumerate(session_date_list) if start_date <= session_date <= end_date]
    simulation_dict["target_weight_arr"] = target_arr[path_idx_list]
    simulation_dict["signal_arr"] = signal_arr[path_idx_list]
    simulation_dict["decision_session_list"] = [session_date_list[idx] for idx in path_idx_list]
    refit_list = []
    for window_str, id_set in used_id_dict.items():
        refit_pdf = window_dict[window_str]["refit_log_pdf"]
        kept_pdf = refit_pdf[refit_pdf["model_id"].isin(id_set)].copy()
        kept_pdf["candidate"] = window_str
        refit_list.append(kept_pdf)
    simulation_dict["refit_log_pdf"] = pd.concat(refit_list, ignore_index=True) if refit_list else pd.DataFrame()
    return simulation_dict

# FUNCTION: GET THE UNINFORMED BASELINE OVER A SPAN
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in):
    """
    Constant exposure at the pre-registered weight, over the span the caller names. The runner names the holdout only.
    The weight is not fit on that span.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span

    Returns:
        dict: baseline name -> total return
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.fractional_exposure import simulate_fractional_exposure_dict
    # HOLD THE CONSTANT WEIGHT FOR THE WHOLE SPAN
    weight_float = float(exp_config.CONSTANT_EXPOSURE_WEIGHT)
    target_arr = np.full(len(ohlcv_array_dict_in["session_date_list"]), weight_float)
    simulation_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, date1_in, date2_in, target_arr, 0.0, weight_float)
    return {"constant_exposure": simulation_dict["metric_dict"]["total_return"]}

# FUNCTION: LOAD DECLARED SOURCES FOR A DEVELOPMENT REPLAY
def get_development_data_context(session_date_list_in):
    """
    Loads DATA_SOURCE_LIST through the development end (embargo sessions before the active window start) and returns
    a development DataContext. The holdout evaluation script loads the same list through the window end instead.
    The runner does not call this function; it passes its own context.

    Args:
        session_date_list_in (list): Session dates that include the window start

    Returns:
        DataContext: Development context
    """
    # THE DEVELOPMENT END IS BEFORE THE WINDOW; THE EVALUATION SCRIPT USES THE WINDOW END
    from so.core.holdout import get_development_end_date
    from so.core.point_in_time import DataContext, load_source_frame_dict
    end_date = get_development_end_date(int(PERIOD_RULE["embargo_sessions"]), session_date_list_in)
    frame_dict = load_source_frame_dict(list(DATA_SOURCE_LIST), end_date)
    return DataContext("development", frame_dict_in=frame_dict, declared_name_list_in=list(DATA_SOURCE_LIST))
