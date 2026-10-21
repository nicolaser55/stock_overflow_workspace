import numpy as np
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL, SEEDS, TOLERANCE)
from so import config
# IMPORT THE RANDOM-FAMILY SUMMARY ALREADY USED BY DEVELOPMENT REPORTS
from so.core.baseline_report import get_random_family_stat_dict
# IMPORT THE ENGINE-ONLY REPLAY OF RECORDED DECISIONS
from so.runner.engine import FractionalWeightEngine, get_decision_dict
from so.runner.loop import run_engine_decisions_dict

"""
Runner Baselines (infrastructure step 4b-1b)

Buy-and-hold, constant exposure at the prior-only path's average weight (rebalanced daily), and random timing with
the path's number of switches between the same weights. All three use the fractional-weight engine and the shared
costs. Random timing uses config.RANDOM_SEED .. RANDOM_SEED + RUNNER_RANDOM_TIMING_SEED_COUNT - 1 (100 fixed seeds).

A switch is a change in the filled target-weight sequence larger than NUMERIC_TOLERANCE. Random paths start at the
path's first weight and, at each drawn switch date, move to a different weight from that sequence's unique set.
"""


# FUNCTION: FILL KEEP-NaN TARGETS WITH THE LAST FINITE WEIGHT
def get_filled_target_weight_arr(target_weight_arr_in):
    """
    NaN means keep. The last session of a stream is stored as NaN (the engine sells at the close).

    Args:
        target_weight_arr_in (array-like): One target per window session

    Returns:
        np.ndarray: Copy with NaN replaced by the previous finite weight
    """
    # WALK FORWARD, CARRYING THE LAST FINITE VALUE
    weight_arr = np.asarray(target_weight_arr_in, dtype=float).copy()
    last_weight = np.nan
    for idx in range(len(weight_arr)):
        if np.isfinite(weight_arr[idx]):
            last_weight = float(weight_arr[idx])
        elif np.isfinite(last_weight):
            weight_arr[idx] = last_weight
    return weight_arr


# FUNCTION: HOW MANY TIMES THE FILLED TARGET WEIGHT CHANGES
def get_weight_switch_count_int(target_weight_arr_in):
    """
    Args:
        target_weight_arr_in (array-like): One target per window session

    Returns:
        int: Switch count
    """
    # A SINGLE SESSION CANNOT SWITCH
    filled_arr = get_filled_target_weight_arr(target_weight_arr_in)
    if len(filled_arr) < 2:
        return 0
    return int(np.sum(np.abs(np.diff(filled_arr)) > float(config.NUMERIC_TOLERANCE)))


# FUNCTION: UNIQUE FILLED TARGET WEIGHTS IN FIRST-SEEN ORDER
def get_unique_weight_list(target_weight_arr_in):
    """
    Args:
        target_weight_arr_in (array-like): One target per window session

    Returns:
        list[float]: Unique weights
    """
    # TOLERANCE MATCHES THE SWITCH COUNT
    unique_list = []
    for weight in get_filled_target_weight_arr(target_weight_arr_in):
        if not np.isfinite(weight):
            continue
        if not any(abs(float(weight) - other) <= float(config.NUMERIC_TOLERANCE) for other in unique_list):
            unique_list.append(float(weight))
    return unique_list


# FUNCTION: THE FIXED RANDOM-TIMING SEEDS
def get_random_timing_seed_list(count_int_in=None):
    """
    config.RANDOM_SEED + 0 .. count-1. The default count is RUNNER_RANDOM_TIMING_SEED_COUNT (100).

    Args:
        count_int_in (int | None): How many seeds (None = the registered count)

    Returns:
        list[int]: Seeds
    """
    # THE SAME OFFSET FOR EVERY RUN
    count_int = int(config.RUNNER_RANDOM_TIMING_SEED_COUNT if count_int_in is None else count_int_in)
    if count_int < 0:
        raise ValueError("random-timing seed count must be >= 0.")
    return [int(config.RANDOM_SEED) + idx for idx in range(count_int)]


