import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE PATHS
from so import config, paths
# IMPORT THE VIX CONSTANTS (THE ARCHIVED PINNED BOUNDARY 2026-05-14)
from so import vix_config

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

Once opened, the window is frozen: new downloads do not move it. Sessions after its end are forward data and are
refused everywhere this module guards (a later task adds forward evaluation). Each frozen design may be evaluated once
per window, and at most HOLDOUT_EVALUATION_BUDGET designs per window. Only scripts/holdout_evaluate.py, run by
Nicolas, may read the window. Development code stops at get_development_end_date (the session an embargo before the
window start).

records/holdout_windows.csv and records/holdout_evaluations.csv are versioned (dates and summary metrics are not
secret). Daily paths are written only under SO_HOLDOUT_PATH, which has no default.
"""

# DEFINE THE REGISTRY COLUMNS
WINDOW_COLUMN_LIST = ["window_id", "status", "start", "end", "session_count", "months_covered", "opened_ts", "opened_by",
                      "data_last_session_at_open", "retired_ts", "retire_reason"]
# DEFINE THE LEDGER COLUMNS
EVALUATION_COLUMN_LIST = ["window_id", "design_id", "design_hash", "commit", "evaluated_ts", "status", "total_return",
                          "buy_hold_total_return", "annualized_log_excess", "log_excess_ci_low", "log_excess_ci_high",
                          "in_market_pct", "sharpe_ratio", "max_drawdown", "mde", "primary_pass", "secondary_pass",
                          "comparable_pass", "baselines_beaten", "carried_weight", "holdout_candidates", "sources_read",
                          "retrain_frequency", "train_window_candidates", "holdout_refit_count", "average_share_purged",
                          "turnover", "candidate_switches"]
# DEFINE THE MESSAGE WHEN NO WINDOW IS REGISTERED
NO_WINDOW_MESSAGE_STR = "no holdout window registered: Nicolas must run scripts/holdout_window.py open"
# DEFINE THE RUNNER FLAG (SET INSIDE run_holdout_evaluation, AND WHILE A WINDOW-END LOAD IS IN PROGRESS)
_RUNNER_ACTIVE_BOOL = False

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

# FUNCTION: WHETHER THE HOLDOUT RUNNER IS ACTIVE
def get_runner_active_bool():
    """
    True only inside run_holdout_evaluation.

    Returns:
        bool: Runner flag
    """
    # RETURN THE FLAG
    return bool(_RUNNER_ACTIVE_BOOL)

# FUNCTION: WARN THAT LEGACY REPRODUCTION IS ON
def print_legacy_reproduction_warning():
    """
    Prints a loud warning. Agents must never set SO_ALLOW_LEGACY_REPRODUCTION (research-integrity.mdc rule 1).

    Returns:
        None
    """
    # PRINT THE WARNING
    print("WARNING: SO_ALLOW_LEGACY_REPRODUCTION=1. Archived experiments may use only the pinned boundary "
          f"{vix_config.UNTOUCHED_START_DATE_STR}. Agents must not set this variable.")

# FUNCTION: GET THE DATE A REPLAY OR A LOADER MAY NOT REACH
def get_replay_boundary_date(pinned_date_in=None):
    """
    The first date that must not be read.
    Runner: the day after the window end (the window itself is allowed; forward data is not).
    SO_ALLOW_LEGACY_REPRODUCTION=1: the pinned 2026-05-14 boundary only (a passed date cannot extend it), with a warning.
    No window and a passed date: that date (archived tests).
    An active window: the earlier of the passed date and the window start.

    Args:
        pinned_date_in (datetime.date | str | None): Legacy pinned boundary passed by the caller

    Returns:
        datetime.date: Boundary (dates on or after it are refused)
    """
    # INSIDE THE RUNNER THE QUARANTINE STARTS THE DAY AFTER THE WINDOW
    if _RUNNER_ACTIVE_BOOL:
        return get_date(get_active_holdout_window_dict()["end"]) + timedelta(days=1)
    # LEGACY REPRODUCTION USES ONLY THE PINNED 2026-05-14 BOUNDARY
    legacy_date = get_date(vix_config.UNTOUCHED_START_DATE_STR)
    if os.environ.get("SO_ALLOW_LEGACY_REPRODUCTION") == "1":
        print_legacy_reproduction_warning()
        boundary_date = legacy_date
        if pinned_date_in is not None:
            boundary_date = min(boundary_date, get_date(pinned_date_in))
        return boundary_date
    # WITHOUT A WINDOW, A PASSED DATE KEEPS THE ARCHIVED BEHAVIOUR
    window_dict = get_active_holdout_window_dict(missing_ok_bool_in=True)
    if window_dict is None:
        if pinned_date_in is None:
            raise ValueError(NO_WINDOW_MESSAGE_STR)
        return get_date(pinned_date_in)
    # WITH A WINDOW, USE THE EARLIER OF THE PINNED DATE AND THE WINDOW START
    start_date = get_date(window_dict["start"])
    if pinned_date_in is None:
        return start_date
    return min(get_date(pinned_date_in), start_date)

# FUNCTION: REFUSE A DEVELOPMENT DATE INSIDE THE HOLDOUT
def check_development_date(date_in):
    """
    Raises if date_in is on or after the active window start, unless the holdout runner is active. Inside the runner,
    dates after the window end (forward data) still raise.

    Args:
        date_in (datetime.date | str): Date a development caller wants to read

    Returns:
        bool: True if the date is allowed
    """
    # COLLECT THE WINDOW AND THE DATE
    window_dict = get_active_holdout_window_dict()
    date = get_date(date_in)
    # INSIDE THE RUNNER, REFUSE ONLY FORWARD DATA
    if _RUNNER_ACTIVE_BOOL:
        if date > get_date(window_dict["end"]):
            raise ValueError(f"❌ Forward data {date} is after the holdout end {window_dict['end']}.")
        return True
    # OUTSIDE THE RUNNER, REFUSE THE WINDOW AND EVERYTHING AFTER IT
    if date >= get_date(window_dict["start"]):
        raise ValueError(f"❌ {date} is on or after the holdout start {window_dict['start']}.")
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
                                       design_folder_str_in=".", ledger_path_str_in=None):
    """
    Hard checks, in order: SO_HOLDOUT_PATH set and existing; token; clean git tree; design commit on main; a
    preregister commit; the (design hash, window) pair is new; the window has fewer than HOLDOUT_EVALUATION_BUDGET
    evaluations.

    Args:
        design_module_in (module): Design module (uppercase constants are hashed)
        design_id_str_in (str): Design id
        token_file_path_str_in (str): Token file
        git_precondition_dict_in (dict | None): Injected git result (None = read git)
        design_folder_str_in (str): Folder passed to git when the probe is not injected
        ledger_path_str_in (str | None): Ledger CSV

    Returns:
        dict: window_dict, design_hash_str, commit_str
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
    # REFUSE A REPEATED DESIGN AND AN ELEVENTH DESIGN
    ledger_pdf = read_holdout_evaluation_pdf(ledger_path_str_in)
    window_pdf = ledger_pdf[ledger_pdf["window_id"] == window_dict["window_id"]] if len(ledger_pdf) else ledger_pdf
    if len(window_pdf) and (window_pdf["design_hash"] == design_hash_str).any():
        raise ValueError("❌ This design hash was already evaluated on the active window.")
    if len(window_pdf) >= config.HOLDOUT_EVALUATION_BUDGET:
        raise ValueError(f"❌ The active window already has {config.HOLDOUT_EVALUATION_BUDGET} evaluations.")
    # RETURN THE CHECKED CONTEXT
    return {"window_dict": window_dict, "design_hash_str": design_hash_str, "commit_str": git_dict["commit_str"]}

