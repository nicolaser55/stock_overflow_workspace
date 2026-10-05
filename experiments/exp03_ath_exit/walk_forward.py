import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp03_ath_exit import config as exp_config
# IMPORT THE WALK-FORWARD SCHEDULE
from so.core.schedule import get_walk_forward_fold_pdf
# IMPORT THE EVALUATION FUNCTIONS (POOLED SELECTION)
from so.core.evaluation import get_pooled_selection_pdf as get_generic_pooled_selection_pdf
# IMPORT EXIT AND RE-ENTRY SIMULATION FUNCTIONS
from so.core.reentry_simulation import get_buy_and_hold_result_dict, simulate_trend_rule_dict, get_random_reentry_func
# IMPORT THE RULES
from experiments.exp03_ath_exit.rules import get_rule_candidate_list, simulate_rule_dict, get_rule_metric_dict, get_random_exit_signal_arr, \
                                             get_random_baseline_probability_dict

"""
Walk-Forward: exp03_ath_exit (step 02, PROTOCOL.md §6-§8)

No model is trained: the 15 rules are fixed. The walk-forward only decides WHICH rule to use, with information from
earlier quarters, and measures how that choice does on later quarters.

Per fold:
    1. VALIDATION: simulate every rule on the validation quarter (start invested, as buy-and-hold).
    2. SELECTION: each rule is scored by its MEAN validation excess return over the last SELECTION_POOLED_QUARTER_COUNT
       quarters (this fold and the previous ones). Ties: the tighter ATH threshold, then the rule order.
    3. PRIOR-ONLY PATH: the rule selected at fold f is re-simulated on the validation quarter of fold f + 1 with its
       baselines (window "valid"): buy-and-hold, random buy-back (same exit), random exit (same buy-back), trend rule.
    4. TEST (run modes "latest" / "history" only): the selected rule on the test window, once, with the same baselines.

The schedule equals exp02's (20-session embargo, 10-year fixed window) so both experiments use the same validation quarters.
"""

"""
Schedule
"""

# FUNCTION: GET THE WALK-FORWARD FOLDS
def get_fold_pdf(session_date_list_in, max_fold_count_in=None, train_years_in=exp_config.FIXED_TRAIN_WINDOW_YEARS):
    """
    Builds the schedule (shared conventions, the experiment's embargo and fixed window; no model is trained).

    Args:
        session_date_list_in (list[datetime.date]): Session dates of the data
        max_fold_count_in (int | None): Keep only the most recent folds
        train_years_in (int): Length of the fixed window that a fold must fit (years; smaller in tests)

    Returns:
        pd.DataFrame: Output of so.core.schedule.get_walk_forward_fold_pdf
    """
    # RETURN THE SCHEDULE
    return get_walk_forward_fold_pdf(session_date_list_in, exp_config.EMBARGO_TRADING_DAYS, [train_years_in], max_fold_count_in=max_fold_count_in)

"""
Validation And Selection
"""

# FUNCTION: RUN THE VALIDATION CANDIDATES OF ONE FOLD
def run_validation_candidate_pdf(fold_row_in, daily_pdf_in, ohlcv_array_dict_in, candidate_dict_list_in=None):
    """
    Simulates every rule on the validation quarter of a fold.

    Args:
        fold_row_in (pd.Series): Row of get_fold_pdf
        daily_pdf_in (pd.DataFrame): Daily table (indexed by session position)
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        candidate_dict_list_in (list[dict] | None): Rule candidates (None = rules.get_rule_candidate_list())

    Returns:
        pd.DataFrame: One row per rule with the validation metrics and the excess return over buy-and-hold
    """
    # COLLECT THE VALIDATION WINDOW AND THE CANDIDATES
    valid_start, valid_end = fold_row_in["valid_start"], fold_row_in["valid_end"]
    candidate_dict_list = candidate_dict_list_in if candidate_dict_list_in is not None else get_rule_candidate_list()
    # SIMULATE BUY AND HOLD ONCE
    buy_hold_metric_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, valid_start, valid_end)["metric_dict"]
    # LIST TO HOLD THE CANDIDATE ROWS
    candidate_row_list = []
    # ITERATE OVER THE RULES
    for candidate_dict in candidate_dict_list:
        # SIMULATE THE RULE
        simulation_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, valid_start, valid_end, candidate_dict)
        # STORE THE CANDIDATE
        candidate_row_list.append({"fold_id": int(fold_row_in["fold_id"]), **candidate_dict,
                                   **{f"valid_{key}": value for key, value in simulation_dict["metric_dict"].items()},
                                   **{f"valid_buy_hold_{key}": value for key, value in buy_hold_metric_dict.items()},
                                   "valid_excess_return": round(simulation_dict["metric_dict"]["total_return"] - buy_hold_metric_dict["total_return"], 8),
                                   "valid_mean_log_share_gain": get_rule_metric_dict(simulation_dict, buy_hold_metric_dict["total_return"])["mean_log_share_gain"]})
    # RETURN THE CANDIDATES
    return pd.DataFrame(candidate_row_list)

