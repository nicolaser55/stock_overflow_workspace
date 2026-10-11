"""
Workspace Tests: the rolling holdout (so.core.holdout; Nicolas, 2026-10-11)

Run from the workspace root:   python tests/test_holdout.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The registry, the ledger, the trial log and SO_DATA_PATH are temporary. The real trial log and
records/holdout_windows.csv are not written. SO_HOLDOUT_PATH, SO_HOLDOUT_EVALUATION_TOKEN and
SO_ALLOW_LEGACY_REPRODUCTION are set only inside this file, to temporary values.
"""

import os
import sys
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
os.environ.pop("SO_ALLOW_LEGACY_REPRODUCTION", None)
# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
# IMPORT THE SHARED MODULES
from so import paths, config, vix_config
from so.core.datetime_utils import ny_tz, get_date_range_market_schedule_pdf
from so.core.holdout import (compute_holdout_window_dict, open_holdout_window_dict, roll_holdout_window_dict,
                             get_active_holdout_window_dict, get_development_end_date, get_latest_session_date,
                             check_development_date, get_replay_boundary_date, read_holdout_evaluation_pdf,
                             run_holdout_evaluation, NO_WINDOW_MESSAGE_STR)
from so.core.schedule import get_walk_forward_fold_pdf, get_development_fold_pdf
from so.core.continuous_replay import check_replay_window_bool
from so.core.raw_data import get_complete_ohlcv_pdf
from so.features.vix_features import check_cutoff_date
from so.core.trade_execution import get_ohlcv_array_dict
from synthetic_data import get_synthetic_ohlcv_pdf

# KEEP THE REAL REGISTRY PATHS AND POINT THE SUITE AT TEMPORARY FILES
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REAL_EVALUATIONS_PATH_STR = paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR
REAL_TRIAL_LOG_PATH_STR = "C:/Users/nico/Desktop/stock_overflow_data/store04_experiments/trial_log.csv"
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
LEDGER_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_evaluations.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR
paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR = LEDGER_PATH_STR
# DEFINE THE REAL RAW AND STEP06 PATHS USED ONLY BY THE FINAL DATE CHECK
REAL_RAW_PATH_STR = "C:/Users/nico/Desktop/stock_overflow_data/store01_rawzone/ibkr_spy_1min/"
REAL_TSDAY_PATH_STR = "C:/Users/nico/Desktop/stock_overflow_data/store02_workzone/step06_TSDAY_data/TSDAY_data.csv"

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

# FUNCTION: TEST LEGACY REPRODUCTION
def test_legacy():
    """
    Checks that the legacy flag allows only the pinned 2026-05-14 boundary and prints a warning.

    Returns:
        None
    """
    # SET THE FLAG AND CAPTURE THE WARNING
    os.environ["SO_ALLOW_LEGACY_REPRODUCTION"] = "1"
    try:
        stdout_file = StringIO()
        saved_stdout = sys.stdout
        sys.stdout = stdout_file
        try:
            assert check_replay_window_bool("2026-04-15", "2027-01-01")
            try:
                check_replay_window_bool("2026-05-14", "2027-01-01")
                raise AssertionError("the legacy flag extended past 2026-05-14")
            except ValueError:
                pass
            assert check_cutoff_date("2026-05-13") == pd.Timestamp("2026-05-13").date()
            try:
                check_cutoff_date("2026-05-14", "2027-01-01")
                raise AssertionError("a VIX cutoff on 2026-05-14 was allowed")
            except ValueError:
                pass
            assert get_replay_boundary_date("2027-01-01") == pd.Timestamp(vix_config.UNTOUCHED_START_DATE_STR).date()
        finally:
            sys.stdout = saved_stdout
        assert "SO_ALLOW_LEGACY_REPRODUCTION" in stdout_file.getvalue()
    finally:
        # CLEAR THE FLAG
        os.environ.pop("SO_ALLOW_LEGACY_REPRODUCTION", None)
    passed("legacy reproduction (pinned 2026-05-14 only, with a warning)")

