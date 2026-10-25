import inspect
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL, SAMPLING, TOLERANCE)
from so import config
# IMPORT THE POINT-IN-TIME CLOCKS, THE CONTEXT AND THE FEATURE CHECK
from so.core.point_in_time import (get_ny_timestamp, get_minute_bar_available_ts, get_runner_context,
                                   get_declared_source_name_list, get_source_spec_dict, set_direct_read_blocked_bool,
                                   check_feature_available_ts)
# IMPORT THE FIRST-ENTRY BAR AND THE WINDOW SESSION LIST
from so.core.backtest_simulation import get_session_first_entry_idx
from so.core.reentry_simulation import get_window_session_idx_arr
# IMPORT THE REFIT CALENDAR AND THE TRAINING MASK
from so.core.rolling_retrain import get_retrain_session_list, TRAIN_WINDOW_ALLOWED_LIST
# IMPORT THE ENGINE DECISION SHAPE
from so.runner.engine import (BarrierEngine, get_decision_dict, get_barrier_buy_bool, DECISION_KEY_LIST,
                              FLOAT_DECISION_KEY_LIST)
# IMPORT THE SHARED BAR EVENTS
from so.runner.loop import get_bar_range_event_dict, get_fill_event_dict, get_empty_daily_result_dict
# IMPORT THE PREFLIGHT
from so.runner.preflight import check_design_source, check_minute_signal

"""
Minute Mode (infrastructure step 4b-2b)

Decisions at minute level, with the point-in-time rule kept structural rather than checked afterwards.

    Rows     built from ROW_SOURCE_LIST through the registry. Every row's available_ts is checked against the end
             of that minute; one late row stops the run.
    Models   fitted on the rolling-retrain calendar. Training rows pass the label door (label_known_ts strictly
             before the refit moment; unfinished labels dropped). Each model scores only the rows at or after its
             refit moment and before the next refit. The design does not choose which rows a model scores.
    Signal   module-level signal(rows, model) -> one output per row. The runner passes one refit block, shuffled,
             restores order, and calls twice; a mismatch stops the run and names the design.
    Fill     an output at the end of minute t is a BarrierEngine decision filled at the open of minute t+1
             (same session). Position, exits and costs live in the engine.

A candidate stream uses MinuteLoop: the same run_through_date / checkpoint / look-ahead surface as DailyLoop.
"""

# COLUMNS THE SIGNAL IS NEVER HANDED (TIME ORDER WOULD LET IT UNSHUFFLE)
SIGNAL_DROP_COL_SET = {"bar_idx", "bar_ts", "timestamp", "decision_ts", "available_ts", "session", "session_idx",
                       "label_known_ts", "row_ts", "entry_ts", "date"}
# RUNNER METADATA STORED ON A RECORDED DECISION (IGNORED BY get_decision_equal)
DECISION_TS_KEY_STR = "_decision_ts"
SESSION_DATE_KEY_STR = "_session_date"
BAR_IDX_KEY_STR = "_bar_idx"


# FUNCTION: THE JOIN TIMESTAMP OF A SOURCE FRAME
def get_source_join_ts_series(frame_pdf_in):
    """
    Bar-start labels. timestamp wins; otherwise decision_ts.

    Args:
        frame_pdf_in (pd.DataFrame): Source rows

    Returns:
        pd.Series: New York timestamps
    """
    # THE SNAPSHOT BAR IS THE JOIN KEY
    if "timestamp" in frame_pdf_in.columns:
        raw_series = frame_pdf_in["timestamp"]
    elif "decision_ts" in frame_pdf_in.columns:
        raw_series = frame_pdf_in["decision_ts"]
    else:
        raise ValueError("a row source needs timestamp or decision_ts.")
    # STORED STRINGS CARRY -05:00 AND -04:00 (WINTER AND SUMMER): PARSE THEM THROUGH UTC, NOT AS MIXED OBJECTS
    if not pd.api.types.is_datetime64_any_dtype(raw_series):
        first_str = str(raw_series.dropna().iloc[0]) if raw_series.notna().any() else ""
        if len(first_str) > 6 and first_str[-6] in "+-" and first_str[-3] == ":":
            return pd.to_datetime(raw_series, utc=True).dt.tz_convert("America/New_York")
    ts_series = pd.to_datetime(raw_series)
    if getattr(ts_series.dt, "tz", None) is None:
        return ts_series.dt.tz_localize("America/New_York")
    return ts_series.dt.tz_convert("America/New_York")


# FUNCTION: THE DECLARED ROW SOURCES (FEATURES)
def get_row_source_name_list(design_module_in):
    """
    ROW_SOURCE_LIST, or DATA_SOURCE_LIST minus labels, or SPY_1MIN.

    Args:
        design_module_in (module): Design

    Returns:
        list[str]: Feature source names
    """
    # AN EXPLICIT ROW LIST WINS
    if hasattr(design_module_in, "ROW_SOURCE_LIST"):
        return [str(name_str) for name_str in design_module_in.ROW_SOURCE_LIST]
    declared_list = get_declared_source_name_list(design_module_in)
    feature_list = []
    for name_str in declared_list:
        if get_source_spec_dict(name_str)["role"] == "label":
            continue
        feature_list.append(name_str)
    return feature_list if feature_list else ["SPY_1MIN"]


# FUNCTION: THE DECLARED LABEL SOURCES
def get_label_source_name_list(design_module_in):
    """
    LABEL_SOURCE_LIST, or label names in DATA_SOURCE_LIST.

    Args:
        design_module_in (module): Design

    Returns:
        list[str]: Label source names
    """
    # AN EXPLICIT LABEL LIST WINS
    if hasattr(design_module_in, "LABEL_SOURCE_LIST"):
        return [str(name_str) for name_str in design_module_in.LABEL_SOURCE_LIST]
    declared_list = get_declared_source_name_list(design_module_in)
    label_list = []
    for name_str in declared_list:
        if get_source_spec_dict(name_str)["role"] == "label":
            label_list.append(name_str)
    return label_list


# FUNCTION: THE OPTIONAL SAMPLE STEP IN MINUTES
def get_row_sample_minutes_int(design_module_in):
    """
    ROW_SAMPLE_EVERY_N_MINUTES, or None (every minute).

    Args:
        design_module_in (module): Design

    Returns:
        int | None: Sample step
    """
    # MISSING MEANS KEEP EVERY MINUTE
    value = getattr(design_module_in, "ROW_SAMPLE_EVERY_N_MINUTES", None)
    if value is None:
        return None
    sample_int = int(value)
    if sample_int < 1:
        raise ValueError("ROW_SAMPLE_EVERY_N_MINUTES must be at least 1.")
    return sample_int


# FUNCTION: THE TRAINING WINDOW STRING
def get_train_window_str(design_in, design_module_in):
    """
    TRAIN_WINDOW_STR on the candidate, then the module, then ALL.

    Args:
        design_in (object): Candidate design
        design_module_in (module): Design module

    Returns:
        str: Window name
    """
    # THE CANDIDATE MAY NAME ITS OWN WINDOW
    window_str = getattr(design_in, "TRAIN_WINDOW_STR", None)
    if window_str is None:
        window_str = getattr(design_module_in, "TRAIN_WINDOW_STR", "ALL")
    window_str = str(window_str)
    if window_str not in TRAIN_WINDOW_ALLOWED_LIST:
        raise ValueError(f"TRAIN_WINDOW_STR {window_str!r} is not one of {TRAIN_WINDOW_ALLOWED_LIST}.")
    return window_str


# FUNCTION: THE REFIT FREQUENCY
def get_retrain_frequency_str(design_in, design_module_in):
    """
    RETRAIN_FREQUENCY_STR on the candidate, then the module, then weekly.

    Args:
        design_in (object): Candidate design
        design_module_in (module): Design module

    Returns:
        str: Frequency
    """
    # WEEKLY IS THE SHARED DEFAULT
    frequency_str = getattr(design_in, "RETRAIN_FREQUENCY_STR", None)
    if frequency_str is None:
        frequency_str = getattr(design_module_in, "RETRAIN_FREQUENCY_STR", "weekly")
    return str(frequency_str)


