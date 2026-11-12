import re
import numpy as np
# IMPORT THE SHARED CONFIGURATION (TOLERANCE)
from so import config
# IMPORT THE FIRST-ENTRY BAR (NOTHING TRADES BEFORE 10:00)
from so.core.backtest_simulation import get_session_first_entry_idx

"""
Intraday Decision Times In Daily Mode (step R4c, decided by Nicolas on 2026-11-11)

A daily-mode design may declare INTRADAY_DECISION_TIME_LIST (module and Design class, equal), for example ["15:30"].
At each time the runner calls the same decide(view) with a view that ends at that bar; the fill is the next bar's
open, the rule of the 15:58 decision and its 15:59 fill. The 15:58 decision is unchanged. Design note:
claude/ENGINE_DESIGN_2026-11-11_intraday.md (project) and docs/RUNNER_DESIGN.md, "Intraday decision times".

    times      "HH:MM" bar starts in New York time, sorted, unique, from INTRADAY_TIME_MIN_STR (10:00, the first-entry
               rule) through INTRADAY_TIME_MAX_STR (15:57), at most INTRADAY_TIME_MAX_COUNT (32)
    mapping    a time maps to the last bar of the session that starts at or before it, strictly before the session's
               decision bar, whose fill bar (the next bar) is at or after the session's first-entry bar. In a live
               stream a call also needs a bar after the previous call's bar. No such bar: no call at that time that
               session (a missing bar, an early close)
    output     only a target weight (or NaN / None = keep). Any other decision field is refused
    engine     fractional only (trailing-stop and barrier designs with intraday times are refused)
    record     each session's recorded decision gains INTRADAY_LIST_KEY_STR: a tuple of (time, target weight) for
               every call that happened (NaN = keep). Only the loop writes it; a design that returns it is refused.
               Designs without intraday times record no such key: their files are byte-identical to before
    replay     every replay applies the recorded intraday fills at the same bars before the 15:59 fill. Strict
               (development, holdout, cost sensitivity): an entry that does not map stops the run. Lenient (random-
               timing draws only): an entry moved to a session where it does not map is skipped and counted

The last session of a window has no design call, intraday included (unchanged rule).
"""

# THE RECORD KEY THE LOOP WRITES ON EACH SESSION'S DECISION
INTRADAY_LIST_KEY_STR = "intraday_list"
# THE ATTRIBUTE A DESIGN DECLARES (MODULE AND CLASS)
INTRADAY_TIME_ATTR_STR = "INTRADAY_DECISION_TIME_LIST"
# THE EARLIEST TIME (FILL AT 10:01 OR LATER; NOTHING TRADES BEFORE 10:00) AND THE LATEST (BEFORE THE 15:58 DECISION)
INTRADAY_TIME_MIN_STR = "10:00"
INTRADAY_TIME_MAX_STR = "15:57"
# AT MOST THIS MANY TIMES (EVERY CALL BUILDS A VIEW; RUN TIME GROWS WITH THE COUNT)
INTRADAY_TIME_MAX_COUNT = 32
# THE TIME FORMAT
INTRADAY_TIME_PATTERN = re.compile(r"^([01][0-9]|2[0-3]):([0-5][0-9])$")
# DECISION FIELDS AND THEIR NEUTRAL VALUES (AN INTRADAY CALL MAY SET ONLY target_weight)
INTRADAY_NEUTRAL_FIELD_DICT = {"stop_price": None, "take_profit_price": None, "trail_multiple": None,
                               "flatten_bool": False, "volatility": None, "delta": None, "exit_block_sessions": 0,
                               "require_fresh_exit": False, "reentry_reason": "model"}


# FUNCTION: MINUTES AFTER MIDNIGHT OF "HH:MM"
def get_time_minute_int(time_str_in):
    """
    Args:
        time_str_in (str): "HH:MM"

    Returns:
        int: Minutes after midnight
    """
    # THE FORMAT IS CHECKED HERE
    match = INTRADAY_TIME_PATTERN.match(str(time_str_in))
    if match is None:
        raise ValueError(f"intraday decision time {time_str_in!r} is not HH:MM.")
    return int(match.group(1)) * 60 + int(match.group(2))


