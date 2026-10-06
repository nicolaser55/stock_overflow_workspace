import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp01_minute_entry import config as exp_config
# IMPORT BARRIER LABEL FUNCTIONS
from so.features.barrier_labels import get_delta_col_str
# IMPORT TRADE EXECUTION FUNCTIONS
from so.core.trade_execution import get_breakeven_tp_rate_arr
# IMPORT THE SIGNAL CHECK BUILDING BLOCKS
from so.core.signal_bins import get_block_id_arr
# IMPORT THE EXPERIMENT FUNCTIONS (UNCHANGED: SAME DATASET, SAME MODEL, SAME NULL SHIFT AS STEPS 02-03)
from experiments.exp01_minute_entry.model_dataset import read_model_dataset_pdf
from experiments.exp01_minute_entry.walk_forward import get_fold_pdf, fit_tp_model_dict, predict_tp_proba_pdf
from experiments.exp01_minute_entry.signal_check import get_session_shifted_feature_pdf

"""
Multivariate Signal Check: exp01 step 04 (diagnostic, PROTOCOL.md §13.3; protocol 1.1, decided by Nicolas 2026-10-06)

exp01 is STOPPED (step 02 verdict, p = 0.10). This step was added AFTER exp01's results were known: it can explain the
failure, it cannot reverse the STOP or restart the walk-forward.

Question: does the COMBINATION of the 33 model features, through exp01's own LightGBM classifiers (one per distance, fit
on training only), rank the pooled validation rows by "take profit first" better than chance and the model's flexibility
produce? And, if so, is the top decile's TP rate above its break-even rate after costs?

    1. Windows and rows exactly as step 02 (training = the 10-year window of the first pooled fold, validation = the 4 most
       recent validation quarters pooled, 15-minute sampling, duplicates of adjacent quarters dropped), sorted by decision time.
    2. Real check: fit_tp_model_dict / predict_tp_proba_pdf of walk_forward.py (unchanged), then per distance on the
       resolved validation rows: AUC, top-decile TP rate and lift over the base rate, the top decile's mean break-even
       rate, with block-bootstrap intervals of whole ISO weeks (the same resampling as so.core.signal_bins).
    3. Null: the feature columns of each window shifted together by whole sessions (get_session_shifted_feature_pdf of
       step 02, 25%-75% of the window), the models RETRAINED, the same measures computed; 19 runs with seeds (RANDOM_SEED, run).
    4. Verdict: INFORMATION only if the real mean AUC over the distances is above EVERY null run (ties: no information);
       p = (1 + null runs >= real) / (1 + runs). Outcome A (no information), B (information, no distance's top-decile
       lower bound above break-even), C (information, at least one distance above break-even: candidate pending review).

LightGBM runs with a fixed number of threads per model (MULTIVARIATE_CHECK_LGBM_THREAD_COUNT) for the real and the null
models, so the numbers do not depend on how many null runs run in parallel (tested).
"""

"""
Windows And Rows
"""

# FUNCTION: GET THE SCHEDULE AND THE POOLED VALIDATION FOLDS
def get_schedule_tuple(session_date_list_in, train_years_in=None, max_fold_count_in=None):
    """
    Builds exp01's fold schedule with the signal-check training window and selects the pooled validation folds (step 02).

    Args:
        session_date_list_in (list[datetime.date]): Session dates of the model dataset files
        train_years_in (int | None): Training window length in years (None = SIGNAL_CHECK_TRAIN_WINDOW_YEARS)
        max_fold_count_in (int | None): Keep only the most recent folds (None = all)

    Returns:
        tuple: (fold_pdf, pooled_fold_pdf) with the SIGNAL_CHECK_POOLED_QUARTER_COUNT most recent folds
    """
    # DEFINE THE TRAINING WINDOW LENGTH
    train_years = train_years_in if train_years_in is not None else exp_config.SIGNAL_CHECK_TRAIN_WINDOW_YEARS
    # CALL FUNCTION TO GET THE FOLDS
    fold_pdf = get_fold_pdf(session_date_list_in, max_fold_count_in, train_window_years_list_in=[train_years])
    # RETURN THE FOLDS AND THE POOLED FOLDS
    return fold_pdf, fold_pdf.iloc[-exp_config.SIGNAL_CHECK_POOLED_QUARTER_COUNT:]

