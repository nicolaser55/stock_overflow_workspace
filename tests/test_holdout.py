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
import types
import tempfile
import shutil
from datetime import timedelta
from io import StringIO
import numpy as np
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
from so.core.holdout import (compute_holdout_window_dict, open_holdout_window_dict, roll_holdout_window_dict,
                             slide_holdout_window_dict, get_active_holdout_window_dict, get_development_end_date,
                             get_latest_session_date, check_development_date, get_replay_boundary_date,
                             read_holdout_evaluation_pdf, run_holdout_evaluation, get_design_hash_str,
                             get_prior_only_result_dict, get_holdout_report_dict, get_perturbed_ohlcv_dict,
                             get_truncation_cut_date_list, get_runner_active_bool, load_evaluation_source_frame_dict,
                             NO_WINDOW_MESSAGE_STR, VIEW_STALE_MESSAGE_STR)
from so.core.local_file_management import read_csv_files_from_path, read_date_range_csv_files_from_path
from so.core.fractional_exposure import simulate_fractional_exposure_dict
from so.features.daily_features import get_session_decision_idx_dict
from so.core.schedule import get_walk_forward_fold_pdf, get_development_fold_pdf
from so.core.continuous_replay import check_replay_window_bool
from so.core.raw_data import get_complete_ohlcv_pdf
from so.core.point_in_time import load_source_frame_dict
from so.features.vix_features import check_cutoff_date
from so.core.trade_execution import get_ohlcv_array_dict
from synthetic_data import get_synthetic_ohlcv_pdf

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
    assert check_replay_window_bool("2026-04-15", "2026-05-14")
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
    # THE REPLAY USES THE EARLIER OF THE PINNED DATE AND THE WINDOW START
    assert check_replay_window_bool("2025-10-09", "2026-05-14")
    for date_str in ["2025-10-10", "2026-04-15", "2026-05-14"]:
        try:
            check_replay_window_bool(date_str, "2026-05-14")
            raise AssertionError(f"{date_str} was allowed")
        except ValueError:
            pass
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
    # OUTSIDE THE RUNNER THE WINDOW START ITSELF IS REFUSED
    try:
        check_development_date("2025-10-10")
        raise AssertionError("the holdout start was allowed")
    except ValueError:
        pass
    passed("guards (replay, raw loader, VIX loader stop at 2025-10-10)")

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

# FUNCTION: BUILD A ONE-ROW DAILY EQUITY FRAME
def get_planted_equity_pdf(date_in, total_return_float_in):
    """
    One session of daily equity whose total return is the given number.

    Args:
        date_in: Session date
        total_return_float_in (float): Total return

    Returns:
        pd.DataFrame: date, equity, in_position, weight
    """
    # RETURN THE FRAME
    return pd.DataFrame({"date": [pd.Timestamp(date_in).date()], "equity": [config.INITIAL_CAPITAL * (1.0 + total_return_float_in)],
                         "in_position": [True], "weight": [1.0]})

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

# FUNCTION: BUILD THE SELECTION DESIGN
def get_selection_design():
    """
    Two candidates. "up" wins every period that ends before the window and loses every later period.

    Returns:
        module: Design
    """
    # BUILD THE MODULE
    design_module = types.ModuleType("selection_design")
    design_module.EXPERIMENT_NAME = "exp_holdout_selection"
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = ["down", "up"]
    design_module.SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}
    # SCORE A PERIOD FROM ITS END DATE ALONE
    def run_candidate_replay_dict(ohlcv_array_dict, date1, date2, candidate):
        # "up" WINS DEVELOPMENT AND LOSES THE HOLDOUT
        window_start = get_active_holdout_window_dict()["start"]
        development_bool = pd.Timestamp(date2).date() < window_start
        win_bool = (candidate == "up") == development_bool
        return {"daily_equity_pdf": get_planted_equity_pdf(date2, 0.5 if win_bool else -0.5), "trade_pdf": pd.DataFrame()}
    # CARRY THE SELECTED CANDIDATE ONTO EACH SESSION
    def run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf):
        session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
        row_dict_list, target_list, decision_list = [], [], []
        for session_idx, session_date in enumerate(session_date_list):
            period_match_pdf = period_pdf[(period_pdf["period_start"].map(lambda value: pd.Timestamp(value).date()) <= session_date)
                                          & (period_pdf["period_end"].map(lambda value: pd.Timestamp(value).date()) >= session_date)]
            if period_match_pdf.empty:
                continue
            candidate = selection_pdf.loc[selection_pdf["period_id"] == int(period_match_pdf["period_id"].iloc[0]), "candidate"].iloc[0]
            weight_float = 1.0 if candidate == "up" else 0.0
            row_dict_list.append({"date": session_date, "equity": config.INITIAL_CAPITAL, "in_position": weight_float > 0, "weight": weight_float})
            target_list.append(weight_float)
            decision_list.append(session_date)
        return {"daily_equity_pdf": pd.DataFrame(row_dict_list), "trade_pdf": pd.DataFrame(),
                "target_weight_arr": np.array(target_list, dtype=float), "decision_session_list": decision_list}
    design_module.run_candidate_replay_dict = run_candidate_replay_dict
    design_module.run_prior_only_path_dict = run_prior_only_path_dict
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict, date1, date2: {"flat": 0.0}
    return design_module

