import os
import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION, THE PATHS AND THE EXPERIMENT CONFIGURATION
from so import config, paths
from experiments.exp13_e1m1_robustness import config as exp_config
# IMPORT DATA LOADING, EXECUTION, DAILY FEATURE AND VIX FEATURE MODULES (MODULE CALLS, SO THE SMOKE RUN CAN REPLACE THE READERS)
from so.core import raw_data
from so.features import vix_features
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
# IMPORT EXIT AND RE-ENTRY SIMULATION FUNCTIONS
from so.core.reentry_simulation import get_random_reentry_func, get_buy_and_hold_result_dict
# IMPORT THE CONTINUOUS REPLAY AND EVALUATION FUNCTIONS
from so.core.continuous_replay import simulate_continuous_replay_dict, get_episode_scorecard_pdf, get_replay_summary_dict, get_log_excess_bootstrap_dict
from so.core.evaluation import get_chained_daily_return_pdf
# IMPORT THE RULES OF exp04 AND exp12 (E1M1 IS FROZEN: exp12's RULE BUILDER IS USED, NEVER RE-IMPLEMENTED)
from experiments.exp04_trend_exit.rules import get_trend_exit_signal_arr, get_trend_reentry_signal_arr
from experiments.exp12_vix_fear_reentry.rules import get_rule_builder_func, get_m1_trigger_bool, get_vix_scorecard_pdf

"""
Robustness Study: exp13_e1m1_robustness (PROTOCOL.md)

E1M1 is exp12's candidate, FROZEN: its rule comes from experiments.exp12_vix_fear_reentry.rules.get_rule_builder_func
(E1 = exit below the 200-session average, original re-entry above, x = 0, n = 1; M1 = buy back when vix_level_prev <=
0.85 x its maximum from the exit decision to now, NaN skipped, or by the original re-entry; fresh exit signal after an M1
re-entry). Every path is a continuous replay (so.core.continuous_replay), with no selection between periods.

    Data      SPY and VIX loads cut at the span's cutoff (DEV 2026-04-15, STRESS 2015-03-18); the 150 / 250-session
              average distances are computed exactly as so.features.daily_features computes ma200_dist_pct.
    Variants  The step 02 neighbourhood (fade ratio x moving-average length x fresh-signal rule) with the same structure
              as exp12's M1 (original rule first, then the fade); at 0.85 / 200 / on it equals the frozen E1M1 exactly
              (asserted in the tests and in step 02).
    Delay     One-session-late execution: the exit signal and the re-entry rule of session t act at session t + 1
              (every trade fills at the fill bar of the next session).
    Nulls     P1 / P2 circularly shifted VIX features (exp08's convention), P3 random re-entry after the path's exits, P4
              random exits with the path's re-entry rule (exp04's families); run in parallel processes, each run seeded
              by its index, so the results do not depend on the number of processes.
"""

"""
Data
"""

# FUNCTION: GET THE DISTANCE OF THE DECISION CLOSE FROM AN n-SESSION AVERAGE
def get_ma_dist_arr(daily_pdf_in, ma_length_in):
    """
    decision close / mean of the previous n complete session closes - 1, rounded to 10 decimals (so.features.daily_features's
    ma200_dist_pct formula and rounding with another n; NaN for the first n sessions).

    Args:
        daily_pdf_in (pd.DataFrame): Output of so.features.daily_features.get_daily_feature_pdf
        ma_length_in (int): Sessions in the average

    Returns:
        np.ndarray: Distance per session position
    """
    # CALCULATE THE AVERAGE OF THE PREVIOUS n COMPLETE CLOSES
    moving_average_series = daily_pdf_in["session_close"].rolling(int(ma_length_in), min_periods=int(ma_length_in)).mean().shift(1)
    # RETURN THE DISTANCE
    return (daily_pdf_in["decision_close"] / moving_average_series - 1).round(10).to_numpy(dtype=float)

# FUNCTION: ADD THE MOVING-AVERAGE DISTANCES OF THE GRID
def add_ma_dist_col_pdf(daily_pdf_in, ma_length_list_in=exp_config.MA_LENGTH_LIST):
    """
    Adds ma{n}_dist_pct for every length that the daily table does not have (the existing ma200_dist_pct is kept).

    Args:
        daily_pdf_in (pd.DataFrame): Daily table
        ma_length_list_in (list[int]): Lengths

    Returns:
        pd.DataFrame: A copy with the columns
    """
    # COPY THE TABLE AND ADD THE MISSING COLUMNS
    daily_pdf = daily_pdf_in.copy()
    for ma_length in ma_length_list_in:
        if f"ma{int(ma_length)}_dist_pct" not in daily_pdf.columns:
            daily_pdf[f"ma{int(ma_length)}_dist_pct"] = get_ma_dist_arr(daily_pdf, ma_length)
    # RETURN THE TABLE
    return daily_pdf

