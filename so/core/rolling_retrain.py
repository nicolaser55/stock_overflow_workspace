import time
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (DEFAULT FREQUENCY, WINDOWS, POOLED QUARTERS)
from so import config

"""
Rolling Retraining (Nicolas, 2026-10-11)

A model-based design is a walk-forward with a rolling training window. On each retraining session the model is fit
on rows that were already knowable that day, then kept until the next retraining. Every session is decided at its
decision bar with the latest fitted model. The path is one continuous series, in development and in the holdout.

The retraining frequency is a pre-registered protocol setting. The default is weekly: the first session of each
calendar week, so a Monday holiday is a Tuesday refit. Changing the frequency after results is a new version. A
protocol may pre-register one comparison of weekly against quarterly, and no other frequency comparison.

Training-window candidates default to 6 months, 2 years and 10 years. "ALL" is an expanding window from the first
session, for a protocol that pre-registers it. A row dated after the retraining day is outside every window: it was
not available that day. The candidate in force for a quarter is chosen from the last
CANDIDATE_SELECTION_POOLED_QUARTERS_DEFAULT completed quarters before that quarter, prior-only, the same rule as
exp02-exp13. A tie takes the longer training window (the more stable choice) unless the protocol names another order.

Labels may look forward from their own row. A model trained on day t learns only from rows whose label_known_ts is
strictly before the decision bar of day t. An unfinished label is dropped and counted as purged. It is never filled
with 0 or any other value. A row that has a label and no label_known_ts raises. When the label source is the
registered TSBAR source, label_known_ts comes from so.core.point_in_time. Otherwise the helpers below compute it:
a barrier label is knowable at the end of the bar where TP or SL was hit, or at the end of the horizon bar if neither
was hit; a fixed-horizon label is knowable at the decision timestamp of the session that many sessions later.

Features are checked with so.core.point_in_time.check_feature_available_ts. This module does not keep a second clock.
"""

# DEFINE THE FREQUENCIES A PROTOCOL MAY PRE-REGISTER
RETRAIN_FREQUENCY_ALLOWED_LIST = ["daily", "weekly", "monthly", "quarterly"]
# DEFINE THE TRAINING WINDOWS THE MASK ACCEPTS (ALL IS EXPANDING)
TRAIN_WINDOW_ALLOWED_LIST = ["6M", "2Y", "3Y", "5Y", "10Y", "ALL"]
# DEFINE THE LENGTH OF EACH NAMED WINDOW IN MONTHS (ALL HAS NO CALENDAR CUT; THE TIE BREAK TREATS IT AS THE LONGEST)
TRAIN_WINDOW_MONTH_DICT = {"6M": 6, "2Y": 24, "3Y": 36, "5Y": 60, "10Y": 120, "ALL": 10 ** 9}
# DEFINE HOW MANY CORES A CANDIDATE POOL MAY USE
MAX_JOB_COUNT = 8

"""
Retraining Sessions
"""

# FUNCTION: CONVERT A VALUE TO A NEW YORK TIMESTAMP
def get_clock_ts(timestamp_in):
    """
    Normalizes a timestamp to America/New_York.

    Args:
        timestamp_in (datetime-like): Timestamp

    Returns:
        pd.Timestamp: New York timestamp
    """
    # THE POINT-IN-TIME CLOCK IS THE ONE CLOCK
    from so.core.point_in_time import get_ny_timestamp
    return get_ny_timestamp(timestamp_in)

# FUNCTION: CONVERT A VALUE TO A SESSION DATE
def get_session_date(value_in):
    """
    Converts a date-like value to datetime.date.

    Args:
        value_in (datetime.date | str | pd.Timestamp): Session

    Returns:
        datetime.date: The session date
    """
    # DATES AND TIMESTAMPS BOTH REDUCE TO THE CALENDAR DAY
    return pd.Timestamp(value_in).date()

