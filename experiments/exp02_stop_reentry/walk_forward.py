import pandas as pd
import numpy as np
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, log_loss
from lightgbm import LGBMClassifier
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp02_stop_reentry import config as exp_config
# IMPORT THE WALK-FORWARD SCHEDULE
from so.core.schedule import get_walk_forward_fold_pdf
# IMPORT THE EVALUATION FUNCTIONS (POOLED SELECTION)
from so.core.evaluation import get_pooled_selection_pdf as get_generic_pooled_selection_pdf
# IMPORT DAILY FEATURE FUNCTIONS
from so.features.daily_features import get_daily_train_pdf
# IMPORT EXIT AND RE-ENTRY SIMULATION FUNCTIONS
from so.core.reentry_simulation import simulate_stop_reentry_dict, get_buy_and_hold_result_dict, simulate_trend_rule_dict, \
                                       get_model_reentry_func, get_fixed_delay_reentry_func, get_random_reentry_func

"""
Walk-Forward: exp02_stop_reentry (step 04, PROTOCOL.md §8-§12)

Per fold:
    1. VALIDATION: for each training window L in {10y, all}, fit the re-entry model on the training window, predict the
       validation sessions, then simulate every (k, threshold offset) candidate on the validation window.
    2. SELECTION: each candidate is scored by its MEAN validation excess return over the last SELECTION_POOLED_QUARTER_COUNT
       folds (pooled validation quarters, all before the test window). Ties: larger k, higher offset, then "10y" before "all".
    3. PRIOR-ONLY PATH (honest reporting, every run mode): the candidate selected at fold f is re-simulated on the
       validation quarter of fold f + 1 together with its uninformed baselines (same stop with fixed-delay and random
       re-entry), buy-and-hold and the 200-session trend rule (run_window_with_baseline_dict with window "valid").
    4. TEST (only in "latest" / "history" run modes): refit the selected L on the refit window (ending at the validation
       end), simulate the test window once, with the same baselines and the cost sensitivity (window "test").

Leakage guards: the label looks config.LABEL_HORIZON_SESSIONS ahead, so the windows are separated by EMBARGO_TRADING_DAYS
(>= the horizon); every feature uses only data up to the decision bar (so.features.daily_features).
"""

"""
Schedule
"""

# FUNCTION: GET THE WALK-FORWARD FOLDS
def get_fold_pdf(session_date_list_in, max_fold_count_in=None, train_years_in=exp_config.FIXED_TRAIN_WINDOW_YEARS):
    """
    Builds the schedule (shared conventions, the experiment's embargo, the fixed training window), plus the "all" window
    (every session since the start of the data). The fixed window is renamed "10y".

    Args:
        session_date_list_in (list[datetime.date]): Session dates of the data
        max_fold_count_in (int | None): Keep only the most recent folds
        train_years_in (int): Length of the fixed training window (years; 10 in the protocol, smaller in tests)

    Returns:
        pd.DataFrame: Fold columns + train_start_all, refit_start_all; the fixed window is renamed "10y" style
    """
    # BUILD THE SCHEDULE WITH THE EXPERIMENT EMBARGO
    fold_pdf = get_walk_forward_fold_pdf(session_date_list_in, exp_config.EMBARGO_TRADING_DAYS, [train_years_in], max_fold_count_in=max_fold_count_in)
    # ADD THE "ALL" WINDOW (START OF THE DATA)
    fold_pdf["train_start_all"] = session_date_list_in[0]
    fold_pdf["refit_start_all"] = session_date_list_in[0]
    # RENAME THE FIXED WINDOW TO THE "10y" KEY USED BY THE CONFIGURATION
    fold_pdf = fold_pdf.rename(columns={f"train_start_{train_years_in}y": "train_start_10y", f"refit_start_{train_years_in}y": "refit_start_10y"})
    # RETURN THE SCHEDULE
    return fold_pdf

"""
Model
"""