"""
Prior-Only Replay
"""

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

# FUNCTION: CALL A DESIGN REPLAY, PASSING THE CONTEXT ONLY IF THE FUNCTION ACCEPTS IT
def call_design_replay(func_in, positional_list_in, data_context_in):
    """
    Calls a design function. data_context_in is passed only when the function has that parameter, so an older design
    keeps the call it had before the point-in-time door existed.

    Args:
        func_in (callable): Design function
        positional_list_in (list): Positional arguments
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        The function's return value
    """
    # IMPORT INSPECT HERE
    import inspect
    # PASS THE CONTEXT ONLY TO A DESIGN THAT DECLARES IT
    if data_context_in is not None and "data_context_in" in inspect.signature(func_in).parameters:
        return func_in(*positional_list_in, data_context_in=data_context_in)
    return func_in(*positional_list_in)

# FUNCTION: SCORE EVERY CANDIDATE ON EVERY PERIOD
def get_candidate_score_pdf(design_module_in, ohlcv_array_dict_in, period_pdf_in, data_context_in=None):
    """
    Period score = the candidate's period return minus buy-and-hold over the same period. Development periods and
    holdout periods are both scored. Each call is the design's own replay of that period.

    Args:
        design_module_in (module): Design (CANDIDATE_LIST, run_candidate_replay_dict)
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        data_context_in (DataContext | None): Point-in-time context (None keeps the previous call)

    Returns:
        pd.DataFrame: fold_id, candidate, excess_return
    """
    # IMPORT BUY-AND-HOLD HERE
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    # SCORE EACH PERIOD AND EACH CANDIDATE
    row_dict_list = []
    for period_row in period_pdf_in.itertuples(index=False):
        buy_hold_float = get_buy_and_hold_result_dict(ohlcv_array_dict_in, period_row.period_start, period_row.period_end)["metric_dict"]["total_return"]
        for candidate in design_module_in.CANDIDATE_LIST:
            replay_dict = call_design_replay(design_module_in.run_candidate_replay_dict,
                                             [ohlcv_array_dict_in, period_row.period_start, period_row.period_end, candidate], data_context_in)
            row_dict_list.append({"fold_id": int(period_row.period_id), "candidate": candidate,
                                  "excess_return": get_equity_total_return_float(replay_dict["daily_equity_pdf"]) - buy_hold_float})
    return pd.DataFrame(row_dict_list)

