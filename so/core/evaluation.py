import pandas as pd
import numpy as np
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

Honest reporting (added 2026-10-05 after that day's audit; the audit document was deleted on 2026-10-22):
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


# FUNCTION: ROLLING CALENDAR-MONTH WINDOWS OF TOTAL RETURN
def get_rolling_month_window_pdf(strategy_return_pdf_in, buy_hold_return_pdf_in, window_months_in=12, step_months_in=1):
    """
    One row per rolling block of window_months_in calendar months, stepped by step_months_in. Each block's returns
    are the chained daily returns that fall in those months. Ahead means the strategy's total return is strictly
    above buy-and-hold's. Months with no sessions are omitted (the remaining months stay in calendar order).

    Args:
        strategy_return_pdf_in (pd.DataFrame): date, daily_return
        buy_hold_return_pdf_in (pd.DataFrame): date, daily_return, same dates
        window_months_in (int): Block length in calendar months
        step_months_in (int): Step between block starts

    Returns:
        pd.DataFrame: start_month, end_month, strategy_return, buy_hold_return, excess_return, ahead_bool
    """
    # ALIGN THE TWO SERIES ON THE DATE
    merged_pdf = strategy_return_pdf_in.merge(buy_hold_return_pdf_in, on="date", suffixes=("_strategy", "_buy_hold"))
    if len(merged_pdf) != len(strategy_return_pdf_in) or len(merged_pdf) != len(buy_hold_return_pdf_in):
        raise ValueError("strategy and buy-and-hold dates differ.")
    merged_pdf = merged_pdf.sort_values("date").reset_index(drop=True)
    merged_pdf["month"] = pd.to_datetime(merged_pdf["date"]).dt.to_period("M")
    month_pdf = merged_pdf.groupby("month", sort=True).agg(
        strategy_factor=("daily_return_strategy", lambda s: float(np.prod(1.0 + s))),
        buy_hold_factor=("daily_return_buy_hold", lambda s: float(np.prod(1.0 + s))),
    )
    window_int, step_int = int(window_months_in), int(step_months_in)
    if window_int < 1 or step_int < 1:
        raise ValueError("window_months_in and step_months_in must be at least 1.")
    row_dict_list = []
    month_count = int(len(month_pdf))
    for start_idx in range(0, month_count - window_int + 1, step_int):
        end_idx = start_idx + window_int
        block_pdf = month_pdf.iloc[start_idx:end_idx]
        strategy_return = float(block_pdf["strategy_factor"].prod() - 1.0)
        buy_hold_return = float(block_pdf["buy_hold_factor"].prod() - 1.0)
        row_dict_list.append({"start_month": str(month_pdf.index[start_idx]), "end_month": str(month_pdf.index[end_idx - 1]),
                              "strategy_return": strategy_return, "buy_hold_return": buy_hold_return,
                              "excess_return": strategy_return - buy_hold_return,
                              "ahead_bool": bool(strategy_return > buy_hold_return)})
    return pd.DataFrame(row_dict_list)


