"""
Workspace Tests: holdout evaluation through the runner (infrastructure 4b-1d)

Run from the workspace root:   python tests/test_runner_holdout.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

Synthetic data only. The data root, the registry, the ledger, the token, the quarantine root and SO_HOLDOUT_PATH are
temporary folders. records/holdout_windows.csv is not written. SO_QUARANTINE_PATH and SO_HOLDOUT_EVALUATION_TOKEN are
set only inside this file, to temporary values. No real-data run.
"""

import json
import os
import sys
import tempfile
import shutil
import types
import pandas as pd

# FORCE UTF-8 SO THE PASS MARK PRINTS ON A WINDOWS CONSOLE
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
_CURRENT_DATA_PATH_STR = os.environ.get("SO_DATA_PATH", "").strip()
_TEMP_DIR_STR = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
OWNED_TEMP_BOOL = False
if _CURRENT_DATA_PATH_STR and os.path.normcase(os.path.abspath(_CURRENT_DATA_PATH_STR)).startswith(_TEMP_DIR_STR + os.sep):
    TEMP_ROOT_STR = _CURRENT_DATA_PATH_STR
else:
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_holdout_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE SHARED MODULES
from so import paths, config
from so.core.holdout import (UNREAD_SANITY_CHECK_STR, read_holdout_evaluation_pdf, get_date)
from so.core.trial_log import read_trial_log_pdf
from so.core.trade_execution import get_ohlcv_array_dict
from so.runner import run_development_dict, run_holdout_dict, MANIFEST_FILE_STR
from so.runner.lookahead import get_decision_equal_bool
from so.runner.verdict import REPORT_JSON_FILE_STR, REPORT_MD_FILE_STR
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_candidate_design as cand_design

# KEEP THE REAL REGISTRY PATHS AND POINT THIS SUITE AT TEMPORARY FILES
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REAL_EVALUATIONS_PATH_STR = paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
LEDGER_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_evaluations.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR
paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR = LEDGER_PATH_STR


# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints the passing line for one test.

    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")


# FUNCTION: A PASSING GIT PROBE
def get_git_dict(design_tree_str_in="design-tree", so_tree_str_in="so-tree", clean_bool_in=True):
    """
    Args:
        design_tree_str_in, so_tree_str_in (str): Injected trees
        clean_bool_in (bool): Working-tree flag

    Returns:
        dict: Git probe
    """
    # TESTS NEVER CALL REAL GIT
    return {"clean_bool": bool(clean_bool_in), "on_main_bool": True, "preregister_bool": True, "commit_str": "abc123",
            "design_tree_str": design_tree_str_in, "so_tree_str": so_tree_str_in}


# FUNCTION: WRITE AN ACTIVE WINDOW ROW
def write_active_window_pdf(start_in, end_in, window_id_str_in="wtest"):
    """
    Args:
        start_in, end_in: Inclusive bounds
        window_id_str_in (str): Window id

    Returns:
        dict: The row
    """
    # THE RUNNER READS paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    start_date, end_date = get_date(start_in), get_date(end_in)
    row_dict = {"window_id": window_id_str_in, "status": "active", "start": start_date, "end": end_date,
                "session_count": 1, "months_covered": 12.0, "opened_ts": "", "opened_by": "test",
                "data_last_session_at_open": end_date, "retired_ts": "", "retire_reason": ""}
    pd.DataFrame([row_dict]).to_csv(paths.HOLDOUT_WINDOWS_FILE_PATH_STR, index=False)
    return row_dict


# FUNCTION: TOKEN, QUARANTINE AND RESULTS FOLDERS
def get_holdout_env_dict():
    """
    Temporary token file (outside the workspace and the data folder), quarantine root and results folder.

    Args:
        None

    Returns:
        dict: token_path_str, quarantine_path_str, results_path_str, trial_log_path_str
    """
    # THE TOKEN FILE MUST LIVE OUTSIDE THE WORKSPACE AND THE DATA ROOT
    token_dir_str = tempfile.mkdtemp(prefix="so_runner_holdout_token_")
    token_path_str = os.path.join(token_dir_str, "token.txt")
    with open(token_path_str, "w", encoding="utf-8") as token_file:
        token_file.write("holdout-token\n")
    quarantine_path_str = tempfile.mkdtemp(prefix="so_runner_holdout_q_")
    results_path_str = tempfile.mkdtemp(prefix="so_runner_holdout_r_")
    trial_log_path_str = os.path.join(TEMP_ROOT_STR, "runner_holdout_trial_log.csv")
    return {"token_path_str": token_path_str, "quarantine_path_str": quarantine_path_str,
            "results_path_str": results_path_str, "trial_log_path_str": trial_log_path_str}


