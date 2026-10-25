import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE PATHS
from so import config, paths
# IMPORT THE LOCKED CSV APPEND (NEW ROWS ONLY; THE EXISTING LEDGER IS NOT REWRITTEN)
from so.core.csv_append import append_csv_record_pdf

"""
Rolling 12-Month Holdout (Nicolas, 2026-10-11)

The holdout result is the design's frozen prior-only path from its development start, continued without interruption
through the holdout window: same code, same decision bar (15:58) and fill (15:59), same costs, dead band and cash
rules, same candidate periods and selection rule, selection history and position carried over from development. Only
the holdout sessions are reported. Every decision uses only information available at its decision bar.

The truncation test checks that. For each month-end in the window it drops the sessions after the cut, and, separately,
overwrites every bar strictly after that session's decision bar (the fill bar through the end of the data) while leaving
the session structure unchanged. The second check does not move the decision bar. Every other registered source is cut
and perturbed the same way through so.core.point_in_time.DataContext: rows with available_ts after the cut session's
last bar are dropped, and feature values with available_ts after the decision are perturbed. Labels are not perturbed.

The holdout is the last HOLDOUT_WINDOW_MONTHS calendar months of the data, ending at the latest session present when
the window is opened. It replaces the per-fold 3-month test windows and the fixed untouched window 2026-05-14 ->
2026-08-13.

Once opened, the window is frozen: new downloads do not move it. Sessions after its end are forward data. slide
moves the window to the latest 12 months with no 6-month minimum and no typed confirmation; roll stays the
non-overlapping successor. A design hash is evaluated once, then only the sessions after its latest reported_end
when the active window ends later and at least HOLDOUT_MIN_FORWARD_SESSIONS new sessions exist. At most
HOLDOUT_EVALUATION_BUDGET ledger rows, any status, may have a window that overlaps the active window. Only
scripts/holdout_evaluate.py, run by Nicolas, may read the window, and it reads that window from the quarantine root
(SO_QUARANTINE_PATH), not from the development view. Development code stops at get_development_end_date (the session
an embargo before the window start) and reads only SO_DATA_PATH.

records/holdout_windows.csv and records/holdout_evaluations.csv are versioned (dates and summary metrics are not
secret). Daily paths are written only under SO_HOLDOUT_PATH, which has no default.
"""

# DEFINE THE REGISTRY COLUMNS
WINDOW_COLUMN_LIST = ["window_id", "status", "start", "end", "session_count", "months_covered", "opened_ts", "opened_by",
                      "data_last_session_at_open", "retired_ts", "retire_reason"]
# DEFINE THE LEDGER COLUMNS
EVALUATION_COLUMN_LIST = ["window_id", "design_id", "experiment_name", "design_hash", "commit", "evaluated_ts", "status",
                          "reported_start", "reported_end", "total_return",
                          "buy_hold_total_return", "annualized_log_excess", "log_excess_ci_low", "log_excess_ci_high",
                          "in_market_pct", "sharpe_ratio", "max_drawdown", "mde", "primary_pass", "secondary_pass",
                          "comparable_pass", "baselines_beaten", "baseline_returns", "carried_weight", "holdout_candidates", "sources_read",
                          "retrain_frequency", "train_window_candidates", "holdout_refit_count", "average_share_purged",
                          "turnover", "candidate_switches",
                          "unread_start", "unread_session_count", "unread_total_return", "unread_buy_hold_total_return"]
# DEFINE THE MESSAGE WHEN NO WINDOW IS REGISTERED
NO_WINDOW_MESSAGE_STR = "no holdout window registered: Nicolas must run scripts/holdout_window.py open"
# DEFINE THE RUNNER FLAG (SET INSIDE run_holdout_dict, AND WHILE THE QUARANTINE WINDOW-END LOAD IS IN PROGRESS)
_RUNNER_ACTIVE_BOOL = False
# DEFINE THE MESSAGE WHEN THE DEVELOPMENT VIEW STAMP IS MISSING OR DOES NOT MATCH THE ACTIVE WINDOW
VIEW_STALE_MESSAGE_STR = "development view is missing or stale: Nicolas must run the refresh"
# DEFINE THE LABEL ON THE NEVER-READ TAIL OF A HOLDOUT WINDOW (AFTER PRIOR_READ_LAST_DATE_STR)
UNREAD_SANITY_CHECK_STR = "sanity check: too few sessions to pass or fail a design"

"""
Dates And The Registry
"""

# FUNCTION: CONVERT A VALUE TO A DATE
def get_date(value_in):
    """
    Converts a date-like value to datetime.date.

    Args:
        value_in (datetime.date | str): Date

    Returns:
        datetime.date: The date
    """
    # RETURN THE DATE
    return pd.Timestamp(value_in).date()

# FUNCTION: READ THE HOLDOUT REGISTRY
def read_holdout_window_pdf(file_path_str_in=None):
    """
    Reads the holdout registry. A missing file is an empty table.

    Args:
        file_path_str_in (str | None): Registry CSV (None = paths.HOLDOUT_WINDOWS_FILE_PATH_STR)

    Returns:
        pd.DataFrame: One row per window
    """
    # COLLECT THE PATH
    file_path_str = file_path_str_in or paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    # RETURN AN EMPTY TABLE WHEN THE FILE DOES NOT EXIST
    if not os.path.isfile(file_path_str):
        return pd.DataFrame(columns=WINDOW_COLUMN_LIST)
    # READ THE REGISTRY AND PARSE THE DATES
    window_pdf = pd.read_csv(file_path_str)
    for col_str in ["start", "end", "data_last_session_at_open"]:
        if col_str in window_pdf.columns:
            window_pdf[col_str] = pd.to_datetime(window_pdf[col_str]).dt.date
    # KEEP EMPTY TEXT COLUMNS AS TEXT (A BLANK retired_ts MUST NOT BECOME A NUMBER)
    for col_str in ["window_id", "status", "opened_ts", "opened_by", "retired_ts", "retire_reason"]:
        if col_str in window_pdf.columns:
            window_pdf[col_str] = window_pdf[col_str].fillna("").astype(str)
    # RETURN THE TABLE
    return window_pdf

# FUNCTION: WRITE THE HOLDOUT REGISTRY
def write_holdout_window_pdf(window_pdf_in, file_path_str_in=None):
    """
    Writes the holdout registry (the one allowed edit of a retired row is retired_ts and retire_reason).

    Args:
        window_pdf_in (pd.DataFrame): Registry rows
        file_path_str_in (str | None): Registry CSV

    Returns:
        None
    """
    # WRITE THE TABLE
    file_path_str = file_path_str_in or paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    os.makedirs(os.path.dirname(file_path_str), exist_ok=True)
    window_pdf_in.to_csv(file_path_str, index=False)

# FUNCTION: GET THE ACTIVE HOLDOUT WINDOW
def get_active_holdout_window_dict(missing_ok_bool_in=False, file_path_str_in=None):
    """
    Returns the single active window. Zero active windows raise the registry error unless missing_ok_bool_in.

    Args:
        missing_ok_bool_in (bool): Return None when no window is registered (internal guards only)
        file_path_str_in (str | None): Registry CSV

    Returns:
        dict | None: The active row
    """
    # READ THE REGISTRY AND KEEP THE ACTIVE ROWS
    window_pdf = read_holdout_window_pdf(file_path_str_in)
    active_pdf = window_pdf[window_pdf["status"] == "active"] if len(window_pdf) else window_pdf
    # RAISE WHEN THE REGISTRY IS AMBIGUOUS
    if len(active_pdf) > 1:
        raise ValueError("❌ More than one active holdout window is registered.")
    # RETURN NONE OR RAISE WHEN NOTHING IS ACTIVE
    if len(active_pdf) == 0:
        if missing_ok_bool_in:
            return None
        raise ValueError(NO_WINDOW_MESSAGE_STR)
    # RETURN THE ACTIVE ROW
    return active_pdf.iloc[0].to_dict()

