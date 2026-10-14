import threading
import time
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp01_minute_entry import config as exp_config
from experiments.exp01_minute_entry.walk_forward import fit_tp_model_dict, get_policy_decision_pdf, get_window_simulation_dict, predict_tp_proba_pdf

"""
Holdout Design: exp01_minute_entry_v2

Re-run of the walk-forward under the current rules, not new evidence. Twelve candidates: a training window of 3, 5 or
10 years, and an expected-net-return threshold of 0, 0.02%, 0.05% or 0.10%. The model is refit on the first session of
each week. A fit whose model cannot govern a scored session is not executed. A row whose barrier label is not yet
knowable is dropped, not filled. The signal check is not repeated.
"""

# THE GRID, WINDOW THEN THRESHOLD, WHICH IS THE PROTOCOL ORDER
_YEAR_LIST = list(exp_config.TRAIN_WINDOW_YEARS_LIST)
_THRESHOLD_LIST = list(exp_config.EV_THRESHOLD_LIST)

# FUNCTION: THE CANDIDATE NAME
def get_candidate_name_str(years_in, threshold_in):
    """
    Names one setting. The threshold is printed with four decimals.

    Args:
        years_in (int): Training window in years
        threshold_in (float): Expected-net-return threshold

    Returns:
        str: Name
    """
    # RETURN THE NAME
    return f"{int(years_in)}Y|{float(threshold_in):.4f}"

# FUNCTION: PARSE A CANDIDATE NAME
def parse_candidate_dict(candidate_str_in):
    """
    Recovers the window and the threshold from a name.

    Args:
        candidate_str_in (str): Name

    Returns:
        dict: years, window, threshold
    """
    # SPLIT THE NAME
    year_str, threshold_str = str(candidate_str_in).split("|")
    years = int(year_str.replace("Y", ""))
    return {"years": years, "window": f"{years}Y", "threshold": float(threshold_str)}

# DEFINE HOW CANDIDATE PERIODS ARE FORMED (THE QUARTER GRID USES THE 10-YEAR FOLDS AND THE EMBARGO OF 10)
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [max(_YEAR_LIST)]}
# DEFINE THE 12 CANDIDATES
CANDIDATE_LIST = [get_candidate_name_str(years, threshold) for years in _YEAR_LIST for threshold in _THRESHOLD_LIST]
# DEFINE THE SELECTION RULE (THE PREVIOUS QUARTER; TIES: THE SHORTER WINDOW, THEN THE HIGHER THRESHOLD)
SELECTION_RULE = {"pooled_periods": exp_config.PRIOR_SELECTION_QUARTER_COUNT,
                  "tie_break": [("years", True), ("threshold", False)]}
# DEFINE THE TIE COLUMNS THE RUNNER ATTACHES
CANDIDATE_TIE_VALUE_DICT = {
    "years": {name_str: parse_candidate_dict(name_str)["years"] for name_str in CANDIDATE_LIST},
    "threshold": {name_str: parse_candidate_dict(name_str)["threshold"] for name_str in CANDIDATE_LIST},
}
# COPY THE NAME AND THE PROTOCOL VERSION
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
# THE WEEKLY REFIT THE LEDGER ROW COPIES
RETRAIN_FREQUENCY_STR = exp_config.RETRAIN_FREQUENCY_STR
TRAIN_WINDOW_CANDIDATE_LIST = [f"{int(years)}Y" for years in _YEAR_LIST]
# FEATURES AND THE BARRIER LABELS
DATA_SOURCE_LIST = ["SPY_1MIN", "TSIND", "TSSEG", "TSCTX", "TSBAR"]
# CACHES LIVE FOR ONE REPLAY. THE RUNNER GIVES EVERY REPLAY A FRESH MODULE.
_cache_dict = {}
# THE SESSIONS WHOSE DECISIONS ARE SCORED. NONE KEEPS EVERY REFIT (A CALLER THAT HAS NOT SET A SPAN).
_score_span_tuple = None
# FALSE REPLAYS THE OLD LOOP, WHICH FITS WEEKS NO SCORED DECISION READS. THE DEVELOPMENT RUN LEAVES THIS TRUE.
_skip_unused_refits_bool = True
# A FAST ROW COUNT BELOW THIS IS RECOUNTED WITH THE MASK THE FIT USES. 5,000 IS FAR ABOVE THE 200-ROW RAISE.
_SLOW_COUNT_BELOW_INT = 5000
# THE DEVELOPMENT LOG PRINTS THIS OFTEN. THE COUNTERS DO NOT ENTER A FIT.
_PROGRESS_INTERVAL_SECONDS = 30 * 60
_progress_lock = threading.Lock()
_progress_dict = {"period_str": "loading", "done_int": 0, "total_int": 0, "start_time": None, "stop_bool": False, "thread": None}

