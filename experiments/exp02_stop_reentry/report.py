import numpy as np
import pandas as pd
# IMPORT THE EXPERIMENT CONFIGURATION AND THE DESIGN
from experiments.exp02_stop_reentry import config as exp_config
from experiments.exp02_stop_reentry import design

"""
Development report for exp02_stop_reentry_v2

The period score of a candidate is a fresh window (protocol 1.0). The prior-only path is one continuous replay of the
candidate the selection rule puts in force, which is what the holdout runner will continue. The best candidate after
the fact is labelled optimistic.
"""

# FUNCTION: SCORE EVERY CANDIDATE ON EVERY DEVELOPMENT PERIOD
def get_development_score_pdf(ohlcv_array_dict_in, period_pdf_in, data_context_in):
    """
    Period score = the candidate's fresh-window return minus buy-and-hold, the same difference the holdout runner stores.

    Args:
        ohlcv_array_dict_in (dict): Bars through the development end
        period_pdf_in (pd.DataFrame): Development periods
        data_context_in (DataContext): Point-in-time context

    Returns:
        pd.DataFrame: fold_id, candidate, total_return, buy_hold_total_return, excess_return
    """
    # IMPORT BUY-AND-HOLD AND THE RUNNER'S RETURN HERE
    from so.core.holdout import get_equity_total_return_float
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    # SCORE EACH PERIOD AND EACH CANDIDATE
    row_dict_list = []
    for period_row in period_pdf_in.itertuples(index=False):
        buy_hold_float = get_buy_and_hold_result_dict(ohlcv_array_dict_in, period_row.period_start, period_row.period_end)["metric_dict"]["total_return"]
        print(f"period {int(period_row.period_id)} {period_row.period_start} -> {period_row.period_end}")
        for candidate in design.CANDIDATE_LIST:
            replay_dict = design.run_candidate_replay_dict(ohlcv_array_dict_in, period_row.period_start, period_row.period_end, candidate, data_context_in)
            total_float = get_equity_total_return_float(replay_dict["daily_equity_pdf"])
            row_dict_list.append({"fold_id": int(period_row.period_id), "candidate": candidate, "total_return": total_float,
                                  "buy_hold_total_return": buy_hold_float, "excess_return": total_float - buy_hold_float})
    return pd.DataFrame(row_dict_list)

# FUNCTION: THE CANDIDATE WITH THE HIGHEST CHAINED FRESH-WINDOW RETURN
def get_optimistic_dict(score_pdf_in):
    """
    Chains each candidate's fresh windows. The maximum is the best candidate after the fact.

    Args:
        score_pdf_in (pd.DataFrame): Period scores

    Returns:
        dict: candidate, total_return, buy_hold_total_return
    """
    # CHAIN THE WINDOWS OF EACH CANDIDATE, AND BUY-AND-HOLD ONCE (THE SAME IN EVERY CANDIDATE)
    best_dict = {"total_return": -np.inf}
    buy_hold_float = None
    for candidate, group_pdf in score_pdf_in.groupby("candidate", sort=False):
        ordered_pdf = group_pdf.sort_values("fold_id")
        total_float = float(np.prod(1.0 + ordered_pdf["total_return"].to_numpy(dtype=float)) - 1.0)
        buy_hold_float = float(np.prod(1.0 + ordered_pdf["buy_hold_total_return"].to_numpy(dtype=float)) - 1.0)
        if total_float > best_dict["total_return"]:
            best_dict = {"candidate": candidate, "total_return": total_float, "buy_hold_total_return": buy_hold_float}
    return best_dict