# FUNCTION: COUNT THE CALENDAR MONTHS BETWEEN TWO DATES
def get_months_covered_float(start_date_in, end_date_in):
    """
    Months covered by a window: the day span divided by the mean calendar-month length.

    Args:
        start_date_in, end_date_in (datetime.date | str): Inclusive bounds

    Returns:
        float: Months covered
    """
    # RETURN THE SPAN IN MONTHS
    return (pd.Timestamp(end_date_in) - pd.Timestamp(start_date_in)).days / 30.436875

# FUNCTION: COMPUTE A HOLDOUT WINDOW FROM A SESSION LIST
def compute_holdout_window_dict(session_date_list_in, window_months_in=config.HOLDOUT_WINDOW_MONTHS, start_after_date_in=None):
    """
    End = last session. Start = first session strictly after (end - window_months calendar months), snapped with
    so.core.schedule.get_first_session_idx_after. If start_after_date_in is given, start is at least the first session
    strictly after that date. Pure: no file access.

    Args:
        session_date_list_in (list[datetime.date]): Sorted session dates
        window_months_in (int): Calendar months
        start_after_date_in (datetime.date | str | None): The new window must start after this date (a roll)

    Returns:
        dict: start, end, session_count, months_covered
    """
    # IMPORT THE SESSION SNAP (THE SAME ONE THE WALK-FORWARD SCHEDULE USES)
    from so.core.schedule import get_first_session_idx_after
    # REQUIRE AT LEAST ONE SESSION
    if len(session_date_list_in) == 0:
        raise ValueError("❌ No sessions to locate a holdout window.")
    # SNAP THE END AND THE CALENDAR START
    session_date_arr = np.array(pd.to_datetime(pd.Series(session_date_list_in)).dt.date.tolist(), dtype="datetime64[D]")
    end_date = get_date(session_date_list_in[-1])
    start_exclusive_date = (pd.Timestamp(end_date) - pd.DateOffset(months=int(window_months_in))).date()
    start_idx = get_first_session_idx_after(session_date_arr, start_exclusive_date)
    # MOVE THE START PAST A RETIRED WINDOW WHEN A ROLL ASKS FOR IT
    if start_after_date_in is not None:
        start_idx = max(start_idx, get_first_session_idx_after(session_date_arr, get_date(start_after_date_in)))
    # REFUSE A START THAT FALLS OFF THE END OF THE CALENDAR
    if start_idx >= len(session_date_list_in):
        raise ValueError("❌ The holdout start is after the last session.")
    start_date = get_date(session_date_list_in[start_idx])
    # COUNT THE SESSIONS INSIDE THE WINDOW
    session_count = int(sum(start_date <= get_date(session_date) <= end_date for session_date in session_date_list_in))
    # RETURN THE WINDOW
    return {"start": start_date, "end": end_date, "session_count": session_count,
            "months_covered": float(get_months_covered_float(start_date, end_date))}

# FUNCTION: GET THE LATEST RAW SESSION AND CHECK THE PIPELINE
def get_latest_session_date(raw_path_str_in=None, tsday_file_path_str_in=None):
    """
    The last New York session of the raw SPY bars (so.core.raw_data, after the bad-tick correction already applied to
    the files) and the last session of the step06 TSDAY table. If they differ, or the table is missing, raise
    "pipeline is stale: re-run pipeline steps 00-06".

    Args:
        raw_path_str_in (str | None): Raw SPY folder (None = the data folder)
        tsday_file_path_str_in (str | None): Step06 CSV (None = TSDAY_data.csv)

    Returns:
        datetime.date: The latest session
    """
    # IMPORT THE RAW LOADER HERE (IT CALLS THIS MODULE'S GUARD)
    from so.core.raw_data import get_complete_ohlcv_pdf
    # READ THE RAW SESSION DATES WITHOUT THE HOLDOUT CUT (OPENING A WINDOW MUST SEE THE LATEST SESSION)
    ohlcv_pdf = get_complete_ohlcv_pdf(raw_path_str_in, enforce_holdout_bool_in=False)
    raw_last_date = get_date(ohlcv_pdf["date"].max())
    # READ THE LAST DATE OF THE STEP06 TABLE
    tsday_file_path_str = tsday_file_path_str_in or f"{paths.LOCAL_TSDAY_DATA_FILE_PATH_STR}TSDAY_data.csv"
    if not os.path.isfile(tsday_file_path_str):
        raise ValueError("pipeline is stale: re-run pipeline steps 00-06")
    tsday_last_date = get_date(pd.read_csv(tsday_file_path_str, usecols=["date"])["date"].max())
    # REFUSE A STALE PIPELINE
    if raw_last_date != tsday_last_date:
        raise ValueError("pipeline is stale: re-run pipeline steps 00-06")
    # RETURN THE LATEST SESSION
    return raw_last_date

# FUNCTION: GET THE ORDERED SESSION DATES OF THE RAW DATA
def get_raw_session_date_list(raw_path_str_in=None):
    """
    Sorted unique New York session dates of the raw SPY bars, including forward data (dates only).

    Args:
        raw_path_str_in (str | None): Raw SPY folder

    Returns:
        list[datetime.date]: Session dates
    """
    # IMPORT THE RAW LOADER HERE
    from so.core.raw_data import get_complete_ohlcv_pdf
    # READ AND RETURN THE DATES
    ohlcv_pdf = get_complete_ohlcv_pdf(raw_path_str_in, enforce_holdout_bool_in=False)
    return sorted(set(ohlcv_pdf["date"].tolist()))

# FUNCTION: APPEND AN ACTIVE WINDOW
def open_holdout_window_dict(session_date_list_in, confirm_str_in, opened_by_str_in="nicolas", file_path_str_in=None):
    """
    Appends an active window computed from the session list. Requires no active window and the typed confirmation
    "OPEN <start> <end>".

    Args:
        session_date_list_in (list[datetime.date]): Sessions used to locate the window
        confirm_str_in (str): Typed confirmation
        opened_by_str_in (str): Who opened it
        file_path_str_in (str | None): Registry CSV

    Returns:
        dict: The appended row
    """
    # REFUSE A SECOND ACTIVE WINDOW
    if get_active_holdout_window_dict(missing_ok_bool_in=True, file_path_str_in=file_path_str_in) is not None:
        raise ValueError("❌ An active holdout window is already registered.")
    # COMPUTE THE WINDOW AND CHECK THE CONFIRMATION
    window_dict = compute_holdout_window_dict(session_date_list_in)
    expected_str = f"OPEN {window_dict['start']} {window_dict['end']}"
    if confirm_str_in != expected_str:
        raise ValueError(f"❌ Confirmation must be exactly: {expected_str}")
    # BUILD THE ROW
    row_dict = {"window_id": f"w{window_dict['start']:%Y%m%d}_{window_dict['end']:%Y%m%d}", "status": "active",
                "start": window_dict["start"], "end": window_dict["end"], "session_count": window_dict["session_count"],
                "months_covered": round(window_dict["months_covered"], 4), "opened_ts": datetime.now().isoformat(timespec="seconds"),
                "opened_by": opened_by_str_in, "data_last_session_at_open": get_date(session_date_list_in[-1]),
                "retired_ts": "", "retire_reason": ""}
    # APPEND THE ROW (AN EMPTY REGISTRY IS REPLACED; IT IS NOT CONCATENATED)
    window_pdf = read_holdout_window_pdf(file_path_str_in)
    row_pdf = pd.DataFrame([row_dict])
    write_holdout_window_pdf(row_pdf if len(window_pdf) == 0 else pd.concat([window_pdf, row_pdf], ignore_index=True), file_path_str_in)
    # RETURN THE ROW
    return row_dict

