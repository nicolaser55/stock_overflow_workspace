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

The holdout is the last HOLDOUT_WINDOW_MONTHS calendar months of the data, ending at the latest session present when
the window is opened. It replaces the per-fold 3-month test windows and the fixed untouched window 2026-05-14 ->
2026-08-13. Its purpose is to measure how a frozen design would have performed if it had been deployed over that year.

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
EVALUATION_COLUMN_LIST = ["window_id", "design_id", "design_hash", "commit", "evaluated_ts", "total_return",
                          "buy_hold_total_return", "annualized_log_excess", "log_excess_ci_low", "log_excess_ci_high",
                          "in_market_pct", "sharpe_ratio", "max_drawdown", "mde", "primary_pass", "secondary_pass",
                          "comparable_pass"]
# DEFINE THE MESSAGE WHEN NO WINDOW IS REGISTERED
NO_WINDOW_MESSAGE_STR = "no holdout window registered: Nicolas must run scripts/holdout_window.py open"
# DEFINE THE RUNNER FLAG (SET ONLY INSIDE run_holdout_evaluation)
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
    # BUILD THE DESIGN HASH (COMMIT + CONFIG HASH)
    from so.core.trial_log import get_config_hash_str
    design_hash_str = f"{git_dict['commit_str']}_{get_config_hash_str(design_module_in)}"
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
Causal Replay
"""

# FUNCTION: GET THE FIRST DATE OF A TRAINING WINDOW
def get_train_start_date(exclusive_date_in, train_window_str_in):
    """
    The day a training window opens: exclusive_date minus "6M" or "1Y".

    Args:
        exclusive_date_in (datetime.date): Decision session (not included)
        train_window_str_in (str): "6M" or "1Y"

    Returns:
        datetime.date: First date included
    """
    # PARSE THE WINDOW
    window_str = str(train_window_str_in).upper()
    if window_str.endswith("M"):
        return (pd.Timestamp(exclusive_date_in) - pd.DateOffset(months=int(window_str[:-1]))).date()
    if window_str.endswith("Y"):
        return (pd.Timestamp(exclusive_date_in) - pd.DateOffset(years=int(window_str[:-1]))).date()
    raise ValueError(f"❌ Unknown train window {train_window_str_in}")

# FUNCTION: BUILD THE CAUSAL FRAME A FIT MAY SEE
def get_fit_frame_pdf(session_pdf_in, exclusive_date_in, train_window_str_in):
    """
    Sessions strictly before the decision date and inside the training window.

    Args:
        session_pdf_in (pd.DataFrame): One row per session (date, ...)
        exclusive_date_in (datetime.date): Decision session
        train_window_str_in (str): Training window

    Returns:
        pd.DataFrame: The frame
    """
    # CUT THE FRAME
    train_start_date = get_train_start_date(exclusive_date_in, train_window_str_in)
    date_arr = pd.to_datetime(session_pdf_in["date"]).dt.date
    return session_pdf_in[(date_arr < exclusive_date_in) & (date_arr >= train_start_date)].reset_index(drop=True)

# FUNCTION: REFIT AND DECIDE ONE SESSION
def get_session_decision_dict(design_module_in, session_pdf_in, session_date_in, candidate_in=None):
    """
    Refits on data strictly before session_date_in and asks for the target exposure. A model state that reports
    last_date_seen on or after the decision session is a leak and raises.

    Args:
        design_module_in (module): Design (fit, decide, DESIGN_REFIT_RULE)
        session_pdf_in (pd.DataFrame): All sessions the runner holds
        session_date_in (datetime.date): Decision session
        candidate_in (str | None): Candidate name

    Returns:
        dict: model_state_dict, exposure_float
    """
    # BUILD THE FRAME AND REFUSE A FRAME THAT REACHES THE DECISION
    rule_dict = design_module_in.DESIGN_REFIT_RULE
    frame_pdf = get_fit_frame_pdf(session_pdf_in, session_date_in, rule_dict["train_window"])
    if len(frame_pdf) and get_date(frame_pdf["date"].max()) >= get_date(session_date_in):
        raise ValueError("❌ Fit frame includes the decision session.")
    # FIT AND REFUSE A LEAK THE DESIGN REPORTS
    model_state_dict = design_module_in.fit(frame_pdf, session_date_in)
    if "last_date_seen" in model_state_dict and get_date(model_state_dict["last_date_seen"]) >= get_date(session_date_in):
        raise ValueError("❌ The design saw the decision session or a later date.")
    # DECIDE FROM INFORMATION KNOWN BEFORE THE SESSION
    prior_pdf = session_pdf_in[pd.to_datetime(session_pdf_in["date"]).dt.date < get_date(session_date_in)]
    feature_dict = {"candidate": candidate_in, "prior_close": None if prior_pdf.empty else float(prior_pdf["close"].iloc[-1])}
    exposure_float = float(design_module_in.decide(model_state_dict, session_date_in, feature_dict))
    # RETURN THE DECISION
    return {"model_state_dict": model_state_dict, "exposure_float": exposure_float}

# FUNCTION: BUILD THE TARGET-WEIGHT ARRAY OF ONE CANDIDATE OVER THE WINDOW
def get_exposure_arr(design_module_in, session_pdf_in, window_date_list_in, candidate_in=None):
    """
    Walks the window session by session. fit is called on the design's refit schedule; between refits the previous
    model state is reused. Every fit sees only earlier sessions.

    Args:
        design_module_in (module): Design
        session_pdf_in (pd.DataFrame): Sessions (date, close), including history before the window
        window_date_list_in (list[datetime.date]): Holdout sessions
        candidate_in (str | None): Candidate

    Returns:
        np.ndarray: Target exposure per window session
    """
    # COLLECT THE REFIT STEP
    every_sessions = int(design_module_in.DESIGN_REFIT_RULE["every_sessions"])
    exposure_list, model_state_dict = [], None
    # ITERATE OVER THE WINDOW
    for session_pos, session_date in enumerate(window_date_list_in):
        # REFIT ON THE SCHEDULE AND ON THE FIRST SESSION
        if model_state_dict is None or session_pos % every_sessions == 0:
            decision_dict = get_session_decision_dict(design_module_in, session_pdf_in, session_date, candidate_in)
            model_state_dict = decision_dict["model_state_dict"]
            exposure_list.append(decision_dict["exposure_float"])
        else:
            # REUSE THE MODEL STATE (THE FEATURES ARE STILL ONLY THE PRIOR CLOSE)
            prior_pdf = session_pdf_in[pd.to_datetime(session_pdf_in["date"]).dt.date < get_date(session_date)]
            feature_dict = {"candidate": candidate_in, "prior_close": float(prior_pdf["close"].iloc[-1])}
            exposure_list.append(float(design_module_in.decide(model_state_dict, session_date, feature_dict)))
    # RETURN THE ARRAY
    return np.array(exposure_list, dtype=float)

# FUNCTION: SPLIT A WINDOW INTO CALENDAR MONTHS
def get_month_span_list(window_date_list_in):
    """
    One (start, end) pair per calendar month of the window.

    Args:
        window_date_list_in (list[datetime.date]): Holdout sessions

    Returns:
        list[tuple]: (first session, last session) of each month
    """
    # GROUP THE SESSIONS BY MONTH
    month_dict = {}
    for session_date in window_date_list_in:
        month_dict.setdefault((session_date.year, session_date.month), []).append(session_date)
    # RETURN THE SPANS IN ORDER
    return [(date_list[0], date_list[-1]) for _, date_list in sorted(month_dict.items())]

# FUNCTION: SELECT CANDIDATES PERIOD BY PERIOD AND BUILD ONE EXPOSURE PATH
def get_selected_exposure_arr(design_module_in, session_pdf_in, window_date_list_in):
    """
    If the design has no CANDIDATE_LIST, one exposure path. If it has candidates and selection_rule, each month is
    governed by the candidate selected from completed earlier months only (the first month uses an empty history).

    Args:
        design_module_in (module): Design
        session_pdf_in (pd.DataFrame): Sessions
        window_date_list_in (list[datetime.date]): Holdout sessions

    Returns:
        np.ndarray: Target exposure per window session
    """
    # WITHOUT CANDIDATES, REPLAY THE SINGLE RULE
    candidate_list = list(getattr(design_module_in, "CANDIDATE_LIST", []) or [])
    if not candidate_list:
        return get_exposure_arr(design_module_in, session_pdf_in, window_date_list_in)
    # SCORE EVERY CANDIDATE OVER THE WHOLE WINDOW FIRST (EACH DECISION IS CAUSAL)
    exposure_dict = {candidate: get_exposure_arr(design_module_in, session_pdf_in, window_date_list_in, candidate) for candidate in candidate_list}
    date_to_pos = {get_date(session_date): pos for pos, session_date in enumerate(window_date_list_in)}
    # WALK THE MONTHS, SELECTING FROM COMPLETED MONTHS ONLY
    selected_list, completed_dict_list = [], []
    for month_start, month_end in get_month_span_list(window_date_list_in):
        selected = design_module_in.selection_rule(pd.DataFrame(completed_dict_list))
        # COPY THE SELECTED CANDIDATE'S EXPOSURE FOR THIS MONTH
        for session_date in window_date_list_in:
            if month_start <= get_date(session_date) <= month_end:
                selected_list.append(exposure_dict[selected][date_to_pos[get_date(session_date)]])
        # RECORD EACH CANDIDATE'S MEAN EXPOSURE ON THE COMPLETED MONTH (A SCORE THAT USES ONLY THAT MONTH)
        for candidate in candidate_list:
            month_exposure_arr = np.array([exposure_dict[candidate][date_to_pos[get_date(session_date)]]
                                           for session_date in window_date_list_in if month_start <= get_date(session_date) <= month_end])
            completed_dict_list.append({"candidate": candidate, "period_end": month_end, "mean_exposure": float(month_exposure_arr.mean())})
    # RETURN THE PATH
    return np.array(selected_list, dtype=float)

# FUNCTION: REPLAY THE HOLDOUT AND BUILD THE REPORT
def get_holdout_report_dict(design_module_in, ohlcv_array_dict_in, window_dict_in, baseline_return_dict_in=None):
    """
    One continuous fractional-exposure path over the window (costs from so.config), buy-and-hold over the same
    sessions, the annualized log excess with a 6-month block bootstrap, time in the market, Sharpe, maximum
    drawdown, the minimum detectable effect of the monthly log excess, and the project success criteria.

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        window_dict_in (dict): Active window (start, end)
        baseline_return_dict_in (dict | None): Uninformed baselines the protocol names (name -> total return)

    Returns:
        dict: report_dict, daily_equity_pdf, buy_hold_equity_pdf
    """
    # IMPORT THE REPLAY AND EVALUATION FUNCTIONS HERE (AVOID AN IMPORT CYCLE)
    from so.core.fractional_exposure import simulate_fractional_exposure_dict
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    from so.core.evaluation import get_chained_daily_return_pdf, get_success_criteria_dict, get_mde_float
    from so.core.continuous_replay import get_log_excess_bootstrap_dict
    # BUILD A SESSION TABLE AND THE WINDOW SESSIONS
    session_pdf = pd.DataFrame({"date": ohlcv_array_dict_in["session_date_list"],
                                "close": [float(ohlcv_array_dict_in["close_arr"][idx]) for idx in ohlcv_array_dict_in["session_end_idx_arr"]]})
    start_date, end_date = get_date(window_dict_in["start"]), get_date(window_dict_in["end"])
    window_date_list = [get_date(session_date) for session_date in session_pdf["date"] if start_date <= get_date(session_date) <= end_date]
    # BUILD THE EXPOSURE OF THE WINDOW AND ALIGN IT TO EVERY SESSION OF THE ARRAYS
    window_exposure_arr = get_selected_exposure_arr(design_module_in, session_pdf, window_date_list)
    target_arr = np.full(len(session_pdf), np.nan)
    window_pos_list = [pos for pos, session_date in enumerate(session_pdf["date"]) if start_date <= get_date(session_date) <= end_date]
    target_arr[window_pos_list] = window_exposure_arr
    # REPLAY THE PATH AND BUY-AND-HOLD (THE RUNNER FLAG IS ALREADY SET BY THE CALLER)
    simulation_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, start_date, end_date, target_arr, dead_band_in=0.0,
                                                       initial_weight_in=float(window_exposure_arr[0]))
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, start_date, end_date)
    # CALCULATE THE LOG EXCESS, THE SUCCESS CRITERIA AND THE MDE
    strategy_return_pdf = get_chained_daily_return_pdf([simulation_dict["daily_equity_pdf"]])
    buy_hold_return_pdf = get_chained_daily_return_pdf([buy_hold_dict["daily_equity_pdf"]])
    log_excess_dict = get_log_excess_bootstrap_dict(strategy_return_pdf, buy_hold_return_pdf, block_month_count_in=6)
    success_dict = get_success_criteria_dict(strategy_return_pdf, buy_hold_return_pdf, baseline_return_dict_in)
    merged_pdf = strategy_return_pdf.merge(buy_hold_return_pdf, on="date", suffixes=("_strategy", "_buy_hold"))
    merged_pdf["month"] = pd.to_datetime(merged_pdf["date"]).dt.to_period("M")
    month_pdf = merged_pdf.groupby("month").agg(strategy_log=("daily_return_strategy", lambda series: float(np.log1p(series).sum())),
                                                buy_hold_log=("daily_return_buy_hold", lambda series: float(np.log1p(series).sum())))
    month_excess_arr = (month_pdf["strategy_log"] - month_pdf["buy_hold_log"]).to_numpy(dtype=float)
    # RETURN THE REPORT
    report_dict = {"total_return": success_dict["strategy_total_return"], "buy_hold_total_return": success_dict["buy_hold_total_return"],
                   "annualized_log_excess": log_excess_dict["annualized_log_excess"], "log_excess_ci_low": log_excess_dict["ci_low"],
                   "log_excess_ci_high": log_excess_dict["ci_high"], "in_market_pct": float(simulation_dict["daily_equity_pdf"]["in_position"].mean()),
                   "sharpe_ratio": success_dict["strategy_sharpe_ratio"], "max_drawdown": success_dict["strategy_max_drawdown"],
                   "mde": get_mde_float(float(np.std(month_excess_arr, ddof=1)) if len(month_excess_arr) > 1 else np.nan, len(month_excess_arr)),
                   "primary_pass": success_dict["primary_success"], "secondary_pass": success_dict["secondary_success"],
                   "comparable_pass": success_dict["comparable_return"], "baselines_beaten": success_dict["baselines_beaten"]}
    return {"report_dict": report_dict, "daily_equity_pdf": simulation_dict["daily_equity_pdf"], "buy_hold_equity_pdf": buy_hold_dict["daily_equity_pdf"]}

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
                           design_folder_str_in=".", baseline_return_dict_in=None, ledger_path_str_in=None, trial_log_path_str_in=None):
    """
    Nicolas only. Checks the preconditions, replays the design over the active window with the runner flag set, writes
    the daily paths under SO_HOLDOUT_PATH/<window_id>/<design_id>/, appends one ledger row and one trial-log row
    (stage "test", test_window_touched True).

    Args:
        design_module_in (module): Design
        design_id_str_in (str): Design id
        ohlcv_array_dict_in (dict): Bars the replay may use (history before the window included; nothing after the end)
        token_file_path_str_in (str): Token file
        git_precondition_dict_in (dict | None): Injected git result
        design_folder_str_in (str): Design folder for the git probe
        baseline_return_dict_in (dict | None): Protocol baselines
        ledger_path_str_in (str | None): Ledger CSV
        trial_log_path_str_in (str | None): Trial log CSV (None = the shared trial log)

    Returns:
        dict: The ledger row
    """
    # CHECK EVERY PRECONDITION BEFORE READING THE WINDOW FOR A RESULT
    precondition_dict = check_evaluation_precondition_dict(design_module_in, design_id_str_in, token_file_path_str_in,
                                                           git_precondition_dict_in, design_folder_str_in, ledger_path_str_in)
    window_dict = precondition_dict["window_dict"]
    # SET THE RUNNER FLAG FOR THE REPLAY ONLY
    global _RUNNER_ACTIVE_BOOL
    _RUNNER_ACTIVE_BOOL = True
    try:
        # REPLAY THE WINDOW
        result_dict = get_holdout_report_dict(design_module_in, ohlcv_array_dict_in, window_dict, baseline_return_dict_in)
    finally:
        # CLEAR THE FLAG EVEN IF THE REPLAY RAISES
        _RUNNER_ACTIVE_BOOL = False
    # WRITE THE DAILY PATHS ONLY UNDER SO_HOLDOUT_PATH
    results_path_str = os.environ["SO_HOLDOUT_PATH"]
    output_path_str = os.path.join(results_path_str, window_dict["window_id"], design_id_str_in)
    os.makedirs(output_path_str, exist_ok=True)
    result_dict["daily_equity_pdf"].to_csv(os.path.join(output_path_str, "strategy_daily_equity.csv"), index=False)
    result_dict["buy_hold_equity_pdf"].to_csv(os.path.join(output_path_str, "buy_hold_daily_equity.csv"), index=False)
    # APPEND THE LEDGER ROW
    report_dict = result_dict["report_dict"]
    row_dict = {"window_id": window_dict["window_id"], "design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"],
                "commit": precondition_dict["commit_str"], "evaluated_ts": datetime.now().isoformat(timespec="seconds"),
                **{key_str: report_dict[key_str] for key_str in EVALUATION_COLUMN_LIST if key_str in report_dict}}
    append_holdout_evaluation_dict(row_dict, ledger_path_str_in)
    # APPEND THE TRIAL-LOG ROW
    from so.core.trial_log import log_trial_dict
    log_trial_dict(design_module_in, "test", {"design_id": design_id_str_in, "design_hash": precondition_dict["design_hash_str"]},
                   {key_str: report_dict[key_str] for key_str in ["total_return", "buy_hold_total_return", "annualized_log_excess", "primary_pass"]},
                   True, fold_row_in={"test_start": window_dict["start"], "test_end": window_dict["end"]},
                   note_str_in="holdout evaluation", file_path_str_in=trial_log_path_str_in, alert_in=False)
    # RETURN THE LEDGER ROW
    return row_dict
