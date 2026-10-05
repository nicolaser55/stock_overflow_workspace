import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp03_ath_exit import config as exp_config
# IMPORT EXIT AND RE-ENTRY SIMULATION FUNCTIONS
from so.core.reentry_simulation import simulate_stop_reentry_dict, get_fixed_delay_reentry_func, get_random_reentry_func

"""
Rules: exp03_ath_exit ("sell at strength", PROTOCOL.md §4)

State machine (so.core.reentry_simulation, no stop):
    INVESTED --(15:58 close within x of the all-time high)--> CASH      (sell at the 15:59 open)
    CASH     --(buy-back rule True at the 15:58 decision)---> INVESTED  (buy at the 15:59 open)
    CASH     --(MAX_CASH_SESSIONS decisions in cash)--------> INVESTED  (forced buy-back)

    - all-time high (ATH): so.features.daily_features "ath_drawdown_pct" = decision close / highest high since
      2005-01-03 (previous sessions and today up to the decision bar) - 1. SPY's 2000 peak is not in the data, so
      2005-2006 highs are pseudo-ATHs.
    - buy-back rules: after a fixed number of cash decisions ("delay_n"), or when the 15:58 close is d below the sale
      fill price ("dip_<d>pct").

The same identity as exp02 applies: an episode that sells at S and buys back at R ends with S / R times the shares, so a
rule beats buy-and-hold only if, on average, it buys back LOWER than it sold.
"""

"""
Rule Definitions
"""

# FUNCTION: GET THE RULE CANDIDATES
def get_rule_candidate_list(ath_within_list_in=exp_config.ATH_WITHIN_LIST, delay_list_in=exp_config.BUYBACK_DELAY_LIST,
                            dip_list_in=exp_config.BUYBACK_DIP_LIST):
    """
    Lists the rule candidates in a fixed order (the order is the last tie-break of the selection).

    Args:
        ath_within_list_in (list[float]): Exit thresholds
        delay_list_in (list[int]): Fixed-delay buy-backs
        dip_list_in (list[float]): Dip buy-backs

    Returns:
        list[dict]: ath_within, rule ("delay_5", "dip_2pct", ...), buyback_type ("delay" / "dip"), buyback_value, rule_order
    """
    # LIST TO HOLD THE CANDIDATES
    candidate_dict_list = []
    # ITERATE OVER THE EXIT THRESHOLDS
    for ath_within in ath_within_list_in:
        # ADD THE FIXED-DELAY BUY-BACKS
        for delay in delay_list_in:
            candidate_dict_list.append({"ath_within": float(ath_within), "rule": f"delay_{int(delay)}", "buyback_type": "delay", "buyback_value": float(delay)})
        # ADD THE DIP BUY-BACKS
        for dip in dip_list_in:
            candidate_dict_list.append({"ath_within": float(ath_within), "rule": f"dip_{int(round(dip * 100))}pct", "buyback_type": "dip", "buyback_value": float(dip)})
    # ADD THE ORDER
    for order_idx, candidate_dict in enumerate(candidate_dict_list):
        candidate_dict["rule_order"] = order_idx
    # RETURN THE CANDIDATES
    return candidate_dict_list

# FUNCTION: GET THE EXIT SIGNAL OF A THRESHOLD
def get_ath_exit_signal_arr(daily_pdf_in, ath_within_in):
    """
    Returns, per session position, whether the 15:58 close is within ath_within_in of the all-time high.

    Args:
        daily_pdf_in (pd.DataFrame): Output of so.features.daily_features.get_daily_feature_pdf
        ath_within_in (float): Exit threshold (0.01 = within 1%)

    Returns:
        np.ndarray: Bool per session position
    """
    # RETURN THE SIGNAL
    return daily_pdf_in["ath_drawdown_pct"].to_numpy(dtype=float) >= -ath_within_in