# FUNCTION: GET THE TRAINING AND VALIDATION WINDOWS OF THE CHECK
def get_check_window_dict(pooled_fold_pdf_in):
    """
    Collects the training window (of the first pooled fold) and the pooled validation window.

    Args:
        pooled_fold_pdf_in (pd.DataFrame): Pooled folds (output of get_schedule_tuple)

    Returns:
        dict: train_years, train_start, train_end, valid_start, valid_end, valid_fold_id_list
    """
    # COLLECT THE FIRST POOLED FOLD
    first_fold_row = pooled_fold_pdf_in.iloc[0]
    # COLLECT THE TRAINING WINDOW LENGTH FROM THE COLUMN NAME
    train_start_col_str = [col for col in pooled_fold_pdf_in.columns if col.startswith("train_start_") and col.endswith("y")][0]
    # RETURN THE WINDOWS
    return {"train_years": int(train_start_col_str.replace("train_start_", "").replace("y", "")),
            "train_start": first_fold_row[train_start_col_str], "train_end": first_fold_row["train_end"],
            "valid_start": pooled_fold_pdf_in["valid_start"].min(), "valid_end": pooled_fold_pdf_in["valid_end"].max(),
            "valid_fold_id_list": [int(fold_id) for fold_id in pooled_fold_pdf_in["fold_id"]]}

# FUNCTION: READ THE TRAINING AND POOLED VALIDATION ROWS
def read_check_window_pdf_tuple(window_dict_in, pooled_fold_pdf_in, delta_list_in=exp_config.SIGNAL_CHECK_DELTA_LIST, alert_in=True):
    """
    Reads the rows of the check as step 02 does (same sampling, adjacent quarters' duplicates dropped), sorted by decision time.

    Args:
        window_dict_in (dict): Output of get_check_window_dict
        pooled_fold_pdf_in (pd.DataFrame): Pooled folds
        delta_list_in (list[float]): Distances whose labels are parsed
        alert_in (bool): Display progress

    Returns:
        tuple: (train_pdf, valid_pdf)
    """
    # CALL FUNCTION TO READ THE TRAINING ROWS (SAMPLED AS FOR TRAINING)
    train_pdf = read_model_dataset_pdf(str(window_dict_in["train_start"]), str(window_dict_in["train_end"]), delta_list_in,
                                       exp_config.SAMPLING_MODE, exp_config.SAMPLE_EVERY_N_MINUTES, alert_in=alert_in)
    # CALL FUNCTION TO READ THE POOLED VALIDATION ROWS (SAME SAMPLING, DUPLICATES DROPPED)
    valid_pdf = pd.concat([read_model_dataset_pdf(str(row["valid_start"]), str(row["valid_end"]), delta_list_in, exp_config.SAMPLING_MODE,
                                                  exp_config.SAMPLE_EVERY_N_MINUTES, alert_in=False) for _, row in pooled_fold_pdf_in.iterrows()],
                          ignore_index=True).drop_duplicates(subset=["decision_ts"])
    # RETURN THE ROWS SORTED BY DECISION TIME (THE ORDER THE NULL SHIFT USES)
    return train_pdf.sort_values("decision_ts").reset_index(drop=True), valid_pdf.sort_values("decision_ts").reset_index(drop=True)

# FUNCTION: CHECK THAT NO ROW IS DATED AFTER THE LAST VALIDATION DATE
def check_last_date_bool(date_series_list_in, last_date_in, untouched_start_date_str_in=exp_config.MULTIVARIATE_CHECK_UNTOUCHED_START_DATE_STR):
    """
    Raises if any decision (or bar) date is after the last validation date or on or after the untouched start.

    Args:
        date_series_list_in (list[pd.Series]): Timestamps or dates of every table used (decision_ts of the rows, bar timestamps)
        last_date_in (datetime.date | str): Last validation date
        untouched_start_date_str_in (str): First date of the untouched window

    Returns:
        bool: True if every date is allowed
    """
    # CONVERT THE LIMITS
    last_date_object, untouched_date_object = pd.to_datetime(last_date_in).date(), pd.to_datetime(untouched_start_date_str_in).date()
    # IF THE LAST VALIDATION DATE ITSELF REACHES THE UNTOUCHED WINDOW
    if last_date_object >= untouched_date_object:
        raise ValueError(f"The last validation date {last_date_object} reaches the untouched window ({untouched_date_object})")
    # ITERATE OVER THE TABLES
    for date_series in date_series_list_in:
        # IF THE TABLE IS EMPTY
        if len(date_series) == 0:
            continue
        # COLLECT THE LATEST DATE (TIMESTAMPS ARE READ IN THEIR OWN TIMEZONE)
        value_series = pd.Series(date_series)
        max_date_object = value_series.dt.date.max() if pd.api.types.is_datetime64_any_dtype(value_series) else pd.to_datetime(value_series).dt.date.max()
        # IF A DATE IS AFTER THE LAST VALIDATION DATE
        if max_date_object > last_date_object or max_date_object >= untouched_date_object:
            raise ValueError(f"A row is dated {max_date_object}, after the last validation date {last_date_object}")
    # RETURN TRUE
    return True