# FUNCTION: POINT THE PROCESS AT THE TEMPORARY HOLDOUT FOLDERS
def set_holdout_env(env_dict_in):
    """
    Args:
        env_dict_in (dict): Output of get_holdout_env_dict

    Returns:
        None
    """
    # THE RUNNER REQUIRES THE QUARANTINE ROOT AND THE TOKEN
    os.environ["SO_QUARANTINE_PATH"] = env_dict_in["quarantine_path_str"]
    os.environ["SO_HOLDOUT_PATH"] = env_dict_in["results_path_str"]
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"


# FUNCTION: DROP THE HOLDOUT ENVIRONMENT VARIABLES
def clear_holdout_env():
    """
    Args:
        None

    Returns:
        None
    """
    # A LATER DEVELOPMENT CALL MUST NOT SEE THE QUARANTINE
    os.environ.pop("SO_QUARANTINE_PATH", None)
    os.environ.pop("SO_HOLDOUT_PATH", None)
    os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)


# FUNCTION: PERIODS THAT TILE DEVELOPMENT, THEN ONE PERIOD ON THE WINDOW
def get_split_period_pdf(development_session_list_in, window_session_list_in):
    """
    Three contiguous development periods, then one period covering the window.

    Args:
        development_session_list_in, window_session_list_in (list): Session dates

    Returns:
        dict: development_pdf, holdout_pdf
    """
    # THE DEVELOPMENT SPLIT MATCHES test_runner_candidates
    development_list = [get_date(session_date) for session_date in development_session_list_in]
    window_list = [get_date(session_date) for session_date in window_session_list_in]
    assert len(development_list) >= 12 and len(window_list) >= 2
    bound_list = [(0, 3), (4, 7), (8, len(development_list) - 1)]
    row_dict_list = []
    for period_id, (start_idx, end_idx) in enumerate(bound_list):
        start_date, end_date = development_list[start_idx], development_list[end_idx]
        row_dict_list.append({"period_id": period_id, "period_start": start_date, "period_end": end_date,
                              "session_count": int(end_idx - start_idx + 1), "valid_start": start_date, "valid_end": end_date})
    development_pdf = pd.DataFrame(row_dict_list)
    holdout_row = {"period_id": 3, "period_start": window_list[0], "period_end": window_list[-1],
                   "session_count": int(len(window_list)), "valid_start": window_list[0], "valid_end": window_list[-1]}
    holdout_pdf = pd.concat([development_pdf, pd.DataFrame([holdout_row])], ignore_index=True)
    return {"development_pdf": development_pdf, "holdout_pdf": holdout_pdf}


# FUNCTION: THE 2026 CALENDAR USED BY THE MATCHING AND UNREAD CHECKS
def get_matching_world_dict():
    """
    Window placed after the development data, straddling PRIOR_READ_LAST_DATE_STR so the never-read tail is nonempty.

    Args:
        None

    Returns:
        dict: bars, sessions, periods, window bounds
    """
    # DEVELOPMENT ENDS BEFORE THE WINDOW; THE WINDOW STARTS AFTER 2026-04-15
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2026-03-02", "2026-05-15", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_date_list = [get_date(session_date) for session_date in ohlcv_array_dict["session_date_list"]]
    prior_read_date = get_date(config.PRIOR_READ_LAST_DATE_STR)
    window_session_list = [session_date for session_date in session_date_list if session_date > prior_read_date]
    development_session_list = [session_date for session_date in session_date_list if session_date < window_session_list[0]]
    assert len(development_session_list) >= 12 and len(window_session_list) >= 2
    window_start, window_end = window_session_list[0], window_session_list[-1]
    development_pdf = ohlcv_pdf[ohlcv_pdf["date"].map(get_date) < window_start]
    development_array_dict = get_ohlcv_array_dict(development_pdf)
    period_dict = get_split_period_pdf(development_session_list, window_session_list)
    return {"ohlcv_array_dict": ohlcv_array_dict, "development_array_dict": development_array_dict,
            "session_date_list": session_date_list, "development_session_list": development_session_list,
            "window_session_list": window_session_list, "window_start": window_start, "window_end": window_end,
            "development_pdf": period_dict["development_pdf"], "holdout_pdf": period_dict["holdout_pdf"]}


