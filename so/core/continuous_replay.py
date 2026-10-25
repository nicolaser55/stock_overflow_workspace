import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION (CAPITAL, BOOTSTRAP, SEED)
from so import config

"""
Continuous Path Helpers (used by the runner)

    1. Replay periods: the validation quarters of a walk-forward schedule made NON-OVERLAPPING. Period f runs from fold
       f's validation start to the session before fold f + 1's validation start; the last period ends at its
       validation end. The periods tile the span, so the period returns of a path chain exactly to its total return.
    2. Prior-only mapping: the candidate selected at period f governs period f + 1 only.
    3. Period returns of a continuous daily equity path.
    4. The annualized log excess return over buy-and-hold with a circular block bootstrap of calendar months (blocks of
       several months keep the dependence that long exits create).

Log excess return: log(strategy growth) - log(buy-and-hold growth); per year it is the difference of the two
continuously compounded growth rates, and it adds up over months (unlike the difference of total compounded returns).
"""

"""
Replay Window And Periods
"""


# FUNCTION: GET THE NON-OVERLAPPING REPLAY PERIODS OF A WALK-FORWARD SCHEDULE
def get_replay_period_pdf(fold_pdf_in, session_date_list_in):
    """
    Turns the validation quarters of a schedule into consecutive, non-overlapping periods that tile the replay span.

    Args:
        fold_pdf_in (pd.DataFrame): Walk-forward schedule (fold_id, valid_start, valid_end)
        session_date_list_in (list[datetime.date]): Session dates of the data

    Returns:
        pd.DataFrame: period_id (= fold_id), period_start, period_end, session_count, valid_start, valid_end
    """
    # SORT THE FOLDS AND CONVERT THE SESSION DATES
    fold_pdf = fold_pdf_in.sort_values("fold_id").reset_index(drop=True)
    session_date_arr = np.array(session_date_list_in)
    # LIST TO HOLD THE PERIODS
    period_dict_list = []
    # ITERATE OVER THE FOLDS
    for row_idx, fold_row in fold_pdf.iterrows():
        # DEFINE THE PERIOD START (FIRST SESSION ON OR AFTER THE VALIDATION START)
        start_date = pd.to_datetime(fold_row["valid_start"]).date()
        # DEFINE THE PERIOD END (SESSION BEFORE THE NEXT VALIDATION START, OR THE LAST VALIDATION END)
        if row_idx < len(fold_pdf) - 1:
            next_start_date = pd.to_datetime(fold_pdf.loc[row_idx + 1, "valid_start"]).date()
            in_period_arr = (session_date_arr >= start_date) & (session_date_arr < next_start_date)
        else:
            in_period_arr = (session_date_arr >= start_date) & (session_date_arr <= pd.to_datetime(fold_row["valid_end"]).date())
        # COLLECT THE PERIOD SESSIONS
        period_date_arr = session_date_arr[in_period_arr]
        # APPEND THE PERIOD (EMPTY PERIODS ARE SKIPPED)
        if len(period_date_arr):
            period_dict_list.append({"period_id": int(fold_row["fold_id"]), "period_start": period_date_arr[0], "period_end": period_date_arr[-1],
                                     "session_count": int(len(period_date_arr)), "valid_start": fold_row["valid_start"], "valid_end": fold_row["valid_end"]})
    # RETURN THE PERIODS
    return pd.DataFrame(period_dict_list)

"""
Simulation
"""


# FUNCTION: GET THE PRIOR-ONLY CANDIDATE OF EVERY PERIOD
def get_prior_only_period_candidate_dict(selection_pdf_in, period_pdf_in, candidate_idx_col_str_in):
    """
    The candidate selected at period f (selection row with fold_id = f, e.g. from so.core.evaluation.
    get_pooled_selection_pdf on period scores) governs the NEXT period of period_pdf_in only.

    Args:
        selection_pdf_in (pd.DataFrame): One selected row per period (fold_id = period_id, the candidate index column)
        period_pdf_in (pd.DataFrame): Output of get_replay_period_pdf
        candidate_idx_col_str_in (str): Column of selection_pdf_in holding the candidate index

    Returns:
        dict: period_id -> candidate index (the first period has none)
    """
    # COLLECT THE PERIOD ORDER
    period_id_list = period_pdf_in.sort_values("period_id")["period_id"].astype(int).tolist()
    next_period_dict = dict(zip(period_id_list[:-1], period_id_list[1:]))
    # RETURN THE NEXT PERIOD OF EVERY SELECTION
    return {next_period_dict[int(row["fold_id"])]: int(row[candidate_idx_col_str_in]) for _, row in selection_pdf_in.iterrows() if int(row["fold_id"]) in next_period_dict}


"""
Period Returns And Episode Scorecard
"""

