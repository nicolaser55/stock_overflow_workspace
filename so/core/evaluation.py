import pandas as pd
import numpy as np
from scipy.stats import binomtest
# IMPORT THE SHARED CONFIGURATION (CAPITAL, BOOTSTRAP, MINIMUM DETECTABLE EFFECT)
from so import config

"""
Evaluation And Honest Reporting (shared by every walk-forward experiment)

Success criteria (decided by Nicolas, 2026-10-04; the same for every experiment unless its protocol says otherwise):
    Primary      total return after all costs, chained over the evaluated windows, ABOVE buy-and-hold over the same windows
    Comparable   strategy total return >= 90% of buy-and-hold's (for a negative buy-and-hold: >= B&H - 10% of its size)
    Secondary    a higher Sharpe ratio OR a smaller maximum drawdown (either is enough; Nicolas, 2026-10-05), counted only at
                 a comparable return; both flags are also reported separately
    Information  the strategy must also beat its uninformed baselines (same rule with random / fixed choices); otherwise
                 the rule, not the information, does the work

Honest reporting (added 2026-10-05 after the audit, docs/history/AUDIT_2026-10-05.md):
    - Prior-only selection: the candidate chosen at fold f (with the experiment's selection rule, using only validation
      quarters up to fold f) is evaluated on the validation quarter of fold f+1. Chained over the folds, this is the
      honest validation estimate. The best candidate chosen after the fact is reported too, but it is optimistic.
    - The prior-only path is also run against the uninformed baselines on the same quarters, so "does the information
      help?" is answered on validation, before any test window is opened.
    - Time in the market is reported, because being out of the market costs drift (SPY's 20-session up-rate is ~66%).
    - The minimum detectable effect (MDE): the true mean excess return per quarter that a two-sided 5% test on the
      quarterly excess returns would detect with 80% power, 2.8 x SD / sqrt(n). With ~44 quarters of SPY it is several
      percentage points per year, so "not statistically supported" is the expected wording for any realistic edge.
"""


"""
Selection
"""

# FUNCTION: ADD THE POOLED SELECTION SCORE AND PICK ONE CANDIDATE PER FOLD
def get_pooled_selection_pdf(candidate_pdf_in, key_col_str_list_in, score_col_str_in, pooled_quarter_count_in, tie_break_list_in):
    """
    Scores every candidate of fold f by the mean of score_col_str_in for the same candidate over folds
    f - pooled_quarter_count_in + 1 .. f (fewer for the first folds) and selects the best candidate per fold.
    With pooled_quarter_count_in = 1 this is plain single-quarter selection. Scores within NUMERIC_TOLERANCE of the
    fold's best pooled score are tied, and tie_break_list_in then decides. The stored pooled score is not rounded.

    Args:
        candidate_pdf_in (pd.DataFrame): One row per (fold_id, candidate) with the score column
        key_col_str_list_in (list[str]): Columns that identify a candidate (e.g. ["train_window", "stop_k", "threshold_offset"])
        score_col_str_in (str): Validation metric to maximize (e.g. "valid_excess_return")
        pooled_quarter_count_in (int): Number of validation quarters pooled (consecutive fold ids required)
        tie_break_list_in (list[tuple[str, bool]]): Tie-break columns in order, with ascending flags,
            e.g. [("stop_k", False), ("threshold_offset", False)]

    Returns:
        pd.DataFrame: One selected row per fold (with pooled_score and pooled_quarter_count)
    """
    # SORT BY CANDIDATE AND FOLD
    candidate_pdf = candidate_pdf_in.sort_values(list(key_col_str_list_in) + ["fold_id"]).copy()
    # CALCULATE THE ROLLING MEAN AND COUNT OVER THE LAST FOLDS OF THE SAME CANDIDATE
    grouped = candidate_pdf.groupby(list(key_col_str_list_in))[score_col_str_in]
    candidate_pdf["pooled_score"] = grouped.transform(lambda s: s.rolling(pooled_quarter_count_in, min_periods=1).mean())
    candidate_pdf["pooled_quarter_count"] = grouped.transform(lambda s: s.rolling(pooled_quarter_count_in, min_periods=1).count()).astype(int)
    # SCORES WITHIN NUMERIC_TOLERANCE OF THAT FOLD'S BEST SCORE ARE TIED. THE STORED POOLED SCORE STAYS EXACT.
    best_score_series = candidate_pdf.groupby("fold_id")["pooled_score"].transform("max")
    within_tolerance_series = (best_score_series - candidate_pdf["pooled_score"]) <= float(config.NUMERIC_TOLERANCE)
    candidate_pdf["_selection_score"] = candidate_pdf["pooled_score"].where(~within_tolerance_series, best_score_series)
    # SORT BY FOLD, THE TIED SCORE (DESCENDING) AND THE TIE-BREAK COLUMNS
    sort_col_list = ["fold_id", "_selection_score"] + [col for col, _ in tie_break_list_in]
    ascending_list = [True, False] + [ascending for _, ascending in tie_break_list_in]
    candidate_pdf = candidate_pdf.sort_values(sort_col_list, ascending=ascending_list)
    # RETURN THE BEST CANDIDATE PER FOLD
    return candidate_pdf.groupby("fold_id").head(1).drop(columns=["_selection_score"]).reset_index(drop=True)