# FUNCTION: A VALIDATED TUPLE OF TIMES
def get_validated_time_tuple(raw_in):
    """
    None or an empty list is no intraday time. Otherwise sorted, unique, within the allowed range, at most
    INTRADAY_TIME_MAX_COUNT.

    Args:
        raw_in (list | tuple | None): Declared times

    Returns:
        tuple[str, ...]: Times
    """
    # NOTHING DECLARED
    if raw_in is None:
        return tuple()
    if isinstance(raw_in, str) or not isinstance(raw_in, (list, tuple)):
        raise ValueError(f"{INTRADAY_TIME_ATTR_STR} must be a list of \"HH:MM\" strings.")
    time_tuple = tuple(str(time_str) for time_str in raw_in)
    if len(time_tuple) == 0:
        return tuple()
    if len(time_tuple) > INTRADAY_TIME_MAX_COUNT:
        raise ValueError(f"{INTRADAY_TIME_ATTR_STR} has {len(time_tuple)} times; at most {INTRADAY_TIME_MAX_COUNT}.")
    minute_list = [get_time_minute_int(time_str) for time_str in time_tuple]
    if minute_list != sorted(minute_list) or len(set(minute_list)) != len(minute_list):
        raise ValueError(f"{INTRADAY_TIME_ATTR_STR} must be sorted and unique.")
    min_int, max_int = get_time_minute_int(INTRADAY_TIME_MIN_STR), get_time_minute_int(INTRADAY_TIME_MAX_STR)
    for time_str, minute_int in zip(time_tuple, minute_list):
        if not min_int <= minute_int <= max_int:
            raise ValueError(f"intraday decision time {time_str} is outside {INTRADAY_TIME_MIN_STR}..{INTRADAY_TIME_MAX_STR}.")
    return time_tuple


# FUNCTION: THE TIMES A DESIGN (MODULE, OBJECT OR CALLABLE) DECLARES
def get_intraday_time_tuple(design_in):
    """
    Args:
        design_in (module | object | callable | None): Design

    Returns:
        tuple[str, ...]: Validated times (empty when none)
    """
    # A MISSING ATTRIBUTE IS NO INTRADAY TIME
    if design_in is None:
        return tuple()
    return get_validated_time_tuple(getattr(design_in, INTRADAY_TIME_ATTR_STR, None))


# FUNCTION: THE TIMES OF A STREAM, CHECKED BETWEEN THE MODULE AND THE DESIGN OBJECT
def get_stream_intraday_time_tuple(design_in, design_module_in=None):
    """
    The module wins when given; a design object that declares other times is refused.

    Args:
        design_in (object | callable): Candidate design
        design_module_in (module | None): Design module

    Returns:
        tuple[str, ...]: Times
    """
    # BOTH SIDES DECLARE THE SAME LIST, OR THE OBJECT DECLARES NOTHING
    object_tuple = get_intraday_time_tuple(design_in)
    if design_module_in is None:
        return object_tuple
    module_tuple = get_intraday_time_tuple(design_module_in)
    if hasattr(design_in, INTRADAY_TIME_ATTR_STR) and object_tuple != module_tuple:
        raise ValueError(f"{INTRADAY_TIME_ATTR_STR} differs between the design module and its Design class.")
    return module_tuple


# FUNCTION: REFUSE INTRADAY TIMES WITH AN ENGINE OTHER THAN THE FRACTIONAL ONE
def check_intraday_engine(time_tuple_in, engine_in):
    """
    Args:
        time_tuple_in (tuple): Times
        engine_in (Engine): Position engine

    Returns:
        None
    """
    # IMPORT HERE: so.runner.engine IMPORTS NOTHING FROM THIS MODULE, BUT KEEP THE ORDER SIMPLE
    from so.runner.engine import FractionalWeightEngine
    if len(time_tuple_in) == 0:
        return
    if not isinstance(engine_in, FractionalWeightEngine):
        raise ValueError(f"{INTRADAY_TIME_ATTR_STR} needs the fractional engine; got {type(engine_in).__name__}.")