"""
Model And Measures
"""

# FUNCTION: GET THE LIGHTGBM PARAMETERS OF THE CHECK
def get_check_lgbm_param_dict(thread_count_in=exp_config.MULTIVARIATE_CHECK_LGBM_THREAD_COUNT):
    """
    Returns exp01's LightGBM parameters with a fixed number of threads (a computational setting, not a model parameter).

    Args:
        thread_count_in (int): Threads per model

    Returns:
        dict: exp_config.LGBM_PARAM_DICT plus n_jobs
    """
    # RETURN THE PARAMETERS
    return {**exp_config.LGBM_PARAM_DICT, "n_jobs": int(thread_count_in)}

# FUNCTION: DRAW THE BOOTSTRAP BLOCK WEIGHTS
def get_block_weight_mat(block_count_in, iteration_count_in, seed_in):
    """
    Draws how many times each block is resampled in every bootstrap iteration (same draws as so.core.signal_bins).

    Args:
        block_count_in (int): Number of blocks
        iteration_count_in (int): Bootstrap iterations
        seed_in (int): Random seed

    Returns:
        np.ndarray: Weights (iterations x blocks)
    """
    # CREATE THE RANDOM GENERATOR
    rng = np.random.default_rng(seed_in)
    # COUNT THE DRAWS OF EVERY BLOCK
    weight_mat = np.zeros((iteration_count_in, block_count_in))
    np.add.at(weight_mat, (np.repeat(np.arange(iteration_count_in), block_count_in), rng.integers(0, block_count_in, size=iteration_count_in * block_count_in)), 1)
    # RETURN THE WEIGHTS
    return weight_mat

# FUNCTION: CALCULATE BLOCK-WEIGHTED AUCS
def get_weighted_auc_arr(y_arr_in, score_arr_in, block_id_arr_in, weight_mat_in, chunk_size_in=200):
    """
    Calculates the AUC (probability that a TP row scores above a non-TP row, ties count one half) for every row of block
    weights: each row's weight is the weight of its block (weights of 1 give the plain AUC).

    Args:
        y_arr_in (np.ndarray): 1 for TP, 0 otherwise
        score_arr_in (np.ndarray): Predicted P(TP)
        block_id_arr_in (np.ndarray): Block id per row (0 .. blocks - 1)
        weight_mat_in (np.ndarray): Block weights (iterations x blocks)
        chunk_size_in (int): Iterations computed at once (memory)

    Returns:
        np.ndarray: One AUC per weight row
    """
    # GROUP THE ROWS BY SCORE (ASCENDING; EQUAL SCORES ARE TIES)
    group_idx_arr = np.unique(score_arr_in, return_inverse=True)[1]
    group_count = int(group_idx_arr.max()) + 1
    block_count = weight_mat_in.shape[1]
    # COUNT THE TP AND NON-TP ROWS PER BLOCK AND SCORE GROUP
    pos_mat, neg_mat = np.zeros((block_count, group_count)), np.zeros((block_count, group_count))
    np.add.at(pos_mat, (block_id_arr_in, group_idx_arr), y_arr_in)
    np.add.at(neg_mat, (block_id_arr_in, group_idx_arr), 1 - y_arr_in)
    # LIST TO HOLD THE AUCS
    auc_list = []
    # ITERATE OVER THE CHUNKS OF ITERATIONS
    for start_idx in range(0, weight_mat_in.shape[0], chunk_size_in):
        # WEIGHT THE COUNTS
        weight_chunk_mat = weight_mat_in[start_idx:start_idx + chunk_size_in]
        boot_pos_mat, boot_neg_mat = weight_chunk_mat @ pos_mat, weight_chunk_mat @ neg_mat
        # NON-TP WEIGHT BELOW EACH SCORE GROUP
        neg_below_mat = np.cumsum(boot_neg_mat, axis=1) - boot_neg_mat
        # CALCULATE THE AUCS
        with np.errstate(invalid="ignore", divide="ignore"):
            auc_list.append((boot_pos_mat * (neg_below_mat + 0.5 * boot_neg_mat)).sum(axis=1) / (boot_pos_mat.sum(axis=1) * boot_neg_mat.sum(axis=1)))
    # RETURN THE AUCS
    return np.concatenate(auc_list) if auc_list else np.array([])