# FUNCTION: FORMAT ONE NUMBER FOR A REPORT OR A SUMMARY PRINT
def get_report_float_str(value_in):
    """
    Shows a number with REPORT_DECIMALS decimal places. The string is for display. Calculations keep the original value.

    Args:
        value_in (float): A return, an excess, or another reported number

    Returns:
        str: The display text
    """
    # FORMAT AT PRINT TIME ONLY
    return f"{float(value_in):.{config.REPORT_DECIMALS}f}"


# FUNCTION: COMPARE TWO SERIES AT THE NUMERIC TOLERANCE AND REPORT THE LARGEST GAP
def get_tolerance_comparison_dict(left_value_list_in, right_value_list_in):
    """
    Counts pairs whose absolute difference is at most NUMERIC_TOLERANCE, and reports the maximum absolute difference.

    Args:
        left_value_list_in (list[float]): Left values, full precision
        right_value_list_in (list[float]): Right values, full precision

    Returns:
        dict: match_count, row_count, max_abs_diff
    """
    # THE DIFFERENCE IS NOT ROUNDED BEFORE THE COMPARISON
    diff_arr = np.abs(np.asarray(left_value_list_in, dtype=float) - np.asarray(right_value_list_in, dtype=float))
    max_abs_diff = float(diff_arr.max()) if diff_arr.size else float("nan")
    return {"match_count": int(np.sum(diff_arr <= float(config.NUMERIC_TOLERANCE))), "row_count": int(diff_arr.size), "max_abs_diff": max_abs_diff}

# FUNCTION: EVALUATE EACH FOLD'S SELECTION ON THE NEXT FOLD'S VALIDATION QUARTER
def get_prior_only_pdf(candidate_pdf_in, selection_pdf_in, key_col_str_list_in):
    """
    Prior-only selection: the candidate selected at fold f is evaluated on the validation quarter of fold f + 1, where it
    was not used for the choice. Every column of the evaluated candidate row is kept.

    Args:
        candidate_pdf_in (pd.DataFrame): One row per (fold_id, candidate) with the validation metrics
        selection_pdf_in (pd.DataFrame): Output of get_pooled_selection_pdf
        key_col_str_list_in (list[str]): Candidate key columns

    Returns:
        pd.DataFrame: One row per evaluated fold (fold_id = the evaluated fold, selected_at_fold_id = the choosing fold)
    """
    # SHIFT EVERY SELECTION TO THE NEXT FOLD
    next_pdf = selection_pdf_in[list(key_col_str_list_in) + ["fold_id"]].rename(columns={"fold_id": "selected_at_fold_id"})
    next_pdf["fold_id"] = next_pdf["selected_at_fold_id"] + 1
    # COLLECT THE NEXT FOLD'S ROW OF THE SELECTED CANDIDATE
    prior_only_pdf = next_pdf.merge(candidate_pdf_in, on=list(key_col_str_list_in) + ["fold_id"], how="inner")
    # RETURN THE ROWS IN FOLD ORDER
    return prior_only_pdf.sort_values("fold_id").reset_index(drop=True)

"""
Summaries
"""