# FUNCTION: LOAD SPY AND THE VIX FEATURES UP TO A CUTOFF
def get_span_data_dict(cutoff_date_str_in):
    """
    Reads the SPY minute bars and the VIX / VIX3M daily bars up to the cutoff (nothing later is read), and builds the
    daily table (with the grid's average distances) and the _prev VIX features.

    Args:
        cutoff_date_str_in (str): Last date loaded (before the untouched window)

    Returns:
        dict: ohlcv_array_dict, daily_pdf, vix_feature_pdf, last_date_dict (spy, vix_daily, vix3m_daily), first_spy_date
    """
    # CHECK THE CUTOFF
    cutoff_date = pd.Timestamp(cutoff_date_str_in).date()
    assert cutoff_date < pd.Timestamp(exp_config.UNTOUCHED_START_DATE_STR).date(), "❌ The cutoff reaches the untouched window"
    # CALL FUNCTION TO READ THE MINUTE BARS UP TO THE CUTOFF
    ohlcv_pdf = raw_data.get_complete_ohlcv_pdf(cutoff_date_str_in=cutoff_date_str_in)
    assert ohlcv_pdf["date"].max() <= cutoff_date, "❌ SPY bars after the cutoff"
    first_spy_date, last_spy_date = ohlcv_pdf["date"].min(), ohlcv_pdf["date"].max()
    # CALL FUNCTION TO BUILD THE ARRAYS AND THE DAILY TABLE
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    del ohlcv_pdf
    daily_pdf = add_ma_dist_col_pdf(get_daily_feature_pdf(ohlcv_array_dict))
    # CALL FUNCTION TO LOAD THE VIX AND VIX3M DAILY BARS WITH THE SAME CUTOFF AND BUILD THE _prev FEATURES
    vix_dict = vix_features.get_vix_daily_feature_dict(daily_pdf, cutoff_date_str_in, [exp_config.VIX_VARIANT_STR])
    assert all(last_date <= cutoff_date for last_date in vix_dict["last_date_dict"].values()), "❌ VIX bars after the cutoff"
    # RETURN THE DATA
    return {"ohlcv_array_dict": ohlcv_array_dict, "daily_pdf": daily_pdf, "vix_feature_pdf": vix_dict["feature_pdf"],
            "last_date_dict": {"spy": last_spy_date, **vix_dict["last_date_dict"]}, "first_spy_date": first_spy_date}

# FUNCTION: READ THE 44 REPLAY PERIODS OF exp12 (DEV)
def get_dev_period_pdf(check_real_bool_in=True, folder_path_str_in=None):
    """
    Reads exp12 step 02's saved replay periods and fold schedule (dates only; no market data), so that DEV is exactly
    exp12's candidate span and no bar after 2026-04-15 is read.

    Args:
        check_real_bool_in (bool): Assert the real schedule (44 periods, 2015-04-17 -> 2026-04-15, latest test start 2026-05-14)
        folder_path_str_in (str | None): Folder of exp12's step 02 outputs (None = the data folder)

    Returns:
        pd.DataFrame: period_id, period_start, period_end, session_count
    """
    # READ THE PERIODS AND THE FOLDS
    folder_path_str = folder_path_str_in or paths.get_experiment_data_path_str(exp_config.DEV_PERIOD_EXPERIMENT_NAME, exp_config.DEV_PERIOD_STEP_FOLDER_STR)
    period_pdf = pd.read_csv(os.path.join(folder_path_str, "replay_period_data.csv"))
    fold_pdf = pd.read_csv(os.path.join(folder_path_str, "fold_schedule_data.csv"))
    # CONVERT THE DATES
    for col_str in ["period_start", "period_end"]:
        period_pdf[col_str] = pd.to_datetime(period_pdf[col_str]).dt.date
    # CHECK THE REAL SCHEDULE
    if check_real_bool_in:
        assert len(period_pdf) == exp_config.DEV_PERIOD_COUNT, f"❌ {len(period_pdf)} periods"
        assert str(period_pdf["period_start"].iloc[0]) == exp_config.DEV_START_DATE_STR and str(period_pdf["period_end"].iloc[-1]) == exp_config.DEV_END_DATE_STR, "❌ DEV span differs"
        assert str(pd.Timestamp(fold_pdf["test_start"].iloc[-1]).date()) == exp_config.DEV_LATEST_TEST_START_STR, "❌ Latest test start differs"
    # RETURN THE PERIODS
    return period_pdf[["period_id", "period_start", "period_end", "session_count"]]

# FUNCTION: GET THE FIRST SESSION OF THE STRESS SPAN
def get_stress_start_date(daily_pdf_in, vix_feature_pdf_in, earliest_date_str_in=exp_config.STRESS_EARLIEST_START_DATE_STR):
    """
    The first session on or after the earliest date where both the 200-session average distance and vix_level_prev exist.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (ma200_dist_pct)
        vix_feature_pdf_in (pd.DataFrame): VIX features aligned with it (vix_level_prev)
        earliest_date_str_in (str): Earliest allowed date

    Returns:
        datetime.date: First STRESS session
    """
    # FIND THE SESSIONS WHERE BOTH VALUES EXIST
    valid_arr = (pd.to_datetime(daily_pdf_in["date"]).dt.date >= pd.Timestamp(earliest_date_str_in).date()).to_numpy() \
        & np.isfinite(daily_pdf_in[exp_config.FROZEN_MA_DIST_COL_STR].to_numpy(dtype=float)) & np.isfinite(vix_feature_pdf_in[exp_config.VIX_LEVEL_COL_STR].to_numpy(dtype=float))
    assert valid_arr.any(), "❌ No STRESS session"
    # RETURN THE FIRST ONE
    return daily_pdf_in["date"].iloc[int(np.flatnonzero(valid_arr)[0])]

# FUNCTION: GET ONE PERIOD PER CALENDAR YEAR OF A WINDOW
def get_year_period_pdf(session_date_list_in, date1_in, date2_in):
    """
    One period per calendar year of the window (for the periods-won count of a path without a schedule).

    Args:
        session_date_list_in (list[datetime.date]): Session dates of the data
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)

    Returns:
        pd.DataFrame: period_id (year), period_start, period_end, session_count
    """
    # COLLECT THE WINDOW SESSIONS
    date1, date2 = pd.Timestamp(date1_in).date(), pd.Timestamp(date2_in).date()
    window_date_list = [date for date in session_date_list_in if date1 <= date <= date2]
    # RETURN ONE ROW PER YEAR
    return pd.DataFrame([{"period_id": year, "period_start": min(d for d in window_date_list if d.year == year), "period_end": max(d for d in window_date_list if d.year == year),
                          "session_count": sum(1 for d in window_date_list if d.year == year)} for year in sorted({d.year for d in window_date_list})])

"""
Rules
"""