# FUNCTION: CHOOSE THE CANDIDATE IN FORCE FOR EACH PERIOD
def get_governing_selection_pdf(design_module_in, score_pdf_in, period_pdf_in):
    """
    Selection for period f uses periods before f only (get_pooled_selection_pdf, then get_prior_only_period_candidate_dict).
    The first period has an empty history and takes the first candidate. A single candidate governs every period.

    Args:
        design_module_in (module): Design (CANDIDATE_LIST, SELECTION_RULE)
        score_pdf_in (pd.DataFrame): Period scores
        period_pdf_in (pd.DataFrame): Periods

    Returns:
        pd.DataFrame: period_id, candidate, candidate_idx (the candidate in force)
    """
    # IMPORT THE SELECTION FUNCTIONS HERE
    from so.core.evaluation import get_pooled_selection_pdf
    from so.core.continuous_replay import get_prior_only_period_candidate_dict
    # A SINGLE CANDIDATE GOVERNS EVERY PERIOD
    candidate_list = list(design_module_in.CANDIDATE_LIST)
    if len(candidate_list) == 1:
        return pd.DataFrame({"period_id": period_pdf_in["period_id"].astype(int), "candidate": candidate_list[0], "candidate_idx": 0})
    # SELECT FROM EARLIER PERIODS ONLY AND MAP THE CHOICE ONTO THE NEXT PERIOD
    rule_dict = design_module_in.SELECTION_RULE
    score_pdf = score_pdf_in.copy()
    # A DESIGN MAY ATTACH TIE COLUMNS (THE TRAINING-WINDOW LENGTH) THAT THE SCORE TABLE DOES NOT CARRY
    tie_value_dict = getattr(design_module_in, "CANDIDATE_TIE_VALUE_DICT", None) or {}
    for column_str, value_dict in tie_value_dict.items():
        if column_str not in score_pdf.columns:
            score_pdf[column_str] = score_pdf["candidate"].map(value_dict)
    selection_pdf = get_pooled_selection_pdf(score_pdf, ["candidate"], "excess_return", int(rule_dict["pooled_periods"]), list(rule_dict["tie_break"]))
    selection_pdf["candidate_idx"] = selection_pdf["candidate"].map({name: idx for idx, name in enumerate(candidate_list)})
    governing_dict = get_prior_only_period_candidate_dict(selection_pdf, period_pdf_in, "candidate_idx")
    # THE FIRST PERIOD HAS NO PRIOR SELECTION
    row_dict_list = []
    for period_id in period_pdf_in["period_id"].astype(int):
        candidate_idx = int(governing_dict[period_id]) if period_id in governing_dict else 0
        row_dict_list.append({"period_id": period_id, "candidate": candidate_list[candidate_idx], "candidate_idx": candidate_idx})
    return pd.DataFrame(row_dict_list)

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

# FUNCTION: WHETHER A CALLABLE WAS DEFINED IN A FILE
def get_defined_in_file_bool(value_in, file_path_str_in):
    """
    True when value_in is a function whose source is file_path_str_in. A function the caller replaced, such as a test
    double, is False.

    Args:
        value_in: Attribute value
        file_path_str_in (str): Design file

    Returns:
        bool: Defined in that file
    """
    # ONLY A FUNCTION CARRIES CODE
    code = getattr(value_in, "__code__", None)
    if code is None:
        return False
    return os.path.normcase(os.path.abspath(code.co_filename)) == os.path.normcase(os.path.abspath(file_path_str_in))

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

# FUNCTION: A FRESH DESIGN MODULE FOR ONE REPLAY
def get_fresh_design_module(design_module_in):
    """
    A new module object from the design file, so a cache or any other module global filled by one replay is absent
    from the next. The caller's uppercase constants are copied onto it (a test may set PERIOD_RULE), and so is a
    callable the caller replaced. A module with no file is returned as itself.

    Args:
        design_module_in (module): Design

    Returns:
        module: The module this replay calls
    """
    # AN IN-MEMORY TEST MODULE HAS NO FILE TO RELOAD
    if get_design_file_str(design_module_in) is None:
        return design_module_in
    # THE FILE, THEN THE CALLER'S OVERRIDES (NOT ITS CACHE)
    fresh_module = get_file_design_module(design_module_in)
    design_path_str = get_design_file_str(design_module_in)
    for key_str, value in vars(design_module_in).items():
        if key_str.startswith("__"):
            continue
        if key_str.isupper() or (callable(value) and not get_defined_in_file_bool(value, design_path_str)):
            setattr(fresh_module, key_str, value)
    return fresh_module

# FUNCTION: RUN THE PRIOR-ONLY PATH ON ONE BAR SET
def get_prior_only_result_dict(design_module_in, ohlcv_array_dict_in, window_dict_in, data_context_in=None):
    """
    Periods, scores, the candidate in force, and the design's continuous path. The design is a fresh module, so this
    replay does not see a cache filled by the full run or by another cut. Period scores and the path share that one
    module, so a cache may be reused inside this replay.

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Bars
        window_dict_in (dict): Active window
        data_context_in (DataContext | None): Point-in-time context (None keeps the previous call)

    Returns:
        dict: period_pdf, score_pdf, selection_pdf, path_dict
    """
    # ONE FRESH MODULE FOR THIS REPLAY (THE FULL RUN, OR ONE TRUNCATED OR PERTURBED RUN)
    design_module_in = get_fresh_design_module(design_module_in)
    # BUILD THE PERIODS, THE SCORES AND THE PATH
    period_pdf = get_holdout_period_pdf(design_module_in, ohlcv_array_dict_in["session_date_list"], window_dict_in)
    score_pdf = get_candidate_score_pdf(design_module_in, ohlcv_array_dict_in, period_pdf, data_context_in)
    selection_pdf = get_governing_selection_pdf(design_module_in, score_pdf, period_pdf)
    path_dict = call_design_replay(design_module_in.run_prior_only_path_dict, [ohlcv_array_dict_in, period_pdf, selection_pdf], data_context_in)
    return {"period_pdf": period_pdf, "score_pdf": score_pdf, "selection_pdf": selection_pdf, "path_dict": path_dict}

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