# FUNCTION: BUILD THE DEAD-BAND DESIGN
def get_dead_band_design():
    """
    One candidate whose target jumps by a full point every 15 sessions and wiggles by 5 points in between.

    Returns:
        module: Design
    """
    # BUILD THE MODULE
    design_module = types.ModuleType("dead_band_design")
    design_module.EXPERIMENT_NAME = "exp_holdout_dead_band"
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = ["band"]
    design_module.SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}
    design_module.DEAD_BAND = 0.20
    # BUILD THE TARGET FROM THE SESSION POSITION
    def get_target_arr(ohlcv_array_dict):
        target_arr = np.empty(len(ohlcv_array_dict["session_date_list"]), dtype=float)
        for session_idx in range(len(target_arr)):
            base_float = 0.0 if (session_idx // 15) % 2 == 0 else 1.0
            target_arr[session_idx] = base_float if session_idx % 15 == 0 else min(1.0, base_float + 0.05)
        return target_arr
    design_module.get_target_arr = get_target_arr
    # A PERIOD SCORE DOES NOT NEED THE SIMULATOR (THERE IS ONE CANDIDATE)
    def run_candidate_replay_dict(ohlcv_array_dict, date1, date2, candidate):
        return {"daily_equity_pdf": get_planted_equity_pdf(date2, 0.0), "trade_pdf": pd.DataFrame()}
    # REPLAY ONCE WITH THE 20-POINT BAND
    def run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf):
        target_arr = get_target_arr(ohlcv_array_dict)
        date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
        session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
        path_idx_list = [idx for idx, session_date in enumerate(session_date_list) if pd.Timestamp(date1).date() <= session_date <= pd.Timestamp(date2).date()]
        simulation_dict = simulate_fractional_exposure_dict(ohlcv_array_dict, date1, date2, target_arr, design_module.DEAD_BAND, float(target_arr[path_idx_list[0]]))
        simulation_dict["target_weight_arr"] = target_arr[path_idx_list]
        simulation_dict["decision_session_list"] = [session_date_list[idx] for idx in path_idx_list]
        return simulation_dict
    design_module.run_candidate_replay_dict = run_candidate_replay_dict
    design_module.run_prior_only_path_dict = run_prior_only_path_dict
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict, date1, date2: {"flat": 0.0}
    return design_module

# FUNCTION: BUILD A DESIGN THAT READS THE NEXT SESSION'S CLOSE
def get_leak_design():
    """
    The target of session t is the next session's close divided by this session's close.

    Returns:
        module: Design
    """
    # BUILD THE MODULE
    design_module = types.ModuleType("leak_design")
    design_module.EXPERIMENT_NAME = "exp_holdout_leak"
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = ["leak"]
    design_module.SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}
    # THE PERIOD SCORE DOES NOT LEAK (THE PATH DOES)
    def run_candidate_replay_dict(ohlcv_array_dict, date1, date2, candidate):
        return {"daily_equity_pdf": get_planted_equity_pdf(date2, 0.0), "trade_pdf": pd.DataFrame()}
    # READ THE NEXT SESSION'S CLOSE
    def run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf):
        end_idx_arr = ohlcv_array_dict["session_end_idx_arr"]
        close_list = [float(ohlcv_array_dict["close_arr"][end_idx_arr[idx]]) for idx in range(len(end_idx_arr))]
        session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
        date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
        row_dict_list, target_list, decision_list = [], [], []
        for session_idx, session_date in enumerate(session_date_list):
            if not (pd.Timestamp(date1).date() <= session_date <= pd.Timestamp(date2).date()):
                continue
            weight_float = close_list[session_idx + 1] / close_list[session_idx] if session_idx + 1 < len(close_list) else 0.0
            row_dict_list.append({"date": session_date, "equity": config.INITIAL_CAPITAL, "in_position": weight_float > 0, "weight": weight_float})
            target_list.append(weight_float)
            decision_list.append(session_date)
        return {"daily_equity_pdf": pd.DataFrame(row_dict_list), "trade_pdf": pd.DataFrame(),
                "target_weight_arr": np.array(target_list, dtype=float), "decision_session_list": decision_list}
    design_module.run_candidate_replay_dict = run_candidate_replay_dict
    design_module.run_prior_only_path_dict = run_prior_only_path_dict
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict, date1, date2: {"flat": 0.0}
    return design_module

# FUNCTION: BUILD A DESIGN THAT USES THE DECISION-BAR CLOSE
def get_decision_average_design():
    """
    The target and the signal are 1 when the decision-bar close is above its 20-session average of decision-bar closes.

    Returns:
        module: Design
    """
    # BUILD THE MODULE
    design_module = types.ModuleType("decision_average_design")
    design_module.EXPERIMENT_NAME = "exp_holdout_decision_average"
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = ["decision_average"]
    design_module.SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}
    # THE PERIOD SCORE DOES NOT READ PRICES
    def run_candidate_replay_dict(ohlcv_array_dict, date1, date2, candidate):
        return {"daily_equity_pdf": get_planted_equity_pdf(date2, 0.0), "trade_pdf": pd.DataFrame()}
    # COMPARE EACH DECISION CLOSE WITH THE MEAN OF THE LAST 20 DECISION CLOSES
    def run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf):
        decision_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict)["decision_idx_arr"]
        decision_close_arr = ohlcv_array_dict["close_arr"][decision_idx_arr]
        session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
        date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
        row_dict_list, target_list, signal_list, decision_list = [], [], [], []
        for session_idx, session_date in enumerate(session_date_list):
            if not (pd.Timestamp(date1).date() <= session_date <= pd.Timestamp(date2).date()):
                continue
            mean_float = float(np.mean(decision_close_arr[max(0, session_idx - 19):session_idx + 1]))
            signal_float = 1.0 if decision_close_arr[session_idx] > mean_float else 0.0
            row_dict_list.append({"date": session_date, "equity": config.INITIAL_CAPITAL, "in_position": signal_float > 0, "weight": signal_float})
            target_list.append(signal_float)
            signal_list.append(signal_float)
            decision_list.append(session_date)
        return {"daily_equity_pdf": pd.DataFrame(row_dict_list), "trade_pdf": pd.DataFrame(),
                "target_weight_arr": np.array(target_list, dtype=float), "signal_arr": np.array(signal_list, dtype=float),
                "decision_session_list": decision_list}
    design_module.run_candidate_replay_dict = run_candidate_replay_dict
    design_module.run_prior_only_path_dict = run_prior_only_path_dict
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict, date1, date2: {"flat": 0.0}
    return design_module

