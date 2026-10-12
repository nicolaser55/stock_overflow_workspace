import types
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION, THE EXPERIMENT CONFIGURATION AND THE DESIGN
from so import config
from experiments.exp12_vix_fear_reentry import config as exp_config
from experiments.exp12_vix_fear_reentry import design
from experiments.exp12_vix_fear_reentry.rules import get_concentration_dict, get_vix_scorecard_pdf, get_yearly_log_excess_pdf

"""
Development report for exp12_vix_fear_reentry_v2

Period scores are slices of one continuous path per candidate (protocol 1.0). The prior-only path switches rules at
period boundaries and carries the position. The information test compares that path with the unmodified {E1, E2} path
and with both random families. The best candidate after the fact is labelled optimistic.
"""

# FUNCTION: SCORE A LIST OF CANDIDATES ON EVERY DEVELOPMENT PERIOD
def get_score_pdf(ohlcv_array_dict_in, period_pdf_in, candidate_list_in, data_context_in):
    """
    Period score = the continuous slice return minus buy-and-hold over the same sessions.

    Args:
        ohlcv_array_dict_in (dict): Bars through the development end
        period_pdf_in (pd.DataFrame): Development periods
        candidate_list_in (list[str]): Candidates to score
        data_context_in (DataContext): Point-in-time context

    Returns:
        pd.DataFrame: fold_id, candidate, total_return, buy_hold_total_return, excess_return
    """
    # IMPORT THE SLICE RETURN AND BUY-AND-HOLD HERE
    from so.core.holdout import get_equity_total_return_float
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    from so.core.continuous_replay import get_period_return_pdf
    date1, date2 = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    buy_hold_period_pdf = get_period_return_pdf(get_buy_and_hold_result_dict(ohlcv_array_dict_in, date1, date2)["daily_equity_pdf"], period_pdf_in)
    buy_hold_dict = {int(row.period_id): float(row.total_return) for row in buy_hold_period_pdf.itertuples(index=False)}
    row_dict_list = []
    for period_row in period_pdf_in.itertuples(index=False):
        buy_hold_float = buy_hold_dict[int(period_row.period_id)]
        for candidate in candidate_list_in:
            replay_dict = design.run_candidate_replay_dict(ohlcv_array_dict_in, period_row.period_start, period_row.period_end, candidate, data_context_in)
            total_float = get_equity_total_return_float(replay_dict["daily_equity_pdf"])
            row_dict_list.append({"fold_id": int(period_row.period_id), "candidate": candidate, "total_return": total_float,
                                  "buy_hold_total_return": buy_hold_float, "excess_return": total_float - buy_hold_float})
    return pd.DataFrame(row_dict_list)

# FUNCTION: THE CANDIDATE WITH THE HIGHEST CHAINED SLICE RETURN
def get_optimistic_dict(score_pdf_in):
    """
    Chains each candidate's period slices. The maximum is the best candidate after the fact.

    Args:
        score_pdf_in (pd.DataFrame): Period scores

    Returns:
        dict: candidate, total_return, buy_hold_total_return
    """
    # CHAIN THE WINDOWS OF EACH CANDIDATE
    best_dict = {"total_return": -np.inf}
    for candidate, group_pdf in score_pdf_in.groupby("candidate", sort=False):
        ordered_pdf = group_pdf.sort_values("fold_id")
        total_float = float(np.prod(1.0 + ordered_pdf["total_return"].to_numpy(dtype=float)) - 1.0)
        buy_hold_float = float(np.prod(1.0 + ordered_pdf["buy_hold_total_return"].to_numpy(dtype=float)) - 1.0)
        if total_float > best_dict["total_return"]:
            best_dict = {"candidate": candidate, "total_return": total_float, "buy_hold_total_return": buy_hold_float}
    return best_dict