# FUNCTION: A CHEAP KEY FOR ONE BAR ARRAY
def get_bar_key_tuple(ohlcv_array_dict_in):
    """
    Identifies a bar array so a later call on the same bars reuses the fit.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        tuple: Length, first close, last close, close sum
    """
    # THE CLOSE SUM MOVES WHEN A LATER BAR IS PERTURBED
    close_arr = np.asarray(ohlcv_array_dict_in["close_arr"], dtype=float)
    return (int(len(close_arr)), round(float(close_arr[0]), 8), round(float(close_arr[-1]), 8), round(float(close_arr.sum()), 4))

# FUNCTION: THE LAST DECISION MOMENT OF THESE BARS
def get_last_decision_ts(ohlcv_array_dict_in):
    """
    The decision timestamp of the last session.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.Timestamp: Decision time
    """
    # THE LAST SESSION'S DECISION BAR
    from so.core.point_in_time import get_decision_ts
    from so.features.daily_features import get_session_decision_idx_dict
    decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][-1])
    return get_decision_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])

# FUNCTION: JOIN THE CONTEXT FRAMES INTO SAMPLED MODEL ROWS
def get_dataset_pdf(ohlcv_array_dict_in, data_context_in):
    """
    One sampled decision row per kept bar. Features come from TSIND, TSSEG and TSCTX. Barrier labels come from TSBAR,
    with label_known_ts. Sampling is every 15 minutes, as protocol 1.0.

    Args:
        ohlcv_array_dict_in (dict): Bars
        data_context_in (DataContext): Point-in-time context

    Returns:
        pd.DataFrame: Model rows
    """
    # REUSE THE ROWS OF THIS BAR ARRAY AND THIS CONTEXT
    cache_key = (get_bar_key_tuple(ohlcv_array_dict_in), "rows", id(data_context_in))
    if cache_key in _cache_dict:
        return _cache_dict[cache_key]
    if data_context_in is None:
        raise ValueError("exp01 reads its features and labels through the DataContext.")
    from so.features.barrier_labels import add_TSBAR_label_cols, format_TSBAR_pdf
    from experiments.exp01_minute_entry.model_dataset import apply_sampling_pdf, get_model_feature_col_str_list
    decision_ts = get_last_decision_ts(ohlcv_array_dict_in)
    data_context_in.set_decision_ts(decision_ts)
    frame_dict = {name_str: data_context_in.get(name_str, decision_ts) for name_str in ["TSIND", "TSSEG", "TSCTX"]}
    data_context_in.set_decision_ts(None)
    # LABELS KNOWABLE BY THE DAY AFTER THE LAST DECISION. THE TRAINING MASK STILL DROPS THE UNFINISHED ONES.
    label_pdf = data_context_in.get_labels("TSBAR", decision_ts + pd.Timedelta(days=1))
    if "decision_ts" not in label_pdf.columns and "timestamp" in label_pdf.columns:
        label_pdf = label_pdf.rename(columns={"timestamp": "decision_ts"})
    dataset_pdf = label_pdf.copy()
    for name_str, frame_pdf in frame_dict.items():
        step_pdf = frame_pdf.copy()
        if "decision_ts" not in step_pdf.columns and "timestamp" in step_pdf.columns:
            step_pdf = step_pdf.rename(columns={"timestamp": "decision_ts"})
        feature_col_list = [column_str for column_str in step_pdf.columns if column_str not in ("decision_ts", "available_ts", "date", "label_known_ts")]
        dataset_pdf = dataset_pdf.merge(step_pdf[["decision_ts"] + feature_col_list], on="decision_ts", how="left", suffixes=("", f"_{name_str}"))
    dataset_pdf = add_TSBAR_label_cols(dataset_pdf, list(exp_config.MODEL_DELTA_LIST), drop_cell_cols_in=True)
    # STORED TIMESTAMPS ARE STRINGS. SAMPLING READS THE NEW YORK MINUTE, THE SAME CONVERSION PROTOCOL 1.0 USED.
    dataset_pdf = format_TSBAR_pdf(dataset_pdf)
    dataset_pdf = apply_sampling_pdf(dataset_pdf, exp_config.SAMPLING_MODE, exp_config.SAMPLE_EVERY_N_MINUTES).reset_index(drop=True)
    if "label_known_ts" not in dataset_pdf.columns:
        raise ValueError("TSBAR rows have no label_known_ts.")
    dataset_pdf["decision_ts"] = [pd.Timestamp(value) for value in dataset_pdf["decision_ts"]]
    dataset_pdf["session"] = [pd.Timestamp(value).date() for value in dataset_pdf["decision_ts"]]
    dataset_pdf["row_ts"] = dataset_pdf["decision_ts"]
    dataset_pdf["available_ts"] = dataset_pdf["decision_ts"]
    dataset_pdf.attrs["feature_col_list"] = get_model_feature_col_str_list(dataset_pdf)
    _cache_dict[cache_key] = dataset_pdf
    return dataset_pdf