# FUNCTION: BUILD A SYNTHETIC DESIGN MODULE
def get_design_module(leak_bool_in, seen_list_in, window_dict_in, name_str_in="exp_holdout_synthetic"):
    """
    Builds a design whose fit records the last date it was given. A leaking design reports the decision date.

    Args:
        leak_bool_in (bool): Report the decision date as seen
        seen_list_in (list): Dates the fit was given
        window_dict_in (dict): Active window (the honest fit checks the runner boundary)
        name_str_in (str): EXPERIMENT_NAME (part of the design hash)

    Returns:
        module: Design
    """
    # BUILD THE MODULE
    design_module = types.ModuleType("holdout_design")
    design_module.EXPERIMENT_NAME = name_str_in
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.DESIGN_REFIT_RULE = {"every_sessions": 1, "train_window": "6M"}
    # DEFINE FIT AND DECIDE
    def fit(frame_pdf, exclusive_date):
        # RECORD THE LAST DATE OF THE FRAME
        last_date = None if len(frame_pdf) == 0 else pd.Timestamp(frame_pdf["date"].max()).date()
        seen_list_in.append((pd.Timestamp(exclusive_date).date(), last_date))
        if last_date is not None:
            assert last_date < pd.Timestamp(exclusive_date).date()
        # A LEAK REPORTS THE DECISION DATE
        if leak_bool_in:
            return {"last_date_seen": pd.Timestamp(exclusive_date).date()}
        # THE RUNNER ALLOWS THE WINDOW AND STILL REFUSES FORWARD DATA
        check_development_date(window_dict_in["end"])
        try:
            check_development_date(pd.Timestamp(window_dict_in["end"]).date() + timedelta(days=5))
            raise AssertionError("forward data was allowed inside the runner")
        except ValueError as error:
            assert "Forward data" in str(error)
        return {"last_date_seen": last_date} if last_date is not None else {}
    design_module.fit = fit
    design_module.decide = lambda model_state_dict, session_date, feature_dict: 1.0
    # RETURN THE MODULE
    return design_module

