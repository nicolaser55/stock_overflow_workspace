import math
import multiprocessing
import os
import time
import numpy as np
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL, SEEDS, TOLERANCE)
from so import config
# IMPORT THE COUNTING RULES OF THE MULTIPLE-TESTING RANDOM-TIMING TEST
from so.core.multiple_testing import (get_random_timing_draw_target_int, get_random_timing_at_or_above_max_int,
                                      get_random_timing_count_dict)
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

The multiple-testing random-timing test (roadmap R3, 2026-11-02; so.core.multiple_testing) needs far more draws than
the 100 registered ones when a path is near passing. get_random_timing_tail_dict continues the same seed sequence
(config.RANDOM_SEED + 100, + 101, ...) with the same draw code, in batches of RUNNER_RANDOM_TIMING_TAIL_BATCH on
RUNNER_RANDOM_TIMING_TAIL_PROCESS_COUNT spawned workers, up to the budget for N designs, and stops as soon as more draws
are at or above the path than the full budget would allow. A typical failing path stops after the registered draws,
with no extra draw. The count does not depend on the number of workers.
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


# FUNCTION: THE EXPOSURE PATH THE BASELINES REPRODUCE
def get_exposure_weight_arr(prior_only_dict_in, realized_bool_in):
    """
    One weight per window session. realized_bool_in True (all-or-nothing engines: trailing stop, barrier): the
    position actually held at each session close (daily_equity_pdf in_position, 1 or 0), because exits and stops
    happen inside the engine and the decision targets do not show them. The last session is NaN (the engine sells at
    its close). realized_bool_in False (fractional engine): the decision targets, which set the weight directly.

    Args:
        prior_only_dict_in (dict): Engine result of the prior-only path
        realized_bool_in (bool): Use the realized position instead of the decision targets

    Returns:
        np.ndarray: Exposure path (NaN = keep)
    """
    # THE FRACTIONAL ENGINE: THE TARGETS ARE THE EXPOSURE
    if not realized_bool_in:
        if "target_weight_arr" not in prior_only_dict_in:
            raise ValueError("the baselines need the prior-only path's target_weight_arr.")
        return np.asarray(prior_only_dict_in["target_weight_arr"], dtype=float)
    # ALL-OR-NOTHING ENGINES: THE POSITION AT EACH CLOSE
    equity_pdf = prior_only_dict_in.get("daily_equity_pdf")
    if equity_pdf is None or len(equity_pdf) == 0 or "in_position" not in equity_pdf.columns:
        raise ValueError("the baselines need the prior-only path's daily in_position column.")
    exposure_arr = equity_pdf["in_position"].astype(bool).to_numpy().astype(float)
    exposure_arr[-1] = np.nan
    return exposure_arr