# FUNCTION: SET THE SESSIONS WHOSE DECISIONS ARE SCORED
def set_score_span(date1_in, date2_in):
    """
    Refits before the model that governs date1_in, and refits after date2_in, are not executed.

    Args:
        date1_in, date2_in: Inclusive scored span

    Returns:
        None
    """
    # KEEP THE CALENDAR DAYS
    global _score_span_tuple
    start_date, end_date = pd.Timestamp(date1_in).date(), pd.Timestamp(date2_in).date()
    if end_date < start_date:
        raise ValueError("the scored span ends before it starts.")
    _score_span_tuple = (start_date, end_date)

# FUNCTION: DROP CACHED PREDICTIONS SO A SECOND LOOP CAN BE COMPARED
def clear_prediction_cache():
    """
    Drops prediction frames. The sampled rows stay cached.

    Returns:
        None
    """
    # PREDICTION KEYS ARE THE ONES WHOSE SECOND FIELD IS "pred"
    for cache_key in list(_cache_dict):
        if len(cache_key) > 1 and cache_key[1] == "pred":
            del _cache_dict[cache_key]

# FUNCTION: FORMAT SECONDS FOR THE PROGRESS LINE
def get_duration_str(seconds_in):
    """
    Hours, minutes and seconds. An unknown remaining time stays the word unknown.

    Args:
        seconds_in (float): Duration

    Returns:
        str: h:mm:ss, or unknown
    """
    # AN UNFINISHED ESTIMATE HAS NO NUMBER YET
    if seconds_in is None or not np.isfinite(seconds_in):
        return "unknown"
    whole_int = int(round(float(seconds_in)))
    hours_int, remainder_int = divmod(whole_int, 3600)
    minutes_int, seconds_int = divmod(remainder_int, 60)
    return f"{hours_int}:{minutes_int:02d}:{seconds_int:02d}"

# FUNCTION: PRINT THE DEVELOPMENT PROGRESS LINE
def print_progress_line():
    """
    Current period, refits done / total, elapsed, estimated remaining. Printing does not change a fit.

    Returns:
        None
    """
    # ELAPSED FROM THE FIRST PROGRESS START, REMAINING FROM THE REFITS ALREADY FINISHED
    with _progress_lock:
        start_time = _progress_dict["start_time"] or time.time()
        elapsed = time.time() - start_time
        done_int, total_int = int(_progress_dict["done_int"]), int(_progress_dict["total_int"])
        if done_int > 0 and total_int > done_int:
            remaining = elapsed / done_int * (total_int - done_int)
        elif done_int > 0:
            remaining = 0.0
        else:
            remaining = np.nan
        print(f"progress period {_progress_dict['period_str']} | refits {done_int}/{total_int} | elapsed {get_duration_str(elapsed)} | remaining {get_duration_str(remaining)}", flush=True)

# FUNCTION: NAME THE PERIOD THE PROGRESS LINE REPORTS
def set_progress_period_str(period_str_in):
    """
    The next progress line names this period.

    Args:
        period_str_in (str): Period text

    Returns:
        None
    """
    # THE THREAD READS THIS STRING
    _progress_dict["period_str"] = str(period_str_in)

# FUNCTION: START THE 30-MINUTE PROGRESS THREAD
def start_progress_thread():
    """
    Prints a progress line at once and then every 30 minutes until the run stops the thread.

    Returns:
        None
    """
    # ONE THREAD PER PROCESS
    if _progress_dict["thread"] is not None:
        return
    _progress_dict["start_time"] = time.time()
    _progress_dict["stop_bool"] = False
    # SLEEP IN SHORT STEPS SO A FINISHED RUN DOES NOT WAIT OUT THE HALF HOUR
    def loop():
        print_progress_line()
        while not _progress_dict["stop_bool"]:
            slept_int = 0
            while slept_int < _PROGRESS_INTERVAL_SECONDS and not _progress_dict["stop_bool"]:
                time.sleep(5)
                slept_int += 5
            if not _progress_dict["stop_bool"]:
                print_progress_line()
    thread = threading.Thread(target=loop, name="exp01-progress", daemon=True)
    _progress_dict["thread"] = thread
    thread.start()

