import pandas as pd
import numpy as np
import lightgbm as lgb
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp01_minute_entry import config as exp_config
# IMPORT THE WALK-FORWARD SCHEDULE
from so.core.schedule import get_walk_forward_fold_pdf
# IMPORT BARRIER LABEL FUNCTIONS
from so.features.barrier_labels import get_delta_col_str
# IMPORT MODEL DATASET FUNCTIONS
from experiments.exp01_minute_entry.model_dataset import encode_feature_pdf, get_uniqueness_weight_arr
# IMPORT TRADE EXECUTION FUNCTIONS
from so.core.trade_execution import get_expected_net_return_arr
# IMPORT BACKTEST SIMULATION FUNCTIONS
from so.core.backtest_simulation import simulate_decision_trading_dict, \
                                       get_daily_equity_pdf, \
                                       simulate_buy_and_hold_dict
# IMPORT PERFORMANCE METRIC FUNCTIONS
from so.core.performance_metrics import get_performance_metric_dict

"""
Walk-Forward: exp01_minute_entry (step 03, PROTOCOL.md §9-§12)

Each fold replays the procedure as if it were run live at the start of its test window:

    |----- train (L years) -----| embargo |-- validation (3 months) --| embargo |-- test (3 months) --|

    - embargo = EMBARGO_TRADING_DAYS sessions, so no training label (up to MAX_HOLD_TRADING_DAYS long) reaches into
      the next window;
    - the training window length L and the expected-return threshold are selected on validation (primary metric:
      total return after costs);
    - the selected setup is refit on the L years ending just before the test embargo (REFIT_BEFORE_TEST) and evaluated
      once on the test window, together with the baselines.

The most recent fold is the moving test window tracked over time. Older folds replay history.

Honest reporting (2026-10-05): run_walk_forward_fold_dict also returns every candidate's validation decisions, so the
notebook can re-simulate the setting selected at fold f - 1 on fold f's validation quarter together with its baselines
(run_window_with_baseline_dict): the prior-only path and the information test, without reading any test window.

Model (proposal pending agreement on the output format): one LightGBM classifier per delta predicting P(take profit).
Decision policy: at each eligible decision bar, compute the expected net return of every delta from P(TP) and the
decision bar close (the entry open is not known yet), pick the best delta, buy if its expected return > threshold.
"""

"""
Schedule And Window Selection
"""

# FUNCTION: GET THE WALK-FORWARD FOLDS OF THE EXPERIMENT
def get_fold_pdf(session_date_list_in, max_fold_count_in=None, train_window_years_list_in=exp_config.TRAIN_WINDOW_YEARS_LIST):
    """
    Builds the schedule with the shared conventions, the experiment's embargo and its training window candidates.

    Args:
        session_date_list_in (list[datetime.date]): Session dates of the data
        max_fold_count_in (int | None): Keep only the most recent folds
        train_window_years_list_in (list[int]): Training window candidates (years)

    Returns:
        pd.DataFrame: Output of so.core.schedule.get_walk_forward_fold_pdf
    """
    # RETURN THE SCHEDULE
    return get_walk_forward_fold_pdf(session_date_list_in, exp_config.EMBARGO_TRADING_DAYS, train_window_years_list_in, max_fold_count_in=max_fold_count_in)


# FUNCTION: GET THE ROWS OF A DATE WINDOW
def get_window_pdf(dataset_pdf_in, date1_in, date2_in):
    """
    Selects the dataset rows whose decision date is within an inclusive date window.

    Args:
        dataset_pdf_in (pd.DataFrame): Model dataset rows with a date column (datetime.date)
        date1_in (datetime.date | str): Start date (inclusive)
        date2_in (datetime.date | str): End date (inclusive)

    Returns:
        pd.DataFrame: Rows in the window
    """
    # CONVERT THE DATES
    date1_object, date2_object = pd.to_datetime(date1_in).date(), pd.to_datetime(date2_in).date()
    # RETURN THE ROWS IN THE WINDOW
    return dataset_pdf_in[(dataset_pdf_in["date"] >= date1_object) & (dataset_pdf_in["date"] <= date2_object)]

"""
Model And Decision Policy
"""

