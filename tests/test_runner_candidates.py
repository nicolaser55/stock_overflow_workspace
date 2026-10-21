"""
Workspace Tests: runner candidates, selection, trial log, checkpoints, parallel (infrastructure 4b-1a)

Run from the workspace root:   python tests/test_runner_candidates.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

Synthetic data only. The data root is a temporary folder. records/holdout_windows.csv is not written.
SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set. No real-data run.
"""

import json
import os
import sys
import tempfile
import shutil
import types
import multiprocessing
import numpy as np
import pandas as pd

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
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_cand_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE SHARED MODULES
from so import paths
from so.core.holdout import NO_WINDOW_MESSAGE_STR
from so.core.trial_log import read_trial_log_pdf, TRIAL_LOG_COLUMN_LIST
from so.core.trade_execution import get_ohlcv_array_dict
from so.core.datetime_utils import get_date_range_market_schedule_pdf
from so.runner import (run_development_dict, run_daily_dict, run_engine_decisions_dict, get_trial_id_str,
                       get_runner_selection_pdf, get_governing_candidate_dict, check_quarantine_refused,
                       get_development_run_period_pdf)
from so.runner.engine import get_decision_dict
from so.paths import QUARANTINE_REFUSED_MESSAGE_STR
from so.runner.run import log_candidate_period_trial_dict, get_candidate_token_str
from so.runner.checkpoint import read_checkpoint_dict
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_candidate_design as cand_design

# KEEP THE REAL REGISTRY PATH AND POINT THIS SUITE AT A TEMPORARY FILE
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR
# PROCESSES ARE SPAWNED (WINDOWS AND LINUX)
MP_CONTEXT = multiprocessing.get_context("spawn")


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


# FUNCTION: THREE INJECTED PERIODS ON A SHORT SYNTHETIC SPAN
def get_injected_period_pdf(session_date_list_in):
    """
    Three contiguous periods that tile the span. Each of the first two has four sessions; the last takes the rest.

    Args:
        session_date_list_in (list): Session dates (at least 12)

    Returns:
        pd.DataFrame: period_id, period_start, period_end, session_count, valid_start, valid_end
    """
    # THE SPAN IS LONG ENOUGH FOR THREE PERIODS
    session_date_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in]
    assert len(session_date_list) >= 12
    bound_list = [(0, 3), (4, 7), (8, len(session_date_list) - 1)]
    row_dict_list = []
    for period_id, (start_idx, end_idx) in enumerate(bound_list):
        start_date, end_date = session_date_list[start_idx], session_date_list[end_idx]
        row_dict_list.append({"period_id": period_id, "period_start": start_date, "period_end": end_date,
                              "session_count": int(end_idx - start_idx + 1), "valid_start": start_date, "valid_end": end_date})
    return pd.DataFrame(row_dict_list)


# FUNCTION: A TRIAL-LOG PATH INSIDE THE TEMPORARY DATA ROOT
def get_test_trial_log_path_str(file_name_str_in):
    """
    Args:
        file_name_str_in (str): File name

    Returns:
        str: CSV path
    """
    # THE FOLDER IS CREATED HERE
    folder_str = os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "runner_candidate_test")
    os.makedirs(folder_str, exist_ok=True)
    return os.path.join(folder_str, file_name_str_in)


# FUNCTION: A DESIGN MODULE FOR A HAND-COMPUTED SELECTION
def get_selection_design_module():
    """
    Two candidates, pooled_periods=2, tie_order ascending.

    Args:
        None

    Returns:
        module: CANDIDATE_LIST, SELECTION_RULE, CANDIDATE_TIE_VALUE_DICT
    """
    # NOT AN EXPERIMENT FILE
    module = types.ModuleType("selection_hand_design")
    module.CANDIDATE_LIST = ["A", "B"]
    module.SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("tie_order", True)]}
    module.CANDIDATE_TIE_VALUE_DICT = {"tie_order": {"A": 1, "B": 0}}
    return module


