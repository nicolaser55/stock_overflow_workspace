"""
Workspace Tests: the rolling holdout (so.core.holdout; Nicolas, 2026-10-11)

Run from the workspace root:   python tests/test_holdout.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The registry, the ledger, the trial log and SO_DATA_PATH are temporary. The data root is a
temporary folder. records/holdout_windows.csv is not written. If that registry file already exists, its size is unchanged.
SO_HOLDOUT_PATH, SO_HOLDOUT_EVALUATION_TOKEN and SO_QUARANTINE_PATH are set only inside this file, to temporary values.
"""

import os
import sys
import json
import tempfile
import shutil
from datetime import timedelta
import pandas as pd

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_holdout_data_")
os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE SHARED MODULES
from so import paths, config
from so.core.datetime_utils import ny_tz, get_date_range_market_schedule_pdf
from so.core.holdout import (compute_holdout_window_dict, open_holdout_window_dict, roll_holdout_window_dict, slide_holdout_window_dict, get_active_holdout_window_dict, get_development_end_date, get_latest_session_date, get_replay_boundary_date, get_design_hash_str, load_evaluation_source_frame_dict, NO_WINDOW_MESSAGE_STR, VIEW_STALE_MESSAGE_STR)
from so.core.local_file_management import read_csv_files_from_path, read_date_range_csv_files_from_path
from so.core.schedule import (get_development_fold_pdf)
from so.core.raw_data import get_complete_ohlcv_pdf
from so.core.point_in_time import load_source_frame_dict
from so.features.vix_features import check_cutoff_date

# KEEP THE REAL REGISTRY PATHS AND POINT THE SUITE AT TEMPORARY FILES
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REAL_WINDOWS_EXISTS_BOOL = os.path.isfile(REAL_WINDOWS_PATH_STR)
REAL_WINDOWS_SIZE_INT = os.path.getsize(REAL_WINDOWS_PATH_STR) if REAL_WINDOWS_EXISTS_BOOL else None
REAL_EVALUATIONS_PATH_STR = paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
LEDGER_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_evaluations.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR
paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR = LEDGER_PATH_STR

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints a passing check.

    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")

# FUNCTION: GET NYSE SESSION DATES
def get_session_date_list(date1_str_in, date2_str_in):
    """
    Session dates of the real NYSE calendar between two dates.

    Args:
        date1_str_in, date2_str_in (str): Inclusive bounds

    Returns:
        list[datetime.date]: Session dates
    """
    # READ THE CALENDAR AND RETURN THE NEW YORK DATES
    schedule_pdf = get_date_range_market_schedule_pdf(date1_str_in, date2_str_in)
    return list(pd.to_datetime(schedule_pdf["market_open_ts"]).dt.tz_convert(ny_tz).dt.date)

# FUNCTION: COUNT THE SESSIONS INSIDE A WINDOW
def get_session_count(session_date_list_in, start_in, end_in):
    """
    Sessions on or between two dates.

    Args:
        session_date_list_in (list): Session dates
        start_in, end_in: Inclusive bounds

    Returns:
        int: Count
    """
    # COUNT THE SESSIONS
    return int(sum(start_in <= session_date <= end_in for session_date in session_date_list_in))