# FUNCTION: THE DESIGN MODULE OF A CANDIDATE OBJECT
def get_design_module(design_in, design_module_in=None):
    """
    An explicit module wins.

    Args:
        design_in (object): Candidate design
        design_module_in (module | None): Module the caller named

    Returns:
        module: Design module
    """
    # THE FILE MODULE IS THE SOURCE OF signal
    if design_module_in is not None:
        return design_module_in
    module = inspect.getmodule(design_in if inspect.isfunction(design_in) or inspect.ismodule(design_in)
                               else design_in.__class__)
    if module is None:
        raise ValueError("minute mode needs the design module (signal lives there).")
    return module


# FUNCTION: SAMPLE MASK ON THE 15-MINUTE (OR N-MINUTE) ENTRY GRID
def get_sample_mask_arr(timestamp_index_in, sample_minutes_int_in):
    """
    True when the entry (the next minute) sits on the grid that starts at 09:30 plus TRADING_START_DELAY_MINUTES.

    Args:
        timestamp_index_in (pd.DatetimeIndex): Bar-start labels
        sample_minutes_int_in (int): Step in minutes

    Returns:
        np.ndarray: Boolean mask
    """
    # ENTRY IS THE NEXT MINUTE AFTER THE DECISION BAR
    entry_index = pd.DatetimeIndex(timestamp_index_in) + pd.Timedelta(minutes=int(config.DECISION_TO_ENTRY_BAR_OFFSET))
    entry_minute_arr = entry_index.hour * 60 + entry_index.minute
    first_entry_minute = 9 * 60 + 30 + int(config.TRADING_START_DELAY_MINUTES)
    return ((entry_minute_arr - first_entry_minute) % int(sample_minutes_int_in)) == 0


# FUNCTION: SPY MINUTE ROWS FOR THE WINDOW, OPTIONALLY SAMPLED
def get_spy_minute_row_pdf(ohlcv_array_dict_in, window_session_idx_arr_in, sample_minutes_int_in=None):
    """
    One row per kept bar. decision_ts is the end of the minute. bar_ts is the start label the engine looks up.

    Args:
        ohlcv_array_dict_in (dict): Bar arrays
        window_session_idx_arr_in (np.ndarray): Window sessions
        sample_minutes_int_in (int | None): Sample step (None = every minute)

    Returns:
        pd.DataFrame: bar_idx, bar_ts, decision_ts, session, session_idx, open, high, low, close
    """
    # NOTHING IN THE WINDOW
    if len(window_session_idx_arr_in) == 0:
        return pd.DataFrame(columns=["bar_idx", "bar_ts", "decision_ts", "session", "session_idx",
                                     "open", "high", "low", "close"])
    timestamp_index = ohlcv_array_dict_in["timestamp_index"]
    session_idx_arr = np.asarray(ohlcv_array_dict_in["bar_session_idx_arr"], dtype=np.int64)
    window_set = set(int(session_idx) for session_idx in window_session_idx_arr_in)
    keep_arr = np.array([int(session_idx) in window_set for session_idx in session_idx_arr], dtype=bool)
    if sample_minutes_int_in is not None:
        keep_arr = keep_arr & get_sample_mask_arr(timestamp_index, sample_minutes_int_in)
    bar_idx_arr = np.flatnonzero(keep_arr).astype(np.int64)
    bar_ts_index = timestamp_index[bar_idx_arr]
    session_idx_kept_arr = session_idx_arr[bar_idx_arr]
    session_date_list = ohlcv_array_dict_in["session_date_list"]
    row_pdf = pd.DataFrame({
        "bar_idx": bar_idx_arr,
        "bar_ts": bar_ts_index,
        "decision_ts": [get_minute_bar_available_ts(ts) for ts in bar_ts_index],
        "session": [session_date_list[int(session_idx)] for session_idx in session_idx_kept_arr],
        "session_idx": session_idx_kept_arr,
        "open": np.asarray(ohlcv_array_dict_in["open_arr"], dtype=float)[bar_idx_arr],
        "high": np.asarray(ohlcv_array_dict_in["high_arr"], dtype=float)[bar_idx_arr],
        "low": np.asarray(ohlcv_array_dict_in["low_arr"], dtype=float)[bar_idx_arr],
        "close": np.asarray(ohlcv_array_dict_in["close_arr"], dtype=float)[bar_idx_arr],
    })
    return row_pdf.reset_index(drop=True)


# FUNCTION: JOIN ONE FEATURE SOURCE ONTO THE MINUTE ROWS
def add_source_feature_pdf(row_pdf_in, source_name_str_in, source_pdf_in, feature_col_list_in):
    """
    Inner-joins on the bar-start timestamp. available_ts of this source is kept as available_ts_<source>.

    Args:
        row_pdf_in (pd.DataFrame): Minute rows
        source_name_str_in (str): Source name
        source_pdf_in (pd.DataFrame): Feature rows already cut at the last moment
        feature_col_list_in (list[str] | None): Declared feature columns (None = all non-clock)

    Returns:
        pd.DataFrame: Joined rows
    """
    # AN EMPTY SOURCE DROPS EVERY ROW
    source_pdf = source_pdf_in.copy()
    source_pdf["_join_ts"] = get_source_join_ts_series(source_pdf)
    clock_set = SIGNAL_DROP_COL_SET | {"_join_ts"}
    if feature_col_list_in is None:
        keep_col_list = [column_str for column_str in source_pdf.columns if column_str not in clock_set]
    else:
        keep_col_list = [column_str for column_str in feature_col_list_in if column_str in source_pdf.columns]
    if "available_ts" not in source_pdf.columns:
        raise ValueError(f"{source_name_str_in} rows have no available_ts.")
    take_col_list = ["_join_ts", "available_ts"] + [column_str for column_str in keep_col_list if column_str != "available_ts"]
    take_pdf = source_pdf[take_col_list].copy()
    take_pdf = take_pdf.rename(columns={"available_ts": f"available_ts_{source_name_str_in}"})
    take_pdf = take_pdf.drop_duplicates("_join_ts", keep="last")
    left_pdf = row_pdf_in.copy()
    left_pdf["_join_ts"] = pd.DatetimeIndex(pd.to_datetime(left_pdf["bar_ts"])).tz_convert("America/New_York")
    right_col_list = [column_str for column_str in take_pdf.columns
                      if column_str == "_join_ts" or column_str.startswith("available_ts_") or column_str not in left_pdf.columns]
    merged_pdf = left_pdf.merge(take_pdf[right_col_list], on="_join_ts", how="inner")
    return merged_pdf.drop(columns=["_join_ts"])


# FUNCTION: BUILD THE MINUTE ROWS AND REFUSE A LATE available_ts
def get_minute_row_pdf(design_module_in, ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None):
    """
    Joins ROW_SOURCE_LIST through the registry onto the sampled SPY bars. One row with available_ts after the end
    of its minute stops the run.

    Args:
        design_module_in (module): Design (ROW_SOURCE_LIST, FEATURE_COL_LIST, optional sample)
        ohlcv_array_dict_in (dict): Bar arrays
        date1_in, date2_in: Window bounds
        data_context_in (DataContext | None): Loaded sources

    Returns:
        pd.DataFrame: Minute rows with clocks and features
    """
    # THE WINDOW AND THE SAMPLE
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    row_pdf = get_spy_minute_row_pdf(ohlcv_array_dict_in, window_session_idx_arr, get_row_sample_minutes_int(design_module_in))
    if row_pdf.empty:
        return row_pdf
    data_context = data_context_in
    if data_context is None:
        data_context = get_runner_context(ohlcv_array_dict_in,
                                          declared_name_list_in=get_declared_source_name_list(design_module_in))
    last_decision_ts = get_ny_timestamp(row_pdf["decision_ts"].iloc[-1])
    feature_col_list = list(getattr(design_module_in, "FEATURE_COL_LIST", []) or [])
    feature_col_list = [str(column_str) for column_str in feature_col_list]
    source_name_list = get_row_source_name_list(design_module_in)
    available_col_list = []
    for source_name_str in source_name_list:
        if source_name_str == "SPY_1MIN":
            data_context.get("SPY_1MIN", last_decision_ts)
            row_pdf["available_ts_SPY_1MIN"] = [get_ny_timestamp(ts) for ts in row_pdf["decision_ts"]]
            available_col_list.append("available_ts_SPY_1MIN")
            continue
        source_pdf = data_context.get(source_name_str, last_decision_ts)
        row_pdf = add_source_feature_pdf(row_pdf, source_name_str, source_pdf,
                                         feature_col_list if feature_col_list else None)
        available_col_list.append(f"available_ts_{source_name_str}")
    if row_pdf.empty:
        raise ValueError("minute mode has no rows after joining ROW_SOURCE_LIST.")
    if feature_col_list:
        missing_list = [column_str for column_str in feature_col_list if column_str not in row_pdf.columns]
        if missing_list:
            raise ValueError(f"FEATURE_COL_LIST columns missing from the joined rows: {missing_list}.")
    available_ts_list = []
    for _, row in row_pdf.iterrows():
        clock_list = [get_ny_timestamp(row[column_str]) for column_str in available_col_list
                      if column_str in row.index and pd.notna(row[column_str])]
        if not clock_list:
            raise ValueError("a minute row has no available_ts.")
        available_ts_list.append(max(clock_list))
    row_pdf["available_ts"] = available_ts_list
    try:
        check_feature_available_ts(row_pdf, row_pdf["decision_ts"])
    except ValueError as error:
        raise ValueError("a minute row has available_ts after its decision moment (end of that minute).") from error
    return row_pdf.reset_index(drop=True)


