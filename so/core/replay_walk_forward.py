import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION (SEED, COSTS)
from so import config
# IMPORT EXIT AND RE-ENTRY SIMULATION FUNCTIONS
from so.core.reentry_simulation import get_buy_and_hold_result_dict, get_random_reentry_func
# IMPORT THE EVALUATION FUNCTIONS (POOLED SELECTION)
from so.core.evaluation import get_pooled_selection_pdf
# IMPORT THE CONTINUOUS REPLAY FUNCTIONS
from so.core.continuous_replay import simulate_continuous_replay_dict, get_period_return_pdf, get_prior_only_period_candidate_dict, \
                                      get_session_assignment_arr, get_switching_rule_dict, get_episode_scorecard_pdf, get_replay_summary_dict, \
                                      get_log_excess_bootstrap_dict
# IMPORT THE EVALUATION FUNCTIONS (CHAINED DAILY RETURNS)
from so.core.evaluation import get_chained_daily_return_pdf

"""
Walk-Forward On A Continuous Replay (shared by the exit-rule experiments of the "stay invested" family: exp04, exp06, exp07)

Candidates are exit / re-entry rules without a trained model. A candidate is a dictionary of settings; the experiment
gives a rule builder f(candidate_dict) -> (exit_signal_arr, reentry_func, reentry_reason_str) that turns it into the
inputs of so.core.reentry_simulation.simulate_stop_reentry_dict (no trailing stop).

    1. CANDIDATE PATHS (after the fact): every candidate is replayed continuously over the replay periods (the validation
       quarters made non-overlapping, so.core.continuous_replay.get_replay_period_pdf). Its return in each period, minus
       buy-and-hold's return in the same period (buy-and-hold also replayed continuously), is its period score. Each
       (candidate, period) row is one validation trial.
    2. SELECTION: so.core.evaluation.get_pooled_selection_pdf on the period scores (mean over the last
       pooled_count_in periods, experiment tie-breaks).
    3. PRIOR-ONLY PATH (the honest estimate): the candidate selected at period f governs period f + 1. One continuous
       path from the start of the first governed period to the end of the last period switches rules at period
       boundaries while the position carries over. Buy-and-hold is replayed over the same span.
    4. BASELINES on the same span, same costs (the uninformed versions of the two informed components):
         random_exit_<i>     random exits with the path's exit frequency (exits per invested decision), the path's re-entry rule
         random_reentry_<i>  the path's exits, random re-entry with probability 1 / the path's mean cash decisions per episode
       The information test: the path must beat the median of each family (and buy-and-hold for the primary criterion).
    5. Cost sensitivity of the path at the shared slippage list; the episode scorecard of the path.
"""

"""
Candidate Paths
"""

# FUNCTION: COUNT THE SIGNAL EXITS OF A SIMULATION IN EVERY PERIOD
def get_period_exit_count_arr(simulation_dict_in, period_pdf_in):
    """
    Counts the SIGNAL exits whose sale date falls in each period.

    Args:
        simulation_dict_in (dict): Output of simulate_stop_reentry_dict
        period_pdf_in (pd.DataFrame): Replay periods

    Returns:
        np.ndarray: Exit count per period row
    """
    # COLLECT THE SALE DATES OF THE SIGNAL EXITS
    transaction_pdf = simulation_dict_in["transaction_pdf"]
    sell_date_arr = np.array([ts.date() for ts in transaction_pdf.loc[transaction_pdf["exit_reason"] == "SIGNAL", "sell_ts"]]) if not transaction_pdf.empty else np.array([])
    # RETURN THE COUNT PER PERIOD
    return np.array([int(((sell_date_arr >= row["period_start"]) & (sell_date_arr <= row["period_end"])).sum()) if len(sell_date_arr) else 0
                     for _, row in period_pdf_in.iterrows()])

