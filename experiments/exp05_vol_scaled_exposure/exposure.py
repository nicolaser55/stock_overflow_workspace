import pandas as pd
import numpy as np
from scipy.stats import spearmanr
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp05_vol_scaled_exposure import config as exp_config
# IMPORT THE WALK-FORWARD SCHEDULE, THE EVALUATION AND THE CONTINUOUS REPLAY FUNCTIONS
from so.core.schedule import get_walk_forward_fold_pdf
from so.core.evaluation import get_pooled_selection_pdf, get_chained_daily_return_pdf
from so.core.continuous_replay import check_replay_window_bool, get_replay_period_pdf, get_period_return_pdf, get_prior_only_period_candidate_dict, \
                                      get_session_assignment_arr, get_replay_summary_dict, get_log_excess_bootstrap_dict
# IMPORT THE BUY AND HOLD BENCHMARK AND THE FRACTIONAL EXPOSURE SIMULATOR
from so.core.reentry_simulation import get_buy_and_hold_result_dict
from so.core.fractional_exposure import simulate_fractional_exposure_dict

"""
Volatility-Scaled Exposure: exp05_vol_scaled_exposure (PROTOCOL.md §4-§8)

Exposure rule (decided at the 15:58 decision of every session, so.core.fractional_exposure):
    w = min(1, max(floor, sigma_target / sigma_hat))
    sigma_hat     = daily_volatility of the session: standard deviation of the previous 20 daily close-to-close returns
    sigma_target  = the q-quantile of every daily_volatility value BEFORE the start of the session's replay period
                    (expanding from 2005-01-03; at least MIN_TARGET_HISTORY_SESSIONS values, otherwise w = 1)
    A NaN sigma_hat gives w = 1. The account rebalances at the 15:59 open only if |w - current weight| > DEAD_BAND.

Arithmetic of success (long only, unlevered): with daily SPY returns r_t and weights w_t <= 1, the strategy earns about
sum(w_t r_t) and buy-and-hold sum(r_t), so the strategy is ahead only if sum((1 - w_t) r_t) < 0 (plus the costs): the
periods of reduced exposure must have NEGATIVE returns in total, not merely more volatile ones.

Baselines of the prior-only path (same span, same costs, same dead band):
    buy_hold                  w = 1
    constant_exposure         w = the path's mean weight on every session (the uninformed version: same average exposure)
    random_shift_<i>          the path's target weights circularly shifted by a random number of sessions (same
                              distribution and persistence of the weights, timing unrelated to volatility)
"""

"""
Schedule And Candidates
"""

# FUNCTION: GET THE SCHEDULE AND THE REPLAY PERIODS
def get_schedule_tuple(session_date_list_in, train_years_in=exp_config.FIXED_TRAIN_WINDOW_YEARS, max_fold_count_in=None):
    """
    Builds the exp02-exp04 schedule (20-session embargo, folds that fit a 10-year window) and its replay periods.

    Args:
        session_date_list_in (list[datetime.date]): Session dates of the data
        train_years_in (int): Fixed window a fold must fit (years; smaller in tests)
        max_fold_count_in (int | None): Keep only the most recent folds

    Returns:
        tuple: (fold_pdf, period_pdf)
    """
    # BUILD THE SCHEDULE
    fold_pdf = get_walk_forward_fold_pdf(session_date_list_in, exp_config.EMBARGO_TRADING_DAYS, [train_years_in], max_fold_count_in=max_fold_count_in)
    # RETURN THE SCHEDULE AND THE PERIODS
    return fold_pdf, get_replay_period_pdf(fold_pdf, session_date_list_in)

# FUNCTION: GET THE CANDIDATES
def get_rule_candidate_list(floor_list_in=exp_config.FLOOR_LIST, quantile_list_in=exp_config.TARGET_QUANTILE_LIST):
    """
    Lists the 4 candidates in a fixed order (floor, then target quantile).

    Args:
        floor_list_in (list[float]): Exposure floors
        quantile_list_in (list[float]): Target volatility quantiles

    Returns:
        list[dict]: floor, target_quantile
    """
    # RETURN THE GRID
    return [{"floor": float(floor), "target_quantile": float(quantile)} for floor in floor_list_in for quantile in quantile_list_in]

"""
Weights
"""