# FUNCTION: GET THE FROZEN RULE OF A CANDIDATE (exp12's RULE BUILDER)
def get_frozen_rule_tuple(daily_pdf_in, vix_feature_pdf_in, candidate_dict_in=exp_config.FROZEN_CANDIDATE_DICT):
    """
    The exp12 rule of a candidate (E1M1 by default), from exp12's rule builder.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table
        vix_feature_pdf_in (pd.DataFrame): VIX features aligned with it
        candidate_dict_in (dict): exp12 candidate (exit_rule, modification)

    Returns:
        tuple: (exit_signal_arr, reentry_func, reentry_reason_str)
    """
    # RETURN THE RULE
    return get_rule_builder_func(daily_pdf_in, vix_feature_pdf_in)(candidate_dict_in)

# FUNCTION: GET THE RULE OF A NEIGHBOURHOOD VARIANT
def get_variant_rule_tuple(daily_pdf_in, vix_feature_pdf_in, fade_ratio_in, ma_length_in, fresh_exit_bool_in):
    """
    E1 with an n-session average (exit below, original re-entry above; x = 0, n = 1, exp04's functions) and M1 with a
    fade ratio (exp12's trigger), the original rule checked first as in exp12; after an M1 re-entry a fresh exit signal is
    required only if fresh_exit_bool_in. At 0.85 / 200 / True it equals the frozen E1M1.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table with ma{n}_dist_pct (add_ma_dist_col_pdf)
        vix_feature_pdf_in (pd.DataFrame): VIX features aligned with it
        fade_ratio_in (float): Fade ratio of M1
        ma_length_in (int): Sessions in the average
        fresh_exit_bool_in (bool): Fresh-signal rule after an M1 re-entry

    Returns:
        tuple: (exit_signal_arr, reentry_func, reentry_reason_str)
    """
    # CHECK THE ALIGNMENT AND COLLECT THE SIGNALS
    assert (vix_feature_pdf_in["session_idx"].to_numpy() == daily_pdf_in["session_idx"].to_numpy()).all(), "❌ VIX features not aligned"
    ma_dist_col_str = f"ma{int(ma_length_in)}_dist_pct"
    exit_arr = get_trend_exit_signal_arr(daily_pdf_in, exp_config.FROZEN_E1_BUFFER, exp_config.FROZEN_E1_CONFIRMATION, ma_dist_col_str)
    original_arr = get_trend_reentry_signal_arr(daily_pdf_in, exp_config.FROZEN_E1_BUFFER, ma_dist_col_str)
    level_arr = vix_feature_pdf_in[exp_config.VIX_LEVEL_COL_STR].to_numpy(dtype=float)
    # FUNCTION: THE RE-ENTRY RULE
    def reentry_func(session_idx, cash_session_count, episode_dict):
        # THE ORIGINAL RULE FIRST (LABELLED "original" WHEN BOTH FIRE)
        if bool(original_arr[session_idx]):
            episode_dict["reentry_trigger"] = "original"
            return True
        # THE FADE TRIGGER (THE EXIT DECISION IS THE SESSION BEFORE THE FIRST CASH DECISION)
        if get_m1_trigger_bool(level_arr, int(episode_dict["first_cash_session_idx"]) - 1, session_idx, fade_ratio_in):
            episode_dict["reentry_trigger"] = "M1"
            if fresh_exit_bool_in:
                episode_dict["require_fresh_exit"] = True
            return True
        # OTHERWISE STAY IN CASH
        return False
    # RETURN THE RULE
    return exit_arr, reentry_func, "rule"

# FUNCTION: DELAY A RULE BY SOME SESSIONS
def get_delayed_rule_tuple(rule_tuple_in, delay_session_count_in=exp_config.DELAY_SESSION_COUNT):
    """
    The same rule acting d sessions late: the exit signal of session t sells at session t + d, and the re-entry decision
    of session t buys at session t + d (the rule is asked at session s about session s - d, with the episode's first cash
    decision moved back by d, so M1's maximum still starts at the original exit decision). Keys the rule sets on the
    episode (reentry_trigger, require_fresh_exit) are passed on to the simulator.

    Args:
        rule_tuple_in (tuple): (exit_signal_arr, reentry_func, reentry_reason_str)
        delay_session_count_in (int): Sessions of delay (>= 1)

    Returns:
        tuple: (exit_signal_arr, reentry_func, reentry_reason_str) of the delayed rule
    """
    # COLLECT THE RULE AND SHIFT THE EXIT SIGNAL
    exit_arr, reentry_func, reason_str = rule_tuple_in
    delay = int(delay_session_count_in)
    assert delay >= 1
    delayed_exit_arr = np.concatenate([np.zeros(delay, dtype=bool), np.asarray(exit_arr, dtype=bool)[:-delay]])
    # FUNCTION: THE DELAYED RE-ENTRY RULE
    def delayed_reentry_func(session_idx, cash_session_count, episode_dict):
        # NO DECISION EXISTS d SESSIONS BEFORE THE FIRST SESSIONS
        if session_idx - delay < 0:
            return False
        # ASK THE RULE ABOUT THE DECISION d SESSIONS EARLIER (ITS EPISODE STARTED d SESSIONS EARLIER)
        inner_episode_dict = dict(episode_dict)
        inner_episode_dict["first_cash_session_idx"] = int(episode_dict["first_cash_session_idx"]) - delay
        result_bool = bool(reentry_func(session_idx - delay, cash_session_count, inner_episode_dict))
        # PASS THE KEYS SET BY THE RULE TO THE SIMULATOR'S EPISODE
        for key_str, value in inner_episode_dict.items():
            if key_str != "first_cash_session_idx":
                episode_dict[key_str] = value
        # RETURN THE DECISION
        return result_bool
    # RETURN THE DELAYED RULE
    return delayed_exit_arr, delayed_reentry_func, reason_str

"""
Replay And Metrics
"""