# FUNCTION: SELECTION MATCHES A HAND-COMPUTED CASE, INCLUDING A TIE
def test_selection_hand_computed_tie():
    """
    Fold 0: A 0.10, B 0.00 -> A. Fold 1: A 0.00, B 0.10 -> pooled both 0.05, tie -> B (lower tie_order).
    Period 0 is governed by CANDIDATE_LIST[0]=A; period 1 by the choice at 0 (A); period 2 by the choice at 1 (B).

    Returns:
        None
    """
    # THE SCORE TABLE THE SELECTOR SEES
    score_pdf = pd.DataFrame([
        {"fold_id": 0, "candidate": "A", "excess_return": 0.10},
        {"fold_id": 0, "candidate": "B", "excess_return": 0.00},
        {"fold_id": 1, "candidate": "A", "excess_return": 0.00},
        {"fold_id": 1, "candidate": "B", "excess_return": 0.10},
    ])
    design_module = get_selection_design_module()
    selection_pdf = get_runner_selection_pdf(score_pdf, design_module)
    assert list(selection_pdf.sort_values("fold_id")["candidate"]) == ["A", "B"]
    period_pdf = pd.DataFrame([{"period_id": 0}, {"period_id": 1}, {"period_id": 2}])
    governing_dict = get_governing_candidate_dict(selection_pdf, period_pdf, design_module.CANDIDATE_LIST)
    assert governing_dict[0] == "A" and governing_dict[1] == "A" and governing_dict[2] == "B"
    passed("selection matches a hand-computed case including a tie")


# FUNCTION: THE DEVELOPMENT RUNNER REFUSES THE QUARANTINE ROOT
def test_quarantine_is_refused():
    """
    SO_QUARANTINE_PATH set is a hard refuse. The folder is not opened.

    Returns:
        None
    """
    # A TEMPORARY PATH THAT IS NOT READ
    os.environ["SO_QUARANTINE_PATH"] = tempfile.mkdtemp(prefix="so_quarantine_refused_")
    try:
        raised_bool = False
        try:
            check_quarantine_refused()
        except RuntimeError as error:
            raised_bool = QUARANTINE_REFUSED_MESSAGE_STR in str(error)
        assert raised_bool, "check_quarantine_refused accepted SO_QUARANTINE_PATH"
    finally:
        os.environ.pop("SO_QUARANTINE_PATH", None)
    passed("development runner refuses the quarantine root")


# FUNCTION: PERIODS FROM PERIOD_RULE WITH THE EXISTING PERIOD CODE
def test_period_rule_uses_existing_code():
    """
    A registered window and a year-plus of session dates produce non-overlapping periods whose last end is the
    development end (one embargo session before the holdout start).

    Returns:
        None
    """
    # SESSION DATES ONLY; NO MINUTE BARS
    session_date_list = list(pd.to_datetime(get_date_range_market_schedule_pdf("2009-01-02", "2010-07-15")["date"]).dt.date)
    window_start = session_date_list[-5]
    bar_session_list = [session_date for session_date in session_date_list if session_date < window_start]
    pd.DataFrame([{"window_id": "wtest", "status": "active", "start": window_start, "end": session_date_list[-1],
                   "session_count": 5, "months_covered": 12.0, "opened_ts": "", "opened_by": "test",
                   "data_last_session_at_open": session_date_list[-1], "retired_ts": "", "retire_reason": ""}]).to_csv(
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR, index=False)
    period_pdf, fold_pdf = get_development_run_period_pdf(cand_design, bar_session_list)
    assert len(period_pdf) >= 2 and len(fold_pdf) >= 2
    assert pd.Timestamp(period_pdf["period_end"].iloc[-1]).date() == bar_session_list[-1]
    assert list(period_pdf["period_id"]) == sorted(period_pdf["period_id"].tolist())
    passed("PERIOD_RULE forms periods with get_development_fold_pdf and get_replay_period_pdf")


# FUNCTION: NO REGISTERED WINDOW IS A REFUSE WHEN PERIODS ARE NOT INJECTED
def test_missing_window_is_refused():
    """
    period_pdf_in None and no active window raise the registry error.

    Returns:
        None
    """
    # AN EMPTY REGISTRY
    if os.path.isfile(paths.HOLDOUT_WINDOWS_FILE_PATH_STR):
        os.remove(paths.HOLDOUT_WINDOWS_FILE_PATH_STR)
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    raised_bool = False
    try:
        run_development_dict(cand_design, ohlcv_array_dict, n_jobs_int_in=1, trial_log_path_str_in=get_test_trial_log_path_str("missing_window.csv"))
    except ValueError as error:
        raised_bool = NO_WINDOW_MESSAGE_STR in str(error)
    assert raised_bool, "run_development_dict accepted a missing holdout window"
    passed("a missing holdout window is refused when periods are not injected")


