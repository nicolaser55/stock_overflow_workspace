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
the path's time at each weight. All three use the fractional-weight engine and the shared costs. Random timing uses
config.RANDOM_SEED .. RANDOM_SEED + RUNNER_RANDOM_TIMING_SEED_COUNT - 1 (100 fixed seeds).

A switch is a change in the filled target-weight sequence larger than NUMERIC_TOLERANCE. The base weight is the
weight the path spends the most sessions at (first-seen on a tie). A spell is a maximal run of sessions not at the
base weight; its internal weight sequence is kept. Each draw shuffles the spells and places them by splitting the
base-weight sessions into k+1 gaps, uniformly over compositions with middle gaps at least 1 (spells never merge)
and first and last gaps at least 0. Time at each weight is then the path's. The switch count may differ from the
path's only at the two window edges (a spell sitting at the start or the end has one side that does not touch
base). A path with no spells is returned unchanged. Shuffling run lengths in place does not move one-exit paths
and is not the baseline.
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


# FUNCTION: RUNS OF THE FILLED TARGET-WEIGHT PATH
def get_weight_run_list(target_weight_arr_in):
    """
    Consecutive sessions at the same weight (within NUMERIC_TOLERANCE) are one run.

    Args:
        target_weight_arr_in (array-like): One target per window session

    Returns:
        list[tuple[float, int]]: (weight, length) in path order
    """
    # EMPTY PATHS HAVE NO RUNS
    filled_arr = get_filled_target_weight_arr(target_weight_arr_in)
    if len(filled_arr) == 0:
        return []
    run_list = []
    current_weight = float(filled_arr[0])
    length_int = 1
    for weight in filled_arr[1:]:
        if abs(float(weight) - current_weight) <= float(config.NUMERIC_TOLERANCE):
            length_int += 1
        else:
            run_list.append((current_weight, length_int))
            current_weight = float(weight)
            length_int = 1
    run_list.append((current_weight, length_int))
    return run_list


# FUNCTION: SESSION COUNTS AT EACH UNIQUE WEIGHT
def get_weight_time_dict(target_weight_arr_in):
    """
    Args:
        target_weight_arr_in (array-like): One target per window session

    Returns:
        dict: weight -> session count, keys in first-seen order
    """
    # THE SAME UNIQUE KEYS AS get_unique_weight_list
    unique_list = get_unique_weight_list(target_weight_arr_in)
    filled_arr = get_filled_target_weight_arr(target_weight_arr_in)
    time_dict = {weight: 0 for weight in unique_list}
    for value in filled_arr:
        if not np.isfinite(value):
            continue
        for weight in unique_list:
            if abs(float(value) - weight) <= float(config.NUMERIC_TOLERANCE):
                time_dict[weight] += 1
                break
    return time_dict


# FUNCTION: WHETHER TWO WEIGHTS MATCH AT THE NUMERIC TOLERANCE
def get_weight_equal_bool(left_in, right_in):
    """
    Args:
        left_in, right_in (float): Weights

    Returns:
        bool: True if they match
    """
    # THE SAME BAND AS A SWITCH
    return abs(float(left_in) - float(right_in)) <= float(config.NUMERIC_TOLERANCE)


# FUNCTION: THE WEIGHT THE PATH SPENDS THE MOST SESSIONS AT
def get_base_weight_float(target_weight_arr_in):
    """
    First-seen unique weight among those with the maximum session count.

    Args:
        target_weight_arr_in (array-like): One target per window session

    Returns:
        float: Base weight (NaN if the path is empty)
    """
    # FIRST-SEEN WINS A TIE
    unique_list = get_unique_weight_list(target_weight_arr_in)
    if not unique_list:
        return float("nan")
    time_dict = get_weight_time_dict(target_weight_arr_in)
    max_count = max(time_dict.values())
    for weight in unique_list:
        if time_dict[weight] == max_count:
            return float(weight)
    return float(unique_list[0])


# FUNCTION: MAXIMAL NON-BASE SPELLS AND THE BASE-WEIGHT SESSION COUNT
def get_non_base_spell_list(target_weight_arr_in, base_weight_in=None):
    """
    Each spell is the weight sequence of a maximal run of sessions not at the base weight.

    Args:
        target_weight_arr_in (array-like): One target per window session
        base_weight_in (float | None): Base weight (None = get_base_weight_float)

    Returns:
        tuple: (list[list[float]] spells in path order, int base-weight session count)
    """
    # EMPTY PATHS HAVE NO SPELLS
    filled_arr = get_filled_target_weight_arr(target_weight_arr_in)
    if len(filled_arr) == 0:
        return [], 0
    base_weight = float(get_base_weight_float(filled_arr) if base_weight_in is None else base_weight_in)
    spell_list = []
    current_list = None
    base_count = 0
    for weight in filled_arr:
        if get_weight_equal_bool(weight, base_weight):
            base_count += 1
            if current_list is not None:
                spell_list.append(current_list)
                current_list = None
        elif current_list is None:
            current_list = [float(weight)]
        else:
            current_list.append(float(weight))
    if current_list is not None:
        spell_list.append(current_list)
    return spell_list, int(base_count)