# FUNCTION: GET THE MINIMUM DETECTABLE EFFECT
def get_mde_float(std_float_in, count_int_in, z_factor_in=config.MDE_Z_FACTOR):
    """
    Minimum detectable effect of a mean: the true mean that a two-sided 5% test detects with 80% power.

    Args:
        std_float_in (float): Standard deviation of the observations
        count_int_in (int): Number of observations
        z_factor_in (float): z(0.975) + z(0.80)

    Returns:
        float: Minimum detectable mean (NaN with fewer than 2 observations)
    """
    # RETURN THE MDE
    return float(z_factor_in * std_float_in / np.sqrt(count_int_in)) if count_int_in > 1 and np.isfinite(std_float_in) else np.nan

# FUNCTION: SUMMARIZE A SERIES OF WINDOW RETURNS AGAINST BUY-AND-HOLD
def get_window_return_summary_dict(return_arr_in, buy_hold_return_arr_in, windows_per_year_in=4):
    """
    Summarizes consecutive window returns (e.g. validation quarters) against buy-and-hold over the same windows.

    Args:
        return_arr_in (np.ndarray): Strategy total return per window
        buy_hold_return_arr_in (np.ndarray): Buy-and-hold total return per window
        windows_per_year_in (int): Windows per year (4 for quarters), for the yearly MDE

    Returns:
        dict: window_count, chained_return, chained_buy_hold_return, chained_excess_return, windows_beating_buy_hold,
              sign_test_p_value (one-sided), mean_excess_return, std_excess_return, t_stat, mde_per_window, mde_per_year
    """
    # CONVERT THE INPUTS
    return_arr, buy_hold_arr = np.asarray(return_arr_in, dtype=float), np.asarray(buy_hold_return_arr_in, dtype=float)
    excess_arr = return_arr - buy_hold_arr
    window_count = int(len(excess_arr))
    # CALCULATE THE CHAINED RETURNS
    chained_return, chained_buy_hold_return = float(np.prod(1 + return_arr) - 1), float(np.prod(1 + buy_hold_arr) - 1)
    # COUNT THE WINDOWS BEATING BUY AND HOLD
    beat_count = int((excess_arr > 0).sum())
    # CALCULATE THE MEAN, SD, t AND MDE OF THE EXCESS RETURN
    std_excess = float(excess_arr.std(ddof=1)) if window_count > 1 else np.nan
    mde = get_mde_float(std_excess, window_count)
    # RETURN THE SUMMARY
    return {"window_count": window_count, "chained_return": chained_return, "chained_buy_hold_return": chained_buy_hold_return,
            "chained_excess_return": chained_return - chained_buy_hold_return, "windows_beating_buy_hold": beat_count,
            "sign_test_p_value": float(binomtest(beat_count, window_count, 0.5, alternative="greater").pvalue) if window_count > 0 else np.nan,
            "mean_excess_return": float(excess_arr.mean()) if window_count else np.nan, "std_excess_return": std_excess,
            "t_stat": float(excess_arr.mean() / (std_excess / np.sqrt(window_count))) if window_count > 1 and std_excess > 0 else np.nan,
            "mde_per_window": mde, "mde_per_year": mde * windows_per_year_in if np.isfinite(mde) else np.nan}

# FUNCTION: SUMMARIZE EVERY CANDIDATE OVER THE VALIDATION QUARTERS
def get_candidate_summary_pdf(candidate_pdf_in, key_col_str_list_in, mean_col_str_list_in=None):
    """
    Chains every candidate's validation quarters (after-the-fact view: optimistic for the best candidate).

    Args:
        candidate_pdf_in (pd.DataFrame): One row per (fold_id, candidate) with valid_total_return and valid_buy_hold_total_return
        key_col_str_list_in (list[str]): Candidate key columns
        mean_col_str_list_in (list[str] | None): Extra columns averaged over the quarters (e.g. time in cash)

    Returns:
        pd.DataFrame: One row per candidate with get_window_return_summary_dict and the extra means, best first
    """
    # LIST TO HOLD THE ROWS
    row_dict_list = []
    # ITERATE OVER THE CANDIDATES
    for key_tuple, group_pdf in candidate_pdf_in.sort_values("fold_id").groupby(list(key_col_str_list_in)):
        # SUMMARIZE THE CANDIDATE
        summary_dict = get_window_return_summary_dict(group_pdf["valid_total_return"].to_numpy(), group_pdf["valid_buy_hold_total_return"].to_numpy())
        # ADD THE EXTRA MEANS
        mean_dict = {f"mean_{col}": float(group_pdf[col].mean()) for col in (mean_col_str_list_in or []) if col in group_pdf.columns}
        # APPEND THE ROW
        row_dict_list.append({**dict(zip(key_col_str_list_in, key_tuple if isinstance(key_tuple, tuple) else (key_tuple,))), **summary_dict, **mean_dict})
    # RETURN THE SUMMARY (BEST CHAINED RETURN FIRST)
    return pd.DataFrame(row_dict_list).sort_values("chained_return", ascending=False).reset_index(drop=True)