# FUNCTION: LIST THE CUT DATES OF THE TRUNCATION TEST
def get_truncation_cut_date_list(session_date_list_in, window_dict_in):
    """
    The last session of each calendar month inside the window, at most 12 (the latest 12 when a window has more).

    Args:
        session_date_list_in (list): Sessions
        window_dict_in (dict): Active window

    Returns:
        list[datetime.date]: Cut dates
    """
    # GROUP THE HOLDOUT SESSIONS BY MONTH
    start_date, end_date = get_date(window_dict_in["start"]), get_date(window_dict_in["end"])
    month_dict = {}
    for session_date in session_date_list_in:
        session_day = get_date(session_date)
        if start_date <= session_day <= end_date:
            month_dict.setdefault((session_day.year, session_day.month), []).append(session_day)
    # RETURN THE MONTH ENDS
    return [date_list[-1] for _, date_list in sorted(month_dict.items())][-12:]

# FUNCTION: COMPARE ONE TRUNCATED REPLAY WITH THE FULL REPLAY
def get_lookahead_difference_str(full_result_dict_in, short_result_dict_in, cut_date_in):
    """
    None when every decision on a session before the cut matches. The cut session itself is the last session of the
    truncated replay, which the simulator liquidates; that liquidation is not a strategy decision and is excluded.
    Target weights are compared on every session up to and including the cut.

    Args:
        full_result_dict_in (dict): Replay on all bars
        short_result_dict_in (dict): Replay on bars through the cut
        cut_date_in (datetime.date): Cut date

    Returns:
        str | None: The decision that differed, or None
    """
    # COMPARE THE CANDIDATE IN FORCE ON PERIODS THAT END BEFORE THE CUT
    full_period_pdf, short_period_pdf = full_result_dict_in["period_pdf"], short_result_dict_in["period_pdf"]
    for period_id in full_period_pdf["period_id"].astype(int):
        full_end_date = get_date(full_period_pdf.loc[full_period_pdf["period_id"] == period_id, "period_end"].iloc[0])
        if full_end_date >= get_date(cut_date_in):
            continue
        short_match_pdf = short_period_pdf[short_period_pdf["period_id"] == period_id]
        if short_match_pdf.empty:
            return f"period {period_id} missing at {cut_date_in}"
        full_candidate = full_result_dict_in["selection_pdf"].loc[full_result_dict_in["selection_pdf"]["period_id"] == period_id, "candidate"].iloc[0]
        short_candidate = short_result_dict_in["selection_pdf"].loc[short_result_dict_in["selection_pdf"]["period_id"] == period_id, "candidate"].iloc[0]
        if full_candidate != short_candidate:
            return f"candidate of period {period_id} at {cut_date_in}"
    # COMPARE TARGET WEIGHTS ON EVERY SESSION UP TO THE CUT
    full_path_dict, short_path_dict = full_result_dict_in["path_dict"], short_result_dict_in["path_dict"]
    if "target_weight_arr" in full_path_dict and "target_weight_arr" in short_path_dict:
        short_weight_dict = {get_date(session_date): float(short_path_dict["target_weight_arr"][idx])
                             for idx, session_date in enumerate(short_path_dict["decision_session_list"])}
        for idx, session_date in enumerate(full_path_dict["decision_session_list"]):
            session_day = get_date(session_date)
            if session_day <= get_date(cut_date_in) and session_day in short_weight_dict:
                if abs(float(full_path_dict["target_weight_arr"][idx]) - short_weight_dict[session_day]) > 1e-12:
                    return f"target weight on {session_day}"
    # COMPARE POSITIONS AND WEIGHTS ON SESSIONS STRICTLY BEFORE THE CUT
    full_equity_pdf, short_equity_pdf = full_path_dict["daily_equity_pdf"].copy(), short_path_dict["daily_equity_pdf"].copy()
    full_equity_pdf["date"] = full_equity_pdf["date"].map(get_date)
    short_equity_pdf["date"] = short_equity_pdf["date"].map(get_date)
    merged_pdf = full_equity_pdf.merge(short_equity_pdf, on="date", suffixes=("_full", "_short"))
    before_pdf = merged_pdf[merged_pdf["date"] < get_date(cut_date_in)]
    if "in_position_full" in before_pdf.columns and not np.array_equal(before_pdf["in_position_full"].to_numpy(), before_pdf["in_position_short"].to_numpy()):
        return f"position on {before_pdf.loc[before_pdf['in_position_full'].to_numpy() != before_pdf['in_position_short'].to_numpy(), 'date'].iloc[0]}"
    if "weight_full" in before_pdf.columns and float(np.max(np.abs(before_pdf["weight_full"].to_numpy(dtype=float) - before_pdf["weight_short"].to_numpy(dtype=float)))) > 1e-12:
        return f"weight on {before_pdf.loc[np.abs(before_pdf['weight_full'] - before_pdf['weight_short']).idxmax(), 'date']}"
    # COMPARE TRADES STRICTLY BEFORE THE CUT, EXCLUDING THE FORCED END-OF-WINDOW SALE
    def get_trade_key_list(trade_pdf_in):
        # KEEP NOTHING WHEN THERE ARE NO TRADES
        if trade_pdf_in is None or len(trade_pdf_in) == 0:
            return []
        trade_pdf = trade_pdf_in.copy()
        if "reason" in trade_pdf.columns:
            trade_pdf = trade_pdf[trade_pdf["reason"] != "END"]
        trade_pdf["session"] = pd.to_datetime(trade_pdf["trade_ts"]).dt.tz_convert("America/New_York").dt.date
        trade_pdf = trade_pdf[trade_pdf["session"] < get_date(cut_date_in)]
        delta_str = "delta_share_count" if "delta_share_count" in trade_pdf.columns else "delta"
        return [(str(session_date), float(delta)) for session_date, delta in zip(trade_pdf["session"], trade_pdf[delta_str])]
    full_trade_list, short_trade_list = get_trade_key_list(full_path_dict.get("trade_pdf")), get_trade_key_list(short_path_dict.get("trade_pdf"))
    if len(full_trade_list) != len(short_trade_list) or any(abs(full_delta - short_delta) > 1e-12 or full_session != short_session
                                                           for (full_session, full_delta), (short_session, short_delta) in zip(full_trade_list, short_trade_list)):
        return f"trade before {cut_date_in}"
    return None