# FUNCTION: ADD THE POOLED SELECTION SCORE AND PICK ONE RULE PER FOLD
def get_pooled_selection_pdf(candidate_pdf_in, pooled_quarter_count_in=exp_config.SELECTION_POOLED_QUARTER_COUNT):
    """
    Scores every rule of fold f by its mean validation excess return over folds f - pooled_quarter_count_in + 1 .. f
    and selects the best rule per fold. Ties: the tighter ATH threshold (fewer exits), then the rule order.

    Args:
        candidate_pdf_in (pd.DataFrame): Concatenated outputs of run_validation_candidate_pdf
        pooled_quarter_count_in (int): Number of validation quarters pooled

    Returns:
        pd.DataFrame: One selected row per fold (with pooled_valid_excess_return and pooled_quarter_count)
    """
    # SELECT WITH THE GENERIC POOLED RULE
    selection_pdf = get_generic_pooled_selection_pdf(candidate_pdf_in, ["ath_within", "rule"], "valid_excess_return", pooled_quarter_count_in,
                                                     [("ath_within", True), ("rule_order", True)])
    # RETURN THE SELECTION
    return selection_pdf.rename(columns={"pooled_score": "pooled_valid_excess_return"})

"""
Evaluation Window With Baselines (prior-only path on validation, test windows)
"""