# FUNCTION: STOP THE PROGRESS THREAD
def stop_progress_thread():
    """
    Stops the progress thread after the run has finished its last print.

    Returns:
        None
    """
    # THE DAEMON WOULD EXIT WITH THE PROCESS; THIS JUST STOPS FURTHER LINES
    _progress_dict["stop_bool"] = True

# FUNCTION: SESSIONS FROM THE GOVERNING REFIT THROUGH THE LAST SCORED SESSION
def get_kept_session_list(session_list_in, retrain_set_in, score_start_in, score_end_in):
    """
    The sessions whose model can govern a scored decision. The refit calendar is the one built on the full session
    list: this function does not rebuild it, so the first kept session is a refit only when that calendar says so.

    Args:
        session_list_in (list): Sampled sessions, chronological
        retrain_set_in (set): Refit sessions of the full span
        score_start_in, score_end_in: Inclusive scored span

    Returns:
        list: Sessions to walk
    """
    # THE LATEST REFIT ON OR BEFORE THE FIRST SCORED SESSION IS THE MODEL IN FORCE THAT DAY
    score_start, score_end = pd.Timestamp(score_start_in).date(), pd.Timestamp(score_end_in).date()
    governing_list = [session_date for session_date in session_list_in if session_date in retrain_set_in and session_date <= score_start]
    if not governing_list:
        return [session_date for session_date in session_list_in if session_date <= score_end]
    first_keep = governing_list[-1]
    return [session_date for session_date in session_list_in if first_keep <= session_date <= score_end]

# FUNCTION: THE FIRST DECISION TIMESTAMP OF EACH SESSION, IN ROW ORDER
def get_session_first_ts_dict(row_pdf_in):
    """
    The same timestamp the fit loop reads with iloc[0]: the first row of that session in the frame, not the earliest clock.

    Args:
        row_pdf_in (pd.DataFrame): Sampled rows

    Returns:
        dict: session -> decision_ts
    """
    # FIRST ROW WINS
    first_dict = {}
    for session_date, decision_ts in zip(row_pdf_in["session"].to_numpy(), row_pdf_in["decision_ts"].to_numpy()):
        if session_date not in first_dict:
            first_dict[session_date] = decision_ts
    return first_dict

# FUNCTION: DAY NUMBERS AND LABEL CLOCKS FOR THE UNUSED-REFIT COUNT
def get_row_clock_tuple(row_pdf_in):
    """
    New York day numbers and label clocks, one per sampled row. NaT stays NaT.

    Args:
        row_pdf_in (pd.DataFrame): Sampled rows

    Returns:
        tuple: row ordinals, label clock
    """
    # THE SAME NEW YORK CONVERSION THE TRAINING MASK USES
    from so.core.point_in_time import NY_TZ_STR
    row_clock = pd.DatetimeIndex(pd.to_datetime(row_pdf_in["row_ts"].to_numpy()))
    label_clock = pd.DatetimeIndex(pd.to_datetime(row_pdf_in["label_known_ts"].to_numpy()))
    row_clock = row_clock.tz_localize(NY_TZ_STR) if row_clock.tz is None else row_clock.tz_convert(NY_TZ_STR)
    label_clock = label_clock.tz_localize(NY_TZ_STR) if label_clock.tz is None else label_clock.tz_convert(NY_TZ_STR)
    row_ord_arr = np.array([day.toordinal() for day in row_clock.date], dtype=np.int32)
    return row_ord_arr, label_clock

