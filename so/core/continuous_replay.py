import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION (CAPITAL, BOOTSTRAP, SEED)
from so import config
# IMPORT EXIT AND RE-ENTRY SIMULATION FUNCTIONS
from so.core.reentry_simulation import simulate_stop_reentry_dict
# IMPORT PERFORMANCE METRICS
from so.core.performance_metrics import get_sharpe_ratio, get_max_drawdown
# IMPORT THE EVALUATION FUNCTIONS (WINDOW SUMMARY, CHAINED DAILY RETURNS, SUCCESS CRITERIA)
from so.core.evaluation import get_window_return_summary_dict, get_chained_daily_return_pdf, get_success_criteria_dict

"""
Continuous Replay And Long-Holding Evaluation (roadmap Step 0, docs/RESEARCH_STATE_2026-10-06.md §6)

Why: exp02 and exp03 evaluated every 3-month validation quarter separately, starting invested and selling at the end of
each quarter, with a forced buy-back after 60 cash decisions. That design cannot test a strategy that stays out of the
market for months (a bear market) or that holds for years. The continuous replay runs ONE path over the whole
development span (the validation quarters, 2015-04-17 -> 2026-04-15), and the position carries across quarter
boundaries.

What this module adds (shared code, no trading rule of exp01-exp03 is changed):
    1. Continuous replay: so.core.reentry_simulation.simulate_stop_reentry_dict over one long window, behind a guard that
       refuses any window reaching the untouched data (the caller passes its start date, 2026-05-14). The optional cash
       cap (max_cash_sessions_in) is passed through: None = never forced, or a long cap such as 250 decisions.
    2. Replay periods: the validation quarters of a walk-forward schedule made NON-OVERLAPPING (the anchored schedule
       lets consecutive quarters overlap or leave gaps of a few sessions): period f runs from fold f's validation start
       to the session before fold f + 1's validation start; the last period ends at its validation end. The periods tile
       the replay span, so the period returns of a path chain exactly to its total return.
    3. Rule switching (prior-only selection on a continuous path): a candidate index per session; the exit signal and
       the re-entry rule of the session's candidate are used, while the position state carries over. With the pooled
       selection of so.core.evaluation, the candidate selected at period f governs period f + 1 only (prior-only).
    4. Episode scorecard: one row per exit (sale date and fill S, buy-back date and fill R, S / R, shares before and
       after, sessions out, reasons, buy-and-hold price change over the same time, the largest decline below the sale
       price while out, the round-trip cost).
    5. Readable statistics: the annualized log excess return over buy-and-hold with a circular block bootstrap of
       calendar months (blocks of several months keep the dependence that long exits create), the period (quarter)
       summary of so.core.evaluation, time in the market, and the success criteria.

Identity behind the scorecard: an episode that sells at S and buys back at R ends with about S / R times the shares (fees
and whole shares aside). Log excess return: log(strategy growth) - log(buy-and-hold growth); per year it is the
difference of the two continuously compounded growth rates, and it adds up over months (unlike the difference of total
compounded returns, which compounding stretches).
"""

"""
Replay Window And Periods
"""

# FUNCTION: CHECK THAT A REPLAY WINDOW STAYS BEFORE THE UNTOUCHED DATA
def check_replay_window_bool(date2_in, untouched_start_date_str_in):
    """
    Raises an error if the replay window reaches the untouched data (research-integrity.mdc, "Never" rule 1).

    Args:
        date2_in (datetime.date | str): Last session of the replay window
        untouched_start_date_str_in (str): First date that must never be read for evaluation (e.g. "2026-05-14")

    Returns:
        bool: True if the window is allowed
    """
    # IF THE WINDOW REACHES THE UNTOUCHED DATA
    if pd.to_datetime(date2_in).date() >= pd.to_datetime(untouched_start_date_str_in).date():
        # REFUSE THE WINDOW
        raise ValueError(f"replay window ends {date2_in}, on or after the untouched data start {untouched_start_date_str_in}")
    # RETURN TRUE
    return True

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

# FUNCTION: SIMULATE A CONTINUOUS REPLAY (ONE WINDOW, STATE CARRIED THROUGH THE WHOLE SPAN)
def simulate_continuous_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, untouched_start_date_str_in, **simulation_kwargs):
    """
    Runs so.core.reentry_simulation.simulate_stop_reentry_dict over one long window after checking the untouched-data
    guard. The window starts invested (10:00 open of its first session, as buy-and-hold) and sells an open position at
    its last close; in between, the state is never reset.

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        date1_in, date2_in (datetime.date | str): Replay bounds (inclusive)
        untouched_start_date_str_in (str): First date of the untouched data (the window must end before it)
        **simulation_kwargs: Arguments of simulate_stop_reentry_dict (volatility_arr_in is required; stop_k_in,
            reentry_func_in, reentry_reason_str_in, exit_signal_arr_in, max_cash_sessions_in, costs)

    Returns:
        dict: Output of simulate_stop_reentry_dict
    """
    # CHECK THE GUARD
    check_replay_window_bool(date2_in, untouched_start_date_str_in)
    # RETURN THE SIMULATION
    return simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, **simulation_kwargs)

