import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION, THE EXPERIMENT CONFIGURATION AND THE DESIGN
from so import config
from experiments.exp05_vol_scaled_exposure import config as exp_config
from experiments.exp05_vol_scaled_exposure import design

"""
Development report for exp05_vol_scaled_exposure_v2

Period scores are slices of one continuous path per candidate (protocol 1.0). The prior-only path switches rules at
period boundaries and carries the position. The constant exposure and the random shifts are matched to that path.
The best candidate after the fact is labelled optimistic.
"""

# FUNCTION: SCORE EVERY CANDIDATE ON EVERY DEVELOPMENT PERIOD
def get_development_score_pdf(ohlcv_array_dict_in, period_pdf_in, data_context_in):
    """
    Period score = the continuous slice return minus buy-and-hold over the same sessions.

    Args:
        ohlcv_array_dict_in (dict): Bars through the development end
        period_pdf_in (pd.DataFrame): Development periods
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
        print(f"period {int(period_row.period_id)} {period_row.period_start} -> {period_row.period_end}")
        for candidate in design.CANDIDATE_LIST:
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

# FUNCTION: CONSTANT EXPOSURE AND RANDOM SHIFTS OF THE PRIOR-ONLY WEIGHTS
def get_path_baseline_dict(ohlcv_array_dict_in, path_dict_in, date1_in, date2_in, data_context_in=None):
    """
    The design's baselines. This is the same function the holdout report calls.

    Args:
        ohlcv_array_dict_in (dict): Bars
        path_dict_in (dict): Prior-only path
        date1_in, date2_in: Span
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: Constant return, the shift family, and the share of shifts the path beats
    """
    # ONE IMPLEMENTATION, ON THE DESIGN
    return design.get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in, data_context_in, path_dict_in)

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
    from so.core.continuous_replay import get_period_return_pdf, get_log_excess_bootstrap_dict
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    span_dict = get_development_ohlcv_dict(exp_config.EMBARGO_TRADING_DAYS)
    ohlcv_array_dict = span_dict["ohlcv_array_dict"]
    period_pdf, fold_pdf = get_development_period_pdf(span_dict["anchor_session_list"], ohlcv_array_dict, exp_config.EMBARGO_TRADING_DAYS, exp_config.FIXED_TRAIN_WINDOW_YEARS)
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    score_pdf = get_development_score_pdf(ohlcv_array_dict, period_pdf, data_context)
    selection_pdf = get_governing_selection_pdf(design, score_pdf, period_pdf)
    path_dict = design.run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf, data_context)
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)
    baseline_dict = get_path_baseline_dict(ohlcv_array_dict, path_dict, date1, date2, data_context)
    strategy_return_pdf = get_chained_daily_return_pdf([path_dict["daily_equity_pdf"]])
    buy_hold_return_pdf = get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]])
    performance_pdf = get_performance_over_time_pdf(strategy_return_pdf, buy_hold_return_pdf)
    quarter_pdf = get_performance_quarter_pdf(strategy_return_pdf, buy_hold_return_pdf)
    candidate_list = [design.get_session_candidate_str(session_date, period_pdf, selection_pdf) for session_date in path_dict["decision_session_list"]]
    activity_dict = get_turnover_switch_dict(path_dict["target_weight_arr"], int((path_dict["trade_pdf"]["reason"] != "END").sum()) if len(path_dict["trade_pdf"]) else 0, candidate_list)
    path_period_pdf = get_period_return_pdf(path_dict["daily_equity_pdf"], period_pdf)
    buy_hold_period_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], period_pdf)
    summary_dict = get_window_return_summary_dict(path_period_pdf["total_return"].to_numpy(), buy_hold_period_pdf["total_return"].to_numpy())
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=exp_config.BOOTSTRAP_BLOCK_MONTH_COUNT)
    log_excess_1m_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=1)
    named_baseline_dict = {"constant_exposure": baseline_dict["constant_exposure"], "random_shift_median": baseline_dict["random_shift_median"]}
    success_dict = get_success_criteria_dict(strategy_return_pdf, buy_hold_return_pdf, named_baseline_dict)
    path_return = path_dict["metric_dict"]["total_return"]
    beats_buy_hold_bool = path_return > buy_hold_dict["metric_dict"]["total_return"]
    beats_constant_bool = path_return > baseline_dict["constant_exposure"]
    beats_median_bool = path_return > baseline_dict["random_shift_median"]
    beats_half_bool = baseline_dict["random_shift_beats_share"] > 0.5
    verdict_str = "CONTINUE" if beats_buy_hold_bool and beats_constant_bool and beats_median_bool and beats_half_bool else "STOP"
    return {"span_dict": span_dict, "period_pdf": period_pdf, "fold_pdf": fold_pdf, "score_pdf": score_pdf,
            "selection_pdf": selection_pdf, "path_dict": path_dict, "buy_hold_dict": buy_hold_dict,
            "baseline_dict": baseline_dict, "optimistic_dict": get_optimistic_dict(score_pdf),
            "performance_pdf": performance_pdf, "quarter_pdf": quarter_pdf, "activity_dict": activity_dict,
            "summary_dict": summary_dict, "log_excess_dict": log_excess_dict, "log_excess_1m_dict": log_excess_1m_dict,
            "success_dict": success_dict, "verdict_str": verdict_str, "beats_buy_hold_bool": beats_buy_hold_bool,
            "beats_constant_bool": beats_constant_bool, "beats_median_bool": beats_median_bool, "beats_half_bool": beats_half_bool}