# FUNCTION: COMPARE SIGNALS THROUGH THE CUT SESSION
def get_signal_difference_str(full_result_dict_in, short_result_dict_in, cut_date_in):
    """
    None when every signal on a session up to and including the cut matches. A path with no signal array is unchanged.
    Fills and share counts on the cut session are not read here.

    Args:
        full_result_dict_in (dict): Replay on the original bars
        short_result_dict_in (dict): Replay on the perturbed bars
        cut_date_in (datetime.date): Cut date

    Returns:
        str | None: The signal that differed, or None
    """
    # SKIP PATHS THAT DO NOT CARRY A SIGNAL
    full_path_dict, short_path_dict = full_result_dict_in["path_dict"], short_result_dict_in["path_dict"]
    if "signal_arr" not in full_path_dict and "signal_arr" not in short_path_dict:
        return None
    if "signal_arr" not in full_path_dict or "signal_arr" not in short_path_dict:
        return f"signal missing at {cut_date_in}"
    # COMPARE THE SIGNAL ON EVERY SESSION UP TO THE CUT
    short_signal_dict = {get_date(session_date): float(short_path_dict["signal_arr"][idx])
                         for idx, session_date in enumerate(short_path_dict["decision_session_list"])}
    for idx, session_date in enumerate(full_path_dict["decision_session_list"]):
        session_day = get_date(session_date)
        if session_day <= get_date(cut_date_in) and session_day in short_signal_dict:
            if abs(float(full_path_dict["signal_arr"][idx]) - short_signal_dict[session_day]) > 1e-12:
                return f"signal on {session_day}"
    return None