# FUNCTION: GET THE DIP BUY-BACK RULE
def get_dip_reentry_func(decision_close_arr_in, dip_float_in):
    """
    Buys back when the decision close is dip_float_in below the sale fill price of the episode.

    Args:
        decision_close_arr_in (np.ndarray): 15:58 close per session position
        dip_float_in (float): Dip (0.05 = 5% below the sale price)

    Returns:
        function: Re-entry rule f(session_idx, cash_session_count, episode_dict) -> bool
    """
    # RETURN THE RULE
    return lambda session_idx, cash_session_count, episode_dict: bool(decision_close_arr_in[session_idx] <= episode_dict["exit_fill_price"] * (1 - dip_float_in))

# FUNCTION: GET THE BUY-BACK RULE OF A CANDIDATE
def get_buyback_func_tuple(candidate_dict_in, daily_pdf_in):
    """
    Returns the re-entry rule and its reason label for a candidate.

    Args:
        candidate_dict_in (dict): One element of get_rule_candidate_list
        daily_pdf_in (pd.DataFrame): Daily table (decision_close)

    Returns:
        tuple: (re-entry rule, reason string "delay" / "dip")
    """
    # IF THE BUY-BACK IS A FIXED DELAY
    if candidate_dict_in["buyback_type"] == "delay":
        return get_fixed_delay_reentry_func(int(candidate_dict_in["buyback_value"])), "delay"
    # OTHERWISE THE BUY-BACK IS A DIP
    return get_dip_reentry_func(daily_pdf_in["decision_close"].to_numpy(dtype=float), float(candidate_dict_in["buyback_value"])), "dip"

"""
Simulation
"""

# FUNCTION: SIMULATE A RULE OVER A WINDOW
def simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, date1_in, date2_in, candidate_dict_in, exit_signal_arr_in=None, reentry_func_tuple_in=None, **simulation_kwargs):
    """
    Simulates one rule (or a baseline variant of it) over a window: start invested, no stop, exit on the signal, buy back
    with the rule, forced buy-back after MAX_CASH_SESSIONS decisions.

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        daily_pdf_in (pd.DataFrame): Daily table (indexed by session position)
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        candidate_dict_in (dict): Rule candidate
        exit_signal_arr_in (np.ndarray | None): Exit signal override (random exit baseline); None = the ATH signal
        reentry_func_tuple_in (tuple | None): (re-entry rule, reason) override (random buy-back baseline); None = the rule
        **simulation_kwargs: Cost overrides for simulate_stop_reentry_dict

    Returns:
        dict: Output of so.core.reentry_simulation.simulate_stop_reentry_dict
    """
    # DEFINE THE EXIT SIGNAL AND THE BUY-BACK RULE
    exit_signal_arr = exit_signal_arr_in if exit_signal_arr_in is not None else get_ath_exit_signal_arr(daily_pdf_in, candidate_dict_in["ath_within"])
    reentry_func, reason_str = reentry_func_tuple_in if reentry_func_tuple_in is not None else get_buyback_func_tuple(candidate_dict_in, daily_pdf_in)
    # RETURN THE SIMULATION (NO STOP: NO VOLATILITY, NO MULTIPLIER)
    return simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, np.full(len(daily_pdf_in), np.nan), None, reentry_func, reason_str,
                                      exit_signal_arr_in=exit_signal_arr, max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS, **simulation_kwargs)