# FUNCTION: WHETHER TWO DECISION DICTS MATCH
def get_minute_decision_equal_bool(left_dict_in, right_dict_in, tolerance_float_in=None):
    """
    target_weight and the other float keys compare within NUMERIC_TOLERANCE, with NaN equal to NaN.

    Args:
        left_dict_in, right_dict_in (dict): get_decision_dict outputs
        tolerance_float_in (float | None): Absolute band

    Returns:
        bool: True when every compared key matches
    """
    # RUNNER METADATA KEYS ARE NOT PART OF THE DECISION
    tolerance_float = float(config.NUMERIC_TOLERANCE if tolerance_float_in is None else tolerance_float_in)
    left_dict, right_dict = get_decision_dict(left_dict_in), get_decision_dict(right_dict_in)
    for key_str in DECISION_KEY_LIST:
        left_value, right_value = left_dict.get(key_str), right_dict.get(key_str)
        if key_str in FLOAT_DECISION_KEY_LIST:
            left_nan_bool = left_value is None or (isinstance(left_value, (float, np.floating)) and np.isnan(left_value))
            right_nan_bool = right_value is None or (isinstance(right_value, (float, np.floating)) and np.isnan(right_value))
            if left_nan_bool and right_nan_bool:
                continue
            if left_nan_bool or right_nan_bool:
                return False
            if abs(float(left_value) - float(right_value)) > tolerance_float:
                return False
            continue
        if left_value != right_value:
            return False
    return True


# FUNCTION: NORMALIZE ONE SIGNAL OUTPUT TO A DECISION DICT
def get_signal_row_decision_dict(output_in):
    """
    A dict may use enter / buy_flag / target_weight. A no-enter output has delta None so a leftover distance
    cannot buy. A float is target_weight.

    Args:
        output_in (dict | float | pd.Series | None): One row of signal output

    Returns:
        dict: get_decision_dict output
    """
    # EMPTY IS KEEP / NO BUY
    if output_in is None:
        return get_decision_dict({"target_weight": 0.0})
    if isinstance(output_in, pd.Series):
        output_in = output_in.to_dict()
    if isinstance(output_in, (int, float, np.integer, np.floating, bool, np.bool_)):
        weight_float = float(output_in)
        if weight_float > 0:
            return get_decision_dict({"target_weight": 1.0})
        return get_decision_dict({"target_weight": 0.0})
    output_dict = dict(output_in)
    enter_bool = None
    if "enter" in output_dict:
        enter_bool = bool(output_dict["enter"])
    elif "buy_flag" in output_dict:
        enter_bool = bool(output_dict["buy_flag"])
    elif "target_weight" in output_dict:
        target_weight = output_dict.get("target_weight")
        enter_bool = target_weight is not None and np.isfinite(float(target_weight)) and float(target_weight) > 0.0
    if enter_bool is False:
        return get_decision_dict({"target_weight": 0.0, "delta": None, "stop_price": None, "take_profit_price": None})
    if enter_bool is True and "target_weight" not in output_dict:
        output_dict = dict(output_dict)
        output_dict["target_weight"] = 1.0
    return get_decision_dict(output_dict)


# FUNCTION: TURN A SIGNAL RETURN INTO ONE DECISION PER ROW
def get_signal_decision_list(output_in, row_count_int_in):
    """
    A DataFrame, a list, or a 1-d array. Length must match the rows that were passed.

    Args:
        output_in: Signal return
        row_count_int_in (int): Expected length

    Returns:
        list[dict]: One get_decision_dict per row
    """
    # A FRAME IS ROW-ALIGNED
    row_count_int = int(row_count_int_in)
    if isinstance(output_in, pd.DataFrame):
        if len(output_in) != row_count_int:
            raise ValueError(f"signal returned {len(output_in)} rows, expected {row_count_int}.")
        return [get_signal_row_decision_dict(row) for row in output_in.to_dict(orient="records")]
    if isinstance(output_in, pd.Series):
        if len(output_in) != row_count_int:
            raise ValueError(f"signal returned {len(output_in)} values, expected {row_count_int}.")
        return [get_signal_row_decision_dict(value) for value in output_in.to_numpy()]
    if isinstance(output_in, np.ndarray):
        if output_in.shape[0] != row_count_int:
            raise ValueError(f"signal returned {output_in.shape[0]} values, expected {row_count_int}.")
        if output_in.ndim == 1:
            return [get_signal_row_decision_dict(value) for value in output_in]
        raise ValueError("signal array must be one value per row.")
    output_list = list(output_in)
    if len(output_list) != row_count_int:
        raise ValueError(f"signal returned {len(output_list)} values, expected {row_count_int}.")
    return [get_signal_row_decision_dict(value) for value in output_list]


# FUNCTION: COLUMNS THE SIGNAL MAY SEE
def get_signal_frame_pdf(row_pdf_in, feature_col_list_in):
    """
    FEATURE_COL_LIST when declared; otherwise every column except clocks and indexes. The index is reset so a
    signal cannot unshuffle through the original index.

    Args:
        row_pdf_in (pd.DataFrame): Block rows in shuffled order
        feature_col_list_in (list[str]): Declared feature columns

    Returns:
        pd.DataFrame: Frame passed to signal
    """
    # TIME COLUMNS WOULD LET A SIGNAL SORT AND THEN LOOK AT NEIGHBOURS
    if feature_col_list_in:
        missing_list = [column_str for column_str in feature_col_list_in if column_str not in row_pdf_in.columns]
        if missing_list:
            raise ValueError(f"signal rows are missing FEATURE_COL_LIST columns: {missing_list}.")
        return row_pdf_in[list(feature_col_list_in)].reset_index(drop=True)
    keep_col_list = [column_str for column_str in row_pdf_in.columns if column_str not in SIGNAL_DROP_COL_SET
                     and not str(column_str).startswith("available_ts_")]
    return row_pdf_in[keep_col_list].reset_index(drop=True)


# FUNCTION: CALL SIGNAL ON A SHUFFLED BLOCK AND RESTORE ORDER
def get_shuffled_signal_list(row_pdf_in, model_in, signal_func_in, design_name_str_in, feature_col_list_in=None,
                             seed_int_in=None):
    """
    Two different shuffles must restore to the same per-row outputs. A neighbouring-row read (shift, rolling,
    cumsum) or a counter across calls fails and names the design.

    Args:
        row_pdf_in (pd.DataFrame): Block rows in time order
        model_in: Fitted model (may be None)
        signal_func_in (callable): Module-level signal(rows, model)
        design_name_str_in (str): Name used in the error
        feature_col_list_in (list[str] | None): Declared feature columns
        seed_int_in (int | None): Shuffle seed (None = RANDOM_SEED)

    Returns:
        list[dict]: Decisions in the original row order
    """
    # AN EMPTY BLOCK HAS NOTHING TO CHECK
    row_count_int = len(row_pdf_in)
    if row_count_int == 0:
        return []
    feature_col_list = list(feature_col_list_in or [])
    seed_int = int(config.RANDOM_SEED if seed_int_in is None else seed_int_in)
    rng_one = np.random.default_rng(seed_int)
    rng_two = np.random.default_rng(seed_int + 1)
    perm_one_arr = rng_one.permutation(row_count_int)
    perm_two_arr = rng_two.permutation(row_count_int)
    if row_count_int >= 2 and np.array_equal(perm_one_arr, perm_two_arr):
        perm_two_arr = perm_one_arr[::-1]
    restored_list = []
    for perm_arr in (perm_one_arr, perm_two_arr):
        shuffled_pdf = get_signal_frame_pdf(row_pdf_in.iloc[list(perm_arr)], feature_col_list)
        output_list = get_signal_decision_list(signal_func_in(shuffled_pdf, model_in), row_count_int)
        restored_row_list = [None] * row_count_int
        for shuffled_idx, original_idx in enumerate(perm_arr):
            restored_row_list[int(original_idx)] = output_list[int(shuffled_idx)]
        restored_list.append(restored_row_list)
    for left_dict, right_dict in zip(restored_list[0], restored_list[1]):
        if not get_minute_decision_equal_bool(left_dict, right_dict):
            raise ValueError(f"minute signal is not row-local for design {design_name_str_in}: shuffle check failed")
    return restored_list[0]