# FUNCTION: REPLAY EVERY CANDIDATE AND SCORE IT PER PERIOD
def run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf_in, candidate_dict_list_in, rule_builder_func_in, untouched_start_date_str_in,
                              max_cash_sessions_in, block_month_count_in, alert_in=True):
    """
    Replays every candidate continuously over the periods and scores it per period against buy-and-hold.

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        period_pdf_in (pd.DataFrame): Replay periods (so.core.continuous_replay.get_replay_period_pdf)
        candidate_dict_list_in (list[dict]): Candidates (settings; a "candidate_idx" key is added in this order)
        rule_builder_func_in (function): f(candidate_dict) -> (exit_signal_arr, reentry_func, reentry_reason_str)
        untouched_start_date_str_in (str): First date of the untouched data
        max_cash_sessions_in (int | None): Forced re-entry after this many cash decisions (None = never)
        block_month_count_in (int): Months per block of the log-excess bootstrap
        alert_in (bool): Display one line per candidate

    Returns:
        dict: candidate_period_pdf (one row per candidate and period: fold_id = period_id, settings, valid_total_return,
              valid_buy_hold_total_return, valid_excess_return, valid_in_market_pct, valid_signal_exit_count),
              candidate_summary_pdf (one row per candidate: replay summary), simulation_dict_list, buy_hold_dict
    """
    # DEFINE THE SPAN AND REPLAY BUY AND HOLD
    span_start, span_end = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end)
    buy_hold_period_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], period_pdf_in)
    # LISTS TO HOLD THE ROWS AND THE SIMULATIONS
    period_pdf_list, summary_dict_list, simulation_dict_list = [], [], []
    # ITERATE OVER THE CANDIDATES
    for candidate_idx, candidate_dict in enumerate(candidate_dict_list_in):
        # BUILD THE RULE AND REPLAY IT
        exit_signal_arr, reentry_func, reason_str = rule_builder_func_in(candidate_dict)
        simulation_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, untouched_start_date_str_in,
                                                          volatility_arr_in=np.full(len(ohlcv_array_dict_in["session_date_list"]), np.nan), stop_k_in=None,
                                                          reentry_func_in=reentry_func, reentry_reason_str_in=reason_str, exit_signal_arr_in=exit_signal_arr,
                                                          max_cash_sessions_in=max_cash_sessions_in)
        simulation_dict_list.append(simulation_dict)
        # SCORE THE CANDIDATE PER PERIOD
        candidate_period_pdf = get_period_return_pdf(simulation_dict["daily_equity_pdf"], period_pdf_in)
        period_pdf_list.append(pd.DataFrame({"fold_id": candidate_period_pdf["period_id"].to_numpy(), "candidate_idx": candidate_idx,
                                             **{key: [value] * len(candidate_period_pdf) for key, value in candidate_dict.items()},
                                             "valid_start": candidate_period_pdf["period_start"].to_numpy(), "valid_end": candidate_period_pdf["period_end"].to_numpy(),
                                             "valid_total_return": candidate_period_pdf["total_return"].to_numpy(),
                                             "valid_buy_hold_total_return": buy_hold_period_pdf["total_return"].to_numpy(),
                                             "valid_excess_return": candidate_period_pdf["total_return"].to_numpy() - buy_hold_period_pdf["total_return"].to_numpy(),
                                             "valid_in_market_pct": candidate_period_pdf["in_market_pct"].to_numpy(),
                                             "valid_signal_exit_count": get_period_exit_count_arr(simulation_dict, period_pdf_in)}))
        # SUMMARIZE THE WHOLE PATH
        summary_dict = get_replay_summary_dict(simulation_dict["daily_equity_pdf"], buy_hold_dict["daily_equity_pdf"], period_pdf_in, block_month_count_in)
        summary_dict_list.append({"candidate_idx": candidate_idx, **candidate_dict, "exit_count": simulation_dict["metric_dict"]["signal_exit_count"],
                                  "mean_cash_sessions": simulation_dict["metric_dict"]["mean_cash_sessions"],
                                  "bought_back_lower_pct": simulation_dict["metric_dict"]["positive_episode_pct"],
                                  **{key: value for key, value in summary_dict.items() if key != "baselines_beaten"}})
        # DISPLAY INFORMATION
        print(f"\tcandidate {candidate_idx} {candidate_dict}: total {summary_dict['strategy_total_return']:.2%} vs buy & hold {summary_dict['buy_hold_total_return']:.2%}"
              f" | in market {summary_dict['in_market_pct']:.1%} | exits {simulation_dict['metric_dict']['signal_exit_count']}") if alert_in else None
    # RETURN THE RESULTS
    return {"candidate_period_pdf": pd.concat(period_pdf_list, ignore_index=True), "candidate_summary_pdf": pd.DataFrame(summary_dict_list),
            "simulation_dict_list": simulation_dict_list, "buy_hold_dict": buy_hold_dict}

"""
Prior-Only Path With Baselines
"""