# FUNCTION: GET THE METRICS OF A RULE SIMULATION
def get_rule_metric_dict(simulation_dict_in, buy_hold_total_return_in):
    """
    Collects the reported metrics of a rule simulation.

    Args:
        simulation_dict_in (dict): Output of simulate_rule_dict
        buy_hold_total_return_in (float): Buy-and-hold total return over the same window

    Returns:
        dict: total_return, excess_return, sharpe_ratio, max_drawdown, exit_count, forced_reentry_count, cash_session_pct,
              mean_cash_sessions, bought_back_lower_pct, mean_log_share_gain
    """
    # COLLECT THE METRICS AND THE EPISODES
    metric_dict, episode_pdf = simulation_dict_in["metric_dict"], simulation_dict_in["episode_pdf"]
    # RETURN THE METRICS
    return {"total_return": metric_dict["total_return"], "excess_return": metric_dict["total_return"] - buy_hold_total_return_in,
            "sharpe_ratio": metric_dict["sharpe_ratio"], "max_drawdown": metric_dict["max_drawdown"], "exit_count": metric_dict["signal_exit_count"],
            "forced_reentry_count": metric_dict["forced_reentry_count"], "cash_session_pct": metric_dict["cash_session_pct"],
            "mean_cash_sessions": metric_dict["mean_cash_sessions"], "bought_back_lower_pct": metric_dict["positive_episode_pct"],
            "mean_log_share_gain": float(np.log(episode_pdf["exit_fill_price"] / episode_pdf["reentry_fill_price"]).mean()) if len(episode_pdf) else np.nan}

"""
Random Baselines (PROTOCOL.md §7)
"""

# FUNCTION: GET A RANDOM EXIT SIGNAL
def get_random_exit_signal_arr(session_count_in, exit_probability_in, seed_in):
    """
    Random exit baseline: at every decision while invested, sell with a fixed probability (matched to the rule's exits per
    invested decision). The buy-back rule is unchanged, so the comparison isolates the ATH exit signal.

    Args:
        session_count_in (int): Number of sessions in the data (one draw per session position)
        exit_probability_in (float): Exit probability per invested decision
        seed_in (int): Random seed

    Returns:
        np.ndarray: Bool per session position
    """
    # RETURN THE DRAWS
    return np.random.default_rng(seed_in).random(session_count_in) < exit_probability_in

# FUNCTION: GET THE MATCHED PROBABILITIES OF THE RANDOM BASELINES
def get_random_baseline_probability_dict(simulation_dict_in):
    """
    Matches the random baselines to the rule's activity in the window.

        exit probability    = exits / invested decisions (sessions in the window x (1 - cash share))
        buy-back probability = 1 / mean cash decisions per episode (every episode, including one open at the window end)

    Args:
        simulation_dict_in (dict): Output of simulate_rule_dict

    Returns:
        dict: exit_probability, buyback_probability (NaN when the rule never exited in the window)
    """
    # COLLECT THE METRICS AND THE EPISODES
    metric_dict, episode_pdf = simulation_dict_in["metric_dict"], simulation_dict_in["episode_pdf"]
    session_count = len(simulation_dict_in["daily_equity_pdf"])
    invested_decision_count = session_count * (1 - metric_dict["cash_session_pct"])
    # CALCULATE THE MATCHED PROBABILITIES
    exit_probability = metric_dict["signal_exit_count"] / invested_decision_count if metric_dict["signal_exit_count"] > 0 and invested_decision_count > 0 else np.nan
    mean_cash_sessions = float(episode_pdf["cash_session_count"].mean()) if not episode_pdf.empty else np.nan
    buyback_probability = 1.0 / mean_cash_sessions if np.isfinite(mean_cash_sessions) and mean_cash_sessions > 0 else np.nan
    # RETURN THE PROBABILITIES
    return {"exit_probability": exit_probability, "buyback_probability": buyback_probability}

"""
Exploration (step 01, 2005-2014 only)
"""