# FUNCTION: GET THE TARGET VOLATILITY OF EVERY SESSION
def get_target_volatility_arr(daily_pdf_in, period_pdf_in, quantile_in, min_history_in=exp_config.MIN_TARGET_HISTORY_SESSIONS,
                              volatility_col_str_in=exp_config.VOLATILITY_COL_STR):
    """
    Per session of a period: the quantile of every volatility value of the sessions BEFORE the period start. The session
    just before the first period gets the first period's target (it decides the initial weight). NaN elsewhere.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (date, daily_volatility; indexed by session position)
        period_pdf_in (pd.DataFrame): Replay periods
        quantile_in (float): Target quantile
        min_history_in (int): Minimum number of finite values before the period start
        volatility_col_str_in (str): Volatility column

    Returns:
        np.ndarray: Target volatility per session position
    """
    # COLLECT THE DATES AND THE VOLATILITY
    date_arr = np.array(daily_pdf_in["date"].tolist())
    volatility_arr = daily_pdf_in[volatility_col_str_in].to_numpy(dtype=float)
    target_arr = np.full(len(date_arr), np.nan)
    # ITERATE OVER THE PERIODS
    for row_idx, period_row in period_pdf_in.reset_index(drop=True).iterrows():
        # COLLECT THE HISTORY BEFORE THE PERIOD START
        history_arr = volatility_arr[(date_arr < period_row["period_start"]) & np.isfinite(volatility_arr)]
        target = float(np.quantile(history_arr, quantile_in)) if len(history_arr) >= min_history_in else np.nan
        # ASSIGN THE TARGET TO THE PERIOD SESSIONS (AND TO THE SESSION BEFORE THE FIRST PERIOD)
        in_period_arr = (date_arr >= period_row["period_start"]) & (date_arr <= period_row["period_end"])
        target_arr[in_period_arr] = target
        first_idx = int(np.flatnonzero(in_period_arr)[0]) if in_period_arr.any() else -1
        if row_idx == 0 and first_idx > 0:
            target_arr[first_idx - 1] = target
    # RETURN THE TARGETS
    return target_arr

# FUNCTION: GET THE TARGET WEIGHT OF EVERY SESSION
def get_weight_arr(daily_pdf_in, target_arr_in, floor_in, volatility_col_str_in=exp_config.VOLATILITY_COL_STR):
    """
    w = min(1, max(floor, target / current volatility)); 1 where the target or the volatility is not available.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table
        target_arr_in (np.ndarray): Target volatility per session position
        floor_in (float): Exposure floor

    Returns:
        np.ndarray: Target weight per session position (in [floor, 1], or 1)
    """
    # COLLECT THE CURRENT VOLATILITY
    volatility_arr = daily_pdf_in[volatility_col_str_in].to_numpy(dtype=float)
    valid_arr = np.isfinite(volatility_arr) & np.isfinite(target_arr_in) & (volatility_arr > 0)
    # CALCULATE THE WEIGHTS
    weight_arr = np.ones(len(volatility_arr))
    weight_arr[valid_arr] = np.clip(target_arr_in[valid_arr] / volatility_arr[valid_arr], floor_in, 1.0)
    # RETURN THE WEIGHTS
    return weight_arr

# FUNCTION: GET THE WEIGHT BUILDER OF THE EXPERIMENT
def get_weight_builder_func(daily_pdf_in, period_pdf_in):
    """
    Returns f(candidate_dict) -> target weight per session position.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table
        period_pdf_in (pd.DataFrame): Replay periods (the targets are fixed per period)

    Returns:
        function: Weight builder
    """
    # CACHE THE TARGETS PER QUANTILE
    target_dict = {}
    # FUNCTION: BUILD ONE CANDIDATE
    def weight_builder_func(candidate_dict_in):
        if candidate_dict_in["target_quantile"] not in target_dict:
            target_dict[candidate_dict_in["target_quantile"]] = get_target_volatility_arr(daily_pdf_in, period_pdf_in, candidate_dict_in["target_quantile"])
        return get_weight_arr(daily_pdf_in, target_dict[candidate_dict_in["target_quantile"]], candidate_dict_in["floor"])
    # RETURN THE BUILDER
    return weight_builder_func

"""
Simulation
"""

