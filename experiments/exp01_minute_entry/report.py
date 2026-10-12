import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION, THE EXPERIMENT CONFIGURATION AND THE DESIGN
from so import config
from experiments.exp01_minute_entry import config as exp_config
from experiments.exp01_minute_entry import design
from experiments.exp01_minute_entry.walk_forward import get_fixed_time_decision_pdf, get_random_decision_pdf, get_window_simulation_dict

"""
Development report for exp01_minute_entry_v2

Each candidate is refit weekly. A period score is that quarter's simulation. The prior-only path switches the chosen
window and threshold at period boundaries. Random entries match the path's buy rate. The fixed-time baseline buys at
10:00 with a 0.50% distance.
"""

# FUNCTION: SCORE EVERY CANDIDATE ON EVERY DEVELOPMENT PERIOD
def get_development_score_pdf(ohlcv_array_dict_in, period_pdf_in, data_context_in):
    """
    Period score = the quarter's total return minus buy-and-hold over the same sessions.

    Args:
        ohlcv_array_dict_in (dict): Bars through the development end
        period_pdf_in (pd.DataFrame): Development periods
        data_context_in (DataContext): Point-in-time context

    Returns:
        pd.DataFrame: fold_id, candidate, total_return, buy_hold_total_return, excess_return
    """
    # IMPORT THE EQUITY RETURN HERE
    from so.core.holdout import get_equity_total_return_float
    row_dict_list = []
    for period_row in period_pdf_in.itertuples(index=False):
        print(f"period {int(period_row.period_id)} {period_row.period_start} -> {period_row.period_end}")
        for candidate in design.CANDIDATE_LIST:
            replay_dict = design.run_candidate_replay_dict(ohlcv_array_dict_in, period_row.period_start, period_row.period_end, candidate, data_context_in)
            total_float = get_equity_total_return_float(replay_dict["daily_equity_pdf"])
            buy_hold_float = float(replay_dict["metric_dict"]["buy_hold_return"])
            row_dict_list.append({"fold_id": int(period_row.period_id), "candidate": candidate, "total_return": total_float,
                                  "buy_hold_total_return": buy_hold_float, "excess_return": total_float - buy_hold_float})
    return pd.DataFrame(row_dict_list)

# FUNCTION: THE CANDIDATE WITH THE HIGHEST CHAINED QUARTER RETURN
def get_optimistic_dict(score_pdf_in):
    """
    Chains each candidate's quarters. The maximum is the best candidate after the fact.

    Args:
        score_pdf_in (pd.DataFrame): Period scores

    Returns:
        dict: candidate, total_return, buy_hold_total_return
    """
    # CHAIN THE QUARTERS OF EACH CANDIDATE
    best_dict = {"total_return": -np.inf}
    for candidate, group_pdf in score_pdf_in.groupby("candidate", sort=False):
        ordered_pdf = group_pdf.sort_values("fold_id")
        total_float = float(np.prod(1.0 + ordered_pdf["total_return"].to_numpy(dtype=float)) - 1.0)
        buy_hold_float = float(np.prod(1.0 + ordered_pdf["buy_hold_total_return"].to_numpy(dtype=float)) - 1.0)
        if total_float > best_dict["total_return"]:
            best_dict = {"candidate": candidate, "total_return": total_float, "buy_hold_total_return": buy_hold_float}
    return best_dict