# FUNCTION: SAME-STOP FIXED DELAYS AND MATCHED RANDOM RE-ENTRY ON THE PRIOR-ONLY PATH
def get_path_baseline_dict(ohlcv_array_dict_in, path_dict_in, date1_in, date2_in):
    """
    Fixed-delay re-entry and 20 random re-entries use the path's stop. The trend rule does not.

    Args:
        ohlcv_array_dict_in (dict): Bars
        path_dict_in (dict): Prior-only path
        date1_in, date2_in: Path span

    Returns:
        dict: baseline name -> total return, plus random_return_list
    """
    # IMPORT THE RULES HERE
    from so import config
    from so.core.reentry_simulation import simulate_stop_reentry_dict, simulate_trend_rule_dict, get_fixed_delay_reentry_func, get_random_reentry_func
    from so.features.daily_features import get_daily_feature_pdf
    # THE PATH'S STOP AND ITS VOLATILITY
    volatility_arr = design.get_window_retrain_dict(ohlcv_array_dict_in, exp_config.TRAIN_WINDOW_CANDIDATE_LIST[0])["row_pdf"]["daily_volatility"].to_numpy(dtype=float)
    stop_k_arr = path_dict_in["full_stop_k_arr"]
    return_dict = {}
    for delay_int in exp_config.FIXED_DELAY_SESSION_LIST:
        simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, volatility_arr, stop_k_arr,
                                                     get_fixed_delay_reentry_func(int(delay_int)), "delay", max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
        return_dict[f"fixed_delay_{int(delay_int)}"] = simulation_dict["metric_dict"]["total_return"]
    # RANDOM RE-ENTRY MATCHED TO THE PATH'S MEAN CASH DECISIONS; NO EXIT MEANS EVERY RUN EQUALS THE PATH
    episode_pdf = path_dict_in["episode_pdf"]
    mean_cash_float = float(episode_pdf["cash_session_count"].mean()) if len(episode_pdf) else np.nan
    random_list = []
    if path_dict_in["metric_dict"]["stop_count"] == 0 or not np.isfinite(mean_cash_float) or mean_cash_float <= 0:
        random_list = [path_dict_in["metric_dict"]["total_return"]] * exp_config.RANDOM_REENTRY_RUN_COUNT
    else:
        probability_float = 1.0 / mean_cash_float
        for run_idx in range(exp_config.RANDOM_REENTRY_RUN_COUNT):
            simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, volatility_arr, stop_k_arr,
                                                         get_random_reentry_func(probability_float, config.RANDOM_SEED + run_idx), "random",
                                                         max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
            random_list.append(simulation_dict["metric_dict"]["total_return"])
    return_dict["random_reentry_median"] = float(np.median(random_list))
    return_dict["random_return_list"] = random_list
    # THE 200-SESSION RULE
    daily_pdf = get_daily_feature_pdf(ohlcv_array_dict_in)
    trend_dict = simulate_trend_rule_dict(ohlcv_array_dict_in, daily_pdf, date1_in, date2_in, "ma200_dist_pct")
    return_dict["trend_ma200"] = trend_dict["metric_dict"]["total_return"]
    return return_dict

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
                                    get_turnover_switch_dict, get_refit_report_dict, get_window_return_summary_dict, get_success_criteria_dict)
    from so.core.continuous_replay import get_period_return_pdf, get_log_excess_bootstrap_dict
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    # BARS THROUGH THE DEVELOPMENT END, AND THE CONTEXT THROUGH THAT END
    span_dict = get_development_ohlcv_dict(exp_config.EMBARGO_TRADING_DAYS)
    ohlcv_array_dict = span_dict["ohlcv_array_dict"]
    period_pdf, fold_pdf = get_development_period_pdf(span_dict["anchor_session_list"], ohlcv_array_dict, exp_config.EMBARGO_TRADING_DAYS, exp_config.FOLD_TRAIN_WINDOW_YEARS)
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    # THE GRID, THEN THE CANDIDATE IN FORCE
    score_pdf = get_development_score_pdf(ohlcv_array_dict, period_pdf, data_context)
    selection_pdf = get_governing_selection_pdf(design, score_pdf, period_pdf)
    path_dict = design.run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf, data_context)
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)
    baseline_dict = get_path_baseline_dict(ohlcv_array_dict, path_dict, date1, date2)
    # PERFORMANCE OVER TIME, TURNOVER, AND THE REFITS
    strategy_return_pdf = get_chained_daily_return_pdf([path_dict["daily_equity_pdf"]])
    buy_hold_return_pdf = get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]])
    performance_pdf = get_performance_over_time_pdf(strategy_return_pdf, buy_hold_return_pdf)
    quarter_pdf = get_performance_quarter_pdf(strategy_return_pdf, buy_hold_return_pdf)
    candidate_list = []
    for session_date in path_dict["decision_session_list"]:
        candidate_list.append(design.get_session_candidate_str(session_date, period_pdf, selection_pdf))
    activity_dict = get_turnover_switch_dict(path_dict["target_weight_arr"], int(len(path_dict["trade_pdf"])), candidate_list)
    refit_dict = get_refit_report_dict(path_dict["refit_log_pdf"], None)
    # THE CONTINUOUS PATH'S PERIOD EXCESS, FOR THE MDE
    path_period_pdf = get_period_return_pdf(path_dict["daily_equity_pdf"], period_pdf)
    buy_hold_period_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], period_pdf)
    summary_dict = get_window_return_summary_dict(path_period_pdf["total_return"].to_numpy(), buy_hold_period_pdf["total_return"].to_numpy())
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=6)
    success_dict = get_success_criteria_dict(strategy_return_pdf, buy_hold_return_pdf,
                                             {name: value for name, value in baseline_dict.items() if name != "random_return_list"})
    # STOP UNLESS THE PATH BEATS BUY-AND-HOLD AND EVERY SAME-STOP FIXED DELAY
    path_return = path_dict["metric_dict"]["total_return"]
    beats_buy_hold_bool = path_return > buy_hold_dict["metric_dict"]["total_return"]
    beats_delay_bool = all(path_return > baseline_dict[f"fixed_delay_{delay_int}"] for delay_int in exp_config.FIXED_DELAY_SESSION_LIST)
    verdict_str = "CONTINUE" if beats_buy_hold_bool and beats_delay_bool else "STOP"
    # RETURN EVERYTHING THE NOTEBOOK SAVES
    return {"span_dict": span_dict, "period_pdf": period_pdf, "fold_pdf": fold_pdf, "score_pdf": score_pdf,
            "selection_pdf": selection_pdf, "path_dict": path_dict, "buy_hold_dict": buy_hold_dict,
            "baseline_dict": baseline_dict, "optimistic_dict": get_optimistic_dict(score_pdf),
            "performance_pdf": performance_pdf, "quarter_pdf": quarter_pdf, "activity_dict": activity_dict,
            "refit_dict": refit_dict, "summary_dict": summary_dict, "log_excess_dict": log_excess_dict,
            "success_dict": success_dict, "verdict_str": verdict_str, "beats_buy_hold_bool": beats_buy_hold_bool,
            "beats_delay_bool": beats_delay_bool}