# FUNCTION: BUILD A DESIGN THAT READS A BAR AFTER THE DECISION
def get_later_bar_design(bar_kind_str_in):
    """
    The target and the signal are the close of a bar after the decision. "fill" is the next bar (15:59 on a full day).
    "session_close" is the session's last bar.

    Args:
        bar_kind_str_in (str): "fill" or "session_close"

    Returns:
        module: Design
    """
    # BUILD THE MODULE
    design_module = types.ModuleType(f"{bar_kind_str_in}_leak_design")
    design_module.EXPERIMENT_NAME = f"exp_holdout_{bar_kind_str_in}_leak"
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = [bar_kind_str_in]
    design_module.SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}
    # THE PERIOD SCORE DOES NOT READ PRICES
    def run_candidate_replay_dict(ohlcv_array_dict, date1, date2, candidate):
        return {"daily_equity_pdf": get_planted_equity_pdf(date2, 0.0), "trade_pdf": pd.DataFrame()}
    # READ THE FILL BAR OR THE SESSION CLOSE
    def run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf):
        idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
        price_idx_arr = idx_dict["fill_idx_arr"] if bar_kind_str_in == "fill" else ohlcv_array_dict["session_end_idx_arr"]
        close_arr = ohlcv_array_dict["close_arr"]
        session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
        date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
        row_dict_list, target_list, signal_list, decision_list = [], [], [], []
        for session_idx, session_date in enumerate(session_date_list):
            if not (pd.Timestamp(date1).date() <= session_date <= pd.Timestamp(date2).date()):
                continue
            close_float = float(close_arr[int(price_idx_arr[session_idx])])
            row_dict_list.append({"date": session_date, "equity": config.INITIAL_CAPITAL, "in_position": True, "weight": 1.0})
            target_list.append(close_float)
            signal_list.append(close_float)
            decision_list.append(session_date)
        return {"daily_equity_pdf": pd.DataFrame(row_dict_list), "trade_pdf": pd.DataFrame(),
                "target_weight_arr": np.array(target_list, dtype=float), "signal_arr": np.array(signal_list, dtype=float),
                "decision_session_list": decision_list}
    design_module.run_candidate_replay_dict = run_candidate_replay_dict
    design_module.run_prior_only_path_dict = run_prior_only_path_dict
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict, date1, date2: {"flat": 0.0}
    return design_module

# FUNCTION: PREPARE THE TOKEN AND THE RESULTS FOLDER
def get_evaluation_path_dict():
    """
    Token file, results folder and a temporary trial log.

    Returns:
        dict: token_path_str, results_path_str, trial_log_path_str
    """
    # WRITE THE TOKEN OUTSIDE THE DATA FOLDER
    token_dir_str = tempfile.mkdtemp(prefix="so_holdout_token_")
    token_path_str = os.path.join(token_dir_str, "token.txt")
    with open(token_path_str, "w", encoding="utf-8") as token_file:
        token_file.write("holdout-token\n")
    # RETURN THE PATHS
    return {"token_path_str": token_path_str, "results_path_str": tempfile.mkdtemp(prefix="so_holdout_results_"),
            "trial_log_path_str": os.path.join(TEMP_ROOT_STR, "trial_log.csv")}