# FUNCTION: DECISIONS ON SHARED SESSIONS MATCH, AND ONLY WINDOW SESSIONS ARE REPORTED
def test_holdout_matches_development_decisions():
    """
    With the window after the development data, the holdout run's decisions over the development sessions equal
    run_development_dict's. Only window sessions are in the report. The never-read tail is labelled with its count.
    No candidate-period trial row is written on the holdout trial log.

    Returns:
        None
    """
    # DEVELOPMENT FIRST, WITHOUT THE QUARANTINE ROOT
    world_dict = get_matching_world_dict()
    write_active_window_pdf(world_dict["window_start"], world_dict["window_end"], "w_match")
    development_log_str = os.path.join(TEMP_ROOT_STR, "match_dev_trial_log.csv")
    clear_holdout_env()
    development_dict = run_development_dict(
        cand_design, world_dict["development_array_dict"], run_id_str_in="holdout_match_dev", n_jobs_int_in=1,
        period_pdf_in=world_dict["development_pdf"], trial_log_path_str_in=development_log_str,
        commit_str_in="testcommit", code_hash_str_in="testhash", check_clean_tree_bool_in=False,
        check_view_bool_in=False, baseline_seed_count_int_in=2, run_lookahead_bool_in=False)
    env_dict = get_holdout_env_dict()
    set_holdout_env(env_dict)
    try:
        holdout_log_str = env_dict["trial_log_path_str"]
        holdout_dict = run_holdout_dict(
            cand_design, "match_holdout", world_dict["ohlcv_array_dict"], env_dict["token_path_str"],
            git_precondition_dict_in=get_git_dict(), design_folder_str_in=os.path.dirname(cand_design.__file__),
            ledger_path_str_in=os.path.join(TEMP_ROOT_STR, "match_ledger.csv"),
            trial_log_path_str_in=holdout_log_str, period_pdf_in=world_dict["holdout_pdf"],
            run_id_str_in="match_holdout", n_jobs_int_in=1, commit_str_in="testcommit", code_hash_str_in="testhash",
            baseline_seed_count_int_in=2, run_lookahead_bool_in=False)
        development_session_list = [get_date(session_date) for session_date in development_dict["window_session_date_list"]]
        holdout_session_list = [get_date(session_date) for session_date in holdout_dict["window_session_date_list"]]
        holdout_idx_dict = {session_date: idx for idx, session_date in enumerate(holdout_session_list)}
        comparable_session_list = development_session_list[:-1]
        for candidate in cand_design.CANDIDATE_LIST:
            development_list = development_dict["candidate_decision_dict"][candidate]
            holdout_list = holdout_dict["candidate_decision_dict"][candidate]
            for idx, session_date in enumerate(comparable_session_list):
                holdout_idx = holdout_idx_dict[session_date]
                assert get_decision_equal_bool(development_list[idx], holdout_list[holdout_idx]), session_date
        report_session_list = [get_date(session_date) for session_date in holdout_dict["report_session_date_list"]]
        assert report_session_list == world_dict["window_session_list"]
        assert not any(session_date in set(development_session_list) for session_date in report_session_list)
        equity_date_list = [get_date(session_date) for session_date in holdout_dict["reported_path_dict"]["daily_equity_pdf"]["date"]]
        assert equity_date_list == world_dict["window_session_list"]
        unread_dict = holdout_dict["unread_dict"]
        assert unread_dict["label_str"] == UNREAD_SANITY_CHECK_STR
        assert int(unread_dict["unread_session_count"]) == len(world_dict["window_session_list"])
        report_path_str = os.path.join(holdout_dict["run_folder_str"], REPORT_JSON_FILE_STR)
        with open(report_path_str, "r", encoding="utf-8") as report_file:
            report_dict = json.load(report_file)
        assert report_dict["unread_dict"]["label_str"] == UNREAD_SANITY_CHECK_STR
        assert int(report_dict["unread_dict"]["unread_session_count"]) == len(world_dict["window_session_list"])
        with open(os.path.join(holdout_dict["run_folder_str"], REPORT_MD_FILE_STR), "r", encoding="utf-8") as markdown_file:
            markdown_str = markdown_file.read()
        assert UNREAD_SANITY_CHECK_STR in markdown_str
        assert str(len(world_dict["window_session_list"])) in markdown_str
        manifest_path_str = os.path.join(holdout_dict["run_folder_str"], MANIFEST_FILE_STR)
        with open(manifest_path_str, "r", encoding="utf-8") as manifest_file:
            manifest_dict = json.load(manifest_file)
        assert manifest_dict["window_id"] == "w_match"
        assert "ledger_row" in manifest_dict and manifest_dict["ledger_row"]["status"] == "valid"
        assert "view_stamp" in manifest_dict and "quarantine_stamp" in manifest_dict
        trial_pdf = read_trial_log_pdf(holdout_log_str)
        assert len(trial_pdf) == 1
        assert str(trial_pdf["stage"].iloc[0]) == "test"
        assert "holdout evaluation" in str(trial_pdf["note"].iloc[0])
        assert holdout_dict["ledger_row_dict"]["status"] == "valid"
        called_list = []
        import so.runner.run as run_mod
        original_func = run_mod.get_holdout_period_pdf
        def fake_get_holdout_period_pdf(design_module_in, session_date_list_in, window_dict_in):
            # RECORD THE CALL AND RETURN THE INJECTED PERIODS
            called_list.append(window_dict_in["window_id"])
            return world_dict["holdout_pdf"]
        run_mod.get_holdout_period_pdf = fake_get_holdout_period_pdf
        try:
            run_holdout_dict(
                cand_design, "match_period_builder", world_dict["ohlcv_array_dict"], env_dict["token_path_str"],
                git_precondition_dict_in=get_git_dict(design_tree_str_in="period-tree"),
                design_folder_str_in=os.path.dirname(cand_design.__file__),
                ledger_path_str_in=os.path.join(TEMP_ROOT_STR, "match_period_ledger.csv"),
                trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "match_period_trial_log.csv"),
                period_pdf_in=None, run_id_str_in="match_period_builder", n_jobs_int_in=1,
                commit_str_in="testcommit", code_hash_str_in="testhash2", baseline_seed_count_int_in=2,
                run_lookahead_bool_in=False)
        finally:
            run_mod.get_holdout_period_pdf = original_func
        assert called_list == ["w_match"]
    finally:
        clear_holdout_env()
    passed("holdout decisions match development on shared sessions; only window sessions are reported")