# FUNCTION: SUMMARIZE THE BASELINES OF THE PRIOR-ONLY PATH
def get_baseline_summary_pdf(baseline_pdf_in, model_name_str_in="model", random_prefix_str_list_in=("random_",)):
    """
    Chains every baseline over the evaluated folds and compares the model with them (the information test).

    Args:
        baseline_pdf_in (pd.DataFrame): One row per (fold_id, baseline) with total_return
        model_name_str_in (str): Name of the model rows
        random_prefix_str_list_in (tuple[str]): Prefixes of the random baseline families (each family is summarized by the
            median of its chained runs and by the share of runs the model beats)

    Returns:
        pd.DataFrame: One row per baseline (or random family): chained_return, model_chained_return, model_beats, and for a
                      random family model_beats_random_run_share and random_run_count
    """
    # CHAIN EVERY BASELINE OVER THE FOLDS
    chained_series = baseline_pdf_in.sort_values("fold_id").groupby("baseline")["total_return"].apply(lambda s: float(np.prod(1 + s) - 1))
    model_chained_return = float(chained_series.get(model_name_str_in, np.nan))
    # DEFINE THE RANDOM RUN MASK
    random_mask = np.zeros(len(chained_series), dtype=bool)
    for prefix_str in random_prefix_str_list_in:
        random_mask |= chained_series.index.str.startswith(prefix_str)
    # BUILD THE ROWS OF THE NON-RANDOM BASELINES (THE MODEL ROW EXCLUDED)
    row_dict_list = [{"baseline": name, "chained_return": value} for name, value in chained_series[~random_mask & (chained_series.index != model_name_str_in)].items()]
    # ITERATE OVER THE RANDOM FAMILIES
    for prefix_str in random_prefix_str_list_in:
        # COLLECT THE CHAINED RUNS OF THE FAMILY
        random_arr = chained_series[chained_series.index.str.startswith(prefix_str)].to_numpy()
        # IF THE FAMILY HAS RUNS
        if len(random_arr):
            # ADD ONE ROW SUMMARIZING THE RUNS
            row_dict_list.append({"baseline": f"{prefix_str}* (median of runs)", "chained_return": float(np.median(random_arr)),
                                  "model_beats_random_run_share": float((random_arr < model_chained_return).mean()), "random_run_count": int(len(random_arr))})
    # CONVERT AND ADD THE MODEL COMPARISON
    summary_pdf = pd.DataFrame(row_dict_list)
    summary_pdf["model_chained_return"] = model_chained_return
    summary_pdf["model_beats"] = summary_pdf["chained_return"] < model_chained_return
    # RETURN THE SUMMARY
    return summary_pdf

"""
Chained Daily Returns, Bootstrap And Success Criteria
"""