# FUNCTION: A RANDOM TARGET-WEIGHT PATH WITH THE SAME SWITCH COUNT
def get_random_timing_weight_arr(target_weight_arr_in, seed_in):
    """
    Same unique weights, same number of switches, random switch dates. Starts at the path's first weight. One unique
    weight, or zero switches, returns the filled path (no timing to randomize).

    Args:
        target_weight_arr_in (array-like): Path targets
        seed_in (int): Generator seed

    Returns:
        np.ndarray: One weight per session
    """
    # FILL KEEP-NaN BEFORE COUNTING SWITCHES
    filled_arr = get_filled_target_weight_arr(target_weight_arr_in)
    session_count = int(len(filled_arr))
    unique_list = get_unique_weight_list(filled_arr)
    switch_count = get_weight_switch_count_int(filled_arr)
    if session_count == 0 or switch_count == 0 or len(unique_list) <= 1:
        return filled_arr
    rng = np.random.default_rng(int(seed_in))
    switch_count = min(switch_count, session_count - 1)
    switch_pos_arr = np.sort(rng.choice(np.arange(1, session_count), size=switch_count, replace=False))
    switch_set = set(int(pos) for pos in switch_pos_arr)
    out_arr = np.empty(session_count, dtype=float)
    current_weight = float(filled_arr[0])
    out_arr[0] = current_weight
    for idx in range(1, session_count):
        if idx in switch_set:
            other_list = [weight for weight in unique_list if abs(weight - current_weight) > float(config.NUMERIC_TOLERANCE)]
            current_weight = float(other_list[int(rng.integers(0, len(other_list)))])
        out_arr[idx] = current_weight
    return out_arr


# FUNCTION: DECISION DICTS FOR A WEIGHT ARRAY
def get_weight_decision_list(weight_arr_in):
    """
    Args:
        weight_arr_in (array-like): One target per session (NaN = keep)

    Returns:
        list[dict]: get_decision_dict outputs
    """
    # NaN STAYS A KEEP DECISION
    decision_list = []
    for weight in np.asarray(weight_arr_in, dtype=float):
        decision_list.append(get_decision_dict(None if not np.isfinite(weight) else float(weight)))
    return decision_list