# FUNCTION: A ROW COUNT WITH THE SAME WINDOW AND LABEL RULE AS THE TRAINING MASK
def get_fast_training_count_int(row_ord_arr_in, label_clock_in, refit_ts_in, window_str_in):
    """
    Rows inside the window whose label clock is strictly before the refit. This count only decides whether an unused
    refit would have raised. The fit itself still uses get_training_mask_arr.

    Args:
        row_ord_arr_in (np.ndarray): Row day ordinals
        label_clock_in (pd.DatetimeIndex): Label clocks
        refit_ts_in: Refit decision timestamp
        window_str_in (str): Training window

    Returns:
        int: Row count
    """
    # THE WINDOW START AND THE LABEL TEST ARE THE SHARED HELPERS
    from so.core.rolling_retrain import get_clock_ts, get_train_window_start_ts
    decision_ts = get_clock_ts(refit_ts_in)
    decision_ord = decision_ts.date().toordinal()
    start_ts = get_train_window_start_ts(refit_ts_in, window_str_in)
    if start_ts is None:
        date_ok_arr = row_ord_arr_in <= decision_ord
    else:
        date_ok_arr = (row_ord_arr_in >= start_ts.date().toordinal()) & (row_ord_arr_in <= decision_ord)
    label_ok_arr = np.asarray(label_clock_in < decision_ts, dtype=bool)
    return int(np.sum(date_ok_arr & label_ok_arr))

# FUNCTION: THE TRAINING-MASK ROW COUNT
def get_slow_training_count_int(row_pdf_in, refit_ts_in, window_str_in):
    """
    The row count of get_training_mask_arr, which is the count the fit uses.

    Args:
        row_pdf_in (pd.DataFrame): Sampled rows
        refit_ts_in: Refit decision timestamp
        window_str_in (str): Training window

    Returns:
        int: Row count
    """
    # THE MASK THE FIT WILL USE
    from so.core.rolling_retrain import get_training_mask_arr
    mask_arr = get_training_mask_arr(row_pdf_in["row_ts"], row_pdf_in["label_known_ts"], refit_ts_in, window_str_in)
    return int(np.sum(mask_arr))

# FUNCTION: WALK REFITS THAT NO SCORED SESSION READS, WITHOUT FITTING THEM
def advance_unused_refit_tuple(row_pdf_in, window_str_in, prefix_refit_list_in, first_ts_dict_in, row_ord_arr_in, label_clock_in):
    """
    Applies the 200-row rule to refits before the governing model. A success increments the model counter and does not
    fit. A short refit after a success raises, as the fit loop would.

    Args:
        row_pdf_in (pd.DataFrame): Sampled rows
        window_str_in (str): Training window
        prefix_refit_list_in (list): Refit sessions strictly before the governing refit
        first_ts_dict_in (dict): First decision timestamp of each session
        row_ord_arr_in (np.ndarray): Row day ordinals
        label_clock_in (pd.DatetimeIndex): Label clocks

    Returns:
        tuple: model sentinel (None or an empty dict), model_id
    """
    # NO EARLIER REFIT MEANS THE FIRST SCORED WEEK IS THE FIRST WEEK
    model, model_id = None, -1
    if not prefix_refit_list_in:
        return model, model_id
    last_prefix = prefix_refit_list_in[-1]
    for session_date in prefix_refit_list_in:
        # A SMALL COUNT, AND THE LAST UNUSED WEEK, USE THE MASK THE FIT USES
        refit_ts = first_ts_dict_in[session_date]
        fast_count = get_fast_training_count_int(row_ord_arr_in, label_clock_in, refit_ts, window_str_in)
        if fast_count < _SLOW_COUNT_BELOW_INT or session_date == last_prefix:
            slow_count = get_slow_training_count_int(row_pdf_in, refit_ts, window_str_in)
            if session_date == last_prefix and slow_count != fast_count:
                raise ValueError(f"unused-refit row count mismatch on {session_date} ({window_str_in}): fast {fast_count}, mask {slow_count}.")
            count = slow_count
        else:
            count = fast_count
        if count < int(exp_config.MIN_TRAIN_ROW_COUNT):
            # THE FIRST SESSIONS OF THE FILE HAVE NO 200 KNOWABLE ROWS YET. DO NOT SHORTEN THE WINDOW.
            if model is None:
                continue
            raise ValueError(f"refit on {session_date} ({window_str_in}) has {count} rows, below {exp_config.MIN_TRAIN_ROW_COUNT}.")
        # THE MODEL OBJECT IS REPLACED AT THE NEXT REFIT. THIS ONE IS NEVER PREDICTED WITH.
        model = {}
        model_id += 1
    return model, model_id