# FUNCTION: RETIRE THE ACTIVE WINDOW AND OPEN THE NEXT ONE
def roll_holdout_window_dict(session_date_list_in, reason_str_in, confirm_str_in, allow_short_bool_in=False, file_path_str_in=None):
    """
    Retires the active window (reason required; retired_ts and retire_reason are filled once) and opens the next one
    with start_after_date_in = the retired end. A span shorter than HOLDOUT_MIN_WINDOW_MONTHS is refused unless
    allow_short_bool_in. The confirmation is "OPEN <start> <end>" of the new window. Nothing is written if either
    check fails.

    Args:
        session_date_list_in (list[datetime.date]): Sessions available now
        reason_str_in (str): Why the window is retired
        confirm_str_in (str): Typed confirmation of the new window
        allow_short_bool_in (bool): Accept a span shorter than the minimum
        file_path_str_in (str | None): Registry CSV

    Returns:
        dict: The new active row
    """
    # REQUIRE A REASON AND AN ACTIVE WINDOW
    if not str(reason_str_in).strip():
        raise ValueError("❌ A roll needs a retire reason.")
    active_dict = get_active_holdout_window_dict(file_path_str_in=file_path_str_in)
    # COMPUTE THE NEXT WINDOW BEFORE WRITING ANYTHING
    window_dict = compute_holdout_window_dict(session_date_list_in, start_after_date_in=active_dict["end"])
    if window_dict["months_covered"] < config.HOLDOUT_MIN_WINDOW_MONTHS and not allow_short_bool_in:
        raise ValueError(f"❌ The next window covers {window_dict['months_covered']:.2f} months, under the minimum of {config.HOLDOUT_MIN_WINDOW_MONTHS}.")
    expected_str = f"OPEN {window_dict['start']} {window_dict['end']}"
    if confirm_str_in != expected_str:
        raise ValueError(f"❌ Confirmation must be exactly: {expected_str}")
    # RETIRE THE ACTIVE ROW (ONLY retired_ts, retire_reason AND status)
    window_pdf = read_holdout_window_pdf(file_path_str_in)
    active_idx = window_pdf.index[window_pdf["status"] == "active"][0]
    window_pdf.loc[active_idx, "status"] = "retired"
    window_pdf.loc[active_idx, "retired_ts"] = datetime.now().isoformat(timespec="seconds")
    window_pdf.loc[active_idx, "retire_reason"] = reason_str_in
    # APPEND THE NEW ACTIVE ROW AND WRITE ONCE
    row_dict = {"window_id": f"w{window_dict['start']:%Y%m%d}_{window_dict['end']:%Y%m%d}", "status": "active",
                "start": window_dict["start"], "end": window_dict["end"], "session_count": window_dict["session_count"],
                "months_covered": round(window_dict["months_covered"], 4), "opened_ts": datetime.now().isoformat(timespec="seconds"),
                "opened_by": "nicolas", "data_last_session_at_open": get_date(session_date_list_in[-1]),
                "retired_ts": "", "retire_reason": ""}
    write_holdout_window_pdf(pd.concat([window_pdf, pd.DataFrame([row_dict])], ignore_index=True), file_path_str_in)
    # RETURN THE NEW ROW
    return row_dict

# FUNCTION: SLIDE THE ACTIVE WINDOW TO THE LATEST TWELVE MONTHS
def slide_holdout_window_dict(session_date_list_in, reason_str_in, file_path_str_in=None):
    """
    Retires the active window and opens the latest HOLDOUT_WINDOW_MONTHS window (compute_holdout_window_dict, no
    start_after, no 6-month minimum, no typed confirmation). A no-op when that window equals the active one. Raises
    when the new start is not after the old start. Nothing is written if the start check fails.

    Args:
        session_date_list_in (list[datetime.date]): Sessions available now
        reason_str_in (str): Why the window is retired
        file_path_str_in (str | None): Registry CSV

    Returns:
        dict: The active row (unchanged on a no-op, otherwise the new row)
    """
    # REQUIRE A REASON AND AN ACTIVE WINDOW
    if not str(reason_str_in).strip():
        raise ValueError("❌ A slide needs a retire reason.")
    active_dict = get_active_holdout_window_dict(file_path_str_in=file_path_str_in)
    # THE LATEST TWELVE MONTHS, WITH NO MINIMUM AND NO START_AFTER
    window_dict = compute_holdout_window_dict(session_date_list_in)
    # THE SAME BOUNDS ARE A NO-OP
    if get_date(window_dict["start"]) == get_date(active_dict["start"]) and get_date(window_dict["end"]) == get_date(active_dict["end"]):
        return active_dict
    # A START THAT DOES NOT MOVE FORWARD IS REFUSED BEFORE ANY WRITE
    if get_date(window_dict["start"]) <= get_date(active_dict["start"]):
        raise ValueError("❌ The new holdout start is not after the active start.")
    # RETIRE THE ACTIVE ROW (ONLY retired_ts, retire_reason AND status)
    window_pdf = read_holdout_window_pdf(file_path_str_in)
    active_idx = window_pdf.index[window_pdf["status"] == "active"][0]
    window_pdf.loc[active_idx, "status"] = "retired"
    window_pdf.loc[active_idx, "retired_ts"] = datetime.now().isoformat(timespec="seconds")
    window_pdf.loc[active_idx, "retire_reason"] = reason_str_in
    # APPEND THE NEW ACTIVE ROW AND WRITE ONCE
    row_dict = {"window_id": f"w{window_dict['start']:%Y%m%d}_{window_dict['end']:%Y%m%d}", "status": "active",
                "start": window_dict["start"], "end": window_dict["end"], "session_count": window_dict["session_count"],
                "months_covered": round(window_dict["months_covered"], 4), "opened_ts": datetime.now().isoformat(timespec="seconds"),
                "opened_by": "slide", "data_last_session_at_open": get_date(session_date_list_in[-1]),
                "retired_ts": "", "retire_reason": ""}
    write_holdout_window_pdf(pd.concat([window_pdf, pd.DataFrame([row_dict])], ignore_index=True), file_path_str_in)
    # RETURN THE NEW ROW
    return row_dict

# FUNCTION: COUNT SESSIONS OF FORWARD DATA AFTER THE ACTIVE WINDOW
def get_forward_session_count(session_date_list_in, file_path_str_in=None):
    """
    How many sessions are strictly after the active window's end. Counts only.

    Args:
        session_date_list_in (list[datetime.date]): Session dates
        file_path_str_in (str | None): Registry CSV

    Returns:
        int: Forward session count
    """
    # COUNT THE SESSIONS AFTER THE END
    end_date = get_date(get_active_holdout_window_dict(file_path_str_in=file_path_str_in)["end"])
    return int(sum(get_date(session_date) > end_date for session_date in session_date_list_in))