# FUNCTION: REBASE THE HOLDOUT SEGMENT AND BUILD THE REPORT
def get_holdout_report_dict(design_module_in, ohlcv_array_dict_in, window_dict_in, result_dict_in):
    """
    Reports only the holdout sessions. Equity is rebased so the equity entering the window equals the initial capital.
    Buy-and-hold and the design's baselines are computed on the holdout sessions only.

    Args:
        design_module_in (module): Design (get_baseline_return_dict)
        ohlcv_array_dict_in (dict): Bars through the window end
        window_dict_in (dict): Active window
        result_dict_in (dict): The full prior-only result

    Returns:
        dict: report_dict, daily_equity_pdf, buy_hold_equity_pdf
    """
    # IMPORT THE EVALUATION FUNCTIONS HERE
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    from so.core.evaluation import (get_chained_daily_return_pdf, get_success_criteria_dict, get_mde_float,
                                    get_turnover_switch_dict, get_refit_report_dict)
    from so.core.continuous_replay import get_log_excess_bootstrap_dict
    # CUT THE PATH TO THE HOLDOUT AND REBASE IT
    start_date, end_date = get_date(window_dict_in["start"]), get_date(window_dict_in["end"])
    equity_pdf = result_dict_in["path_dict"]["daily_equity_pdf"].copy()
    equity_pdf["date"] = equity_pdf["date"].map(get_date)
    prior_pdf = equity_pdf[equity_pdf["date"] < start_date]
    holdout_pdf = equity_pdf[(equity_pdf["date"] >= start_date) & (equity_pdf["date"] <= end_date)].copy()
    base_float = float(prior_pdf["equity"].iloc[-1]) if len(prior_pdf) else config.INITIAL_CAPITAL
    holdout_pdf["equity"] = holdout_pdf["equity"] * (config.INITIAL_CAPITAL / base_float)
    carried_weight_float = float(holdout_pdf["weight"].iloc[0]) if "weight" in holdout_pdf.columns and len(holdout_pdf) else np.nan
    # BUY-AND-HOLD AND THE DESIGN'S BASELINES, BOTH OVER THE HOLDOUT ONLY
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, start_date, end_date)
    baseline_return_dict = design_module_in.get_baseline_return_dict(ohlcv_array_dict_in, start_date, end_date)
    # CALCULATE THE LOG EXCESS, THE SUCCESS CRITERIA AND THE MDE
    strategy_return_pdf = get_chained_daily_return_pdf([holdout_pdf])
    buy_hold_return_pdf = get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]])
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=6)
    success_dict = get_success_criteria_dict(strategy_return_pdf, buy_hold_return_pdf, baseline_return_dict)
    merged_pdf = strategy_return_pdf.merge(buy_hold_return_pdf, on="date", suffixes=("_strategy", "_buy_hold"))
    merged_pdf["month"] = pd.to_datetime(merged_pdf["date"]).dt.to_period("M")
    month_pdf = merged_pdf.groupby("month").agg(strategy_log=("daily_return_strategy", lambda series: float(np.log1p(series).sum())),
                                                buy_hold_log=("daily_return_buy_hold", lambda series: float(np.log1p(series).sum())))
    month_excess_arr = (month_pdf["strategy_log"] - month_pdf["buy_hold_log"]).to_numpy(dtype=float)
    # RECORD THE CANDIDATE IN FORCE IN EACH HOLDOUT PERIOD
    period_pdf, selection_pdf = result_dict_in["period_pdf"], result_dict_in["selection_pdf"]
    holdout_period_pdf = period_pdf[period_pdf["period_end"].map(get_date) >= start_date]
    candidate_dict = {int(period_row.period_id): selection_pdf.loc[selection_pdf["period_id"] == period_row.period_id, "candidate"].iloc[0]
                      for period_row in holdout_period_pdf.itertuples(index=False)}
    # THE CANDIDATE IN FORCE ON EACH HOLDOUT SESSION, FOR THE SWITCH COUNT
    candidate_list = []
    for session_date in holdout_pdf["date"]:
        cover_pdf = period_pdf[(period_pdf["period_start"].map(get_date) <= session_date) & (period_pdf["period_end"].map(get_date) >= session_date)]
        if len(cover_pdf) == 0:
            continue
        period_id = int(cover_pdf["period_id"].iloc[-1])
        candidate_list.append(selection_pdf.loc[selection_pdf["period_id"] == period_id, "candidate"].iloc[0])
    # TRADES WHOSE SESSION FALLS INSIDE THE HOLDOUT
    trade_pdf = result_dict_in["path_dict"].get("trade_pdf")
    trade_count = 0
    if trade_pdf is not None and len(trade_pdf) and "trade_ts" in trade_pdf.columns:
        trade_work_pdf = trade_pdf if "reason" not in trade_pdf.columns else trade_pdf[trade_pdf["reason"] != "END"]
        trade_clock = pd.to_datetime(trade_work_pdf["trade_ts"])
        if getattr(trade_clock.dt, "tz", None) is None:
            trade_clock = trade_clock.dt.tz_localize("America/New_York")
        else:
            trade_clock = trade_clock.dt.tz_convert("America/New_York")
        trade_day = trade_clock.dt.date
        trade_count = int(((trade_day >= start_date) & (trade_day <= end_date)).sum())
    # TURNOVER FROM THE HOLDOUT WEIGHTS
    weight_arr = holdout_pdf["weight"].to_numpy(dtype=float) if "weight" in holdout_pdf.columns and len(holdout_pdf) else np.array([])
    if len(weight_arr):
        activity_dict = get_turnover_switch_dict(weight_arr, trade_count, candidate_list)
        turnover_float = activity_dict["turnover_per_year"]
        switch_count = activity_dict["candidate_switch_count"]
    else:
        turnover_float, switch_count = np.nan, 0 if candidate_list else np.nan
    # REFITS WHOSE SESSION IS INSIDE THE HOLDOUT
    refit_pdf = result_dict_in["path_dict"].get("refit_log_pdf")
    if refit_pdf is not None and len(refit_pdf):
        refit_day = refit_pdf["retrain_session"].map(get_date)
        holdout_refit_pdf = refit_pdf[(refit_day >= start_date) & (refit_day <= end_date)].copy()
    else:
        holdout_refit_pdf = None
    refit_report_dict = get_refit_report_dict(holdout_refit_pdf if holdout_refit_pdf is not None else pd.DataFrame(), None)
    frequency_str = str(getattr(design_module_in, "RETRAIN_FREQUENCY_STR", "") or "")
    window_list = getattr(design_module_in, "TRAIN_WINDOW_CANDIDATE_LIST", None)
    window_text = "" if not window_list else ",".join(str(window_str) for window_str in window_list)
    # RETURN THE REPORT
    report_dict = {"total_return": success_dict["strategy_total_return"], "buy_hold_total_return": success_dict["buy_hold_total_return"],
                   "annualized_log_excess": log_excess_dict["annualized_log_excess"], "log_excess_ci_low": log_excess_dict["ci_low"],
                   "log_excess_ci_high": log_excess_dict["ci_high"], "in_market_pct": float(holdout_pdf["in_position"].mean()) if "in_position" in holdout_pdf.columns else np.nan,
                   "sharpe_ratio": success_dict["strategy_sharpe_ratio"], "max_drawdown": success_dict["strategy_max_drawdown"],
                   "mde": get_mde_float(float(np.std(month_excess_arr, ddof=1)) if len(month_excess_arr) > 1 else np.nan, len(month_excess_arr)),
                   "primary_pass": success_dict["primary_success"], "secondary_pass": success_dict["secondary_success"],
                   "comparable_pass": success_dict["comparable_return"], "baselines_beaten": success_dict["baselines_beaten"],
                   "carried_weight": carried_weight_float, "holdout_candidates": json.dumps(candidate_dict),
                   "retrain_frequency": frequency_str, "train_window_candidates": window_text,
                   "holdout_refit_count": int(len(holdout_refit_pdf)) if holdout_refit_pdf is not None else np.nan,
                   "average_share_purged": refit_report_dict["mean_share_purged"],
                   "turnover": turnover_float, "candidate_switches": switch_count}
    return {"report_dict": report_dict, "daily_equity_pdf": holdout_pdf, "buy_hold_equity_pdf": buy_hold_dict["daily_equity_pdf"],
            "refit_log_pdf": holdout_refit_pdf}

