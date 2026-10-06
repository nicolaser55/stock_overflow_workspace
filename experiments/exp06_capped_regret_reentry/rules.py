import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp06_capped_regret_reentry import config as exp_config
# IMPORT THE WALK-FORWARD SCHEDULE AND THE REPLAY PERIODS
from so.core.schedule import get_walk_forward_fold_pdf
from so.core.continuous_replay import get_replay_period_pdf

"""
Rules: exp06_capped_regret_reentry (PROTOCOL.md §5; DATA-DEPENDENT FOLLOW-UP OF exp03)

State machine (so.core.reentry_simulation, no stop, continuous replay, no forced buy-back):
    INVESTED --(exit signal at the 15:58 decision, unless cooling off)--> CASH      (sell at the 15:59 open, fill S)
    CASH     --(buy-stop: 15:58 close >= S x (1 + b))------------------> INVESTED  (buy at the 15:59 open; no exit for
                                                                                    the next c decisions)
    CASH     --(recovery: 15:58 close above the 200-session average,
                after at least one close below it since the exit)------> INVESTED  (buy at the 15:59 open)

    exit signals   trend_ma200: ma200_dist_pct < 0 (exp04's textbook rule); ath_1pct: ath_drawdown_pct >= -1% (exp03)
    buy-stop       caps the cost of a wrong exit near b + costs: if the price rises after the sale, buy back at once
    recovery       if the price falls instead, buy back when the trend turns up again (for trend_ma200 this is exactly
                   exp04's re-entry, since its exit decision is already below the average)

Arithmetic (roadmap): with a share q of exits ended by the buy-stop (wrong exits), a mean gain G of the other episodes
and a round-trip cost k, the exits pay only if (1 - q) x G > q x (b + k).
"""

"""
Schedule And Candidates
"""