# FUNCTION: GET THE TOP-SHARE MASK OF THE PREDICTIONS
def get_top_mask_arr(score_arr_in, top_share_in=exp_config.MULTIVARIATE_CHECK_TOP_SHARE):
    """
    Flags the rows with the highest predicted P(TP) (ties broken by row order, so the selection is deterministic).

    Args:
        score_arr_in (np.ndarray): Predicted P(TP)
        top_share_in (float): Share of rows flagged

    Returns:
        np.ndarray: Boolean mask
    """
    # DEFINE THE NUMBER OF TOP ROWS (AT LEAST ONE)
    top_count = max(1, int(round(top_share_in * len(score_arr_in))))
    # FLAG THE HIGHEST SCORES
    mask_arr = np.zeros(len(score_arr_in), dtype=bool)
    mask_arr[np.argsort(-np.asarray(score_arr_in, dtype=float), kind="mergesort")[:top_count]] = True
    # RETURN THE MASK
    return mask_arr

# FUNCTION: GET THE MEASURES OF ONE DISTANCE
def get_distance_metric_dict(valid_pdf_in, score_series_in, delta_float_in, top_share_in=exp_config.MULTIVARIATE_CHECK_TOP_SHARE,
                             iteration_count_in=config.BOOTSTRAP_ITERATION_COUNT, confidence_level_in=config.CONFIDENCE_LEVEL,
                             seed_in=config.RANDOM_SEED, block_str_in=exp_config.SIGNAL_CHECK_BOOTSTRAP_BLOCK_STR):
    """
    Measures the predictions of one distance on the resolved validation rows: AUC, top-share TP rate and lift over the
    base rate, the top share's mean break-even rate, with block-bootstrap intervals (iteration_count_in = 0: no intervals).

    Args:
        valid_pdf_in (pd.DataFrame): Validation rows (decision_ts, entry_price, y_tp_<d>)
        score_series_in (pd.Series): Predicted P(TP) of the distance (same index)
        delta_float_in (float): Distance
        top_share_in (float): Share of rows in the top group
        iteration_count_in (int): Bootstrap iterations
        confidence_level_in (float): Two-sided confidence level
        seed_in (int): Bootstrap seed
        block_str_in (str): Bootstrap block ("week" or "day")

    Returns:
        dict: delta, row_count, base_rate, auc, auc_ci_low, auc_ci_high, top_row_count, top_tp_rate, top_tp_rate_ci_low,
              top_tp_rate_ci_high, top_lift, top_lift_ci_low, top_lift_ci_high, top_breakeven_tp_rate, clears_breakeven
    """
    # KEEP THE RESOLVED ROWS
    y_col_str = f"y_tp_{get_delta_col_str(delta_float_in)}"
    resolved_mask = valid_pdf_in[y_col_str].notna().to_numpy() & score_series_in.notna().to_numpy()
    resolved_pdf = valid_pdf_in[resolved_mask]
    y_arr = resolved_pdf[y_col_str].to_numpy(dtype=float)
    score_arr = score_series_in.to_numpy(dtype=float)[resolved_mask]
    # FLAG THE TOP ROWS AND COLLECT THEIR BREAK-EVEN RATE
    top_mask_arr = get_top_mask_arr(score_arr, top_share_in)
    breakeven_arr = get_breakeven_tp_rate_arr(resolved_pdf["entry_price"].to_numpy(dtype=float), delta_float_in)
    # DEFINE THE POINT ESTIMATES
    base_rate, top_tp_rate = float(y_arr.mean()), float(y_arr[top_mask_arr].mean())
    metric_dict = {"delta": delta_float_in, "row_count": int(len(y_arr)), "base_rate": base_rate,
                   "auc": float(get_weighted_auc_arr(y_arr, score_arr, np.zeros(len(y_arr), dtype=int), np.ones((1, 1)))[0]),
                   "top_row_count": int(top_mask_arr.sum()), "top_tp_rate": top_tp_rate, "top_lift": top_tp_rate - base_rate,
                   "top_breakeven_tp_rate": float(breakeven_arr[top_mask_arr].mean())}
    # IF NO INTERVAL IS REQUESTED
    if iteration_count_in <= 0:
        # RETURN THE POINT ESTIMATES WITH EMPTY INTERVALS
        return {**metric_dict, **{key: np.nan for key in ["auc_ci_low", "auc_ci_high", "top_tp_rate_ci_low", "top_tp_rate_ci_high", "top_lift_ci_low",
                                                          "top_lift_ci_high"]}, "clears_breakeven": False}
    # COLLECT THE BLOCKS AND DRAW THE BLOCK WEIGHTS
    block_id_arr = get_block_id_arr(resolved_pdf["decision_ts"], block_str_in)
    weight_mat = get_block_weight_mat(int(block_id_arr.max()) + 1, iteration_count_in, seed_in)
    # SUM THE TP COUNTS AND THE ROWS PER BLOCK (ALL ROWS AND TOP ROWS)
    block_count = weight_mat.shape[1]
    all_tp_arr, all_row_arr = np.bincount(block_id_arr, weights=y_arr, minlength=block_count), np.bincount(block_id_arr, minlength=block_count).astype(float)
    top_tp_arr = np.bincount(block_id_arr[top_mask_arr], weights=y_arr[top_mask_arr], minlength=block_count)
    top_row_arr = np.bincount(block_id_arr[top_mask_arr], minlength=block_count).astype(float)
    # CALCULATE THE BOOTSTRAPPED STATISTICS
    with np.errstate(invalid="ignore", divide="ignore"):
        boot_top_rate_arr = (weight_mat @ top_tp_arr) / (weight_mat @ top_row_arr)
        boot_lift_arr = boot_top_rate_arr - (weight_mat @ all_tp_arr) / (weight_mat @ all_row_arr)
    boot_auc_arr = get_weighted_auc_arr(y_arr, score_arr, block_id_arr, weight_mat)
    # DEFINE THE PERCENTILES
    low_pct, high_pct = 100 * (1 - confidence_level_in) / 2, 100 * (1 + confidence_level_in) / 2
    # ADD THE INTERVALS
    metric_dict.update({"auc_ci_low": float(np.nanpercentile(boot_auc_arr, low_pct)), "auc_ci_high": float(np.nanpercentile(boot_auc_arr, high_pct)),
                        "top_tp_rate_ci_low": float(np.nanpercentile(boot_top_rate_arr, low_pct)), "top_tp_rate_ci_high": float(np.nanpercentile(boot_top_rate_arr, high_pct)),
                        "top_lift_ci_low": float(np.nanpercentile(boot_lift_arr, low_pct)), "top_lift_ci_high": float(np.nanpercentile(boot_lift_arr, high_pct))})
    # FLAG A TOP GROUP WHOSE LOWER BOUND IS ABOVE ITS MEAN BREAK-EVEN RATE (TRADABLE AFTER COSTS)
    metric_dict["clears_breakeven"] = bool(metric_dict["top_tp_rate_ci_low"] > metric_dict["top_breakeven_tp_rate"])
    # RETURN THE MEASURES
    return metric_dict