# FUNCTION: GET THE CANDIDATE ASSIGNMENT OF EVERY SESSION
def get_session_assignment_arr(session_date_list_in, period_pdf_in, period_candidate_idx_dict_in):
    """
    Assigns a candidate index to every session of the periods that have one (-1 elsewhere).

    Args:
        session_date_list_in (list[datetime.date]): Session dates of the data
        period_pdf_in (pd.DataFrame): Output of get_replay_period_pdf
        period_candidate_idx_dict_in (dict): period_id -> candidate index governing that period

    Returns:
        np.ndarray: Candidate index per session position (-1 = no candidate)
    """
    # CONVERT THE SESSION DATES AND DEFINE THE ASSIGNMENT
    session_date_arr = np.array(session_date_list_in)
    assignment_arr = np.full(len(session_date_arr), -1, dtype=int)
    # ITERATE OVER THE PERIODS
    for _, period_row in period_pdf_in.iterrows():
        # IF THE PERIOD HAS A CANDIDATE
        if int(period_row["period_id"]) in period_candidate_idx_dict_in:
            # ASSIGN IT TO THE PERIOD SESSIONS
            in_period_arr = (session_date_arr >= period_row["period_start"]) & (session_date_arr <= period_row["period_end"])
            assignment_arr[in_period_arr] = int(period_candidate_idx_dict_in[int(period_row["period_id"])])
    # RETURN THE ASSIGNMENT
    return assignment_arr

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

# FUNCTION: GET THE SWITCHING EXIT SIGNAL AND RE-ENTRY RULE
def get_switching_rule_dict(assignment_arr_in, exit_signal_arr_list_in, reentry_func_list_in):
    """
    Combines several candidates into one rule: on every session, the exit signal and the re-entry rule of the candidate
    assigned to that session are used (a session with no candidate never exits and never re-enters).

    Args:
        assignment_arr_in (np.ndarray): Candidate index per session position (output of get_session_assignment_arr)
        exit_signal_arr_list_in (list[np.ndarray]): Exit signal per candidate (bool per session position)
        reentry_func_list_in (list[function]): Re-entry rule per candidate f(session_idx, cash_session_count, episode_dict)

    Returns:
        dict: exit_signal_arr (bool per session position), reentry_func (rule)
    """
    # BUILD THE EXIT SIGNAL OF THE ASSIGNED CANDIDATES
    exit_signal_arr = np.zeros(len(assignment_arr_in), dtype=bool)
    for candidate_idx, candidate_exit_arr in enumerate(exit_signal_arr_list_in):
        candidate_mask_arr = assignment_arr_in == candidate_idx
        exit_signal_arr[candidate_mask_arr] = np.asarray(candidate_exit_arr, dtype=bool)[candidate_mask_arr]
    # FUNCTION: THE RE-ENTRY RULE OF THE ASSIGNED CANDIDATE
    def reentry_func(session_idx, cash_session_count, episode_dict):
        candidate_idx = int(assignment_arr_in[session_idx])
        return bool(reentry_func_list_in[candidate_idx](session_idx, cash_session_count, episode_dict)) if candidate_idx >= 0 else False
    # RETURN THE RULE
    return {"exit_signal_arr": exit_signal_arr, "reentry_func": reentry_func}

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