# FUNCTION: GET THE SCHEDULE AND THE REPLAY PERIODS
def get_schedule_tuple(session_date_list_in, train_years_in=exp_config.FIXED_TRAIN_WINDOW_YEARS, max_fold_count_in=None):
    """
    Builds the exp02-exp05 schedule (20-session embargo, folds that fit a 10-year window) and its replay periods.

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
def get_rule_candidate_list(exit_signal_order_dict_in=exp_config.EXIT_SIGNAL_ORDER_DICT, buy_stop_list_in=exp_config.BUY_STOP_LIST,
                            cooling_list_in=exp_config.COOLING_LIST):
    """
    Lists the 12 candidates in a fixed order (exit signal, then buy-stop, then cooling-off).

    Args:
        exit_signal_order_dict_in (dict): Exit signal name -> order
        buy_stop_list_in (list[float]): Buy-stops b
        cooling_list_in (list[int]): Cooling-off periods c

    Returns:
        list[dict]: exit_signal, exit_order, buy_stop, cooling
    """
    # RETURN THE GRID
    return [{"exit_signal": exit_signal, "exit_order": int(exit_order), "buy_stop": float(buy_stop), "cooling": int(cooling)}
            for exit_signal, exit_order in sorted(exit_signal_order_dict_in.items(), key=lambda item: item[1]) for buy_stop in buy_stop_list_in for cooling in cooling_list_in]

"""
Signals And Re-Entry
"""

# FUNCTION: GET AN EXIT SIGNAL
def get_exit_signal_arr(daily_pdf_in, exit_signal_str_in, ath_within_in=exp_config.ATH_WITHIN):
    """
    Returns the exit signal per session position (a missing feature never exits).

    Args:
        daily_pdf_in (pd.DataFrame): Output of so.features.daily_features.get_daily_feature_pdf
        exit_signal_str_in (str): "trend_ma200" or "ath_1pct"
        ath_within_in (float): ATH threshold of "ath_1pct"

    Returns:
        np.ndarray: Bool per session position
    """
    # IF THE SIGNAL IS THE TREND EXIT
    if exit_signal_str_in == "trend_ma200":
        return np.nan_to_num(daily_pdf_in["ma200_dist_pct"].to_numpy(dtype=float), nan=0.0) < 0
    # IF THE SIGNAL IS THE ATH EXIT
    if exit_signal_str_in == "ath_1pct":
        return np.nan_to_num(daily_pdf_in["ath_drawdown_pct"].to_numpy(dtype=float), nan=-np.inf) >= -ath_within_in
    # OTHERWISE THE SIGNAL IS UNKNOWN
    raise ValueError(f"unknown exit signal {exit_signal_str_in}")

# FUNCTION: GET THE CAPPED-REGRET RE-ENTRY RULE
def get_capped_reentry_func(daily_pdf_in, buy_stop_in, cooling_in):
    """
    Re-entry rule: buy-stop (close >= S x (1 + b); then no exit for cooling_in decisions) or recovery (close above the
    200-session average after at least one close below it from the exit decision on). Writes the trigger to
    episode_dict["reentry_trigger"] and the cooling-off to episode_dict["exit_block_sessions"].

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (decision_close, ma200_dist_pct)
        buy_stop_in (float): Buy-stop b
        cooling_in (int): Cooling-off c after a buy-stop re-entry

    Returns:
        function: Re-entry rule f(session_idx, cash_session_count, episode_dict) -> bool
    """
    # COLLECT THE ARRAYS
    decision_close_arr = daily_pdf_in["decision_close"].to_numpy(dtype=float)
    ma_dist_arr = np.nan_to_num(daily_pdf_in["ma200_dist_pct"].to_numpy(dtype=float), nan=0.0)
    below_cum_arr = np.cumsum(ma_dist_arr < 0)
    # FUNCTION: THE RULE
    def reentry_func(session_idx, cash_session_count, episode_dict):
        # BUY-STOP: THE PRICE ROSE b ABOVE THE SALE
        if decision_close_arr[session_idx] >= episode_dict["exit_fill_price"] * (1 + buy_stop_in):
            episode_dict.update({"reentry_trigger": "buy_stop", "exit_block_sessions": int(cooling_in)})
            return True
        # RECOVERY: ABOVE THE AVERAGE AFTER A CLOSE BELOW IT SINCE THE EXIT DECISION
        exit_session_idx = int(episode_dict["first_cash_session_idx"]) - 1
        below_since_exit = below_cum_arr[session_idx] - (below_cum_arr[exit_session_idx - 1] if exit_session_idx > 0 else 0)
        if below_since_exit > 0 and ma_dist_arr[session_idx] > 0:
            episode_dict.update({"reentry_trigger": "recovery", "exit_block_sessions": 0})
            return True
        # OTHERWISE STAY IN CASH
        return False
    # RETURN THE RULE
    return reentry_func

# FUNCTION: GET THE RULE BUILDER OF THE EXPERIMENT
def get_rule_builder_func(daily_pdf_in):
    """
    Returns f(candidate_dict) -> (exit_signal_arr, reentry_func, reason_str) for so.core.replay_walk_forward.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table

    Returns:
        function: Rule builder
    """
    # CACHE THE EXIT SIGNALS
    exit_dict = {}
    # FUNCTION: BUILD ONE CANDIDATE
    def rule_builder_func(candidate_dict_in):
        if candidate_dict_in["exit_signal"] not in exit_dict:
            exit_dict[candidate_dict_in["exit_signal"]] = get_exit_signal_arr(daily_pdf_in, candidate_dict_in["exit_signal"])
        return exit_dict[candidate_dict_in["exit_signal"]], get_capped_reentry_func(daily_pdf_in, candidate_dict_in["buy_stop"], candidate_dict_in["cooling"]), "rule"
    # RETURN THE BUILDER
    return rule_builder_func

"""
Reporting
"""

# FUNCTION: GET THE RE-ENTRY TRIGGERS AND THE ROADMAP ARITHMETIC OF A SIMULATION
def get_trigger_summary_dict(simulation_dict_in):
    """
    Counts the episodes by re-entry trigger and evaluates (1 - q) x G vs q x |L|: q = share of closed episodes ended by the
    buy-stop, G = mean log share gain of the other closed episodes, L = mean log share gain of the buy-stop episodes
    (negative: b plus the slippage).

    Args:
        simulation_dict_in (dict): Output of so.core.reentry_simulation.simulate_stop_reentry_dict

    Returns:
        dict: episode_count, buy_stop_count, recovery_count, open_count, wrong_exit_share, mean_gain_right, mean_loss_wrong,
              right_side, wrong_side
    """
    # COLLECT THE EPISODES
    episode_pdf = simulation_dict_in["episode_pdf"]
    if episode_pdf.empty:
        return {"episode_count": 0, "buy_stop_count": 0, "recovery_count": 0, "open_count": 0, "wrong_exit_share": np.nan,
                "mean_gain_right": np.nan, "mean_loss_wrong": np.nan, "right_side": np.nan, "wrong_side": np.nan}
    trigger_series = episode_pdf["reentry_trigger"] if "reentry_trigger" in episode_pdf.columns else pd.Series([np.nan] * len(episode_pdf))
    log_gain_arr = np.log(episode_pdf["exit_fill_price"].to_numpy(dtype=float) / episode_pdf["reentry_fill_price"].to_numpy(dtype=float))
    closed_arr = (episode_pdf["reentry_reason"] != "window_end").to_numpy()
    stop_arr, recovery_arr = (trigger_series == "buy_stop").to_numpy() & closed_arr, (trigger_series == "recovery").to_numpy() & closed_arr
    # CALCULATE THE ARITHMETIC
    closed_count = int(closed_arr.sum())
    wrong_share = float(stop_arr.sum() / closed_count) if closed_count else np.nan
    mean_gain_right = float(log_gain_arr[recovery_arr].mean()) if recovery_arr.any() else np.nan
    mean_loss_wrong = float(log_gain_arr[stop_arr].mean()) if stop_arr.any() else np.nan
    # RETURN THE SUMMARY
    return {"episode_count": int(len(episode_pdf)), "buy_stop_count": int(stop_arr.sum()), "recovery_count": int(recovery_arr.sum()), "open_count": int((~closed_arr).sum()),
            "wrong_exit_share": wrong_share, "mean_gain_right": mean_gain_right, "mean_loss_wrong": mean_loss_wrong,
            "right_side": (1 - wrong_share) * mean_gain_right if np.isfinite(wrong_share) and np.isfinite(mean_gain_right) else np.nan,
            "wrong_side": wrong_share * abs(mean_loss_wrong) if np.isfinite(wrong_share) and np.isfinite(mean_loss_wrong) else np.nan}