# FUNCTION: GET THE MEASURES OF EVERY DISTANCE
def get_distance_metric_pdf(valid_pdf_in, proba_pdf_in, delta_list_in=exp_config.SIGNAL_CHECK_DELTA_LIST, **metric_kwargs):
    """
    Measures the predictions of every modelled distance.

    Args:
        valid_pdf_in (pd.DataFrame): Validation rows
        proba_pdf_in (pd.DataFrame): Output of predict_tp_proba_pdf (same index)
        delta_list_in (list[float]): Distances
        **metric_kwargs: Overrides for get_distance_metric_dict (iteration_count_in, top_share_in, ...)

    Returns:
        pd.DataFrame: One row per distance (output of get_distance_metric_dict)
    """
    # RETURN THE MEASURES OF THE DISTANCES THAT HAVE A MODEL
    return pd.DataFrame([get_distance_metric_dict(valid_pdf_in, proba_pdf_in[f"p_tp_{get_delta_col_str(delta)}"], delta, **metric_kwargs)
                         for delta in delta_list_in if f"p_tp_{get_delta_col_str(delta)}" in proba_pdf_in.columns])

# FUNCTION: FIT THE MODELS AND MEASURE THEIR VALIDATION PREDICTIONS
def run_model_check_dict(train_pdf_in, valid_pdf_in, feature_col_str_list_in, ohlcv_array_dict_in, delta_list_in=exp_config.SIGNAL_CHECK_DELTA_LIST,
                         sample_weight_mode_str_in=exp_config.SAMPLE_WEIGHT_MODE, lgbm_param_dict_in=None, **metric_kwargs):
    """
    Fits exp01's models on the training rows (fit_tp_model_dict, unchanged), predicts the validation rows and measures them.

    Args:
        train_pdf_in, valid_pdf_in (pd.DataFrame): Training and pooled validation rows
        feature_col_str_list_in (list[str]): Feature columns
        ohlcv_array_dict_in (dict | None): Output of trade_execution.get_ohlcv_array_dict (uniqueness weights; None if not weighted)
        delta_list_in (list[float]): Distances
        sample_weight_mode_str_in (str): "uniqueness" (exp01) or "none" (unit tests)
        lgbm_param_dict_in (dict | None): LightGBM parameters (None = get_check_lgbm_param_dict())
        **metric_kwargs: Overrides for get_distance_metric_dict

    Returns:
        dict: model_dict, proba_pdf, metric_pdf, mean_auc
    """
    # CALL FUNCTION TO FIT THE MODELS ON TRAINING ONLY
    model_dict = fit_tp_model_dict(train_pdf_in, feature_col_str_list_in, ohlcv_array_dict_in, delta_list_in, sample_weight_mode_str_in,
                                   lgbm_param_dict_in if lgbm_param_dict_in is not None else get_check_lgbm_param_dict())
    # CALL FUNCTION TO PREDICT THE VALIDATION ROWS
    proba_pdf = predict_tp_proba_pdf(model_dict, valid_pdf_in, feature_col_str_list_in)
    # CALL FUNCTION TO MEASURE THE PREDICTIONS
    metric_pdf = get_distance_metric_pdf(valid_pdf_in, proba_pdf, delta_list_in, **metric_kwargs)
    # RETURN THE RESULTS
    return {"model_dict": model_dict, "proba_pdf": proba_pdf, "metric_pdf": metric_pdf, "mean_auc": float(metric_pdf["auc"].mean())}