# FUNCTION: k+1 GAP LENGTHS OVER THE BASE-WEIGHT SESSIONS
def get_random_timing_gap_list(base_count_int_in, spell_count_int_in, rng_in):
    """
    Uniform over compositions of base_count_int_in into spell_count_int_in + 1 gaps. Middle gaps are at least 1
    so spells never merge. First and last gaps are at least 0.

    Args:
        base_count_int_in (int): Sessions at the base weight
        spell_count_int_in (int): Number of spells k
        rng_in (np.random.Generator): Generator

    Returns:
        list[int]: k+1 gap lengths, summing to base_count_int_in
    """
    # NO SPELLS: ONE GAP HOLDING EVERY BASE SESSION
    spell_count = int(spell_count_int_in)
    base_count = int(base_count_int_in)
    if spell_count <= 0:
        return [base_count]
    middle_min_int = max(spell_count - 1, 0)
    if base_count < middle_min_int:
        raise ValueError("not enough base-weight sessions to separate the spells.")
    remainder_int = base_count - middle_min_int
    part_count = spell_count + 1
    if remainder_int == 0:
        extra_list = [0] * part_count
    elif part_count == 1:
        extra_list = [remainder_int]
    else:
        cut_arr = np.sort(rng_in.choice(remainder_int + part_count - 1, size=part_count - 1, replace=False))
        padded_arr = np.concatenate([[-1], cut_arr, [remainder_int + part_count - 1]])
        extra_list = [int(value) for value in (np.diff(padded_arr) - 1)]
    gap_list = list(extra_list)
    for middle_idx in range(1, spell_count):
        gap_list[middle_idx] += 1
    return gap_list


# FUNCTION: BASE-WEIGHT GAP LENGTHS OF A PLACED PATH
def get_base_gap_list(target_weight_arr_in, base_weight_in=None):
    """
    First and last gaps may be 0. Middle gaps are the base-weight runs between spells.

    Args:
        target_weight_arr_in (array-like): One target per window session
        base_weight_in (float | None): Base weight (None = get_base_weight_float)

    Returns:
        list[int]: spell_count + 1 gap lengths
    """
    # ONE GAP BEFORE EACH SPELL, THEN THE TRAILING GAP
    filled_arr = get_filled_target_weight_arr(target_weight_arr_in)
    if len(filled_arr) == 0:
        return []
    base_weight = float(get_base_weight_float(filled_arr) if base_weight_in is None else base_weight_in)
    spell_list, _base_count = get_non_base_spell_list(filled_arr, base_weight)
    if len(spell_list) == 0:
        return [int(len(filled_arr))]
    gap_list = []
    idx = 0
    session_count = int(len(filled_arr))
    for _spell in spell_list:
        gap_int = 0
        while idx < session_count and get_weight_equal_bool(filled_arr[idx], base_weight):
            gap_int += 1
            idx += 1
        gap_list.append(int(gap_int))
        while idx < session_count and not get_weight_equal_bool(filled_arr[idx], base_weight):
            idx += 1
    gap_int = 0
    while idx < session_count and get_weight_equal_bool(filled_arr[idx], base_weight):
        gap_int += 1
        idx += 1
    gap_list.append(int(gap_int))
    return gap_list


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


# FUNCTION: A RANDOM TARGET-WEIGHT PATH BY PLACING SPELLS
def get_random_timing_weight_arr(target_weight_arr_in, seed_in):
    """
    Same time at each weight as the path. The switch count may differ from the path's only at the two window
    edges. Base weight = the weight with the most sessions. Each spell is a maximal non-base run (internal
    sequence kept). The draw shuffles the spells and places them at uniformly random non-overlapping positions:
    the base-weight sessions are split into k+1 gaps (middle >= 1, first and last >= 0). A path with no spells
    is returned unchanged.

    Args:
        target_weight_arr_in (array-like): Path targets
        seed_in (int): Generator seed

    Returns:
        np.ndarray: One weight per session
    """
    # NO SPELLS: THE PATH IS ALREADY THE BASE WEIGHT
    filled_arr = get_filled_target_weight_arr(target_weight_arr_in)
    if len(filled_arr) == 0:
        return filled_arr
    base_weight = get_base_weight_float(filled_arr)
    spell_list, base_count = get_non_base_spell_list(filled_arr, base_weight)
    if len(spell_list) == 0:
        return filled_arr
    rng = np.random.default_rng(int(seed_in))
    order_arr = rng.permutation(len(spell_list))
    placed_spell_list = [spell_list[int(idx)] for idx in order_arr]
    gap_list = get_random_timing_gap_list(base_count, len(placed_spell_list), rng)
    out_list = []
    for spell_idx, spell in enumerate(placed_spell_list):
        out_list.extend([base_weight] * int(gap_list[spell_idx]))
        out_list.extend(spell)
    out_list.extend([base_weight] * int(gap_list[-1]))
    return np.asarray(out_list, dtype=float)


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
    and rebalances daily (dead band 0). Random timing places the path's non-base spells at random (same time at
    each weight; switch count may differ only at the two window edges).

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
    # RANDOM TIMING: SAME TIME AT EACH WEIGHT, SPELLS PLACED AT RANDOM, FIXED SEEDS
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