# FUNCTION: WEEKLY PREDICTIONS FOR ONE TRAINING WINDOW
def get_weekly_prediction_pdf(ohlcv_array_dict_in, data_context_in, window_str_in):
    """
    Refits on the first session of each week and predicts every later sampled row with that model. Rows whose label
    was not knowable at the refit are excluded from that refit. When a scored span is set, refits before the model
    that governs the first scored session, and refits after the last scored session, are not executed.

    Args:
        ohlcv_array_dict_in (dict): Bars
        data_context_in (DataContext): Point-in-time context
        window_str_in (str): "3Y", "5Y" or "10Y"

    Returns:
        pd.DataFrame: The dataset rows that have a model, plus p_tp columns
    """
    # REUSE THE PREDICTIONS OF THIS SPAN AND THIS SKIP FLAG
    cache_key = (get_bar_key_tuple(ohlcv_array_dict_in), "pred", window_str_in, id(data_context_in), _score_span_tuple, bool(_skip_unused_refits_bool))
    if cache_key in _cache_dict:
        return _cache_dict[cache_key]
    from so.core.rolling_retrain import get_retrain_session_list, get_training_mask_arr
    row_pdf = get_dataset_pdf(ohlcv_array_dict_in, data_context_in)
    feature_col_list = list(row_pdf.attrs["feature_col_list"])
    session_list = sorted(set(row_pdf["session"]))
    retrain_set = set(get_retrain_session_list(session_list, session_list[0], session_list[-1], RETRAIN_FREQUENCY_STR))
    # THE FULL CALENDAR STAYS. THE WALK STARTS AT THE MODEL A SCORED SESSION CAN STILL READ.
    loop_session_list = session_list
    model, model_id = None, -1
    if _skip_unused_refits_bool and _score_span_tuple is not None:
        loop_session_list = get_kept_session_list(session_list, retrain_set, _score_span_tuple[0], _score_span_tuple[1])
    planned_int = sum(session_date in retrain_set for session_date in loop_session_list)
    if _progress_dict["total_int"] == 0 and planned_int:
        _progress_dict["total_int"] = len(TRAIN_WINDOW_CANDIDATE_LIST) * planned_int
    if _skip_unused_refits_bool and _score_span_tuple is not None and loop_session_list:
        # THE PREFIX CHECK DOES NOT FIT. THE PROGRESS TOTAL ABOVE IS THE FITS THAT REMAIN.
        first_ts_dict = get_session_first_ts_dict(row_pdf)
        row_ord_arr, label_clock = get_row_clock_tuple(row_pdf)
        prefix_refit_list = [session_date for session_date in session_list if session_date in retrain_set and session_date < loop_session_list[0]]
        model, model_id = advance_unused_refit_tuple(row_pdf, window_str_in, prefix_refit_list, first_ts_dict, row_ord_arr, label_clock)
    kept_pdf_list = []
    for session_date in loop_session_list:
        session_pdf = row_pdf[row_pdf["session"] == session_date]
        if session_date in retrain_set:
            refit_ts = session_pdf["decision_ts"].iloc[0]
            mask_arr = get_training_mask_arr(row_pdf["row_ts"], row_pdf["label_known_ts"], refit_ts, window_str_in)
            train_pdf = row_pdf.loc[mask_arr]
            if len(train_pdf) < int(exp_config.MIN_TRAIN_ROW_COUNT):
                # THE FIRST SESSIONS OF THE FILE HAVE NO 200 KNOWABLE ROWS YET. DO NOT SHORTEN THE WINDOW.
                if model is None:
                    continue
                raise ValueError(f"refit on {session_date} ({window_str_in}) has {len(train_pdf)} rows, below {exp_config.MIN_TRAIN_ROW_COUNT}.")
            model = fit_tp_model_dict(train_pdf, feature_col_list, ohlcv_array_dict_in, alert_in=False)
            model_id += 1
            _progress_dict["done_int"] += 1
            print(f"\trefit {window_str_in} {session_date}: model {model_id}, {len(train_pdf)} rows", flush=True)
        if model is None or not model:
            continue
        proba_pdf = predict_tp_proba_pdf(model, session_pdf, feature_col_list)
        scored_pdf = session_pdf.reset_index(drop=True).copy()
        for column_str in proba_pdf.columns:
            scored_pdf[column_str] = proba_pdf[column_str].to_numpy()
        scored_pdf["model_id"] = model_id
        kept_pdf_list.append(scored_pdf)
    if not kept_pdf_list:
        raise ValueError(f"no fitted model for window {window_str_in}.")
    prediction_pdf = pd.concat(kept_pdf_list, ignore_index=True)
    _cache_dict[cache_key] = prediction_pdf
    return prediction_pdf