# FUNCTION: BUY-AND-HOLD, CONSTANT EXPOSURE AND RANDOM TIMING ON ONE SPAN
def get_runner_baseline_dict(ohlcv_array_dict_in, date1_in, date2_in, prior_only_dict_in, seed_count_int_in=None,
                             initial_capital_in=config.INITIAL_CAPITAL,
                             entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                             market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                             realized_exposure_bool_in=False):
    """
    Baselines over the prior-only path's span, same engine and costs. Constant exposure uses the path's mean
    exposure and rebalances when it drifts more than RUNNER_CONSTANT_EXPOSURE_DEAD_BAND (0.05; audit S8). Random timing places the path's non-base spells at random (same time
    at each weight; switch count may differ only at the two window edges). For all-or-nothing engines
    (realized_exposure_bool_in True) the exposure is the position actually held at each close, not the decision
    targets (audit B1, 2026-10-25).

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span bounds
        prior_only_dict_in (dict): Engine result of the prior-only path (target_weight_arr, daily_equity_pdf)
        seed_count_int_in (int | None): Random draws (None = RUNNER_RANDOM_TIMING_SEED_COUNT)
        initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Engine costs
        realized_exposure_bool_in (bool): Exposure from the realized position (trailing stop, barrier)

    Returns:
        dict: Buy-and-hold, constant-exposure and random-timing returns and the random-family stats
    """
    # THE EXPOSURE PATH AND ITS MEAN (LAST SESSION EXCLUDED: EVERYTHING IS SOLD AT ITS CLOSE)
    if prior_only_dict_in is None:
        raise ValueError("the baselines need the prior-only path.")
    target_arr = get_exposure_weight_arr(prior_only_dict_in, realized_exposure_bool_in)
    session_count = int(len(target_arr))
    if session_count == 0:
        raise ValueError("the prior-only path has no sessions.")
    metric_dict = dict(prior_only_dict_in.get("metric_dict") or {})
    filled_arr = get_filled_target_weight_arr(target_arr)
    counted_arr = filled_arr[:-1] if len(filled_arr) > 1 else filled_arr
    counted_arr = counted_arr[np.isfinite(counted_arr)]
    if realized_exposure_bool_in:
        mean_weight = float(counted_arr.mean()) if len(counted_arr) else 0.0
    else:
        if not np.isfinite(metric_dict.get("mean_weight", np.nan)):
            raise ValueError("the fractional prior-only path has no mean_weight.")
        mean_weight = float(metric_dict["mean_weight"])
    path_return = float(metric_dict["total_return"]) if np.isfinite(metric_dict.get("total_return", np.nan)) else np.nan
    # BUY-AND-HOLD: WEIGHT 1 EVERY SESSION, DAILY REBALANCE (MATCHES THE CONSTANT BASELINE AT WEIGHT 1)
    buy_hold_dict = run_weight_path_dict(ohlcv_array_dict_in, date1_in, date2_in, np.ones(session_count, dtype=float),
                                         1.0, 0.0, initial_capital_in, entry_slippage_in, market_exit_slippage_in)
    # CONSTANT EXPOSURE AT THE PATH'S AVERAGE WEIGHT, REBALANCED DAILY
    constant_arr = np.full(session_count, mean_weight, dtype=float)
    constant_dict = run_weight_path_dict(ohlcv_array_dict_in, date1_in, date2_in, constant_arr, mean_weight,
                                         float(config.RUNNER_CONSTANT_EXPOSURE_DEAD_BAND), initial_capital_in,
                                         entry_slippage_in, market_exit_slippage_in)
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
            "constant_exposure_dead_band": float(config.RUNNER_CONSTANT_EXPOSURE_DEAD_BAND),
            "constant_exposure_daily_equity_pdf": constant_dict["daily_equity_pdf"],
            "random_timing_return_list": list(random_return_list),
            "random_timing_seed_list": list(seed_list),
            "random_timing_switch_count": get_weight_switch_count_int(target_arr),
            "random_timing_unique_weight_list": get_unique_weight_list(target_arr),
            "exposure_source_str": "realized_position" if realized_exposure_bool_in else "decision_target",
            **family_dict}


# THE PROCESS-LOCAL SPAN OF A TAIL-DRAW WORKER (SET BY THE POOL INITIALIZER)
_TAIL_WORKER_STATE_DICT = {}