# FUNCTION: REPLAY A RULE OVER A WINDOW
def replay_rule_dict(ohlcv_array_dict_in, rule_tuple_in, date1_in, date2_in, **cost_kwargs):
    """
    One continuous path (start invested, no stop, no forced buy-back), exp12's simulator settings.

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        rule_tuple_in (tuple): (exit_signal_arr, reentry_func, reentry_reason_str)
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        cost_kwargs: entry_slippage_in, market_exit_slippage_in (default: so.config)

    Returns:
        dict: Output of simulate_stop_reentry_dict
    """
    # COLLECT THE RULE AND REPLAY IT
    exit_arr, reentry_func, reason_str = rule_tuple_in
    return simulate_continuous_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, exp_config.UNTOUCHED_START_DATE_STR,
                                           volatility_arr_in=np.full(len(ohlcv_array_dict_in["session_date_list"]), np.nan), stop_k_in=None,
                                           reentry_func_in=reentry_func, reentry_reason_str_in=reason_str, exit_signal_arr_in=exit_arr,
                                           max_cash_sessions_in=exp_config.FROZEN_MAX_CASH_SESSIONS, **cost_kwargs)

# FUNCTION: GET THE REPORTED METRICS OF A PATH
def get_path_metric_dict(simulation_dict_in, buy_hold_dict_in, period_pdf_in, ohlcv_array_dict_in):
    """
    Total return vs buy-and-hold over the same sessions; annualized log excess with 6-month and 1-month block intervals;
    time in the market; exits; Sharpe; maximum drawdown; product of S/R; periods won.

    Args:
        simulation_dict_in (dict): Output of replay_rule_dict
        buy_hold_dict_in (dict): Output of get_buy_and_hold_result_dict over the same window
        period_pdf_in (pd.DataFrame): Periods of the window (period_id, period_start, period_end)
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict

    Returns:
        dict: Flat metrics
    """
    # SUMMARIZE THE PATH (6-MONTH BLOCKS) AND ADD THE 1-MONTH INTERVAL
    strategy_equity_pdf, buy_hold_equity_pdf = simulation_dict_in["daily_equity_pdf"], buy_hold_dict_in["daily_equity_pdf"]
    summary_dict = get_replay_summary_dict(strategy_equity_pdf, buy_hold_equity_pdf, period_pdf_in, exp_config.BOOTSTRAP_BLOCK_MONTH_COUNT)
    log_excess_1m_dict = get_log_excess_bootstrap_dict(get_chained_daily_return_pdf([strategy_equity_pdf]), get_chained_daily_return_pdf([buy_hold_equity_pdf]),
                                                       exp_config.SECONDARY_BOOTSTRAP_BLOCK_MONTH_COUNT)
    # CALCULATE THE PRODUCT OF S / R
    scorecard_pdf = get_episode_scorecard_pdf(simulation_dict_in, ohlcv_array_dict_in)
    log_gain_sum = float(scorecard_pdf["log_share_gain"].sum()) if len(scorecard_pdf) else 0.0
    # RETURN THE METRICS
    return {"first_date": str(summary_dict["first_date"]), "last_date": str(summary_dict["last_date"]), "session_count": summary_dict["session_count"],
            "total_return": summary_dict["strategy_total_return"], "buy_hold_total_return": summary_dict["buy_hold_total_return"],
            "excess_total_return": summary_dict["excess_total_return"], "beats_buy_hold": bool(summary_dict["strategy_total_return"] > summary_dict["buy_hold_total_return"]),
            "annualized_log_excess": summary_dict["log_excess_annualized_log_excess"],
            "log_excess_ci_low_6m": summary_dict["log_excess_ci_low"], "log_excess_ci_high_6m": summary_dict["log_excess_ci_high"],
            "log_excess_ci_low_1m": log_excess_1m_dict["ci_low"], "log_excess_ci_high_1m": log_excess_1m_dict["ci_high"],
            "in_market_pct": summary_dict["in_market_pct"], "exit_count": int(simulation_dict_in["metric_dict"]["signal_exit_count"]),
            "sharpe_ratio": summary_dict["strategy_sharpe_ratio"], "buy_hold_sharpe_ratio": summary_dict["buy_hold_sharpe_ratio"],
            "max_drawdown": summary_dict["strategy_max_drawdown"], "buy_hold_max_drawdown": summary_dict["buy_hold_max_drawdown"],
            "episode_count": int(len(scorecard_pdf)), "product_s_over_r": float(np.exp(log_gain_sum)),
            "periods_won": summary_dict["period_windows_beating_buy_hold"], "period_count": summary_dict["period_window_count"]}

