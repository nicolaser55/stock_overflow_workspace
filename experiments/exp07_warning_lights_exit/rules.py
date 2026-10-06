import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp07_warning_lights_exit import config as exp_config
# IMPORT THE WALK-FORWARD SCHEDULE AND THE REPLAY PERIODS
from so.core.schedule import get_walk_forward_fold_pdf
from so.core.continuous_replay import get_replay_period_pdf

"""
Rules: exp07_warning_lights_exit (PROTOCOL.md §5)

State machine (so.core.reentry_simulation, no stop, continuous replay, no forced buy-back):
    INVESTED --(at least k lights on at the 15:58 decision)-------> CASH      (sell at the 15:59 open)
    CASH     --(fewer than k - 1 lights on at the 15:58 decision)-> INVESTED  (buy at the 15:59 open)

    lights (exp_config.LIGHT_DICT; a missing feature is an off light):
        below_ma200            ma200_dist_pct < 0
        return_250d_negative   return_250d < 0
        volatility_rising      volatility_ratio_20_60 > 1.2
        ath_drawdown_10pct     ath_drawdown_pct < -10%
        high60_stale           sessions_since_high60 > 20

The gap between the exit (>= k) and the re-entry (<= k - 2) is a hysteresis: one light switching on and off does not
trade. Exits are expected to be rare (3-8 in 21 years); the episode scorecard is the main evidence.
"""

"""
Schedule And Candidates
"""

# FUNCTION: GET THE SCHEDULE AND THE REPLAY PERIODS
def get_schedule_tuple(session_date_list_in, train_years_in=exp_config.FIXED_TRAIN_WINDOW_YEARS, max_fold_count_in=None):
    """
    Builds the exp02-exp06 schedule (20-session embargo, folds that fit a 10-year window) and its replay periods.

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
def get_rule_candidate_list(k_list_in=exp_config.LIGHT_K_LIST):
    """
    Lists the 3 candidates in a fixed order.

    Args:
        k_list_in (list[int]): Exit thresholds k

    Returns:
        list[dict]: light_k
    """
    # RETURN THE GRID
    return [{"light_k": int(k)} for k in k_list_in]

"""
Lights And Signals
"""

# FUNCTION: GET THE LIGHTS OF EVERY SESSION
def get_light_pdf(daily_pdf_in, light_dict_in=exp_config.LIGHT_DICT):
    """
    Evaluates every light at every decision (a missing feature is an off light) and counts the lights on.

    Args:
        daily_pdf_in (pd.DataFrame): Output of so.features.daily_features.get_daily_feature_pdf
        light_dict_in (dict): Light name -> (feature, comparison "<" or ">", threshold)

    Returns:
        pd.DataFrame: date, one bool column per light, light_count
    """
    # DICTIONARY TO HOLD THE LIGHTS
    light_col_dict = {"date": daily_pdf_in["date"].to_numpy()}
    # ITERATE OVER THE LIGHTS
    for light_str, (feature_str, comparison_str, threshold) in light_dict_in.items():
        feature_arr = daily_pdf_in[feature_str].to_numpy(dtype=float)
        with np.errstate(invalid="ignore"):
            light_arr = feature_arr < threshold if comparison_str == "<" else feature_arr > threshold
        light_col_dict[light_str] = light_arr & np.isfinite(feature_arr)
    # COUNT THE LIGHTS ON
    light_pdf = pd.DataFrame(light_col_dict)
    light_pdf["light_count"] = light_pdf[list(light_dict_in)].sum(axis=1).astype(int)
    # RETURN THE LIGHTS
    return light_pdf

# FUNCTION: GET THE RULE BUILDER OF THE EXPERIMENT
def get_rule_builder_func(daily_pdf_in):
    """
    Returns f(candidate_dict) -> (exit_signal_arr, reentry_func, reason_str) for so.core.replay_walk_forward: exit when
    light_count >= k, re-entry when light_count < k - 1.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table

    Returns:
        function: Rule builder
    """
    # COUNT THE LIGHTS ONCE
    light_count_arr = get_light_pdf(daily_pdf_in)["light_count"].to_numpy()
    # FUNCTION: BUILD ONE CANDIDATE
    def rule_builder_func(candidate_dict_in):
        light_k = int(candidate_dict_in["light_k"])
        reentry_arr = light_count_arr < light_k - 1
        return light_count_arr >= light_k, (lambda session_idx, cash_session_count, episode_dict: bool(reentry_arr[session_idx])), "rule"
    # RETURN THE BUILDER
    return rule_builder_func