# FUNCTION: TEST THE LEDGER AND THE CAUSAL REPLAY
def test_evaluation():
    """
    Checks the preconditions, one causal replay, a repeated hash, the budget and a leaking design.

    Returns:
        None
    """
    # PREPARE THE TOKEN, THE RESULTS FOLDER AND THE BARS
    token_dir_str = tempfile.mkdtemp(prefix="so_holdout_token_")
    token_path_str = os.path.join(token_dir_str, "token.txt")
    with open(token_path_str, "w", encoding="utf-8") as token_file:
        token_file.write("holdout-token\n")
    results_path_str = tempfile.mkdtemp(prefix="so_holdout_results_")
    trial_log_path_str = os.path.join(TEMP_ROOT_STR, "trial_log.csv")
    git_dict = {"clean_bool": True, "on_main_bool": True, "preregister_bool": True, "commit_str": "abc123"}
    window_dict = get_active_holdout_window_dict()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2025-04-01", "2026-10-09", minute_vol_in=0.0004, seed_in=11)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    seen_list = []
    design_module = get_design_module(False, seen_list, window_dict)
    real_trial_size = os.path.getsize(REAL_TRIAL_LOG_PATH_STR)
    # REFUSE A MISSING RESULTS FOLDER AND A WRONG TOKEN BEFORE ANY ROW IS WRITTEN
    try:
        run_holdout_evaluation(design_module, "honest", ohlcv_array_dict, token_path_str, git_dict, ledger_path_str_in=LEDGER_PATH_STR,
                               trial_log_path_str_in=trial_log_path_str)
        raise AssertionError("evaluation without SO_HOLDOUT_PATH was accepted")
    except ValueError as error:
        assert "SO_HOLDOUT_PATH" in str(error)
    os.environ["SO_HOLDOUT_PATH"] = results_path_str
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "wrong"
    try:
        run_holdout_evaluation(design_module, "honest", ohlcv_array_dict, token_path_str, git_dict, ledger_path_str_in=LEDGER_PATH_STR,
                               trial_log_path_str_in=trial_log_path_str)
        raise AssertionError("a wrong token was accepted")
    except ValueError as error:
        assert "TOKEN" in str(error)
    assert not os.path.isfile(LEDGER_PATH_STR)
    # RUN THE HONEST DESIGN ONCE
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
    row_dict = run_holdout_evaluation(design_module, "honest", ohlcv_array_dict, token_path_str, git_dict, ledger_path_str_in=LEDGER_PATH_STR,
                                      trial_log_path_str_in=trial_log_path_str)
    # THE FIT NEVER SAW THE DECISION SESSION
    assert len(seen_list) > 0 and all(last_date is None or last_date < decision_date for decision_date, last_date in seen_list)
    # THE DAILY PATHS LAND ONLY UNDER SO_HOLDOUT_PATH
    output_path_str = os.path.join(results_path_str, row_dict["window_id"], "honest", "strategy_daily_equity.csv")
    assert os.path.isfile(output_path_str)
    assert not os.path.isfile(REAL_EVALUATIONS_PATH_STR)
    assert os.path.isfile(LEDGER_PATH_STR)
    # THE TEMPORARY TRIAL LOG HAS ONE TEST ROW; THE REAL TRIAL LOG IS UNCHANGED
    trial_pdf = pd.read_csv(trial_log_path_str)
    assert len(trial_pdf) == 1 and trial_pdf["stage"].iloc[0] == "test" and bool(trial_pdf["test_window_touched"].iloc[0])
    assert os.path.getsize(REAL_TRIAL_LOG_PATH_STR) == real_trial_size
    assert row_dict["primary_pass"] in (True, False)
    # THE SAME DESIGN HASH ON THE SAME WINDOW IS REFUSED
    try:
        run_holdout_evaluation(design_module, "honest_again", ohlcv_array_dict, token_path_str, git_dict, ledger_path_str_in=LEDGER_PATH_STR,
                               trial_log_path_str_in=trial_log_path_str)
        raise AssertionError("a repeated design hash was accepted")
    except ValueError as error:
        assert "already evaluated" in str(error)
    # THE ELEVENTH DESIGN IS REFUSED (NINE PLACEHOLDER ROWS PLUS THE ONE ABOVE)
    ledger_pdf = read_holdout_evaluation_pdf(LEDGER_PATH_STR)
    placeholder_pdf = pd.concat([ledger_pdf.iloc[[0]].assign(design_id=f"pad_{idx}", design_hash=f"pad_hash_{idx}") for idx in range(9)], ignore_index=True)
    pd.concat([ledger_pdf, placeholder_pdf], ignore_index=True).to_csv(LEDGER_PATH_STR, index=False)
    other_module = get_design_module(False, [], window_dict, name_str_in="exp_holdout_other")
    try:
        run_holdout_evaluation(other_module, "eleventh", ohlcv_array_dict, token_path_str, git_dict, ledger_path_str_in=LEDGER_PATH_STR,
                               trial_log_path_str_in=trial_log_path_str)
        raise AssertionError("an eleventh design was accepted")
    except ValueError as error:
        assert "evaluations" in str(error)
    # A LEAKING DESIGN RAISES (ON A FRESH LEDGER, SO THE BUDGET IS NOT THE REASON)
    fresh_ledger_str = os.path.join(TEMP_ROOT_STR, "fresh_evaluations.csv")
    leak_list = []
    leak_module = get_design_module(True, leak_list, window_dict, name_str_in="exp_holdout_leak")
    try:
        run_holdout_evaluation(leak_module, "leak", ohlcv_array_dict, token_path_str, git_dict, ledger_path_str_in=fresh_ledger_str,
                               trial_log_path_str_in=trial_log_path_str)
        raise AssertionError("a leaking design was accepted")
    except ValueError as error:
        assert "decision session" in str(error)
    assert not os.path.isfile(fresh_ledger_str)
    passed("ledger and causal replay (token, budget, no look-ahead, results only under SO_HOLDOUT_PATH)")

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
        test_legacy()
        test_evaluation()
        test_walk_forward_unchanged()
        assert not os.path.isfile(REAL_WINDOWS_PATH_STR)
        print("\nAll holdout tests passed ✅")
    finally:
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_ALLOW_LEGACY_REPRODUCTION", None)
