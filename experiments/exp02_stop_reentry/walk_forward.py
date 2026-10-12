import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from lightgbm import LGBMClassifier
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp02_stop_reentry import config as exp_config

"""
Model fit kept for exp08 until that folder is removed (PART 2).

exp08's gate imports these two functions. The version 2.0 decision path is experiments.exp02_stop_reentry.model and
design.py. These functions are the protocol 1.0 fit, so the gate's logistic regression does not change.
"""

# FUNCTION: FIT THE RE-ENTRY MODEL
def fit_reentry_model_dict(train_pdf_in, feature_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST, model_str_in=exp_config.PRIMARY_MODEL_STR):
    """
    Fits P(positive 20-session forward return) on the training rows.

    Args:
        train_pdf_in (pd.DataFrame): Training rows
        feature_col_str_list_in (list[str]): Model features
        model_str_in (str): "logistic" or "lgbm"

    Returns:
        dict: model, base_rate, row_count, model_str
    """
    # COLLECT THE TRAINING DATA
    x_pdf = train_pdf_in[list(feature_col_str_list_in)].astype(float)
    y_arr = train_pdf_in["y_fwd_positive"].to_numpy(dtype=int)
    # CREATE THE MODEL
    if model_str_in == "logistic":
        model = make_pipeline(StandardScaler(), LogisticRegression(C=exp_config.LOGISTIC_C, max_iter=2000))
    elif model_str_in == "lgbm":
        model = LGBMClassifier(**exp_config.LGBM_PARAM_DICT)
    else:
        raise ValueError(f"Unknown model '{model_str_in}'")
    # FIT THE MODEL
    model.fit(x_pdf, y_arr)
    # RETURN THE MODEL DICTIONARY
    return {"model": model, "base_rate": float(y_arr.mean()), "row_count": int(len(y_arr)), "model_str": model_str_in}

# FUNCTION: PREDICT THE RE-ENTRY PROBABILITY OF EVERY SESSION
def predict_reentry_proba_arr(model_dict_in, daily_pdf_in, feature_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST):
    """
    Predicts P(positive forward return) for every session (NaN where a feature is missing).

    Args:
        model_dict_in (dict): Output of fit_reentry_model_dict
        daily_pdf_in (pd.DataFrame): Daily features
        feature_col_str_list_in (list[str]): Model features

    Returns:
        np.ndarray: Probability per session position
    """
    # COLLECT THE FEATURES
    x_pdf = daily_pdf_in[list(feature_col_str_list_in)].astype(float)
    complete_mask = x_pdf.notna().all(axis=1).to_numpy()
    # PREDICT THE COMPLETE ROWS
    proba_arr = np.full(len(x_pdf), np.nan)
    if complete_mask.any():
        proba_arr[complete_mask] = model_dict_in["model"].predict_proba(x_pdf[complete_mask])[:, 1]
    # RETURN THE PROBABILITIES
    return proba_arr