# FUNCTION: SIMULATE A WEIGHT PATH OVER A SPAN
def simulate_weight_path_dict(ohlcv_array_dict_in, span_start_in, span_end_in, weight_arr_in, untouched_start_date_str_in, dead_band_in=exp_config.DEAD_BAND, **cost_kwargs):
    """
    Runs the fractional exposure simulator over the span (guard checked). The initial weight is the weight decided at the
    session before the span (1 if there is none or it is NaN).

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        span_start_in, span_end_in (datetime.date | str): Span bounds (inclusive)
        weight_arr_in (np.ndarray): Target weight per session position
        untouched_start_date_str_in (str): First date of the untouched data
        dead_band_in (float): Dead band
        **cost_kwargs: entry_slippage_in, market_exit_slippage_in

    Returns:
        dict: Output of so.core.fractional_exposure.simulate_fractional_exposure_dict
    """
    # CHECK THE GUARD
    check_replay_window_bool(span_end_in, untouched_start_date_str_in)
    # DEFINE THE INITIAL WEIGHT (DECIDED AT THE SESSION BEFORE THE SPAN)
    first_idx = int(ohlcv_array_dict_in["date_session_idx_dict"][pd.to_datetime(span_start_in).date()])
    initial_weight = float(weight_arr_in[first_idx - 1]) if first_idx > 0 and np.isfinite(weight_arr_in[first_idx - 1]) else 1.0
    # RETURN THE SIMULATION
    return simulate_fractional_exposure_dict(ohlcv_array_dict_in, span_start_in, span_end_in, weight_arr_in, dead_band_in, initial_weight, **cost_kwargs)

# FUNCTION: REPLAY EVERY CANDIDATE AND SCORE IT PER PERIOD
def run_candidate_exposure_dict(ohlcv_array_dict_in, period_pdf_in, candidate_dict_list_in, weight_builder_func_in, untouched_start_date_str_in,
                                block_month_count_in=exp_config.BOOTSTRAP_BLOCK_MONTH_COUNT, alert_in=True):
    """
    Replays every candidate continuously over the periods and scores it per period against buy-and-hold.

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        period_pdf_in (pd.DataFrame): Replay periods
        candidate_dict_list_in (list[dict]): Candidates
        weight_builder_func_in (function): f(candidate_dict) -> target weight per session position
        untouched_start_date_str_in (str): First date of the untouched data
        block_month_count_in (int): Months per block of the log-excess bootstrap
        alert_in (bool): Display one line per candidate

    Returns:
        dict: candidate_period_pdf (fold_id = period_id, settings, valid_total_return, valid_buy_hold_total_return,
              valid_excess_return, valid_mean_weight), candidate_summary_pdf, simulation_dict_list, buy_hold_dict
    """
    # DEFINE THE SPAN AND REPLAY BUY AND HOLD
    span_start, span_end = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end)
    buy_hold_period_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], period_pdf_in)
    # LISTS TO HOLD THE ROWS AND THE SIMULATIONS
    period_pdf_list, summary_dict_list, simulation_dict_list = [], [], []
    # ITERATE OVER THE CANDIDATES
    for candidate_idx, candidate_dict in enumerate(candidate_dict_list_in):
        # BUILD THE WEIGHTS AND REPLAY THEM
        simulation_dict = simulate_weight_path_dict(ohlcv_array_dict_in, span_start, span_end, weight_builder_func_in(candidate_dict), untouched_start_date_str_in)
        simulation_dict_list.append(simulation_dict)
        equity_pdf = simulation_dict["daily_equity_pdf"]
        # SCORE THE CANDIDATE PER PERIOD (MEAN END-OF-DAY WEIGHT PER PERIOD)
        candidate_period_pdf = get_period_return_pdf(equity_pdf, period_pdf_in)
        mean_weight_list = [float(equity_pdf.loc[(equity_pdf["date"] >= row["period_start"]) & (equity_pdf["date"] <= row["period_end"]), "weight"].mean()) for _, row in candidate_period_pdf.iterrows()]
        period_pdf_list.append(pd.DataFrame({"fold_id": candidate_period_pdf["period_id"].to_numpy(), "candidate_idx": candidate_idx,
                                             **{key: [value] * len(candidate_period_pdf) for key, value in candidate_dict.items()},
                                             "valid_start": candidate_period_pdf["period_start"].to_numpy(), "valid_end": candidate_period_pdf["period_end"].to_numpy(),
                                             "valid_total_return": candidate_period_pdf["total_return"].to_numpy(),
                                             "valid_buy_hold_total_return": buy_hold_period_pdf["total_return"].to_numpy(),
                                             "valid_excess_return": candidate_period_pdf["total_return"].to_numpy() - buy_hold_period_pdf["total_return"].to_numpy(),
                                             "valid_mean_weight": mean_weight_list}))
        # SUMMARIZE THE WHOLE PATH
        summary_dict = get_replay_summary_dict(equity_pdf, buy_hold_dict["daily_equity_pdf"], period_pdf_in, block_month_count_in)
        summary_dict_list.append({"candidate_idx": candidate_idx, **candidate_dict, "mean_weight": simulation_dict["metric_dict"]["mean_weight"],
                                  "rebalance_count": simulation_dict["metric_dict"]["rebalance_count"], "cost_paid": simulation_dict["metric_dict"]["cost_paid"],
                                  **{key: value for key, value in summary_dict.items() if key != "baselines_beaten"}})
        # DISPLAY INFORMATION
        print(f"\tcandidate {candidate_idx} {candidate_dict}: total {summary_dict['strategy_total_return']:.2%} vs buy & hold {summary_dict['buy_hold_total_return']:.2%}"
              f" | mean weight {simulation_dict['metric_dict']['mean_weight']:.1%} | rebalances {simulation_dict['metric_dict']['rebalance_count']}") if alert_in else None
    # RETURN THE RESULTS
    return {"candidate_period_pdf": pd.concat(period_pdf_list, ignore_index=True), "candidate_summary_pdf": pd.DataFrame(summary_dict_list),
            "simulation_dict_list": simulation_dict_list, "buy_hold_dict": buy_hold_dict}