# FUNCTION: GET THE STRESS SCORECARD OF A PATH
def get_stress_scorecard_pdf(simulation_dict_in, ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in):
    """
    exp12's VIX scorecard (re-entry reason, vix_level_prev at the exit and at the buy-back) plus the maximum of
    vix_level_prev from the exit decision to the buy-back decision and, for every M1 re-entry, SPY's lowest session close
    from the buy-back session to the next exit session (or the end of the path) and the drawdown from the buy-back price
    to that low (capped at 0).

    Args:
        simulation_dict_in (dict): Output of replay_rule_dict
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        daily_pdf_in (pd.DataFrame): Daily table (date, session_close)
        vix_feature_pdf_in (pd.DataFrame): VIX features aligned with it

    Returns:
        pd.DataFrame: The scorecard with vix_max_out, lowest_close_to_next_exit, drawdown_to_low_pct
    """
    # BUILD exp12's VIX SCORECARD
    scorecard_pdf = get_vix_scorecard_pdf(get_episode_scorecard_pdf(simulation_dict_in, ohlcv_array_dict_in), simulation_dict_in, vix_feature_pdf_in)
    # IF THERE IS NO EPISODE
    if scorecard_pdf.empty:
        return scorecard_pdf
    # COLLECT THE SESSION POSITIONS, THE LEVELS AND THE CLOSES
    position_dict = {date: idx for idx, date in enumerate(daily_pdf_in["date"].tolist())}
    level_arr = vix_feature_pdf_in[exp_config.VIX_LEVEL_COL_STR].to_numpy(dtype=float)
    close_arr = daily_pdf_in["session_close"].to_numpy(dtype=float)
    path_end_idx = position_dict[pd.Timestamp(simulation_dict_in["daily_equity_pdf"]["date"].iloc[-1]).date()]
    # LISTS TO HOLD THE NEW COLUMNS
    vix_max_list, low_list, drawdown_list = [], [], []
    # ITERATE OVER THE EPISODES
    for row_pos, (_, row) in enumerate(scorecard_pdf.iterrows()):
        exit_idx, reentry_idx = position_dict[row["exit_date"]], position_dict[row["reentry_date"]]
        # THE VIX MAXIMUM FROM THE EXIT DECISION TO THE BUY-BACK DECISION (NaN SKIPPED)
        window_arr = level_arr[exit_idx:reentry_idx + 1]
        vix_max_list.append(float(np.nanmax(window_arr)) if np.isfinite(window_arr).any() else np.nan)
        # FOR AN M1 RE-ENTRY: THE LOWEST CLOSE UNTIL THE NEXT EXIT AND THE DRAWDOWN FROM THE BUY-BACK PRICE
        if row["reentry_trigger"] == "M1":
            next_exit_idx = position_dict[scorecard_pdf["exit_date"].iloc[row_pos + 1]] if row_pos + 1 < len(scorecard_pdf) else path_end_idx
            lowest_close = float(close_arr[reentry_idx:next_exit_idx + 1].min())
            low_list.append(lowest_close)
            drawdown_list.append(min(0.0, lowest_close / float(row["reentry_fill_price"]) - 1))
        else:
            low_list.append(np.nan)
            drawdown_list.append(np.nan)
    # ADD THE COLUMNS AND RETURN THE SCORECARD
    return scorecard_pdf.assign(vix_max_out=vix_max_list, lowest_close_to_next_exit=low_list, drawdown_to_low_pct=drawdown_list)

# FUNCTION: REPLAY THE DEV REPRODUCTION PATHS (FROZEN E1M1, UNMODIFIED E1, BUY-AND-HOLD)
def get_dev_reproduction_dict(span_data_dict_in, period_pdf_in, check_real_bool_in=True):
    """
    Replays the frozen E1M1 and the unmodified E1 over DEV (exp12's code) with buy-and-hold, and asserts exp12's saved
    numbers (+314.80% with 35 exits, +108.03% with 35 exits, buy-and-hold +235.39%). Any difference stops the notebook.

    Args:
        span_data_dict_in (dict): Output of get_span_data_dict (DEV cutoff)
        period_pdf_in (pd.DataFrame): DEV periods (get_dev_period_pdf)
        check_real_bool_in (bool): Assert the real numbers

    Returns:
        dict: date1, date2, frozen_rule_tuple, frozen_simulation_dict, e1_simulation_dict, buy_hold_dict, reproduction_dict
    """
    # COLLECT THE SPAN AND THE DATA
    date1, date2 = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    ohlcv_array_dict, daily_pdf, vix_feature_pdf = span_data_dict_in["ohlcv_array_dict"], span_data_dict_in["daily_pdf"], span_data_dict_in["vix_feature_pdf"]
    # REPLAY THE THREE PATHS
    frozen_rule_tuple = get_frozen_rule_tuple(daily_pdf, vix_feature_pdf)
    frozen_simulation_dict = replay_rule_dict(ohlcv_array_dict, frozen_rule_tuple, date1, date2)
    e1_simulation_dict = replay_rule_dict(ohlcv_array_dict, get_frozen_rule_tuple(daily_pdf, vix_feature_pdf, exp_config.UNMODIFIED_E1_CANDIDATE_DICT), date1, date2)
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)
    # COLLECT THE REPRODUCTION NUMBERS
    reproduction_dict = {"dev_start": str(date1), "dev_end": str(date2),
                         "e1m1_total_pct": round(100 * frozen_simulation_dict["metric_dict"]["total_return"], 2), "e1m1_exit_count": int(frozen_simulation_dict["metric_dict"]["signal_exit_count"]),
                         "e1_total_pct": round(100 * e1_simulation_dict["metric_dict"]["total_return"], 2), "e1_exit_count": int(e1_simulation_dict["metric_dict"]["signal_exit_count"]),
                         "buy_hold_pct": round(100 * buy_hold_dict["metric_dict"]["total_return"], 2)}
    # ASSERT THE REPRODUCTION
    if check_real_bool_in:
        assert reproduction_dict["e1m1_total_pct"] == exp_config.REPRODUCTION_DEV_E1M1_TOTAL_PCT and reproduction_dict["e1m1_exit_count"] == exp_config.REPRODUCTION_DEV_E1M1_EXIT_COUNT, f"❌ E1M1 differs: {reproduction_dict}"
        assert reproduction_dict["e1_total_pct"] == exp_config.REPRODUCTION_DEV_E1_TOTAL_PCT and reproduction_dict["e1_exit_count"] == exp_config.REPRODUCTION_DEV_E1_EXIT_COUNT, f"❌ E1 differs: {reproduction_dict}"
        assert reproduction_dict["buy_hold_pct"] == exp_config.REPRODUCTION_DEV_BUY_HOLD_PCT, f"❌ Buy-and-hold differs: {reproduction_dict}"
    # RETURN THE PATHS
    return {"date1": date1, "date2": date2, "frozen_rule_tuple": frozen_rule_tuple, "frozen_simulation_dict": frozen_simulation_dict,
            "e1_simulation_dict": e1_simulation_dict, "buy_hold_dict": buy_hold_dict, "reproduction_dict": reproduction_dict}