# FUNCTION: BAR MINUTES OF ONE SESSION (NEW YORK)
def get_session_bar_minute_arr(ohlcv_array_dict_in, session_idx_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bars
        session_idx_in (int): Session

    Returns:
        tuple[int, np.ndarray]: First bar index, minutes after midnight of every bar of the session
    """
    # THE TIMESTAMP INDEX IS NEW YORK TIME (tz-aware)
    start_idx = int(ohlcv_array_dict_in["session_start_idx_arr"][int(session_idx_in)])
    end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][int(session_idx_in)])
    ts_index = ohlcv_array_dict_in["timestamp_index"][start_idx:end_idx + 1]
    if getattr(ts_index, "tz", None) is not None:
        ts_index = ts_index.tz_convert("America/New_York")
    minute_arr = np.asarray(ts_index.hour, dtype=np.int64) * 60 + np.asarray(ts_index.minute, dtype=np.int64)
    return start_idx, minute_arr


# FUNCTION: THE BAR OF ONE TIME IN ONE SESSION, OR -1
def get_time_bar_idx(ohlcv_array_dict_in, session_idx_in, time_str_in, decision_idx_in, first_entry_idx_in,
                     minute_tuple_in=None):
    """
    The last bar starting at or before the time, strictly before the decision bar, whose next bar (the fill) is at or
    after the first-entry bar.

    Args:
        ohlcv_array_dict_in (dict): Bars
        session_idx_in (int): Session
        time_str_in (str): "HH:MM"
        decision_idx_in (int): The session's 15:58 decision bar
        first_entry_idx_in (int): The session's first-entry bar (-1 = none)
        minute_tuple_in (tuple | None): Output of get_session_bar_minute_arr (computed when None)

    Returns:
        int: Bar index, or -1 when the time does not map
    """
    # NO FIRST-ENTRY BAR: NOTHING TRADES THAT SESSION
    if int(first_entry_idx_in) < 0:
        return -1
    start_idx, minute_arr = minute_tuple_in if minute_tuple_in is not None else get_session_bar_minute_arr(ohlcv_array_dict_in, session_idx_in)
    pos_int = int(np.searchsorted(minute_arr, get_time_minute_int(time_str_in), side="right")) - 1
    if pos_int < 0:
        return -1
    bar_idx = start_idx + pos_int
    # AT OR AFTER THE DECISION BAR (AN EARLY CLOSE): NO CALL, NOT AN EARLIER BAR
    if bar_idx >= int(decision_idx_in):
        return -1
    if bar_idx + 1 < int(first_entry_idx_in):
        return -1
    return int(bar_idx)


# FUNCTION: THE LIVE CALLS OF ONE SESSION
def get_session_call_list(ohlcv_array_dict_in, session_idx_in, time_tuple_in, decision_idx_in, first_entry_idx_in):
    """
    Each time maps as in get_time_bar_idx, and a call also needs a bar after the previous call's bar.

    Args:
        ohlcv_array_dict_in (dict): Bars
        session_idx_in (int): Session
        time_tuple_in (tuple): Times
        decision_idx_in, first_entry_idx_in (int): The session's decision bar and first-entry bar

    Returns:
        list[tuple[str, int]]: (time, bar index) in time order
    """
    # NOTHING DECLARED
    if len(time_tuple_in) == 0:
        return []
    minute_tuple = get_session_bar_minute_arr(ohlcv_array_dict_in, session_idx_in)
    call_list = []
    previous_bar_idx = -1
    for time_str in time_tuple_in:
        bar_idx = get_time_bar_idx(ohlcv_array_dict_in, session_idx_in, time_str, decision_idx_in, first_entry_idx_in,
                                   minute_tuple)
        if bar_idx < 0 or bar_idx <= previous_bar_idx:
            continue
        call_list.append((str(time_str), int(bar_idx)))
        previous_bar_idx = int(bar_idx)
    return call_list


# FUNCTION: THE FIRST-ENTRY BAR OF EVERY SESSION
def get_first_entry_idx_arr(ohlcv_array_dict_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        np.ndarray: First-entry bar per session (-1 = none)
    """
    # ONE LOOKUP PER SESSION (ONLY INTRADAY DESIGNS PAY FOR IT)
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    return np.asarray([get_session_first_entry_idx(ohlcv_array_dict_in, session_idx) for session_idx in range(session_count)],
                      dtype=np.int64)


# FUNCTION: THE TARGET WEIGHT OF AN INTRADAY CALL'S RETURN
def get_intraday_target_weight_float(raw_in, time_str_in):
    """
    A number, None, or a dict whose only non-neutral field is target_weight. Anything else is refused.

    Args:
        raw_in (float | dict | None): The design's return
        time_str_in (str): Call time (for the message)

    Returns:
        float: Target weight (NaN = keep)
    """
    # IMPORT THE SHARED NORMALIZER
    from so.runner.engine import get_decision_dict
    if isinstance(raw_in, dict):
        if INTRADAY_LIST_KEY_STR in raw_in:
            raise ValueError(f"a design may not return {INTRADAY_LIST_KEY_STR!r}; only the runner writes it.")
        decision_dict = get_decision_dict(raw_in)
        for key_str, neutral_value in INTRADAY_NEUTRAL_FIELD_DICT.items():
            if decision_dict.get(key_str) != neutral_value:
                raise ValueError(f"the intraday call at {time_str_in} set {key_str!r}; only target_weight is allowed.")
        return float(decision_dict["target_weight"])
    return float(get_decision_dict(raw_in)["target_weight"])


# FUNCTION: A NORMALIZED INTRADAY RECORD
def get_normalized_intraday_tuple(raw_in):
    """
    Args:
        raw_in (iterable): (time, weight) pairs

    Returns:
        tuple[tuple[str, float], ...]: Same pairs, time as str, weight as float (NaN = keep)
    """
    # EVERY ENTRY HAS TWO PARTS
    entry_list = []
    for entry in list(raw_in or []):
        time_str, weight = entry
        entry_list.append((str(time_str), float(np.nan if weight is None else weight)))
    return tuple(entry_list)


# FUNCTION: WHETHER TWO INTRADAY RECORDS MATCH (OPTIONALLY ONLY UP TO A TIME)
def get_intraday_equal_bool(left_in, right_in, through_time_str_in=None, tolerance_float_in=None):
    """
    Times compare exactly; weights within NUMERIC_TOLERANCE, NaN equal to NaN. A missing record is empty.

    Args:
        left_in, right_in (iterable | None): Records
        through_time_str_in (str | None): Compare only entries at or before this time (None = all)
        tolerance_float_in (float | None): Absolute band (None = NUMERIC_TOLERANCE)

    Returns:
        bool: True when the compared entries match
    """
    # FILTER BOTH SIDES THE SAME WAY
    tolerance_float = float(config.NUMERIC_TOLERANCE if tolerance_float_in is None else tolerance_float_in)
    left_tuple, right_tuple = get_normalized_intraday_tuple(left_in), get_normalized_intraday_tuple(right_in)
    if through_time_str_in is not None:
        through_int = get_time_minute_int(through_time_str_in)
        left_tuple = tuple(entry for entry in left_tuple if get_time_minute_int(entry[0]) <= through_int)
        right_tuple = tuple(entry for entry in right_tuple if get_time_minute_int(entry[0]) <= through_int)
    if len(left_tuple) != len(right_tuple):
        return False
    for (left_time, left_weight), (right_time, right_weight) in zip(left_tuple, right_tuple):
        if left_time != right_time:
            return False
        left_nan, right_nan = not np.isfinite(left_weight), not np.isfinite(right_weight)
        if left_nan and right_nan:
            continue
        if left_nan or right_nan or abs(left_weight - right_weight) > tolerance_float:
            return False
    return True


"""
Baselines For Intraday Paths
"""


# FUNCTION: ONE PATTERN PER SESSION (THE WEIGHT AFTER EACH TIME, THEN AFTER 15:59)
def get_intraday_pattern_list(decision_dict_list_in, time_tuple_in, initial_weight_in):
    """
    Keep (NaN, or no call at that time) carries the weight held before it. The first session starts from the initial
    weight. The last element of each pattern is the weight after the 15:59 fill (the filled daily target).

    Args:
        decision_dict_list_in (list[dict]): The path's decisions, one per window session
        time_tuple_in (tuple): The design's times
        initial_weight_in (float): Weight bought at the window start

    Returns:
        list[tuple[float, ...]]: len(time_tuple_in) + 1 weights per session
    """
    # WALK THE SESSIONS, CARRYING THE WEIGHT
    held_float = float(initial_weight_in)
    pattern_list = []
    for decision_dict in decision_dict_list_in:
        entry_dict = {time_str: weight for time_str, weight in get_normalized_intraday_tuple(
            (decision_dict or {}).get(INTRADAY_LIST_KEY_STR))}
        weight_list = []
        for time_str in time_tuple_in:
            weight = entry_dict.get(str(time_str), np.nan)
            if np.isfinite(weight):
                held_float = float(weight)
            weight_list.append(held_float)
        daily_weight = float((decision_dict or {}).get("target_weight", np.nan))
        if np.isfinite(daily_weight):
            held_float = daily_weight
        weight_list.append(held_float)
        pattern_list.append(tuple(weight_list))
    return pattern_list


# FUNCTION: WHETHER TWO PATTERNS MATCH AT THE NUMERIC TOLERANCE
def get_pattern_equal_bool(left_in, right_in):
    """
    Args:
        left_in, right_in (tuple): Patterns

    Returns:
        bool: True when every weight matches
    """
    # SAME LENGTH, EVERY WEIGHT WITHIN THE BAND
    if len(left_in) != len(right_in):
        return False
    return all(abs(float(left) - float(right)) <= float(config.NUMERIC_TOLERANCE) for left, right in zip(left_in, right_in))


# FUNCTION: THE PATTERN THE PATH SPENDS THE MOST SESSIONS AT
def get_base_pattern(pattern_list_in):
    """
    First-seen pattern among those with the maximum session count (the rule of get_base_weight_float).

    Args:
        pattern_list_in (list[tuple]): Patterns

    Returns:
        tuple: Base pattern
    """
    # COUNT WITH THE TOLERANCE
    unique_list, count_list = [], []
    for pattern in pattern_list_in:
        for unique_idx, unique_pattern in enumerate(unique_list):
            if get_pattern_equal_bool(pattern, unique_pattern):
                count_list[unique_idx] += 1
                break
        else:
            unique_list.append(tuple(pattern))
            count_list.append(1)
    max_count = max(count_list)
    return unique_list[count_list.index(max_count)]


# FUNCTION: A RANDOM PLACEMENT OF THE PATH'S NON-BASE SPELLS OF SESSIONS
def get_random_pattern_list(pattern_list_in, seed_in):
    """
    The draw of so.runner.baselines.get_random_timing_weight_arr with a session's pattern in place of its weight:
    spells are maximal runs of non-base sessions (internal sequence kept), shuffled and placed by splitting the
    base sessions into k+1 gaps (middle >= 1, edges >= 0). Time at each pattern is the path's.

    Args:
        pattern_list_in (list[tuple]): Path patterns
        seed_in (int): Seed

    Returns:
        list[tuple]: One pattern per session
    """
    # IMPORT THE SHARED GAP DRAW
    from so.runner.baselines import get_random_timing_gap_list
    if len(pattern_list_in) == 0:
        return []
    base_pattern = get_base_pattern(pattern_list_in)
    spell_list, current_list, base_count = [], None, 0
    for pattern in pattern_list_in:
        if get_pattern_equal_bool(pattern, base_pattern):
            base_count += 1
            if current_list is not None:
                spell_list.append(current_list)
                current_list = None
        elif current_list is None:
            current_list = [tuple(pattern)]
        else:
            current_list.append(tuple(pattern))
    if current_list is not None:
        spell_list.append(current_list)
    if len(spell_list) == 0:
        return [tuple(pattern) for pattern in pattern_list_in]
    rng = np.random.default_rng(int(seed_in))
    order_arr = rng.permutation(len(spell_list))
    placed_list = [spell_list[int(idx)] for idx in order_arr]
    gap_list = get_random_timing_gap_list(base_count, len(placed_list), rng)
    out_list = []
    for spell_idx, spell in enumerate(placed_list):
        out_list.extend([base_pattern] * int(gap_list[spell_idx]))
        out_list.extend(spell)
    out_list.extend([base_pattern] * int(gap_list[-1]))
    return out_list


# FUNCTION: DECISIONS THAT REPRODUCE A PATTERN LIST
def get_pattern_decision_list(pattern_list_in, time_tuple_in, initial_weight_in):
    """
    An intraday entry only where the weight changes from the weight held before it (no rebalance where nothing
    changed); the daily target every session.

    Args:
        pattern_list_in (list[tuple]): Patterns
        time_tuple_in (tuple): Times
        initial_weight_in (float): Weight held before the first session

    Returns:
        list[dict]: get_decision_dict outputs with intraday records
    """
    # IMPORT THE SHARED NORMALIZER
    from so.runner.engine import get_decision_dict
    held_float = float(initial_weight_in)
    decision_list = []
    for pattern in pattern_list_in:
        entry_list = []
        for time_str, weight in zip(time_tuple_in, pattern[:-1]):
            if abs(float(weight) - held_float) > float(config.NUMERIC_TOLERANCE):
                entry_list.append((str(time_str), float(weight)))
                held_float = float(weight)
        decision_dict = get_decision_dict(float(pattern[-1]))
        decision_dict[INTRADAY_LIST_KEY_STR] = tuple(entry_list)
        decision_list.append(decision_dict)
        held_float = float(pattern[-1])
    return decision_list


# FUNCTION: (SESSION, TIME) -> BAR FOR EVERY WINDOW SESSION
def get_window_bar_map_dict(ohlcv_array_dict_in, window_session_idx_arr_in, time_tuple_in):
    """
    Built once per baseline span so thousands of draws do not map times again.

    Args:
        ohlcv_array_dict_in (dict): Bars
        window_session_idx_arr_in (array-like): Window sessions
        time_tuple_in (tuple): Times

    Returns:
        dict: session index -> {time: bar index (-1 = does not map)}
    """
    # IMPORT THE DECISION BARS
    from so.features.daily_features import get_session_decision_idx_dict
    decision_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"]
    map_dict = {}
    for session_idx in window_session_idx_arr_in:
        session_idx = int(session_idx)
        first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, session_idx)
        minute_tuple = get_session_bar_minute_arr(ohlcv_array_dict_in, session_idx)
        map_dict[session_idx] = {str(time_str): get_time_bar_idx(ohlcv_array_dict_in, session_idx, time_str,
                                                                 int(decision_idx_arr[session_idx]), first_entry_idx,
                                                                 minute_tuple)
                                 for time_str in time_tuple_in}
    return map_dict