# FUNCTION: TEST THE PRIOR-ONLY REPLAY
def test_evaluation():
    """
    Checks the preconditions, selection carried across the window, the dead band, and a leaking design.

    Returns:
        None
    """
    # PREPARE THE TOKEN, THE RESULTS FOLDER AND THE BARS
    path_dict = get_evaluation_path_dict()
    git_dict = get_git_dict()
    window_dict = get_active_holdout_window_dict()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2023-06-01", "2026-10-09", minute_vol_in=0.0004, seed_in=11)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    os.environ["SO_HOLDOUT_PATH"] = path_dict["results_path_str"]
    selection_module = get_selection_design()
    # REFUSE A MISSING RESULTS FOLDER AND A WRONG TOKEN BEFORE ANY ROW IS WRITTEN
    os.environ.pop("SO_HOLDOUT_PATH")
    try:
        run_holdout_evaluation(selection_module, "selection", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                               ledger_path_str_in=LEDGER_PATH_STR, trial_log_path_str_in=path_dict["trial_log_path_str"])
        raise AssertionError("evaluation without SO_HOLDOUT_PATH was accepted")
    except ValueError as error:
        assert "SO_HOLDOUT_PATH" in str(error)
    os.environ["SO_HOLDOUT_PATH"] = path_dict["results_path_str"]
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "wrong"
    try:
        run_holdout_evaluation(selection_module, "selection", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                               ledger_path_str_in=LEDGER_PATH_STR, trial_log_path_str_in=path_dict["trial_log_path_str"])
        raise AssertionError("a wrong token was accepted")
    except ValueError as error:
        assert "TOKEN" in str(error)
    assert not os.path.isfile(LEDGER_PATH_STR)
    # THE SELECTION USES PERIOD RETURNS AND CARRIES THE DEVELOPMENT CHOICE INTO THE WINDOW
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
    selection_ledger_str = os.path.join(TEMP_ROOT_STR, "selection_evaluations.csv")
    selection_row = run_holdout_evaluation(selection_module, "selection", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                                           ledger_path_str_in=selection_ledger_str, trial_log_path_str_in=path_dict["trial_log_path_str"])
    candidate_dict = {int(period_id): candidate for period_id, candidate in json.loads(selection_row["holdout_candidates"]).items()}
    ordered_id_list = sorted(candidate_dict)
    assert selection_row["status"] == "valid"
    assert candidate_dict[ordered_id_list[0]] == "up"
    assert "down" in candidate_dict.values()
    assert selection_row["carried_weight"] == 1.0
    assert os.path.isfile(os.path.join(path_dict["results_path_str"], selection_row["window_id"], "selection", "strategy_daily_equity.csv"))
    assert not os.path.isfile(REAL_EVALUATIONS_PATH_STR)
    # THE SAME DESIGN HASH ON THE SAME WINDOW IS REFUSED
    try:
        run_holdout_evaluation(selection_module, "selection_again", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                               ledger_path_str_in=selection_ledger_str, trial_log_path_str_in=path_dict["trial_log_path_str"])
        raise AssertionError("a repeated design hash was accepted")
    except ValueError as error:
        assert "already evaluated" in str(error)
    # A 20-POINT DEAD BAND IS KEPT, AND A REBALANCE FILLS AT 15:59 OF THE SAME SESSION
    band_module = get_dead_band_design()
    band_ledger_str = os.path.join(TEMP_ROOT_STR, "band_evaluations.csv")
    band_row = run_holdout_evaluation(band_module, "band", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                                      ledger_path_str_in=band_ledger_str, trial_log_path_str_in=path_dict["trial_log_path_str"])
    assert band_row["status"] == "valid"
    band_result_dict = get_prior_only_result_dict(band_module, ohlcv_array_dict, window_dict)
    target_arr = band_module.get_target_arr(ohlcv_array_dict)
    date1, date2 = band_result_dict["period_pdf"]["period_start"].iloc[0], band_result_dict["period_pdf"]["period_end"].iloc[-1]
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
    first_idx = next(idx for idx, session_date in enumerate(session_date_list) if pd.Timestamp(date1).date() <= session_date <= pd.Timestamp(date2).date())
    band_direct_dict = simulate_fractional_exposure_dict(ohlcv_array_dict, date1, date2, target_arr, 0.20, float(target_arr[first_idx]))
    open_direct_dict = simulate_fractional_exposure_dict(ohlcv_array_dict, date1, date2, target_arr, 0.0, float(target_arr[first_idx]))
    path_trade_pdf = band_result_dict["path_dict"]["trade_pdf"]
    assert list(path_trade_pdf["trade_idx"]) == list(band_direct_dict["trade_pdf"]["trade_idx"])
    assert int((path_trade_pdf["reason"] == "rebalance").sum()) < int((open_direct_dict["trade_pdf"]["reason"] == "rebalance").sum())
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
    for trade_row in path_trade_pdf[path_trade_pdf["reason"] == "rebalance"].itertuples(index=False):
        session_idx = int(ohlcv_array_dict["bar_session_idx_arr"][int(trade_row.trade_idx)])
        assert int(trade_row.trade_idx) == int(idx_dict["fill_idx_arr"][session_idx])
        assert session_idx + 1 == len(session_date_list) or int(trade_row.trade_idx) < int(ohlcv_array_dict["session_start_idx_arr"][session_idx + 1])
        end_ts = ohlcv_array_dict["timestamp_index"][int(ohlcv_array_dict["session_end_idx_arr"][session_idx])]
        if end_ts.hour == 15 and end_ts.minute == 59:
            assert trade_row.trade_ts.hour == 15 and trade_row.trade_ts.minute == 59
            decision_ts = ohlcv_array_dict["timestamp_index"][int(idx_dict["decision_idx_arr"][session_idx])]
            assert decision_ts.hour == 15 and decision_ts.minute == 58
    # THE TEMPLATE IS ON THE RUNNER (get_candidate_design); THE OLD REPLAY PATH IS NOT USED FOR IT
    from experiments._template import design as template_design
    assert hasattr(template_design, "get_candidate_design")
    assert not hasattr(template_design, "run_candidate_replay_dict")
    # A DESIGN THAT READS THE NEXT CLOSE IS REJECTED AND CONSUMES A BUDGET SLOT
    leak_module = get_leak_design()
    leak_ledger_str = os.path.join(TEMP_ROOT_STR, "leak_evaluations.csv")
    stdout_file = StringIO()
    saved_stdout = sys.stdout
    sys.stdout = stdout_file
    try:
        leak_row = run_holdout_evaluation(leak_module, "leak", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                                          ledger_path_str_in=leak_ledger_str, trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "leak_trial_log.csv"))
    finally:
        sys.stdout = saved_stdout
    assert leak_row["status"] == "invalid_lookahead"
    assert "invalid_lookahead" in stdout_file.getvalue()
    assert not os.path.isfile(os.path.join(path_dict["results_path_str"], leak_row["window_id"], "leak", "strategy_daily_equity.csv"))
    leak_trial_pdf = pd.read_csv(os.path.join(TEMP_ROOT_STR, "leak_trial_log.csv"))
    assert len(leak_trial_pdf) == 1
    assert leak_trial_pdf["stage"].iloc[0] == "test"
    assert str(leak_trial_pdf["test_window_touched"].iloc[0]) == "True"
    assert leak_trial_pdf["note"].iloc[0] == "invalid_lookahead"
    assert "total_return" not in str(leak_trial_pdf["metric_json"].iloc[0])
    assert len(read_holdout_evaluation_pdf(leak_ledger_str)) == 1
    try:
        run_holdout_evaluation(leak_module, "leak_again", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                               ledger_path_str_in=leak_ledger_str, trial_log_path_str_in=path_dict["trial_log_path_str"])
        raise AssertionError("a repeated leaking design was accepted")
    except ValueError as error:
        assert "already evaluated" in str(error)
    leak_pdf = read_holdout_evaluation_pdf(leak_ledger_str)
    placeholder_pdf = pd.concat([leak_pdf.iloc[[0]].assign(design_id=f"pad_{idx}", design_hash=f"pad_hash_{idx}") for idx in range(9)], ignore_index=True)
    pd.concat([leak_pdf, placeholder_pdf], ignore_index=True).to_csv(leak_ledger_str, index=False)
    eleventh_module = get_selection_design()
    eleventh_module.EXPERIMENT_NAME = "exp_holdout_eleventh"
    try:
        run_holdout_evaluation(eleventh_module, "eleventh", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                               ledger_path_str_in=leak_ledger_str, trial_log_path_str_in=path_dict["trial_log_path_str"])
        raise AssertionError("an eleventh design was accepted")
    except ValueError as error:
        assert "evaluations" in str(error)
    # THE TEMPORARY TRIAL LOG HOLDS THE VALID RUNS ONLY (SELECTION AND DEAD-BAND; THE TEMPLATE IS ON THE RUNNER)
    trial_pdf = pd.read_csv(path_dict["trial_log_path_str"])
    assert len(trial_pdf) == 2 and set(trial_pdf["stage"]) == {"test"}
    # THE PERTURBATION KEEPS THE DECISION BAR AND CHANGES THE FILL BAR
    cut_date = get_truncation_cut_date_list(ohlcv_array_dict["session_date_list"], window_dict)[0]
    perturbed_dict = get_perturbed_ohlcv_dict(ohlcv_array_dict, cut_date)
    full_idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
    perturbed_idx_dict = get_session_decision_idx_dict(perturbed_dict)
    cut_day = pd.Timestamp(cut_date).date()
    cut_session_idx = next(idx for idx, session_date in enumerate(ohlcv_array_dict["session_date_list"]) if pd.Timestamp(session_date).date() == cut_day)
    decision_idx = int(full_idx_dict["decision_idx_arr"][cut_session_idx])
    assert np.array_equal(full_idx_dict["decision_idx_arr"], perturbed_idx_dict["decision_idx_arr"])
    assert perturbed_dict["close_arr"][decision_idx] == ohlcv_array_dict["close_arr"][decision_idx]
    assert perturbed_dict["close_arr"][decision_idx + 1] != ohlcv_array_dict["close_arr"][decision_idx + 1]
    # AN HONEST DECISION-BAR RULE PASSES BOTH CHECKS; THE TEMPLATE ALREADY PASSED
    honest_ledger_str = os.path.join(TEMP_ROOT_STR, "honest_evaluations.csv")
    honest_row = run_holdout_evaluation(get_decision_average_design(), "decision_average", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                                        ledger_path_str_in=honest_ledger_str, trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "honest_trial_log.csv"))
    assert honest_row["status"] == "valid"
    # THE 15:59 FILL AND THE SESSION CLOSE ARE BOTH CAUGHT, AND THE MESSAGE NAMES THE DECISION BAR
    leak_status_dict = {}
    for bar_kind_str in ["fill", "session_close"]:
        leak_stdout_file = StringIO()
        sys.stdout = leak_stdout_file
        try:
            later_row = run_holdout_evaluation(get_later_bar_design(bar_kind_str), bar_kind_str, ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                                               ledger_path_str_in=os.path.join(TEMP_ROOT_STR, f"{bar_kind_str}_evaluations.csv"),
                                               trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, f"{bar_kind_str}_trial_log.csv"))
        finally:
            sys.stdout = saved_stdout
        leak_status_dict[bar_kind_str] = later_row["status"]
        assert later_row["status"] == "invalid_lookahead"
        assert "decision bar" in leak_stdout_file.getvalue()
        assert not os.path.isfile(os.path.join(path_dict["results_path_str"], later_row["window_id"], bar_kind_str, "strategy_daily_equity.csv"))
    # A CRASH IN THE DAILY-PATH WRITER STILL LEAVES THE LEDGER ROW AND REFUSES A SECOND RUN
    import so.core.holdout as holdout_mod
    from so.core.trial_log import read_trial_log_pdf
    crash_module = get_selection_design()
    crash_module.EXPERIMENT_NAME = "exp_holdout_crash_paths"
    crash_ledger_str = os.path.join(TEMP_ROOT_STR, "crash_path_evaluations.csv")
    crash_log_str = os.path.join(TEMP_ROOT_STR, "crash_path_trial_log.csv")
    original_writer = holdout_mod.write_holdout_daily_paths_dict
    def raise_daily_writer(output_path_str_in, report_dict_in):
        # THE LEDGER AND THE TRIAL MUST ALREADY BE ON DISK WHEN THIS RUNS
        raise RuntimeError("daily path writer crash")
    holdout_mod.write_holdout_daily_paths_dict = raise_daily_writer
    crashed_bool = False
    try:
        run_holdout_evaluation(crash_module, "crash_paths", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                               ledger_path_str_in=crash_ledger_str, trial_log_path_str_in=crash_log_str)
    except RuntimeError as error:
        crashed_bool = "daily path writer crash" in str(error)
    finally:
        holdout_mod.write_holdout_daily_paths_dict = original_writer
    assert crashed_bool, "the daily path writer did not raise"
    crash_ledger_pdf = read_holdout_evaluation_pdf(crash_ledger_str)
    assert len(crash_ledger_pdf) == 1
    crash_trial_pdf = read_trial_log_pdf(crash_log_str)
    assert len(crash_trial_pdf) == 1 and str(crash_trial_pdf["stage"].iloc[0]) == "test"
    try:
        run_holdout_evaluation(crash_module, "crash_paths_again", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                               ledger_path_str_in=crash_ledger_str, trial_log_path_str_in=crash_log_str)
        raise AssertionError("a second evaluation after a writer crash was accepted")
    except ValueError as error:
        assert "already evaluated" in str(error)
    passed("prior-only replay (selection carried, dead band, leaking design counts)")
    passed(f"perturbation (decision-bar average {honest_row['status']}; fill {leak_status_dict['fill']}; session close {leak_status_dict['session_close']})")
    passed("a crash in the daily-path writer still counts the evaluation; a second run is refused")