# FUNCTION: RUN THE PRIOR-ONLY PATH, ITS BASELINES AND ITS SUMMARY
def run_prior_only_exposure_dict(ohlcv_array_dict_in, period_pdf_in, candidate_period_pdf_in, candidate_dict_list_in, weight_builder_func_in, untouched_start_date_str_in,
                                 key_col_str_list_in=("floor", "target_quantile"), tie_break_list_in=(("floor", False), ("target_quantile", False)),
                                 pooled_count_in=exp_config.SELECTION_POOLED_QUARTER_COUNT, random_run_count_in=exp_config.RANDOM_RUN_COUNT,
                                 random_shift_min_in=exp_config.RANDOM_SHIFT_MIN_SESSIONS, block_month_count_in=exp_config.BOOTSTRAP_BLOCK_MONTH_COUNT,
                                 seed_in=config.RANDOM_SEED):
    """
    Pooled selection per period, the prior-only weight path (period f's choice governs period f + 1), its baselines
    (module docstring), the summary, the 1-month log-excess interval and the cost sensitivity.

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        period_pdf_in (pd.DataFrame): Replay periods
        candidate_period_pdf_in (pd.DataFrame): candidate_period_pdf of run_candidate_exposure_dict
        candidate_dict_list_in (list[dict]): Candidates, in the same order
        weight_builder_func_in (function): f(candidate_dict) -> target weight per session position
        untouched_start_date_str_in (str): First date of the untouched data
        key_col_str_list_in (tuple[str]): Candidate key columns
        tie_break_list_in (tuple[tuple[str, bool]]): Tie-breaks (higher floor, then higher quantile: closest to buy-and-hold)
        pooled_count_in (int): Periods pooled by the selection
        random_run_count_in (int): Random shift runs
        random_shift_min_in (int): Smallest circular shift (sessions)
        block_month_count_in (int): Months per block of the primary log-excess bootstrap
        seed_in (int): Random seed

    Returns:
        dict: selection_pdf, period_candidate_dict, weight_arr, simulation_dict, buy_hold_dict, baseline_pdf,
              baseline_summary_dict, summary_dict, log_excess_1m_dict, cost_sensitivity_pdf, path_period_pdf
    """
    # SELECT ONE CANDIDATE PER PERIOD AND MAP IT TO THE NEXT PERIOD
    selection_pdf = get_pooled_selection_pdf(candidate_period_pdf_in, list(key_col_str_list_in), "valid_excess_return", pooled_count_in, list(tie_break_list_in))
    period_candidate_dict = get_prior_only_period_candidate_dict(selection_pdf, period_pdf_in, "candidate_idx")
    path_period_pdf = period_pdf_in[period_pdf_in["period_id"].isin(list(period_candidate_dict))].reset_index(drop=True)
    span_start, span_end = path_period_pdf["period_start"].iloc[0], path_period_pdf["period_end"].iloc[-1]
    # BUILD THE PRIOR-ONLY WEIGHTS (THE SESSION BEFORE THE SPAN USES THE FIRST GOVERNING CANDIDATE)
    candidate_weight_mat = np.vstack([weight_builder_func_in(candidate_dict) for candidate_dict in candidate_dict_list_in])
    assignment_arr = get_session_assignment_arr(ohlcv_array_dict_in["session_date_list"], path_period_pdf, period_candidate_dict)
    first_idx = int(ohlcv_array_dict_in["date_session_idx_dict"][span_start])
    if first_idx > 0:
        assignment_arr[first_idx - 1] = assignment_arr[first_idx]
    weight_arr = np.full(assignment_arr.shape, np.nan)
    weight_arr[assignment_arr >= 0] = candidate_weight_mat[assignment_arr[assignment_arr >= 0], np.flatnonzero(assignment_arr >= 0)]
    # REPLAY THE PATH AND BUY AND HOLD
    simulation_dict = simulate_weight_path_dict(ohlcv_array_dict_in, span_start, span_end, weight_arr, untouched_start_date_str_in)
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end)
    # LIST TO HOLD THE BASELINE ROWS
    baseline_dict_list = [{"baseline": "model", **simulation_dict["metric_dict"]}, {"baseline": "buy_hold", **buy_hold_dict["metric_dict"]}]
    # CONSTANT EXPOSURE AT THE PATH'S MEAN WEIGHT
    mean_weight = simulation_dict["metric_dict"]["mean_weight"]
    constant_arr = np.where(np.isfinite(weight_arr), mean_weight, np.nan)
    baseline_dict_list.append({"baseline": "constant_exposure", **simulate_weight_path_dict(ohlcv_array_dict_in, span_start, span_end, constant_arr, untouched_start_date_str_in)["metric_dict"]})
    # RANDOM CIRCULAR SHIFTS OF THE PATH'S WEIGHTS (THE SESSION BEFORE THE SPAN INCLUDED)
    window_idx_arr = np.flatnonzero(np.isfinite(weight_arr))
    rng = np.random.default_rng(seed_in)
    shift_arr = rng.integers(random_shift_min_in, len(window_idx_arr) - random_shift_min_in, size=random_run_count_in)
    for run_idx, shift in enumerate(shift_arr):
        shifted_arr = np.full(weight_arr.shape, np.nan)
        shifted_arr[window_idx_arr] = np.roll(weight_arr[window_idx_arr], int(shift))
        baseline_dict_list.append({"baseline": f"random_shift_{run_idx:02d}", "shift_sessions": int(shift),
                                   **simulate_weight_path_dict(ohlcv_array_dict_in, span_start, span_end, shifted_arr, untouched_start_date_str_in)["metric_dict"]})
    baseline_pdf = pd.DataFrame(baseline_dict_list)
    # SUMMARIZE THE BASELINES
    path_total_return = simulation_dict["metric_dict"]["total_return"]
    random_arr = baseline_pdf.loc[baseline_pdf["baseline"].str.startswith("random_shift_"), "total_return"].to_numpy(dtype=float)
    constant_total_return = float(baseline_pdf.loc[baseline_pdf["baseline"] == "constant_exposure", "total_return"].iloc[0])
    baseline_summary_dict = {"constant_exposure_total_return": constant_total_return, "constant_exposure_weight": mean_weight,
                             "random_shift_median": float(np.median(random_arr)), "random_shift_path_beats_share": float((random_arr < path_total_return).mean())}
    # SUMMARIZE THE PATH
    summary_dict = get_replay_summary_dict(simulation_dict["daily_equity_pdf"], buy_hold_dict["daily_equity_pdf"], path_period_pdf, block_month_count_in,
                                           {"constant_exposure": constant_total_return, "random_shift_median": baseline_summary_dict["random_shift_median"]})
    log_excess_1m_dict = get_log_excess_bootstrap_dict(get_chained_daily_return_pdf([simulation_dict["daily_equity_pdf"]]), get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]]), 1)
    # COST SENSITIVITY (SAME WEIGHTS, DIFFERENT SLIPPAGE; BUY-AND-HOLD RECOMPUTED WITH THE SAME SLIPPAGE)
    cost_dict_list = []
    for slippage in config.COST_SENSITIVITY_SLIPPAGE_LIST:
        cost_total = simulate_weight_path_dict(ohlcv_array_dict_in, span_start, span_end, weight_arr, untouched_start_date_str_in, entry_slippage_in=slippage, market_exit_slippage_in=slippage)["metric_dict"]["total_return"]
        cost_buy_hold = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end, entry_slippage_in=slippage, market_exit_slippage_in=slippage)["metric_dict"]["total_return"]
        cost_dict_list.append({"slippage_per_share": slippage, "total_return": cost_total, "buy_hold_return": cost_buy_hold, "excess_return": cost_total - cost_buy_hold})
    # RETURN THE RESULTS
    return {"selection_pdf": selection_pdf, "period_candidate_dict": period_candidate_dict, "weight_arr": weight_arr, "simulation_dict": simulation_dict,
            "buy_hold_dict": buy_hold_dict, "baseline_pdf": baseline_pdf, "baseline_summary_dict": baseline_summary_dict, "summary_dict": summary_dict,
            "log_excess_1m_dict": log_excess_1m_dict, "cost_sensitivity_pdf": pd.DataFrame(cost_dict_list), "path_period_pdf": path_period_pdf}

