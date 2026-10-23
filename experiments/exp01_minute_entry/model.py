import numpy as np
import pandas as pd
import lightgbm as lgb
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp01_minute_entry import config as exp_config
# IMPORT THE TSBAR CELL PARSER, THE COLUMN NAME OF A DISTANCE AND THE EXPECTED NET RETURN
from so.features.barrier_labels import parse_TSBAR_cell_pdf, get_delta_col_str
from so.core.trade_execution import get_expected_net_return_arr

"""
Model of exp01: P(take profit first) per distance, uniqueness weights, and the expected-return entry policy

All functions work on rows the runner hands over. fit_delta_model_dict sees training rows (features, the TSBAR cells
of every distance, bar_idx); predict and the policy see one row at a time (row-local).
"""

# THE MODEL'S FEATURE COLUMNS (REGISTERED FEATURES OF THE ALLOWED SCALE TYPES, FROM THE THREE FEATURE SOURCES)
MODEL_FEATURE_COL_LIST = config.get_feature_col_str_list(exp_config.MODEL_FEATURE_SCALE_TYPE_LIST, exp_config.FEATURE_SOURCE_LIST)


# FUNCTION: MODEL INPUTS (FIXED CATEGORY LEVELS, FLOATS WITH INFINITIES AS NaN)
def encode_feature_pdf(row_pdf_in, feature_col_list_in=MODEL_FEATURE_COL_LIST):
    """
    Args:
        row_pdf_in (pd.DataFrame): Rows
        feature_col_list_in (list[str]): Feature columns

    Returns:
        pd.DataFrame: Encoded features (same index)
    """
    # CATEGORICAL FEATURES KEEP THE SAME CODES IN EVERY REFIT
    encoded_col_dict = {}
    for column_str in feature_col_list_in:
        if config.FEATURE_REGISTRY_DICT[column_str]["scale_type"] == "categorical":
            encoded_col_dict[column_str] = pd.Categorical(row_pdf_in[column_str], categories=config.CATEGORY_LEVEL_DICT[column_str])
        else:
            encoded_col_dict[column_str] = pd.to_numeric(row_pdf_in[column_str], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return pd.DataFrame(encoded_col_dict, index=row_pdf_in.index)


# FUNCTION: TAKE-PROFIT LABEL AND HOLDING LENGTH OF ONE DISTANCE
def get_delta_label_dict(train_pdf_in, delta_in):
    """
    Args:
        train_pdf_in (pd.DataFrame): Training rows with the TSBAR cell column of the distance
        delta_in (float): Distance

    Returns:
        dict: y_arr (1 TP, 0 SL or time limit, NaN unresolved), exit_bar_count_arr (-1 unresolved)
    """
    # THE STORED CELL IS "exit_bar_count|exit_price|exit_reason"
    cell_pdf = parse_TSBAR_cell_pdf(train_pdf_in[get_delta_col_str(delta_in)])
    resolved_arr = (cell_pdf.exit_reason != config.EXIT_REASON_NA).to_numpy()
    y_arr = np.where(resolved_arr, (cell_pdf.exit_reason == config.EXIT_REASON_TP).to_numpy().astype(float), np.nan)
    exit_bar_count_arr = np.where(resolved_arr, pd.to_numeric(cell_pdf.exit_bar_count, errors="coerce").fillna(-1).to_numpy(), -1).astype(int)
    return {"y_arr": y_arr, "exit_bar_count_arr": exit_bar_count_arr}


# FUNCTION: AVERAGE-UNIQUENESS SAMPLE WEIGHTS (LOPEZ DE PRADO)
def get_uniqueness_weight_arr(entry_idx_arr_in, exit_bar_count_arr_in):
    """
    For each resolved trade, the mean over its bars (entry .. exit) of 1 / the number of trades open on that bar.
    Normalized to a mean of 1. Unresolved trades are NaN.

    Args:
        entry_idx_arr_in (np.ndarray): Entry bar index of every row
        exit_bar_count_arr_in (np.ndarray): Bars from entry to exit (-1 unresolved)

    Returns:
        np.ndarray: Weights
    """
    # ONLY RESOLVED TRADES OVERLAP
    entry_idx_arr = np.asarray(entry_idx_arr_in, dtype=np.int64)
    count_arr = np.asarray(exit_bar_count_arr_in, dtype=np.int64)
    valid_arr = (count_arr >= 0) & (entry_idx_arr >= 0)
    weight_arr = np.full(len(entry_idx_arr), np.nan)
    if not valid_arr.any():
        return weight_arr
    start_arr = entry_idx_arr[valid_arr]
    end_arr = start_arr + count_arr[valid_arr]
    offset_int = int(start_arr.min())
    start_arr, end_arr = start_arr - offset_int, end_arr - offset_int
    concurrency_arr = np.zeros(int(end_arr.max()) + 2)
    np.add.at(concurrency_arr, start_arr, 1)
    np.add.at(concurrency_arr, end_arr + 1, -1)
    concurrency_arr = np.cumsum(concurrency_arr)[:-1]
    inverse_cumsum_arr = np.concatenate([[0.0], np.cumsum(np.where(concurrency_arr > 0, 1.0 / np.maximum(concurrency_arr, 1), 0.0))])
    uniqueness_arr = (inverse_cumsum_arr[end_arr + 1] - inverse_cumsum_arr[start_arr]) / (end_arr - start_arr + 1)
    weight_arr[valid_arr] = uniqueness_arr / uniqueness_arr.mean()
    return weight_arr


# FUNCTION: ONE CLASSIFIER PER DISTANCE
def fit_delta_model_dict(train_pdf_in):
    """
    Fewer than MIN_TRAIN_ROW_COUNT rows, or a distance with one class, gives no model for that distance.

    Args:
        train_pdf_in (pd.DataFrame): Training rows (features, TSBAR cells, bar_idx)

    Returns:
        dict: delta -> LGBMClassifier
    """
    # TOO FEW ROWS: NO MODEL, NO ENTRY
    model_dict = {}
    if len(train_pdf_in) < int(exp_config.MIN_TRAIN_ROW_COUNT):
        return model_dict
    feature_pdf = encode_feature_pdf(train_pdf_in)
    entry_idx_arr = train_pdf_in["bar_idx"].to_numpy(dtype=np.int64) + int(config.DECISION_TO_ENTRY_BAR_OFFSET)
    for delta in exp_config.MODEL_DELTA_LIST:
        if get_delta_col_str(delta) not in train_pdf_in.columns:
            continue
        label_dict = get_delta_label_dict(train_pdf_in, delta)
        weight_arr = get_uniqueness_weight_arr(entry_idx_arr, label_dict["exit_bar_count_arr"])
        fit_mask = np.isfinite(label_dict["y_arr"]) & np.isfinite(weight_arr)
        if int(fit_mask.sum()) < int(exp_config.MIN_TRAIN_ROW_COUNT) or len(np.unique(label_dict["y_arr"][fit_mask])) < 2:
            continue
        model = lgb.LGBMClassifier(**exp_config.LGBM_PARAM_DICT)
        model.fit(feature_pdf[fit_mask], label_dict["y_arr"][fit_mask].astype(int), sample_weight=weight_arr[fit_mask])
        model_dict[float(delta)] = model
    return model_dict


# FUNCTION: BEST DISTANCE AND ITS EXPECTED NET RETURN PER ROW
def get_policy_pdf(row_pdf_in, model_dict_in):
    """
    For every modelled distance: expected net return from P(take profit) and the row's decision-bar close (known at
    the decision). Each row takes its best distance.

    Args:
        row_pdf_in (pd.DataFrame): Rows (features and close)
        model_dict_in (dict): delta -> classifier

    Returns:
        pd.DataFrame: delta, expected_return (NaN when there is no model)
    """
    # NO MODEL: NO DISTANCE
    if not model_dict_in:
        return pd.DataFrame({"delta": np.full(len(row_pdf_in), np.nan), "expected_return": np.full(len(row_pdf_in), np.nan)})
    feature_pdf = encode_feature_pdf(row_pdf_in)
    close_arr = row_pdf_in["close"].to_numpy(dtype=float)
    delta_arr = np.asarray(sorted(model_dict_in), dtype=float)
    ev_mat = np.column_stack([get_expected_net_return_arr(model_dict_in[delta].predict_proba(feature_pdf)[:, 1], close_arr, float(delta), config.RR_RATIO)
                              for delta in delta_arr])
    best_idx_arr = np.argmax(np.where(np.isfinite(ev_mat), ev_mat, -np.inf), axis=1)
    return pd.DataFrame({"delta": delta_arr[best_idx_arr], "expected_return": ev_mat[np.arange(len(ev_mat)), best_idx_arr]})