# FUNCTION: TEST THAT THE LEDGER STORES THE DESIGN'S BASELINES
def test_baseline_ledger():
    """
    The runner passes the context and the path. The ledger stores the scalars, including percentiles and counts.
    The success flags compare only the keys the design names.

    Returns:
        None
    """
    # A SELECTION DESIGN WHOSE COMPARISON LIST IS ONE RETURN
    path_dict = get_evaluation_path_dict()
    git_dict = get_git_dict()
    window_dict = get_active_holdout_window_dict()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2023-06-01", "2026-10-09", minute_vol_in=0.0004, seed_in=11)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    os.environ["SO_HOLDOUT_PATH"] = path_dict["results_path_str"]
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
    design_module = get_selection_design()
    design_module.EXPERIMENT_NAME = "exp_holdout_baselines"
    design_module.BASELINE_COMPARISON_KEY_LIST = ["flat_return"]
    seen_dict = {}
    def baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None, path_dict_in=None):
        # THE RUNNER PASSES THE CONTEXT AND THE PRIOR-ONLY PATH, AND THE READ GOES THROUGH THE CONTEXT
        assert data_context_in is not None and path_dict_in is not None and "daily_equity_pdf" in path_dict_in
        from so.core.point_in_time import get_decision_ts
        from so.features.daily_features import get_session_decision_idx_dict
        decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][-1])
        decision_ts = get_decision_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])
        data_context_in.set_decision_ts(decision_ts)
        data_context_in.get("SPY_1MIN", decision_ts, columns_in=["timestamp", "close", "available_ts"])
        data_context_in.set_decision_ts(None)
        seen_dict["span"] = (pd.Timestamp(date1_in).date(), pd.Timestamp(date2_in).date())
        return {"flat_return": 0.01, "random_entry_median": 0.02, "random_entry_p05": -0.1, "random_entry_p95": 0.4,
                "random_entry_count": 20, "random_entry_beaten_count": 15}
    design_module.get_baseline_return_dict = baseline_return_dict
    # A FRESH LEDGER AND A FRESH TRIAL LOG, NOT THE REAL FILES
    ledger_str = os.path.join(TEMP_ROOT_STR, "baseline_evaluations.csv")
    trial_str = os.path.join(TEMP_ROOT_STR, "baseline_trial_log.csv")
    row_dict = run_holdout_evaluation(design_module, "baselines", ohlcv_array_dict, path_dict["token_path_str"], git_dict,
                                      ledger_path_str_in=ledger_str, trial_log_path_str_in=trial_str)
    # THE LEDGER CELL HOLDS THE SCALARS; THE BEATEN FLAGS HOLD ONLY THE NAMED RETURN
    assert row_dict["status"] == "valid"
    assert seen_dict["span"] == (pd.Timestamp(window_dict["start"]).date(), pd.Timestamp(window_dict["end"]).date())
    stored_dict = json.loads(pd.read_csv(ledger_str)["baseline_returns"].iloc[0])
    assert stored_dict["flat_return"] == 0.01 and stored_dict["random_entry_median"] == 0.02
    assert stored_dict["random_entry_p05"] == -0.1 and stored_dict["random_entry_p95"] == 0.4
    assert stored_dict["random_entry_count"] == 20 and stored_dict["random_entry_beaten_count"] == 15
    assert set(row_dict["baselines_beaten"]) == {"flat_return"}
    passed("holdout ledger stores the design baselines and does not beat the counts")

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
    assert get_runner_active_bool() is False
    try:
        load_source_frame_dict(["SPY_1MIN"], window_start)
        raise AssertionError("a development load through the window start was accepted")
    except ValueError as error:
        assert "on or after the holdout start" in str(error)
    # THE FLAG IS STILL CLEAR, AND THE DEVELOPMENT LOADER DOES NOT TOUCH IT
    assert get_runner_active_bool() is False
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
        assert get_runner_active_bool() is False
        assert paths.LOCAL_OHLCV_DATA_FILE_PATH_STR.startswith(paths.get_data_root_str())
        assert not paths.LOCAL_OHLCV_DATA_FILE_PATH_STR.startswith(paths.get_quarantine_root_str())
        # THE SCRIPT'S TWO LOADERS ARE THE QUARANTINE LOADER
        script_text = open(os.path.join(WORKSPACE_PATH_STR, "scripts", "holdout_evaluate.py"), encoding="utf-8").read()
        assert "load_source_frame_dict" not in script_text
        assert script_text.count("load_evaluation_source_frame_dict(") >= 2
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
    allowed_file_set = {"scripts/check_spy_rename.py", "scripts/holdout_evaluate.py", "scripts/smoke_notebook.py", "so/core/holdout.py"}
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
    # THE QUARANTINE ROOT MAY BE NAMED ONLY IN THE PATHS MODULE, THE EVALUATION LOADER, THE EVALUATION SCRIPT AND TESTS
    quarantine_allowed_set = {"so/paths.py", "so/core/holdout.py", "so/runner/run.py", "scripts/holdout_evaluate.py",
                              "scripts/refresh_development_view.py"}
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