"""
Volatility Signal Check (step 01, exploration 2005-2014)
"""

# FUNCTION: GET THE FORWARD REALIZED VOLATILITY OF EVERY SESSION
def get_forward_volatility_arr(daily_pdf_in, horizon_in=exp_config.SIGNAL_CHECK_HORIZON_SESSIONS):
    """
    Standard deviation of the daily close-to-close returns of the horizon_in sessions AFTER the session (NaN at the end).

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (session_close)
        horizon_in (int): Sessions

    Returns:
        np.ndarray: Forward realized volatility per session position
    """
    # CALCULATE THE DAILY RETURNS AND THEIR ROLLING STANDARD DEVIATION, SHIFTED BACK BY THE HORIZON
    daily_return_series = daily_pdf_in["session_close"] / daily_pdf_in["session_close"].shift(1) - 1
    return daily_return_series.rolling(horizon_in, min_periods=horizon_in).std().shift(-horizon_in).to_numpy(dtype=float)

# FUNCTION: RUN THE VOLATILITY SIGNAL CHECK
def get_volatility_signal_check_dict(daily_pdf_in, date1_in, date2_in, horizon_in=exp_config.SIGNAL_CHECK_HORIZON_SESSIONS,
                                     iteration_count_in=exp_config.SIGNAL_CHECK_BOOTSTRAP_ITERATION_COUNT,
                                     block_month_count_in=exp_config.SIGNAL_CHECK_BLOCK_MONTH_COUNT, seed_in=config.RANDOM_SEED,
                                     volatility_col_str_in=exp_config.VOLATILITY_COL_STR):
    """
    Does the current volatility predict the realized volatility of the next horizon_in sessions? Spearman correlation of
    the two on the decisions of [date1, date2] (both known values, every forward value inside the data), with a circular
    block bootstrap of calendar months; also the log-log regression slope and R^2. PASS if the interval's lower bound > 0.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (cut at the exploration data cutoff)
        date1_in, date2_in (datetime.date | str): Decision window (inclusive)
        horizon_in (int): Forward horizon (sessions)
        iteration_count_in (int): Bootstrap iterations
        block_month_count_in (int): Months per block
        seed_in (int): Random seed
        volatility_col_str_in (str): Current volatility column

    Returns:
        dict: row_count, month_count, spearman, ci_low, ci_high, log_slope, log_r2, passed
    """
    # COLLECT THE ROWS
    date_arr = np.array(daily_pdf_in["date"].tolist())
    current_arr, forward_arr = daily_pdf_in[volatility_col_str_in].to_numpy(dtype=float), get_forward_volatility_arr(daily_pdf_in, horizon_in)
    mask_arr = (date_arr >= pd.to_datetime(date1_in).date()) & (date_arr <= pd.to_datetime(date2_in).date()) & np.isfinite(current_arr) & np.isfinite(forward_arr) & (current_arr > 0) & (forward_arr > 0)
    current_arr, forward_arr, month_arr = current_arr[mask_arr], forward_arr[mask_arr], pd.to_datetime(pd.Series(date_arr[mask_arr])).dt.to_period("M").to_numpy()
    # CALCULATE THE OBSERVED STATISTICS
    spearman = float(spearmanr(current_arr, forward_arr).correlation)
    log_slope, log_intercept = np.polyfit(np.log(current_arr), np.log(forward_arr), 1)
    log_r2 = float(np.corrcoef(np.log(current_arr), np.log(forward_arr))[0, 1] ** 2)
    # RESAMPLE BLOCKS OF MONTHS (CIRCULAR)
    month_code_arr, month_label_arr = pd.factorize(month_arr)
    month_count = len(month_label_arr)
    row_idx_list = [np.flatnonzero(month_code_arr == code) for code in range(month_count)]
    rng = np.random.default_rng(seed_in)
    block_count = int(np.ceil(month_count / block_month_count_in))
    boot_list = []
    for _ in range(iteration_count_in):
        start_arr = rng.integers(0, month_count, size=block_count)
        sample_month_arr = ((start_arr[:, None] + np.arange(block_month_count_in)[None, :]) % month_count).ravel()[:month_count]
        sample_idx_arr = np.concatenate([row_idx_list[code] for code in sample_month_arr])
        boot_list.append(spearmanr(current_arr[sample_idx_arr], forward_arr[sample_idx_arr]).correlation)
    ci_low, ci_high = np.percentile(boot_list, [2.5, 97.5])
    # RETURN THE CHECK
    return {"row_count": int(mask_arr.sum()), "month_count": int(month_count), "spearman": spearman, "ci_low": float(ci_low), "ci_high": float(ci_high),
            "log_slope": float(log_slope), "log_r2": log_r2, "passed": bool(ci_low > 0)}

