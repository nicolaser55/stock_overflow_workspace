import json
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Holdout Baselines (report only)

The development report and the holdout report share one implementation, on the design:
get_baseline_return_dict. A path whose equity already lies inside the requested span is used unchanged, so the
development numbers stay the numbers that were saved. A wider path is restricted to the span first: activity
(exits, cash, weights, decisions) is counted on that span, and the simulators still index full-length signal
arrays by session position. Random families report the median (np.median, the saved estimator), the 5th and 95th
percentiles, the run count, and how many runs the path's return beats.
"""

# SUFFIXES THAT ARE NOT TOTAL RETURNS THE SUCCESS CRITERIA COMPARE
_STAT_SUFFIX_TUPLE = ("_p05", "_p95", "_count", "_beaten_count", "_beats_share", "_weight", "_list")

# FUNCTION: A TIMESTAMP AS A NEW YORK SESSION DATE
def get_session_date(value_in):
    """
    Converts a date or timestamp to a session date. Aware timestamps are converted to America/New_York first.

    Args:
        value_in: Date or timestamp

    Returns:
        datetime.date: The session date
    """
    # CONVERT, THEN DROP THE CLOCK IN NEW YORK WHEN THE STAMP HAS A ZONE
    stamp = pd.Timestamp(value_in)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("America/New_York")
    return stamp.date()

# FUNCTION: WHETHER EVERY EQUITY DATE LIES INSIDE THE SPAN
def get_equity_inside_span_bool(equity_pdf_in, date1_in, date2_in):
    """
    True when the path's equity dates are all inside the inclusive span. That is the development call: the path was
    simulated on that span, and the saved baselines used it unchanged.

    Args:
        equity_pdf_in (pd.DataFrame): Daily equity with a date column
        date1_in, date2_in: Span

    Returns:
        bool: Every row is inside the span
    """
    # AN EMPTY FRAME HAS NOTHING OUTSIDE THE SPAN
    if equity_pdf_in is None or len(equity_pdf_in) == 0 or "date" not in equity_pdf_in.columns:
        return True
    # COMPARE THE SESSION DATES
    start_date, end_date = get_session_date(date1_in), get_session_date(date2_in)
    date_series = equity_pdf_in["date"].map(get_session_date)
    return bool(((date_series >= start_date) & (date_series <= end_date)).all())

# FUNCTION: KEEP ROWS WHOSE DATE COLUMN LIES INSIDE THE SPAN
def get_span_frame_pdf(frame_pdf_in, date_col_str_in, date1_in, date2_in):
    """
    Rows whose date column falls inside the inclusive span. A missing column or an empty frame is returned as it is.

    Args:
        frame_pdf_in (pd.DataFrame | None): Table
        date_col_str_in (str): Date or timestamp column
        date1_in, date2_in: Span

    Returns:
        pd.DataFrame | None: The rows inside the span
    """
    # NOTHING TO CUT
    if frame_pdf_in is None or len(frame_pdf_in) == 0 or date_col_str_in not in frame_pdf_in.columns:
        return frame_pdf_in
    # KEEP THE SPAN
    start_date, end_date = get_session_date(date1_in), get_session_date(date2_in)
    date_series = frame_pdf_in[date_col_str_in].map(get_session_date)
    return frame_pdf_in.loc[(date_series >= start_date) & (date_series <= end_date)].reset_index(drop=True)

# FUNCTION: SET WEIGHTS OUTSIDE THE SPAN TO NAN
def get_span_weight_arr(weight_arr_in, session_date_list_in, date1_in, date2_in):
    """
    A copy of the weight array. Sessions outside the span become NaN. Sessions inside keep the path's weight.

    Args:
        weight_arr_in (np.ndarray): One weight per session position
        session_date_list_in (list): Session date per position
        date1_in, date2_in: Span

    Returns:
        np.ndarray: The masked weights
    """
    # COPY, THEN CLEAR THE POSITIONS OUTSIDE THE SPAN
    weight_arr = np.array(weight_arr_in, dtype=float, copy=True)
    start_date, end_date = get_session_date(date1_in), get_session_date(date2_in)
    for session_idx, session_date in enumerate(session_date_list_in):
        session_day = get_session_date(session_date)
        if session_idx < len(weight_arr) and (session_day < start_date or session_day > end_date):
            weight_arr[session_idx] = np.nan
    return weight_arr

# FUNCTION: RESTRICT A WIDER PATH TO THE SPAN
def get_span_path_dict(path_dict_in, ohlcv_array_dict_in, date1_in, date2_in):
    """
    The same path when its equity already lies inside the span. Otherwise a shallow copy whose equity, episodes,
    transactions and decision rows are the span, and whose metric fields that the baselines read are recomputed
    from those rows. Full-length signal arrays stay, so a simulator still indexes them by session position.

    Args:
        path_dict_in (dict): Prior-only path
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span

    Returns:
        dict: Path the baseline simulators read
    """
    # THE DEVELOPMENT CALL IS ALREADY THE SPAN
    if path_dict_in is None:
        raise ValueError("the baselines need the prior-only path.")
    equity_pdf = path_dict_in.get("daily_equity_pdf")
    if get_equity_inside_span_bool(equity_pdf, date1_in, date2_in):
        return path_dict_in
    # CUT THE TABLES TO THE SPAN
    span_equity_pdf = get_span_frame_pdf(equity_pdf, "date", date1_in, date2_in)
    span_episode_pdf = get_span_frame_pdf(path_dict_in.get("episode_pdf"), "exit_ts", date1_in, date2_in)
    span_transaction_pdf = get_span_frame_pdf(path_dict_in.get("transaction_pdf"), "sell_ts", date1_in, date2_in)
    span_decision_pdf = get_span_frame_pdf(path_dict_in.get("decision_pdf"), "decision_ts", date1_in, date2_in)
    # RECOMPUTE THE ACTIVITY THE MATCHED BASELINES READ
    metric_dict = dict(path_dict_in.get("metric_dict") or {})
    if span_equity_pdf is not None and len(span_equity_pdf) > 1 and "in_position" in span_equity_pdf.columns:
        metric_dict["cash_session_pct"] = float((~span_equity_pdf["in_position"].iloc[:-1].astype(bool)).mean())
    if span_equity_pdf is not None and len(span_equity_pdf) > 1 and "weight" in span_equity_pdf.columns:
        metric_dict["mean_weight"] = float(span_equity_pdf["weight"].to_numpy(dtype=float)[:-1].mean())
    if span_transaction_pdf is not None and "exit_reason" in getattr(span_transaction_pdf, "columns", []):
        metric_dict["signal_exit_count"] = int((span_transaction_pdf["exit_reason"] == "SIGNAL").sum())
        metric_dict["stop_count"] = int((span_transaction_pdf["exit_reason"] == "STOP").sum())
    # THE PATH'S GROWTH OVER THE SPAN, SAME ROUNDING AS THE SIMULATOR'S TOTAL RETURN
    full_pdf = equity_pdf.copy()
    full_pdf["_day"] = full_pdf["date"].map(get_session_date)
    start_date = get_session_date(date1_in)
    prior_pdf = full_pdf[full_pdf["_day"] < start_date]
    enter_float = float(prior_pdf["equity"].iloc[-1]) if len(prior_pdf) else float(config.INITIAL_CAPITAL)
    last_float = float(span_equity_pdf["equity"].iloc[-1]) if span_equity_pdf is not None and len(span_equity_pdf) else enter_float
    metric_dict["total_return"] = round(last_float / enter_float - 1.0, 8) if enter_float else np.nan
    # COPY THE PATH AND REPLACE THE SPAN FIELDS. SIGNAL ARRAYS STAY THE FULL-LENGTH ONES
    span_dict = dict(path_dict_in)
    span_dict["daily_equity_pdf"] = span_equity_pdf
    span_dict["metric_dict"] = metric_dict
    if "episode_pdf" in path_dict_in:
        span_dict["episode_pdf"] = span_episode_pdf if span_episode_pdf is not None else path_dict_in["episode_pdf"].iloc[0:0]
    if "transaction_pdf" in path_dict_in and span_transaction_pdf is not None:
        span_dict["transaction_pdf"] = span_transaction_pdf
    if "decision_pdf" in path_dict_in and span_decision_pdf is not None:
        span_dict["decision_pdf"] = span_decision_pdf
    if "target_decision_arr" in path_dict_in and ohlcv_array_dict_in is not None:
        span_dict["target_decision_arr"] = get_span_weight_arr(path_dict_in["target_decision_arr"], ohlcv_array_dict_in["session_date_list"], date1_in, date2_in)
    return span_dict

# FUNCTION: MEDIAN, PERCENTILES AND THE COUNTS OF ONE RANDOM FAMILY
def get_random_family_stat_dict(family_str_in, return_list_in, path_return_float_in):
    """
    The median is np.median, which is the estimator the development reports saved. The 5th and 95th percentiles use
    np.percentile. The beaten count is how many runs have a strictly smaller return than the path, which is the
    count behind the share the stopping rules print.

    Args:
        family_str_in (str): Name prefix, without a trailing underscore
        return_list_in (list): One total return per run
        path_return_float_in (float): Path total return on the same span

    Returns:
        dict: median, p05, p95, count, beaten_count
    """
    # THE EMPTY FAMILY HAS NOTHING TO SUMMARISE
    return_arr = np.asarray(list(return_list_in), dtype=float)
    if len(return_arr) == 0:
        return {f"{family_str_in}_median": np.nan, f"{family_str_in}_p05": np.nan, f"{family_str_in}_p95": np.nan,
                f"{family_str_in}_count": 0, f"{family_str_in}_beaten_count": 0}
    # THE SAVED MEDIAN, THE PERCENTILES, AND THE STRICT COUNT
    beaten_count = int(np.sum(return_arr < float(path_return_float_in)))
    return {f"{family_str_in}_median": float(np.median(return_arr)),
            f"{family_str_in}_p05": float(np.percentile(return_arr, 5)),
            f"{family_str_in}_p95": float(np.percentile(return_arr, 95)),
            f"{family_str_in}_count": int(len(return_arr)),
            f"{family_str_in}_beaten_count": beaten_count}

# FUNCTION: THE RETURNS THE SUCCESS CRITERIA COMPARE
def get_comparison_baseline_dict(baseline_dict_in, key_list_in=None):
    """
    The named comparison keys when the design lists them and they are present. Otherwise every scalar that is not a
    percentile, a count, a share, a weight or a list. Counts are not returns, so they are not beaten.

    Args:
        baseline_dict_in (dict): Baseline name -> value
        key_list_in (list | None): Keys the development report passes to the success criteria

    Returns:
        dict: Name -> total return
    """
    # THE DESIGN'S LIST WINS
    if key_list_in:
        return {key_str: baseline_dict_in[key_str] for key_str in key_list_in if key_str in baseline_dict_in}
    # DROP THE STATISTICS THAT ARE NOT TOTAL RETURNS
    return_dict = {}
    for key_str, value in baseline_dict_in.items():
        if isinstance(value, (list, tuple, dict)) or isinstance(value, (bool, np.bool_)):
            continue
        if any(str(key_str).endswith(suffix_str) for suffix_str in _STAT_SUFFIX_TUPLE):
            continue
        if isinstance(value, (int, float, np.integer, np.floating)):
            return_dict[key_str] = value
    return return_dict

# FUNCTION: JSON OF THE SCALAR BASELINE FIELDS
def get_baseline_json_str(baseline_dict_in):
    """
    The scalar baseline fields as JSON. Lists stay out of the ledger cell. Non-finite floats are null.

    Args:
        baseline_dict_in (dict): Baseline name -> value

    Returns:
        str: JSON object
    """
    # KEEP SCALARS ONLY
    scalar_dict = {}
    for key_str, value in baseline_dict_in.items():
        if isinstance(value, (list, tuple, dict)):
            continue
        if isinstance(value, (bool, np.bool_)):
            scalar_dict[key_str] = bool(value)
        elif isinstance(value, (int, np.integer)):
            scalar_dict[key_str] = int(value)
        elif isinstance(value, (float, np.floating)):
            scalar_dict[key_str] = float(value) if np.isfinite(value) else None
        else:
            scalar_dict[key_str] = value
    return json.dumps(scalar_dict)