# FUNCTION: FIT THE TAKE PROFIT PROBABILITY MODELS
def fit_tp_model_dict(train_pdf_in, feature_col_str_list_in, ohlcv_array_dict_in,
                      delta_list_in=exp_config.MODEL_DELTA_LIST,
                      sample_weight_mode_str_in=exp_config.SAMPLE_WEIGHT_MODE,
                      lgbm_param_dict_in=exp_config.LGBM_PARAM_DICT,
                      seed_in=config.RANDOM_SEED,
                      alert_in=False):
    """
    Fits one LightGBM binary classifier per delta predicting whether the take profit is hit first.
    Unresolved rows (NA) are excluded; time limit exits count as "not take profit".

    Args:
        train_pdf_in (pd.DataFrame): Labeled (and sampled) training rows
        feature_col_str_list_in (list[str]): Feature columns
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict (uniqueness weights)
        delta_list_in (list[float]): Deltas to model
        sample_weight_mode_str_in (str): "none" or "uniqueness"
        lgbm_param_dict_in (dict): LightGBM parameters
        seed_in (int): Random seed
        alert_in (bool): Display progress

    Returns:
        dict: delta -> fitted LGBMClassifier (deltas with a single class or no rows are skipped)
    """
    # ENCODE THE FEATURES
    feature_pdf = encode_feature_pdf(train_pdf_in, feature_col_str_list_in)
    # DICTIONARY TO HOLD THE MODELS
    model_dict = {}
    # ITERATE OVER THE DELTAS
    for delta in delta_list_in:
        # IF THE LABEL COLUMN IS MISSING
        if f"y_tp_{get_delta_col_str(delta)}" not in train_pdf_in.columns:
            # DISPLAY INFORMATION
            print(f"\t⚠️ Delta {delta}: no label column, no model") if alert_in else None
            # SKIP THE DELTA
            continue
        # COLLECT THE LABELS
        y_series = train_pdf_in[f"y_tp_{get_delta_col_str(delta)}"]
        # DEFINE THE RESOLVED MASK
        resolved_mask = y_series.notna().to_numpy()
        # IF THERE IS ONLY ONE CLASS
        if y_series[resolved_mask].nunique() < 2:
            # DISPLAY INFORMATION
            print(f"\t⚠️ Delta {delta}: single class, no model") if alert_in else None
            # SKIP THE DELTA
            continue
        # CALCULATE THE SAMPLE WEIGHTS
        weight_arr = get_uniqueness_weight_arr(train_pdf_in, delta, ohlcv_array_dict_in) if sample_weight_mode_str_in == "uniqueness" else np.ones(len(train_pdf_in))
        # COMBINE THE RESOLVED MASK WITH VALID WEIGHTS
        fit_mask = resolved_mask & np.isfinite(weight_arr)
        # CREATE THE MODEL
        model = lgb.LGBMClassifier(**lgbm_param_dict_in, random_state=seed_in)
        # FIT THE MODEL
        model.fit(feature_pdf[fit_mask], y_series[fit_mask].astype(int), sample_weight=weight_arr[fit_mask])
        # ADD THE MODEL TO THE DICTIONARY
        model_dict[delta] = model
        # DISPLAY INFORMATION
        print(f"\t✅ Delta {delta}: fitted on {int(fit_mask.sum()):,} rows (TP rate {y_series[fit_mask].mean():.3f})") if alert_in else None
    # RETURN THE MODEL DICTIONARY
    return model_dict

# FUNCTION: PREDICT THE TAKE PROFIT PROBABILITIES
def predict_tp_proba_pdf(model_dict_in, dataset_pdf_in, feature_col_str_list_in):
    """
    Predicts P(take profit) of every modeled delta.

    Args:
        model_dict_in (dict): Output of fit_tp_model_dict
        dataset_pdf_in (pd.DataFrame): Rows to predict
        feature_col_str_list_in (list[str]): Feature columns (same as training)

    Returns:
        pd.DataFrame: Columns p_tp_<d> (same index as the input)
    """
    # ENCODE THE FEATURES
    feature_pdf = encode_feature_pdf(dataset_pdf_in, feature_col_str_list_in)
    # RETURN THE PROBABILITIES
    return pd.DataFrame({f"p_tp_{get_delta_col_str(delta)}": model.predict_proba(feature_pdf)[:, 1]
                         for delta, model in model_dict_in.items()}, index=dataset_pdf_in.index)