# FUNCTION: THE FIT CALLABLE OF A CANDIDATE
def get_minute_fit_func(design_in, design_module_in):
    """
    design.fit if present, else the module-level fit, else None (rule-only).

    Args:
        design_in (object): Candidate design
        design_module_in (module): Design module

    Returns:
        callable | None: fit(train_rows) -> model
    """
    # A CANDIDATE METHOD MAY CLOSE OVER THE THRESHOLD AND THE WINDOW
    if hasattr(design_in, "fit") and callable(getattr(design_in, "fit")):
        return design_in.fit
    if hasattr(design_module_in, "fit") and callable(getattr(design_module_in, "fit")):
        return design_module_in.fit
    return None


# FOLDER OF THE SHARED FIT CACHE OF THE CURRENT RUN (None = NO SHARING ACROSS PROCESSES)
_FIT_CACHE_FOLDER_STR = None
# HOW LONG A PROCESS WAITS FOR ANOTHER PROCESS'S FIT OF THE SAME ROWS BEFORE FITTING ITSELF
FIT_CACHE_WAIT_SECONDS = 3 * 3600


# FUNCTION: SET THE RUN'S FIT CACHE FOLDER
def set_fit_cache_folder_str(folder_str_in):
    """
    The runner sets this to <run folder>/fit_cache before a candidate stream or a look-ahead stream. One run's code
    is fixed (commit and code hash are checked on resume), so a fit keyed by the design's fit key and a hash of the
    training rows is the same object in every process of that run.

    Args:
        folder_str_in (str | None): Folder, or None to switch sharing off

    Returns:
        None
    """
    # MODULE STATE, PER PROCESS
    global _FIT_CACHE_FOLDER_STR
    _FIT_CACHE_FOLDER_STR = None if folder_str_in is None else str(folder_str_in)


# FUNCTION: A HASH OF THE TRAINING ROWS
def get_train_rows_hash_str(train_pdf_in):
    """
    Content hash of every column and row (order kept).

    Args:
        train_pdf_in (pd.DataFrame): Training rows

    Returns:
        str: Hex digest
    """
    # IMPORT HERE (RUNNER-ONLY)
    import hashlib
    hasher = hashlib.sha256()
    hasher.update(("|".join(str(column_str) for column_str in train_pdf_in.columns)).encode("utf-8"))
    if len(train_pdf_in):
        hasher.update(pd.util.hash_pandas_object(train_pdf_in, index=False).to_numpy().tobytes())
    return hasher.hexdigest()


