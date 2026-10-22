import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config as so_config
from experiments.exp02_stop_reentry import config as exp_config
from experiments.exp02_stop_reentry.model import fit_reentry_model_dict, predict_reentry_proba_arr

"""
Protocol 2.0 Reference: exp02_stop_reentry_v2 (calibration only)

The version 2.0 model path, kept verbatim from the 2.0 design.py (commit cb4fa16) so the 2.1 runner port can be
compared with it on the same bars: daily features and the 20-session label computed in memory from the bars, the
weekly rolling logistic regression of so.core.rolling_retrain.run_rolling_retrain_dict, and the per-session
probability and threshold (training base rate + offset).

design.py never imports this file. It is used by tests/test_exp02.py and scripts/compare_exp02_calibration.py only.
It reads no file and writes no trial row.
"""

# THE COLUMNS OF THE 2.0 PATH
FEATURE_COL_LIST = list(so_config.DAILY_FEATURE_COL_STR_LIST)
LABEL_COL_STR = exp_config.LABEL_COL_STR


# FUNCTION: ONE LABELLED ROW PER SESSION (2.0 get_labelled_row_pdf)
def get_labelled_row_pdf(ohlcv_array_dict_in):
    """
    Daily features, the 20-session label, and the clocks the rolling fit requires.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.DataFrame: Rows for run_rolling_retrain_dict
    """
    # IMPORT THE CLOCKS AND THE DAILY FEATURES HERE
    from so.core.point_in_time import get_decision_ts
    from so.core.rolling_retrain import get_fixed_horizon_label_known_ts_arr
    from so.features.daily_features import get_daily_feature_pdf
    # THE DAILY TABLE, THEN THE DECISION MOMENT IN PLACE OF THE BAR-START LABEL
    daily_pdf = get_daily_feature_pdf(ohlcv_array_dict_in, so_config.LABEL_HORIZON_SESSIONS).copy()
    decision_list = [get_decision_ts(bar_ts) for bar_ts in daily_pdf["decision_ts"]]
    daily_pdf["decision_ts"] = decision_list
    daily_pdf["row_ts"] = decision_list
    daily_pdf["available_ts"] = decision_list
    daily_pdf["session"] = [pd.Timestamp(day).date() for day in daily_pdf["date"]]
    daily_pdf["label_known_ts"] = get_fixed_horizon_label_known_ts_arr(decision_list, so_config.LABEL_HORIZON_SESSIONS)
    return daily_pdf


# FUNCTION: DECISION SESSIONS FROM THE WARMUP ON (2.0 get_decision_session_list)
def get_decision_session_list(row_pdf_in):
    """
    Sessions from the feature warmup onward whose features are finite. The first of them is always a refit.

    Args:
        row_pdf_in (pd.DataFrame): Labelled rows

    Returns:
        list: Session dates
    """
    # THE 250-SESSION RETURN IS THE LONGEST FEATURE; THE LABEL THEN NEEDS THE HORIZON, THEN THE MINIMUM
    start_idx = int(max(so_config.PAST_RETURN_SESSION_LIST) + so_config.LABEL_HORIZON_SESSIONS + exp_config.MIN_TRAIN_ROW_COUNT)
    if start_idx >= len(row_pdf_in):
        raise ValueError(f"the series has {len(row_pdf_in)} sessions, shorter than the warmup {start_idx}.")
    finite_arr = row_pdf_in[FEATURE_COL_LIST].apply(pd.to_numeric, errors="coerce").notna().all(axis=1).to_numpy()
    return [session_date for session_date, finite_bool in zip(row_pdf_in["session"].iloc[start_idx:], finite_arr[start_idx:]) if finite_bool]