# FUNCTION: GET THE MATCHED PROBABILITIES OF THE RANDOM BASELINES OF A PATH
def get_path_random_probability_dict(simulation_dict_in):
    """
    exit probability     = signal exits / invested decisions of the path
    re-entry probability = 1 / mean cash decisions per episode (every episode, including one open at the end)

    Args:
        simulation_dict_in (dict): Output of simulate_stop_reentry_dict

    Returns:
        dict: exit_probability, reentry_probability (NaN when the path never exited)
    """
    # COLLECT THE METRICS AND THE EPISODES
    metric_dict, episode_pdf = simulation_dict_in["metric_dict"], simulation_dict_in["episode_pdf"]
    invested_decision_count = len(simulation_dict_in["daily_equity_pdf"]) * (1 - metric_dict["cash_session_pct"])
    # CALCULATE THE PROBABILITIES
    exit_probability = metric_dict["signal_exit_count"] / invested_decision_count if metric_dict["signal_exit_count"] > 0 and invested_decision_count > 0 else np.nan
    mean_cash_sessions = float(episode_pdf["cash_session_count"].mean()) if not episode_pdf.empty else np.nan
    reentry_probability = 1.0 / mean_cash_sessions if np.isfinite(mean_cash_sessions) and mean_cash_sessions > 0 else np.nan
    # RETURN THE PROBABILITIES
    return {"exit_probability": exit_probability, "reentry_probability": reentry_probability}