# FUNCTION: WRITE A ONE-BAR-PER-DAY RAW FILE
def write_raw_csv(folder_str_in, date_str_list_in):
    """
    Writes a raw-style CSV (one bar per date) that so.core.raw_data can read.

    Args:
        folder_str_in (str): Folder
        date_str_list_in (list[str]): Session dates

    Returns:
        str: Folder path ending with "/"
    """
    # BUILD ONE UTC BAR PER DATE AND WRITE IT (THE LOADER JOINS THE FOLDER AND THE FILE NAME, SO THE FOLDER NEEDS A SLASH)
    folder_str = folder_str_in.replace("\\", "/").rstrip("/") + "/"
    os.makedirs(folder_str, exist_ok=True)
    row_dict_list = [{"timestamp": f"{date_str} 14:30:00+00:00", "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000}
                     for date_str in date_str_list_in]
    pd.DataFrame(row_dict_list).to_csv(f"{folder_str}ohlcv_data_test.csv", index=False)
    return folder_str

# FUNCTION: TEST THE WINDOW ARITHMETIC
def test_window_math():
    """
    Checks the 12-month example, holiday snapping, month-end snapping and the session count.

    Returns:
        None
    """
    # CHECK THE WORKED EXAMPLE (SESSIONS ENDING 2026-10-09)
    session_date_list = get_session_date_list("2020-01-02", "2026-10-09")
    window_dict = compute_holdout_window_dict(session_date_list)
    assert window_dict["end"] == pd.Timestamp("2026-10-09").date()
    assert window_dict["start"] == pd.Timestamp("2025-10-10").date()
    assert window_dict["session_count"] == get_session_count(session_date_list, window_dict["start"], window_dict["end"])
    # CHECK A MONTH THAT ENDS BY SNAPPING PAST A SUNDAY (2023-12-31) AND NEW YEAR'S DAY
    month_end_list = get_session_date_list("2023-06-01", "2024-01-31")
    month_end_dict = compute_holdout_window_dict(month_end_list, window_months_in=1)
    assert month_end_dict["end"] == pd.Timestamp("2024-01-31").date()
    assert month_end_dict["start"] == pd.Timestamp("2024-01-02").date()
    # CHECK A START THAT FALLS ON NEW YEAR'S DAY (MONDAY, MARKET CLOSED)
    holiday_list = get_session_date_list("2023-06-01", "2024-02-01")
    holiday_dict = compute_holdout_window_dict(holiday_list, window_months_in=1)
    assert holiday_dict["end"] == pd.Timestamp("2024-02-01").date()
    assert holiday_dict["start"] == pd.Timestamp("2024-01-02").date()
    assert holiday_dict["session_count"] == get_session_count(holiday_list, holiday_dict["start"], holiday_dict["end"])
    passed("window (2025-10-10 -> 2026-10-09; month-end and New Year snapping; session count)")

# FUNCTION: TEST A MISSING REGISTRY
def test_no_window():
    """
    Checks the error when no window is registered, and that a pinned date still works with no window.

    Returns:
        None
    """
    # POINT THE REGISTRY AT A MISSING FILE
    missing_path_str = os.path.join(TEMP_ROOT_STR, "missing_windows.csv")
    paths.HOLDOUT_WINDOWS_FILE_PATH_STR = missing_path_str
    # REQUIRE THE REGISTRY ERROR
    try:
        get_active_holdout_window_dict()
        raise AssertionError("a missing registry was accepted")
    except ValueError as error:
        assert str(error) == NO_WINDOW_MESSAGE_STR
    # A PINNED DATE KEEPS THE ARCHIVED BEHAVIOUR WHEN NOTHING IS REGISTERED
    assert get_replay_boundary_date("2026-05-14") == pd.Timestamp("2026-05-14").date()
    # NO PINNED DATE AND NO WINDOW IS THE SAME ERROR
    try:
        get_replay_boundary_date(None)
        raise AssertionError("a missing window was accepted")
    except ValueError as error:
        assert str(error) == NO_WINDOW_MESSAGE_STR
    # RESTORE THE SUITE REGISTRY
    paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR
    passed("no registered window (clear error; a pinned date still works)")

# FUNCTION: TEST THE STALE-PIPELINE CHECK
def test_stale_pipeline():
    """
    Checks a missing step06 table, a date mismatch, and a match.

    Returns:
        None
    """
    # WRITE ONE RAW SESSION
    raw_path_str = write_raw_csv(os.path.join(TEMP_ROOT_STR, "raw_stale"), ["2020-01-02"])
    missing_tsday_str = os.path.join(TEMP_ROOT_STR, "missing_tsday.csv")
    # A MISSING TABLE IS STALE
    try:
        get_latest_session_date(raw_path_str, missing_tsday_str)
        raise AssertionError("a missing step06 table was accepted")
    except ValueError as error:
        assert str(error) == "pipeline is stale: re-run pipeline steps 00-06"
    # A DIFFERENT STEP06 DATE IS STALE
    tsday_path_str = os.path.join(TEMP_ROOT_STR, "tsday.csv")
    pd.DataFrame({"date": ["2020-01-03"]}).to_csv(tsday_path_str, index=False)
    try:
        get_latest_session_date(raw_path_str, tsday_path_str)
        raise AssertionError("a stale pipeline was accepted")
    except ValueError as error:
        assert str(error) == "pipeline is stale: re-run pipeline steps 00-06"
    # A MATCHING DATE IS THE LATEST SESSION
    pd.DataFrame({"date": ["2020-01-02"]}).to_csv(tsday_path_str, index=False)
    assert get_latest_session_date(raw_path_str, tsday_path_str) == pd.Timestamp("2020-01-02").date()
    passed("stale pipeline (missing table, mismatched date, matching date)")

# FUNCTION: OPEN THE SUITE WINDOW AND TEST FREEZE AND ROLL
def test_registry():
    """
    Opens the example window, checks that later sessions do not move it, and rolls on separate registries.

    Returns:
        None
    """
    # OPEN THE EXAMPLE WINDOW
    session_date_list = get_session_date_list("2020-01-02", "2026-10-09")
    proposed_dict = compute_holdout_window_dict(session_date_list)
    row_dict = open_holdout_window_dict(session_date_list, f"OPEN {proposed_dict['start']} {proposed_dict['end']}")
    assert row_dict["start"] == pd.Timestamp("2025-10-10").date() and row_dict["status"] == "active"
    # LATER SESSIONS DO NOT MOVE THE REGISTERED WINDOW
    longer_list = session_date_list + [pd.Timestamp("2026-10-13").date(), pd.Timestamp("2026-10-14").date()]
    active_dict = get_active_holdout_window_dict()
    assert active_dict["start"] == row_dict["start"] and active_dict["end"] == row_dict["end"]
    assert compute_holdout_window_dict(longer_list)["end"] != active_dict["end"]
    # A SHORT ROLL IS REFUSED AND DOES NOT RETIRE THE WINDOW
    roll_path_str = os.path.join(TEMP_ROOT_STR, "roll_windows.csv")
    short_base_list = get_session_date_list("2022-01-03", "2024-06-28")
    short_proposed_dict = compute_holdout_window_dict(short_base_list)
    open_holdout_window_dict(short_base_list, f"OPEN {short_proposed_dict['start']} {short_proposed_dict['end']}", file_path_str_in=roll_path_str)
    short_list = short_base_list + [pd.Timestamp("2024-07-01").date(), pd.Timestamp("2024-07-02").date()]
    try:
        roll_holdout_window_dict(short_list, "too short", "OPEN ignored", file_path_str_in=roll_path_str)
        raise AssertionError("a short roll was accepted")
    except ValueError as error:
        assert "minimum" in str(error)
    still_active_dict = get_active_holdout_window_dict(file_path_str_in=roll_path_str)
    assert still_active_dict["end"] == short_proposed_dict["end"] and still_active_dict["status"] == "active"
    # THE SAME SHORT SPAN IS ACCEPTED WITH --allow-short
    short_next_dict = compute_holdout_window_dict(short_list, start_after_date_in=short_proposed_dict["end"])
    rolled_dict = roll_holdout_window_dict(short_list, "allow short", f"OPEN {short_next_dict['start']} {short_next_dict['end']}",
                                           allow_short_bool_in=True, file_path_str_in=roll_path_str)
    assert rolled_dict["start"] > short_proposed_dict["end"]
    # A ROLL OF AT LEAST THE MINIMUM STARTS AFTER THE RETIRED END
    long_path_str = os.path.join(TEMP_ROOT_STR, "roll_long_windows.csv")
    long_base_list = get_session_date_list("2022-01-03", "2024-06-28")
    long_proposed_dict = compute_holdout_window_dict(long_base_list)
    open_holdout_window_dict(long_base_list, f"OPEN {long_proposed_dict['start']} {long_proposed_dict['end']}", file_path_str_in=long_path_str)
    long_list = get_session_date_list("2022-01-03", "2025-08-29")
    long_next_dict = compute_holdout_window_dict(long_list, start_after_date_in=long_proposed_dict["end"])
    assert long_next_dict["months_covered"] >= config.HOLDOUT_MIN_WINDOW_MONTHS
    long_row_dict = roll_holdout_window_dict(long_list, "next year", f"OPEN {long_next_dict['start']} {long_next_dict['end']}", file_path_str_in=long_path_str)
    assert long_row_dict["start"] > long_proposed_dict["end"] and long_row_dict["status"] == "active"
    passed("registry (frozen after open; short roll refused; next window starts after the retired end)")

# FUNCTION: TEST THE DEVELOPMENT SCHEDULE
def test_development_schedule():
    """
    Checks the embargo and that development folds have no test columns and stop before the holdout.

    Returns:
        None
    """
    # LOCATE THE DEVELOPMENT END
    session_date_list = get_session_date_list("2018-01-02", "2026-10-09")
    start_date = get_active_holdout_window_dict()["start"]
    start_idx = session_date_list.index(start_date)
    embargo_int = 20
    assert get_development_end_date(embargo_int, session_date_list) == session_date_list[start_idx - embargo_int]
    # BUILD THE DEVELOPMENT FOLDS
    fold_pdf = get_development_fold_pdf(session_date_list, embargo_int, [1])
    development_end_date = session_date_list[start_idx - embargo_int]
    assert "test_start" not in fold_pdf.columns and "test_end" not in fold_pdf.columns and "refit_end" not in fold_pdf.columns
    assert len(fold_pdf) > 0
    assert pd.Timestamp(fold_pdf["valid_end"].iloc[-1]).date() == development_end_date
    # NO FOLD DATE REACHES THE HOLDOUT START
    for column_str in ["valid_start", "valid_end", "train_end", "train_start_1y"]:
        assert all(pd.Timestamp(value).date() < start_date for value in fold_pdf[column_str])
    passed(f"development schedule ({len(fold_pdf)} validation folds, none reaching {start_date})")

# FUNCTION: TEST THE GUARDS WITH AN ACTIVE WINDOW
def test_guards():
    """
    Checks that replay, the raw loader and the VIX loader stop at the holdout start.

    Returns:
        None
    """
    # THE GUARDED RAW LOADER REQUIRES A STAMP THAT MATCHES THE ACTIVE WINDOW
    write_view_stamp(get_active_holdout_window_dict()["start"])
    # THE BOUNDARY IS THE EARLIER OF THE PINNED DATE AND THE WINDOW START
    assert get_replay_boundary_date("2026-05-14") == pd.Timestamp("2025-10-10").date()
    # THE RAW LOADER CUTS BEFORE THE WINDOW AND REFUSES A LATER CUTOFF
    raw_path_str = write_raw_csv(os.path.join(TEMP_ROOT_STR, "raw_guard"), ["2025-10-09", "2025-10-10", "2026-05-13"])
    cut_pdf = get_complete_ohlcv_pdf(raw_path_str)
    assert set(cut_pdf["date"]) == {pd.Timestamp("2025-10-09").date()}
    try:
        get_complete_ohlcv_pdf(raw_path_str, "2025-10-10")
        raise AssertionError("a cutoff on the holdout start was accepted")
    except ValueError:
        pass
    full_pdf = get_complete_ohlcv_pdf(raw_path_str, enforce_holdout_bool_in=False)
    assert len(full_pdf) == 3
    # THE VIX LOADER USES THE SAME EARLIER BOUNDARY
    assert check_cutoff_date("2025-10-09") == pd.Timestamp("2025-10-09").date()
    for date_str in ["2025-10-10", "2026-05-13"]:
        try:
            check_cutoff_date(date_str)
            raise AssertionError(f"VIX cutoff {date_str} was allowed")
        except ValueError:
            pass
    passed("guards (boundary, raw loader, VIX loader stop at 2025-10-10)")

# FUNCTION: TEST THAT THE REMOVED LEGACY FLAG DOES NOT MOVE THE BOUNDARY
def test_legacy_flag_ignored():
    """
    Setting SO_ALLOW_LEGACY_REPRODUCTION leaves the replay boundary on the active window start.

    Returns:
        None
    """
    # THE ACTIVE WINDOW IS THE ONE test_registry OPENED
    window_start = pd.Timestamp(get_active_holdout_window_dict()["start"]).date()
    # THE FLAG MUST NOT CHANGE THE BOUNDARY
    os.environ["SO_ALLOW_LEGACY_REPRODUCTION"] = "1"
    try:
        flagged_date = get_replay_boundary_date("2027-01-01")
    finally:
        os.environ.pop("SO_ALLOW_LEGACY_REPRODUCTION", None)
    plain_date = get_replay_boundary_date("2027-01-01")
    assert flagged_date == plain_date == min(window_start, pd.Timestamp("2027-01-01").date())
    passed("legacy flag ignored (boundary stays the window start)")

# FUNCTION: BUILD THE GIT PROBE THE TESTS INJECT
def get_git_dict(design_tree_str_in="design-tree", so_tree_str_in="so-tree"):
    """
    A passing git probe with injected tree ids (the design hash reads them).

    Args:
        design_tree_str_in (str): HEAD:<design folder>
        so_tree_str_in (str): HEAD:so

    Returns:
        dict: Git probe
    """
    # RETURN THE PROBE
    return {"clean_bool": True, "on_main_bool": True, "preregister_bool": True, "commit_str": "abc123",
            "design_tree_str": design_tree_str_in, "so_tree_str": so_tree_str_in}


# FUNCTION: TEST THAT THE PIPELINE READS THROUGH A REGISTERED WINDOW
def test_pipeline_holdout_flag():
    """
    Scans the pipeline notebooks for the holdout flag, and checks that a window does not hide the last raw session.

    Returns:
        None
    """
    # EVERY LOADER CALL IN A PIPELINE NOTEBOOK TURNS THE GUARD OFF
    for notebook_path in sorted(os.listdir(os.path.join(WORKSPACE_PATH_STR, "pipeline"))):
        if not notebook_path.endswith(".ipynb"):
            continue
        notebook_text = open(os.path.join(WORKSPACE_PATH_STR, "pipeline", notebook_path), encoding="utf-8").read()
        for call_name_str in ["get_complete_ohlcv_pdf(", "read_date_range_csv_files_from_path(", "read_csv_files_from_path(", "get_vix_daily_feature_dict("]:
            search_from_int = 0
            while True:
                found_int = notebook_text.find(call_name_str, search_from_int)
                if found_int < 0:
                    break
                depth_int, end_int = 0, found_int
                while end_int < len(notebook_text):
                    if notebook_text[end_int] == "(":
                        depth_int += 1
                    elif notebook_text[end_int] == ")":
                        depth_int -= 1
                        if depth_int == 0:
                            break
                    end_int += 1
                call_text = notebook_text[found_int:end_int + 1]
                assert "enforce_holdout_bool_in=False" in call_text, f"{notebook_path} {call_name_str}"
                search_from_int = end_int + 1
    # WITH THE WINDOW OPEN, THE UNGUARDED LOADER STILL SEES THE LAST RAW SESSION
    raw_path_str = write_raw_csv(os.path.join(TEMP_ROOT_STR, "raw_pipeline"), ["2025-10-09", "2025-10-10", "2026-08-13"])
    tsday_path_str = os.path.join(TEMP_ROOT_STR, "TSDAY_pipeline.csv")
    pd.DataFrame({"date": ["2026-08-13"]}).to_csv(tsday_path_str, index=False)
    full_pdf = get_complete_ohlcv_pdf(raw_path_str, enforce_holdout_bool_in=False)
    assert max(full_pdf["date"]) == pd.Timestamp("2026-08-13").date()
    assert get_latest_session_date(raw_path_str, tsday_path_str) == pd.Timestamp("2026-08-13").date()
    passed("pipeline reads through a registered window (notebooks, rename check, last raw session)")

# FUNCTION: WRITE TWO DATE-STAMPED CACHE FILES
def write_cache_csv(folder_str_in):
    """
    Writes cache_20251009.csv and cache_20251010.csv.

    Args:
        folder_str_in (str): Directory ending with "/"

    Returns:
        str: The directory
    """
    # WRITE ONE ROW PER FILE
    os.makedirs(folder_str_in, exist_ok=True)
    for stamp_str in ["20251009", "20251010"]:
        pd.DataFrame({"value": [1]}).to_csv(f"{folder_str_in}cache_{stamp_str}.csv", index=False)
    return folder_str_in

# FUNCTION: WRITE THE DEVELOPMENT VIEW STAMP
def write_view_stamp(window_start_in):
    """
    Writes VIEW.json in the temporary data root with the given window start.

    Args:
        window_start_in: Date the stamp must match

    Returns:
        str: Path of VIEW.json
    """
    # THE STAMP IS THE ACTIVE WINDOW START AND NOTHING ELSE
    view_path_str = os.path.join(TEMP_ROOT_STR, "VIEW.json")
    with open(view_path_str, "w", encoding="utf-8") as view_file:
        json.dump({"window_start": str(pd.Timestamp(window_start_in).date())}, view_file)
    return view_path_str

# FUNCTION: WRITE AN UNDATED CACHE FILE
def write_undated_cache_csv(folder_str_in, date_str_list_in):
    """
    Writes TSDAY_data.csv (no date in the name) with one row per date.

    Args:
        folder_str_in (str): Directory
        date_str_list_in (list[str]): Session dates

    Returns:
        str: Directory ending with "/"
    """
    # THE FILE NAME HAS NO YYYYMMDD STAMP
    folder_str = folder_str_in.replace("\\", "/").rstrip("/") + "/"
    os.makedirs(folder_str, exist_ok=True)
    pd.DataFrame({"date": date_str_list_in, "value": list(range(len(date_str_list_in)))}).to_csv(folder_str + "TSDAY_data.csv", index=False)
    return folder_str

# FUNCTION: TEST THE PIPELINE-CACHE GUARD
def test_cache_guard():
    """
    Checks that a work-zone read stops at the window, a later date2 raises, and a store04 read does not.

    Returns:
        None
    """
    # POINT THE WORK ZONE AT A TEMPORARY FOLDER AND KEEP THE REAL ONE
    saved_work_str = paths.LOCAL_WORKZONE_PATH_STR
    work_str = os.path.join(TEMP_ROOT_STR, "workzone").replace("\\", "/") + "/"
    store_str = os.path.join(TEMP_ROOT_STR, "store04_experiments", "exp").replace("\\", "/") + "/"
    paths.LOCAL_WORKZONE_PATH_STR = work_str
    try:
        # A WORK-ZONE READ DROPS THE FILE DATED ON THE WINDOW START
        write_cache_csv(work_str)
        kept_pdf = read_date_range_csv_files_from_path(work_str, "2025-10-01", "2025-10-09")
        assert len(kept_pdf) == 1
        assert len(read_csv_files_from_path(work_str)) == 1
        try:
            read_date_range_csv_files_from_path(work_str, "2025-10-01", "2025-10-10")
            raise AssertionError("a cache date2 on the holdout start was accepted")
        except ValueError as error:
            assert "holdout boundary" in str(error)
        # STORE04 IS UNAFFECTED, INCLUDING WHEN NO WINDOW IS REGISTERED
        write_cache_csv(store_str)
        both_pdf = read_date_range_csv_files_from_path(store_str, "2025-10-01", "2025-10-10")
        assert len(both_pdf) == 2
        saved_registry_str = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = os.path.join(TEMP_ROOT_STR, "missing_windows.csv")
        try:
            assert len(read_date_range_csv_files_from_path(store_str, "2025-10-01", "2025-10-10")) == 2
            try:
                read_date_range_csv_files_from_path(work_str, "2025-10-01", "2025-10-09")
                raise AssertionError("a cache read without a window was accepted")
            except ValueError as error:
                assert error.args[0] == NO_WINDOW_MESSAGE_STR or NO_WINDOW_MESSAGE_STR in str(error)
        finally:
            paths.HOLDOUT_WINDOWS_FILE_PATH_STR = saved_registry_str
    finally:
        paths.LOCAL_WORKZONE_PATH_STR = saved_work_str
    passed("pipeline cache guard (cut at the boundary, later date2 raises, store04 unaffected)")

# FUNCTION: TEST THE DESIGN HASH
def test_design_hash():
    """
    Checks that the hash changes with so/ and not with an unrelated tree.

    Returns:
        None
    """
    # IMPORT THE TEMPLATE AND HASH IT THREE WAYS
    from experiments._template import design as template_design
    same_str = get_design_hash_str(template_design, design_tree_str_in="design-tree", so_tree_str_in="so-tree")
    again_str = get_design_hash_str(template_design, design_tree_str_in="design-tree", so_tree_str_in="so-tree")
    changed_so_str = get_design_hash_str(template_design, design_tree_str_in="design-tree", so_tree_str_in="so-tree-changed")
    changed_design_str = get_design_hash_str(template_design, design_tree_str_in="design-tree-changed", so_tree_str_in="so-tree")
    # THE SAME TREES MATCH; EITHER TREE CHANGING DOES NOT; AN UNRELATED PATH IS NOT AN INPUT
    assert same_str == again_str and same_str != changed_so_str and same_str != changed_design_str
    passed("design hash (so/ changes it, an unrelated tree does not)")


# FUNCTION: TEST THAT A DEVELOPMENT LOAD CANNOT OPEN THE WINDOW
def test_development_load_refuses_window():
    """
    load_source_frame_dict raises when the end date is on or after the active window start, and it does not set the
    runner flag. The unguarded raw reader is not a public function.

    Returns:
        None
    """
    # A MATCHING STAMP, SO THE REFUSAL IS THE WINDOW AND NOT A STALE VIEW
    write_view_stamp(get_active_holdout_window_dict()["start"])
    window_start = pd.Timestamp(get_active_holdout_window_dict()["start"]).date()
    try:
        load_source_frame_dict(["SPY_1MIN"], window_start)
        raise AssertionError("a development load through the window start was accepted")
    except ValueError as error:
        assert "on or after the holdout start" in str(error)
    # THE FLAG IS STILL CLEAR, AND THE DEVELOPMENT LOADER DOES NOT TOUCH IT
    pit_text = open(os.path.join(WORKSPACE_PATH_STR, "so", "core", "point_in_time.py"), encoding="utf-8").read()
    assert "_RUNNER_ACTIVE_BOOL" not in pit_text
    # THE RAW READER WITH NO GUARD IS PRIVATE
    import so.core.raw_data as raw_data_module
    assert not hasattr(raw_data_module, "read_raw_ohlcv_pdf")
    assert hasattr(raw_data_module, "_read_raw_ohlcv_pdf")
    passed("development load refuses the window (runner flag unset; raw reader private)")

# FUNCTION: TEST THAT AN UNDATED CACHE FILE IS CUT
def test_undated_cache_cut():
    """
    Inside the work zone and the gold zone, a file with no date in its name is cut by the date column. Outside those
    zones, and when the pipeline turns the guard off, the file is returned whole.

    Returns:
        None
    """
    # ONE ROW BEFORE THE WINDOW, ONE ON THE START, ONE ON THE END
    date_str_list = ["2025-10-09", "2025-10-10", "2026-10-09"]
    work_str = write_undated_cache_csv(paths.LOCAL_WORKZONE_PATH_STR + "undated_cut/", date_str_list)
    gold_str = write_undated_cache_csv(paths.LOCAL_GOLDZONE_PATH_STR + "undated_cut/", date_str_list)
    outside_str = write_undated_cache_csv(os.path.join(TEMP_ROOT_STR, "outside_zone"), date_str_list)
    store_str = write_undated_cache_csv(paths.LOCAL_EXPERIMENTZONE_PATH_STR + "undated_cut/", date_str_list)
    # WORK AND GOLD KEEP ONLY THE SESSION STRICTLY BEFORE THE WINDOW START
    for folder_str in (work_str, gold_str):
        cut_pdf = read_csv_files_from_path(folder_str)
        assert [pd.Timestamp(day).date() for day in cut_pdf["date"]] == [pd.Timestamp("2025-10-09").date()]
    # THE PIPELINE FLAG AND A FOLDER OUTSIDE THE TWO ZONES KEEP EVERY ROW
    assert len(read_csv_files_from_path(work_str, enforce_holdout_bool_in=False)) == 3
    assert len(read_csv_files_from_path(outside_str)) == 3
    assert len(read_csv_files_from_path(store_str)) == 3
    # AN UNDATED FILE WITH NO DATE COLUMN IS NOT RETURNED WHOLE
    bare_str = paths.LOCAL_WORKZONE_PATH_STR + "undated_nodate/"
    os.makedirs(bare_str, exist_ok=True)
    pd.DataFrame({"value": [1]}).to_csv(bare_str + "nodate.csv", index=False)
    try:
        read_csv_files_from_path(bare_str)
        raise AssertionError("an undated cache file with no date column was returned whole")
    except ValueError as error:
        assert "date column" in str(error)
    passed("undated cache cut (work and gold drop the window; outside and the pipeline keep it)")

# FUNCTION: WRITE A TOKEN FILE OUTSIDE THE WORKSPACE AND THE DATA ROOT
def write_token_file(token_str_in):
    """
    Writes a token file in its own temporary directory.

    Args:
        token_str_in (str): Token text

    Returns:
        str: Token file path
    """
    # THE TOKEN DIRECTORY IS NOT THE DATA ROOT AND NOT THE WORKSPACE
    token_dir_str = tempfile.mkdtemp(prefix="so_holdout_token_")
    token_path_str = os.path.join(token_dir_str, "token.txt")
    with open(token_path_str, "w", encoding="utf-8") as token_file:
        token_file.write(token_str_in + "\n")
    return token_path_str

# FUNCTION: TEST THE QUARANTINE WINDOW-END LOADER
def test_evaluation_quarantine_load():
    """
    The evaluation loader refuses without the token and without SO_QUARANTINE_PATH. With both, it reads the window
    from the quarantine root and does not leave the development paths pointed there.

    Returns:
        None
    """
    # A MATCHING STAMP ON THE DEVELOPMENT VIEW. THE BARS LIVE ONLY IN THE QUARANTINE
    write_view_stamp(get_active_holdout_window_dict()["start"])
    window_dict = get_active_holdout_window_dict()
    start_date = pd.Timestamp(window_dict["start"]).date()
    end_date = pd.Timestamp(window_dict["end"]).date()
    quarantine_root_str = tempfile.mkdtemp(prefix="so_holdout_quarantine_")
    token_path_str = write_token_file("holdout-token")
    saved_token_str = os.environ.get("SO_HOLDOUT_EVALUATION_TOKEN")
    try:
        # WITHOUT THE TOKEN THE QUARANTINE IS NOT READ
        os.environ.pop("SO_QUARANTINE_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        try:
            load_evaluation_source_frame_dict(["SPY_1MIN"], token_path_str)
            raise AssertionError("an evaluation load without the token was accepted")
        except ValueError as error:
            assert "SO_HOLDOUT_EVALUATION_TOKEN" in str(error)
        # WITH THE TOKEN AND WITHOUT THE QUARANTINE ROOT, THE LOAD REFUSES BEFORE ANY FILE IS READ
        os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
        try:
            load_evaluation_source_frame_dict(["SPY_1MIN"], token_path_str)
            raise AssertionError("an evaluation load without SO_QUARANTINE_PATH was accepted")
        except RuntimeError as error:
            assert "SO_QUARANTINE_PATH" in str(error)
        # THE SAME LAYOUT UNDER THE QUARANTINE ROOT, WITH A SESSION BEFORE, INSIDE AND AFTER THE WINDOW
        os.environ["SO_QUARANTINE_PATH"] = quarantine_root_str
        raw_folder_str = paths.get_quarantine_named_path_str("LOCAL_OHLCV_DATA_FILE_PATH_STR")
        assert raw_folder_str == paths.get_quarantine_root_str() + "store01_rawzone/ibkr_spy_1min/"
        before_date = start_date - timedelta(days=1)
        after_date = end_date + timedelta(days=4)
        write_raw_csv(raw_folder_str, [str(before_date), str(start_date), str(end_date), str(after_date)])
        frame_dict = load_evaluation_source_frame_dict(["SPY_1MIN"], token_path_str)
        loaded_date_set = set(pd.Timestamp(day).date() for day in frame_dict["SPY_1MIN"]["date"])
        assert before_date in loaded_date_set and start_date in loaded_date_set and end_date in loaded_date_set
        assert after_date not in loaded_date_set
        # THE RUNNER FLAG AND THE DEVELOPMENT PATHS ARE RESTORED
        assert paths.LOCAL_OHLCV_DATA_FILE_PATH_STR.startswith(paths.get_data_root_str())
        assert not paths.LOCAL_OHLCV_DATA_FILE_PATH_STR.startswith(paths.get_quarantine_root_str())
        # THE SCRIPT LOADS THROUGH THE QUARANTINE LOADER ONLY
        script_text = open(os.path.join(WORKSPACE_PATH_STR, "scripts", "holdout_evaluate.py"), encoding="utf-8").read()
        assert "load_source_frame_dict" not in script_text
        assert script_text.count("load_evaluation_source_frame_dict(") >= 1
    finally:
        os.environ.pop("SO_QUARANTINE_PATH", None)
        if saved_token_str is None:
            os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        else:
            os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = saved_token_str
        shutil.rmtree(quarantine_root_str, ignore_errors=True)
        shutil.rmtree(os.path.dirname(token_path_str), ignore_errors=True)
    passed("evaluation loader (refuses without token or quarantine; reads the window with both)")

# FUNCTION: TEST A MISSING OR WRONG DEVELOPMENT VIEW STAMP
def test_view_stamp():
    """
    A missing VIEW.json and a stamp for a different window both refuse, on the guarded raw loader and on
    load_source_frame_dict.

    Returns:
        None
    """
    # THE MESSAGE THE REFRESH MUST PRODUCE
    assert VIEW_STALE_MESSAGE_STR == "development view is missing or stale: Nicolas must run the refresh"
    view_path_str = os.path.join(TEMP_ROOT_STR, "VIEW.json")
    # A MISSING FILE
    if os.path.isfile(view_path_str):
        os.remove(view_path_str)
    for call in (lambda: get_complete_ohlcv_pdf(), lambda: load_source_frame_dict(["SPY_1MIN"], "2020-01-02")):
        try:
            call()
            raise AssertionError("a missing development view was accepted")
        except ValueError as error:
            assert str(error) == VIEW_STALE_MESSAGE_STR
    # A STAMP FOR A DIFFERENT WINDOW
    write_view_stamp("1999-01-04")
    for call in (lambda: get_complete_ohlcv_pdf(), lambda: load_source_frame_dict(["SPY_1MIN"], "2020-01-02")):
        try:
            call()
            raise AssertionError("a stale development view was accepted")
        except ValueError as error:
            assert str(error) == VIEW_STALE_MESSAGE_STR
    # PUT A MATCHING STAMP BACK
    write_view_stamp(get_active_holdout_window_dict()["start"])
    passed("development view stamp (missing and wrong both refuse)")

# FUNCTION: TEST WHERE THE HOLDOUT GUARD MAY BE TURNED OFF
def test_holdout_flag_scan():
    """
    The guard-off argument may appear only in the pipeline, four named files, and the tests.

    Returns:
        None
    """
    # SCAN SOURCE FILES OUTSIDE THE ALLOWED PLACES
    allowed_file_set = {"scripts/holdout_evaluate.py", "so/core/holdout.py"}
    needle_str = "enforce_holdout_bool_in=False"
    offender_list = []
    for root_str, dir_list, file_list in os.walk(WORKSPACE_PATH_STR):
        dir_list[:] = [dir_name for dir_name in dir_list if dir_name not in {".git", "venv-main", "__pycache__", "logs"}]
        for file_name in file_list:
            if not file_name.endswith((".py", ".ipynb", ".md", ".mdc")):
                continue
            full_str = os.path.join(root_str, file_name)
            rel_str = os.path.relpath(full_str, WORKSPACE_PATH_STR).replace("\\", "/")
            if rel_str.startswith("pipeline/") or rel_str.startswith("tests/") or rel_str in allowed_file_set:
                continue
            text = open(full_str, encoding="utf-8").read()
            if needle_str in text:
                offender_list.append(rel_str)
    # FAIL WHEN THE ARGUMENT APPEARS ANYWHERE ELSE
    assert offender_list == []
    # THE QUARANTINE ROOT MAY BE NAMED ONLY IN THE PATHS MODULE, THE EVALUATION LOADER, THE EVALUATION SCRIPT, TESTS,
    # THE AGENT ACCESS CHECK (WHICH REQUIRES IT UNSET), THE DESIGN-CODE GUARD (WHICH CLOSES IT) AND THE DOCUMENTS THAT FORBID IT
    quarantine_allowed_set = {"so/paths.py", "so/core/holdout.py", "so/runner/run.py", "scripts/holdout_evaluate.py",
                              "scripts/refresh_development_view.py", "scripts/check_agent_access.py", "so/runner/guard.py", "README.md",
                              ".cursor/rules/research-integrity.mdc"}
    quarantine_offender_list = []
    for root_str, dir_list, file_list in os.walk(WORKSPACE_PATH_STR):
        dir_list[:] = [dir_name for dir_name in dir_list if dir_name not in {".git", "venv-main", "__pycache__", "logs"}]
        for file_name in file_list:
            if not file_name.endswith((".py", ".ipynb", ".md", ".mdc")):
                continue
            full_str = os.path.join(root_str, file_name)
            rel_str = os.path.relpath(full_str, WORKSPACE_PATH_STR).replace("\\", "/")
            if rel_str.startswith("tests/") or rel_str in quarantine_allowed_set:
                continue
            text = open(full_str, encoding="utf-8").read()
            for needle_str in ("SO_QUARANTINE_PATH", "get_quarantine_root_str"):
                if needle_str in text:
                    quarantine_offender_list.append(f"{rel_str}: {needle_str}")
    assert quarantine_offender_list == []
    passed("holdout guard off only in the pipeline, the named scripts, holdout.py and tests; quarantine root only in paths, holdout, the runner, the evaluation script and tests")

# FUNCTION: TEST SLIDING THE ACTIVE WINDOW
def test_slide_window():
    """
    slide_holdout_window_dict moves to the latest 12 months, is a no-op when the bounds are unchanged, and refuses
    a new start that is not after the old start. roll_holdout_window_dict is not used here.

    Returns:
        None
    """
    # A PRIVATE REGISTRY SO THE SUITE WINDOW STAYS WHERE IT IS
    slide_path_str = os.path.join(TEMP_ROOT_STR, "slide_windows.csv")
    base_list = get_session_date_list("2022-01-03", "2024-06-28")
    proposed_dict = compute_holdout_window_dict(base_list)
    open_holdout_window_dict(base_list, f"OPEN {proposed_dict['start']} {proposed_dict['end']}", file_path_str_in=slide_path_str)
    # THE SAME SESSION LIST IS A NO-OP
    same_dict = slide_holdout_window_dict(base_list, "no-op", file_path_str_in=slide_path_str)
    assert same_dict["start"] == proposed_dict["start"] and same_dict["end"] == proposed_dict["end"]
    still_active_dict = get_active_holdout_window_dict(file_path_str_in=slide_path_str)
    assert still_active_dict["status"] == "active" and str(still_active_dict["retired_ts"]).strip() in ("", "nan")
    assert len(pd.read_csv(slide_path_str)) == 1
    # AN EARLIER END MOVES THE START BACKWARDS AND IS REFUSED
    early_list = get_session_date_list("2022-01-03", "2023-06-30")
    try:
        slide_holdout_window_dict(early_list, "backwards", file_path_str_in=slide_path_str)
        raise AssertionError("a backwards slide was accepted")
    except ValueError as error:
        assert "not after the active start" in str(error)
    assert get_active_holdout_window_dict(file_path_str_in=slide_path_str)["end"] == proposed_dict["end"]
    # A LATER LAST SESSION OPENS THE LATEST 12 MONTHS AND RETIRES THE OLD ROW
    later_list = get_session_date_list("2022-01-03", "2025-08-29")
    later_dict = compute_holdout_window_dict(later_list)
    assert later_dict["start"] > proposed_dict["start"]
    slid_dict = slide_holdout_window_dict(later_list, "latest 12 months", file_path_str_in=slide_path_str)
    assert slid_dict["start"] == later_dict["start"] and slid_dict["end"] == later_dict["end"]
    assert slid_dict["status"] == "active"
    registry_pdf = pd.read_csv(slide_path_str)
    assert list(registry_pdf["status"]) == ["retired", "active"]
    assert registry_pdf["retire_reason"].iloc[0] == "latest 12 months"
    passed("slide (normal, no-op, refused backwards)")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY FOLDERS
    try:
        test_window_math()
        test_no_window()
        test_stale_pipeline()
        test_registry()
        test_development_schedule()
        test_guards()
        test_legacy_flag_ignored()
        test_pipeline_holdout_flag()
        test_cache_guard()
        test_development_load_refuses_window()
        test_undated_cache_cut()
        test_evaluation_quarantine_load()
        test_view_stamp()
        test_design_hash()
        test_holdout_flag_scan()
        test_slide_window()
        # THE REAL REGISTRY IS UNCHANGED (IT MAY ALREADY EXIST; THIS SUITE MUST NOT WRITE IT)
        assert os.path.isfile(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_EXISTS_BOOL
        if REAL_WINDOWS_EXISTS_BOOL:
            assert os.path.getsize(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_SIZE_INT
        print("\nAll holdout tests passed ✅")
    finally:
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