# FUNCTION: GET THE POLICY DECISIONS
def get_policy_decision_pdf(dataset_pdf_in, proba_pdf_in, ev_threshold_float_in, rr_ratio_float_in=config.RR_RATIO, **cost_kwargs):
    """
    Converts take profit probabilities into decisions: best expected net return across deltas, buy if above threshold.
    The expected return uses the decision bar CLOSE (known at decision time), never the entry open.

    Args:
        dataset_pdf_in (pd.DataFrame): Rows with decision_ts and close
        proba_pdf_in (pd.DataFrame): Output of predict_tp_proba_pdf (same index)
        ev_threshold_float_in (float): Minimum expected net return to buy
        rr_ratio_float_in (float): Stop loss distance / take profit distance
        **cost_kwargs: Optional cost overrides for trade_execution.get_expected_net_return_arr

    Returns:
        pd.DataFrame: decision_ts, buy_flag, delta, expected_return
    """
    # IF THERE ARE NO PROBABILITIES
    if proba_pdf_in.empty:
        # RETURN NO BUY DECISIONS
        return pd.DataFrame({"decision_ts": dataset_pdf_in["decision_ts"].to_numpy(), "buy_flag": False, "delta": np.nan, "expected_return": np.nan})
    # COLLECT THE DELTAS FROM THE PROBABILITY COLUMNS
    delta_arr = np.array([float(col.replace("p_tp_", "")) for col in proba_pdf_in.columns])
    # COLLECT THE DECISION BAR CLOSE
    close_arr = dataset_pdf_in["close"].to_numpy(dtype=float)
    # CALCULATE THE EXPECTED NET RETURN OF EVERY DELTA (ROWS x DELTAS)
    ev_mat = np.column_stack([get_expected_net_return_arr(proba_pdf_in[col].to_numpy(), close_arr, delta, rr_ratio_float_in, **cost_kwargs)
                              for col, delta in zip(proba_pdf_in.columns, delta_arr)])
    # COLLECT THE BEST DELTA OF EVERY ROW
    best_idx_arr = np.nanargmax(np.where(np.isfinite(ev_mat), ev_mat, -np.inf), axis=1)
    best_ev_arr = ev_mat[np.arange(len(ev_mat)), best_idx_arr]
    # RETURN THE DECISION DATAFRAME
    return pd.DataFrame({"decision_ts": dataset_pdf_in["decision_ts"].to_numpy(),
                         "buy_flag": best_ev_arr > ev_threshold_float_in,
                         "delta": delta_arr[best_idx_arr],
                         "expected_return": best_ev_arr})

"""
Fold Runner
"""

# FUNCTION: SIMULATE AND SCORE A DECISION DATAFRAME OVER A WINDOW
def get_window_simulation_dict(decision_pdf_in, ohlcv_array_dict_in, date1_in, date2_in, initial_capital_in=config.INITIAL_CAPITAL, **slippage_kwargs):
    """
    Simulates decisions over a window and scores them against buy-and-hold over the same span
    (from the window start to the later of the window end and the last exit).

    Args:
        decision_pdf_in (pd.DataFrame): decision_ts, buy_flag, delta
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        initial_capital_in (float): Starting cash
        **slippage_kwargs: Optional slippage overrides for simulate_decision_trading_dict

    Returns:
        dict: transaction_pdf, daily_equity_pdf, metric_dict (with buy_hold_return and excess_return)
    """
    # SIMULATE THE DECISIONS
    simulation_dict = simulate_decision_trading_dict(decision_pdf_in, ohlcv_array_dict_in, initial_capital_in, **slippage_kwargs)
    transaction_pdf = simulation_dict["transaction_pdf"]
    # CALCULATE THE DAILY EQUITY CURVE
    daily_equity_pdf = get_daily_equity_pdf(transaction_pdf, ohlcv_array_dict_in, str(date1_in), str(date2_in), initial_capital_in)
    # COLLECT THE LAST DATE OF THE EQUITY CURVE (WINDOW END OR LAST EXIT)
    span_end_date = daily_equity_pdf["date"].max() if not daily_equity_pdf.empty else pd.to_datetime(date2_in).date()
    # SIMULATE BUY AND HOLD OVER THE SAME SPAN
    entry_slippage = slippage_kwargs.get("entry_slippage_in", config.ENTRY_SLIPPAGE_PER_SHARE)
    exit_slippage = slippage_kwargs.get("market_exit_slippage_in", config.MARKET_EXIT_SLIPPAGE_PER_SHARE)
    buy_hold_dict = simulate_buy_and_hold_dict(ohlcv_array_dict_in, str(date1_in), str(span_end_date), initial_capital_in, entry_slippage, exit_slippage)
    # COLLECT THE NUMBER OF BARS IN THE SPAN
    session_mask = np.array([pd.to_datetime(date1_in).date() <= d <= span_end_date for d in ohlcv_array_dict_in["session_date_list"]])
    window_bar_count = int((ohlcv_array_dict_in["session_end_idx_arr"][session_mask] - ohlcv_array_dict_in["session_start_idx_arr"][session_mask] + 1).sum())
    # CALCULATE THE METRICS
    metric_dict = get_performance_metric_dict(transaction_pdf, daily_equity_pdf, window_bar_count, initial_capital_in)
    buy_hold_metric_dict = get_performance_metric_dict(buy_hold_dict["transaction_pdf"], buy_hold_dict["daily_equity_pdf"], window_bar_count, initial_capital_in)
    # ADD THE BENCHMARK COMPARISON
    metric_dict["buy_hold_return"] = buy_hold_metric_dict["total_return"]
    metric_dict["buy_hold_sharpe_ratio"] = buy_hold_metric_dict["sharpe_ratio"]
    metric_dict["buy_hold_max_drawdown"] = buy_hold_metric_dict["max_drawdown"]
    metric_dict["excess_return"] = round(metric_dict["total_return"] - buy_hold_metric_dict["total_return"], 8)
    metric_dict["skipped_decision_count"] = simulation_dict["skipped_decision_count"]
    # RETURN THE DICTIONARY
    return {"transaction_pdf": transaction_pdf, "daily_equity_pdf": daily_equity_pdf, "metric_dict": metric_dict}