# FUNCTION: A SECOND EVALUATION OF THE SAME DESIGN IS REFUSED; A FORWARD-ONLY ONE AFTER A SLIDE IS ALLOWED
def test_second_evaluation_and_forward_slide():
    """
    The same design hash on the same window is refused. After the window end moves and at least
    HOLDOUT_MIN_FORWARD_SESSIONS new sessions exist, a repeat is allowed and reports only those sessions.

    Returns:
        None
    """
    # ENOUGH SESSIONS FOR A FIRST WINDOW AND 21 NEW ONES AFTER A SLIDE
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2026-03-02", "2026-06-30", seed_in=5)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_date_list = [get_date(session_date) for session_date in ohlcv_array_dict["session_date_list"]]
    first_end = session_date_list[len(session_date_list) // 2]
    first_start = session_date_list[12]
    first_window_list = [session_date for session_date in session_date_list if first_start <= session_date <= first_end]
    after_list = [session_date for session_date in session_date_list if session_date > first_end]
    assert len(after_list) >= config.HOLDOUT_MIN_FORWARD_SESSIONS
    development_list = [session_date for session_date in session_date_list if session_date < first_start]
    assert len(development_list) >= 12
    first_bars_dict = get_ohlcv_array_dict(ohlcv_pdf[ohlcv_pdf["date"].map(get_date) <= first_end])
    period_dict = get_split_period_pdf(development_list, first_window_list)
    write_active_window_pdf(first_start, first_end, "w_first")
    env_dict = get_holdout_env_dict()
    set_holdout_env(env_dict)
    ledger_str = os.path.join(TEMP_ROOT_STR, "forward_ledger.csv")
    try:
        first_dict = run_holdout_dict(
            cand_design, "forward_first", first_bars_dict, env_dict["token_path_str"],
            git_precondition_dict_in=get_git_dict(), design_folder_str_in=os.path.dirname(cand_design.__file__),
            ledger_path_str_in=ledger_str, trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "forward_trial_1.csv"),
            period_pdf_in=period_dict["holdout_pdf"], run_id_str_in="forward_first", n_jobs_int_in=1,
            commit_str_in="testcommit", code_hash_str_in="testhash", baseline_seed_count_int_in=2,
            run_lookahead_bool_in=False)
        assert first_dict["ledger_row_dict"]["status"] == "valid"
        raised_bool = False
        try:
            run_holdout_dict(
                cand_design, "forward_again", first_bars_dict, env_dict["token_path_str"],
                git_precondition_dict_in=get_git_dict(), design_folder_str_in=os.path.dirname(cand_design.__file__),
                ledger_path_str_in=ledger_str, trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "forward_trial_2.csv"),
                period_pdf_in=period_dict["holdout_pdf"], run_id_str_in="forward_again", n_jobs_int_in=1,
                commit_str_in="testcommit", code_hash_str_in="testhash", baseline_seed_count_int_in=2,
                run_lookahead_bool_in=False)
        except ValueError as error:
            raised_bool = "already evaluated" in str(error)
        assert raised_bool, "a second evaluation of the same design was accepted"
        assert len(read_holdout_evaluation_pdf(ledger_str)) == 1
        new_end = after_list[config.HOLDOUT_MIN_FORWARD_SESSIONS - 1]
        new_window_list = [session_date for session_date in session_date_list if first_start <= session_date <= new_end]
        write_active_window_pdf(first_start, new_end, "w_slid")
        enough_bars_dict = get_ohlcv_array_dict(ohlcv_pdf[ohlcv_pdf["date"].map(get_date) <= new_end])
        enough_period_dict = get_split_period_pdf(development_list, new_window_list)
        second_dict = run_holdout_dict(
            cand_design, "forward_enough", enough_bars_dict, env_dict["token_path_str"],
            git_precondition_dict_in=get_git_dict(), design_folder_str_in=os.path.dirname(cand_design.__file__),
            ledger_path_str_in=ledger_str, trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "forward_trial_3.csv"),
            period_pdf_in=enough_period_dict["holdout_pdf"], run_id_str_in="forward_enough", n_jobs_int_in=1,
            commit_str_in="testcommit", code_hash_str_in="testhash", baseline_seed_count_int_in=2,
            run_lookahead_bool_in=False)
        assert second_dict["ledger_row_dict"]["status"] == "valid"
        report_session_list = [get_date(session_date) for session_date in second_dict["report_session_date_list"]]
        expected_list = [session_date for session_date in new_window_list if session_date > first_end]
        assert report_session_list == expected_list
        assert first_end not in report_session_list
    finally:
        clear_holdout_env()
    passed("second evaluation refused; forward-only after a slide reports only the new sessions")