# FUNCTION: CHECK THE LAST DATES LOADED
def check_last_date_dict(last_date_dict_in, cutoff_date_str_in, check_real_bool_in=True):
    """
    Prints the last SPY, VIX and VIX3M dates loaded; asserts they are not after the cutoff and, on the real data, that
    they equal it.

    Args:
        last_date_dict_in (dict): spy, vix_daily, vix3m_daily -> last date
        cutoff_date_str_in (str): Cutoff of the load
        check_real_bool_in (bool): Assert equality with the cutoff

    Returns:
        dict: The dates as strings
    """
    # PRINT AND CHECK EVERY DATE
    cutoff_date = pd.Timestamp(cutoff_date_str_in).date()
    for key_str, last_date in last_date_dict_in.items():
        print(f"Last date loaded:\t{key_str}\t{last_date}\t(cutoff {cutoff_date_str_in})")
        assert last_date <= cutoff_date, f"❌ {key_str} after the cutoff"
        if check_real_bool_in:
            assert last_date == cutoff_date, f"❌ {key_str} ends on {last_date}, not on the cutoff"
    # RETURN THE DATES
    return {key_str: str(last_date) for key_str, last_date in last_date_dict_in.items()}

# FUNCTION: WARN ABOUT EARLIER ENTRIES OF A STEP AND CHECK THE BUDGET
def check_step_trial_dict(trial_log_pdf_in, step_str_in, new_trial_count_in):
    """
    Counts the exp13 entries already logged by this step (note prefix "exp13 <step>") and asserts that the new entries
    keep exp13 within its budget and equal the step's expected count.

    Args:
        trial_log_pdf_in (pd.DataFrame): The trial log
        step_str_in (str): "step01" .. "step04"
        new_trial_count_in (int): Entries about to be logged

    Returns:
        dict: experiment_trial_count, step_trial_count
    """
    # COUNT THE ENTRIES
    experiment_pdf = trial_log_pdf_in[trial_log_pdf_in["experiment"] == exp_config.EXPERIMENT_NAME] if len(trial_log_pdf_in) else trial_log_pdf_in
    step_trial_count = int(experiment_pdf["note"].fillna("").str.startswith(f"exp13 {step_str_in}").sum()) if len(experiment_pdf) else 0
    if step_trial_count:
        print(f"⚠️ The trial log already holds {step_trial_count} entries of exp13 {step_str_in}: this run ADDS trials")
    # CHECK THE BUDGET AND THE EXPECTED COUNT
    assert new_trial_count_in == exp_config.EXPECTED_STEP_TRIAL_COUNT_DICT[step_str_in], f"❌ {new_trial_count_in} entries for {step_str_in}"
    assert len(experiment_pdf) + new_trial_count_in <= exp_config.TRIAL_BUDGET, "❌ Trial budget exceeded"
    # RETURN THE COUNTS
    return {"experiment_trial_count": int(len(experiment_pdf)), "step_trial_count": step_trial_count}

"""
Placebo And Information Tests (step 03)
"""

# FUNCTION: SHIFT THE VIX FEATURES CIRCULARLY (ONE NULL RUN)
def get_shifted_vix_feature_pdf(vix_feature_pdf_in, run_idx_in, seed_in=exp_config.NULL_SEED, share_range_in=exp_config.NULL_SHIFT_SHARE_RANGE):
    """
    Circularly shifts every VIX feature column together by k rows over the loaded rows (k = round(u x rows), u uniform in
    the share range, seed = seed_in + run_idx_in; exp08's convention); session_idx and date stay in place (so does SPY).

    Args:
        vix_feature_pdf_in (pd.DataFrame): VIX features (session_idx, date + feature columns)
        run_idx_in (int): Null run index
        seed_in (int): Base seed
        share_range_in (tuple): Range of u

    Returns:
        tuple: (shifted_pdf, shift_int)
    """
    # DRAW THE SHIFT
    rng = np.random.default_rng(seed_in + run_idx_in)
    shift_int = int(round(rng.uniform(share_range_in[0], share_range_in[1]) * len(vix_feature_pdf_in)))
    # SHIFT THE FEATURE BLOCK
    feature_col_str_list = [col for col in vix_feature_pdf_in.columns if col not in ["session_idx", "date"]]
    shifted_pdf = vix_feature_pdf_in.copy()
    shifted_pdf[feature_col_str_list] = np.roll(vix_feature_pdf_in[feature_col_str_list].to_numpy(), shift_int, axis=0)
    # RETURN THE TABLE AND THE SHIFT
    return shifted_pdf, shift_int

# FUNCTION: RUN SOME VIX-SHIFT NULL RUNS (P1, P2)
def run_vix_placebo_run_list(run_idx_list_in, ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in, date1_in, date2_in, candidate_dict_list_in,
                             seed_in=exp_config.NULL_SEED, share_range_in=exp_config.NULL_SHIFT_SHARE_RANGE):
    """
    For each run: shift the VIX features, rebuild exp12's rules on them, replay every candidate over the window.

    Args:
        run_idx_list_in (list[int]): Null run indexes
        ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in: The span data (real VIX features)
        date1_in, date2_in (datetime.date | str): Window bounds
        candidate_dict_list_in (list[dict]): exp12 candidates (the six)
        seed_in (int): Base seed
        share_range_in (tuple): Range of u

    Returns:
        list[dict]: run_idx, shift_session_count, total_<candidate> per candidate, max_total
    """
    # LIST TO HOLD THE RUNS
    run_dict_list = []
    # ITERATE OVER THE RUNS
    for run_idx in run_idx_list_in:
        # SHIFT THE FEATURES AND REBUILD THE RULES
        shifted_pdf, shift_int = get_shifted_vix_feature_pdf(vix_feature_pdf_in, int(run_idx), seed_in, share_range_in)
        rule_builder_func = get_rule_builder_func(daily_pdf_in, shifted_pdf)
        # REPLAY EVERY CANDIDATE
        run_dict = {"run_idx": int(run_idx), "shift_session_count": shift_int}
        for candidate_dict in candidate_dict_list_in:
            run_dict[f"total_{candidate_dict['candidate_name']}"] = float(replay_rule_dict(ohlcv_array_dict_in, rule_builder_func(candidate_dict), date1_in, date2_in)["metric_dict"]["total_return"])
        run_dict["max_total"] = max(run_dict[f"total_{candidate_dict['candidate_name']}"] for candidate_dict in candidate_dict_list_in)
        run_dict_list.append(run_dict)
    # RETURN THE RUNS
    return run_dict_list