# FUNCTION: GET THE EPISODE SCORECARD OF A SIMULATION
def get_episode_scorecard_pdf(simulation_dict_in, ohlcv_array_dict_in):
    """
    One row per out-of-market episode of a simulate_stop_reentry_dict output, with everything needed to judge it.

    Columns:
        exit_date, exit_fill_price (S), exit_reason, reentry_date, reentry_fill_price (R), reentry_reason
        s_over_r                 S / R (> 1 = bought back lower)
        log_share_gain           log(S / R)
        shares_before, shares_after, share_ratio (shares_after / shares_before; NaN for an episode open at the end)
        sessions_out             cash decisions of the episode
        buy_hold_return_out      raw price change of SPY from the sale bar to the buy-back bar (what holding earned)
        max_decline_out_pct      lowest low while out / raw sale price - 1, capped at 0 (the decline that was avoided)
        cost_paid                slippage and fees of the round trip (dollars), cost_paid_pct (of the sale value)
        open_at_end              True if the episode was still open at the end (valued at the last close, no cost)

    Args:
        simulation_dict_in (dict): Output of so.core.reentry_simulation.simulate_stop_reentry_dict
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict

    Returns:
        pd.DataFrame: The scorecard (empty if there was no exit)
    """
    # COLLECT THE EPISODES AND THE TRANSACTIONS
    episode_pdf, transaction_pdf = simulation_dict_in["episode_pdf"], simulation_dict_in["transaction_pdf"]
    # IF THERE IS NO EPISODE
    if episode_pdf is None or episode_pdf.empty:
        # RETURN AN EMPTY SCORECARD
        return pd.DataFrame()
    # COLLECT THE ARRAYS AND THE BAR INDEX OF EVERY TIMESTAMP
    timestamp_index, low_arr, close_arr = ohlcv_array_dict_in["timestamp_index"], ohlcv_array_dict_in["low_arr"], ohlcv_array_dict_in["close_arr"]
    # INDEX THE TRANSACTIONS BY SALE AND PURCHASE TIMESTAMP
    sell_dict = {row["sell_ts"]: row for _, row in transaction_pdf.iterrows()}
    buy_dict = {row["buy_ts"]: row for _, row in transaction_pdf.iterrows()}
    # LIST TO HOLD THE ROWS
    row_dict_list = []
    # ITERATE OVER THE EPISODES
    for _, episode_row in episode_pdf.iterrows():
        # COLLECT THE SALE AND THE BUY-BACK
        sell_row = sell_dict[episode_row["exit_ts"]]
        open_at_end_bool = episode_row["reentry_reason"] == "window_end"
        buy_row = None if open_at_end_bool else buy_dict[episode_row["reentry_ts"]]
        exit_idx, reentry_idx = int(sell_row["sell_idx"]), int(timestamp_index.get_loc(episode_row["reentry_ts"]))
        # COLLECT THE RAW PRICES (THE BUY-BACK OF AN OPEN EPISODE IS THE LAST CLOSE)
        sell_raw_price = float(sell_row["sell_raw_price"])
        reentry_raw_price = float(close_arr[reentry_idx]) if open_at_end_bool else float(buy_row["buy_raw_price"])
        # COLLECT THE SHARES
        shares_before = int(sell_row["share_count"])
        shares_after = np.nan if open_at_end_bool else int(buy_row["share_count"])
        # CALCULATE THE ROUND-TRIP COST (SLIPPAGE AND FEES; NONE ON THE BUY SIDE OF AN OPEN EPISODE)
        sell_cost = shares_before * (sell_raw_price - float(episode_row["exit_fill_price"])) + float(sell_row["sell_fee"])
        buy_cost = 0.0 if open_at_end_bool else shares_after * (float(episode_row["reentry_fill_price"]) - reentry_raw_price) + float(buy_row["buy_fee"])
        # CALCULATE THE LARGEST DECLINE BELOW THE SALE PRICE WHILE OUT
        min_low = float(low_arr[exit_idx:reentry_idx + 1].min()) if reentry_idx >= exit_idx else sell_raw_price
        # APPEND THE ROW
        row_dict_list.append({
            "exit_date": timestamp_index[exit_idx].date(), "exit_fill_price": float(episode_row["exit_fill_price"]), "exit_reason": episode_row["exit_reason"],
            "reentry_date": episode_row["reentry_ts"].date(), "reentry_fill_price": float(episode_row["reentry_fill_price"]), "reentry_reason": episode_row["reentry_reason"],
            "s_over_r": float(episode_row["exit_fill_price"]) / float(episode_row["reentry_fill_price"]),
            "log_share_gain": float(np.log(float(episode_row["exit_fill_price"]) / float(episode_row["reentry_fill_price"]))),
            "shares_before": shares_before, "shares_after": shares_after,
            "share_ratio": np.nan if open_at_end_bool else shares_after / shares_before,
            "sessions_out": int(episode_row["cash_session_count"]),
            "buy_hold_return_out": reentry_raw_price / sell_raw_price - 1,
            "max_decline_out_pct": min(0.0, min_low / sell_raw_price - 1),
            "cost_paid": float(sell_cost + buy_cost), "cost_paid_pct": float((sell_cost + buy_cost) / (shares_before * sell_raw_price)),
            "open_at_end": bool(open_at_end_bool),
        })
    # RETURN THE SCORECARD
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