# FUNCTION: THE 10-EVALUATION BUDGET IS ENFORCED
def test_evaluation_budget_is_enforced():
    """
    Ten ledger rows whose window overlaps the active window refuse an eleventh design before any stream.

    Returns:
        None
    """
    # A PRIVATE LEDGER SO OTHER TESTS KEEP THEIR ROWS
    world_dict = get_matching_world_dict()
    write_active_window_pdf(world_dict["window_start"], world_dict["window_end"], "w_budget")
    ledger_str = os.path.join(TEMP_ROOT_STR, "budget_ledger.csv")
    pad_pdf = pd.DataFrame({"window_id": ["w_budget"] * config.HOLDOUT_EVALUATION_BUDGET,
                            "design_hash": [f"pad_hash_{idx}" for idx in range(config.HOLDOUT_EVALUATION_BUDGET)],
                            "status": ["invalid_lookahead"] * config.HOLDOUT_EVALUATION_BUDGET,
                            "reported_start": [world_dict["window_start"]] * config.HOLDOUT_EVALUATION_BUDGET,
                            "reported_end": [world_dict["window_end"]] * config.HOLDOUT_EVALUATION_BUDGET})
    pad_pdf.to_csv(ledger_str, index=False)
    env_dict = get_holdout_env_dict()
    set_holdout_env(env_dict)
    try:
        raised_bool = False
        try:
            run_holdout_dict(
                cand_design, "budget_eleventh", {"session_date_list": world_dict["session_date_list"]},
                env_dict["token_path_str"], git_precondition_dict_in=get_git_dict(),
                design_folder_str_in=os.path.dirname(cand_design.__file__), ledger_path_str_in=ledger_str,
                trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "budget_trial.csv"))
        except ValueError as error:
            raised_bool = "evaluations" in str(error) and "overlap" in str(error)
        assert raised_bool, "an eleventh overlapping evaluation was accepted"
    finally:
        clear_holdout_env()
    passed("the 10-evaluation budget is enforced")