# FUNCTION: TEST THE OVERLAPPING-WINDOW BUDGET
def test_overlapping_budget():
    """
    Ten ledger rows on a retired window that overlaps the active window consume the budget. A new design is refused
    before any replay.

    Returns:
        None
    """
    # A PRIVATE REGISTRY AND LEDGER
    saved_registry_str = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    budget_path_str = os.path.join(TEMP_ROOT_STR, "budget_windows.csv")
    ledger_str = os.path.join(TEMP_ROOT_STR, "budget_evaluations.csv")
    paths.HOLDOUT_WINDOWS_FILE_PATH_STR = budget_path_str
    try:
        base_list = get_session_date_list("2022-01-03", "2024-06-28")
        first_dict = compute_holdout_window_dict(base_list)
        open_holdout_window_dict(base_list, f"OPEN {first_dict['start']} {first_dict['end']}", file_path_str_in=budget_path_str)
        first_id_str = get_active_holdout_window_dict()["window_id"]
        # TEN ROWS ON THE FIRST WINDOW, ANY STATUS
        pad_pdf = pd.DataFrame({"window_id": [first_id_str] * config.HOLDOUT_EVALUATION_BUDGET,
                                "design_hash": [f"pad_hash_{idx}" for idx in range(config.HOLDOUT_EVALUATION_BUDGET)],
                                "status": ["invalid_lookahead"] * config.HOLDOUT_EVALUATION_BUDGET,
                                "reported_start": [first_dict["start"]] * config.HOLDOUT_EVALUATION_BUDGET,
                                "reported_end": [first_dict["end"]] * config.HOLDOUT_EVALUATION_BUDGET})
        pad_pdf.to_csv(ledger_str, index=False)
        # SLIDE BY A FEW MONTHS SO THE NEW 12-MONTH WINDOW OVERLAPS THE FIRST
        later_list = get_session_date_list("2022-01-03", "2024-12-31")
        later_dict = compute_holdout_window_dict(later_list)
        assert later_dict["start"] <= first_dict["end"]
        slide_holdout_window_dict(later_list, "overlap", file_path_str_in=budget_path_str)
        assert get_active_holdout_window_dict()["window_id"] != first_id_str
        path_dict = get_evaluation_path_dict()
        os.environ["SO_HOLDOUT_PATH"] = path_dict["results_path_str"]
        os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
        design_module = get_selection_design()
        design_module.EXPERIMENT_NAME = "exp_holdout_overlap_budget"
        try:
            run_holdout_evaluation(design_module, "overlap_budget", {"session_date_list": later_list},
                                   path_dict["token_path_str"], get_git_dict(), ledger_path_str_in=ledger_str,
                                   trial_log_path_str_in=path_dict["trial_log_path_str"])
            raise AssertionError("an overlapping eleventh evaluation was accepted")
        except ValueError as error:
            assert "evaluations" in str(error) and "overlap" in str(error)
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = saved_registry_str
    passed("budget across two overlapping windows")

