import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
# IMPORT THE EXPERIMENT CONFIGURATION
from experiments.exp02_stop_reentry import config as exp_config

"""
Re-entry model of exp02 (the logistic regression of protocol 1.0, kept for version 2.0)

The model is P(the net 20-session forward return is positive). A weekly refit uses the same estimator. A window with
one class returns that class's rate: the fit is defined, and it is not a different training window. The diagnostic
LightGBM of protocol 1.0 never placed a trade; version 2.0 does not refit it.
"""

# FUNCTION: FIT THE RE-ENTRY MODEL
def fit_reentry_model_dict(train_pdf_in, feature_col_list_in, label_col_str_in, seed_int_in):
    """
    Logistic regression of the label on the feature columns, standardized, L2 with the protocol's C. One class returns
    that class's rate.

    Args:
        train_pdf_in (pd.DataFrame): Training rows
        feature_col_list_in (list[str]): Feature columns
        label_col_str_in (str): Label column
        seed_int_in (int): Seed (the logistic solver is deterministic; the seed is recorded)

    Returns:
        dict: kind "logistic" or "constant"
    """
    # COLLECT THE LABEL
    label_arr = train_pdf_in[label_col_str_in].to_numpy(dtype=int)
    # A ONE-CLASS WINDOW HAS A DEFINED PROBABILITY
    if len(np.unique(label_arr)) < 2:
        return {"kind": "constant", "probability": float(np.mean(label_arr))}
    # FIT THE SCALED LOGISTIC REGRESSION
    model = make_pipeline(StandardScaler(), LogisticRegression(C=float(exp_config.LOGISTIC_C), max_iter=2000, random_state=int(seed_int_in)))
    model.fit(train_pdf_in[list(feature_col_list_in)].to_numpy(dtype=float), label_arr)
    return {"kind": "logistic", "model": model}

# FUNCTION: PREDICT THE PROBABILITY OF THE POSITIVE CLASS
def predict_reentry_proba_arr(model_in, feature_pdf_in, feature_col_list_in):
    """
    One probability per feature row. A constant model repeats its rate.

    Args:
        model_in (dict): Output of fit_reentry_model_dict
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
    class_list = list(model_in["model"].named_steps["logisticregression"].classes_)
    class_idx = class_list.index(1) if 1 in class_list else None
    if class_idx is None:
        return np.zeros(len(feature_pdf_in))
    return proba_arr[:, class_idx]

# FUNCTION: RE-ENTER WHEN THE SESSION PROBABILITY CLEARS THAT SESSION'S THRESHOLD
def get_session_threshold_reentry_func(proba_arr_in, threshold_arr_in):
    """
    The protocol rule P >= p*, with p* allowed to change by session because each weekly refit has its own training
    base rate. A missing probability or threshold never re-enters. A constant threshold is the same rule as
    so.core.reentry_simulation.get_model_reentry_func.

    Args:
        proba_arr_in (np.ndarray): Probability per session position
        threshold_arr_in (np.ndarray): p* per session position

    Returns:
        function: Re-entry rule
    """
    # RETURN THE RULE
    def reentry_func(session_idx, cash_session_count, episode_dict):
        proba_float, threshold_float = proba_arr_in[session_idx], threshold_arr_in[session_idx]
        if not np.isfinite(proba_float) or not np.isfinite(threshold_float):
            return False
        return bool(proba_float >= threshold_float)
    return reentry_func

# FUNCTION: THE CANDIDATE NAME THE RUNNER STORES AS ONE FIELD
def get_candidate_name_str(train_window_str_in, stop_k_in, offset_float_in):
    """
    One string for one (window, k, offset) candidate.

    Args:
        train_window_str_in (str): "10Y" or "ALL"
        stop_k_in (float): Stop multiplier
        offset_float_in (float): Threshold offset

    Returns:
        str: Candidate name
    """
    # THE NAME IS STABLE ACROSS RUNS
    return f"{train_window_str_in}|{float(stop_k_in):.0f}|{float(offset_float_in):.2f}"

# FUNCTION: SPLIT A CANDIDATE NAME
def parse_candidate_dict(candidate_in):
    """
    The window, the stop multiplier and the offset of a candidate name.

    Args:
        candidate_in (str): Output of get_candidate_name_str

    Returns:
        dict: train_window, stop_k, threshold_offset
    """
    # SPLIT THE THREE FIELDS
    window_str, k_str, offset_str = str(candidate_in).split("|")
    return {"train_window": window_str, "stop_k": float(k_str), "threshold_offset": float(offset_str)}