# FUNCTION: GET THE CHAINED DAILY RETURNS OF CONSECUTIVE WINDOWS
def get_chained_daily_return_pdf(daily_equity_pdf_list_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Converts the daily equity of consecutive windows (each starting at initial_capital_in) into one daily return series.

    Args:
        daily_equity_pdf_list_in (list[pd.DataFrame]): Daily equity per window (date, equity), in chronological order
        initial_capital_in (float): Starting equity of every window

    Returns:
        pd.DataFrame: Columns date, daily_return
    """
    # LIST TO HOLD THE WINDOW RETURNS
    return_pdf_list = []
    # ITERATE OVER THE WINDOWS
    for daily_equity_pdf in daily_equity_pdf_list_in:
        # CALCULATE THE DAILY RETURNS (THE FIRST ONE IS RELATIVE TO THE STARTING CAPITAL)
        equity_arr = np.concatenate([[initial_capital_in], daily_equity_pdf["equity"].to_numpy(dtype=float)])
        return_pdf_list.append(pd.DataFrame({"date": daily_equity_pdf["date"].to_numpy(), "daily_return": equity_arr[1:] / equity_arr[:-1] - 1}))
    # RETURN THE CONCATENATED RETURNS
    return pd.concat(return_pdf_list, ignore_index=True) if return_pdf_list else pd.DataFrame(columns=["date", "daily_return"])

# FUNCTION: GET THE MONTHLY BLOCK BOOTSTRAP INTERVAL OF THE CHAINED EXCESS RETURN
def get_excess_return_bootstrap_dict(strategy_return_pdf_in, buy_hold_return_pdf_in,
                                     iteration_count_in=config.BOOTSTRAP_ITERATION_COUNT,
                                     confidence_level_in=config.CONFIDENCE_LEVEL, seed_in=config.RANDOM_SEED):
    """
    Resamples calendar months (strategy and buy-and-hold returns of the same month together) and recomputes the chained
    excess return (strategy total return - buy-and-hold total return) of each resample.

    Args:
        strategy_return_pdf_in, buy_hold_return_pdf_in (pd.DataFrame): Outputs of get_chained_daily_return_pdf (same dates)
        iteration_count_in (int): Bootstrap iterations
        confidence_level_in (float): Two-sided confidence level
        seed_in (int): Random seed

    Returns:
        dict: excess_return, ci_low, ci_high, month_count, supported (ci_low > 0)
    """
    # MERGE THE DAILY RETURNS
    merged_pdf = strategy_return_pdf_in.merge(buy_hold_return_pdf_in, on="date", suffixes=("_strategy", "_buy_hold"))
    merged_pdf["month"] = pd.to_datetime(merged_pdf["date"]).dt.to_period("M")
    # CALCULATE THE MONTHLY GROWTH FACTORS
    month_pdf = merged_pdf.groupby("month").agg(strategy_factor=("daily_return_strategy", lambda s: float(np.prod(1 + s))),
                                                buy_hold_factor=("daily_return_buy_hold", lambda s: float(np.prod(1 + s))))
    strategy_factor_arr, buy_hold_factor_arr = month_pdf["strategy_factor"].to_numpy(), month_pdf["buy_hold_factor"].to_numpy()
    # CALCULATE THE OBSERVED EXCESS RETURN
    excess_return = float(strategy_factor_arr.prod() - buy_hold_factor_arr.prod())
    # RESAMPLE THE MONTHS
    rng = np.random.default_rng(seed_in)
    sample_idx_mat = rng.integers(0, len(month_pdf), size=(iteration_count_in, len(month_pdf)))
    boot_excess_arr = np.prod(strategy_factor_arr[sample_idx_mat], axis=1) - np.prod(buy_hold_factor_arr[sample_idx_mat], axis=1)
    # CALCULATE THE INTERVAL
    ci_low, ci_high = np.percentile(boot_excess_arr, [100 * (1 - confidence_level_in) / 2, 100 * (1 + confidence_level_in) / 2])
    # RETURN THE DICTIONARY
    return {"excess_return": excess_return, "ci_low": float(ci_low), "ci_high": float(ci_high), "month_count": int(len(month_pdf)), "supported": bool(ci_low > 0)}

# FUNCTION: EVALUATE THE SUCCESS CRITERIA (PRIMARY, COMPARABLE RETURN, SECONDARY, BASELINES)
def get_success_criteria_dict(strategy_return_pdf_in, buy_hold_return_pdf_in, baseline_total_return_dict_in=None):
    """
    Applies the v2 success criteria to the chained test returns.

    Args:
        strategy_return_pdf_in, buy_hold_return_pdf_in (pd.DataFrame): Outputs of get_chained_daily_return_pdf
        baseline_total_return_dict_in (dict | None): Chained total return of each same-stop baseline (name -> return)

    Returns:
        dict: chained returns, Sharpe ratios, drawdowns, primary / comparable / secondary flags (secondary_success = Sharpe OR
              drawdown), baselines beaten
    """
    # FUNCTION: CHAINED METRICS OF A DAILY RETURN SERIES
    def chained_metric_dict(return_pdf):
        equity_arr = np.concatenate([[1.0], np.cumprod(1 + return_pdf["daily_return"].to_numpy(dtype=float))])
        daily_return_arr = return_pdf["daily_return"].to_numpy(dtype=float)
        std = daily_return_arr.std(ddof=1)
        return {"total_return": float(equity_arr[-1] - 1),
                "sharpe_ratio": float(daily_return_arr.mean() / std * np.sqrt(config.TRADING_DAYS_PER_YEAR)) if std > 0 else np.nan,
                "max_drawdown": float((equity_arr / np.maximum.accumulate(equity_arr) - 1).min())}
    # CALCULATE THE CHAINED METRICS
    strategy_dict, buy_hold_dict = chained_metric_dict(strategy_return_pdf_in), chained_metric_dict(buy_hold_return_pdf_in)
    # PRIMARY CRITERION
    primary_bool = strategy_dict["total_return"] > buy_hold_dict["total_return"]
    # COMPARABLE RETURN (>= 90% OF BUY-AND-HOLD; FOR A NEGATIVE BUY-AND-HOLD: >= BUY-AND-HOLD - 10% OF ITS SIZE)
    buy_hold_return = buy_hold_dict["total_return"]
    comparable_floor = 0.9 * buy_hold_return if buy_hold_return >= 0 else buy_hold_return - 0.1 * abs(buy_hold_return)
    comparable_bool = strategy_dict["total_return"] >= comparable_floor
    # SECONDARY CRITERIA (ONLY COUNTED AT COMPARABLE RETURN)
    sharpe_bool = comparable_bool and strategy_dict["sharpe_ratio"] > buy_hold_dict["sharpe_ratio"]
    drawdown_bool = comparable_bool and strategy_dict["max_drawdown"] > buy_hold_dict["max_drawdown"]
    # SECONDARY SUCCESS: EITHER IS ENOUGH (DECIDED BY NICOLAS, 2026-10-05; AUDIT F7)
    secondary_bool = sharpe_bool or drawdown_bool
    # BASELINES BEATEN ON THE PRIMARY METRIC
    baseline_dict = baseline_total_return_dict_in or {}
    beaten_dict = {name: bool(strategy_dict["total_return"] > value) for name, value in baseline_dict.items()}
    # RETURN THE DICTIONARY
    return {"strategy_total_return": strategy_dict["total_return"], "buy_hold_total_return": buy_hold_return,
            "strategy_sharpe_ratio": strategy_dict["sharpe_ratio"], "buy_hold_sharpe_ratio": buy_hold_dict["sharpe_ratio"],
            "strategy_max_drawdown": strategy_dict["max_drawdown"], "buy_hold_max_drawdown": buy_hold_dict["max_drawdown"],
            "primary_success": bool(primary_bool), "comparable_return": bool(comparable_bool), "comparable_floor": comparable_floor,
            "secondary_sharpe": bool(sharpe_bool), "secondary_drawdown": bool(drawdown_bool), "secondary_success": bool(secondary_bool),
            "baselines_beaten": beaten_dict, "all_baselines_beaten": bool(all(beaten_dict.values())) if beaten_dict else None}


"""
Performance Over Time (Nicolas, 2026-10-11; shared by development notebooks and the holdout report)
"""

# FUNCTION: ROLLING EXCESS RETURN OF ONE WINDOW LENGTH
def get_rolling_excess_return_arr(strategy_return_arr_in, buy_hold_return_arr_in, window_int_in):
    """
    Strategy total return minus buy-and-hold total return over each block of window_int_in sessions. Shorter prefixes
    are NaN.

    Args:
        strategy_return_arr_in (np.ndarray): Strategy daily returns
        buy_hold_return_arr_in (np.ndarray): Buy-and-hold daily returns
        window_int_in (int): Block length in sessions

    Returns:
        np.ndarray: One excess return per session
    """
    # EMPTY UNTIL A FULL BLOCK EXISTS
    excess_arr = np.full(len(strategy_return_arr_in), np.nan)
    window_int = int(window_int_in)
    for end_idx in range(window_int - 1, len(strategy_return_arr_in)):
        start_idx = end_idx - window_int + 1
        strategy_total = float(np.prod(1.0 + strategy_return_arr_in[start_idx:end_idx + 1]) - 1.0)
        buy_hold_total = float(np.prod(1.0 + buy_hold_return_arr_in[start_idx:end_idx + 1]) - 1.0)
        excess_arr[end_idx] = strategy_total - buy_hold_total
    return excess_arr

# FUNCTION: CUMULATIVE LOG EXCESS, ROLLING EXCESS AND DRAWDOWNS
def get_performance_over_time_pdf(strategy_daily_return_pdf_in, buy_hold_daily_return_pdf_in):
    """
    One row per session: the cumulative log excess (sum of log strategy return minus log buy-and-hold return), the
    rolling 63-session and 252-session excess return, and the drawdown of each equity curve. The quarter table is
    get_performance_quarter_pdf.

    Args:
        strategy_daily_return_pdf_in (pd.DataFrame): date, daily_return
        buy_hold_daily_return_pdf_in (pd.DataFrame): date, daily_return, same dates

    Returns:
        pd.DataFrame: One row per session
    """
    # ALIGN THE TWO SERIES ON THE DATE
    merged_pdf = strategy_daily_return_pdf_in.merge(buy_hold_daily_return_pdf_in, on="date", suffixes=("_strategy", "_buy_hold"))
    if len(merged_pdf) != len(strategy_daily_return_pdf_in) or len(merged_pdf) != len(buy_hold_daily_return_pdf_in):
        raise ValueError("strategy and buy-and-hold dates differ.")
    merged_pdf = merged_pdf.sort_values("date").reset_index(drop=True)
    strategy_arr = merged_pdf["daily_return_strategy"].to_numpy(dtype=float)
    buy_hold_arr = merged_pdf["daily_return_buy_hold"].to_numpy(dtype=float)
    # CUMULATIVE LOG EXCESS AND THE TWO EQUITY CURVES
    log_excess_arr = np.cumsum(np.log1p(strategy_arr) - np.log1p(buy_hold_arr))
    strategy_equity_arr = np.cumprod(1.0 + strategy_arr)
    buy_hold_equity_arr = np.cumprod(1.0 + buy_hold_arr)
    # RETURN THE SESSION TABLE
    return pd.DataFrame({
        "date": merged_pdf["date"].to_numpy(),
        "strategy_daily_return": strategy_arr,
        "buy_hold_daily_return": buy_hold_arr,
        "cumulative_log_excess": log_excess_arr,
        "rolling_63_excess_return": get_rolling_excess_return_arr(strategy_arr, buy_hold_arr, 63),
        "rolling_252_excess_return": get_rolling_excess_return_arr(strategy_arr, buy_hold_arr, 252),
        "strategy_drawdown": strategy_equity_arr / np.maximum.accumulate(strategy_equity_arr) - 1.0,
        "buy_hold_drawdown": buy_hold_equity_arr / np.maximum.accumulate(buy_hold_equity_arr) - 1.0,
    })

# FUNCTION: THE SAME PATH SUMMED BY CALENDAR QUARTER
def get_performance_quarter_pdf(strategy_daily_return_pdf_in, buy_hold_daily_return_pdf_in):
    """
    One row per calendar quarter: strategy return, buy-and-hold return, their difference, and the cumulative log
    excess at the quarter's last session.

    Args:
        strategy_daily_return_pdf_in (pd.DataFrame): date, daily_return
        buy_hold_daily_return_pdf_in (pd.DataFrame): date, daily_return

    Returns:
        pd.DataFrame: One row per quarter
    """
    # THE SESSION PATH, THEN THE QUARTER OF EACH DATE
    session_pdf = get_performance_over_time_pdf(strategy_daily_return_pdf_in, buy_hold_daily_return_pdf_in)
    session_pdf["quarter"] = pd.to_datetime(session_pdf["date"]).dt.to_period("Q").astype(str)
    row_dict_list = []
    for quarter_str, group_pdf in session_pdf.groupby("quarter", sort=True):
        strategy_return = float(np.prod(1.0 + group_pdf["strategy_daily_return"].to_numpy(dtype=float)) - 1.0)
        buy_hold_return = float(np.prod(1.0 + group_pdf["buy_hold_daily_return"].to_numpy(dtype=float)) - 1.0)
        row_dict_list.append({"quarter": quarter_str, "strategy_return": strategy_return, "buy_hold_return": buy_hold_return,
                              "excess_return": strategy_return - buy_hold_return,
                              "cumulative_log_excess": float(group_pdf["cumulative_log_excess"].iloc[-1])})
    return pd.DataFrame(row_dict_list)

# FUNCTION: TURNOVER, TRADES AND CANDIDATE SWITCHES
def get_turnover_switch_dict(weight_arr_in, trade_count_int_in, candidate_list_in):
    """
    Turnover per year is the sum of absolute weight changes, scaled by 252 / session count. A candidate switch is a
    change between two consecutive entries of candidate_list_in (one entry per session). The time share is the fraction
    of those entries each candidate occupies.

    Args:
        weight_arr_in (array-like): Weight at each session
        trade_count_int_in (int): Number of trades
        candidate_list_in (list): Candidate in force at each session

    Returns:
        dict: turnover_per_year, trade_count, candidate_switch_count, candidate_switches_per_year, candidate_time_share_dict
    """
    # THE WEIGHT CHANGES THAT ARE FINITE
    weight_arr = np.asarray(weight_arr_in, dtype=float)
    session_count = int(len(weight_arr))
    change_arr = np.diff(weight_arr) if session_count > 1 else np.array([])
    finite_change_arr = change_arr[np.isfinite(change_arr)] if len(change_arr) else change_arr
    turnover_sum = float(np.abs(finite_change_arr).sum()) if len(finite_change_arr) else 0.0
    year_scale = config.TRADING_DAYS_PER_YEAR / session_count if session_count else np.nan
    # SWITCHES ALONG THE CANDIDATE SEQUENCE
    candidate_list = list(candidate_list_in)
    switch_count = int(sum(candidate_list[idx] != candidate_list[idx - 1] for idx in range(1, len(candidate_list))))
    share_dict = {}
    for candidate in candidate_list:
        share_dict[candidate] = share_dict.get(candidate, 0) + 1
    if candidate_list:
        share_dict = {candidate: count / len(candidate_list) for candidate, count in share_dict.items()}
    # RETURN THE COUNTS
    return {"turnover_per_year": turnover_sum * year_scale if session_count else np.nan, "trade_count": int(trade_count_int_in),
            "candidate_switch_count": switch_count,
            "candidate_switches_per_year": switch_count * year_scale if session_count else np.nan,
            "candidate_time_share_dict": share_dict}

# FUNCTION: ROWS USED, SHARE PURGED, AND HOW FAR PREDICTIONS MOVED
def get_refit_report_dict(refit_log_pdf_in, prediction_pdf_in=None):
    """
    Average rows used, the average share of window rows purged for an unfinished label, and the average absolute move
    in the prediction between consecutive refits. prediction_move on the refit log is that move on the refit session's
    own features. When the column is absent, the move is the jump in prediction_pdf at each model change.

    Args:
        refit_log_pdf_in (pd.DataFrame): Refit log (rows_used, rows_purged, and optionally prediction_move)
        prediction_pdf_in (pd.DataFrame | None): session, prediction, model_id

    Returns:
        dict: mean_rows_used, mean_share_purged, mean_prediction_move
    """
    # AN EMPTY LOG HAS NOTHING TO AVERAGE
    if refit_log_pdf_in is None or len(refit_log_pdf_in) == 0:
        return {"mean_rows_used": np.nan, "mean_share_purged": np.nan, "mean_prediction_move": np.nan}
    used_arr = refit_log_pdf_in["rows_used"].to_numpy(dtype=float)
    purged_arr = refit_log_pdf_in["rows_purged"].to_numpy(dtype=float)
    denom_arr = used_arr + purged_arr
    share_arr = np.divide(purged_arr, denom_arr, out=np.full(len(denom_arr), np.nan), where=denom_arr > 0)
    # THE MOVE COLUMN WINS; OTHERWISE THE JUMP IN THE PREDICTION SERIES
    if "prediction_move" in refit_log_pdf_in.columns and np.isfinite(refit_log_pdf_in["prediction_move"].to_numpy(dtype=float)).any():
        move_float = float(np.nanmean(refit_log_pdf_in["prediction_move"].to_numpy(dtype=float)))
    elif prediction_pdf_in is not None and len(prediction_pdf_in) > 1 and "model_id" in prediction_pdf_in.columns:
        prediction_arr = prediction_pdf_in["prediction"].to_numpy(dtype=float)
        model_arr = prediction_pdf_in["model_id"].to_numpy()
        jump_list = [abs(float(prediction_arr[idx] - prediction_arr[idx - 1])) for idx in range(1, len(model_arr)) if model_arr[idx] != model_arr[idx - 1]]
        move_float = float(np.mean(jump_list)) if jump_list else np.nan
    else:
        move_float = np.nan
    return {"mean_rows_used": float(np.mean(used_arr)), "mean_share_purged": float(np.nanmean(share_arr)), "mean_prediction_move": move_float}