# FUNCTION: MATCHED RANDOM FAMILIES ON THE PRIOR-ONLY PATH
def get_path_baseline_dict(ohlcv_array_dict_in, path_dict_in, date1_in, date2_in):
    """
    Twenty random exits keep the path's re-entry. Twenty random re-entries keep the path's exit signal. When the path
    never exits, every random run equals the path.

    Args:
        ohlcv_array_dict_in (dict): Bars
        path_dict_in (dict): Prior-only path
        date1_in, date2_in: Span

    Returns:
        dict: Medians and the two lists
    """
    # IMPORT THE RANDOM RULES AND THE PROBABILITY MATCH HERE
    from so.core.reentry_simulation import simulate_stop_reentry_dict, get_random_reentry_func
    from experiments.exp03_ath_exit.rules import get_random_baseline_probability_dict, get_random_exit_signal_arr
    probability_dict = get_random_baseline_probability_dict(path_dict_in)
    path_return = path_dict_in["metric_dict"]["total_return"]
    session_count = len(path_dict_in["exit_signal_arr"])
    never_bool = not np.isfinite(probability_dict["exit_probability"]) or not np.isfinite(probability_dict["buyback_probability"])
    exit_list, reentry_list = [], []
    if never_bool:
        exit_list = [path_return] * exp_config.RANDOM_RUN_COUNT
        reentry_list = [path_return] * exp_config.RANDOM_RUN_COUNT
    else:
        reentry_func = path_dict_in["reentry_func"]
        for run_idx in range(exp_config.RANDOM_RUN_COUNT):
            exit_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, np.full(session_count, np.nan), None, reentry_func, "random",
                                                  exit_signal_arr_in=get_random_exit_signal_arr(session_count, probability_dict["exit_probability"], config.RANDOM_SEED + exp_config.RANDOM_EXIT_SEED_OFFSET + run_idx),
                                                  max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
            reentry_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, np.full(session_count, np.nan), None,
                                                     get_random_reentry_func(probability_dict["buyback_probability"], config.RANDOM_SEED + run_idx), "random",
                                                     exit_signal_arr_in=path_dict_in["exit_signal_arr"], max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
            exit_list.append(exit_dict["metric_dict"]["total_return"])
            reentry_list.append(reentry_dict["metric_dict"]["total_return"])
    return {"random_exit_median": float(np.median(exit_list)), "random_reentry_median": float(np.median(reentry_list)),
            "random_exit_list": exit_list, "random_reentry_list": reentry_list}

# FUNCTION: THE UNMODIFIED {E1, E2} PRIOR-ONLY PATH
def get_unmodified_path_dict(ohlcv_array_dict_in, period_pdf_in, data_context_in):
    """
    Prior-only path over the two unmodified exits. Ties take E2. The first period is E2none.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        data_context_in (DataContext): Point-in-time context

    Returns:
        dict: Path and its total return
    """
    # SELECT WITH THE SAME POOLED RULE, THEN REPLAY
    from so.core.holdout import get_governing_selection_pdf
    unmodified_module = types.SimpleNamespace(CANDIDATE_LIST=list(design.UNMODIFIED_CANDIDATE_LIST), SELECTION_RULE=design.UNMODIFIED_SELECTION_RULE,
                                              CANDIDATE_TIE_VALUE_DICT=design.UNMODIFIED_TIE_VALUE_DICT)
    score_pdf = get_score_pdf(ohlcv_array_dict_in, period_pdf_in, design.UNMODIFIED_CANDIDATE_LIST, data_context_in)
    selection_pdf = get_governing_selection_pdf(unmodified_module, score_pdf, period_pdf_in)
    path_dict = design.run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf, data_context_in)
    return {"path_dict": path_dict, "total_return": path_dict["metric_dict"]["total_return"], "selection_pdf": selection_pdf}