# FUNCTION: THE WEEKLY ROLLING FIT OF ONE TRAINING WINDOW (2.0 get_window_retrain_dict, NO CACHE)
def get_window_retrain_dict(ohlcv_array_dict_in, train_window_str_in, row_pdf_in=None):
    """
    Args:
        ohlcv_array_dict_in (dict): Bars
        train_window_str_in (str): "10Y" or "ALL"
        row_pdf_in (pd.DataFrame | None): Labelled rows already built from the same bars

    Returns:
        dict: prediction_pdf, refit_log_pdf, row_pdf
    """
    # IMPORT THE WALKER HERE
    from so.core.rolling_retrain import run_rolling_retrain_dict
    # THE ROWS, THEN THE WALK
    row_pdf = row_pdf_in if row_pdf_in is not None else get_labelled_row_pdf(ohlcv_array_dict_in)
    decision_list = get_decision_session_list(row_pdf)
    result_dict = run_rolling_retrain_dict(row_pdf, FEATURE_COL_LIST, LABEL_COL_STR, fit_reentry_model_dict,
                                           predict_reentry_proba_arr, decision_list, train_window_str_in,
                                           exp_config.RETRAIN_FREQUENCY_STR, int(exp_config.MODEL_SEED),
                                           int(exp_config.MIN_TRAIN_ROW_COUNT), True)
    return {**result_dict, "row_pdf": row_pdf}


# FUNCTION: PROBABILITY, THRESHOLD AND VOLATILITY ON EVERY SESSION (2.0 get_aligned_prediction_dict)
def get_aligned_prediction_dict(ohlcv_array_dict_in, retrain_dict_in, offset_float_in):
    """
    Full-length arrays, one value per session of the bars. Sessions without a model are NaN; a NaN never re-enters.

    Args:
        ohlcv_array_dict_in (dict): Bars
        retrain_dict_in (dict): Output of get_window_retrain_dict on the same bars
        offset_float_in (float): Added to the refit's training base rate

    Returns:
        dict: proba_arr, threshold_arr, volatility_arr, model_id_arr
    """
    # MAP EACH SESSION TO ITS PREDICTION AND MODEL
    prediction_pdf, refit_pdf = retrain_dict_in["prediction_pdf"], retrain_dict_in["refit_log_pdf"]
    balance_dict = {int(model_id): float(balance) for model_id, balance in zip(refit_pdf["model_id"], refit_pdf["label_balance"])}
    pred_dict = {pd.Timestamp(session_date).date(): (float(prediction), int(model_id))
                 for session_date, prediction, model_id in zip(prediction_pdf["session"], prediction_pdf["prediction"], prediction_pdf["model_id"])}
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    proba_arr, threshold_arr = np.full(session_count, np.nan), np.full(session_count, np.nan)
    model_id_arr = np.full(session_count, -1, dtype=int)
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        session_day = pd.Timestamp(session_date).date()
        if session_day not in pred_dict:
            continue
        proba_float, model_id = pred_dict[session_day]
        proba_arr[session_idx] = proba_float
        threshold_arr[session_idx] = balance_dict[model_id] + float(offset_float_in)
        model_id_arr[session_idx] = model_id
    # THE STOP VOLATILITY IS THE LABELLED ROW'S daily_volatility
    volatility_arr = retrain_dict_in["row_pdf"]["daily_volatility"].to_numpy(dtype=float)
    return {"proba_arr": proba_arr, "threshold_arr": threshold_arr, "volatility_arr": volatility_arr,
            "model_id_arr": model_id_arr}


# FUNCTION: THE 2.0 RE-ENTRY BOOLEAN PER SESSION
def get_reentry_bool_arr(proba_arr_in, threshold_arr_in):
    """
    P >= p*, both finite. The same rule as model.get_session_threshold_reentry_func.

    Args:
        proba_arr_in, threshold_arr_in (np.ndarray): Per session

    Returns:
        np.ndarray: bool per session
    """
    # A MISSING VALUE NEVER RE-ENTERS
    proba_arr = np.asarray(proba_arr_in, dtype=float)
    threshold_arr = np.asarray(threshold_arr_in, dtype=float)
    finite_arr = np.isfinite(proba_arr) & np.isfinite(threshold_arr)
    return finite_arr & (np.where(finite_arr, proba_arr, 0.0) >= np.where(finite_arr, threshold_arr, 1.0))