"""
Development Boundary And Guards
"""

# FUNCTION: GET THE LAST DEVELOPMENT SESSION
def get_development_end_date(embargo_sessions_in, session_date_list_in):
    """
    The session embargo_sessions_in sessions before the active window's start (index of the start minus the embargo).
    embargo_sessions_in is required and must be at least 1 (the experiment's label horizon).

    Args:
        embargo_sessions_in (int): Sessions of embargo
        session_date_list_in (list[datetime.date]): Sorted session dates that include the window start

    Returns:
        datetime.date: Development end
    """
    # REQUIRE AN EMBARGO
    if embargo_sessions_in is None or int(embargo_sessions_in) < 1:
        raise ValueError("❌ embargo_sessions_in is required and must be at least 1.")
    # LOCATE THE WINDOW START ON THE CALENDAR
    start_date = get_date(get_active_holdout_window_dict()["start"])
    session_date_list = [get_date(session_date) for session_date in session_date_list_in]
    start_idx = session_date_list.index(start_date)
    end_idx = start_idx - int(embargo_sessions_in)
    # REFUSE AN EMBARGO THAT FALLS OFF THE START OF THE CALENDAR
    if end_idx < 0:
        raise ValueError("❌ The embargo reaches before the first session.")
    # RETURN THE DEVELOPMENT END
    return session_date_list[end_idx]


# FUNCTION: SET THE HOLDOUT RUNNER FLAG
def set_runner_active_bool(active_bool_in):
    """
    Sets the runner-scope flag so the window itself is readable and the day after it is not.

    Args:
        active_bool_in (bool): True while a holdout evaluation is running

    Returns:
        None
    """
    # STORE THE FLAG FOR THE LOADERS AND THE BOUNDARY
    global _RUNNER_ACTIVE_BOOL
    _RUNNER_ACTIVE_BOOL = bool(active_bool_in)

# FUNCTION: GET THE DATE A REPLAY OR A LOADER MAY NOT REACH
def get_replay_boundary_date(pinned_date_in=None):
    """
    The first date that must not be read.
    Runner: the day after the window end (the window itself is allowed; forward data is not).
    No window and a passed date: that date (tests that pass their own cap).
    An active window: the earlier of the passed date and the window start.

    Args:
        pinned_date_in (datetime.date | str | None): Optional extra cap passed by the caller

    Returns:
        datetime.date: Boundary (dates on or after it are refused)
    """
    # INSIDE THE RUNNER THE QUARANTINE STARTS THE DAY AFTER THE WINDOW
    if _RUNNER_ACTIVE_BOOL:
        return get_date(get_active_holdout_window_dict()["end"]) + timedelta(days=1)
    # WITHOUT A WINDOW, A PASSED DATE IS THE CAP
    window_dict = get_active_holdout_window_dict(missing_ok_bool_in=True)
    if window_dict is None:
        if pinned_date_in is None:
            raise ValueError(NO_WINDOW_MESSAGE_STR)
        return get_date(pinned_date_in)
    # WITH A WINDOW, USE THE EARLIER OF THE PASSED DATE AND THE WINDOW START
    start_date = get_date(window_dict["start"])
    if pinned_date_in is None:
        return start_date
    return min(get_date(pinned_date_in), start_date)