# FUNCTION: THE BAR-WEIGHTED MEAN WEIGHT OF A PATTERN LIST
def get_bar_weighted_mean_weight_float(ohlcv_array_dict_in, window_session_idx_arr_in, pattern_list_in, time_tuple_in,
                                       initial_weight_in, bar_map_dict_in=None):
    """
    The weight held through each minute bar, averaged over every bar of the window except the last session (sold at
    its close; the rule of the fractional engine's mean_weight). A fill at a bar's open counts for that bar. An entry
    that does not map is not a change.

    Args:
        ohlcv_array_dict_in (dict): Bars
        window_session_idx_arr_in (array-like): Window sessions
        pattern_list_in (list[tuple]): Patterns, one per window session
        time_tuple_in (tuple): Times
        initial_weight_in (float): Weight held before the first session
        bar_map_dict_in (dict | None): Output of get_window_bar_map_dict (built when None)

    Returns:
        float: Mean weight
    """
    # IMPORT THE DECISION AND FILL BARS
    from so.features.daily_features import get_session_decision_idx_dict
    session_idx_list = [int(session_idx) for session_idx in window_session_idx_arr_in]
    if len(session_idx_list) == 0:
        return 0.0
    bar_map_dict = bar_map_dict_in if bar_map_dict_in is not None else get_window_bar_map_dict(ohlcv_array_dict_in, session_idx_list, time_tuple_in)
    fill_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict_in)["fill_idx_arr"]
    counted_list = session_idx_list[:-1] if len(session_idx_list) > 1 else session_idx_list
    held_float = float(initial_weight_in)
    weighted_float, bar_total_int = 0.0, 0
    for session_pos, session_idx in enumerate(counted_list):
        start_idx = int(ohlcv_array_dict_in["session_start_idx_arr"][session_idx])
        end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx])
        pattern = pattern_list_in[session_pos]
        change_list = []
        for time_str, weight in zip(time_tuple_in, pattern[:-1]):
            bar_idx = int(bar_map_dict[session_idx][str(time_str)])
            if bar_idx >= 0:
                change_list.append((bar_idx + 1, float(weight)))
        change_list.append((int(fill_idx_arr[session_idx]), float(pattern[-1])))
        cursor_idx = start_idx
        for change_idx, weight in change_list:
            change_idx = max(cursor_idx, min(int(change_idx), end_idx + 1))
            weighted_float += held_float * (change_idx - cursor_idx)
            bar_total_int += change_idx - cursor_idx
            cursor_idx = change_idx
            held_float = float(weight)
        weighted_float += held_float * (end_idx + 1 - cursor_idx)
        bar_total_int += end_idx + 1 - cursor_idx
    return float(weighted_float / bar_total_int) if bar_total_int > 0 else 0.0