# FUNCTION: TEST A FORWARD-ONLY REPEAT OF A DESIGN HASH
def test_forward_evaluation():
    """
    A design hash already in the ledger is refused when the new sessions are fewer than HOLDOUT_MIN_FORWARD_SESSIONS
    and accepted when there are enough. The accepted row reports only the new sessions.

    Returns:
        None
    """
    # A PRIVATE REGISTRY SO THE SUITE WINDOW STAYS WHERE IT IS
    saved_registry_str = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    fwd_path_str = os.path.join(TEMP_ROOT_STR, "fwd_windows.csv")
    paths.HOLDOUT_WINDOWS_FILE_PATH_STR = fwd_path_str
    try:
        base_list = get_session_date_list("2022-01-03", "2024-06-28")
        first_dict = compute_holdout_window_dict(base_list)
        open_holdout_window_dict(base_list, f"OPEN {first_dict['start']} {first_dict['end']}", file_path_str_in=fwd_path_str)
        # ENOUGH SESSIONS AFTER THE FIRST END FOR THE ACCEPTED REPEAT
        after_list = [session_date for session_date in get_session_date_list("2024-06-28", "2024-08-30") if session_date > first_dict["end"]]
        assert len(after_list) >= config.HOLDOUT_MIN_FORWARD_SESSIONS
        few_list = base_list + after_list[: config.HOLDOUT_MIN_FORWARD_SESSIONS - 1]
        enough_list = base_list + after_list
        ohlcv_pdf = get_synthetic_ohlcv_pdf("2022-01-03", str(enough_list[-1]), minute_vol_in=0.0004, seed_in=21)
        def get_cut_dict(end_in):
            # KEEP BARS THROUGH THE REQUESTED END
            end_date = pd.Timestamp(end_in).date()
            cut_pdf = ohlcv_pdf[ohlcv_pdf["date"].map(lambda value: pd.Timestamp(value).date()) <= end_date]
            return get_ohlcv_array_dict(cut_pdf)
        path_dict = get_evaluation_path_dict()
        os.environ["SO_HOLDOUT_PATH"] = path_dict["results_path_str"]
        os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
        design_module = get_selection_design()
        design_module.EXPERIMENT_NAME = "exp_holdout_forward"
        ledger_str = os.path.join(TEMP_ROOT_STR, "fwd_evaluations.csv")
        first_row = run_holdout_evaluation(design_module, "forward_first", get_cut_dict(first_dict["end"]),
                                           path_dict["token_path_str"], get_git_dict(), ledger_path_str_in=ledger_str,
                                           trial_log_path_str_in=path_dict["trial_log_path_str"])
        assert first_row["status"] == "valid"
        assert pd.Timestamp(first_row["reported_start"]).date() == first_dict["start"]
        assert pd.Timestamp(first_row["reported_end"]).date() == first_dict["end"]
        # TOO FEW NEW SESSIONS AFTER A SLIDE
        slide_holdout_window_dict(few_list, "few forward", file_path_str_in=fwd_path_str)
        try:
            run_holdout_evaluation(design_module, "forward_few", get_cut_dict(few_list[-1]), path_dict["token_path_str"],
                                   get_git_dict(), ledger_path_str_in=ledger_str, trial_log_path_str_in=path_dict["trial_log_path_str"])
            raise AssertionError("a repeat with too few new sessions was accepted")
        except ValueError as error:
            assert "new sessions" in str(error)
        assert len(read_holdout_evaluation_pdf(ledger_str)) == 1
        # ENOUGH NEW SESSIONS: ONLY THOSE SESSIONS ARE REPORTED
        slide_holdout_window_dict(enough_list, "enough forward", file_path_str_in=fwd_path_str)
        second_row = run_holdout_evaluation(design_module, "forward_enough", get_cut_dict(enough_list[-1]),
                                            path_dict["token_path_str"], get_git_dict(), ledger_path_str_in=ledger_str,
                                            trial_log_path_str_in=path_dict["trial_log_path_str"])
        assert second_row["status"] == "valid"
        assert pd.Timestamp(second_row["reported_start"]).date() == after_list[0]
        assert pd.Timestamp(second_row["reported_end"]).date() == enough_list[-1]
        equity_path_str = os.path.join(path_dict["results_path_str"], second_row["window_id"], "forward_enough", "strategy_daily_equity.csv")
        equity_pdf = pd.read_csv(equity_path_str)
        equity_date_list = [pd.Timestamp(day).date() for day in equity_pdf["date"]]
        assert min(equity_date_list) == after_list[0] and max(equity_date_list) == enough_list[-1]
        assert first_dict["end"] not in equity_date_list
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = saved_registry_str
    passed("forward evaluation (too few new sessions refused; enough reports only the new sessions)")

# FUNCTION: TEST THAT THE SAME EXPERIMENT NAME IS A REPEAT EVEN WHEN THE HASH CHANGES
def test_experiment_name_repeat():
    """
    A ledger row with the same EXPERIMENT_NAME and a different so-tree hash is the same design. A second evaluation
    on the same sessions is refused.

    Returns:
        None
    """
    # A PRIVATE REGISTRY SO THE SUITE WINDOW STAYS WHERE IT IS
    saved_registry_str = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    name_path_str = os.path.join(TEMP_ROOT_STR, "name_windows.csv")
    paths.HOLDOUT_WINDOWS_FILE_PATH_STR = name_path_str
    try:
        session_date_list = get_session_date_list("2022-01-03", "2024-06-28")
        proposed_dict = compute_holdout_window_dict(session_date_list)
        open_holdout_window_dict(session_date_list, f"OPEN {proposed_dict['start']} {proposed_dict['end']}", file_path_str_in=name_path_str)
        window_dict = get_active_holdout_window_dict()
        design_module = get_selection_design()
        design_module.EXPERIMENT_NAME = "exp_holdout_name_match"
        old_hash_str = get_design_hash_str(design_module, design_tree_str_in="design-tree", so_tree_str_in="so-tree")
        new_hash_str = get_design_hash_str(design_module, design_tree_str_in="design-tree", so_tree_str_in="so-tree-changed")
        assert old_hash_str != new_hash_str
        # A PRIOR ROW OF THIS NAME WITH THE OLD HASH, ALREADY REPORTED THROUGH THE WINDOW END
        ledger_str = os.path.join(TEMP_ROOT_STR, "name_evaluations.csv")
        pd.DataFrame({"window_id": [window_dict["window_id"]], "design_id": ["name_first"],
                      "experiment_name": ["exp_holdout_name_match"], "design_hash": [old_hash_str], "status": ["valid"],
                      "reported_start": [window_dict["start"]], "reported_end": [window_dict["end"]]}).to_csv(ledger_str, index=False)
        path_dict = get_evaluation_path_dict()
        os.environ["SO_HOLDOUT_PATH"] = path_dict["results_path_str"]
        os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
        try:
            run_holdout_evaluation(design_module, "name_again", {"session_date_list": session_date_list},
                                   path_dict["token_path_str"], get_git_dict(so_tree_str_in="so-tree-changed"),
                                   ledger_path_str_in=ledger_str, trial_log_path_str_in=path_dict["trial_log_path_str"])
            raise AssertionError("the same EXPERIMENT_NAME with a new so-tree hash was accepted on the same sessions")
        except ValueError as error:
            assert "already evaluated" in str(error)
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = saved_registry_str
    passed("same EXPERIMENT_NAME with a different so-tree hash is refused on the same sessions")

