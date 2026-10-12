import pandas as pd
# IMPORT THE SHARED CONFIGURATION, THIS DESIGN AND exp12'S REPORT HELPERS
from experiments.exp12_vix_fear_reentry import config as exp12_config
from experiments.exp12_vix_fear_reentry import design as exp12_design
from experiments.exp12_vix_fear_reentry.report import get_optimistic_dict, get_path_baseline_dict, get_score_pdf
from experiments.exp12_vix_fear_reentry.rules import get_concentration_dict, get_vix_scorecard_pdf, get_yearly_log_excess_pdf
from experiments.exp13_e1m1_robustness import design

"""
Development report for exp13_e1m1_robustness_v2

One continuous path of the frozen rule E1M1. The unmodified E1 path and the two random families are baselines. The
robustness steps of protocol 1.0 are not repeated, so this report does not reopen that verdict.
"""

# FUNCTION: RUN THE DEVELOPMENT REPORT
def run_development_dict():
    """
    Scores E1M1, replays it, and compares it with buy-and-hold, unmodified E1 and the random families.

    Returns:
        dict: Tables and the verdict
    """
    # IMPORT THE BOUNDARY AND THE SHARED REPORTS HERE
    from so.core.development_span import get_development_ohlcv_dict, get_development_period_pdf
    from so.core.holdout import get_governing_selection_pdf
    from so.core.evaluation import (get_chained_daily_return_pdf, get_performance_over_time_pdf, get_performance_quarter_pdf,
                                    get_turnover_switch_dict, get_window_return_summary_dict, get_success_criteria_dict)
    from so.core.continuous_replay import get_episode_scorecard_pdf, get_log_excess_bootstrap_dict, get_period_return_pdf
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    span_dict = get_development_ohlcv_dict(int(design.PERIOD_RULE["embargo_sessions"]))
    ohlcv_array_dict = span_dict["ohlcv_array_dict"]
    period_pdf, fold_pdf = get_development_period_pdf(span_dict["anchor_session_list"], ohlcv_array_dict, int(design.PERIOD_RULE["embargo_sessions"]), int(design.PERIOD_RULE["train_years"][0]))
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    score_pdf = get_score_pdf(ohlcv_array_dict, period_pdf, design.CANDIDATE_LIST, data_context)
    selection_pdf = get_governing_selection_pdf(design, score_pdf, period_pdf)
    path_dict = design.run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf, data_context)
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)
    baseline_dict = get_path_baseline_dict(ohlcv_array_dict, path_dict, date1, date2)
    unmodified_selection_pdf = pd.DataFrame({"period_id": period_pdf["period_id"].astype(int), "candidate": "E1none", "candidate_idx": 0})
    unmodified_path_dict = exp12_design.run_prior_only_path_dict(ohlcv_array_dict, period_pdf, unmodified_selection_pdf, data_context)
    unmodified_dict = {"path_dict": unmodified_path_dict, "total_return": unmodified_path_dict["metric_dict"]["total_return"], "selection_pdf": unmodified_selection_pdf}
    strategy_return_pdf = get_chained_daily_return_pdf([path_dict["daily_equity_pdf"]])
    buy_hold_return_pdf = get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]])
    performance_pdf = get_performance_over_time_pdf(strategy_return_pdf, buy_hold_return_pdf)
    quarter_pdf = get_performance_quarter_pdf(strategy_return_pdf, buy_hold_return_pdf)
    candidate_list = [design.get_session_candidate_str(session_date, period_pdf, selection_pdf) for session_date in path_dict["decision_session_list"]]
    activity_dict = get_turnover_switch_dict(path_dict["target_weight_arr"], int(len(path_dict["trade_pdf"])), candidate_list)
    path_period_pdf = get_period_return_pdf(path_dict["daily_equity_pdf"], period_pdf)
    buy_hold_period_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], period_pdf)
    summary_dict = get_window_return_summary_dict(path_period_pdf["total_return"].to_numpy(), buy_hold_period_pdf["total_return"].to_numpy())
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=exp12_config.BOOTSTRAP_BLOCK_MONTH_COUNT)
    log_excess_1m_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=1)
    named_baseline_dict = {"unmodified_e1": unmodified_dict["total_return"], "random_exit_median": baseline_dict["random_exit_median"],
                           "random_reentry_median": baseline_dict["random_reentry_median"]}
    success_dict = get_success_criteria_dict(strategy_return_pdf, buy_hold_return_pdf, named_baseline_dict)
    scorecard_pdf = get_vix_scorecard_pdf(get_episode_scorecard_pdf(path_dict, ohlcv_array_dict), path_dict, path_dict["vix_feature_pdf"])
    concentration_dict = get_concentration_dict(scorecard_pdf, path_dict["daily_equity_pdf"], buy_hold_dict["daily_equity_pdf"])
    yearly_pdf = get_yearly_log_excess_pdf(path_dict["daily_equity_pdf"], buy_hold_dict["daily_equity_pdf"])
    path_return = path_dict["metric_dict"]["total_return"]
    beats_buy_hold_bool = path_return > buy_hold_dict["metric_dict"]["total_return"]
    beats_random_bool = path_return > baseline_dict["random_exit_median"] and path_return > baseline_dict["random_reentry_median"]
    information_test_bool = beats_random_bool and path_return > unmodified_dict["total_return"]
    verdict_str = "CONTINUE" if beats_buy_hold_bool else "STOP"
    return {"span_dict": span_dict, "period_pdf": period_pdf, "fold_pdf": fold_pdf, "score_pdf": score_pdf,
            "selection_pdf": selection_pdf, "path_dict": path_dict, "buy_hold_dict": buy_hold_dict,
            "baseline_dict": baseline_dict, "unmodified_dict": unmodified_dict, "optimistic_dict": get_optimistic_dict(score_pdf),
            "performance_pdf": performance_pdf, "quarter_pdf": quarter_pdf, "activity_dict": activity_dict,
            "summary_dict": summary_dict, "log_excess_dict": log_excess_dict, "log_excess_1m_dict": log_excess_1m_dict,
            "success_dict": success_dict, "scorecard_pdf": scorecard_pdf, "concentration_dict": concentration_dict,
            "yearly_pdf": yearly_pdf, "verdict_str": verdict_str, "beats_buy_hold_bool": beats_buy_hold_bool,
            "beats_random_bool": beats_random_bool, "information_test_bool": information_test_bool}