# FUNCTION: DECISIONS OF ONE CANDIDATE ON ONE SPAN
def get_candidate_decision_pdf(ohlcv_array_dict_in, data_context_in, candidate_str_in, date1_in, date2_in):
    """
    Buy when the best expected net return of the latest weekly model exceeds the candidate's threshold.

    Args:
        ohlcv_array_dict_in (dict): Bars
        data_context_in (DataContext): Point-in-time context
        candidate_str_in (str): Candidate name
        date1_in, date2_in: Span

    Returns:
        pd.DataFrame: decision_ts, buy_flag, delta, expected_return
    """
    # KEEP THE ROWS INSIDE THE SPAN AND APPLY THE THRESHOLD
    candidate_dict = parse_candidate_dict(candidate_str_in)
    prediction_pdf = get_weekly_prediction_pdf(ohlcv_array_dict_in, data_context_in, candidate_dict["window"])
    start_date, end_date = pd.Timestamp(date1_in).date(), pd.Timestamp(date2_in).date()
    span_pdf = prediction_pdf[(prediction_pdf["session"] >= start_date) & (prediction_pdf["session"] <= end_date)].copy()
    proba_col_list = [column_str for column_str in span_pdf.columns if column_str.startswith("p_tp_")]
    return get_policy_decision_pdf(span_pdf, span_pdf[proba_col_list], candidate_dict["threshold"])

# FUNCTION: READ SPY THROUGH THE CONTEXT
def read_context_inputs(ohlcv_array_dict_in, data_context_in):
    """
    Reads SPY_1MIN as of the last decision. The feature and label reads happen when the dataset is built.

    Args:
        ohlcv_array_dict_in (dict): Bars
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        None
    """
    # SPY THROUGH THE CONTEXT
    if data_context_in is None or not data_context_in.has_source_bool("SPY_1MIN") or not len(ohlcv_array_dict_in["session_date_list"]):
        return
    decision_ts = get_last_decision_ts(ohlcv_array_dict_in)
    data_context_in.set_decision_ts(decision_ts)
    data_context_in.get("SPY_1MIN", decision_ts, columns_in=["timestamp", "close", "available_ts"])
    data_context_in.set_decision_ts(None)

# FUNCTION: ROUND TRIPS AS THE TRADE TABLE THE RUNNER COUNTS
def get_trade_pdf(transaction_pdf_in):
    """
    One buy row and one sell row per round trip.

    Args:
        transaction_pdf_in (pd.DataFrame): Simulator transactions

    Returns:
        pd.DataFrame: trade_ts, delta_share_count, reason
    """
    # AN EMPTY PATH HAS NO TRADES
    if transaction_pdf_in is None or len(transaction_pdf_in) == 0:
        return pd.DataFrame(columns=["trade_ts", "delta_share_count", "reason"])
    row_dict_list = []
    for _, row in transaction_pdf_in.iterrows():
        row_dict_list.append({"trade_ts": row["buy_ts"], "delta_share_count": 1.0, "reason": "entry"})
        row_dict_list.append({"trade_ts": row["sell_ts"], "delta_share_count": -1.0, "reason": row.get("exit_reason", "exit")})
    return pd.DataFrame(row_dict_list)

# FUNCTION: ATTACH THE WEIGHT AND THE TRADES
def attach_path_columns(simulation_dict_in):
    """
    Weight is 1 on a session that ends with a position open.

    Args:
        simulation_dict_in (dict): Simulator output

    Returns:
        dict: The same dict, with weight and trade_pdf
    """
    # COPY THE EQUITY AND MARK THE POSITION
    equity_pdf = simulation_dict_in["daily_equity_pdf"].copy()
    equity_pdf["weight"] = equity_pdf["in_position"].astype(float)
    simulation_dict_in["daily_equity_pdf"] = equity_pdf
    simulation_dict_in["trade_pdf"] = get_trade_pdf(simulation_dict_in["transaction_pdf"])
    return simulation_dict_in

# FUNCTION: REPLAY ONE CANDIDATE OVER ONE PERIOD
def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
    """
    One quarter of one candidate. The weekly models use every earlier row whose label was already knowable.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Period bounds
        candidate_in (str): Candidate name
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, metric_dict
    """
    # READ SPY, THEN SIMULATE THE QUARTER
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    decision_pdf = get_candidate_decision_pdf(ohlcv_array_dict_in, data_context_in, str(candidate_in), date1_in, date2_in)
    return attach_path_columns(get_window_simulation_dict(decision_pdf, ohlcv_array_dict_in, date1_in, date2_in))