# FUNCTION: RANDOM ENTRIES AND THE FIXED-TIME BASELINE
def get_path_baseline_dict(ohlcv_array_dict_in, path_dict_in, date1_in, date2_in):
    """
    Twenty random-entry runs use the path's buy rate and its decision times. One fixed-time run buys at 09:59.

    Args:
        ohlcv_array_dict_in (dict): Bars
        path_dict_in (dict): Prior-only path
        date1_in, date2_in: Span

    Returns:
        dict: The random median, the list, and the fixed-time return
    """
    # MATCH THE BUY RATE AND SIMULATE
    decision_pdf = path_dict_in["decision_pdf"]
    eligible_series = pd.Series(decision_pdf["decision_ts"])
    buy_probability = float(np.mean(decision_pdf["buy_flag"].to_numpy(dtype=float))) if len(decision_pdf) else 0.0
    delta_list = list(exp_config.MODEL_DELTA_LIST)
    random_list = []
    for run_idx in range(exp_config.RANDOM_BASELINE_RUN_COUNT):
        random_pdf = get_random_decision_pdf(eligible_series, buy_probability, delta_list, config.RANDOM_SEED + run_idx)
        random_list.append(get_window_simulation_dict(random_pdf, ohlcv_array_dict_in, date1_in, date2_in)["metric_dict"]["total_return"])
    fixed_pdf = get_fixed_time_decision_pdf(eligible_series)
    fixed_return = get_window_simulation_dict(fixed_pdf, ohlcv_array_dict_in, date1_in, date2_in)["metric_dict"]["total_return"]
    return {"random_entry_median": float(np.median(random_list)), "random_entry_list": random_list, "fixed_time_return": float(fixed_return)}

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
    from so.core.continuous_replay import get_log_excess_bootstrap_dict, get_period_return_pdf
    span_dict = get_development_ohlcv_dict(exp_config.EMBARGO_TRADING_DAYS)
    ohlcv_array_dict = span_dict["ohlcv_array_dict"]
    period_pdf, fold_pdf = get_development_period_pdf(span_dict["anchor_session_list"], ohlcv_array_dict, exp_config.EMBARGO_TRADING_DAYS, max(exp_config.TRAIN_WINDOW_YEARS_LIST))
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    score_pdf = get_development_score_pdf(ohlcv_array_dict, period_pdf, data_context)
    selection_pdf = get_governing_selection_pdf(design, score_pdf, period_pdf)
    path_dict = design.run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf, data_context)
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    baseline_dict = get_path_baseline_dict(ohlcv_array_dict, path_dict, date1, date2)
    path_dict["metric_dict"]["cash_session_pct"] = float(1.0 - path_dict["daily_equity_pdf"]["in_position"].mean())
    path_dict["metric_dict"]["signal_exit_count"] = int(len(path_dict["transaction_pdf"])) if path_dict["transaction_pdf"] is not None else 0
    strategy_return_pdf = get_chained_daily_return_pdf([path_dict["daily_equity_pdf"]])
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)
    buy_hold_return_pdf = get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]])
    performance_pdf = get_performance_over_time_pdf(strategy_return_pdf, buy_hold_return_pdf)
    quarter_pdf = get_performance_quarter_pdf(strategy_return_pdf, buy_hold_return_pdf)
    candidate_list = [design.get_session_candidate_str(session_date, period_pdf, selection_pdf) for session_date in path_dict["decision_session_list"]]
    activity_dict = get_turnover_switch_dict(path_dict["target_weight_arr"], int(len(path_dict["trade_pdf"])), candidate_list)
    path_period_pdf = get_period_return_pdf(path_dict["daily_equity_pdf"], period_pdf)
    buy_hold_period_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], period_pdf)
    summary_dict = get_window_return_summary_dict(path_period_pdf["total_return"].to_numpy(), buy_hold_period_pdf["total_return"].to_numpy())
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=6)
    log_excess_1m_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=1)
    named_baseline_dict = {"random_entry_median": baseline_dict["random_entry_median"], "fixed_time": baseline_dict["fixed_time_return"]}
    success_dict = get_success_criteria_dict(strategy_return_pdf, buy_hold_return_pdf, named_baseline_dict)
    path_return = float(path_dict["metric_dict"]["total_return"])
    beats_buy_hold_bool = path_return > buy_hold_dict["metric_dict"]["total_return"]
    beats_random_bool = path_return > baseline_dict["random_entry_median"]
    verdict_str = "CONTINUE" if beats_buy_hold_bool and beats_random_bool else "STOP"
    return {"span_dict": span_dict, "period_pdf": period_pdf, "fold_pdf": fold_pdf, "score_pdf": score_pdf,
            "selection_pdf": selection_pdf, "path_dict": path_dict, "buy_hold_dict": buy_hold_dict,
            "baseline_dict": baseline_dict, "optimistic_dict": get_optimistic_dict(score_pdf),
            "performance_pdf": performance_pdf, "quarter_pdf": quarter_pdf, "activity_dict": activity_dict,
            "summary_dict": summary_dict, "log_excess_dict": log_excess_dict, "log_excess_1m_dict": log_excess_1m_dict,
            "success_dict": success_dict, "verdict_str": verdict_str, "beats_buy_hold_bool": beats_buy_hold_bool,
            "beats_random_bool": beats_random_bool}