# FUNCTION: GET THE RETURN OF A CONTINUOUS PATH IN EVERY PERIOD
def get_period_return_pdf(daily_equity_pdf_in, period_pdf_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Cuts a continuous daily equity curve into periods: return = equity at the period's last session / equity at the last
    session before the period (the initial capital for the first session of the curve) - 1.

    Args:
        daily_equity_pdf_in (pd.DataFrame): Daily equity of a continuous path (date, equity, in_position)
        period_pdf_in (pd.DataFrame): Output of get_replay_period_pdf
        initial_capital_in (float): Equity before the first session of the curve

    Returns:
        pd.DataFrame: period_id, period_start, period_end, session_count, total_return, in_market_pct
    """
    # COLLECT THE ARRAYS (THE LAST SESSION OF THE CURVE IS EXCLUDED FROM THE TIME IN THE MARKET: EVERY POSITION IS SOLD AT ITS CLOSE)
    date_arr = np.array(daily_equity_pdf_in["date"].tolist())
    equity_arr = daily_equity_pdf_in["equity"].to_numpy(dtype=float)
    in_position_arr = daily_equity_pdf_in["in_position"].to_numpy(dtype=bool)
    counted_arr = np.arange(len(date_arr)) < len(date_arr) - 1
    # LIST TO HOLD THE PERIOD ROWS
    row_dict_list = []
    # ITERATE OVER THE PERIODS
    for _, period_row in period_pdf_in.iterrows():
        # COLLECT THE PERIOD SESSIONS OF THE CURVE
        position_arr = np.flatnonzero((date_arr >= period_row["period_start"]) & (date_arr <= period_row["period_end"]))
        # SKIP A PERIOD OUTSIDE THE CURVE
        if len(position_arr) == 0:
            continue
        # CALCULATE THE START AND END EQUITY
        start_equity = equity_arr[position_arr[0] - 1] if position_arr[0] > 0 else float(initial_capital_in)
        end_equity = equity_arr[position_arr[-1]]
        # CALCULATE THE TIME IN THE MARKET
        counted_position_arr = position_arr[counted_arr[position_arr]]
        in_market_pct = float(in_position_arr[counted_position_arr].mean()) if len(counted_position_arr) else np.nan
        # APPEND THE ROW
        row_dict_list.append({"period_id": int(period_row["period_id"]), "period_start": period_row["period_start"], "period_end": period_row["period_end"],
                              "session_count": int(len(position_arr)), "total_return": float(end_equity / start_equity - 1), "in_market_pct": in_market_pct})
    # RETURN THE ROWS
    return pd.DataFrame(row_dict_list)


"""
Statistics
"""

# FUNCTION: GET THE ANNUALIZED LOG EXCESS RETURN WITH A CIRCULAR BLOCK BOOTSTRAP OF MONTHS
def get_log_excess_bootstrap_dict(strategy_return_pdf_in, buy_hold_return_pdf_in, block_month_count_in,
                                  iteration_count_in=config.BOOTSTRAP_ITERATION_COUNT,
                                  confidence_level_in=config.CONFIDENCE_LEVEL, seed_in=config.RANDOM_SEED):
    """
    Annualized log excess return = 12 x the mean monthly log excess return, where the monthly log excess return is
    log(strategy growth of the month) - log(buy-and-hold growth of the month). Interval: circular block bootstrap of
    calendar months (blocks of block_month_count_in consecutive months, wrapped at the end), percentile interval.

    Args:
        strategy_return_pdf_in, buy_hold_return_pdf_in (pd.DataFrame): Daily returns (date, daily_return), same dates
            (outputs of so.core.evaluation.get_chained_daily_return_pdf)
        block_month_count_in (int): Months per block (1 = months resampled independently)
        iteration_count_in (int): Bootstrap iterations
        confidence_level_in (float): Two-sided confidence level
        seed_in (int): Random seed

    Returns:
        dict: annualized_log_excess, annualized_excess_factor_pct (exp(annualized log excess) - 1), ci_low, ci_high
              (annualized log excess), month_count, block_month_count, supported (ci_low > 0)
    """
    # MERGE THE DAILY RETURNS AND GROUP THEM BY MONTH
    merged_pdf = strategy_return_pdf_in.merge(buy_hold_return_pdf_in, on="date", suffixes=("_strategy", "_buy_hold"))
    merged_pdf["month"] = pd.to_datetime(merged_pdf["date"]).dt.to_period("M")
    # CALCULATE THE MONTHLY LOG EXCESS RETURNS
    month_pdf = merged_pdf.groupby("month").agg(strategy_log=("daily_return_strategy", lambda s: float(np.log1p(s).sum())),
                                                buy_hold_log=("daily_return_buy_hold", lambda s: float(np.log1p(s).sum())))
    excess_arr = (month_pdf["strategy_log"] - month_pdf["buy_hold_log"]).to_numpy(dtype=float)
    month_count = len(excess_arr)
    # CALCULATE THE OBSERVED ANNUALIZED LOG EXCESS
    annualized_log_excess = float(12 * excess_arr.mean()) if month_count else np.nan
    # DRAW THE BLOCK STARTS AND BUILD THE RESAMPLED MONTH INDEXES (CIRCULAR, TRUNCATED TO THE SAMPLE LENGTH)
    rng = np.random.default_rng(seed_in)
    block_count = int(np.ceil(month_count / block_month_count_in))
    start_mat = rng.integers(0, month_count, size=(iteration_count_in, block_count))
    sample_idx_mat = ((start_mat[:, :, None] + np.arange(block_month_count_in)[None, None, :]) % month_count).reshape(iteration_count_in, -1)[:, :month_count]
    # CALCULATE THE RESAMPLED ANNUALIZED LOG EXCESS AND THE INTERVAL
    boot_arr = 12 * excess_arr[sample_idx_mat].mean(axis=1)
    ci_low, ci_high = np.percentile(boot_arr, [100 * (1 - confidence_level_in) / 2, 100 * (1 + confidence_level_in) / 2])
    # RETURN THE DICTIONARY
    return {"annualized_log_excess": annualized_log_excess, "annualized_excess_factor_pct": float(np.expm1(annualized_log_excess)),
            "ci_low": float(ci_low), "ci_high": float(ci_high), "month_count": int(month_count),
            "block_month_count": int(block_month_count_in), "supported": bool(ci_low > 0)}