# FUNCTION: SIMULATE ONE WINDOW WITH A SETTING'S DECISIONS AND ITS BASELINES
def run_window_with_baseline_dict(decision_pdf_in, window_pdf_in, ohlcv_array_dict_in, date1_in, date2_in, alert_in=False):
    """
    Simulates a setting's decisions over a window together with the uninformed baselines and the cost sensitivity.

        Baselines (same simulator, same costs): RANDOM_BASELINE_RUN_COUNT random-entry runs (every eligible minute buys
        with the model's buy rate, with a delta drawn from the model's chosen deltas: matched activity) and the
        fixed-time entry (10:00 open every session when flat, FIXED_TIME_BASELINE_DELTA). Buy-and-hold is part of each
        row (buy_hold_return), measured over the same span as the row (window start -> later of window end and last exit).

    Used for the prior-only path on validation (the setting selected at fold f - 1 on fold f's validation quarter) and
    for the test window (run modes "latest" / "history").

    Args:
        decision_pdf_in (pd.DataFrame): Decisions of the setting over the window (output of get_policy_decision_pdf)
        window_pdf_in (pd.DataFrame): Unsampled model dataset rows of the window (eligible decision bars)
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        alert_in (bool): Display a summary line

    Returns:
        dict: metric_dict, baseline_pdf (model, random_<i>, fixed_time; with excess_return), cost_sensitivity_pdf,
              transaction_pdf, daily_equity_pdf, buy_hold_daily_equity_pdf
    """
    # SIMULATE THE SETTING
    simulation_dict = get_window_simulation_dict(decision_pdf_in, ohlcv_array_dict_in, date1_in, date2_in)
    # LIST TO HOLD THE BASELINE ROWS
    baseline_dict_list = [{"baseline": "model", **simulation_dict["metric_dict"]}]
    # COLLECT THE MODEL ACTIVITY (BUY RATE AND CHOSEN DELTAS)
    model_buy_rate = float(decision_pdf_in["buy_flag"].mean()) if len(decision_pdf_in) > 0 else 0.0
    model_delta_list = decision_pdf_in.loc[decision_pdf_in["buy_flag"], "delta"].dropna().tolist() or [exp_config.FIXED_TIME_BASELINE_DELTA]
    # RANDOM ENTRY BASELINES (MATCHED ACTIVITY)
    for run_idx in range(exp_config.RANDOM_BASELINE_RUN_COUNT):
        random_decision_pdf = get_random_decision_pdf(window_pdf_in["decision_ts"], model_buy_rate, model_delta_list, seed_in=config.RANDOM_SEED + run_idx)
        baseline_dict_list.append({"baseline": f"random_{run_idx:02d}", **get_window_simulation_dict(random_decision_pdf, ohlcv_array_dict_in, date1_in, date2_in)["metric_dict"]})
    # FIXED-TIME BASELINE
    fixed_time_decision_pdf = get_fixed_time_decision_pdf(window_pdf_in["decision_ts"])
    baseline_dict_list.append({"baseline": "fixed_time", **get_window_simulation_dict(fixed_time_decision_pdf, ohlcv_array_dict_in, date1_in, date2_in)["metric_dict"]})
    # CONVERT THE BASELINES (total_return AND excess_return OVER EACH ROW'S OWN BUY-AND-HOLD SPAN)
    baseline_pdf = pd.DataFrame(baseline_dict_list)
    # COST SENSITIVITY (SAME DECISIONS, DIFFERENT SLIPPAGE)
    cost_dict_list = []
    for slippage in config.COST_SENSITIVITY_SLIPPAGE_LIST:
        cost_metric_dict = get_window_simulation_dict(decision_pdf_in, ohlcv_array_dict_in, date1_in, date2_in, entry_slippage_in=slippage, market_exit_slippage_in=slippage)["metric_dict"]
        cost_dict_list.append({"slippage_per_share": slippage, **cost_metric_dict})
    # SIMULATE BUY AND HOLD OVER THE MODEL SPAN (DAILY EQUITY FOR THE CHAINED STATISTICS)
    span_end_date = simulation_dict["daily_equity_pdf"]["date"].max() if not simulation_dict["daily_equity_pdf"].empty else pd.to_datetime(date2_in).date()
    buy_hold_dict = simulate_buy_and_hold_dict(ohlcv_array_dict_in, str(date1_in), str(span_end_date))
    # DISPLAY INFORMATION
    print(f"\ttotal return {simulation_dict['metric_dict']['total_return']:.4%} | buy & hold {simulation_dict['metric_dict']['buy_hold_return']:.4%} | trades {simulation_dict['metric_dict']['trade_count']}") if alert_in else None
    # RETURN THE RESULTS
    return {"metric_dict": simulation_dict["metric_dict"], "baseline_pdf": baseline_pdf, "cost_sensitivity_pdf": pd.DataFrame(cost_dict_list),
            "transaction_pdf": simulation_dict["transaction_pdf"], "daily_equity_pdf": simulation_dict["daily_equity_pdf"],
            "buy_hold_daily_equity_pdf": buy_hold_dict["daily_equity_pdf"]}