# FUNCTION: RUN SOME RANDOM-FAMILY RUNS (P3, P4)
def run_random_family_run_list(run_idx_list_in, ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in, date1_in, date2_in, family_str_in, probability_dict_in,
                               seed_in=config.RANDOM_SEED, exit_seed_offset_in=exp_config.RANDOM_EXIT_SEED_OFFSET):
    """
    exp04's random families around the frozen E1M1 (so.core.replay_walk_forward's convention):
        random_reentry  E1M1's exits, re-entry with probability p per cash decision (run i: seed + i)
        random_exit     exits with probability p per invested decision (run i: seed + offset + i), E1M1's re-entry rule

    Args:
        run_idx_list_in (list[int]): Run indexes
        ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in: The span data
        date1_in, date2_in (datetime.date | str): Window bounds
        family_str_in (str): "random_reentry" or "random_exit"
        probability_dict_in (dict): exit_probability, reentry_probability (matched to the frozen path)
        seed_in (int): Base seed
        exit_seed_offset_in (int): Seed offset of the random exits

    Returns:
        list[dict]: run_idx, total_return
    """
    # BUILD THE FROZEN RULE
    exit_arr, reentry_func, reason_str = get_frozen_rule_tuple(daily_pdf_in, vix_feature_pdf_in)
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    # LIST TO HOLD THE RUNS
    run_dict_list = []
    # ITERATE OVER THE RUNS
    for run_idx in run_idx_list_in:
        # BUILD THE RANDOMIZED RULE
        if family_str_in == "random_exit":
            random_exit_arr = np.random.default_rng(seed_in + exit_seed_offset_in + int(run_idx)).random(session_count) < probability_dict_in["exit_probability"]
            rule_tuple = (random_exit_arr, reentry_func, reason_str)
        elif family_str_in == "random_reentry":
            rule_tuple = (exit_arr, get_random_reentry_func(probability_dict_in["reentry_probability"], seed_in + int(run_idx)), "random")
        else:
            raise ValueError(f"❌ Unknown family {family_str_in}")
        # REPLAY IT
        run_dict_list.append({"run_idx": int(run_idx), "total_return": float(replay_rule_dict(ohlcv_array_dict_in, rule_tuple, date1_in, date2_in)["metric_dict"]["total_return"])})
    # RETURN THE RUNS
    return run_dict_list

# FUNCTION: RUN NULL RUNS IN PARALLEL PROCESSES
def run_parallel_null_pdf(run_func_in, run_count_in, job_count_in=exp_config.JOB_COUNT, chunk_count_in=None, **run_kwargs):
    """
    Splits the run indexes 0 .. run_count - 1 into chunks and runs them in parallel processes (joblib); every run is
    seeded by its index, so the result does not depend on the number of processes or chunks.

    Args:
        run_func_in (function): run_vix_placebo_run_list or run_random_family_run_list
        run_count_in (int): Runs
        job_count_in (int): Processes (-1 = all cores, 1 = sequential)
        chunk_count_in (int | None): Chunks (None = 4 per core, at most one per run)
        run_kwargs: Arguments of the run function

    Returns:
        pd.DataFrame: One row per run, sorted by run_idx
    """
    # SPLIT THE RUNS INTO CHUNKS
    chunk_count = chunk_count_in or max(1, min(int(run_count_in), 4 * (os.cpu_count() or 1)))
    chunk_list = [chunk.tolist() for chunk in np.array_split(np.arange(int(run_count_in)), chunk_count) if len(chunk)]
    # RUN THE CHUNKS
    if job_count_in == 1:
        result_list = [run_func_in(chunk, **run_kwargs) for chunk in chunk_list]
    else:
        from joblib import Parallel, delayed
        result_list = Parallel(n_jobs=job_count_in)(delayed(run_func_in)(chunk, **run_kwargs) for chunk in chunk_list)
    # RETURN THE RUNS
    return pd.DataFrame([run_dict for run_list in result_list for run_dict in run_list]).sort_values("run_idx").reset_index(drop=True)

# FUNCTION: SUMMARIZE A NULL DISTRIBUTION AGAINST THE REAL VALUE
def get_null_summary_dict(null_arr_in, real_value_in):
    """
    p = (1 + runs >= real) / (runs + 1); rank of the real value among the runs and itself (1 = highest); median, 5th and
    95th percentiles of the null.

    Args:
        null_arr_in (np.ndarray): Null values
        real_value_in (float): Real value

    Returns:
        dict: run_count, real_value, null_median, null_p05, null_p95, p_value, real_rank, runs_at_or_above_real
    """
    # COLLECT THE NULL
    null_arr = np.asarray(null_arr_in, dtype=float)
    at_or_above_count = int((null_arr >= real_value_in).sum())
    # RETURN THE SUMMARY
    return {"run_count": int(len(null_arr)), "real_value": float(real_value_in), "null_median": float(np.median(null_arr)),
            "null_p05": float(np.percentile(null_arr, 5)), "null_p95": float(np.percentile(null_arr, 95)),
            "p_value": float((1 + at_or_above_count) / (len(null_arr) + 1)), "real_rank": int(1 + (null_arr > real_value_in).sum()),
            "runs_at_or_above_real": at_or_above_count}

"""
Episode Reports (step 04) And Verdict
"""