# FUNCTION: A SHORT SYNTHETIC RUN
def run_short_dict(n_jobs_int_in, run_id_str_in, trial_log_path_str_in, crash_after_period_id_in=None):
    """
    Three injected periods on a few weeks of synthetic bars.

    Args:
        n_jobs_int_in (int): Process count
        run_id_str_in (str): Run id
        trial_log_path_str_in (str): Trial log
        crash_after_period_id_in (int | None): Crash hook

    Returns:
        dict: run_development_dict output plus ohlcv_array_dict
    """
    # THE SAME BARS FOR EVERY COMPARISON IN THIS SUITE
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    result_dict = run_development_dict(cand_design, ohlcv_array_dict, run_id_str_in=run_id_str_in, n_jobs_int_in=n_jobs_int_in,
                                       period_pdf_in=period_pdf, trial_log_path_str_in=trial_log_path_str_in,
                                       commit_str_in="testcommit", crash_after_period_id_in=crash_after_period_id_in)
    result_dict["ohlcv_array_dict"] = ohlcv_array_dict
    return result_dict


# FUNCTION: PRIOR-ONLY EQUALS A MANUAL ENGINE PASS OVER THE GOVERNING DECISIONS
def test_prior_only_matches_manual_engine():
    """
    The runner's prior-only path matches run_engine_decisions_dict on a hand-built list of the governing candidate's
    recorded decisions, and also matches run_daily_dict with those target weights.

    Returns:
        None
    """
    # ONE IN-PROCESS RUN
    trial_path_str = get_test_trial_log_path_str("prior_only_trial_log.csv")
    result_dict = run_short_dict(1, "prior_only_run", trial_path_str)
    session_date_list = result_dict["window_session_date_list"]
    governing_dict = result_dict["governing_dict"]
    period_pdf = result_dict["period_pdf"]
    candidate_decision_dict = result_dict["candidate_decision_dict"]
    # HAND-BUILD THE GOVERNING DECISION OF EVERY SESSION
    manual_decision_list = []
    for session_idx, session_date in enumerate(session_date_list):
        session_day = pd.Timestamp(session_date).date()
        cover_pdf = period_pdf[(period_pdf["period_start"].map(lambda value: pd.Timestamp(value).date()) <= session_day)
                               & (period_pdf["period_end"].map(lambda value: pd.Timestamp(value).date()) >= session_day)]
        candidate = governing_dict[int(cover_pdf["period_id"].iloc[-1])]
        manual_decision_list.append(get_decision_dict(candidate_decision_dict[candidate][session_idx]))
    manual_dict = run_engine_decisions_dict(result_dict["ohlcv_array_dict"], result_dict["date1"], result_dict["date2"],
                                            manual_decision_list, initial_weight_in=1.0, dead_band_in=0.0)
    prior_equity = result_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float)
    manual_equity = manual_dict["daily_equity_pdf"]["equity"].to_numpy(dtype=float)
    assert np.allclose(prior_equity, manual_equity, atol=0.0)
    # THE SAME WEIGHTS THROUGH THE 4A LOOP
    class ManualWeightDesign:
        DATA_SOURCE_LIST = ["SPY_1MIN"]

        def __init__(self, weight_list_in, session_list_in):
            self.weight_dict = {session_date: float(weight) for session_date, weight in zip(session_list_in, weight_list_in)}

        def decide(self, view_in):
            return self.weight_dict[view_in.session_date]

    weight_list = [float(decision_dict["target_weight"]) for decision_dict in manual_decision_list]
    loop_dict = run_daily_dict(ManualWeightDesign(weight_list, session_date_list), result_dict["ohlcv_array_dict"],
                               result_dict["date1"], result_dict["date2"], initial_weight_in=1.0, dead_band_in=0.0)
    assert np.allclose(prior_equity, loop_dict["daily_equity_pdf"]["equity"].to_numpy(dtype=float), atol=0.0)
    passed("prior-only path equals a manual engine pass over the governing decisions")