# FUNCTION: RUN THE TRUNCATION TEST
def get_lookahead_failure_str(design_module_in, ohlcv_array_dict_in, window_dict_in, full_result_dict_in, data_context_in=None):
    """
    Re-runs the prior-only path at each month-end inside the window. First the sessions after the cut are dropped
    (the cut session stays whole, so its decision bar does not move), and every other source keeps only rows with
    available_ts at or before the end of the cut session. Then every SPY bar strictly after that session's decision
    bar is perturbed, and every feature value with available_ts after the decision is perturbed. Labels are not.
    The perturbation must leave target weights and signals unchanged through the cut session, positions, weights and
    trades unchanged strictly before it, and the candidate unchanged for periods that end before it. Fills and share
    counts on the cut session itself are not compared.

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Bars through the window end
        window_dict_in (dict): Active window
        full_result_dict_in (dict): The full replay
        data_context_in (DataContext | None): Point-in-time context (None keeps the SPY-only checks)

    Returns:
        str | None: The cut and the decision that differed, or None
    """
    # IMPORT THE CONTEXT CLOCK HERE
    from so.core.point_in_time import get_cut_clock_dict
    # CHECK EACH MONTH END BY DROPPING LATER SESSIONS, THEN BY PERTURBING VALUES AFTER THE DECISION
    for cut_date in get_truncation_cut_date_list(ohlcv_array_dict_in["session_date_list"], window_dict_in):
        truncated_array_dict = get_truncated_ohlcv_dict(ohlcv_array_dict_in, cut_date)
        clock_dict = get_cut_clock_dict(ohlcv_array_dict_in, cut_date)
        truncated_context = None if data_context_in is None else data_context_in.get_truncated_context(clock_dict["session_end_ts"], truncated_array_dict)
        short_result_dict = get_prior_only_result_dict(design_module_in, truncated_array_dict, window_dict_in, truncated_context)
        difference_str = get_lookahead_difference_str(full_result_dict_in, short_result_dict, cut_date)
        if difference_str is not None:
            return f"{cut_date}: {difference_str}"
        perturbed_array_dict = get_perturbed_ohlcv_dict(ohlcv_array_dict_in, cut_date)
        perturbed_context = None if data_context_in is None else data_context_in.get_perturbed_context(clock_dict["decision_ts"], int(pd.Timestamp(cut_date).strftime("%Y%m%d")), perturbed_array_dict)
        perturbed_result_dict = get_prior_only_result_dict(design_module_in, perturbed_array_dict, window_dict_in, perturbed_context)
        perturbed_difference_str = get_lookahead_difference_str(full_result_dict_in, perturbed_result_dict, cut_date)
        if perturbed_difference_str is not None:
            return f"{cut_date} decision bar: {perturbed_difference_str}"
        signal_difference_str = get_signal_difference_str(full_result_dict_in, perturbed_result_dict, cut_date)
        if signal_difference_str is not None:
            return f"{cut_date} decision bar: {signal_difference_str}"
    return None

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
    # APPEND THE ROW
    file_path_str = file_path_str_in or paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR
    os.makedirs(os.path.dirname(file_path_str), exist_ok=True)
    pd.DataFrame([row_dict_in], columns=EVALUATION_COLUMN_LIST).to_csv(file_path_str, mode="a", header=not os.path.isfile(file_path_str), index=False)