# FUNCTION: CHECK THE DEVELOPMENT VIEW STAMP
def check_development_view():
    """
    Reads VIEW.json in the SO_DATA_PATH root and requires its window_start to equal the active registry start.
    A missing file, an unreadable file, or a different start raises. The quarantine root is not consulted.

    Returns:
        bool: True when the stamp matches the active window
    """
    # THE STAMP LIVES IN THE DEVELOPMENT VIEW, NOT IN THE QUARANTINE
    view_path_str = paths.get_data_root_str() + "VIEW.json"
    # A MISSING STAMP IS THE REFRESH ERROR
    if not os.path.isfile(view_path_str):
        raise ValueError(VIEW_STALE_MESSAGE_STR)
    # PARSE window_start. A BROKEN FILE IS THE SAME REFRESH ERROR
    try:
        with open(view_path_str, "r", encoding="utf-8") as view_file:
            view_dict = json.load(view_file)
        stamped_date = get_date(view_dict["window_start"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise ValueError(VIEW_STALE_MESSAGE_STR)
    # THE ACTIVE WINDOW SUPPLIES THE DATE THE STAMP MUST MATCH (A MISSING WINDOW KEEPS ITS OWN ERROR)
    active_date = get_date(get_active_holdout_window_dict()["start"])
    # A STAMP FOR A DIFFERENT WINDOW IS STALE
    if stamped_date != active_date:
        raise ValueError(VIEW_STALE_MESSAGE_STR)
    return True

"""
Evaluation Ledger And Preconditions
"""

# FUNCTION: READ THE EVALUATION LEDGER
def read_holdout_evaluation_pdf(file_path_str_in=None):
    """
    Reads the evaluation ledger. A missing file is an empty table.

    Args:
        file_path_str_in (str | None): Ledger CSV

    Returns:
        pd.DataFrame: One row per evaluation
    """
    # RETURN AN EMPTY TABLE WHEN THE FILE DOES NOT EXIST
    file_path_str = file_path_str_in or paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR
    if not os.path.isfile(file_path_str):
        return pd.DataFrame(columns=EVALUATION_COLUMN_LIST)
    # RETURN THE LEDGER
    return pd.read_csv(file_path_str)

# FUNCTION: WHETHER TWO DATE SPANS OVERLAP
def get_span_overlap_bool(start1_in, end1_in, start2_in, end2_in):
    """
    True when the inclusive spans overlap.

    Args:
        start1_in, end1_in, start2_in, end2_in: Inclusive bounds

    Returns:
        bool: Overlap
    """
    # TWO CLOSED INTERVALS OVERLAP WHEN EACH STARTS ON OR BEFORE THE OTHER END
    return get_date(start1_in) <= get_date(end2_in) and get_date(start2_in) <= get_date(end1_in)

# FUNCTION: LEDGER ROWS WHOSE WINDOW OVERLAPS THE ACTIVE WINDOW
def get_overlapping_evaluation_pdf(ledger_pdf_in, window_dict_in, file_path_str_in=None):
    """
    Ledger rows of any status whose registry window overlaps window_dict_in. A ledger window_id that is not in the
    registry is counted (the conservative reading).

    Args:
        ledger_pdf_in (pd.DataFrame): Ledger
        window_dict_in (dict): Active window
        file_path_str_in (str | None): Registry CSV

    Returns:
        pd.DataFrame: Overlapping rows
    """
    # NOTHING OVERLAPS AN EMPTY LEDGER
    if ledger_pdf_in is None or len(ledger_pdf_in) == 0:
        return ledger_pdf_in if ledger_pdf_in is not None else pd.DataFrame(columns=EVALUATION_COLUMN_LIST)
    # MAP EACH WINDOW_ID TO ITS REGISTERED BOUNDS
    registry_pdf = read_holdout_window_pdf(file_path_str_in)
    bound_dict = {str(row.window_id): (get_date(row.start), get_date(row.end))
                  for row in registry_pdf.itertuples(index=False)} if len(registry_pdf) else {}
    active_start, active_end = get_date(window_dict_in["start"]), get_date(window_dict_in["end"])
    keep_idx_list = []
    for row_idx, row in ledger_pdf_in.iterrows():
        bound_tup = bound_dict.get(str(row["window_id"]))
        # A MISSING REGISTRY ROW IS COUNTED, NOT DROPPED
        if bound_tup is None or get_span_overlap_bool(bound_tup[0], bound_tup[1], active_start, active_end):
            keep_idx_list.append(row_idx)
    return ledger_pdf_in.loc[keep_idx_list]


# FUNCTION: WHETHER A PATH IS INSIDE A ROOT
def get_path_inside_bool(path_str_in, root_str_in):
    """
    True when path_str_in is the root or a file inside it.

    Args:
        path_str_in (str): File or folder
        root_str_in (str): Root folder

    Returns:
        bool: Inside the root
    """
    # COMPARE THE ABSOLUTE PATHS (DIFFERENT DRIVES ARE NOT INSIDE)
    try:
        return os.path.commonpath([os.path.abspath(path_str_in), os.path.abspath(root_str_in)]) == os.path.abspath(root_str_in)
    except ValueError:
        return False

# FUNCTION: CHECK THE EVALUATION TOKEN
def check_evaluation_token_bool(token_file_path_str_in):
    """
    Raises unless SO_HOLDOUT_EVALUATION_TOKEN equals the stripped contents of the token file, and the file is outside
    the workspace and the data folder.

    Args:
        token_file_path_str_in (str): Token file path (given by Nicolas on the command line)

    Returns:
        bool: True if the token matches
    """
    # REFUSE A TOKEN FILE INSIDE THE WORKSPACE OR THE DATA FOLDER
    if get_path_inside_bool(token_file_path_str_in, paths.WORKSPACE_PATH_STR) or get_path_inside_bool(token_file_path_str_in, paths.LOCAL_PATH_STR):
        raise ValueError("❌ The token file must live outside the workspace and the data folder.")
    # READ THE FILE AND THE ENVIRONMENT
    with open(token_file_path_str_in, "r", encoding="utf-8") as token_file:
        file_token_str = token_file.read().strip()
    env_token_str = os.environ.get("SO_HOLDOUT_EVALUATION_TOKEN", "")
    # REFUSE A MISMATCH
    if not file_token_str or env_token_str != file_token_str:
        raise ValueError("❌ SO_HOLDOUT_EVALUATION_TOKEN does not match the token file.")
    return True

# FUNCTION: LOAD DECLARED SOURCES FROM THE QUARANTINE THROUGH THE WINDOW END
def load_evaluation_source_frame_dict(source_name_list_in, token_file_path_str_in):
    """
    Reads declared sources from the quarantine root through the active window end. The evaluation token is checked
    first, then SO_QUARANTINE_PATH. Development code does not call this. The runner flag is set only for the read,
    so the loaders allow the window and still refuse the day after it, and it is restored before the function returns.

    Args:
        source_name_list_in (list[str]): Registry names
        token_file_path_str_in (str): Token file path (given by Nicolas on the command line)

    Returns:
        dict: source name -> stamped frame
    """
    # THE RUNNER FLAG IS MODULE STATE. DECLARE IT BEFORE IT IS READ OR SET
    global _RUNNER_ACTIVE_BOOL
    # THE TOKEN IS CHECKED BEFORE THE QUARANTINE PATH IS READ
    check_evaluation_token_bool(token_file_path_str_in)
    # THE QUARANTINE ROOT HAS NO DEFAULT. AN UNSET VARIABLE RAISES HERE, BEFORE ANY PATH IS REPOINTED
    paths.get_quarantine_root_str()
    # THE LAST SESSION THE EVALUATION MAY SEE
    end_date = get_date(get_active_holdout_window_dict()["end"])
    # REMEMBER ASSIGNMENTS SO A DEVELOPMENT OVERRIDE IS RESTORED, AND WHICH NAMES WERE LAZY
    saved_dict = {}
    fresh_name_list = []
    previous_bool = _RUNNER_ACTIVE_BOOL
    try:
        # POINT EVERY DATA-PATH NAME AT THE SAME LAYOUT UNDER THE QUARANTINE ROOT
        for name_str in paths.get_data_path_name_list():
            if name_str in paths.__dict__:
                saved_dict[name_str] = paths.__dict__[name_str]
            else:
                fresh_name_list.append(name_str)
            setattr(paths, name_str, paths.get_quarantine_named_path_str(name_str))
        # THE WINDOW IS READABLE ONLY WHILE THIS FLAG IS SET
        _RUNNER_ACTIVE_BOOL = True
        # STAMP THE FRAMES. THE DEVELOPMENT LOADER WOULD REFUSE THIS END DATE
        from so.core.point_in_time import get_stamped_source_frame_dict
        return get_stamped_source_frame_dict(source_name_list_in, end_date)
    finally:
        # RESTORE THE FLAG AND THE DEVELOPMENT PATHS EVEN WHEN THE LOAD RAISES
        _RUNNER_ACTIVE_BOOL = previous_bool
        for name_str, value in saved_dict.items():
            setattr(paths, name_str, value)
        for name_str in fresh_name_list:
            if name_str in paths.__dict__:
                delattr(paths, name_str)

# FUNCTION: READ THE GIT PRECONDITIONS OF A DESIGN
def get_git_precondition_dict(design_folder_str_in):
    """
    Clean working tree, the design folder's HEAD commit is on main, and that folder has a commit whose message
    contains "preregister".

    Args:
        design_folder_str_in (str): Experiment folder

    Returns:
        dict: clean_bool, on_main_bool, preregister_bool, commit_str
    """
    # READ THE WORKING TREE, THE DESIGN COMMIT AND MAIN
    status_str = subprocess.check_output(["git", "status", "--porcelain"], cwd=paths.WORKSPACE_PATH_STR, text=True)
    commit_str = subprocess.check_output(["git", "log", "-1", "--format=%H", "--", design_folder_str_in], cwd=paths.WORKSPACE_PATH_STR, text=True).strip()
    ancestor_code = subprocess.call(["git", "merge-base", "--is-ancestor", commit_str, "main"], cwd=paths.WORKSPACE_PATH_STR)
    message_str = subprocess.check_output(["git", "log", "--format=%s", "--", design_folder_str_in], cwd=paths.WORKSPACE_PATH_STR, text=True)
    # RETURN THE FLAGS
    return {"clean_bool": status_str.strip() == "", "on_main_bool": ancestor_code == 0, "preregister_bool": "preregister" in message_str,
            "commit_str": commit_str}

# FUNCTION: CHECK THAT A DESIGN MAY BE EVALUATED
def check_evaluation_precondition_dict(design_module_in, design_id_str_in, token_file_path_str_in, git_precondition_dict_in=None,
                                       design_folder_str_in=".", ledger_path_str_in=None, session_date_list_in=None):
    """
    Hard checks, in order: SO_HOLDOUT_PATH set and existing; token; clean git tree; design commit on main; a
    preregister commit; fewer than HOLDOUT_EVALUATION_BUDGET ledger rows whose window overlaps the active window;
    a new design (neither design_hash nor EXPERIMENT_NAME already in the ledger), or a repeat whose active window
    ends after its latest reported_end and has at least HOLDOUT_MIN_FORWARD_SESSIONS new sessions.

    Args:
        design_module_in (module): Design module (uppercase constants are hashed)
        design_id_str_in (str): Design id
        token_file_path_str_in (str): Token file
        git_precondition_dict_in (dict | None): Injected git result (None = read git)
        design_folder_str_in (str): Folder passed to git when the probe is not injected
        ledger_path_str_in (str | None): Ledger CSV
        session_date_list_in (list | None): Sessions in the bars (required to count new sessions)

    Returns:
        dict: window_dict, design_hash_str, commit_str, reported_start, reported_end
    """
    # REQUIRE A RESULTS FOLDER
    results_path_str = os.environ.get("SO_HOLDOUT_PATH") or None
    if not results_path_str or not os.path.isdir(results_path_str):
        raise ValueError("❌ SO_HOLDOUT_PATH must be set to an existing folder.")
    # REQUIRE THE TOKEN, THE WINDOW AND THE GIT STATE
    check_evaluation_token_bool(token_file_path_str_in)
    window_dict = get_active_holdout_window_dict()
    git_dict = git_precondition_dict_in or get_git_precondition_dict(design_folder_str_in)
    if not git_dict["clean_bool"]:
        raise ValueError("❌ The git working tree is not clean.")
    if not git_dict["on_main_bool"]:
        raise ValueError("❌ The design commit is not on main.")
    if not git_dict["preregister_bool"]:
        raise ValueError("❌ The design has no preregister commit.")
    # BUILD THE DESIGN HASH (THE DESIGN TREE, THE SHARED-CODE TREE, AND THE CONFIG HASH)
    design_hash_str = get_design_hash_str(design_module_in, design_folder_str_in, git_dict.get("design_tree_str"), git_dict.get("so_tree_str"))
    experiment_name_str = str(getattr(design_module_in, "EXPERIMENT_NAME", "") or "")
    # REFUSE AN ELEVENTH OVERLAPPING ROW AND A REPEAT THAT IS NOT FORWARD
    ledger_pdf = read_holdout_evaluation_pdf(ledger_path_str_in)
    overlap_pdf = get_overlapping_evaluation_pdf(ledger_pdf, window_dict)
    if len(overlap_pdf) >= config.HOLDOUT_EVALUATION_BUDGET:
        raise ValueError(f"❌ {config.HOLDOUT_EVALUATION_BUDGET} evaluations already overlap the active window.")
    reported_end_date = get_latest_reported_end_date(ledger_pdf, design_hash_str, experiment_name_str)
    report_session_list = get_report_session_date_list(session_date_list_in or [], window_dict, reported_end_date)
    if reported_end_date is not None:
        if get_date(window_dict["end"]) <= reported_end_date:
            raise ValueError("❌ This design hash was already evaluated on the active window.")
        if len(report_session_list) < int(config.HOLDOUT_MIN_FORWARD_SESSIONS):
            raise ValueError(f"❌ fewer than {config.HOLDOUT_MIN_FORWARD_SESSIONS} new sessions after {reported_end_date}.")
    if not report_session_list:
        raise ValueError("❌ This design hash has no new sessions to report on the active window.")
    # RETURN THE CHECKED CONTEXT AND THE REPORTED SPAN
    return {"window_dict": window_dict, "design_hash_str": design_hash_str, "commit_str": git_dict["commit_str"],
            "reported_start": report_session_list[0], "reported_end": report_session_list[-1]}

"""
Prior-Only Replay
"""

# FUNCTION: THE LATEST REPORTED END OF THE SAME DESIGN
def get_latest_reported_end_date(ledger_pdf_in, design_hash_str_in, experiment_name_str_in=None, file_path_str_in=None):
    """
    The latest reported_end on ledger rows of this design hash or this EXPERIMENT_NAME. A new protocol version uses a
    new EXPERIMENT_NAME, so it is a new design. A blank reported_end falls back to the registry window end of that row.

    Args:
        ledger_pdf_in (pd.DataFrame): Ledger
        design_hash_str_in (str): Design hash
        experiment_name_str_in (str | None): Design EXPERIMENT_NAME
        file_path_str_in (str | None): Registry CSV

    Returns:
        datetime.date | None: Latest reported end, or None when the design is new
    """
    # NO LEDGER ROW TO MATCH
    if ledger_pdf_in is None or len(ledger_pdf_in) == 0:
        return None
    # A ROW MATCHES WHEN THE HASH MATCHES OR THE EXPERIMENT NAME MATCHES
    false_series = pd.Series(False, index=ledger_pdf_in.index)
    hash_match_series = ledger_pdf_in["design_hash"] == design_hash_str_in if "design_hash" in ledger_pdf_in.columns else false_series
    name_str = str(experiment_name_str_in or "").strip()
    name_match_series = false_series
    if name_str and "experiment_name" in ledger_pdf_in.columns:
        name_match_series = ledger_pdf_in["experiment_name"].astype(str) == name_str
    hash_pdf = ledger_pdf_in[hash_match_series | name_match_series]
    if len(hash_pdf) == 0:
        return None
    # REGISTRY ENDS FOR A BLANK reported_end
    registry_pdf = read_holdout_window_pdf(file_path_str_in)
    end_dict = {str(row.window_id): get_date(row.end) for row in registry_pdf.itertuples(index=False)} if len(registry_pdf) else {}
    end_list = []
    for _, row in hash_pdf.iterrows():
        reported_str = str(row["reported_end"]).strip() if "reported_end" in hash_pdf.columns else ""
        if reported_str not in ("", "nan", "None"):
            try:
                end_list.append(get_date(reported_str))
                continue
            except (ValueError, TypeError):
                pass
        if str(row["window_id"]) in end_dict:
            end_list.append(end_dict[str(row["window_id"])])
    # NOTHING PARSEABLE
    if not end_list:
        return None
    return max(end_list)

# FUNCTION: THE SESSIONS THIS EVALUATION MAY REPORT
def get_report_session_date_list(session_date_list_in, window_dict_in, reported_end_in):
    """
    Sessions inside the active window. When reported_end_in is set, only sessions strictly after it.

    Args:
        session_date_list_in (list): Session dates
        window_dict_in (dict): Active window
        reported_end_in (datetime.date | None): Previous reported end of this hash

    Returns:
        list[datetime.date]: Sessions to report
    """
    # KEEP SESSIONS INSIDE THE ACTIVE WINDOW
    start_date, end_date = get_date(window_dict_in["start"]), get_date(window_dict_in["end"])
    session_date_list = [get_date(session_date) for session_date in session_date_list_in]
    inside_list = [session_date for session_date in session_date_list if start_date <= session_date <= end_date]
    # A NEW HASH REPORTS THE WHOLE WINDOW
    if reported_end_in is None:
        return inside_list
    # A REPEAT REPORTS ONLY THE SESSIONS AFTER THE LAST REPORTED END
    return [session_date for session_date in inside_list if session_date > get_date(reported_end_in)]

# FUNCTION: GET THE TOTAL RETURN OF A REPLAY'S DAILY EQUITY
def get_equity_total_return_float(daily_equity_pdf_in):
    """
    Last equity divided by the initial capital, minus one. A candidate replay starts a fresh window at the initial capital.

    Args:
        daily_equity_pdf_in (pd.DataFrame): daily equity (column equity)

    Returns:
        float: Total return
    """
    # RETURN ZERO ON AN EMPTY WINDOW
    if daily_equity_pdf_in is None or len(daily_equity_pdf_in) == 0:
        return 0.0
    return float(daily_equity_pdf_in["equity"].iloc[-1]) / config.INITIAL_CAPITAL - 1.0

# FUNCTION: LOAD THE DESIGN FILE, WITH config.py CONSTANTS COPIED AS load_design_module DOES
def get_file_design_module(design_module_in):
    """
    A new module object executed from the design file. Uppercase constants in the sibling config.py are copied when
    the design does not already define them (scripts/holdout_evaluate.load_design_module). Nothing on the caller's
    module object is copied, so this is the module the design hash reads.

    Args:
        design_module_in (module): Design that was loaded from a file

    Returns:
        module: Fresh module
    """
    # IMPORT THE LOADER HERE
    import importlib.util
    # EXECUTE THE FILE INTO A NEW MODULE OBJECT (NOT THE ONE ALREADY IN sys.modules)
    design_path_str = get_design_file_str(design_module_in)
    fresh_module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(f"holdout_design_file_{id(design_module_in)}", design_path_str))
    fresh_module.__spec__.loader.exec_module(fresh_module)
    # COPY MISSING CONSTANTS FROM config.py
    config_path_str = os.path.join(os.path.dirname(design_path_str), "config.py")
    if os.path.isfile(config_path_str):
        config_module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(f"holdout_design_config_{id(design_module_in)}", config_path_str))
        config_module.__spec__.loader.exec_module(config_module)
        for key_str, value in vars(config_module).items():
            if key_str.isupper() and not hasattr(fresh_module, key_str):
                setattr(fresh_module, key_str, value)
    return fresh_module