"""
Null Calibration And Verdict
"""

# FUNCTION: RUN ONE NULL CHECK
def get_null_run_dict(train_pdf_in, valid_pdf_in, feature_col_str_list_in, ohlcv_array_dict_in, delta_list_in, run_id_in,
                      seed_in=config.RANDOM_SEED, sample_weight_mode_str_in=exp_config.SAMPLE_WEIGHT_MODE, lgbm_param_dict_in=None, **metric_kwargs):
    """
    Shifts the features of each window by whole sessions (independently, as step 02), retrains the models and measures them.

    Args:
        train_pdf_in, valid_pdf_in (pd.DataFrame): Training and pooled validation rows
        feature_col_str_list_in (list[str]): Feature columns
        ohlcv_array_dict_in (dict | None): Bars for the uniqueness weights
        delta_list_in (list[float]): Distances
        run_id_in (int): Null run number (with seed_in, defines the shifts)
        seed_in (int): Base random seed
        sample_weight_mode_str_in (str): Sample weight mode
        lgbm_param_dict_in (dict | None): LightGBM parameters (None = get_check_lgbm_param_dict())
        **metric_kwargs: Overrides for get_distance_metric_dict

    Returns:
        dict: summary_dict (run_id, shifts, mean_auc, mean_top_lift) and metric_pdf (per distance, with run_id)
    """
    # CREATE THE RANDOM GENERATOR OF THE RUN (SAME SEEDING AS STEP 02)
    rng = np.random.default_rng([seed_in, run_id_in])
    # SHIFT THE FEATURES OF EACH WINDOW
    train_pdf = get_session_shifted_feature_pdf(train_pdf_in, feature_col_str_list_in, rng)
    valid_pdf = get_session_shifted_feature_pdf(valid_pdf_in, feature_col_str_list_in, rng)
    # RETRAIN AND MEASURE WITHOUT INTERVALS
    check_dict = run_model_check_dict(train_pdf, valid_pdf, feature_col_str_list_in, ohlcv_array_dict_in, delta_list_in, sample_weight_mode_str_in,
                                      lgbm_param_dict_in, **{**metric_kwargs, "iteration_count_in": 0})
    # RETURN THE SUMMARY AND THE PER-DISTANCE MEASURES
    return {"summary_dict": {"run_id": int(run_id_in), "train_shift_session_count": train_pdf.attrs.get("null_shift_session_count"),
                             "valid_shift_session_count": valid_pdf.attrs.get("null_shift_session_count"), "mean_auc": check_dict["mean_auc"],
                             "mean_top_lift": float(check_dict["metric_pdf"]["top_lift"].mean())},
            "metric_pdf": check_dict["metric_pdf"].assign(run_id=int(run_id_in))}