# FUNCTION: FIT ONCE PER (FIT KEY, TRAINING ROWS) ACROSS THE RUN'S PROCESSES
def get_shared_fit(fit_key_str_in, train_pdf_in, fit_func_in):
    """
    A design with fit_shared and FIT_KEY_STR declares that every candidate with the same key fits the same model on
    the same rows. The first process writes <key>_<hash>.pkl; the others wait for it. A missing folder fits locally.

    Args:
        fit_key_str_in (str): Design fit key (e.g. the training window)
        train_pdf_in (pd.DataFrame): Training rows
        fit_func_in (callable): fit_shared(train_rows) -> shared model

    Returns:
        object: Shared model
    """
    # IMPORT HERE (RUNNER-ONLY FILE WORK)
    import os
    import pickle
    import time
    if _FIT_CACHE_FOLDER_STR is None:
        return fit_func_in(train_pdf_in)
    os.makedirs(_FIT_CACHE_FOLDER_STR, exist_ok=True)
    stem_str = f"{fit_key_str_in}_{get_train_rows_hash_str(train_pdf_in)}"
    model_path_str = os.path.join(_FIT_CACHE_FOLDER_STR, stem_str + ".pkl")
    lock_path_str = os.path.join(_FIT_CACHE_FOLDER_STR, stem_str + ".lock")
    # ALREADY FITTED
    if os.path.isfile(model_path_str):
        with open(model_path_str, "rb") as file_obj:
            return pickle.load(file_obj)
    # BECOME THE LEADER, OR WAIT FOR IT
    try:
        lock_fd = os.open(lock_path_str, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        start_time = time.time()
        while time.time() - start_time < FIT_CACHE_WAIT_SECONDS:
            if os.path.isfile(model_path_str):
                with open(model_path_str, "rb") as file_obj:
                    return pickle.load(file_obj)
            time.sleep(1.0)
        return fit_func_in(train_pdf_in)
    os.close(lock_fd)
    shared_model = fit_func_in(train_pdf_in)
    temp_path_str = model_path_str + f".{os.getpid()}.tmp"
    with open(temp_path_str, "wb") as file_obj:
        pickle.dump(shared_model, file_obj)
    os.replace(temp_path_str, model_path_str)
    return shared_model


# FUNCTION: ROW DAY ORDINALS AND LABEL CLOCKS FOR FAST TRAINING MASKS
def get_train_clock_dict(train_pool_pdf_in):
    """
    Args:
        train_pool_pdf_in (pd.DataFrame): Rows with decision_ts and label_known_ts (NaT allowed)

    Returns:
        dict: day_ord_arr (int64), label_ns_arr (int64), label_ok_arr (bool)
    """
    # NEW YORK DAYS OF THE DECISION; NANOSECONDS OF THE LABEL CLOCK
    decision_index = pd.DatetimeIndex(pd.to_datetime(train_pool_pdf_in["decision_ts"], utc=True)).tz_convert("America/New_York")
    day_ord_arr = np.asarray([day.toordinal() for day in decision_index.date], dtype=np.int64)
    label_series = pd.to_datetime(train_pool_pdf_in["label_known_ts"], utc=True)
    label_ok_arr = label_series.notna().to_numpy()
    label_ns_arr = np.asarray([ts.value if pd.notna(ts) else 0 for ts in label_series], dtype=np.int64)
    return {"day_ord_arr": day_ord_arr, "label_ns_arr": label_ns_arr, "label_ok_arr": label_ok_arr}


# FUNCTION: THE TRAINING MASK (ROW DAY IN THE WINDOW, LABEL KNOWN BEFORE THE REFIT)
def get_fast_training_mask_arr(clock_dict_in, refit_ts_in, train_window_str_in):
    """
    Row day inside [refit day - window, refit day] and label_known_ts strictly before the refit moment. A missing
    label clock is never a training row.

    Args:
        clock_dict_in (dict): Output of get_train_clock_dict
        refit_ts_in: Refit moment
        train_window_str_in (str): Training window

    Returns:
        np.ndarray: Boolean mask
    """
    # IMPORT THE WINDOW START HERE
    from so.core.rolling_retrain import get_train_window_start_ts
    refit_ts = get_ny_timestamp(refit_ts_in)
    refit_day_ord = int(refit_ts.date().toordinal())
    start_ts = get_train_window_start_ts(refit_ts, train_window_str_in)
    day_ord_arr = clock_dict_in["day_ord_arr"]
    mask_arr = day_ord_arr <= refit_day_ord
    if start_ts is not None:
        mask_arr &= day_ord_arr >= int(start_ts.date().toordinal())
    mask_arr &= clock_dict_in["label_ok_arr"] & (clock_dict_in["label_ns_arr"] < int(refit_ts.value))
    return mask_arr


# FUNCTION: ATTACH RUNNER METADATA TO A RECORDED DECISION
def get_recorded_decision_dict(decision_dict_in, bar_ts_in, session_date_in, bar_idx_in):
    """
    Args:
        decision_dict_in (dict): get_decision_dict output
        bar_ts_in: Bar-start label (the engine lookup)
        session_date_in: Session date
        bar_idx_in (int): Bar index

    Returns:
        dict: Decision plus _decision_ts, _session_date, _bar_idx
    """
    # LOOK-AHEAD MATCHES ON THE BAR TIMESTAMP
    recorded_dict = dict(decision_dict_in)
    recorded_dict[DECISION_TS_KEY_STR] = bar_ts_in
    recorded_dict[SESSION_DATE_KEY_STR] = session_date_in
    recorded_dict[BAR_IDX_KEY_STR] = int(bar_idx_in)
    return recorded_dict


# FUNCTION: A MINUTE LOOP THAT CAN STOP AT A PERIOD END AND RESUME
class MinuteLoop:
    """
    One design, one barrier engine, one window. Rows are built once. run_through_date walks sessions, fits at the
    rolling-retrain calendar, scores each refit block (shuffled), and fills at the next minute's open.
    """

    # FUNCTION: COLLECT THE WINDOW, THE ROWS AND THE ENGINE
    def __init__(self, design_in, ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None, engine_in=None,
                 initial_weight_in=0.0, dead_band_in=0.0, initial_capital_in=config.INITIAL_CAPITAL,
                 entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                 market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE, design_file_path_str_in=None,
                 check_source_bool_in=True, design_module_in=None):
        """
        Args:
            design_in (object): Candidate (fit may live here)
            ohlcv_array_dict_in (dict): Full bar arrays
            date1_in, date2_in: Window bounds
            data_context_in (DataContext | None): Loaded sources
            engine_in (Engine | None): None uses BarrierEngine
            initial_weight_in (float): Weight bought at the first 10:00 open (0 starts in cash)
            dead_band_in (float): Unused (barrier has no dead band)
            initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Default-engine costs
            design_file_path_str_in (str | None): Design file to AST-check
            check_source_bool_in (bool): False when the caller already ran the preflight
            design_module_in (module | None): Module that holds signal
        """
        # SIGNAL IS A MODULE-LEVEL FUNCTION; THE PREFLIGHT REFUSES A METHOD OR A CLOSURE
        _ = dead_band_in
        self.design_module = get_design_module(design_in, design_module_in)
        if check_source_bool_in:
            check_design_source(self.design_module, design_file_path_str_in)
        check_minute_signal(self.design_module)
        self.design = design_in
        self.ohlcv_array_dict = ohlcv_array_dict_in
        self.initial_weight_float = float(initial_weight_in)
        self.window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
        self.empty_bool = len(self.window_session_idx_arr) == 0
        self.next_session_pos_int = 0
        self.window_opened_bool = False
        self.target_weight_list = []
        self.decision_session_list = []
        self.decision_dict_list = []
        self.current_model = None
        self.current_refit_ts = None
        self.fitted_refit_list = []
        self.block_decision_dict = {}
        self.score_log_list = []
        self.train_log_list = []
        self.design_name_str = str(getattr(self.design_module, "EXPERIMENT_NAME",
                                           getattr(self.design_module, "__name__", "minute_design")))
        self.feature_col_list = [str(column_str) for column_str in list(getattr(self.design_module, "FEATURE_COL_LIST", []) or [])]
        self.signal_func = self.design_module.signal
        self.fit_func = get_minute_fit_func(design_in, self.design_module)
        self.train_window_str = get_train_window_str(design_in, self.design_module)
        self.retrain_frequency_str = get_retrain_frequency_str(design_in, self.design_module)
        if self.empty_bool:
            self.engine = engine_in
            self.row_pdf = pd.DataFrame()
            self.data_context = data_context_in
            self.retrain_session_list = []
            return
        data_context = data_context_in
        if data_context is None:
            data_context = get_runner_context(ohlcv_array_dict_in,
                                              declared_name_list_in=get_declared_source_name_list(self.design_module))
        self.data_context = data_context
        # TRAINING MAY USE EVERY EARLIER SESSION OF THE BARS (TRAIN_ROW_HISTORY_BOOL); SCORING USES THE WINDOW ONLY
        history_bool = self.fit_func is not None and bool(getattr(self.design_module, "TRAIN_ROW_HISTORY_BOOL", False))
        pool_date1 = ohlcv_array_dict_in["session_date_list"][0] if history_bool else date1_in
        pool_pdf = get_minute_row_pdf(self.design_module, ohlcv_array_dict_in, pool_date1, date2_in, data_context)
        window_session_set = set(int(session_idx) for session_idx in self.window_session_idx_arr)
        self.row_pdf = pool_pdf.loc[pool_pdf["session_idx"].astype(int).isin(window_session_set)].reset_index(drop=True)
        self.train_pool_pdf = self.get_train_pool_pdf(pool_pdf)
        self.train_clock_dict = get_train_clock_dict(self.train_pool_pdf) if len(self.train_pool_pdf) else None
        self.train_decision_ns_arr = np.asarray([get_ny_timestamp(ts).value for ts in self.train_pool_pdf["decision_ts"]], dtype=np.int64) if len(self.train_pool_pdf) else np.array([], dtype=np.int64)
        self.row_decision_ns_arr = np.asarray([get_ny_timestamp(ts).value for ts in self.row_pdf["decision_ts"]], dtype=np.int64)
        self.session_bar_dict = {}
        for session_idx, bar_idx in zip(self.row_pdf["session_idx"].astype(int), self.row_pdf["bar_idx"].astype(int)):
            self.session_bar_dict.setdefault(int(session_idx), []).append(int(bar_idx))
        session_date_list = [ohlcv_array_dict_in["session_date_list"][int(session_idx)]
                             for session_idx in self.window_session_idx_arr]
        if session_date_list:
            self.retrain_session_list = get_retrain_session_list(session_date_list, session_date_list[0],
                                                                session_date_list[-1], self.retrain_frequency_str)
        else:
            self.retrain_session_list = []
        self.retrain_session_set = set(self.retrain_session_list)
        self.session_refit_ts_dict = {}
        for session_date in self.retrain_session_list:
            session_pdf = self.row_pdf[self.row_pdf["session"].map(lambda value: pd.Timestamp(value).date())
                                       == pd.Timestamp(session_date).date()]
            if session_pdf.empty:
                session_idx = int(ohlcv_array_dict_in["date_session_idx_dict"][pd.Timestamp(session_date).date()])
                start_idx = int(ohlcv_array_dict_in["session_start_idx_arr"][session_idx])
                self.session_refit_ts_dict[pd.Timestamp(session_date).date()] = get_minute_bar_available_ts(
                    ohlcv_array_dict_in["timestamp_index"][start_idx])
            else:
                self.session_refit_ts_dict[pd.Timestamp(session_date).date()] = session_pdf["decision_ts"].iloc[0]
        self.end_idx_arr = ohlcv_array_dict_in["session_end_idx_arr"]
        self.start_idx_arr = ohlcv_array_dict_in["session_start_idx_arr"]
        self.open_arr = ohlcv_array_dict_in["open_arr"]
        self.close_arr = ohlcv_array_dict_in["close_arr"]
        self.timestamp_index = ohlcv_array_dict_in["timestamp_index"]
        self.engine = engine_in if engine_in is not None else BarrierEngine(
            int(getattr(self.design_module, "MAX_HOLD_TRADING_DAYS", config.MAX_HOLD_TRADING_DAYS)),
            float(getattr(self.design_module, "RR_RATIO", config.RR_RATIO)),
            initial_capital_in, entry_slippage_in, market_exit_slippage_in,
            config.LIMIT_EXIT_SLIPPAGE_PER_SHARE)
        self.engine.set_session_bounds(self.end_idx_arr, len(self.close_arr))

    # FUNCTION: FEATURE ROWS JOINED ONCE WITH EVERY LABEL KNOWN BEFORE THE LAST ROW
    def get_train_pool_pdf(self, pool_pdf_in):
        """
        The label door is applied per refit by the training mask (label_known_ts strictly before the refit moment).
        Joining once here and masking per refit gives the training rows of each refit without re-reading the labels.
        A design without a label source gets label_known_ts = NaT and is masked by the row clock only.

        Args:
            pool_pdf_in (pd.DataFrame): Minute rows (history and window)

        Returns:
            pd.DataFrame: Rows with label columns and label_known_ts
        """
        # NO ROWS, NO POOL
        if pool_pdf_in is None or len(pool_pdf_in) == 0:
            return pd.DataFrame()
        label_name_list = get_label_source_name_list(self.design_module)
        if not label_name_list or self.data_context is None:
            train_pdf = pool_pdf_in.copy()
            train_pdf["label_known_ts"] = pd.NaT
            train_pdf["_no_label_bool"] = True
            return train_pdf.reset_index(drop=True)
        cutoff_ts = get_ny_timestamp(pool_pdf_in["decision_ts"].iloc[-1]) + pd.Timedelta(minutes=1)
        train_pdf = pool_pdf_in.copy()
        train_pdf["_join_ts"] = pd.DatetimeIndex(pd.to_datetime(train_pdf["bar_ts"])).tz_convert("America/New_York")
        for source_name_str in label_name_list:
            label_pdf = self.data_context.get_labels(source_name_str, cutoff_ts)
            if label_pdf.empty:
                return pool_pdf_in.iloc[0:0].copy()
            label_pdf = label_pdf.copy()
            label_pdf["_join_ts"] = get_source_join_ts_series(label_pdf)
            drop_set = SIGNAL_DROP_COL_SET | {"_join_ts"}
            keep_col_list = [column_str for column_str in label_pdf.columns if column_str not in drop_set or column_str == "label_known_ts"]
            take_pdf = label_pdf[["_join_ts"] + [column_str for column_str in keep_col_list if column_str != "_join_ts"]]
            train_pdf = train_pdf.merge(take_pdf.drop_duplicates("_join_ts", keep="last"), on="_join_ts", how="inner")
        if len(train_pdf) and "label_known_ts" not in train_pdf.columns:
            raise ValueError("label rows have no label_known_ts.")
        return train_pdf.drop(columns=["_join_ts"], errors="ignore").reset_index(drop=True)

    # FUNCTION: THE TRAINING ROWS OF ONE REFIT
    def get_refit_train_pdf(self, refit_ts_in):
        """
        Rows dated inside the window, decided strictly before the refit moment, with a label known strictly before it.

        Args:
            refit_ts_in: Refit moment

        Returns:
            pd.DataFrame: Rows the fit may see
        """
        # AN EMPTY POOL TRAINS NOTHING
        if self.train_clock_dict is None:
            return pd.DataFrame()
        refit_ns = int(get_ny_timestamp(refit_ts_in).value)
        mask_arr = self.train_decision_ns_arr < refit_ns
        if "_no_label_bool" in self.train_pool_pdf.columns:
            from so.core.rolling_retrain import get_train_window_start_ts
            refit_ts = get_ny_timestamp(refit_ts_in)
            start_ts = get_train_window_start_ts(refit_ts, self.train_window_str)
            if start_ts is not None:
                mask_arr &= self.train_clock_dict["day_ord_arr"] >= int(start_ts.date().toordinal())
            return self.train_pool_pdf.loc[mask_arr].drop(columns=["_no_label_bool"]).reset_index(drop=True)
        mask_arr &= get_fast_training_mask_arr(self.train_clock_dict, refit_ts_in, self.train_window_str)
        return self.train_pool_pdf.loc[mask_arr].reset_index(drop=True)

    # FUNCTION: THE NEXT REFIT MOMENT AFTER THIS ONE
    def get_next_refit_ts(self, refit_ts_in):
        """
        Args:
            refit_ts_in: Current refit moment

        Returns:
            pd.Timestamp | None: Next refit, or None after the last
        """
        # CHRONOLOGICAL REFIT MOMENTS
        refit_ts_list = [self.session_refit_ts_dict[pd.Timestamp(session_date).date()]
                         for session_date in self.retrain_session_list]
        current_ts = get_ny_timestamp(refit_ts_in)
        later_list = [refit_ts for refit_ts in refit_ts_list if get_ny_timestamp(refit_ts) > current_ts]
        if not later_list:
            return None
        return later_list[0]

    # FUNCTION: SCORE ONE REFIT BLOCK (SHUFFLED, TWICE)
    def score_refit_block(self, refit_ts_in, model_in):
        """
        Rows with decision_ts >= this refit and < the next. The design does not choose the rows.

        Args:
            refit_ts_in: Refit moment
            model_in: Fitted model (may be None)

        Returns:
            None
        """
        # THE RUNNER CHOOSES THE SCORING WINDOW
        next_refit_ts = self.get_next_refit_ts(refit_ts_in)
        refit_ts = get_ny_timestamp(refit_ts_in)
        block_mask_arr = self.row_decision_ns_arr >= int(refit_ts.value)
        if next_refit_ts is not None:
            block_mask_arr &= self.row_decision_ns_arr < int(get_ny_timestamp(next_refit_ts).value)
        block_pdf = self.row_pdf.loc[block_mask_arr].reset_index(drop=True)
        decision_list = get_shuffled_signal_list(block_pdf, model_in, self.signal_func, self.design_name_str,
                                                 self.feature_col_list)
        self.score_log_list.append({"refit_ts": refit_ts, "next_refit_ts": next_refit_ts,
                                    "bar_idx_arr": block_pdf["bar_idx"].to_numpy(dtype=np.int64) if len(block_pdf) else np.array([], dtype=np.int64),
                                    "decision_ts_list": list(block_pdf["decision_ts"])})
        for row_idx, decision_dict in enumerate(decision_list):
            bar_idx = int(block_pdf["bar_idx"].iloc[row_idx])
            self.block_decision_dict[bar_idx] = get_recorded_decision_dict(
                decision_dict, block_pdf["bar_ts"].iloc[row_idx], block_pdf["session"].iloc[row_idx], bar_idx)

    # FUNCTION: FIT AT A REFIT SESSION AND SCORE THE BLOCK
    def fit_and_score_session(self, session_date_in):
        """
        Args:
            session_date_in: Session date

        Returns:
            None
        """
        # A REFIT ALREADY DONE ON THIS STREAM IS NOT REPEATED
        session_day = pd.Timestamp(session_date_in).date()
        if session_day not in self.session_refit_ts_dict:
            return
        refit_ts = self.session_refit_ts_dict[session_day]
        if any(get_ny_timestamp(seen_ts) == get_ny_timestamp(refit_ts) for seen_ts in self.fitted_refit_list):
            if self.current_model is not None and get_ny_timestamp(self.current_refit_ts) == get_ny_timestamp(refit_ts):
                self.score_refit_block(refit_ts, self.current_model)
            return
        train_pdf = self.get_refit_train_pdf(refit_ts)
        self.train_log_list.append({"refit_ts": refit_ts, "row_count": int(len(train_pdf)),
                                    "label_known_ts_list": list(train_pdf["label_known_ts"]) if "label_known_ts" in train_pdf.columns else []})
        self.fitted_refit_list.append(refit_ts)
        self.current_refit_ts = refit_ts
        if self.fit_func is not None:
            # AN EMPTY TRAINING SET IS PASSED TO THE DESIGN, WHICH DECIDES WHAT IT MEANS (USUALLY: NO MODEL, NO ENTRY)
            if callable(getattr(self.design, "fit_shared", None)) and getattr(self.design, "FIT_KEY_STR", None):
                # CANDIDATES WITH THE SAME FIT KEY SHARE ONE FIT OF THE SAME ROWS (ONE RUN, ONE CODE VERSION)
                shared_model = get_shared_fit(str(self.design.FIT_KEY_STR), train_pdf, self.design.fit_shared)
                self.current_model = self.design.finish_fit(shared_model)
            else:
                self.current_model = self.fit_func(train_pdf)
        self.score_refit_block(refit_ts, self.current_model)

    # FUNCTION: APPLY THIS SESSION'S FILLS AND EXITS
    def apply_session_fills(self, session_pos_in):
        """
        Args:
            session_pos_in (int): Position in the window session list

        Returns:
            None
        """
        # BARS OF THIS SESSION
        session_idx = int(self.window_session_idx_arr[int(session_pos_in)])
        start_idx = int(self.start_idx_arr[session_idx])
        end_idx = int(self.end_idx_arr[session_idx])
        session_date = self.ohlcv_array_dict["session_date_list"][session_idx]
        is_last_session = int(session_pos_in) == len(self.window_session_idx_arr) - 1
        last_bar_idx = len(self.close_arr) - 1
        fill_idx_list = []
        for bar_idx in self.session_bar_dict.get(session_idx, []):
            if bar_idx not in self.block_decision_dict:
                continue
            recorded_dict = self.block_decision_dict[bar_idx]
            if int(bar_idx) < start_idx or int(bar_idx) > end_idx:
                continue
            fill_idx = int(bar_idx) + int(config.DECISION_TO_ENTRY_BAR_OFFSET)
            if fill_idx > last_bar_idx:
                continue
            if int(self.ohlcv_array_dict["bar_session_idx_arr"][fill_idx]) != session_idx:
                continue
            fill_idx_list.append((int(fill_idx), int(bar_idx), recorded_dict))
        fill_idx_list.sort(key=lambda item: item[0])
        cursor_idx = start_idx
        for fill_idx, bar_idx, recorded_dict in fill_idx_list:
            morning_event_dict = get_bar_range_event_dict(self.ohlcv_array_dict, cursor_idx, fill_idx - 1, session_date)
            if morning_event_dict is not None:
                self.engine.process_bars(morning_event_dict)
            decision_dict = get_decision_dict(recorded_dict)
            if get_barrier_buy_bool(decision_dict):
                self.engine.apply_decision(get_fill_event_dict(self.ohlcv_array_dict, fill_idx, bar_idx, session_idx,
                                                               session_date, end_idx),
                                           decision_dict, float(self.close_arr[bar_idx]))
            cursor_idx = fill_idx
        rest_event_dict = get_bar_range_event_dict(self.ohlcv_array_dict, cursor_idx, end_idx, session_date)
        if rest_event_dict is not None:
            self.engine.process_bars(rest_event_dict)
        if is_last_session:
            self.engine.close_window({"bar_idx": end_idx, "timestamp": self.timestamp_index[end_idx],
                                      "raw_price": float(self.close_arr[end_idx]),
                                      "close": float(self.close_arr[end_idx]), "session_idx": session_idx,
                                      "session_date": session_date})
        self.engine.close_session({"session_date": session_date, "close": float(self.close_arr[end_idx])})
        state_dict = self.engine.get_state_dict()
        if is_last_session:
            self.target_weight_list.append(np.nan)
        else:
            self.target_weight_list.append(1.0 if state_dict["in_position"] else 0.0)
        for bar_idx in self.session_bar_dict.get(session_idx, []):
            if bar_idx not in self.block_decision_dict:
                continue
            self.decision_dict_list.append(dict(self.block_decision_dict[bar_idx]))
            self.decision_session_list.append(session_date)

    # FUNCTION: BUY THE INITIAL WEIGHT AT THE FIRST 10:00 OPEN
    def open_window_if_needed(self):
        """
        Args:
            None

        Returns:
            None
        """
        # ALREADY OPEN, OR NOTHING TO OPEN
        if self.empty_bool or self.window_opened_bool:
            return
        first_entry_idx = get_session_first_entry_idx(self.ohlcv_array_dict, int(self.window_session_idx_arr[0]))
        first_session_idx = int(self.window_session_idx_arr[0])
        self.engine.open_window({"bar_idx": int(first_entry_idx),
                                 "timestamp": self.timestamp_index[first_entry_idx],
                                 "raw_price": float(self.open_arr[first_entry_idx]),
                                 "close": float(self.close_arr[first_entry_idx]),
                                 "session_idx": first_session_idx,
                                 "session_date": self.ohlcv_array_dict["session_date_list"][first_session_idx]},
                                float(self.initial_weight_float))
        self.window_opened_bool = True

    # FUNCTION: ONE SESSION (REFIT, SCORE, FILL)
    def step_session(self, session_pos_in):
        """
        Args:
            session_pos_in (int): Position in the window session list

        Returns:
            None
        """
        # REFIT ON THE CALENDAR SESSION, THEN FILL
        session_idx = int(self.window_session_idx_arr[int(session_pos_in)])
        session_date = self.ohlcv_array_dict["session_date_list"][session_idx]
        if pd.Timestamp(session_date).date() in self.retrain_session_set:
            self.fit_and_score_session(session_date)
        self.apply_session_fills(session_pos_in)

    # FUNCTION: COPY NOTHING (MINUTE MODE HAS NO VIEW BUFFERS)
    def warmup_buffers(self, session_count_int_in):
        """
        Args:
            session_count_int_in (int): Unused

        Returns:
            None
        """
        # ROWS ARE BUILT IN __init__; THERE ARE NO DAILY BUFFERS
        _ = session_count_int_in
        return

    # FUNCTION: RESTORE A CHECKPOINT
    def restore_progress(self, next_session_pos_in, target_weight_list_in, decision_session_list_in, decision_dict_list_in):
        """
        Args:
            next_session_pos_in (int): First window session still to run
            target_weight_list_in, decision_session_list_in, decision_dict_list_in (list): Recorded so far

        Returns:
            None
        """
        # THE ENGINE WAS PICKLED AFTER OPEN_WINDOW
        self.next_session_pos_int = int(next_session_pos_in)
        self.target_weight_list = list(target_weight_list_in)
        self.decision_session_list = list(decision_session_list_in)
        self.decision_dict_list = list(decision_dict_list_in)
        self.window_opened_bool = True

    # FUNCTION: MINUTE-ONLY CHECKPOINT FIELDS
    def get_checkpoint_extra_dict(self):
        """
        Args:
            None

        Returns:
            dict: Model, refit moment, fitted refits
        """
        # THE MODEL IS RESTORED; THE BLOCK IS RE-SCORED
        return {"minute_model": self.current_model, "minute_refit_ts": self.current_refit_ts,
                "minute_fitted_refit_list": list(self.fitted_refit_list)}

    # FUNCTION: RESTORE THE FITTED MODEL
    def restore_checkpoint_extra(self, checkpoint_dict_in):
        """
        Args:
            checkpoint_dict_in (dict): Checkpoint payload

        Returns:
            None
        """
        # RE-SCORE THE BLOCK IN FORCE SO FILLS AFTER THE RESUME USE THE SAME MODEL
        self.current_model = checkpoint_dict_in.get("minute_model")
        self.current_refit_ts = checkpoint_dict_in.get("minute_refit_ts")
        self.fitted_refit_list = list(checkpoint_dict_in.get("minute_fitted_refit_list") or [])
        if self.current_model is not None and self.current_refit_ts is not None:
            self.score_refit_block(self.current_refit_ts, self.current_model)

    # FUNCTION: WALK FROM THE NEXT SESSION THROUGH A DATE
    def run_through_date(self, through_date_in):
        """
        Args:
            through_date_in: Last session to process (inclusive)

        Returns:
            None
        """
        # NOTHING IN THE WINDOW
        if self.empty_bool:
            return
        self.open_window_if_needed()
        through_date = pd.Timestamp(through_date_in).date()
        while self.next_session_pos_int < len(self.window_session_idx_arr):
            session_idx = int(self.window_session_idx_arr[self.next_session_pos_int])
            session_date = self.ohlcv_array_dict["session_date_list"][session_idx]
            if pd.Timestamp(session_date).date() > through_date:
                break
            self.step_session(self.next_session_pos_int)
            self.next_session_pos_int += 1

    # FUNCTION: TRADES, MARKS, TARGETS AND DECISIONS
    def get_result_dict(self):
        """
        Args:
            None

        Returns:
            dict: Engine result plus target_weight_arr, decision_session_list, decision_dict_list
        """
        # THE EMPTY WINDOW HAS NO ENGINE RESULT
        if self.empty_bool:
            return get_empty_daily_result_dict()
        result_dict = self.engine.get_result_dict()
        result_dict["target_weight_arr"] = np.asarray(self.target_weight_list, dtype=float)
        result_dict["decision_session_list"] = list(self.decision_session_list)
        result_dict["decision_dict_list"] = list(self.decision_dict_list)
        equity_pdf = result_dict.get("daily_equity_pdf")
        if equity_pdf is not None and len(equity_pdf) and "weight" in equity_pdf.columns:
            weight_arr = equity_pdf["weight"].to_numpy(dtype=float)
            counted_arr = weight_arr[:-1] if len(weight_arr) > 1 else weight_arr
            result_dict.setdefault("metric_dict", {})
            result_dict["metric_dict"]["mean_weight"] = float(counted_arr.mean()) if len(counted_arr) else 0.0
        return result_dict


# FUNCTION: RUN THE MINUTE LOOP
def run_minute_dict(design_in, ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None, engine_in=None,
                    initial_weight_in=0.0, dead_band_in=0.0, initial_capital_in=config.INITIAL_CAPITAL,
                    entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                    market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                    design_file_path_str_in=None, design_module_in=None):
    """
    Minute point-in-time replay. A signal at the end of minute t fills at the open of minute t+1.

    Args:
        design_in (object): Candidate
        ohlcv_array_dict_in (dict): Bar arrays
        date1_in, date2_in: Window bounds
        data_context_in (DataContext | None): Loaded sources
        engine_in (Engine | None): None uses BarrierEngine
        initial_weight_in (float): 0 starts in cash
        dead_band_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Engine
        design_file_path_str_in (str | None): Design file
        design_module_in (module | None): Module that holds signal

    Returns:
        dict: trade_pdf, daily_equity_pdf, metric_dict, target_weight_arr, decision_session_list, decision_dict_list
    """
    # REFUSE A DESIGN FILE THAT CAN REACH AROUND THE VIEW, THEN BLOCK DIRECT LOADS
    design_module = get_design_module(design_in, design_module_in)
    check_design_source(design_module, design_file_path_str_in)
    loop = MinuteLoop(design_in, ohlcv_array_dict_in, date1_in, date2_in, data_context_in, engine_in, initial_weight_in,
                      dead_band_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in,
                      design_file_path_str_in, check_source_bool_in=False, design_module_in=design_module)
    if loop.empty_bool:
        return get_empty_daily_result_dict()
    set_direct_read_blocked_bool(True)
    try:
        loop.run_through_date(date2_in)
    finally:
        set_direct_read_blocked_bool(False)
    return loop.get_result_dict()


# FUNCTION: ONE ENGINE PASS OVER RECORDED MINUTE DECISIONS (NO SIGNAL CALL)
def run_engine_minute_decisions_dict(ohlcv_array_dict_in, date1_in, date2_in, decision_dict_list_in, engine_in=None,
                                     initial_weight_in=0.0, initial_capital_in=config.INITIAL_CAPITAL,
                                     entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                                     market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                                     limit_exit_slippage_in=None):
    """
    Applies recorded minute decisions at the next-bar open. Same session-change skip as the old simulator.

    Args:
        ohlcv_array_dict_in (dict): Bar arrays
        date1_in, date2_in: Window bounds
        decision_dict_list_in (list[dict]): Recorded decisions (with _decision_ts or _bar_idx)
        engine_in (Engine | None): None uses a fresh BarrierEngine
        initial_weight_in (float): 0 starts in cash
        initial_capital_in, entry_slippage_in, market_exit_slippage_in, limit_exit_slippage_in (float): Costs

    Returns:
        dict: Engine result plus target_weight_arr and the recorded decisions
    """
    # THE SAME WINDOW AS THE MINUTE LOOP
    from so.core.trade_execution import get_ts_bar_idx_arr
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    if len(window_session_idx_arr) == 0:
        return get_empty_daily_result_dict()
    engine = engine_in if engine_in is not None else BarrierEngine(
        config.MAX_HOLD_TRADING_DAYS, config.RR_RATIO, initial_capital_in, entry_slippage_in,
        market_exit_slippage_in, config.LIMIT_EXIT_SLIPPAGE_PER_SHARE if limit_exit_slippage_in is None
        else float(limit_exit_slippage_in))
    engine.set_session_bounds(ohlcv_array_dict_in["session_end_idx_arr"], len(ohlcv_array_dict_in["close_arr"]))
    timestamp_index = ohlcv_array_dict_in["timestamp_index"]
    first_session_idx = int(window_session_idx_arr[0])
    first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, first_session_idx)
    engine.open_window({"bar_idx": int(first_entry_idx), "timestamp": timestamp_index[first_entry_idx],
                        "raw_price": float(ohlcv_array_dict_in["open_arr"][first_entry_idx]),
                        "close": float(ohlcv_array_dict_in["close_arr"][first_entry_idx]),
                        "session_idx": first_session_idx,
                        "session_date": ohlcv_array_dict_in["session_date_list"][first_session_idx]},
                       float(initial_weight_in))
    last_bar_idx = len(ohlcv_array_dict_in["close_arr"]) - 1
    fill_item_list = []
    for decision_dict in decision_dict_list_in:
        recorded_dict = dict(decision_dict)
        if BAR_IDX_KEY_STR in recorded_dict:
            bar_idx = int(recorded_dict[BAR_IDX_KEY_STR])
        elif DECISION_TS_KEY_STR in recorded_dict:
            bar_idx = int(get_ts_bar_idx_arr(ohlcv_array_dict_in, [recorded_dict[DECISION_TS_KEY_STR]])[0])
        else:
            continue
        if bar_idx < 0:
            continue
        fill_idx = int(bar_idx) + int(config.DECISION_TO_ENTRY_BAR_OFFSET)
        if fill_idx > last_bar_idx:
            continue
        if int(ohlcv_array_dict_in["bar_session_idx_arr"][fill_idx]) != int(ohlcv_array_dict_in["bar_session_idx_arr"][bar_idx]):
            continue
        fill_item_list.append((fill_idx, bar_idx, recorded_dict))
    fill_item_list.sort(key=lambda item: item[0])
    fill_by_session_dict = {}
    for fill_idx, bar_idx, recorded_dict in fill_item_list:
        session_idx = int(ohlcv_array_dict_in["bar_session_idx_arr"][fill_idx])
        fill_by_session_dict.setdefault(session_idx, []).append((fill_idx, bar_idx, recorded_dict))
    target_weight_list, decision_session_list, kept_decision_list = [], [], []
    last_window_pos = len(window_session_idx_arr) - 1
    for session_pos, session_idx in enumerate(window_session_idx_arr):
        session_idx = int(session_idx)
        start_idx = int(ohlcv_array_dict_in["session_start_idx_arr"][session_idx])
        end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx])
        session_date = ohlcv_array_dict_in["session_date_list"][session_idx]
        is_last_session = session_pos == last_window_pos
        cursor_idx = start_idx
        for fill_idx, bar_idx, recorded_dict in fill_by_session_dict.get(session_idx, []):
            morning_event_dict = get_bar_range_event_dict(ohlcv_array_dict_in, cursor_idx, fill_idx - 1, session_date)
            if morning_event_dict is not None:
                engine.process_bars(morning_event_dict)
            decision_dict = get_decision_dict(recorded_dict)
            kept_decision_list.append(dict(recorded_dict))
            decision_session_list.append(session_date)
            if get_barrier_buy_bool(decision_dict):
                engine.apply_decision(get_fill_event_dict(ohlcv_array_dict_in, fill_idx, bar_idx, session_idx,
                                                          session_date, end_idx),
                                      decision_dict, float(ohlcv_array_dict_in["close_arr"][bar_idx]))
            cursor_idx = fill_idx
        rest_event_dict = get_bar_range_event_dict(ohlcv_array_dict_in, cursor_idx, end_idx, session_date)
        if rest_event_dict is not None:
            engine.process_bars(rest_event_dict)
        if is_last_session:
            engine.close_window({"bar_idx": end_idx, "timestamp": timestamp_index[end_idx],
                                 "raw_price": float(ohlcv_array_dict_in["close_arr"][end_idx]),
                                 "close": float(ohlcv_array_dict_in["close_arr"][end_idx]),
                                 "session_idx": session_idx, "session_date": session_date})
        engine.close_session({"session_date": session_date, "close": float(ohlcv_array_dict_in["close_arr"][end_idx])})
        state_dict = engine.get_state_dict()
        target_weight_list.append(np.nan if is_last_session else (1.0 if state_dict["in_position"] else 0.0))
    result_dict = engine.get_result_dict()
    result_dict["target_weight_arr"] = np.asarray(target_weight_list, dtype=float)
    result_dict["decision_session_list"] = list(decision_session_list)
    result_dict["decision_dict_list"] = list(kept_decision_list)
    equity_pdf = result_dict.get("daily_equity_pdf")
    if equity_pdf is not None and len(equity_pdf) and "weight" in equity_pdf.columns:
        weight_arr = equity_pdf["weight"].to_numpy(dtype=float)
        counted_arr = weight_arr[:-1] if len(weight_arr) > 1 else weight_arr
        result_dict.setdefault("metric_dict", {})
        result_dict["metric_dict"]["mean_weight"] = float(counted_arr.mean()) if len(counted_arr) else 0.0
    return result_dict