# FUNCTION: ONE ENGINE PASS OVER A TARGET-WEIGHT ARRAY
def run_weight_path_dict(ohlcv_array_dict_in, date1_in, date2_in, weight_arr_in, initial_weight_in, dead_band_in=0.0,
                         initial_capital_in=config.INITIAL_CAPITAL, entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                         market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
    """
    The same fractional engine and costs as a candidate stream. dead_band 0 rebalances daily.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span bounds
        weight_arr_in (array-like): One target per window session
        initial_weight_in (float): Weight bought at the first 10:00 open
        dead_band_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Engine

    Returns:
        dict: Engine result
    """
    # A FRESH ENGINE PER PATH (NO STATE SHARED WITH THE STRATEGY)
    engine = FractionalWeightEngine(dead_band_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in)
    return run_engine_decisions_dict(ohlcv_array_dict_in, date1_in, date2_in, get_weight_decision_list(weight_arr_in),
                                     engine, float(initial_weight_in), float(dead_band_in), initial_capital_in,
                                     entry_slippage_in, market_exit_slippage_in)


# FUNCTION: BUY-AND-HOLD, CONSTANT EXPOSURE AND RANDOM TIMING ON ONE SPAN
def get_runner_baseline_dict(ohlcv_array_dict_in, date1_in, date2_in, prior_only_dict_in, seed_count_int_in=None,
                             initial_capital_in=config.INITIAL_CAPITAL,
                             entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                             market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
    """
    Baselines over the prior-only path's span, same engine and costs. Constant exposure uses the path's mean_weight
    and rebalances daily (dead band 0). Random timing uses the path's target weights and switch count.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span bounds
        prior_only_dict_in (dict): Engine result of the prior-only path (target_weight_arr, metric_dict)
        seed_count_int_in (int | None): Random draws (None = RUNNER_RANDOM_TIMING_SEED_COUNT)
        initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Engine costs

    Returns:
        dict: Buy-and-hold, constant-exposure and random-timing returns and the random-family stats
    """
    # THE PATH'S TARGETS AND ITS AVERAGE REALIZED WEIGHT (LAST SESSION EXCLUDED BY THE ENGINE)
    if prior_only_dict_in is None or "target_weight_arr" not in prior_only_dict_in:
        raise ValueError("the baselines need the prior-only path's target_weight_arr.")
    target_arr = np.asarray(prior_only_dict_in["target_weight_arr"], dtype=float)
    session_count = int(len(target_arr))
    if session_count == 0:
        raise ValueError("the prior-only path has no sessions.")
    metric_dict = dict(prior_only_dict_in.get("metric_dict") or {})
    mean_weight = float(metric_dict["mean_weight"]) if np.isfinite(metric_dict.get("mean_weight", np.nan)) else 0.0
    path_return = float(metric_dict["total_return"]) if np.isfinite(metric_dict.get("total_return", np.nan)) else np.nan
    # BUY-AND-HOLD: WEIGHT 1 EVERY SESSION, DAILY REBALANCE (MATCHES THE CONSTANT BASELINE AT WEIGHT 1)
    buy_hold_dict = run_weight_path_dict(ohlcv_array_dict_in, date1_in, date2_in, np.ones(session_count, dtype=float),
                                         1.0, 0.0, initial_capital_in, entry_slippage_in, market_exit_slippage_in)
    # CONSTANT EXPOSURE AT THE PATH'S AVERAGE WEIGHT, REBALANCED DAILY
    constant_arr = np.full(session_count, mean_weight, dtype=float)
    constant_dict = run_weight_path_dict(ohlcv_array_dict_in, date1_in, date2_in, constant_arr, mean_weight, 0.0,
                                         initial_capital_in, entry_slippage_in, market_exit_slippage_in)
    # RANDOM TIMING: SAME SWITCH COUNT BETWEEN THE SAME WEIGHTS, FIXED SEEDS
    seed_list = get_random_timing_seed_list(seed_count_int_in)
    random_return_list = []
    for seed_int in seed_list:
        random_arr = get_random_timing_weight_arr(target_arr, seed_int)
        initial_weight = float(random_arr[0]) if len(random_arr) and np.isfinite(random_arr[0]) else 0.0
        random_dict = run_weight_path_dict(ohlcv_array_dict_in, date1_in, date2_in, random_arr, initial_weight, 0.0,
                                           initial_capital_in, entry_slippage_in, market_exit_slippage_in)
        random_return_list.append(float(random_dict["metric_dict"]["total_return"]))
    family_dict = get_random_family_stat_dict("random_timing", random_return_list, path_return)
    return {"buy_hold_total_return": float(buy_hold_dict["metric_dict"]["total_return"]),
            "buy_hold_metric_dict": dict(buy_hold_dict["metric_dict"]),
            "buy_hold_daily_equity_pdf": buy_hold_dict["daily_equity_pdf"],
            "constant_exposure_total_return": float(constant_dict["metric_dict"]["total_return"]),
            "constant_exposure_weight": mean_weight,
            "constant_exposure_metric_dict": dict(constant_dict["metric_dict"]),
            "constant_exposure_daily_equity_pdf": constant_dict["daily_equity_pdf"],
            "random_timing_return_list": list(random_return_list),
            "random_timing_seed_list": list(seed_list),
            "random_timing_switch_count": get_weight_switch_count_int(target_arr),
            "random_timing_unique_weight_list": get_unique_weight_list(target_arr),
            **family_dict}