# FUNCTION: A MISSING TOKEN AND A DIRTY TREE ARE REFUSED
def test_missing_token_and_dirty_tree_are_refused():
    """
    Args:
        None

    Returns:
        None
    """
    # THE SAME SHORT WORLD AS THE MATCHING CHECK
    world_dict = get_matching_world_dict()
    write_active_window_pdf(world_dict["window_start"], world_dict["window_end"], "w_guard")
    env_dict = get_holdout_env_dict()
    os.environ["SO_QUARANTINE_PATH"] = env_dict["quarantine_path_str"]
    os.environ["SO_HOLDOUT_PATH"] = env_dict["results_path_str"]
    os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
    try:
        token_raised_bool = False
        try:
            run_holdout_dict(
                cand_design, "missing_token", {"session_date_list": world_dict["session_date_list"]},
                env_dict["token_path_str"], git_precondition_dict_in=get_git_dict(),
                design_folder_str_in=os.path.dirname(cand_design.__file__),
                ledger_path_str_in=os.path.join(TEMP_ROOT_STR, "token_ledger.csv"),
                trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "token_trial.csv"))
        except ValueError as error:
            token_raised_bool = "SO_HOLDOUT_EVALUATION_TOKEN" in str(error)
        assert token_raised_bool, "a missing token was accepted"
        os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
        dirty_raised_bool = False
        try:
            run_holdout_dict(
                cand_design, "dirty_tree", {"session_date_list": world_dict["session_date_list"]},
                env_dict["token_path_str"], git_precondition_dict_in=get_git_dict(clean_bool_in=False),
                design_folder_str_in=os.path.dirname(cand_design.__file__),
                ledger_path_str_in=os.path.join(TEMP_ROOT_STR, "dirty_ledger.csv"),
                trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "dirty_trial.csv"))
        except ValueError as error:
            dirty_raised_bool = "not clean" in str(error)
        assert dirty_raised_bool, "a dirty tree was accepted"
    finally:
        clear_holdout_env()
    passed("missing token and a dirty tree are refused")