# FUNCTION: HASH A FROZEN DESIGN
def get_design_hash_str(design_module_in, design_folder_str_in=".", design_tree_str_in=None, so_tree_str_in=None):
    """
    sha256 of git rev-parse HEAD:<design folder>, git rev-parse HEAD:so, and the design's config hash.
    An unrelated path is not an input, so an unrelated commit does not change the hash. A change under the design
    folder or under so/ does.

    Args:
        design_module_in (module): Design module (uppercase constants are hashed)
        design_folder_str_in (str): Design folder, relative to the workspace
        design_tree_str_in (str | None): Injected HEAD:<design folder> (None = read git)
        so_tree_str_in (str | None): Injected HEAD:so (None = read git)

    Returns:
        str: Hex digest
    """
    # IMPORT THE CONFIG HASH HERE (AVOID AN IMPORT CYCLE)
    from so.core.trial_log import get_config_hash_str
    # READ THE TWO TREES WHEN THE CALLER DID NOT INJECT THEM
    design_tree_str = design_tree_str_in
    if design_tree_str is None:
        design_tree_str = subprocess.check_output(["git", "rev-parse", f"HEAD:{design_folder_str_in}"], cwd=paths.WORKSPACE_PATH_STR, text=True).strip()
    so_tree_str = so_tree_str_in
    if so_tree_str is None:
        so_tree_str = subprocess.check_output(["git", "rev-parse", "HEAD:so"], cwd=paths.WORKSPACE_PATH_STR, text=True).strip()
    # THE CONFIG PART IS THE FILE'S CONSTANTS, NOT A REPLAY MODULE AND NOT ITS CACHE
    hash_module = get_file_design_module(design_module_in) if get_design_file_str(design_module_in) else design_module_in
    payload_str = design_tree_str + "\n" + so_tree_str + "\n" + get_config_hash_str(hash_module)
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