# FUNCTION: COMPARE THE FORWARD RETURNS OF EVENT DAYS WITH ALL DAYS
def get_event_forward_pdf(daily_pdf_in, event_dict_in, window_end_str_in, horizon_list_in=exp_config.EXPLORATION_HORIZON_LIST,
                          iteration_count_in=exp_config.EXPLORATION_BOOTSTRAP_ITERATION_COUNT, seed_in=config.RANDOM_SEED):
    """
    For every event (bool mask per session) and horizon n: the mean forward log return from the 15:59 fill of event days
    to the 15:59 fill n sessions later, compared with every day of the window, with a monthly block bootstrap of the
    difference. Event days must be in the window (date <= window end); forward fills may lie after it.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (fill_open, date), cut at the exploration data cutoff
        event_dict_in (dict): Event name -> bool mask per session position
        window_end_str_in (str): Last event date
        horizon_list_in (list[int]): Forward horizons (sessions)
        iteration_count_in (int): Bootstrap iterations
        seed_in (int): Random seed (one generator for the whole table, in event then horizon order)

    Returns:
        pd.DataFrame: event, horizon, episode_count, event_day_count, event_mean_log_return, all_mean_log_return, diff,
                      diff_ci_low, diff_ci_high, event_up_share, all_up_share
    """
    # COLLECT THE ARRAYS
    fill_open_arr = daily_pdf_in["fill_open"].to_numpy(dtype=float)
    in_window_arr = np.array([date_object <= pd.Timestamp(window_end_str_in).date() for date_object in daily_pdf_in["date"]])
    month_arr = pd.to_datetime(daily_pdf_in["date"]).dt.to_period("M").astype(str).to_numpy()
    # CREATE THE RANDOM GENERATOR
    rng = np.random.default_rng(seed_in)
    # LIST TO HOLD THE ROWS
    row_dict_list = []
    # ITERATE OVER THE EVENTS AND THE HORIZONS
    for event_str, event_mask_arr in event_dict_in.items():
        for horizon in horizon_list_in:
            # COLLECT THE DAYS WITH A FORWARD RETURN
            idx_arr = np.flatnonzero(in_window_arr & (np.arange(len(daily_pdf_in)) + horizon < len(daily_pdf_in)))
            return_arr, event_arr = np.log(fill_open_arr[idx_arr + horizon] / fill_open_arr[idx_arr]), event_mask_arr[idx_arr]
            # SUM THE RETURNS PER MONTH
            month_code_arr, month_label_arr = pd.factorize(month_arr[idx_arr])
            month_count = len(month_label_arr)
            all_sum_arr, all_count_arr = np.bincount(month_code_arr, return_arr, month_count), np.bincount(month_code_arr, minlength=month_count).astype(float)
            event_sum_arr, event_count_arr = np.bincount(month_code_arr, return_arr * event_arr, month_count), np.bincount(month_code_arr, event_arr.astype(float), month_count)
            # RESAMPLE THE MONTHS
            weight_mat = rng.multinomial(month_count, np.full(month_count, 1 / month_count), size=iteration_count_in)
            with np.errstate(invalid="ignore", divide="ignore"):
                boot_diff_arr = (weight_mat @ event_sum_arr) / (weight_mat @ event_count_arr) - (weight_mat @ all_sum_arr) / (weight_mat @ all_count_arr)
            # COUNT THE SEPARATE EPISODES (EVENT DAYS MORE THAN EPISODE_GAP_SESSIONS APART)
            event_idx_arr = np.flatnonzero(event_mask_arr & in_window_arr)
            episode_count = int(1 + (np.diff(event_idx_arr) > exp_config.EPISODE_GAP_SESSIONS).sum()) if len(event_idx_arr) else 0
            # APPEND THE ROW
            row_dict_list.append({"event": event_str, "horizon": horizon, "episode_count": episode_count, "event_day_count": int(event_arr.sum()),
                                  "event_mean_log_return": return_arr[event_arr].mean(), "all_mean_log_return": return_arr.mean(),
                                  "diff": return_arr[event_arr].mean() - return_arr.mean(),
                                  "diff_ci_low": np.nanpercentile(boot_diff_arr, 2.5), "diff_ci_high": np.nanpercentile(boot_diff_arr, 97.5),
                                  "event_up_share": float((return_arr[event_arr] > 0).mean()), "all_up_share": float((return_arr > 0).mean())})
    # RETURN THE TABLE
    return pd.DataFrame(row_dict_list)