# FUNCTION: THE CANDIDATE IN FORCE ON ONE SESSION
def get_session_candidate_str(session_date_in, period_pdf_in, selection_pdf_in):
    """
    The governing candidate of the period that contains the session.

    Args:
        session_date_in (datetime.date): Session
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force

    Returns:
        str | None: Candidate
    """
    # THE PERIOD THAT COVERS THE SESSION
    session_day = pd.Timestamp(session_date_in).date()
    cover_pdf = period_pdf_in[(period_pdf_in["period_start"].map(lambda value: pd.Timestamp(value).date()) <= session_day)
                              & (period_pdf_in["period_end"].map(lambda value: pd.Timestamp(value).date()) >= session_day)]
    if cover_pdf.empty:
        return None
    period_id = int(cover_pdf["period_id"].iloc[-1])
    return selection_pdf_in.loc[selection_pdf_in["period_id"] == period_id, "candidate"].iloc[0]

# FUNCTION: REPLAY THE PRIOR-ONLY PATH
def run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
    """
    One simulation from the first period through the last. Each row uses the window and the threshold in force.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force per period
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, target_weight_arr, signal_arr, decision_session_list
    """
    # FIT EACH WINDOW ONCE, THEN SWITCH THE THRESHOLD BY PERIOD
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    date1, date2 = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    decision_list = []
    for candidate_str in sorted(set(selection_pdf_in["candidate"])):
        candidate_dict = parse_candidate_dict(candidate_str)
        prediction_pdf = get_weekly_prediction_pdf(ohlcv_array_dict_in, data_context_in, candidate_dict["window"])
        start_date, end_date = pd.Timestamp(date1).date(), pd.Timestamp(date2).date()
        span_pdf = prediction_pdf[(prediction_pdf["session"] >= start_date) & (prediction_pdf["session"] <= end_date)].copy()
        span_pdf["candidate"] = [get_session_candidate_str(session_date, period_pdf_in, selection_pdf_in) for session_date in span_pdf["session"]]
        span_pdf = span_pdf[span_pdf["candidate"] == candidate_str]
        if span_pdf.empty:
            continue
        proba_col_list = [column_str for column_str in span_pdf.columns if column_str.startswith("p_tp_")]
        decision_pdf = get_policy_decision_pdf(span_pdf, span_pdf[proba_col_list], candidate_dict["threshold"])
        decision_list.append(decision_pdf)
    if not decision_list:
        raise ValueError("the prior-only path has no decisions.")
    decision_pdf = pd.concat(decision_list, ignore_index=True).sort_values("decision_ts")
    simulation_dict = attach_path_columns(get_window_simulation_dict(decision_pdf, ohlcv_array_dict_in, date1, date2))
    equity_pdf = simulation_dict["daily_equity_pdf"]
    simulation_dict["target_weight_arr"] = equity_pdf["weight"].to_numpy(dtype=float)
    buy_day_set = set(pd.Timestamp(value).date() for value, flag in zip(decision_pdf["decision_ts"], decision_pdf["buy_flag"]) if flag)
    simulation_dict["signal_arr"] = np.array([1.0 if pd.Timestamp(day).date() in buy_day_set else 0.0 for day in equity_pdf["date"]])
    simulation_dict["decision_session_list"] = [pd.Timestamp(day).date() for day in equity_pdf["date"]]
    simulation_dict["decision_pdf"] = decision_pdf
    return simulation_dict

# FUNCTION: PATH-MATCHED BASELINES LIVE IN THE REPORT
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in):
    """
    The random-entry runs and the fixed-time baseline need the path's decision rows.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span

    Returns:
        dict: Empty
    """
    # THE BASELINES NEED THE PATH
    return {}

# FUNCTION: LOAD DECLARED SOURCES FOR A DEVELOPMENT REPLAY
def get_development_data_context(session_date_list_in):
    """
    Loads DATA_SOURCE_LIST through the development end and returns a development DataContext.

    Args:
        session_date_list_in (list): Session dates that include the window start

    Returns:
        DataContext: Development context
    """
    # THE DEVELOPMENT END IS BEFORE THE WINDOW
    from so.core.holdout import get_development_end_date
    from so.core.point_in_time import DataContext, load_source_frame_dict
    end_date = get_development_end_date(int(PERIOD_RULE["embargo_sessions"]), session_date_list_in)
    frame_dict = load_source_frame_dict(list(DATA_SOURCE_LIST), end_date)
    return DataContext("development", frame_dict_in=frame_dict, declared_name_list_in=list(DATA_SOURCE_LIST))
