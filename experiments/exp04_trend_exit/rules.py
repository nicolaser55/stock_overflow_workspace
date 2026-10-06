import pandas as pd
import numpy as np
# IMPORT THE EXPERIMENT CONFIGURATION
from experiments.exp04_trend_exit import config as exp_config
# IMPORT THE WALK-FORWARD SCHEDULE AND THE REPLAY PERIODS
from so.core.schedule import get_walk_forward_fold_pdf
from so.core.continuous_replay import get_replay_period_pdf

"""
Rules: exp04_trend_exit (PROTOCOL.md §4)

State machine (so.core.reentry_simulation, no stop, no forced buy-back):
    INVESTED --(the 15:58 close has been more than x BELOW the 200-session average for n consecutive decisions)--> CASH
    CASH     --(the 15:58 close is more than x ABOVE the 200-session average)-----------------------------------> INVESTED
    Trades fill at the 15:59 open (+/- slippage), IBKR fees, cash earns 0%.

    - 200-session average: mean of the previous 200 complete session closes (so.features.daily_features
      "ma200_dist_pct" = decision close / average - 1). NaN (the first 200 sessions of the data) never signals.
    - The n consecutive decisions are counted on the data, whatever the position (a sale happens on the n-th
      consecutive decision below -x if the strategy is invested then).
    - x = 0 and n = 1 is the textbook 200-day rule (so.core.reentry_simulation.simulate_trend_rule_dict).

The identity of exp02 / exp03 applies: an episode that sells at S and buys back at R ends with S / R times the shares,
so the rule gains only if, on average, it buys back lower than it sold, by more than the costs.
"""

# FUNCTION: GET THE SCHEDULE AND THE REPLAY PERIODS
def get_schedule_tuple(session_date_list_in, train_years_in=exp_config.FIXED_TRAIN_WINDOW_YEARS, max_fold_count_in=None):
    """
    Builds the exp02 / exp03 schedule (20-session embargo, folds that fit a 10-year window) and its replay periods.

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

# FUNCTION: GET THE RULE CANDIDATES
def get_rule_candidate_list(buffer_list_in=exp_config.BUFFER_LIST, confirmation_list_in=exp_config.CONFIRMATION_LIST):
    """
    Lists the 9 candidates in a fixed order (buffer, then confirmation).

    Args:
        buffer_list_in (list[float]): Buffers x
        confirmation_list_in (list[int]): Confirmations n

    Returns:
        list[dict]: buffer, confirmation
    """
    # RETURN THE GRID
    return [{"buffer": float(buffer), "confirmation": int(confirmation)} for buffer in buffer_list_in for confirmation in confirmation_list_in]

# FUNCTION: GET THE EXIT SIGNAL OF A CANDIDATE
def get_trend_exit_signal_arr(daily_pdf_in, buffer_in, confirmation_in, ma_dist_col_str_in=exp_config.MA_DIST_COL_STR):
    """
    True on a session if the decision close was more than buffer_in below the average on this decision and the
    confirmation_in - 1 previous decisions.

    Args:
        daily_pdf_in (pd.DataFrame): Output of so.features.daily_features.get_daily_feature_pdf
        buffer_in (float): Buffer x
        confirmation_in (int): Confirmation n
        ma_dist_col_str_in (str): Moving average distance column

    Returns:
        np.ndarray: Bool per session position
    """
    # FLAG THE DECISIONS BELOW -x (NaN IS NEVER BELOW)
    below_series = pd.Series(np.nan_to_num(daily_pdf_in[ma_dist_col_str_in].to_numpy(dtype=float), nan=0.0) < -buffer_in).astype(float)
    # RETURN TRUE WHEN THE LAST n DECISIONS ARE ALL BELOW
    return (below_series.rolling(confirmation_in, min_periods=confirmation_in).min() == 1).to_numpy()

# FUNCTION: GET THE RE-ENTRY SIGNAL OF A CANDIDATE
def get_trend_reentry_signal_arr(daily_pdf_in, buffer_in, ma_dist_col_str_in=exp_config.MA_DIST_COL_STR):
    """
    True on a session if the decision close is more than buffer_in above the average.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table
        buffer_in (float): Buffer x
        ma_dist_col_str_in (str): Moving average distance column

    Returns:
        np.ndarray: Bool per session position
    """
    # RETURN THE SIGNAL (NaN IS NEVER ABOVE)
    return np.nan_to_num(daily_pdf_in[ma_dist_col_str_in].to_numpy(dtype=float), nan=0.0) > buffer_in

# FUNCTION: GET THE RULE BUILDER OF THE EXPERIMENT
def get_rule_builder_func(daily_pdf_in):
    """
    Returns f(candidate_dict) -> (exit_signal_arr, reentry_func, reentry_reason_str) for so.core.replay_walk_forward.

    Args:
        daily_pdf_in (pd.DataFrame): Daily table (indexed by session position)

    Returns:
        function: Rule builder
    """
    # FUNCTION: BUILD ONE CANDIDATE
    def rule_builder_func(candidate_dict_in):
        exit_signal_arr = get_trend_exit_signal_arr(daily_pdf_in, candidate_dict_in["buffer"], candidate_dict_in["confirmation"])
        reentry_signal_arr = get_trend_reentry_signal_arr(daily_pdf_in, candidate_dict_in["buffer"])
        return exit_signal_arr, (lambda session_idx, cash_session_count, episode_dict: bool(reentry_signal_arr[session_idx])), "rule"
    # RETURN THE BUILDER
    return rule_builder_func