# FUNCTION: RUN ONE WALK-FORWARD FOLD
def run_walk_forward_fold_dict(fold_row_in, train_pool_pdf_in, eval_pool_pdf_in, ohlcv_array_dict_in, feature_col_str_list_in,
                               delta_list_in=exp_config.MODEL_DELTA_LIST,
                               train_window_years_list_in=exp_config.TRAIN_WINDOW_YEARS_LIST,
                               ev_threshold_list_in=exp_config.EV_THRESHOLD_LIST,
                               selection_metric_str_in=exp_config.SELECTION_METRIC_STR,
                               run_test_bool_in=True,
                               alert_in=True):
    """
    Runs one fold: every validation candidate, selection on validation, (refit), one evaluation on test with baselines
    and cost sensitivity.

    Args:
        fold_row_in (pd.Series): One row of get_fold_pdf
        train_pool_pdf_in (pd.DataFrame): SAMPLED labeled rows covering every training / refit window of the fold
        eval_pool_pdf_in (pd.DataFrame): UNSAMPLED rows covering the validation and test windows (every eligible decision)
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict (complete data)
        feature_col_str_list_in (list[str]): Feature columns
        delta_list_in (list[float]): Deltas that receive a take profit model
        train_window_years_list_in (list[int]): Training window candidates
        ev_threshold_list_in (list[float]): Expected return threshold candidates
        selection_metric_str_in (str): Validation metric to maximize
        run_test_bool_in (bool): Evaluate the test window (False while iterating on the design: the test window stays unseen)
        alert_in (bool): Display progress

    Returns:
        dict: selection_pdf (every validation candidate), valid_decision_pdf_dict ((train_years, ev_threshold) -> validation
              decisions, used by the prior-only path), valid_pdf (unsampled validation rows), best_setting_dict, and in
              test mode: test_metric_dict, baseline_metric_pdf, cost_sensitivity_pdf, test_transaction_pdf,
              test_daily_equity_pdf, test_buy_hold_daily_equity_pdf, test_decision_pdf
    """
    # SELECT THE VALIDATION AND TEST ROWS
    valid_pdf = get_window_pdf(eval_pool_pdf_in, fold_row_in["valid_start"], fold_row_in["valid_end"])
    test_pdf = get_window_pdf(eval_pool_pdf_in, fold_row_in["test_start"], fold_row_in["test_end"])
    # LIST AND DICTIONARY TO HOLD THE CANDIDATES AND THEIR VALIDATION DECISIONS
    selection_dict_list, valid_decision_pdf_dict = [], {}
    # ITERATE OVER THE TRAINING WINDOWS
    for train_years in train_window_years_list_in:
        # SKIP A WINDOW THAT DOES NOT FIT IN THE DATA
        if not fold_row_in.get(f"fits_{train_years}y", True):
            continue
        # SELECT THE TRAINING ROWS
        train_pdf = get_window_pdf(train_pool_pdf_in, fold_row_in[f"train_start_{train_years}y"], fold_row_in["train_end"])
        print(f"\tTrain {train_years}y: {fold_row_in[f'train_start_{train_years}y']} -> {fold_row_in['train_end']} ({len(train_pdf):,} rows)") if alert_in else None
        # FIT THE MODELS AND PREDICT THE VALIDATION ROWS
        model_dict = fit_tp_model_dict(train_pdf, feature_col_str_list_in, ohlcv_array_dict_in, delta_list_in)
        valid_proba_pdf = predict_tp_proba_pdf(model_dict, valid_pdf, feature_col_str_list_in)
        # ITERATE OVER THE THRESHOLDS
        for ev_threshold in ev_threshold_list_in:
            # DECIDE AND SIMULATE THE VALIDATION WINDOW
            valid_decision_pdf = get_policy_decision_pdf(valid_pdf, valid_proba_pdf, ev_threshold)
            valid_decision_pdf_dict[(int(train_years), float(ev_threshold))] = valid_decision_pdf
            valid_simulation_dict = get_window_simulation_dict(valid_decision_pdf, ohlcv_array_dict_in, fold_row_in["valid_start"], fold_row_in["valid_end"])
            # STORE THE CANDIDATE
            selection_dict_list.append({"fold_id": int(fold_row_in["fold_id"]), "train_years": train_years, "ev_threshold": ev_threshold,
                                        "train_row_count": len(train_pdf), "model_count": len(model_dict),
                                        **{f"valid_{key}": value for key, value in valid_simulation_dict["metric_dict"].items()}})
    # CONVERT THE CANDIDATES (valid_buy_hold_total_return = THE CANDIDATE'S OWN BUY-AND-HOLD SPAN)
    selection_pdf = pd.DataFrame(selection_dict_list)
    selection_pdf["valid_buy_hold_total_return"] = selection_pdf["valid_buy_hold_return"]
    # SELECT ON VALIDATION (TIES: SHORTER WINDOW, HIGHER THRESHOLD)
    best_row = selection_pdf.sort_values([f"valid_{selection_metric_str_in}", "train_years", "ev_threshold"], ascending=[False, True, False]).iloc[0]
    best_setting_dict = {"train_years": int(best_row["train_years"]), "ev_threshold": float(best_row["ev_threshold"])}
    print(f"\t🏆 Selected on validation: {best_setting_dict} ({selection_metric_str_in}: {best_row[f'valid_{selection_metric_str_in}']:.4%})") if alert_in else None
    # DEFINE THE RESULT
    result_dict = {"selection_pdf": selection_pdf, "valid_decision_pdf_dict": valid_decision_pdf_dict, "valid_pdf": valid_pdf, "best_setting_dict": best_setting_dict}
    # IF THE TEST WINDOW STAYS UNSEEN
    if not run_test_bool_in:
        # RETURN THE VALIDATION RESULTS
        return result_dict
    # DEFINE THE FINAL TRAINING WINDOW (REFIT ENDS AN EMBARGO BEFORE THE TEST WINDOW)
    final_train_start = fold_row_in[f"refit_start_{best_setting_dict['train_years']}y"] if exp_config.REFIT_BEFORE_TEST else fold_row_in[f"train_start_{best_setting_dict['train_years']}y"]
    final_train_end = fold_row_in["refit_end"] if exp_config.REFIT_BEFORE_TEST else fold_row_in["train_end"]
    final_train_pdf = get_window_pdf(train_pool_pdf_in, final_train_start, final_train_end)
    # FIT, PREDICT AND DECIDE ON THE TEST WINDOW
    final_model_dict = fit_tp_model_dict(final_train_pdf, feature_col_str_list_in, ohlcv_array_dict_in, delta_list_in)
    test_proba_pdf = predict_tp_proba_pdf(final_model_dict, test_pdf, feature_col_str_list_in)
    test_decision_pdf = get_policy_decision_pdf(test_pdf, test_proba_pdf, best_setting_dict["ev_threshold"])
    # EVALUATE THE TEST WINDOW ONCE WITH THE BASELINES
    test_window_dict = run_window_with_baseline_dict(test_decision_pdf, test_pdf, ohlcv_array_dict_in, fold_row_in["test_start"], fold_row_in["test_end"], alert_in=alert_in)
    # ADD THE TEST RESULTS
    result_dict.update({
        "final_train_window": (final_train_start, final_train_end, len(final_train_pdf)),
        "test_metric_dict": test_window_dict["metric_dict"],
        "baseline_metric_pdf": test_window_dict["baseline_pdf"],
        "cost_sensitivity_pdf": test_window_dict["cost_sensitivity_pdf"],
        "test_transaction_pdf": test_window_dict["transaction_pdf"],
        "test_daily_equity_pdf": test_window_dict["daily_equity_pdf"],
        "test_buy_hold_daily_equity_pdf": test_window_dict["buy_hold_daily_equity_pdf"],
        "test_decision_pdf": test_decision_pdf,
    })
    # RETURN THE RESULTS
    return result_dict