# FUNCTION: RUN THE NULL CHECKS
def get_null_run_pdf_tuple(train_pdf_in, valid_pdf_in, feature_col_str_list_in, ohlcv_array_dict_in, delta_list_in=exp_config.SIGNAL_CHECK_DELTA_LIST,
                           run_count_in=exp_config.SIGNAL_CHECK_NULL_RUN_COUNT, job_count_in=-1, seed_in=config.RANDOM_SEED, **run_kwargs):
    """
    Runs the null checks in parallel processes (joblib); the results do not depend on job_count_in (fixed LightGBM threads).

    Args:
        train_pdf_in, valid_pdf_in (pd.DataFrame): Training and pooled validation rows
        feature_col_str_list_in (list[str]): Feature columns
        ohlcv_array_dict_in (dict | None): Bars for the uniqueness weights
        delta_list_in (list[float]): Distances
        run_count_in (int): Number of null runs
        job_count_in (int): Parallel processes (-1 = all cores, 1 = sequential)
        seed_in (int): Base random seed
        **run_kwargs: Overrides for get_null_run_dict (sample_weight_mode_str_in, lgbm_param_dict_in, metric overrides)

    Returns:
        tuple: (null_summary_pdf with one row per run, null_metric_pdf with one row per run and distance)
    """
    # IMPORT JOBLIB
    from joblib import Parallel, delayed
    # RUN THE NULL CHECKS
    run_dict_list = Parallel(n_jobs=job_count_in)(delayed(get_null_run_dict)(train_pdf_in, valid_pdf_in, feature_col_str_list_in, ohlcv_array_dict_in,
                                                                             delta_list_in, run_id, seed_in, **run_kwargs) for run_id in range(run_count_in))
    # RETURN THE RUNS
    return pd.DataFrame([run_dict["summary_dict"] for run_dict in run_dict_list]), pd.concat([run_dict["metric_pdf"] for run_dict in run_dict_list], ignore_index=True)

# FUNCTION: GET THE VERDICT OF THE MULTIVARIATE CHECK
def get_multivariate_verdict_dict(metric_pdf_in, null_summary_pdf_in):
    """
    Applies the pre-registered verdict: INFORMATION only if the real mean AUC is above every null run (ties: no
    information); outcome A (no information), B (information, not tradable), C (information, possibly tradable).

    Args:
        metric_pdf_in (pd.DataFrame): Per-distance measures of the real models (with intervals)
        null_summary_pdf_in (pd.DataFrame): Output of get_null_run_pdf_tuple (first element)

    Returns:
        dict: real_mean_auc, null_run_count, null_mean_auc_list, null_max_mean_auc, null_p_value, information,
              clears_breakeven_delta_list, outcome, outcome_str
    """
    # COLLECT THE REAL STATISTIC AND THE NULL VALUES (IN RUN ORDER)
    real_mean_auc = float(metric_pdf_in["auc"].mean())
    null_arr = null_summary_pdf_in.sort_values("run_id")["mean_auc"].to_numpy(dtype=float)
    # CALCULATE THE EMPIRICAL P-VALUE AND THE INFORMATION FLAG (ABOVE EVERY RUN)
    null_p_value = float((1 + (null_arr >= real_mean_auc).sum()) / (1 + len(null_arr)))
    information_bool = bool(len(null_arr) > 0 and real_mean_auc > null_arr.max())
    # COLLECT THE DISTANCES WHOSE TOP GROUP CLEARS BREAK-EVEN
    clears_delta_list = [float(delta) for delta in metric_pdf_in.loc[metric_pdf_in["clears_breakeven"].astype(bool), "delta"]]
    # DEFINE THE OUTCOME
    outcome_str = "A" if not information_bool else ("C" if clears_delta_list else "B")
    outcome_text_dict = {"A": "no information", "B": "information, not tradable", "C": "information, possibly tradable (candidate pending review)"}
    # RETURN THE VERDICT
    return {"real_mean_auc": real_mean_auc, "null_run_count": int(len(null_arr)), "null_mean_auc_list": [float(value) for value in null_arr],
            "null_max_mean_auc": float(null_arr.max()) if len(null_arr) else None, "null_p_value": null_p_value, "information": information_bool,
            "clears_breakeven_delta_list": clears_delta_list, "outcome": outcome_str, "outcome_str": outcome_text_dict[outcome_str]}