# FUNCTION: THE FIRST SESSION OF EACH CALENDAR BLOCK, PLUS THE FIRST SESSION OF THE SPAN
def get_retrain_session_list(session_date_list_in, start_date_in, end_date_in, frequency_str_in):
    """
    The sessions on which a refit happens. weekly is the first session of each ISO week (Monday-start; a Monday
    holiday makes Tuesday the first session). monthly is the first session of each calendar month. quarterly is the
    first session of each calendar quarter. daily is every session. The first session of the span is always a refit.

    Args:
        session_date_list_in (list): Session dates, in any order
        start_date_in, end_date_in: Inclusive span
        frequency_str_in (str): "daily", "weekly", "monthly" or "quarterly"

    Returns:
        list[datetime.date]: Retraining sessions, chronological, no duplicates
    """
    # REFUSE A FREQUENCY THE PROTOCOL MAY NOT NAME
    if frequency_str_in not in RETRAIN_FREQUENCY_ALLOWED_LIST:
        raise ValueError(f"retraining frequency '{frequency_str_in}' is not one of {RETRAIN_FREQUENCY_ALLOWED_LIST}.")
    # KEEP THE SESSIONS INSIDE THE SPAN
    start_date, end_date = get_session_date(start_date_in), get_session_date(end_date_in)
    session_date_list = sorted({get_session_date(session_date) for session_date in session_date_list_in if start_date <= get_session_date(session_date) <= end_date})
    if not session_date_list:
        return []
    # DAILY REFITS ON EVERY SESSION
    if frequency_str_in == "daily":
        return session_date_list
    # THE BLOCK KEY OF A SESSION
    def get_block_key(session_date):
        # A WEEK IS THE ISO WEEK (MONDAY START)
        if frequency_str_in == "weekly":
            iso = session_date.isocalendar()
            return (iso[0], iso[1])
        # A MONTH IS THE CALENDAR MONTH
        if frequency_str_in == "monthly":
            return (session_date.year, session_date.month)
        # A QUARTER IS JANUARY, APRIL, JULY, OCTOBER
        return (session_date.year, (session_date.month - 1) // 3)
    # THE FIRST SESSION OF EACH BLOCK
    first_dict = {}
    for session_date in session_date_list:
        first_dict.setdefault(get_block_key(session_date), session_date)
    # THE FIRST SESSION OF THE SPAN IS A REFIT EVEN MID-BLOCK
    retrain_set = set(first_dict.values())
    retrain_set.add(session_date_list[0])
    return sorted(retrain_set)

"""
Label Clocks
"""

# FUNCTION: WHEN A BARRIER LABEL BECAME KNOWABLE
def get_barrier_label_known_ts_arr(exit_ts_arr_in):
    """
    The end of the bar where TP or SL was hit, or the end of the horizon bar when neither was hit. exit_ts_arr_in is
    that bar's start label. The clock matches the registered TSBAR rule (so.core.point_in_time.get_minute_bar_available_ts):
    the bar can be known when it ends.

    Args:
        exit_ts_arr_in (array-like): Bar-start label of the hit bar or the horizon-end bar

    Returns:
        np.ndarray: label_known_ts, one per row (NaT when the exit timestamp is missing)
    """
    # THE REGISTERED MINUTE CLOCK
    from so.core.point_in_time import get_minute_bar_available_ts
    # ONE CLOCK PER EXIT BAR
    known_list = [pd.NaT if pd.isna(exit_ts) else get_minute_bar_available_ts(exit_ts) for exit_ts in exit_ts_arr_in]
    return np.array(known_list, dtype="object")

# FUNCTION: WHEN A FIXED-HORIZON LABEL BECAME KNOWABLE
def get_fixed_horizon_label_known_ts_arr(decision_ts_arr_in, horizon_session_count_in):
    """
    The decision timestamp of the session horizon_session_count_in sessions later. The last horizon_session_count_in
    rows have no such session, so their clock is NaT and a training mask excludes them.

    Args:
        decision_ts_arr_in (array-like): Decision timestamp of each row, in session order
        horizon_session_count_in (int): Forward horizon in sessions

    Returns:
        np.ndarray: label_known_ts (NaT on the last horizon rows)
    """
    # A NON-POSITIVE HORIZON IS NOT A FORWARD LABEL
    horizon_int = int(horizon_session_count_in)
    if horizon_int < 1:
        raise ValueError("a fixed-horizon label needs a horizon of at least 1 session.")
    # SHIFT THE DECISION TIMESTAMPS FORWARD BY THE HORIZON
    decision_list = list(decision_ts_arr_in)
    known_list = [pd.NaT] * len(decision_list)
    for row_idx in range(len(decision_list) - horizon_int):
        known_list[row_idx] = decision_list[row_idx + horizon_int]
    return np.array(known_list, dtype="object")

# FUNCTION: ATTACH label_known_ts, FROM THE REGISTRY WHEN THE SOURCE IS A REGISTERED LABEL
def get_label_known_ts_pdf(label_pdf_in, source_name_str_in=None, horizon_session_count_in=None):
    """
    Returns a copy that carries label_known_ts. A registered label source (TSBAR) uses its point-in-time availability
    function. Otherwise a frame with exit_ts uses the barrier helper, and a frame with decision_ts plus a horizon uses
    the fixed-horizon helper. A frame that already carries label_known_ts is normalized to New York. A labelled frame
    with none of these raises.

    Args:
        label_pdf_in (pd.DataFrame): Label rows
        source_name_str_in (str | None): Registry name, or None when the helpers compute the clock
        horizon_session_count_in (int | None): Fixed horizon in sessions

    Returns:
        pd.DataFrame: Copy with label_known_ts
    """
    # A REGISTERED LABEL SOURCE KEEPS THE REGISTRY CLOCK
    if source_name_str_in is not None:
        from so.core.point_in_time import get_source_spec_dict
        spec_dict = get_source_spec_dict(source_name_str_in)
        if spec_dict.get("role") != "label":
            raise ValueError(f"{source_name_str_in} is not a label source.")
        return spec_dict["availability_func"](label_pdf_in)
    # COPY BEFORE ADDING THE CLOCK
    labelled_pdf = label_pdf_in.copy()
    # A BARRIER FRAME: THE HIT BAR OR THE HORIZON END
    if "exit_ts" in labelled_pdf.columns and "label_known_ts" not in labelled_pdf.columns:
        labelled_pdf["label_known_ts"] = get_barrier_label_known_ts_arr(labelled_pdf["exit_ts"])
        return labelled_pdf
    # A FIXED HORIZON: THE DECISION OF THE LATER SESSION
    if horizon_session_count_in is not None:
        if "decision_ts" not in labelled_pdf.columns:
            raise ValueError("a fixed-horizon label needs decision_ts.")
        labelled_pdf["label_known_ts"] = get_fixed_horizon_label_known_ts_arr(labelled_pdf["decision_ts"], horizon_session_count_in)
        return labelled_pdf
    # AN EXISTING CLOCK IS NORMALIZED
    if "label_known_ts" not in labelled_pdf.columns:
        raise ValueError("A labelled row has no label_known_ts.")
    labelled_pdf["label_known_ts"] = [pd.NaT if pd.isna(label_ts) else get_clock_ts(label_ts) for label_ts in labelled_pdf["label_known_ts"]]
    return labelled_pdf

# FUNCTION: REFUSE A LABEL THAT HAS NO CLOCK
def check_labelled_row_clock(label_arr_in, label_known_ts_arr_in):
    """
    A finite label whose label_known_ts is missing raises. An unfinished row (no label, no clock) does not.

    Args:
        label_arr_in (array-like): Label values
        label_known_ts_arr_in (array-like): Label clocks

    Returns:
        None
    """
    # THE TWO ARRAYS ARE ROW-ALIGNED
    if len(label_arr_in) != len(label_known_ts_arr_in):
        raise ValueError("labels and label_known_ts have different lengths.")
    # A FINITE LABEL WITHOUT A CLOCK IS A LEAK, NOT AN UNFINISHED ROW
    for label_value, label_known_ts in zip(label_arr_in, label_known_ts_arr_in):
        label_finite_bool = isinstance(label_value, (int, float, np.integer, np.floating)) and np.isfinite(label_value)
        if label_finite_bool and pd.isna(label_known_ts):
            raise ValueError("A labelled row has no label_known_ts.")

"""
Training Mask
"""

# FUNCTION: THE FIRST DAY OF A TRAINING WINDOW
def get_train_window_start_ts(retrain_decision_ts_in, train_window_str_in):
    """
    Midnight New York on (retrain day - the window). ALL has no calendar start (None): every row date is inside it.

    Args:
        retrain_decision_ts_in (datetime-like): Decision bar of the retraining session
        train_window_str_in (str): "6M", "2Y", "10Y" or "ALL"

    Returns:
        pd.Timestamp | None: Window start, or None for ALL
    """
    # REFUSE AN UNKNOWN WINDOW
    if train_window_str_in not in TRAIN_WINDOW_ALLOWED_LIST:
        raise ValueError(f"training window '{train_window_str_in}' is not one of {TRAIN_WINDOW_ALLOWED_LIST}.")
    # ALL STARTS AT THE FIRST SESSION THE CALLER PASSED
    if train_window_str_in == "ALL":
        return None
    # 6 MONTHS, OR A WHOLE NUMBER OF YEARS, MEASURED BACK FROM THE RETRAIN DAY
    day_ts = get_clock_ts(retrain_decision_ts_in).normalize()
    if train_window_str_in == "6M":
        return day_ts - pd.DateOffset(months=6)
    year_dict = {"2Y": 2, "3Y": 3, "5Y": 5, "10Y": 10}
    return day_ts - pd.DateOffset(years=year_dict[train_window_str_in])

# FUNCTION: ROWS THAT MAY TRAIN A REFIT
def get_training_mask_arr(row_ts_arr_in, label_known_ts_arr_in, retrain_decision_ts_in, train_window_str_in):
    """
    True when the row's date is inside the training window and label_known_ts is strictly before the retraining
    decision. The window runs from (retrain day - the named length) through the retrain day. A later row was not
    available that day. A missing label clock is not True: that row is dropped, not filled. ALL keeps every row on or
    before the retrain day that passes the label test.

    Args:
        row_ts_arr_in (array-like): Timestamp of each row
        label_known_ts_arr_in (array-like): When that row's label became knowable
        retrain_decision_ts_in (datetime-like): Decision bar of the retraining session
        train_window_str_in (str): "6M", "2Y", "10Y" or "ALL"

    Returns:
        np.ndarray: Boolean mask, True for rows the fit may see
    """
    # THE TWO CLOCKS ARE ROW-ALIGNED
    row_count = len(row_ts_arr_in)
    if len(label_known_ts_arr_in) != row_count:
        raise ValueError("row_ts and label_known_ts have different lengths.")
    # THE CALENDAR WINDOW, THEN THE LABEL CLOCK (A MISSING CLOCK IS NOT A TRAINING ROW)
    decision_ts = get_clock_ts(retrain_decision_ts_in)
    date_mask_arr = get_window_date_mask_arr(row_ts_arr_in, retrain_decision_ts_in, train_window_str_in)
    mask_list = []
    for date_ok_bool, label_known_ts in zip(date_mask_arr, label_known_ts_arr_in):
        if not date_ok_bool or pd.isna(label_known_ts):
            mask_list.append(False)
            continue
        mask_list.append(bool(get_clock_ts(label_known_ts) < decision_ts))
    return np.asarray(mask_list, dtype=bool)

# FUNCTION: ROWS INSIDE THE CALENDAR WINDOW, IGNORING THE LABEL CLOCK
def get_window_date_mask_arr(row_ts_arr_in, retrain_decision_ts_in, train_window_str_in):
    """
    True when the row date is on or after the training-window start and on or before the retrain day. ALL has no start,
    so it is every row on or before the retrain day. Rows inside this mask whose label is not yet knowable are purged.

    Args:
        row_ts_arr_in (array-like): Timestamp of each row
        retrain_decision_ts_in (datetime-like): Decision bar of the retraining session
        train_window_str_in (str): "6M", "2Y", "10Y" or "ALL"

    Returns:
        np.ndarray: Boolean mask
    """
    # THE WINDOW IS THE RETRAIN DAY AND THE DAYS BACK TO THE START (A LATER ROW WAS NOT AVAILABLE THAT DAY)
    decision_day = get_clock_ts(retrain_decision_ts_in).date()
    start_ts = get_train_window_start_ts(retrain_decision_ts_in, train_window_str_in)
    mask_list = []
    for row_ts in row_ts_arr_in:
        if pd.isna(row_ts):
            mask_list.append(False)
            continue
        row_day = get_clock_ts(row_ts).date()
        start_ok_bool = True if start_ts is None else row_day >= start_ts.date()
        mask_list.append(bool(start_ok_bool and row_day <= decision_day))
    return np.asarray(mask_list, dtype=bool)

"""
One Rolling Fit
"""

# FUNCTION: WHETHER A LABEL VALUE IS A FINITE NUMBER
def get_finite_label_bool(label_value_in):
    """
    True for a finite number. NaN, None and strings are not labels.

    Args:
        label_value_in: One label cell

    Returns:
        bool: Finite
    """
    # NUMBERS ONLY
    return isinstance(label_value_in, (int, float, np.integer, np.floating)) and bool(np.isfinite(label_value_in))

# FUNCTION: FIT ONE WINDOW ACROSS THE DECISION SESSIONS AND PREDICT WITH THE LATEST MODEL
def run_rolling_retrain_dict(row_pdf_in, feature_col_list_in, label_col_str_in, fit_func_in, predict_func_in,
                             decision_session_list_in, train_window_str_in, frequency_str_in, seed_in,
                             min_train_row_count_in, purge_unfinished_label_bool_in=True):
    """
    Walks the decision sessions. On each retraining session, fits fit_func_in on the masked rows. On every decision
    session, predicts with the latest fitted model. The fit receives only the kept rows: an unfinished label is absent,
    not filled with 0 or NaN. A refit with fewer than min_train_row_count_in rows raises. There is no fallback window.

    fit_func_in(train_pdf, feature_col_list, label_col, seed) -> model.
    predict_func_in(model, feature_pdf, feature_col_list) -> one prediction per feature row.
    The same seed_in is passed to every fit, so the predictions do not depend on which worker ran the fit.

    purge_unfinished_label_bool_in is True in every protocol. False is only for the truncation test that must catch a
    design which trains on labels that are not yet knowable. Features are refused by check_feature_available_ts when
    their available_ts is after the decision.

    Args:
        row_pdf_in (pd.DataFrame): One row per labelled session, with session, row_ts, decision_ts, label_known_ts,
            available_ts, the feature columns and the label column
        feature_col_list_in (list[str]): Feature columns
        label_col_str_in (str): Label column
        fit_func_in (callable): Fit
        predict_func_in (callable): Predict
        decision_session_list_in (list): Sessions that receive a prediction
        train_window_str_in (str): "6M", "2Y", "10Y" or "ALL"
        frequency_str_in (str): Retraining frequency
        seed_in (int): Seed passed to every fit
        min_train_row_count_in (int): Minimum rows a refit must have
        purge_unfinished_label_bool_in (bool): Drop rows whose label_known_ts is not strictly before the decision

    Returns:
        dict: prediction_pdf (session, prediction, model_id), refit_log_pdf (one row per refit)
    """
    # THE LABEL CLOCK IS REQUIRED
    if "label_known_ts" not in row_pdf_in.columns:
        raise ValueError("A labelled row has no label_known_ts.")
    # A FINITE LABEL WITHOUT A CLOCK RAISES; AN UNFINISHED ROW DOES NOT
    check_labelled_row_clock(row_pdf_in[label_col_str_in].to_numpy(), row_pdf_in["label_known_ts"].to_numpy())
    # THE DECISION SESSIONS IN ORDER
    decision_date_list = [get_session_date(session_date) for session_date in decision_session_list_in]
    if not decision_date_list:
        raise ValueError("a rolling retrain needs at least one decision session.")
    # INDEX THE ROWS BY SESSION (THE LAST ROW WINS IF A SESSION IS REPEATED)
    row_pdf = row_pdf_in.reset_index(drop=True).copy()
    row_pdf["_session_date"] = [get_session_date(session_date) for session_date in row_pdf["session"]]
    row_by_session_dict = {session_date: group_pdf.iloc[-1] for session_date, group_pdf in row_pdf.groupby("_session_date", sort=False)}
    # RETRAINING SESSIONS INSIDE THE DECISION SPAN
    retrain_date_list = get_retrain_session_list(decision_date_list, decision_date_list[0], decision_date_list[-1], frequency_str_in)
    retrain_date_set = set(retrain_date_list)
    # THE CLOCKS AND THE FINITE CELLS, ONCE (A REFIT THEN ONLY COMPARES THEM)
    row_ts_arr = row_pdf["row_ts"].to_numpy()
    label_known_arr = row_pdf["label_known_ts"].to_numpy()
    row_day_list, label_ns_list = [], []
    for row_ts, label_known_ts in zip(row_ts_arr, label_known_arr):
        row_day_list.append(None if pd.isna(row_ts) else get_clock_ts(row_ts).date())
        label_ns_list.append(None if pd.isna(label_known_ts) else int(get_clock_ts(label_known_ts).value))
    row_day_arr = np.asarray(row_day_list, dtype=object)
    label_ns_arr = np.asarray(label_ns_list, dtype=object)
    feature_float_arr = row_pdf[list(feature_col_list_in)].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    label_float_arr = pd.to_numeric(row_pdf[label_col_str_in], errors="coerce").to_numpy(dtype=float)
    finite_feature_arr = np.isfinite(feature_float_arr).all(axis=1) if feature_float_arr.ndim == 2 else np.isfinite(feature_float_arr)
    finite_label_arr = np.isfinite(label_float_arr)
    # WALK THE DECISIONS
    prediction_dict_list, refit_dict_list = [], []
    model, model_id_int = None, -1
    for session_date in decision_date_list:
        # THIS SESSION MUST HAVE A FEATURE ROW
        if session_date not in row_by_session_dict:
            raise ValueError(f"no feature row for decision session {session_date}.")
        session_row = row_by_session_dict[session_date]
        decision_ts = get_clock_ts(session_row["decision_ts"])
        # REFIT ON A RETRAINING SESSION
        if session_date in retrain_date_set:
            # THE CALENDAR WINDOW (PRECOMPUTED DATES) AND THE LABEL CLOCK
            decision_ns = int(decision_ts.value)
            decision_day = decision_ts.date()
            start_ts = get_train_window_start_ts(decision_ts, train_window_str_in)
            start_day = None if start_ts is None else start_ts.date()
            date_mask_arr = np.asarray([row_day is not None and (start_day is None or row_day >= start_day) and row_day <= decision_day for row_day in row_day_arr], dtype=bool)
            ready_mask_arr = np.asarray([bool(date_ok and label_ns is not None and label_ns < decision_ns) for date_ok, label_ns in zip(date_mask_arr, label_ns_arr)], dtype=bool)
            # PURGE DROPS UNFINISHED LABELS; DISABLING IT KEEPS THEM WHEN THE LABEL NUMBER IS FINITE
            keep_mask_arr = ready_mask_arr if purge_unfinished_label_bool_in else date_mask_arr
            # A NON-FINITE LABEL NEVER REACHES THE FIT, AND A NON-FINITE FEATURE IS NOT FILLED
            finite_mask_arr = keep_mask_arr & finite_feature_arr & finite_label_arr
            # PURGED = INSIDE THE WINDOW AND NOT HANDED TO THE FIT BECAUSE THE LABEL WAS NOT YET KNOWABLE
            if purge_unfinished_label_bool_in:
                purged_count = int((date_mask_arr & ~ready_mask_arr).sum())
            else:
                purged_count = int((date_mask_arr & ~finite_label_arr).sum())
            train_pdf = row_pdf.loc[finite_mask_arr].copy()
            # NO SILENT FALLBACK WHEN THE REFIT IS TOO SMALL
            if len(train_pdf) < int(min_train_row_count_in):
                raise ValueError(f"refit on {session_date} ({train_window_str_in}) has {len(train_pdf)} training rows, below the minimum {int(min_train_row_count_in)}.")
            # THE LAST LABEL CLOCK ACTUALLY USED
            used_known_arr = train_pdf["label_known_ts"].to_numpy()
            last_known_ts = max(get_clock_ts(label_ts) for label_ts in used_known_arr)
            # THE WINDOW START RECORDED ON THE LOG (ALL: THE EARLIEST ROW DATE HANDED TO THE FIT)
            if start_ts is None:
                train_start_date = min(get_clock_ts(row_ts).date() for row_ts in train_pdf["row_ts"])
            else:
                train_start_date = start_ts.date()
            # FIT, TIMED, WITH THE CALLER'S SEED
            fit_start = time.perf_counter()
            previous_model = model
            model = fit_func_in(train_pdf, list(feature_col_list_in), label_col_str_in, int(seed_in))
            fit_seconds = float(time.perf_counter() - fit_start)
            model_id_int += 1
            # HOW FAR THE PREDICTION MOVED ON THIS SESSION'S OWN FEATURES
            prediction_move = np.nan
            if previous_model is not None:
                move_pdf = pd.DataFrame([{column_str: session_row[column_str] for column_str in list(feature_col_list_in)}])
                old_value = float(np.asarray(predict_func_in(previous_model, move_pdf, list(feature_col_list_in)), dtype=float).reshape(-1)[0])
                new_value = float(np.asarray(predict_func_in(model, move_pdf, list(feature_col_list_in)), dtype=float).reshape(-1)[0])
                prediction_move = float(abs(new_value - old_value))
            # LABEL BALANCE IS THE MEAN OF THE LABELS THE FIT SAW
            balance_float = float(np.mean(train_pdf[label_col_str_in].to_numpy(dtype=float)))
            refit_dict_list.append({
                "model_id": model_id_int, "retrain_session": session_date, "decision_ts": decision_ts,
                "train_window": train_window_str_in, "train_start": train_start_date, "rows_used": int(len(train_pdf)),
                "rows_purged": purged_count, "last_label_known_ts": last_known_ts, "label_balance": balance_float,
                "fit_seconds": fit_seconds, "prediction_move": prediction_move,
            })
        # A DECISION BEFORE THE FIRST REFIT HAS NO MODEL
        if model is None:
            raise ValueError(f"no fitted model for decision session {session_date}.")
        # FEATURES MUST BE KNOWABLE AT THIS DECISION (THE POINT-IN-TIME CHECK, NOT A SECOND CLOCK)
        from so.core.point_in_time import check_feature_available_ts
        feature_pdf = pd.DataFrame([{column_str: session_row[column_str] for column_str in list(feature_col_list_in) + ["available_ts"]}])
        check_feature_available_ts(feature_pdf, [decision_ts])
        # PREDICT WITH THE LATEST MODEL
        prediction_arr = np.asarray(predict_func_in(model, feature_pdf, list(feature_col_list_in)), dtype=float).reshape(-1)
        prediction_dict_list.append({"session": session_date, "prediction": float(prediction_arr[0]), "model_id": model_id_int})
    # RETURN THE TWO TABLES
    return {"prediction_pdf": pd.DataFrame(prediction_dict_list), "refit_log_pdf": pd.DataFrame(refit_dict_list)}

# FUNCTION: FIT ONE NAMED WINDOW (MODULE LEVEL SO A PROCESS POOL CAN CALL IT)
def run_named_window_retrain_dict(train_window_str_in, row_pdf_in, feature_col_list_in, label_col_str_in, fit_func_in, predict_func_in,
                                  decision_session_list_in, frequency_str_in, seed_in, min_train_row_count_in, purge_unfinished_label_bool_in):
    """
    Fits one training window. A joblib worker calls this; the seed is the caller's seed.

    Args:
        train_window_str_in (str): Training window
        row_pdf_in (pd.DataFrame): Labelled rows
        feature_col_list_in (list[str]): Feature columns
        label_col_str_in (str): Label column
        fit_func_in, predict_func_in (callable): Fit and predict
        decision_session_list_in (list): Decision sessions
        frequency_str_in (str): Retraining frequency
        seed_in (int): Seed
        min_train_row_count_in (int): Minimum training rows
        purge_unfinished_label_bool_in (bool): Drop unfinished labels

    Returns:
        dict: prediction_pdf, refit_log_pdf
    """
    # THE SAME CALL THE SEQUENTIAL PATH MAKES
    return run_rolling_retrain_dict(row_pdf_in, feature_col_list_in, label_col_str_in, fit_func_in, predict_func_in,
                                    decision_session_list_in, train_window_str_in, frequency_str_in, seed_in,
                                    min_train_row_count_in, purge_unfinished_label_bool_in)

# FUNCTION: FIT EVERY TRAINING WINDOW, OPTIONALLY IN PARALLEL
def run_rolling_retrain_candidate_dict(row_pdf_in, feature_col_list_in, label_col_str_in, fit_func_in, predict_func_in,
                                       decision_session_list_in, train_window_str_list_in, frequency_str_in, seed_in,
                                       min_train_row_count_in, job_count_in=1, purge_unfinished_label_bool_in=True):
    """
    Fits one rolling model per training window. joblib may run the windows in parallel, up to 8 cores. Every window
    receives the same seed_in. The returned predictions do not depend on job_count_in.

    Args:
        row_pdf_in (pd.DataFrame): Labelled rows (see run_rolling_retrain_dict)
        feature_col_list_in (list[str]): Feature columns
        label_col_str_in (str): Label column
        fit_func_in, predict_func_in (callable): Fit and predict
        decision_session_list_in (list): Decision sessions
        train_window_str_list_in (list[str]): Training windows, one candidate each
        frequency_str_in (str): Retraining frequency
        seed_in (int): Seed
        min_train_row_count_in (int): Minimum training rows
        job_count_in (int): Workers (1 runs in this process; capped at 8)
        purge_unfinished_label_bool_in (bool): Drop unfinished labels

    Returns:
        dict: train window -> the dict returned by run_rolling_retrain_dict, in the requested window order
    """
    # CAP THE POOL
    window_list = list(train_window_str_list_in)
    job_count = int(min(max(int(job_count_in), 1), MAX_JOB_COUNT, max(len(window_list), 1)))
    # SEQUENTIAL WHEN ONE WORKER WAS ASKED
    if job_count == 1 or len(window_list) <= 1:
        result_list = [run_named_window_retrain_dict(train_window_str, row_pdf_in, feature_col_list_in, label_col_str_in, fit_func_in, predict_func_in,
                                                     decision_session_list_in, frequency_str_in, seed_in, min_train_row_count_in, purge_unfinished_label_bool_in)
                       for train_window_str in window_list]
    else:
        # PARALLEL ACROSS CANDIDATES; ORDER FOLLOWS THE WINDOW LIST; THE SEED IS NOT A WORKER ID
        from joblib import Parallel, delayed
        result_list = Parallel(n_jobs=job_count, backend="loky")(
            delayed(run_named_window_retrain_dict)(train_window_str, row_pdf_in, feature_col_list_in, label_col_str_in, fit_func_in, predict_func_in,
                                                   decision_session_list_in, frequency_str_in, seed_in, min_train_row_count_in, purge_unfinished_label_bool_in)
            for train_window_str in window_list)
    return {train_window_str: result_dict for train_window_str, result_dict in zip(window_list, result_list)}

"""
Candidate Selection
"""

# FUNCTION: THE CANDIDATE IN FORCE EACH QUARTER, FROM EARLIER QUARTERS ONLY
def get_rolling_candidate_selection_pdf(candidate_pdf_in, key_col_str_list_in, score_col_str_in="excess_return",
                                        pooled_quarter_count_in=None, tie_break_list_in=None):
    """
    The candidate for quarter f is chosen from the last pooled_quarter_count_in completed quarters before f
    (get_pooled_selection_pdf on those quarters, then get_prior_only_pdf). The score is the quarter's return minus
    buy-and-hold. The default tie order prefers the longer training window, then the first key column ascending.
    A protocol passes its own tie_break_list_in to override that order.

    Args:
        candidate_pdf_in (pd.DataFrame): One row per (fold_id, candidate) with the score column
        key_col_str_list_in (list[str]): Columns that identify a candidate
        score_col_str_in (str): Score to maximize (period return minus buy-and-hold)
        pooled_quarter_count_in (int | None): Quarters pooled (None = the shared default, 4)
        tie_break_list_in (list[tuple[str, bool]] | None): Tie order (None = longer training window, then the first key)

    Returns:
        pd.DataFrame: One row per evaluated quarter (fold_id is the quarter the candidate is in force)
    """
    # THE SHARED POOLED RULE AND THE PRIOR-ONLY SHIFT
    from so.core.evaluation import get_pooled_selection_pdf, get_prior_only_pdf
    # THE DEFAULT POOL IS FOUR QUARTERS
    pooled_int = int(config.CANDIDATE_SELECTION_POOLED_QUARTERS_DEFAULT if pooled_quarter_count_in is None else pooled_quarter_count_in)
    # COPY SO A TRAIN-WINDOW LENGTH CAN BE ATTACHED FOR THE TIE
    work_pdf = candidate_pdf_in.copy()
    if "train_window" in work_pdf.columns and "train_window_months" not in work_pdf.columns:
        work_pdf["train_window_months"] = work_pdf["train_window"].map(TRAIN_WINDOW_MONTH_DICT)
    # THE DEFAULT TIE IS THE LONGER WINDOW, THEN A STABLE KEY
    if tie_break_list_in is None:
        tie_break_list = []
        if "train_window_months" in work_pdf.columns:
            tie_break_list.append(("train_window_months", False))
        if key_col_str_list_in:
            tie_break_list.append((key_col_str_list_in[0], True))
    else:
        tie_break_list = list(tie_break_list_in)
    # SELECT ON EACH QUARTER FROM THE QUARTERS UP TO AND INCLUDING IT, THEN SHIFT THE CHOICE ONTO THE NEXT QUARTER
    selection_pdf = get_pooled_selection_pdf(work_pdf, list(key_col_str_list_in), score_col_str_in, pooled_int, tie_break_list)
    return get_prior_only_pdf(work_pdf, selection_pdf, list(key_col_str_list_in))

"""
Reference Fit (deterministic given the seed; used by the parallel check)
"""

# FUNCTION: FIT THE MEAN LABEL
def fit_mean_label_dict(train_pdf_in, feature_col_list_in, label_col_str_in, seed_int_in):
    """
    A deterministic fit: the training mean of the label, plus a normal draw of scale 0 from seed_int_in. The draw keeps
    the seed on the path without moving the number. Two calls with the same seed and the same rows return the same model.

    Args:
        train_pdf_in (pd.DataFrame): Training rows
        feature_col_list_in (list[str]): Unused (the mean does not use features)
        label_col_str_in (str): Label column
        seed_int_in (int): Seed

    Returns:
        dict: prediction (the mean)
    """
    # THE SEED IS CONSUMED SO A WORKER CANNOT SUBSTITUTE ITS OWN GENERATOR
    rng = np.random.default_rng(int(seed_int_in))
    mean_float = float(train_pdf_in[label_col_str_in].to_numpy(dtype=float).mean())
    return {"prediction": mean_float + float(rng.normal(0.0, 0.0))}

# FUNCTION: PREDICT THE FITTED MEAN ON EVERY ROW
def predict_constant_arr(model_in, feature_pdf_in, feature_col_list_in):
    """
    Repeats the fitted mean once per feature row.

    Args:
        model_in (dict): Output of fit_mean_label_dict
        feature_pdf_in (pd.DataFrame): Feature rows
        feature_col_list_in (list[str]): Unused

    Returns:
        np.ndarray: One prediction per row
    """
    # THE SAME NUMBER ON EVERY ROW
    return np.full(len(feature_pdf_in), float(model_in["prediction"]))