# FUNCTION: A KILLED RUN RESUMED MATCHES A CLEAN RUN AND DOES NOT DUPLICATE TRIAL IDS
def test_killed_run_resumes():
    """
    Crash after the first period's checkpoint. Resume the same run_id. Scores and the prior-only path match a clean
    run. Trial ids are unique.

    Returns:
        None
    """
    # CRASH AFTER PERIOD 0, THEN RESUME
    crash_log_str = get_test_trial_log_path_str("resume_trial_log.csv")
    crashed_bool = False
    try:
        run_short_dict(1, "resume_run", crash_log_str, crash_after_period_id_in=0)
    except RuntimeError as error:
        crashed_bool = "runner crash after period 0" in str(error)
    assert crashed_bool, "the crash hook did not fire"
    mid_pdf = read_trial_log_pdf(crash_log_str)
    assert len(mid_pdf) >= 1 and mid_pdf["trial_id"].is_unique
    # THE FIRST CANDIDATE WAS CHECKPOINTED AT PERIOD 0 BEFORE THE CRASH
    first_checkpoint_dict = read_checkpoint_dict("resume_run", get_candidate_token_str(cand_design.CANDIDATE_LIST[0]))
    assert first_checkpoint_dict is not None and int(first_checkpoint_dict["period_id"]) == 0
    resumed_dict = run_short_dict(1, "resume_run", crash_log_str)
    clean_log_str = get_test_trial_log_path_str("resume_clean_trial_log.csv")
    clean_dict = run_short_dict(1, "resume_clean_run", clean_log_str)
    resumed_score_pdf = resumed_dict["score_pdf"].sort_values(["candidate", "fold_id"]).reset_index(drop=True)
    clean_score_pdf = clean_dict["score_pdf"].sort_values(["candidate", "fold_id"]).reset_index(drop=True)
    assert np.allclose(resumed_score_pdf["total_return"].to_numpy(dtype=float), clean_score_pdf["total_return"].to_numpy(dtype=float), atol=0.0)
    assert np.allclose(resumed_score_pdf["excess_return"].to_numpy(dtype=float), clean_score_pdf["excess_return"].to_numpy(dtype=float), atol=0.0)
    assert np.allclose(resumed_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float),
                       clean_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float), atol=0.0)
    trial_pdf = read_trial_log_pdf(crash_log_str)
    assert trial_pdf["trial_id"].is_unique
    assert len(trial_pdf) == len(cand_design.CANDIDATE_LIST) * len(resumed_dict["period_pdf"])
    passed("a run killed mid-way and resumed gives the same results and no duplicate trial ids")


# FUNCTION: ONE PROCESS WRITES STABLE TRIAL ROWS (SPAWN TARGET)
def write_stable_trial_worker(file_path_str_in, run_id_str_in, candidate_in, period_id_list_in, shared_period_id_in,
                              design_file_path_str_in, commit_str_in, hash_str_in):
    """
    Appends one row per period_id plus one shared period id. The shared id is written by every process.

    Args:
        file_path_str_in (str): Trial log
        run_id_str_in (str): Run id
        candidate_in (str): Candidate
        period_id_list_in (list[int]): Periods unique to this process
        shared_period_id_in (int): Period every process also writes
        design_file_path_str_in (str): Design file (for EXPERIMENT_NAME)
        commit_str_in, hash_str_in (str): Setting fields

    Returns:
        None
    """
    # RE-IMPORT IN THE SPAWNED PROCESS
    import importlib.util
    spec = importlib.util.spec_from_file_location("so_runner_design_worker", design_file_path_str_in)
    design_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(design_module)
    period_row = {"period_id": 0, "period_start": pd.Timestamp("2010-06-01").date(), "period_end": pd.Timestamp("2010-06-02").date()}
    score_dict = {"total_return": 0.01, "buy_hold_total_return": 0.02, "excess_return": -0.01}
    for period_id in list(period_id_list_in):
        period_row["period_id"] = int(period_id)
        log_candidate_period_trial_dict(design_module, run_id_str_in, candidate_in, period_row, score_dict,
                                        commit_str_in, hash_str_in, file_path_str_in)
    period_row["period_id"] = int(shared_period_id_in)
    log_candidate_period_trial_dict(design_module, run_id_str_in, "shared", period_row, score_dict,
                                    commit_str_in, hash_str_in, file_path_str_in)


# FUNCTION: SEVERAL PROCESSES WRITING TRIAL ROWS LOSE NOTHING AND SKIP DUPLICATES
def test_concurrent_stable_trial_rows():
    """
    Four processes write 10 unique ids each and all write one shared id. The file has 41 unique rows.

    Returns:
        None
    """
    # STABLE IDS THROUGH THE RUNNER'S LOGGING PATH
    file_path_str = get_test_trial_log_path_str("concurrent_stable_trial_log.csv")
    design_file_path_str = cand_design.__file__
    process_list = []
    for proc_idx in range(4):
        candidate = f"proc{proc_idx}"
        period_id_list = list(range(proc_idx * 10, proc_idx * 10 + 10))
        process = MP_CONTEXT.Process(target=write_stable_trial_worker,
                                     args=(file_path_str, "concurrent_run", candidate, period_id_list, 999,
                                           design_file_path_str, "testcommit", "testhash"))
        process_list.append(process)
    for process in process_list:
        process.start()
    for process in process_list:
        process.join(120)
        assert process.exitcode == 0, process.exitcode
    trial_pdf = read_trial_log_pdf(file_path_str)
    assert trial_pdf["trial_id"].is_unique
    assert len(trial_pdf) == 41
    assert list(trial_pdf.columns) == TRIAL_LOG_COLUMN_LIST
    setting_dict = json.loads(trial_pdf["setting_json"].iloc[0])
    assert setting_dict["commit"] == "testcommit" and setting_dict["design_folder_hash"] == "testhash"
    passed("several processes writing trial rows at once lose nothing and skip a duplicate id")