# FUNCTION: GET THE LOG EXCESS OVER SUB-SPANS OF A PATH
def get_span_log_excess_pdf(strategy_equity_pdf_in, buy_hold_equity_pdf_in, span_tuple_list_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Log excess over buy-and-hold inside each sub-span: sum over its sessions of log(1 + r_path) - log(1 + r_bh), and the
    same annualized (x 252 / sessions).

    Args:
        strategy_equity_pdf_in, buy_hold_equity_pdf_in (pd.DataFrame): Daily equity over the same sessions
        span_tuple_list_in (list[tuple[str, str]]): Sub-spans (inclusive)
        initial_capital_in (float): Starting equity of both paths

    Returns:
        pd.DataFrame: span_start, span_end, session_count, strategy_log_return, buy_hold_log_return, log_excess, annualized_log_excess
    """
    # CALCULATE THE DAILY RETURNS AND MERGE THEM
    merged_pdf = get_chained_daily_return_pdf([strategy_equity_pdf_in], initial_capital_in).merge(
        get_chained_daily_return_pdf([buy_hold_equity_pdf_in], initial_capital_in), on="date", suffixes=("_strategy", "_buy_hold"))
    date_arr = pd.to_datetime(merged_pdf["date"]).dt.date.to_numpy()
    # LIST TO HOLD THE ROWS
    row_dict_list = []
    for span_start_str, span_end_str in span_tuple_list_in:
        mask_arr = (date_arr >= pd.Timestamp(span_start_str).date()) & (date_arr <= pd.Timestamp(span_end_str).date())
        strategy_log, buy_hold_log = float(np.log1p(merged_pdf.loc[mask_arr, "daily_return_strategy"]).sum()), float(np.log1p(merged_pdf.loc[mask_arr, "daily_return_buy_hold"]).sum())
        row_dict_list.append({"span_start": span_start_str, "span_end": span_end_str, "session_count": int(mask_arr.sum()), "strategy_log_return": strategy_log,
                              "buy_hold_log_return": buy_hold_log, "log_excess": strategy_log - buy_hold_log,
                              "annualized_log_excess": (strategy_log - buy_hold_log) * config.TRADING_DAYS_PER_YEAR / mask_arr.sum() if mask_arr.sum() else np.nan})
    # RETURN THE TABLE
    return pd.DataFrame(row_dict_list)

# FUNCTION: SPLIT THE PRODUCT OF S / R BY RE-ENTRY REASON
def get_reason_split_pdf(vix_scorecard_pdf_in):
    """
    Per re-entry reason (M1, original rule, end of data): episodes, product of S/R, sum of log(S/R), episodes bought back lower.

    Args:
        vix_scorecard_pdf_in (pd.DataFrame): Scorecard with reentry_trigger, s_over_r, log_share_gain

    Returns:
        pd.DataFrame: reentry_trigger, episode_count, product_s_over_r, log_share_gain_sum, bought_back_lower_count
    """
    # IF THERE IS NO EPISODE
    if vix_scorecard_pdf_in.empty:
        return pd.DataFrame(columns=["reentry_trigger", "episode_count", "product_s_over_r", "log_share_gain_sum", "bought_back_lower_count"])
    # RETURN THE SPLIT
    split_pdf = vix_scorecard_pdf_in.groupby("reentry_trigger").agg(episode_count=("s_over_r", "size"), log_share_gain_sum=("log_share_gain", "sum"),
                                                                     bought_back_lower_count=("s_over_r", lambda s: int((s > 1).sum()))).reset_index()
    split_pdf["product_s_over_r"] = np.exp(split_pdf["log_share_gain_sum"])
    return split_pdf[["reentry_trigger", "episode_count", "product_s_over_r", "log_share_gain_sum", "bought_back_lower_count"]]

# FUNCTION: APPLY THE PRE-REGISTERED VERDICT RULE (PROTOCOL.md §8)
def get_verdict_dict(stress_total_in, stress_buy_hold_total_in, dev_beat_count_in, stress_beat_count_in, p2_in, equity_ratio_without_top1_in,
                     delayed_total_in, cost_total_in, dev_buy_hold_total_in):
    """
    R1 STRESS       frozen E1M1's total return >= buy-and-hold's over STRESS
    R2 PLATEAU      >= 24 of 36 variants beat buy-and-hold on DEV and >= 18 on STRESS
    R3 INFORMATION  p2 <= 0.05
    R4 EPISODES     final equity / buy-and-hold without the single best episode > 1 (DEV)
    R5 EXECUTION    one-session-delayed E1M1 and 5-cent-slippage E1M1 each beat buy-and-hold under exp12's costs (DEV)
    "ROBUST CANDIDATE PENDING REVIEW" only if all hold, otherwise "E1M1 IS NOT ROBUST".

    Args:
        stress_total_in, stress_buy_hold_total_in (float): STRESS total returns
        dev_beat_count_in, stress_beat_count_in (int): Variants beating buy-and-hold
        p2_in (float): Selection-aware p
        equity_ratio_without_top1_in (float): Equity ratio without the best episode
        delayed_total_in, cost_total_in (float): DEV total returns of the delayed and 5-cent paths
        dev_buy_hold_total_in (float): DEV buy-and-hold total return under exp12's costs

    Returns:
        dict: r1 .. r5 (bool), failed_list, verdict_str
    """
    # EVALUATE THE CRITERIA
    criterion_dict = {"r1_stress": bool(stress_total_in >= stress_buy_hold_total_in),
                      "r2_plateau": bool(dev_beat_count_in >= exp_config.R2_DEV_MIN_COUNT and stress_beat_count_in >= exp_config.R2_STRESS_MIN_COUNT),
                      "r3_information": bool(p2_in <= exp_config.R3_MAX_P),
                      "r4_episodes": bool(equity_ratio_without_top1_in > 1),
                      "r5_execution": bool(delayed_total_in > dev_buy_hold_total_in and cost_total_in > dev_buy_hold_total_in)}
    failed_list = [key_str for key_str, value in criterion_dict.items() if not value]
    # RETURN THE VERDICT
    return {**criterion_dict, "failed_list": failed_list, "verdict_str": "ROBUST CANDIDATE PENDING REVIEW" if not failed_list else "E1M1 IS NOT ROBUST"}