"""
Descriptive Tables
"""

# FUNCTION: GET THE CALIBRATION TABLE
def get_calibration_pdf(valid_pdf_in, proba_pdf_in, delta_list_in=exp_config.SIGNAL_CHECK_DELTA_LIST,
                        bin_count_in=exp_config.MULTIVARIATE_CHECK_CALIBRATION_BIN_COUNT):
    """
    Compares the mean predicted P(TP) with the observed TP rate by decile of predicted P(TP) (deciles per distance, on
    the resolved validation rows, then pooled over the distances).

    Args:
        valid_pdf_in (pd.DataFrame): Validation rows
        proba_pdf_in (pd.DataFrame): Output of predict_tp_proba_pdf (same index)
        delta_list_in (list[float]): Distances
        bin_count_in (int): Number of bins

    Returns:
        pd.DataFrame: decile (1 = lowest predictions), row_count, mean_predicted, observed_tp_rate, gap
    """
    # LIST TO HOLD THE ROWS OF EVERY DISTANCE
    row_pdf_list = []
    # ITERATE OVER THE DISTANCES THAT HAVE A MODEL
    for delta in delta_list_in:
        # DEFINE THE COLUMNS
        delta_col_str = get_delta_col_str(delta)
        if f"p_tp_{delta_col_str}" not in proba_pdf_in.columns:
            continue
        # KEEP THE RESOLVED ROWS
        resolved_mask = valid_pdf_in[f"y_tp_{delta_col_str}"].notna()
        score_series = proba_pdf_in.loc[resolved_mask, f"p_tp_{delta_col_str}"]
        # ASSIGN THE DECILES BY RANK (TIES BY ROW ORDER)
        decile_arr = pd.qcut(score_series.rank(method="first"), bin_count_in, labels=False) + 1
        row_pdf_list.append(pd.DataFrame({"decile": decile_arr.to_numpy(), "predicted": score_series.to_numpy(),
                                          "observed": valid_pdf_in.loc[resolved_mask, f"y_tp_{delta_col_str}"].to_numpy(dtype=float)}))
    # POOL THE DISTANCES AND SUMMARIZE PER DECILE
    calibration_pdf = pd.concat(row_pdf_list, ignore_index=True).groupby("decile").agg(row_count=("observed", "size"), mean_predicted=("predicted", "mean"),
                                                                                      observed_tp_rate=("observed", "mean")).reset_index()
    calibration_pdf["gap"] = calibration_pdf["observed_tp_rate"] - calibration_pdf["mean_predicted"]
    # RETURN THE TABLE
    return calibration_pdf

# FUNCTION: GET THE SPLIT-GAIN FEATURE IMPORTANCE OF THE MODELS
def get_feature_importance_pdf(model_dict_in, feature_col_str_list_in):
    """
    Averages LightGBM's split-gain importance over the distance models (descriptive: says what the models used, not
    whether it carries information).

    Args:
        model_dict_in (dict): Output of fit_tp_model_dict
        feature_col_str_list_in (list[str]): Feature columns (model input order)

    Returns:
        pd.DataFrame: feature, mean_gain_share (share of each model's total gain, averaged), mean_gain, sorted descending
    """
    # COLLECT THE GAINS OF EVERY MODEL (FEATURES x MODELS)
    gain_mat = np.column_stack([model.booster_.feature_importance(importance_type="gain") for model in model_dict_in.values()])
    # RETURN THE AVERAGED IMPORTANCE
    return pd.DataFrame({"feature": feature_col_str_list_in, "mean_gain_share": (gain_mat / gain_mat.sum(axis=0, keepdims=True)).mean(axis=1),
                         "mean_gain": gain_mat.mean(axis=1)}).sort_values("mean_gain_share", ascending=False).reset_index(drop=True)