# FUNCTION: RUN THE PRIOR-ONLY PATH, ITS BASELINES AND ITS SUMMARY
def run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf_in, candidate_period_pdf_in, candidate_dict_list_in, rule_builder_func_in,
                               key_col_str_list_in, tie_break_list_in, pooled_count_in, untouched_start_date_str_in, max_cash_sessions_in,
                               random_run_count_in, random_exit_seed_offset_in, block_month_count_in, seed_in=config.RANDOM_SEED):
    """
    Selects a candidate per period with the pooled rule, replays the prior-only switching path and its baselines, and
    summarizes it (module docstring, steps 2-5).

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        period_pdf_in (pd.DataFrame): Replay periods
        candidate_period_pdf_in (pd.DataFrame): candidate_period_pdf of run_candidate_replay_dict
        candidate_dict_list_in (list[dict]): Candidates, in the order of run_candidate_replay_dict
        rule_builder_func_in (function): f(candidate_dict) -> (exit_signal_arr, reentry_func, reentry_reason_str)
        key_col_str_list_in (list[str]): Candidate key columns
        tie_break_list_in (list[tuple[str, bool]]): Tie-breaks of the selection (column, ascending)
        pooled_count_in (int): Periods pooled by the selection
        untouched_start_date_str_in (str): First date of the untouched data
        max_cash_sessions_in (int | None): Forced re-entry after this many cash decisions (None = never)
        random_run_count_in (int): Runs per random family
        random_exit_seed_offset_in (int): Seed offset of the random exit runs
        block_month_count_in (int): Months per block of the primary log-excess bootstrap
        seed_in (int): Base random seed

    Returns:
        dict: selection_pdf, period_candidate_dict, assignment_arr, simulation_dict, buy_hold_dict, baseline_pdf (one row per
              baseline with total_return), baseline_summary_dict (medians and shares beaten), summary_dict,
              log_excess_1m_dict, cost_sensitivity_pdf, scorecard_pdf, probability_dict, path_period_pdf
    """
    # SELECT ONE CANDIDATE PER PERIOD AND MAP IT TO THE NEXT PERIOD
    selection_pdf = get_pooled_selection_pdf(candidate_period_pdf_in, key_col_str_list_in, "valid_excess_return", pooled_count_in, tie_break_list_in)
    period_candidate_dict = get_prior_only_period_candidate_dict(selection_pdf, period_pdf_in, "candidate_idx")
    # DEFINE THE PATH SPAN (FIRST GOVERNED PERIOD -> LAST PERIOD) AND ITS PERIODS
    path_period_pdf = period_pdf_in[period_pdf_in["period_id"].isin(list(period_candidate_dict))].reset_index(drop=True)
    span_start, span_end = path_period_pdf["period_start"].iloc[0], path_period_pdf["period_end"].iloc[-1]
    # BUILD THE SWITCHING RULE
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    assignment_arr = get_session_assignment_arr(ohlcv_array_dict_in["session_date_list"], path_period_pdf, period_candidate_dict)
    rule_tuple_list = [rule_builder_func_in(candidate_dict) for candidate_dict in candidate_dict_list_in]
    switching_dict = get_switching_rule_dict(assignment_arr, [rule_tuple[0] for rule_tuple in rule_tuple_list], [rule_tuple[1] for rule_tuple in rule_tuple_list])
    # FUNCTION: REPLAY A VARIANT OF THE PATH
    def replay(exit_signal_arr, reentry_func, reason_str="rule", **cost_kwargs):
        return simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, untouched_start_date_str_in, volatility_arr_in=np.full(session_count, np.nan),
                                               stop_k_in=None, reentry_func_in=reentry_func, reentry_reason_str_in=reason_str, exit_signal_arr_in=exit_signal_arr,
                                               max_cash_sessions_in=max_cash_sessions_in, **cost_kwargs)
    # REPLAY THE PATH AND BUY AND HOLD
    simulation_dict = replay(switching_dict["exit_signal_arr"], switching_dict["reentry_func"])
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end)
    # LIST TO HOLD THE BASELINE ROWS
    baseline_dict_list = [{"baseline": "model", **simulation_dict["metric_dict"]}, {"baseline": "buy_hold", **buy_hold_dict["metric_dict"]}]
    # MATCH THE RANDOM BASELINES TO THE PATH'S ACTIVITY
    probability_dict = get_path_random_probability_dict(simulation_dict)
    # ITERATE OVER THE RANDOM RUNS
    for run_idx in range(random_run_count_in):
        # IF THE PATH NEVER EXITED (EVERY RANDOM RUN EQUALS THE PATH)
        if not np.isfinite(probability_dict["exit_probability"]):
            baseline_dict_list += [{"baseline": f"random_exit_{run_idx:02d}", **simulation_dict["metric_dict"]},
                                   {"baseline": f"random_reentry_{run_idx:02d}", **simulation_dict["metric_dict"]}]
            continue
        # RANDOM EXIT (SAME RE-ENTRY RULE)
        random_exit_arr = np.random.default_rng(seed_in + random_exit_seed_offset_in + run_idx).random(session_count) < probability_dict["exit_probability"]
        baseline_dict_list.append({"baseline": f"random_exit_{run_idx:02d}", **replay(random_exit_arr, switching_dict["reentry_func"])["metric_dict"]})
        # RANDOM RE-ENTRY (SAME EXITS)
        random_reentry_func = get_random_reentry_func(probability_dict["reentry_probability"], seed_in + run_idx)
        baseline_dict_list.append({"baseline": f"random_reentry_{run_idx:02d}", **replay(switching_dict["exit_signal_arr"], random_reentry_func, "random")["metric_dict"]})
    baseline_pdf = pd.DataFrame(baseline_dict_list)
    # SUMMARIZE THE RANDOM FAMILIES (MEDIAN AND SHARE OF RUNS THE PATH BEATS)
    path_total_return = simulation_dict["metric_dict"]["total_return"]
    baseline_summary_dict = {}
    for prefix_str in ["random_exit_", "random_reentry_"]:
        family_arr = baseline_pdf.loc[baseline_pdf["baseline"].str.startswith(prefix_str), "total_return"].to_numpy(dtype=float)
        baseline_summary_dict[f"{prefix_str}median"] = float(np.median(family_arr))
        baseline_summary_dict[f"{prefix_str}path_beats_share"] = float((family_arr < path_total_return).mean())
    # SUMMARIZE THE PATH (PRIMARY 6-MONTH BLOCKS; 1-MONTH VERSION ALONGSIDE)
    summary_dict = get_replay_summary_dict(simulation_dict["daily_equity_pdf"], buy_hold_dict["daily_equity_pdf"], path_period_pdf, block_month_count_in,
                                           {"random_exit_median": baseline_summary_dict["random_exit_median"], "random_reentry_median": baseline_summary_dict["random_reentry_median"]})
    log_excess_1m_dict = get_log_excess_bootstrap_dict(get_chained_daily_return_pdf([simulation_dict["daily_equity_pdf"]]), get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]]), 1)
    # COST SENSITIVITY (SAME PATH, DIFFERENT SLIPPAGE; BUY-AND-HOLD RECOMPUTED WITH THE SAME SLIPPAGE)
    cost_dict_list = []
    for slippage in config.COST_SENSITIVITY_SLIPPAGE_LIST:
        cost_total = replay(switching_dict["exit_signal_arr"], switching_dict["reentry_func"], entry_slippage_in=slippage, market_exit_slippage_in=slippage)["metric_dict"]["total_return"]
        cost_buy_hold = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end, entry_slippage_in=slippage, market_exit_slippage_in=slippage)["metric_dict"]["total_return"]
        cost_dict_list.append({"slippage_per_share": slippage, "total_return": cost_total, "buy_hold_return": cost_buy_hold, "excess_return": cost_total - cost_buy_hold})
    # RETURN THE RESULTS
    return {"selection_pdf": selection_pdf, "period_candidate_dict": period_candidate_dict, "assignment_arr": assignment_arr, "simulation_dict": simulation_dict,
            "buy_hold_dict": buy_hold_dict, "baseline_pdf": baseline_pdf, "baseline_summary_dict": baseline_summary_dict, "summary_dict": summary_dict,
            "log_excess_1m_dict": log_excess_1m_dict, "cost_sensitivity_pdf": pd.DataFrame(cost_dict_list),
            "scorecard_pdf": get_episode_scorecard_pdf(simulation_dict, ohlcv_array_dict_in), "probability_dict": probability_dict, "path_period_pdf": path_period_pdf}