# FUNCTION: SUMMARIZE A CONTINUOUS PATH AGAINST BUY-AND-HOLD
def get_replay_summary_dict(strategy_equity_pdf_in, buy_hold_equity_pdf_in, period_pdf_in, block_month_count_in,
                            baseline_total_return_dict_in=None, initial_capital_in=config.INITIAL_CAPITAL):
    """
    The readable statistics of a continuous path: total and annualized returns, time in the market, the period
    (quarter) summary with its sign test and minimum detectable effect, the annualized log excess with its block
    bootstrap interval, and the success criteria (primary, comparable return, secondary, baselines).

    Args:
        strategy_equity_pdf_in, buy_hold_equity_pdf_in (pd.DataFrame): Daily equity of the strategy and of buy-and-hold
            over the same sessions (date, equity, in_position)
        period_pdf_in (pd.DataFrame): Output of get_replay_period_pdf (the periods inside the path are used)
        block_month_count_in (int): Months per bootstrap block
        baseline_total_return_dict_in (dict | None): Total return of each baseline over the same path (name -> return)
        initial_capital_in (float): Starting equity of both paths

    Returns:
        dict: Flat summary (strategy_/buy_hold_ total and annualized returns, Sharpe, drawdown, in_market_pct, the window
              summary keys, log_excess_* keys, success flags, baselines_beaten)
    """
    # CALCULATE THE DAILY RETURNS OF BOTH PATHS
    strategy_return_pdf = get_chained_daily_return_pdf([strategy_equity_pdf_in], initial_capital_in)
    buy_hold_return_pdf = get_chained_daily_return_pdf([buy_hold_equity_pdf_in], initial_capital_in)
    # CALCULATE THE YEARS COVERED
    year_count = len(strategy_equity_pdf_in) / config.TRADING_DAYS_PER_YEAR
    # CALCULATE THE TOTAL AND ANNUALIZED RETURNS
    strategy_total = float(strategy_equity_pdf_in["equity"].iloc[-1] / initial_capital_in - 1)
    buy_hold_total = float(buy_hold_equity_pdf_in["equity"].iloc[-1] / initial_capital_in - 1)
    # CALCULATE THE PERIOD RETURNS AND THEIR SUMMARY
    strategy_period_pdf = get_period_return_pdf(strategy_equity_pdf_in, period_pdf_in, initial_capital_in)
    buy_hold_period_pdf = get_period_return_pdf(buy_hold_equity_pdf_in, period_pdf_in, initial_capital_in)
    window_summary_dict = get_window_return_summary_dict(strategy_period_pdf["total_return"].to_numpy(), buy_hold_period_pdf["total_return"].to_numpy())
    # CALCULATE THE LOG EXCESS BOOTSTRAP AND THE SUCCESS CRITERIA
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in)
    success_dict = get_success_criteria_dict(strategy_return_pdf, buy_hold_return_pdf, baseline_total_return_dict_in)
    # CALCULATE THE TIME IN THE MARKET (THE LAST SESSION EXCLUDED: EVERY POSITION IS SOLD AT ITS CLOSE)
    in_market_pct = float(strategy_equity_pdf_in["in_position"].iloc[:-1].astype(bool).mean()) if len(strategy_equity_pdf_in) > 1 else np.nan
    # RETURN THE SUMMARY
    return {"first_date": strategy_equity_pdf_in["date"].iloc[0], "last_date": strategy_equity_pdf_in["date"].iloc[-1],
            "session_count": int(len(strategy_equity_pdf_in)), "year_count": year_count,
            "strategy_total_return": strategy_total, "buy_hold_total_return": buy_hold_total, "excess_total_return": strategy_total - buy_hold_total,
            "strategy_annualized_return": float((1 + strategy_total) ** (1 / year_count) - 1), "buy_hold_annualized_return": float((1 + buy_hold_total) ** (1 / year_count) - 1),
            "strategy_sharpe_ratio": get_sharpe_ratio(strategy_equity_pdf_in, initial_capital_in), "buy_hold_sharpe_ratio": get_sharpe_ratio(buy_hold_equity_pdf_in, initial_capital_in),
            "strategy_max_drawdown": get_max_drawdown(strategy_equity_pdf_in, initial_capital_in), "buy_hold_max_drawdown": get_max_drawdown(buy_hold_equity_pdf_in, initial_capital_in),
            "in_market_pct": in_market_pct,
            **{f"period_{key}": value for key, value in window_summary_dict.items()},
            **{f"log_excess_{key}": value for key, value in log_excess_dict.items()},
            **{key: value for key, value in success_dict.items() if key.endswith("_success") or key in ["comparable_return", "secondary_sharpe", "secondary_drawdown", "all_baselines_beaten"]},
            "baselines_beaten": success_dict["baselines_beaten"]}