# FUNCTION: TEST THE UNREAD FIELDS ON A WINDOW THAT STRADDLES THE PRIOR-READ DATE
def test_unread_fields():
    """
    Reported sessions after PRIOR_READ_LAST_DATE_STR fill the unread fields. A span that does not go past that date
    stores NaN.

    Returns:
        None
    """
    # A SHORT STRADDLE: LAST PROTOCOL-1.0 DATE IS INSIDE THE REPORTED SPAN
    prior_date = pd.Timestamp(config.PRIOR_READ_LAST_DATE_STR).date()
    straddle_list = get_session_date_list("2026-04-01", "2026-05-15")
    assert straddle_list[0] <= prior_date < straddle_list[-1]
    unread_list = [session_date for session_date in straddle_list if session_date > prior_date]
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2026-04-01", "2026-05-15", minute_vol_in=0.0004, seed_in=7)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    equity_pdf = pd.DataFrame({"date": straddle_list,
                               "equity": [config.INITIAL_CAPITAL * (1.0 + 0.01 * (idx + 1)) for idx in range(len(straddle_list))],
                               "in_position": [True] * len(straddle_list), "weight": [1.0] * len(straddle_list)})
    period_pdf = pd.DataFrame({"period_id": [1], "period_start": [straddle_list[0]], "period_end": [straddle_list[-1]]})
    selection_pdf = pd.DataFrame({"period_id": [1], "candidate": ["up"]})
    result_dict = {"period_pdf": period_pdf, "selection_pdf": selection_pdf,
                   "path_dict": {"daily_equity_pdf": equity_pdf, "trade_pdf": pd.DataFrame()}}
    design_module = get_selection_design()
    window_dict = {"start": straddle_list[0], "end": straddle_list[-1], "window_id": "w_straddle"}
    report_pack_dict = get_holdout_report_dict(design_module, ohlcv_array_dict, window_dict, result_dict)
    report_dict = report_pack_dict["report_dict"]
    assert pd.Timestamp(report_dict["unread_start"]).date() == unread_list[0]
    assert int(report_dict["unread_session_count"]) == len(unread_list)
    assert np.isfinite(report_dict["unread_total_return"]) and np.isfinite(report_dict["unread_buy_hold_total_return"])
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    unread_buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict, unread_list[0], straddle_list[-1])
    assert abs(float(report_dict["unread_buy_hold_total_return"]) - float(unread_buy_hold_dict["metric_dict"]["total_return"])) <= config.NUMERIC_TOLERANCE
    # A SPAN THAT ENDS ON THE PRIOR-READ DATE HAS NO UNREAD SESSION
    before_list = [session_date for session_date in straddle_list if session_date <= prior_date]
    before_equity_pdf = equity_pdf[equity_pdf["date"].map(lambda value: pd.Timestamp(value).date() <= prior_date)].reset_index(drop=True)
    before_result_dict = {"period_pdf": pd.DataFrame({"period_id": [1], "period_start": [before_list[0]], "period_end": [before_list[-1]]}),
                          "selection_pdf": selection_pdf, "path_dict": {"daily_equity_pdf": before_equity_pdf, "trade_pdf": pd.DataFrame()}}
    before_window_dict = {"start": before_list[0], "end": before_list[-1], "window_id": "w_before"}
    before_report_dict = get_holdout_report_dict(design_module, ohlcv_array_dict, before_window_dict, before_result_dict)["report_dict"]
    assert pd.isna(before_report_dict["unread_start"]) and pd.isna(before_report_dict["unread_session_count"])
    assert pd.isna(before_report_dict["unread_total_return"]) and pd.isna(before_report_dict["unread_buy_hold_total_return"])
    passed("unread fields (straddle fills them; a span that does not go past the date is NaN)")

# FUNCTION: TEST THAT THE ARCHIVED SCHEDULE STILL HAS TEST WINDOWS
def test_walk_forward_unchanged():
    """
    Checks that get_walk_forward_fold_pdf still anchors test windows on the last session.

    Returns:
        None
    """
    # BUILD THE SCHEDULE TWICE
    session_date_list = get_session_date_list("2018-01-02", "2026-10-09")
    fold_pdf = get_walk_forward_fold_pdf(session_date_list, 20, [1])
    again_pdf = get_walk_forward_fold_pdf(session_date_list, 20, [1])
    # THE TEST COLUMNS ARE STILL THERE AND THE LAST TEST WINDOW ENDS ON THE LAST SESSION
    assert "test_start" in fold_pdf.columns and "test_end" in fold_pdf.columns
    assert pd.Timestamp(fold_pdf["test_end"].iloc[-1]).date() == session_date_list[-1]
    assert fold_pdf.equals(again_pdf)
    passed(f"archived walk-forward schedule unchanged ({len(fold_pdf)} folds, test windows kept)")

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
        test_evaluation()
        test_baseline_ledger()
        test_holdout_flag_scan()
        test_slide_window()
        test_overlapping_budget()
        test_forward_evaluation()
        test_experiment_name_repeat()
        test_unread_fields()
        test_walk_forward_unchanged()
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