# FUNCTION: BUILD THE CANDIDATE PERIODS THROUGH THE WINDOW
def get_holdout_period_pdf(design_module_in, session_date_list_in, window_dict_in):
    """
    Development validation quarters (get_development_fold_pdf), extended through the holdout with the same step and
    made non-overlapping (get_replay_period_pdf). The extension is allowed only because the runner is replaying the
    frozen path; development code still stops at the development end.

    Args:
        design_module_in (module): Design (PERIOD_RULE)
        session_date_list_in (list): Sessions the bars actually contain
        window_dict_in (dict): Active window

    Returns:
        pd.DataFrame: period_id, period_start, period_end, session_count, valid_start, valid_end
    """
    # IMPORT THE FOLD AND PERIOD BUILDERS HERE
    from so.core.schedule import get_development_fold_pdf
    from so.core.continuous_replay import get_replay_period_pdf
    # COLLECT THE PERIOD RULE AND THE DATES
    rule_dict = design_module_in.PERIOD_RULE
    session_date_list = [get_date(session_date) for session_date in session_date_list_in]
    window_end_date = min(get_date(window_dict_in["end"]), session_date_list[-1])
    # BUILD THE DEVELOPMENT QUARTERS (ANCHORED ON THE REGISTERED WINDOW, NOT ON THE TRUNCATED END)
    fold_pdf = get_development_fold_pdf(session_date_list, int(rule_dict["embargo_sessions"]), list(rule_dict["train_years"]),
                                       validation_window_months_in=config.VALIDATION_WINDOW_MONTHS, step_months_in=config.WALK_FORWARD_STEP_MONTHS)
    if fold_pdf.empty:
        raise ValueError("❌ The design has no development period on these sessions.")
    # EXTEND ONE STEP AT A TIME UNTIL THE WINDOW END (OR THE LAST SESSION THE BARS CONTAIN)
    extra_dict_list, last_end_date = [], get_date(fold_pdf["valid_end"].iloc[-1])
    next_id_int = int(fold_pdf["fold_id"].max()) + 1
    while last_end_date < window_end_date:
        later_date_list = [session_date for session_date in session_date_list if session_date > last_end_date]
        if not later_date_list:
            break
        step_end_date = (pd.Timestamp(last_end_date) + pd.DateOffset(months=config.WALK_FORWARD_STEP_MONTHS)).date()
        bounded_date_list = [session_date for session_date in later_date_list if session_date <= min(step_end_date, window_end_date)] or [later_date_list[0]]
        period_end_date = bounded_date_list[-1]
        extra_dict_list.append({"fold_id": next_id_int, "valid_start": later_date_list[0], "valid_end": period_end_date})
        next_id_int += 1
        if period_end_date <= last_end_date:
            break
        last_end_date = period_end_date
    # KEEP THE COLUMNS THE PERIOD BUILDER READS AND MAKE THE PERIODS NON-OVERLAPPING
    fold_pdf = fold_pdf[["fold_id", "valid_start", "valid_end"]]
    if extra_dict_list:
        fold_pdf = pd.concat([fold_pdf, pd.DataFrame(extra_dict_list)], ignore_index=True)
    period_pdf = get_replay_period_pdf(fold_pdf, session_date_list)
    # DROP A PERIOD THAT STARTS AFTER THE BARS END AND CLIP THE LAST END
    period_pdf = period_pdf[period_pdf["period_start"].map(get_date) <= window_end_date].reset_index(drop=True)
    period_pdf["period_end"] = [min(get_date(period_end), window_end_date) for period_end in period_pdf["period_end"]]
    return period_pdf


# FUNCTION: THE DESIGN FILE, WHEN THE MODULE WAS LOADED FROM ONE
def get_design_file_str(design_module_in):
    """
    The design's source file. A module built in memory for a test has none.

    Args:
        design_module_in (module): Design

    Returns:
        str | None: Path, or None
    """
    # A REAL FILE ONLY
    design_path_str = getattr(design_module_in, "__file__", None)
    if not design_path_str or not os.path.isfile(design_path_str):
        return None
    return design_path_str