# FUNCTION: RUN THE DEVELOPMENT REPORT
def run_development_dict():
    """
    Scores the grid, selects, replays the prior-only path and its baselines, and applies the stopping rule.

    Returns:
        dict: Tables and the verdict
    """
    # IMPORT THE BOUNDARY, THE SELECTION AND THE REPORTS HERE
    from so.core.development_span import get_development_ohlcv_dict, get_development_period_pdf
    from so.core.holdout import get_governing_selection_pdf
    from so.core.evaluation import (get_chained_daily_return_pdf, get_performance_over_time_pdf, get_performance_quarter_pdf,
                                    get_turnover_switch_dict, get_window_return_summary_dict, get_success_criteria_dict)
    from so.core.continuous_replay import get_episode_scorecard_pdf, get_log_excess_bootstrap_dict, get_period_return_pdf
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    span_dict = get_development_ohlcv_dict(exp_config.EMBARGO_TRADING_DAYS)
    ohlcv_array_dict = span_dict["ohlcv_array_dict"]
    period_pdf, fold_pdf = get_development_period_pdf(span_dict["anchor_session_list"], ohlcv_array_dict, exp_config.EMBARGO_TRADING_DAYS, exp_config.FIXED_TRAIN_WINDOW_YEARS)
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    score_pdf = get_score_pdf(ohlcv_array_dict, period_pdf, design.CANDIDATE_LIST, data_context)
    selection_pdf = get_governing_selection_pdf(design, score_pdf, period_pdf)
    path_dict = design.run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf, data_context)
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)
    baseline_dict = get_path_baseline_dict(ohlcv_array_dict, path_dict, date1, date2)
    unmodified_dict = get_unmodified_path_dict(ohlcv_array_dict, period_pdf, data_context)
    strategy_return_pdf = get_chained_daily_return_pdf([path_dict["daily_equity_pdf"]])
    buy_hold_return_pdf = get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]])
    performance_pdf = get_performance_over_time_pdf(strategy_return_pdf, buy_hold_return_pdf)
    quarter_pdf = get_performance_quarter_pdf(strategy_return_pdf, buy_hold_return_pdf)
    candidate_list = [design.get_session_candidate_str(session_date, period_pdf, selection_pdf) for session_date in path_dict["decision_session_list"]]
    activity_dict = get_turnover_switch_dict(path_dict["target_weight_arr"], int(len(path_dict["trade_pdf"])), candidate_list)
    path_period_pdf = get_period_return_pdf(path_dict["daily_equity_pdf"], period_pdf)
    buy_hold_period_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], period_pdf)
    summary_dict = get_window_return_summary_dict(path_period_pdf["total_return"].to_numpy(), buy_hold_period_pdf["total_return"].to_numpy())
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=exp_config.BOOTSTRAP_BLOCK_MONTH_COUNT)
    log_excess_1m_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=1)
    named_baseline_dict = {"unmodified": unmodified_dict["total_return"], "random_exit_median": baseline_dict["random_exit_median"],
                           "random_reentry_median": baseline_dict["random_reentry_median"]}
    success_dict = get_success_criteria_dict(strategy_return_pdf, buy_hold_return_pdf, named_baseline_dict)
    scorecard_pdf = get_vix_scorecard_pdf(get_episode_scorecard_pdf(path_dict, ohlcv_array_dict), path_dict, path_dict["vix_feature_pdf"])
    concentration_dict = get_concentration_dict(scorecard_pdf, path_dict["daily_equity_pdf"], buy_hold_dict["daily_equity_pdf"])
    yearly_pdf = get_yearly_log_excess_pdf(path_dict["daily_equity_pdf"], buy_hold_dict["daily_equity_pdf"])
    path_return = path_dict["metric_dict"]["total_return"]
    beats_buy_hold_bool = path_return > buy_hold_dict["metric_dict"]["total_return"]
    beats_random_bool = path_return > baseline_dict["random_exit_median"] and path_return > baseline_dict["random_reentry_median"]
    beats_unmodified_bool = path_return > unmodified_dict["total_return"]
    information_test_bool = beats_unmodified_bool and beats_random_bool
    # THE PRIMARY IS BUY-AND-HOLD. A PASS WITH A FAILED INFORMATION TEST STAYS A CANDIDATE, LABELLED AS SUCH.
    verdict_str = "CONTINUE" if beats_buy_hold_bool else "STOP"
    return {"span_dict": span_dict, "period_pdf": period_pdf, "fold_pdf": fold_pdf, "score_pdf": score_pdf,
            "selection_pdf": selection_pdf, "path_dict": path_dict, "buy_hold_dict": buy_hold_dict,
            "baseline_dict": baseline_dict, "unmodified_dict": unmodified_dict, "optimistic_dict": get_optimistic_dict(score_pdf),
            "performance_pdf": performance_pdf, "quarter_pdf": quarter_pdf, "activity_dict": activity_dict,
            "summary_dict": summary_dict, "log_excess_dict": log_excess_dict, "log_excess_1m_dict": log_excess_1m_dict,
            "success_dict": success_dict, "scorecard_pdf": scorecard_pdf, "concentration_dict": concentration_dict,
            "yearly_pdf": yearly_pdf, "verdict_str": verdict_str, "beats_buy_hold_bool": beats_buy_hold_bool,
            "beats_random_bool": beats_random_bool, "information_test_bool": information_test_bool}