# FUNCTION: GET THE FORWARD RETURNS BY CURRENT VOLATILITY BIN (DESCRIPTIVE, THE "LEVERAGE EFFECT" QUESTION)
def get_volatility_bin_return_pdf(daily_pdf_in, date1_in, date2_in, horizon_in=exp_config.SIGNAL_CHECK_HORIZON_SESSIONS, bin_count_in=exp_config.SIGNAL_CHECK_BIN_COUNT,
                                  volatility_col_str_in=exp_config.VOLATILITY_COL_STR):
    """
    Mean forward log return from the 15:59 fill to the 15:59 fill horizon_in sessions later, by quantile bin of the
    current volatility (edges from the same window). Scaling exposure down pays only if the high-volatility bins have
    forward returns below zero (not merely below average).

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (fill_open)
        date1_in, date2_in (datetime.date | str): Decision window (inclusive)
        horizon_in (int): Forward horizon (sessions)
        bin_count_in (int): Number of quantile bins
        volatility_col_str_in (str): Current volatility column

    Returns:
        pd.DataFrame: bin, volatility_low, volatility_high, row_count, mean_forward_log_return, up_share, std_forward_log_return
    """
    # COLLECT THE ROWS
    date_arr = np.array(daily_pdf_in["date"].tolist())
    fill_open_arr, current_arr = daily_pdf_in["fill_open"].to_numpy(dtype=float), daily_pdf_in[volatility_col_str_in].to_numpy(dtype=float)
    forward_arr = np.full(len(fill_open_arr), np.nan)
    forward_arr[:-horizon_in] = np.log(fill_open_arr[horizon_in:] / fill_open_arr[:-horizon_in])
    mask_arr = (date_arr >= pd.to_datetime(date1_in).date()) & (date_arr <= pd.to_datetime(date2_in).date()) & np.isfinite(current_arr) & np.isfinite(forward_arr)
    # DEFINE THE BINS AND SUMMARIZE THEM
    edge_arr = np.quantile(current_arr[mask_arr], np.linspace(0, 1, bin_count_in + 1))
    bin_arr = np.clip(np.searchsorted(edge_arr, current_arr[mask_arr], side="right") - 1, 0, bin_count_in - 1)
    row_pdf = pd.DataFrame({"bin": bin_arr, "forward": forward_arr[mask_arr]})
    summary_pdf = row_pdf.groupby("bin").agg(row_count=("forward", "size"), mean_forward_log_return=("forward", "mean"),
                                             up_share=("forward", lambda s: float((s > 0).mean())), std_forward_log_return=("forward", "std")).reset_index()
    summary_pdf.insert(1, "volatility_low", edge_arr[summary_pdf["bin"]])
    summary_pdf.insert(2, "volatility_high", edge_arr[summary_pdf["bin"] + 1])
    # RETURN THE TABLE
    return summary_pdf