"""
Baseline Decisions
"""

# FUNCTION: GET RANDOM ENTRY DECISIONS
def get_random_decision_pdf(eligible_decision_ts_series_in, buy_probability_in, delta_list_in, seed_in=config.RANDOM_SEED):
    """
    Builds the random entry baseline: every eligible decision bar buys with probability buy_probability_in, with a delta
    drawn uniformly from delta_list_in. Use the model's buy rate and chosen deltas to match its activity.

    Args:
        eligible_decision_ts_series_in (pd.Series): Eligible decision timestamps of the window
        buy_probability_in (float): Probability of a buy at each eligible bar
        delta_list_in (list[float]): Deltas to draw from
        seed_in (int): Random seed

    Returns:
        pd.DataFrame: Decision DataFrame (decision_ts, buy_flag, delta)
    """
    # CREATE THE RANDOM GENERATOR
    rng = np.random.default_rng(seed_in)
    # COLLECT THE ROW COUNT
    row_count = len(eligible_decision_ts_series_in)
    # RETURN THE DECISION DATAFRAME
    return pd.DataFrame({"decision_ts": eligible_decision_ts_series_in.to_numpy(),
                         "buy_flag": rng.random(row_count) < buy_probability_in,
                         "delta": rng.choice(np.asarray(delta_list_in, dtype=float), size=row_count)})

# FUNCTION: GET FIXED-TIME ENTRY DECISIONS
def get_fixed_time_decision_pdf(eligible_decision_ts_series_in, delta_float_in=exp_config.FIXED_TIME_BASELINE_DELTA,
                                decision_time_str_in=exp_config.FIXED_TIME_BASELINE_DECISION_TIME_STR):
    """
    Builds the fixed-time baseline: buy every session at the same decision time (default 09:59 -> 10:00 open) with a
    fixed delta, whenever no position is open.

    Args:
        eligible_decision_ts_series_in (pd.Series): Eligible decision timestamps of the window
        delta_float_in (float): Fixed delta
        decision_time_str_in (str): Decision time 'HH:MM'

    Returns:
        pd.DataFrame: Decision DataFrame (decision_ts, buy_flag, delta)
    """
    # COLLECT THE DECISION TIMES
    decision_ts_series = pd.Series(eligible_decision_ts_series_in.to_numpy())
    # RETURN THE DECISION DATAFRAME
    return pd.DataFrame({"decision_ts": decision_ts_series,
                         "buy_flag": decision_ts_series.dt.strftime("%H:%M") == decision_time_str_in,
                         "delta": float(delta_float_in)})