# FUNCTION: DROP BARS AFTER A CUT DATE
def get_truncated_ohlcv_dict(ohlcv_array_dict_in, cut_date_in):
    """
    The same arrays with every session after cut_date_in removed. Kept sessions stay a prefix, so their bar indexes
    and session positions do not move. The cut session is kept in full, so its decision bar does not move.

    Args:
        ohlcv_array_dict_in (dict): Bars
        cut_date_in (datetime.date): Last session kept

    Returns:
        dict: Truncated arrays
    """
    # FIND THE LAST KEPT SESSION AND ITS LAST BAR
    session_date_list = [get_date(session_date) for session_date in ohlcv_array_dict_in["session_date_list"]]
    last_idx = max(idx for idx, session_date in enumerate(session_date_list) if session_date <= get_date(cut_date_in))
    end_bar_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][last_idx]) + 1
    # COPY THE PREFIX
    truncated_dict = {key_str: ohlcv_array_dict_in[key_str][:end_bar_idx] for key_str in ["open_arr", "high_arr", "low_arr", "close_arr", "bar_session_idx_arr"]}
    truncated_dict["timestamp_index"] = ohlcv_array_dict_in["timestamp_index"][:end_bar_idx]
    truncated_dict["session_date_list"] = list(ohlcv_array_dict_in["session_date_list"][:last_idx + 1])
    truncated_dict["session_start_idx_arr"] = ohlcv_array_dict_in["session_start_idx_arr"][:last_idx + 1]
    truncated_dict["session_end_idx_arr"] = ohlcv_array_dict_in["session_end_idx_arr"][:last_idx + 1]
    truncated_dict["date_session_idx_dict"] = {get_date(session_date): idx for idx, session_date in enumerate(truncated_dict["session_date_list"])}
    return truncated_dict

# FUNCTION: PERTURB EVERY BAR AFTER A DECISION BAR
def get_perturbed_ohlcv_dict(ohlcv_array_dict_in, cut_date_in):
    """
    A copy of the bars. Every open, high, low and close strictly after the cut session's decision bar (from its fill
    bar through the end of the data) is replaced by price x 1.25 plus seeded noise. High stays at least the larger of
    open and close; low stays at most the smaller. Timestamps, session bounds and bar indexes are unchanged, so the
    decision bar stays the decision bar.

    Args:
        ohlcv_array_dict_in (dict): Bars
        cut_date_in (datetime.date): Session whose decision bar is the last unperturbed bar

    Returns:
        dict: Perturbed arrays
    """
    # IMPORT THE DECISION INDEX HERE
    from so.features.daily_features import get_session_decision_idx_dict
    # FIND THE CUT SESSION AND THE FIRST BAR AFTER ITS DECISION
    session_date_list = [get_date(session_date) for session_date in ohlcv_array_dict_in["session_date_list"]]
    last_idx = max(idx for idx, session_date in enumerate(session_date_list) if session_date <= get_date(cut_date_in))
    start_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][last_idx]) + 1
    # COPY THE STRUCTURE AND THE PRICES
    perturbed_dict = {key_str: np.array(ohlcv_array_dict_in[key_str], copy=True) for key_str in ["open_arr", "high_arr", "low_arr", "close_arr", "bar_session_idx_arr", "session_start_idx_arr", "session_end_idx_arr"]}
    perturbed_dict["timestamp_index"] = ohlcv_array_dict_in["timestamp_index"].copy()
    perturbed_dict["session_date_list"] = list(ohlcv_array_dict_in["session_date_list"])
    perturbed_dict["date_session_idx_dict"] = dict(ohlcv_array_dict_in["date_session_idx_dict"])
    # OVERWRITE THE BARS AFTER THE DECISION BAR
    bar_count = len(perturbed_dict["close_arr"]) - start_idx
    if bar_count > 0:
        noise_arr = np.random.default_rng(int(get_date(cut_date_in).strftime("%Y%m%d"))).normal(0.0, 0.01, bar_count)
        for key_str in ["open_arr", "high_arr", "low_arr", "close_arr"]:
            perturbed_dict[key_str][start_idx:] = perturbed_dict[key_str][start_idx:] * 1.25 + noise_arr
        body_max_arr = np.maximum(perturbed_dict["open_arr"][start_idx:], perturbed_dict["close_arr"][start_idx:])
        body_min_arr = np.minimum(perturbed_dict["open_arr"][start_idx:], perturbed_dict["close_arr"][start_idx:])
        perturbed_dict["high_arr"][start_idx:] = np.maximum(perturbed_dict["high_arr"][start_idx:], body_max_arr)
        perturbed_dict["low_arr"][start_idx:] = np.minimum(perturbed_dict["low_arr"][start_idx:], body_min_arr)
    return perturbed_dict


# FUNCTION: THE NEVER-READ TAIL OF A REPORTED HOLDOUT SPAN
def get_unread_report_dict(holdout_equity_pdf_in, ohlcv_array_dict_in, end_date_in):
    """
    Sessions after PRIOR_READ_LAST_DATE_STR. Equity is rebased to the initial capital at the first unread session.
    Empty when the reported span does not go past that date. The label is always the sanity-check sentence: that
    tail is too short to pass or fail a design.

    Args:
        holdout_equity_pdf_in (pd.DataFrame): Reported-span equity (date, equity)
        ohlcv_array_dict_in (dict): Bars
        end_date_in (datetime.date | str): Last reported session

    Returns:
        dict: unread_start, unread_session_count, unread_total_return, unread_buy_hold_total_return, label_str
    """
    # IMPORT BUY-AND-HOLD HERE
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    # DATES ARE NORMALISED SO A TIMESTAMP COLUMN STILL CUTS
    prior_read_date = get_date(config.PRIOR_READ_LAST_DATE_STR)
    equity_pdf = holdout_equity_pdf_in.copy()
    equity_pdf["date"] = equity_pdf["date"].map(get_date)
    unread_pdf = equity_pdf[equity_pdf["date"] > prior_read_date].copy()
    unread_dict = {"label_str": UNREAD_SANITY_CHECK_STR}
    if len(unread_pdf) == 0:
        unread_dict["unread_start"] = np.nan
        unread_dict["unread_session_count"] = np.nan
        unread_dict["unread_total_return"] = np.nan
        unread_dict["unread_buy_hold_total_return"] = np.nan
        return unread_dict
    unread_start_date = unread_pdf["date"].iloc[0]
    unread_prior_pdf = equity_pdf[equity_pdf["date"] < unread_start_date]
    unread_base_float = float(unread_prior_pdf["equity"].iloc[-1]) if len(unread_prior_pdf) else config.INITIAL_CAPITAL
    unread_pdf["equity"] = unread_pdf["equity"] * (config.INITIAL_CAPITAL / unread_base_float)
    unread_buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, unread_start_date, get_date(end_date_in))
    unread_dict["unread_start"] = unread_start_date
    unread_dict["unread_session_count"] = int(len(unread_pdf))
    unread_dict["unread_total_return"] = get_equity_total_return_float(unread_pdf)
    unread_dict["unread_buy_hold_total_return"] = unread_buy_hold_dict["metric_dict"]["total_return"]
    return unread_dict


# FUNCTION: APPEND ONE LEDGER ROW
def append_holdout_evaluation_dict(row_dict_in, file_path_str_in=None):
    """
    Appends one summary row to the evaluation ledger.

    Args:
        row_dict_in (dict): Ledger columns
        file_path_str_in (str | None): Ledger CSV

    Returns:
        None
    """
    # APPEND THE ROW UNDER THE EXCLUSIVE LOCK (A MISSING COLUMN IS LEFT EMPTY, AS IN THE LEDGER SCHEMA)
    file_path_str = file_path_str_in or paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR
    row_pdf = pd.DataFrame([row_dict_in], columns=EVALUATION_COLUMN_LIST)
    append_csv_record_pdf(row_pdf, file_path_str, EVALUATION_COLUMN_LIST)