# FUNCTION: SIMULATE ONE WINDOW WITH THE SELECTED RULE AND ITS BASELINES
def run_window_with_baseline_dict(fold_row_in, selection_row_in, daily_pdf_in, ohlcv_array_dict_in, window_str_in="valid", alert_in=True):
    """
    Simulates the selected rule on one window of a fold with every baseline and the cost sensitivity.

    Baselines (same simulator, same costs):
        buy_hold                buy-and-hold over the window
        random_buyback_<i>      same ATH exit, buy back at random (probability 1 / the rule's mean cash decisions per episode)
        random_exit_<i>         exit at random while invested (probability = the rule's exits per invested decision), same buy-back
        trend_ma200             the 200-session moving-average rule (reference only)
    When the rule never exits in the window, every random run equals the rule (nothing to randomize).

    Args:
        fold_row_in (pd.Series): Row of get_fold_pdf
        selection_row_in (pd.Series | dict): Selected rule (ath_within, rule, buyback_type, buyback_value)
        daily_pdf_in (pd.DataFrame): Daily table (indexed by session position)
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        window_str_in (str): "valid" or "test"
        alert_in (bool): Display a summary line

    Returns:
        dict: metric_dict, baseline_pdf, cost_sensitivity_pdf, transaction_pdf, episode_pdf, daily_equity_pdf, buy_hold_daily_equity_pdf
    """
    # COLLECT THE WINDOW AND THE RULE
    window_start, window_end = fold_row_in[f"{window_str_in}_start"], fold_row_in[f"{window_str_in}_end"]
    candidate_dict = {key: selection_row_in[key] for key in ["ath_within", "rule", "buyback_type", "buyback_value"]}
    # SIMULATE THE RULE AND BUY AND HOLD
    simulation_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, window_start, window_end, candidate_dict)
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, window_start, window_end)
    # LIST TO HOLD THE BASELINE ROWS
    baseline_dict_list = [{"baseline": "model", **simulation_dict["metric_dict"]}, {"baseline": "buy_hold", **buy_hold_dict["metric_dict"]}]
    # MATCH THE RANDOM BASELINES TO THE RULE'S ACTIVITY
    probability_dict = get_random_baseline_probability_dict(simulation_dict)
    # ITERATE OVER THE RANDOM RUNS
    for run_idx in range(exp_config.RANDOM_RUN_COUNT):
        # IF THE RULE NEVER EXITED (EVERY RANDOM RUN EQUALS THE RULE)
        if not np.isfinite(probability_dict["exit_probability"]):
            baseline_dict_list += [{"baseline": f"random_buyback_{run_idx:02d}", **simulation_dict["metric_dict"]},
                                   {"baseline": f"random_exit_{run_idx:02d}", **simulation_dict["metric_dict"]}]
            continue
        # RANDOM BUY-BACK (SAME EXIT)
        random_buyback_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, window_start, window_end, candidate_dict,
                                                 reentry_func_tuple_in=(get_random_reentry_func(probability_dict["buyback_probability"], config.RANDOM_SEED + run_idx), "random"))
        baseline_dict_list.append({"baseline": f"random_buyback_{run_idx:02d}", **random_buyback_dict["metric_dict"]})
        # RANDOM EXIT (SAME BUY-BACK RULE)
        random_exit_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, window_start, window_end, candidate_dict,
                                              exit_signal_arr_in=get_random_exit_signal_arr(len(daily_pdf_in), probability_dict["exit_probability"], config.RANDOM_SEED + 1000 + run_idx))
        baseline_dict_list.append({"baseline": f"random_exit_{run_idx:02d}", **random_exit_dict["metric_dict"]})
    # TEXTBOOK TREND RULE (REFERENCE)
    trend_dict = simulate_trend_rule_dict(ohlcv_array_dict_in, daily_pdf_in, window_start, window_end, f"ma{exp_config.TREND_RULE_MA_SESSIONS}_dist_pct")
    baseline_dict_list.append({"baseline": f"trend_ma{exp_config.TREND_RULE_MA_SESSIONS}", **trend_dict["metric_dict"]})
    baseline_pdf = pd.DataFrame(baseline_dict_list)
    baseline_pdf["excess_return"] = baseline_pdf["total_return"] - buy_hold_dict["metric_dict"]["total_return"]
    # COST SENSITIVITY (SAME RULE, DIFFERENT SLIPPAGE; BUY-AND-HOLD RECOMPUTED WITH THE SAME SLIPPAGE)
    cost_dict_list = []
    for slippage in config.COST_SENSITIVITY_SLIPPAGE_LIST:
        cost_simulation_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, window_start, window_end, candidate_dict, entry_slippage_in=slippage, market_exit_slippage_in=slippage)
        cost_buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, window_start, window_end, entry_slippage_in=slippage, market_exit_slippage_in=slippage)
        cost_dict_list.append({"slippage_per_share": slippage, "total_return": cost_simulation_dict["metric_dict"]["total_return"],
                               "buy_hold_return": cost_buy_hold_dict["metric_dict"]["total_return"],
                               "excess_return": cost_simulation_dict["metric_dict"]["total_return"] - cost_buy_hold_dict["metric_dict"]["total_return"]})
    # DEFINE THE METRICS
    metric_dict = {**simulation_dict["metric_dict"], **{f"buy_hold_{key}": value for key, value in buy_hold_dict["metric_dict"].items()},
                   "excess_return": round(simulation_dict["metric_dict"]["total_return"] - buy_hold_dict["metric_dict"]["total_return"], 8), **probability_dict}
    # DISPLAY INFORMATION
    print(f"\t{window_str_in}: total return {metric_dict['total_return']:.4%} | buy & hold {metric_dict['buy_hold_total_return']:.4%} | exits {metric_dict['signal_exit_count']}") if alert_in else None
    # RETURN THE RESULTS
    return {"metric_dict": metric_dict, "baseline_pdf": baseline_pdf, "cost_sensitivity_pdf": pd.DataFrame(cost_dict_list),
            "transaction_pdf": simulation_dict["transaction_pdf"], "episode_pdf": simulation_dict["episode_pdf"],
            "daily_equity_pdf": simulation_dict["daily_equity_pdf"], "buy_hold_daily_equity_pdf": buy_hold_dict["daily_equity_pdf"]}