# FUNCTION: SET A TAIL-DRAW WORKER'S BARS AND EXPOSURE PATH
def init_tail_draw_worker(ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span
        exposure_arr_in (np.ndarray): The path's exposure (as get_exposure_weight_arr returns it)

    Returns:
        None
    """
    # ONE COPY PER PROCESS
    _TAIL_WORKER_STATE_DICT.update({"ohlcv": ohlcv_array_dict_in, "date1": date1_in, "date2": date2_in,
                                    "exposure": exposure_arr_in})


# FUNCTION: THE TOTAL RETURN OF ONE RANDOM-TIMING DRAW (THE LOOP BODY OF get_runner_baseline_dict)
def get_random_timing_draw_return_float(seed_in, ohlcv_array_dict_in=None, date1_in=None, date2_in=None,
                                        exposure_arr_in=None, initial_capital_in=config.INITIAL_CAPITAL,
                                        entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                                        market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
    """
    Args:
        seed_in (int): Seed
        ohlcv_array_dict_in, date1_in, date2_in, exposure_arr_in: The span (None = the worker's)
        initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Engine costs

    Returns:
        float: Total return of the draw
    """
    # THE SAME DRAW AND THE SAME ENGINE AS THE REGISTERED DRAWS
    ohlcv = ohlcv_array_dict_in if ohlcv_array_dict_in is not None else _TAIL_WORKER_STATE_DICT["ohlcv"]
    date1 = date1_in if date1_in is not None else _TAIL_WORKER_STATE_DICT["date1"]
    date2 = date2_in if date2_in is not None else _TAIL_WORKER_STATE_DICT["date2"]
    exposure_arr = exposure_arr_in if exposure_arr_in is not None else _TAIL_WORKER_STATE_DICT["exposure"]
    random_arr = get_random_timing_weight_arr(exposure_arr, int(seed_in))
    initial_weight = float(random_arr[0]) if len(random_arr) and np.isfinite(random_arr[0]) else 0.0
    random_dict = run_weight_path_dict(ohlcv, date1, date2, random_arr, initial_weight, 0.0, initial_capital_in,
                                       entry_slippage_in, market_exit_slippage_in)
    return float(random_dict["metric_dict"]["total_return"])


# FUNCTION: THE MULTIPLE-TESTING RANDOM-TIMING COUNT, WITH EXTRA DRAWS UP TO THE BUDGET FOR N DESIGNS
def get_random_timing_tail_dict(ohlcv_array_dict_in, date1_in, date2_in, baseline_dict_in, prior_only_dict_in,
                                design_count_int_in, realized_exposure_bool_in=False, extend_bool_in=True,
                                process_count_int_in=None, batch_int_in=None, max_draw_int_in=None, alpha_in=None,
                                pilot_design_count_int_in=None):
    """
    k = draws at or above the path; the budget M + 1 = ceil(factor * N / alpha); after the registered draws, batches of
    further seeds run while fewer than M draws are done and k is still at most k_max(M). Stopping early cannot change
    the outcome: k only grows, so p at the budget already exceeds alpha / N. Extension is skipped (the strict count of
    the registered draws is used) when extend_bool_in is False (a test configuration with a reduced seed count), when the
    registered seeds are not the default sequence, or when the budget exceeds max_draw_int_in (budget_exceeded_bool):
    all three can only make the test harder to pass.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span of the baselines
        baseline_dict_in (dict): Output of get_runner_baseline_dict (registered draws and seeds)
        prior_only_dict_in (dict): The path (metric_dict total_return, and its exposure)
        design_count_int_in (int): N (so.core.multiple_testing.get_tried_design_count_dict)
        realized_exposure_bool_in (bool): Exposure from the realized position (as the baselines)
        extend_bool_in (bool): Draw beyond the registered draws
        process_count_int_in, batch_int_in, max_draw_int_in (int | None): None = the config values
        alpha_in (float | None): Family-wise alpha (None = RUNNER_MULTIPLE_TESTING_ALPHA)
        pilot_design_count_int_in (int | None): N with the pilot designs included (roadmap R4, reported only). When it
            is larger than N, the budget is sized for it (when that budget is within max_draw_int_in), so the same
            draws decide both: the verdict at N and the pilot-included view. The verdict stays an exact test at N
            (p = (k + 1) / (M + 1) with M fixed before any draw, only finer); the stop rule follows the verdict's
            allowed count (the larger one), and the pilot-included pass needs k at most its own allowed count at the
            same budget. A pilot budget above max_draw_int_in leaves the budget at N and the pilot view fails.

    Returns:
        dict: method_str, design_count, alpha, p_max, path_return_used, draw_target, draw_count,
              registered_draw_count, at_or_above_count, at_or_above_max, p (at the budget: (k + 1) / (target + 1)),
              stopped_early_bool, budget_exceeded_bool, extension_bool, process_count, extra_seconds, pass_bool,
              pilot_design_count, pilot_at_or_above_max, pilot_budget_bool, pilot_pass_bool
    """
    # THE REGISTERED DRAWS FIRST (THE PATH RETURN HAS THE ENGINE'S ROUNDING, LIKE EVERY DRAW)
    alpha_float = float(config.RUNNER_MULTIPLE_TESTING_ALPHA if alpha_in is None else alpha_in)
    design_count = max(1, int(design_count_int_in))
    path_float = float((prior_only_dict_in.get("metric_dict") or {}).get("total_return", float("nan")))
    registered_list = [float(value) for value in list(baseline_dict_in.get("random_timing_return_list") or [])]
    registered_seed_list = [int(value) for value in list(baseline_dict_in.get("random_timing_seed_list") or [])]
    pilot_count = max(design_count, int(pilot_design_count_int_in or design_count))
    tail_dict = get_random_timing_count_dict(path_float, registered_list, design_count, alpha_float)
    tail_dict.update({"process_count": 0, "extra_seconds": 0.0, "pilot_design_count": pilot_count,
                      "pilot_at_or_above_max": get_random_timing_at_or_above_max_int(len(registered_list), pilot_count,
                                                                                    alpha_float),
                      "pilot_budget_bool": False})
    tail_dict["pilot_pass_bool"] = bool(tail_dict["pass_bool"] and int(tail_dict["at_or_above_count"])
                                        <= int(tail_dict["pilot_at_or_above_max"]))
    budget_int = get_random_timing_draw_target_int(design_count, alpha_float)
    max_draw_int = int(config.RUNNER_RANDOM_TIMING_TAIL_MAX_DRAWS if max_draw_int_in is None else max_draw_int_in)
    pilot_budget_int = get_random_timing_draw_target_int(pilot_count, alpha_float)
    pilot_budget_bool = pilot_budget_int <= max_draw_int
    if pilot_budget_bool:
        budget_int = max(budget_int, pilot_budget_int)
    default_seed_bool = registered_seed_list == get_random_timing_seed_list(len(registered_seed_list))
    if not (extend_bool_in and default_seed_bool and math.isfinite(path_float) and len(registered_list) > 0):
        return tail_dict
    if budget_int > max_draw_int:
        tail_dict["budget_exceeded_bool"] = True
        return tail_dict
    # THE TARGET: THE BUDGET, OR THE REGISTERED DRAWS WHEN THEY ALREADY COVER IT
    target_int = max(budget_int, len(registered_list))
    at_or_above_max = get_random_timing_at_or_above_max_int(target_int, design_count, alpha_float)
    at_or_above_int = int(tail_dict["at_or_above_count"])
    draw_count = len(registered_list)
    exposure_arr = get_exposure_weight_arr(prior_only_dict_in, realized_exposure_bool_in)
    batch_int = max(1, int(config.RUNNER_RANDOM_TIMING_TAIL_BATCH if batch_int_in is None else batch_int_in))
    process_count = max(1, int(config.RUNNER_RANDOM_TIMING_TAIL_PROCESS_COUNT if process_count_int_in is None
                               else process_count_int_in))
    process_count = min(process_count, max(1, (os.cpu_count() or 2) - 1))
    start_float = time.time()
    pool = None
    try:
        while draw_count < target_int and at_or_above_int <= at_or_above_max:
            seed_list = [int(config.RANDOM_SEED) + idx for idx in range(draw_count, min(draw_count + batch_int, target_int))]
            if process_count > 1 and pool is None:
                pool = multiprocessing.get_context("spawn").Pool(
                    processes=process_count, initializer=init_tail_draw_worker,
                    initargs=(ohlcv_array_dict_in, date1_in, date2_in, exposure_arr))
            if pool is not None:
                return_list = pool.map(get_random_timing_draw_return_float, seed_list,
                                       chunksize=max(1, len(seed_list) // (4 * process_count)))
            else:
                return_list = [get_random_timing_draw_return_float(seed_int, ohlcv_array_dict_in, date1_in, date2_in,
                                                                   exposure_arr) for seed_int in seed_list]
            value_arr = np.asarray(return_list, dtype=float)
            at_or_above_int += int(np.sum(~(value_arr < path_float)))
            draw_count += len(seed_list)
    finally:
        if pool is not None:
            pool.close()
            pool.join()
    stopped_early_bool = draw_count < target_int
    tail_dict.update({"draw_target": target_int, "draw_count": draw_count, "at_or_above_count": at_or_above_int,
                      "at_or_above_max": at_or_above_max, "p": float((at_or_above_int + 1) / (target_int + 1)),
                      "stopped_early_bool": bool(stopped_early_bool), "extension_bool": draw_count > len(registered_list),
                      "process_count": process_count if pool is not None else (1 if draw_count > len(registered_list) else 0),
                      "extra_seconds": float(time.time() - start_float),
                      "pass_bool": bool(not stopped_early_bool and at_or_above_int <= at_or_above_max)})
    pilot_at_or_above_max = get_random_timing_at_or_above_max_int(target_int, pilot_count, alpha_float)
    tail_dict.update({"pilot_at_or_above_max": pilot_at_or_above_max, "pilot_budget_bool": bool(pilot_budget_bool),
                      "pilot_pass_bool": bool(pilot_budget_bool and not stopped_early_bool
                                              and at_or_above_int <= pilot_at_or_above_max)})
    return tail_dict