# FUNCTION: EVALUATE ONE FROZEN DESIGN ON THE ACTIVE WINDOW
def run_holdout_evaluation(design_module_in, design_id_str_in, ohlcv_array_dict_in, token_file_path_str_in, git_precondition_dict_in=None,
                           design_folder_str_in=".", ledger_path_str_in=None, trial_log_path_str_in=None, source_frame_dict_in=None):
    """
    Nicolas only. Checks the preconditions, replays the frozen prior-only path from the development start through the
    window end, runs the truncation test, and only then writes a result. A design that declares an unregistered
    source raises before any replay and writes no ledger row. A read of a source that is not in DATA_SOURCE_LIST
    (missing means ["SPY_1MIN"]) writes no daily paths and appends a ledger row with status "invalid_undeclared".
    A failed truncation test writes no daily paths and appends a ledger row with status "invalid_lookahead" (it
    counts against the window budget) plus one trial-log row (stage "test", test_window_touched True, note
    "invalid_lookahead", no return metrics).     A valid run writes the holdout paths under
    SO_HOLDOUT_PATH/<window_id>/<design_id>/, and, when the path carried a refit log, refit_log.csv beside them.
    The ledger row records the retraining frequency, the training-window candidates, the holdout refit count, the
    average share purged, turnover per year and the candidate-switch count. It appends one trial-log
    row (stage "test", test_window_touched True).

    Args:
        design_module_in (module): Design
        design_id_str_in (str): Design id
        ohlcv_array_dict_in (dict): Bars from the first session through the window end (nothing after the end)
        token_file_path_str_in (str): Token file
        git_precondition_dict_in (dict | None): Injected git result (may include design_tree_str and so_tree_str)
        design_folder_str_in (str): Design folder for the git probe and the design-tree hash
        ledger_path_str_in (str | None): Ledger CSV
        trial_log_path_str_in (str | None): Trial log CSV (None = the shared trial log)
        source_frame_dict_in (dict | None): Other registered sources already loaded (SPY comes from the bar arrays)

    Returns:
        dict: The ledger row
    """
    # IMPORT THE POINT-IN-TIME DOOR HERE
    from so.core.point_in_time import (get_declared_source_name_list, get_minute_bar_available_ts, get_runner_context,
                                       get_source_spec_dict, set_direct_read_blocked_bool)
    # CHECK EVERY PRECONDITION BEFORE READING THE WINDOW FOR A RESULT
    precondition_dict = check_evaluation_precondition_dict(design_module_in, design_id_str_in, token_file_path_str_in,
                                                           git_precondition_dict_in, design_folder_str_in, ledger_path_str_in)
    window_dict = precondition_dict["window_dict"]
    # AN UNREGISTERED DECLARATION STOPS HERE: NO REPLAY, NO LEDGER ROW
    declared_name_list = get_declared_source_name_list(design_module_in)
    for source_name_str in declared_name_list:
        get_source_spec_dict(source_name_str)
    # THE RUNNER LOADS FIRST, THEN HANDS EVERY SOURCE THROUGH THE CONTEXT
    limit_ts = get_minute_bar_available_ts(ohlcv_array_dict_in["timestamp_index"][-1])
    data_context = get_runner_context(ohlcv_array_dict_in, source_frame_dict_in, limit_ts, declared_name_list)
    # SET THE RUNNER FLAG SO THE WINDOW ITSELF IS READABLE AND THE DAY AFTER IT IS NOT
    global _RUNNER_ACTIVE_BOOL
    _RUNNER_ACTIVE_BOOL = True
    # BLOCK DIRECT LOADS WHILE THE DESIGN RUNS; THE RUNNER ALREADY HOLDS THE FRAMES
    set_direct_read_blocked_bool(True)
    undeclared_error = None
    try:
        # REPLAY THE PATH, THEN THE TRUNCATION TEST, BEFORE ANY RESULT IS WRITTEN
        full_result_dict = get_prior_only_result_dict(design_module_in, ohlcv_array_dict_in, window_dict, data_context)
        failure_str = get_lookahead_failure_str(design_module_in, ohlcv_array_dict_in, window_dict, full_result_dict, data_context)
        report_dict = None if failure_str else get_holdout_report_dict(design_module_in, ohlcv_array_dict_in, window_dict, full_result_dict)
    except ValueError as error:
        # A READ OUTSIDE DATA_SOURCE_LIST IS INVALID; ANY OTHER ERROR STILL PROPAGATES
        if "undeclared source" not in str(error):
            raise
        undeclared_error = error
        failure_str = None
        report_dict = None
    finally:
        # CLEAR BOTH FLAGS EVEN IF THE REPLAY RAISES
        _RUNNER_ACTIVE_BOOL = False
        set_direct_read_blocked_bool(False)
    # BUILD THE LEDGER ROW, INCLUDING THE SOURCES THE DESIGN READ
    row_dict = {"window_id": window_dict["window_id"], "design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"],
                "commit": precondition_dict["commit_str"], "evaluated_ts": datetime.now().isoformat(timespec="seconds"),
                "sources_read": ",".join(data_context.get_access_name_list())}
    # A SOURCE IN THE ACCESS LOG THAT THE DESIGN DID NOT DECLARE IS NOT A VALID RESULT
    undeclared_name_list = [source_name_str for source_name_str in data_context.get_access_name_list() if source_name_str not in declared_name_list]
    if undeclared_error is not None or undeclared_name_list:
        print(f"invalid_undeclared: {undeclared_error or undeclared_name_list}")
        row_dict["status"] = "invalid_undeclared"
        append_holdout_evaluation_dict(row_dict, ledger_path_str_in)
        from so.core.trial_log import log_trial_dict
        log_trial_dict(design_module_in, "test", {"design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"]},
                       {}, True, fold_row_in={"test_start": window_dict["start"], "test_end": window_dict["end"]},
                       note_str_in="invalid_undeclared", file_path_str_in=trial_log_path_str_in, alert_in=False)
        return row_dict
    # A LEAK COUNTS AGAINST THE BUDGET AND WRITES NO PATH
    if failure_str:
        print(f"invalid_lookahead: {failure_str}")
        row_dict["status"] = "invalid_lookahead"
        append_holdout_evaluation_dict(row_dict, ledger_path_str_in)
        from so.core.trial_log import log_trial_dict
        log_trial_dict(design_module_in, "test", {"design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"]},
                       {}, True, fold_row_in={"test_start": window_dict["start"], "test_end": window_dict["end"]},
                       note_str_in="invalid_lookahead", file_path_str_in=trial_log_path_str_in, alert_in=False)
        return row_dict
    # WRITE THE HOLDOUT PATHS ONLY UNDER SO_HOLDOUT_PATH
    results_path_str = os.environ["SO_HOLDOUT_PATH"]
    output_path_str = os.path.join(results_path_str, window_dict["window_id"], design_id_str_in)
    os.makedirs(output_path_str, exist_ok=True)
    report_dict["daily_equity_pdf"].to_csv(os.path.join(output_path_str, "strategy_daily_equity.csv"), index=False)
    report_dict["buy_hold_equity_pdf"].to_csv(os.path.join(output_path_str, "buy_hold_daily_equity.csv"), index=False)
    # THE REFIT LOG OF THE HOLDOUT SEGMENT, NEXT TO THE DAILY PATHS, AND ONLY UNDER SO_HOLDOUT_PATH
    if report_dict.get("refit_log_pdf") is not None:
        report_dict["refit_log_pdf"].to_csv(os.path.join(output_path_str, "refit_log.csv"), index=False)
    # APPEND THE VALID LEDGER ROW AND THE TRIAL-LOG ROW
    report_fields_dict = report_dict["report_dict"]
    row_dict["status"] = "valid"
    row_dict.update(report_fields_dict)
    append_holdout_evaluation_dict(row_dict, ledger_path_str_in)
    from so.core.trial_log import log_trial_dict
    log_trial_dict(design_module_in, "test", {"design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"]},
                   {key_str: report_fields_dict[key_str] for key_str in ["total_return", "buy_hold_total_return", "annualized_log_excess", "primary_pass"]},
                   True, fold_row_in={"test_start": window_dict["start"], "test_end": window_dict["end"]},
                   note_str_in="holdout evaluation", file_path_str_in=trial_log_path_str_in, alert_in=False)
    return row_dict