# FUNCTION: A CRASH IN THE REPORT WRITER STILL COUNTS THE EVALUATION
def test_report_writer_crash_still_counts():
    """
    write_run_report_dict raises after the ledger row and the stage-test trial are appended. A second evaluation
    of the same design is refused.

    Returns:
        None
    """
    # THE WINDOW SITS AFTER THE DEVELOPMENT DATA, SAME WORLD AS THE MATCHING CHECK
    world_dict = get_matching_world_dict()
    write_active_window_pdf(world_dict["window_start"], world_dict["window_end"], "w_crash_report")
    env_dict = get_holdout_env_dict()
    set_holdout_env(env_dict)
    import so.runner.run as run_mod
    original_writer = run_mod.write_run_report_dict
    def raise_report_writer(run_folder_str_in, report_dict_in):
        # THE LEDGER AND THE TRIAL MUST ALREADY BE ON DISK WHEN THIS RUNS
        raise RuntimeError("report writer crash")
    ledger_path_str = os.path.join(TEMP_ROOT_STR, "crash_report_ledger.csv")
    trial_log_path_str = os.path.join(TEMP_ROOT_STR, "crash_report_trial_log.csv")
    git_dict = get_git_dict(design_tree_str_in="crash-report-tree")
    run_mod.write_run_report_dict = raise_report_writer
    crashed_bool = False
    try:
        try:
            run_holdout_dict(
                cand_design, "crash_report", world_dict["ohlcv_array_dict"], env_dict["token_path_str"],
                git_precondition_dict_in=git_dict, design_folder_str_in=os.path.dirname(cand_design.__file__),
                ledger_path_str_in=ledger_path_str, trial_log_path_str_in=trial_log_path_str,
                period_pdf_in=world_dict["holdout_pdf"], run_id_str_in="crash_report", n_jobs_int_in=1,
                commit_str_in="testcommit", code_hash_str_in="crashhash", baseline_seed_count_int_in=2,
                run_lookahead_bool_in=False)
        except RuntimeError as error:
            crashed_bool = "report writer crash" in str(error)
        assert crashed_bool, "the report writer did not raise"
        ledger_pdf = read_holdout_evaluation_pdf(ledger_path_str)
        assert len(ledger_pdf) == 1
        assert str(ledger_pdf["design_id"].iloc[0]) == "crash_report"
        assert str(ledger_pdf["status"].iloc[0]) == "valid"
        trial_pdf = read_trial_log_pdf(trial_log_path_str)
        assert len(trial_pdf) == 1
        assert str(trial_pdf["stage"].iloc[0]) == "test"
        assert "holdout evaluation" in str(trial_pdf["note"].iloc[0])
        run_mod.write_run_report_dict = original_writer
        second_raised_bool = False
        try:
            run_holdout_dict(
                cand_design, "crash_report_again", world_dict["ohlcv_array_dict"], env_dict["token_path_str"],
                git_precondition_dict_in=git_dict, design_folder_str_in=os.path.dirname(cand_design.__file__),
                ledger_path_str_in=ledger_path_str, trial_log_path_str_in=trial_log_path_str,
                period_pdf_in=world_dict["holdout_pdf"], run_id_str_in="crash_report_again", n_jobs_int_in=1,
                commit_str_in="testcommit", code_hash_str_in="crashhash", baseline_seed_count_int_in=2,
                run_lookahead_bool_in=False)
        except ValueError as error:
            second_raised_bool = "already evaluated" in str(error)
        assert second_raised_bool, "a second evaluation after a report-writer crash was accepted"
        assert len(read_holdout_evaluation_pdf(ledger_path_str)) == 1
    finally:
        run_mod.write_run_report_dict = original_writer
        clear_holdout_env()
    passed("a crash in the report writer still counts the evaluation; a second run is refused")


# FUNCTION: THE EVALUATION SCRIPT CHOOSES THE RUNNER PATH FOR A PORTED DESIGN
def test_evaluate_script_path_choice():
    """
    get_candidate_design selects run_holdout_dict. A design without it keeps the old replay. Both path labels are
    in the script.

    Returns:
        None
    """
    # LOAD THE SCRIPT THE SAME WAY test_point_in_time DOES (ITS __main__ IS NOT EXECUTED)
    import importlib.util
    script_path_str = os.path.join(WORKSPACE_PATH_STR, "scripts", "holdout_evaluate.py")
    script_spec = importlib.util.spec_from_file_location("holdout_evaluate_runner_path", script_path_str)
    script_module = importlib.util.module_from_spec(script_spec)
    script_spec.loader.exec_module(script_module)
    assert script_module.get_holdout_evaluate_path_str(cand_design) == script_module.RUNNER_PATH_STR
    replay_module = types.ModuleType("replay_design")
    assert script_module.get_holdout_evaluate_path_str(replay_module) == script_module.REPLAY_PATH_STR
    script_text = open(script_path_str, encoding="utf-8").read()
    assert "run_holdout_dict(" in script_text and "run_holdout_evaluation(" in script_text
    assert script_module.RUNNER_PATH_STR in script_text and script_module.REPLAY_PATH_STR in script_text
    passed("holdout_evaluate.py uses the runner path for get_candidate_design and keeps the replay fallback")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE A FOLDER THIS FILE CREATED
    try:
        test_holdout_matches_development_decisions()
        test_second_evaluation_and_forward_slide()
        test_evaluation_budget_is_enforced()
        test_missing_token_and_dirty_tree_are_refused()
        test_report_writer_crash_still_counts()
        test_evaluate_script_path_choice()
        print("\nAll runner holdout tests passed ✅")
    finally:
        clear_holdout_env()
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR = REAL_EVALUATIONS_PATH_STR
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