# FUNCTION: FIT THE RE-ENTRY MODEL
def fit_reentry_model_dict(train_pdf_in, feature_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST, model_str_in=exp_config.PRIMARY_MODEL_STR):
    """
    Fits P(positive 20-session forward return) on the training rows.

    Args:
        train_pdf_in (pd.DataFrame): Output of daily_features.get_daily_train_pdf
        feature_col_str_list_in (list[str]): Model features
        model_str_in (str): "logistic" (standardized, L2-regularized) or "lgbm"

    Returns:
        dict: model, base_rate (training mean of y), row_count, model_str
    """
    # COLLECT THE TRAINING DATA (A DATAFRAME KEEPS THE FEATURE NAMES FOR BOTH MODELS)
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
        daily_pdf_in (pd.DataFrame): Output of daily_features.get_daily_feature_pdf (indexed by session position)
        feature_col_str_list_in (list[str]): Model features

    Returns:
        np.ndarray: Probability per session position
    """
    # COLLECT THE FEATURES
    x_pdf = daily_pdf_in[list(feature_col_str_list_in)].astype(float)
    # DEFINE THE COMPLETE ROWS
    complete_mask = x_pdf.notna().all(axis=1).to_numpy()
    # PREDICT THE COMPLETE ROWS
    proba_arr = np.full(len(x_pdf), np.nan)
    if complete_mask.any():
        proba_arr[complete_mask] = model_dict_in["model"].predict_proba(x_pdf[complete_mask])[:, 1]
    # RETURN THE PROBABILITIES
    return proba_arr

# FUNCTION: GET THE CLASSIFICATION DIAGNOSTICS OF A WINDOW
def get_classification_diagnostic_dict(proba_arr_in, daily_pdf_in, date1_in, date2_in, prefix_str_in):
    """
    Calculates AUC and log loss of the predictions on the labelled rows of a window (diagnostic, not used for selection).

    Args:
        proba_arr_in (np.ndarray): Probability per session position
        daily_pdf_in (pd.DataFrame): Daily features and labels
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        prefix_str_in (str): Key prefix

    Returns:
        dict: <prefix>_auc, <prefix>_log_loss, <prefix>_row_count
    """
    # SELECT THE LABELLED ROWS OF THE WINDOW WITH A PREDICTION
    date1_object, date2_object = pd.to_datetime(date1_in).date(), pd.to_datetime(date2_in).date()
    mask = (daily_pdf_in["date"] >= date1_object).to_numpy() & (daily_pdf_in["date"] <= date2_object).to_numpy() \
           & daily_pdf_in["y_fwd_positive"].notna().to_numpy() & ~np.isnan(proba_arr_in)
    y_arr, p_arr = daily_pdf_in.loc[mask, "y_fwd_positive"].to_numpy(dtype=int), proba_arr_in[mask]
    # IF BOTH CLASSES ARE PRESENT
    if len(np.unique(y_arr)) == 2:
        return {f"{prefix_str_in}_auc": float(roc_auc_score(y_arr, p_arr)), f"{prefix_str_in}_log_loss": float(log_loss(y_arr, np.clip(p_arr, 1e-6, 1 - 1e-6))),
                f"{prefix_str_in}_row_count": int(mask.sum())}
    # RETURN NaN OTHERWISE
    return {f"{prefix_str_in}_auc": np.nan, f"{prefix_str_in}_log_loss": np.nan, f"{prefix_str_in}_row_count": int(mask.sum())}

"""
Validation And Selection
"""

# FUNCTION: RUN THE VALIDATION CANDIDATES OF ONE FOLD
def run_validation_candidate_pdf(fold_row_in, daily_pdf_in, ohlcv_array_dict_in,
                                 train_window_list_in=exp_config.TRAIN_WINDOW_LIST,
                                 stop_k_list_in=exp_config.STOP_K_LIST,
                                 offset_list_in=exp_config.REENTRY_THRESHOLD_OFFSET_LIST,
                                 feature_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST):
    """
    Fits the re-entry model per training window and simulates every (k, offset) candidate on the validation window.

    Args:
        fold_row_in (pd.Series): Row of get_fold_pdf
        daily_pdf_in (pd.DataFrame): Daily features and labels (indexed by session position)
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        train_window_list_in, stop_k_list_in, offset_list_in (list): Candidate grids
        feature_col_str_list_in (list[str]): Model features

    Returns:
        pd.DataFrame: One row per candidate with the validation metrics and excess return over buy-and-hold
    """
    # COLLECT THE VALIDATION WINDOW AND THE STOP VOLATILITY
    valid_start, valid_end = fold_row_in["valid_start"], fold_row_in["valid_end"]
    volatility_arr = daily_pdf_in["daily_volatility"].to_numpy(dtype=float)
    # SIMULATE BUY AND HOLD ONCE
    buy_hold_metric_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, valid_start, valid_end)["metric_dict"]
    # LIST TO HOLD THE CANDIDATE ROWS
    candidate_dict_list = []
    # ITERATE OVER THE TRAINING WINDOWS
    for train_window_str in train_window_list_in:
        # FIT THE PRIMARY MODEL AND THE DIAGNOSTIC MODEL
        train_pdf = get_daily_train_pdf(daily_pdf_in, fold_row_in[f"train_start_{train_window_str}"], fold_row_in["train_end"], feature_col_str_list_in)
        model_dict = fit_reentry_model_dict(train_pdf, feature_col_str_list_in, exp_config.PRIMARY_MODEL_STR)
        diagnostic_model_dict = fit_reentry_model_dict(train_pdf, feature_col_str_list_in, exp_config.DIAGNOSTIC_MODEL_STR)
        # PREDICT EVERY SESSION
        proba_arr = predict_reentry_proba_arr(model_dict, daily_pdf_in, feature_col_str_list_in)
        diagnostic_proba_arr = predict_reentry_proba_arr(diagnostic_model_dict, daily_pdf_in, feature_col_str_list_in)
        # COLLECT THE CLASSIFICATION DIAGNOSTICS
        diagnostic_dict = {**get_classification_diagnostic_dict(proba_arr, daily_pdf_in, valid_start, valid_end, f"valid_{exp_config.PRIMARY_MODEL_STR}"),
                           **get_classification_diagnostic_dict(diagnostic_proba_arr, daily_pdf_in, valid_start, valid_end, f"valid_{exp_config.DIAGNOSTIC_MODEL_STR}")}
        # ITERATE OVER THE CANDIDATES
        for stop_k in stop_k_list_in:
            for offset in offset_list_in:
                # DEFINE THE THRESHOLD
                threshold = model_dict["base_rate"] + offset
                # SIMULATE THE VALIDATION WINDOW
                simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, valid_start, valid_end, volatility_arr, stop_k,
                                                             get_model_reentry_func(proba_arr, threshold), "model",
                                                             max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
                metric_dict = simulation_dict["metric_dict"]
                # STORE THE CANDIDATE
                candidate_dict_list.append({
                    "fold_id": int(fold_row_in["fold_id"]), "train_window": train_window_str, "stop_k": stop_k, "threshold_offset": offset,
                    "train_row_count": model_dict["row_count"], "train_base_rate": model_dict["base_rate"], "threshold": threshold,
                    **{f"valid_{key}": value for key, value in metric_dict.items()},
                    **{f"valid_buy_hold_{key}": value for key, value in buy_hold_metric_dict.items()},
                    "valid_excess_return": round(metric_dict["total_return"] - buy_hold_metric_dict["total_return"], 8),
                    **diagnostic_dict,
                })
    # RETURN THE CANDIDATES
    return pd.DataFrame(candidate_dict_list)

# FUNCTION: ADD THE POOLED SELECTION SCORE AND PICK ONE CANDIDATE PER FOLD
def get_pooled_selection_pdf(candidate_pdf_in, pooled_quarter_count_in=exp_config.SELECTION_POOLED_QUARTER_COUNT):
    """
    Scores every candidate of fold f by the mean validation excess return of the same candidate over folds
    f - pooled_quarter_count_in + 1 .. f (fewer for the first folds) and selects the best candidate per fold.
    Ties: larger k, higher offset, then the shorter training window ("10y" before "all").

    Args:
        candidate_pdf_in (pd.DataFrame): Concatenated outputs of run_validation_candidate_pdf
        pooled_quarter_count_in (int): Number of validation quarters pooled

    Returns:
        pd.DataFrame: One selected row per fold (with pooled_valid_excess_return and pooled_quarter_count)
    """
    # ADD THE TRAINING WINDOW ORDER (TIE-BREAK)
    candidate_pdf = candidate_pdf_in.assign(window_order=candidate_pdf_in["train_window"].map({window_str: idx for idx, window_str in enumerate(exp_config.TRAIN_WINDOW_LIST)}))
    # SELECT WITH THE GENERIC POOLED RULE
    selection_pdf = get_generic_pooled_selection_pdf(candidate_pdf, ["train_window", "stop_k", "threshold_offset"], "valid_excess_return", pooled_quarter_count_in,
                                                     [("stop_k", False), ("threshold_offset", False), ("window_order", True)])
    # RETURN THE SELECTION (NAMES OF THE stop_reentry_v2 OUTPUT KEPT)
    return selection_pdf.rename(columns={"pooled_score": "pooled_valid_excess_return"}).drop(columns=["window_order"])

"""
Evaluation Window With Baselines (prior-only path on validation, test windows)
"""

# FUNCTION: SIMULATE ONE WINDOW WITH THE SELECTED CANDIDATE AND ITS BASELINES
def run_window_with_baseline_dict(fold_row_in, selection_row_in, daily_pdf_in, ohlcv_array_dict_in, window_str_in="valid",
                                  feature_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST, alert_in=True):
    """
    Simulates one candidate on one window of a fold, with every baseline and the cost sensitivity.

        window "valid": the model is fitted on the fold's TRAINING window (exactly the validation candidate of the fold);
                        used for the prior-only path (candidate selected at fold f - 1, evaluated on fold f's quarter).
        window "test":  the model is refit on the REFIT window (ending at the validation end) and the test window is
                        evaluated ONCE (run modes "latest" / "history" only).

    Baselines (same simulator, same costs): buy-and-hold; same stop with fixed-delay re-entry (FIXED_DELAY_SESSION_LIST);
    same stop with random re-entry (RANDOM_REENTRY_RUN_COUNT runs, daily probability = 1 / the model's mean cash decisions
    per episode); the 200-session trend rule.

    Args:
        fold_row_in (pd.Series): Row of get_fold_pdf
        selection_row_in (pd.Series): Candidate (train_window, stop_k, threshold_offset)
        daily_pdf_in (pd.DataFrame): Daily features and labels (indexed by session position)
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        window_str_in (str): "valid" or "test"
        feature_col_str_list_in (list[str]): Model features
        alert_in (bool): Display a summary line

    Returns:
        dict: metric_dict (strategy and buy-and-hold), baseline_pdf, cost_sensitivity_pdf, transaction_pdf, episode_pdf,
              daily_equity_pdf, buy_hold_daily_equity_pdf
    """
    # COLLECT THE WINDOW, THE MODEL WINDOW AND THE SELECTED CANDIDATE
    window_start, window_end = fold_row_in[f"{window_str_in}_start"], fold_row_in[f"{window_str_in}_end"]
    train_window_str, stop_k, offset = selection_row_in["train_window"], selection_row_in["stop_k"], selection_row_in["threshold_offset"]
    model_start = fold_row_in[f"train_start_{train_window_str}"] if window_str_in == "valid" else fold_row_in[f"refit_start_{train_window_str}"]
    model_end = fold_row_in["train_end"] if window_str_in == "valid" else fold_row_in["refit_end"]
    volatility_arr = daily_pdf_in["daily_volatility"].to_numpy(dtype=float)
    max_cash_sessions = exp_config.MAX_CASH_SESSIONS
    # FIT THE MODEL (THE EMBARGO PROTECTS THE EVALUATED WINDOW)
    model_dict = fit_reentry_model_dict(get_daily_train_pdf(daily_pdf_in, model_start, model_end, feature_col_str_list_in), feature_col_str_list_in, exp_config.PRIMARY_MODEL_STR)
    proba_arr = predict_reentry_proba_arr(model_dict, daily_pdf_in, feature_col_str_list_in)
    threshold = model_dict["base_rate"] + offset
    # SIMULATE THE STRATEGY
    simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, window_start, window_end, volatility_arr, stop_k, get_model_reentry_func(proba_arr, threshold), "model",
                                                 max_cash_sessions_in=max_cash_sessions)
    # SIMULATE BUY AND HOLD
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, window_start, window_end)
    # LIST TO HOLD THE BASELINE ROWS
    baseline_dict_list = [{"baseline": "model", **simulation_dict["metric_dict"]}, {"baseline": "buy_hold", **buy_hold_dict["metric_dict"]}]
    # FIXED-DELAY BASELINES (SAME STOP)
    for delay_session_count in exp_config.FIXED_DELAY_SESSION_LIST:
        delay_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, window_start, window_end, volatility_arr, stop_k, get_fixed_delay_reentry_func(delay_session_count), "delay",
                                                max_cash_sessions_in=max_cash_sessions)
        baseline_dict_list.append({"baseline": f"fixed_delay_{delay_session_count}", **delay_dict["metric_dict"]})
    # RANDOM RE-ENTRY BASELINES (SAME STOP; DAILY PROBABILITY = 1 / THE MODEL'S MEAN CASH DECISIONS PER EPISODE)
    episode_pdf = simulation_dict["episode_pdf"]
    mean_cash_sessions = simulation_dict["metric_dict"].get("mean_cash_sessions", np.nan)
    # IF NO EPISODE CLOSED WITH A RE-ENTRY, USE EVERY EPISODE (INCLUDING THE ONE STILL OPEN AT THE WINDOW END)
    if not np.isfinite(mean_cash_sessions) and not episode_pdf.empty:
        mean_cash_sessions = float(episode_pdf["cash_session_count"].mean())
    random_probability = 1.0 / mean_cash_sessions if np.isfinite(mean_cash_sessions) and mean_cash_sessions > 0 else np.nan
    # ITERATE OVER THE RANDOM RUNS
    for run_idx in range(exp_config.RANDOM_REENTRY_RUN_COUNT):
        # IF THE MODEL NEVER LEFT THE MARKET (NO STOP: EVERY RUN WOULD EQUAL THE MODEL)
        if not np.isfinite(random_probability):
            # STORE THE MODEL RESULT
            baseline_dict_list.append({"baseline": f"random_{run_idx:02d}", **simulation_dict["metric_dict"]})
            continue
        # SIMULATE THE RANDOM RUN
        random_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, window_start, window_end, volatility_arr, stop_k,
                                                 get_random_reentry_func(random_probability, config.RANDOM_SEED + run_idx), "random", max_cash_sessions_in=max_cash_sessions)
        baseline_dict_list.append({"baseline": f"random_{run_idx:02d}", **random_dict["metric_dict"]})
    # TEXTBOOK TREND RULE
    trend_dict = simulate_trend_rule_dict(ohlcv_array_dict_in, daily_pdf_in, window_start, window_end, f"ma{exp_config.TREND_RULE_MA_SESSIONS}_dist_pct")
    baseline_dict_list.append({"baseline": f"trend_ma{exp_config.TREND_RULE_MA_SESSIONS}", **trend_dict["metric_dict"]})
    baseline_pdf = pd.DataFrame(baseline_dict_list)
    baseline_pdf["excess_return"] = baseline_pdf["total_return"] - buy_hold_dict["metric_dict"]["total_return"]
    # COST SENSITIVITY (SAME RULE, DIFFERENT SLIPPAGE ON BOTH SIDES; BUY-AND-HOLD RECOMPUTED WITH THE SAME SLIPPAGE)
    cost_dict_list = []
    for slippage in config.COST_SENSITIVITY_SLIPPAGE_LIST:
        cost_simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, window_start, window_end, volatility_arr, stop_k, get_model_reentry_func(proba_arr, threshold), "model",
                                                          max_cash_sessions_in=max_cash_sessions, entry_slippage_in=slippage, market_exit_slippage_in=slippage)
        cost_buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, window_start, window_end, entry_slippage_in=slippage, market_exit_slippage_in=slippage)
        cost_dict_list.append({"slippage_per_share": slippage, "total_return": cost_simulation_dict["metric_dict"]["total_return"],
                               "buy_hold_return": cost_buy_hold_dict["metric_dict"]["total_return"],
                               "excess_return": cost_simulation_dict["metric_dict"]["total_return"] - cost_buy_hold_dict["metric_dict"]["total_return"]})
    # DEFINE THE METRICS
    metric_dict = {**simulation_dict["metric_dict"],
                   **{f"buy_hold_{key}": value for key, value in buy_hold_dict["metric_dict"].items()},
                   "excess_return": round(simulation_dict["metric_dict"]["total_return"] - buy_hold_dict["metric_dict"]["total_return"], 8),
                   "model_row_count": model_dict["row_count"], "model_base_rate": model_dict["base_rate"], "threshold": threshold}
    # DISPLAY INFORMATION
    print(f"\t{window_str_in}: total return {metric_dict['total_return']:.4%} | buy & hold {metric_dict['buy_hold_total_return']:.4%} | stops {metric_dict['stop_count']}") if alert_in else None
    # RETURN THE RESULTS
    return {"metric_dict": metric_dict, "baseline_pdf": baseline_pdf, "cost_sensitivity_pdf": pd.DataFrame(cost_dict_list),
            "transaction_pdf": simulation_dict["transaction_pdf"], "episode_pdf": simulation_dict["episode_pdf"],
            "daily_equity_pdf": simulation_dict["daily_equity_pdf"], "buy_hold_daily_equity_pdf": buy_hold_dict["daily_equity_pdf"]}