# FUNCTION: PARALLEL AND SINGLE-PROCESS RUNS MATCH
def test_parallel_matches_single_process():
    """
    n_jobs=1 and n_jobs=3 on the same bars give identical scores, governing candidates and prior-only equity.

    Returns:
        None
    """
    # TWO FRESH RUN IDS, THE SAME INJECTED PERIODS
    single_dict = run_short_dict(1, "parallel_single", get_test_trial_log_path_str("parallel_single.csv"))
    parallel_dict = run_short_dict(3, "parallel_multi", get_test_trial_log_path_str("parallel_multi.csv"))
    single_score_pdf = single_dict["score_pdf"].sort_values(["candidate", "fold_id"]).reset_index(drop=True)
    parallel_score_pdf = parallel_dict["score_pdf"].sort_values(["candidate", "fold_id"]).reset_index(drop=True)
    assert list(single_score_pdf["candidate"]) == list(parallel_score_pdf["candidate"])
    assert list(single_score_pdf["fold_id"]) == list(parallel_score_pdf["fold_id"])
    assert np.allclose(single_score_pdf["total_return"].to_numpy(dtype=float), parallel_score_pdf["total_return"].to_numpy(dtype=float), atol=0.0)
    assert np.allclose(single_score_pdf["excess_return"].to_numpy(dtype=float), parallel_score_pdf["excess_return"].to_numpy(dtype=float), atol=0.0)
    assert single_dict["governing_dict"] == parallel_dict["governing_dict"]
    assert np.allclose(single_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float),
                       parallel_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float), atol=0.0)
    single_trial_pdf = read_trial_log_pdf(get_test_trial_log_path_str("parallel_single.csv"))
    parallel_trial_pdf = read_trial_log_pdf(get_test_trial_log_path_str("parallel_multi.csv"))
    assert len(single_trial_pdf) == len(parallel_trial_pdf)
    assert single_trial_pdf["trial_id"].is_unique and parallel_trial_pdf["trial_id"].is_unique
    passed("parallel and single-process runs give identical results")


# FUNCTION: EACH TRIAL ROW CARRIES THE COMMIT AND THE DESIGN-FOLDER HASH
def test_trial_row_carries_commit_and_hash():
    """
    A short run writes one row per candidate-period with the injected commit and a non-empty design-folder hash.

    Returns:
        None
    """
    # ONE IN-PROCESS RUN
    log_path_str = get_test_trial_log_path_str("hash_trial_log.csv")
    result_dict = run_short_dict(1, "hash_run", log_path_str)
    trial_pdf = read_trial_log_pdf(log_path_str)
    assert len(trial_pdf) == len(cand_design.CANDIDATE_LIST) * len(result_dict["period_pdf"])
    for _, trial_row in trial_pdf.iterrows():
        setting_dict = json.loads(trial_row["setting_json"])
        assert setting_dict["commit"] == "testcommit"
        assert setting_dict["design_folder_hash"] == result_dict["design_folder_hash_str"]
        assert len(setting_dict["design_folder_hash"]) == 64
        metric_dict = json.loads(trial_row["metric_json"])
        assert "total_return" in metric_dict and "buy_hold_total_return" in metric_dict and "excess_return" in metric_dict
        expected_id = get_trial_id_str("hash_run", setting_dict["candidate"], int(trial_row["fold_id"]))
        assert trial_row["trial_id"] == expected_id
    passed("each trial row carries the commit, the design-folder hash and a stable trial id")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE A TEMPORARY FOLDER THIS FILE CREATED
    try:
        test_selection_hand_computed_tie()
        test_quarantine_is_refused()
        test_period_rule_uses_existing_code()
        test_missing_window_is_refused()
        test_prior_only_matches_manual_engine()
        test_killed_run_resumes()
        test_concurrent_stable_trial_rows()
        test_parallel_matches_single_process()
        test_trial_row_carries_commit_and_hash()
        print("\nAll runner candidate tests passed ✅")
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
            if _CURRENT_DATA_PATH_STR:
                os.environ["SO_DATA_PATH"] = _CURRENT_DATA_PATH_STR
            else:
                os.environ.pop("SO_DATA_PATH", None)
