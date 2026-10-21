"""
Time the 4b-1c look-ahead check on a synthetic 4-year span with 4 candidates.

Not part of the ordinary suite. Run:

    venv-main\\Scripts\\python.exe tests\\time_runner_lookahead.py

Synthetic data only. Temporary SO_DATA_PATH. No holdout window, no shared trial-log row.
"""

import os
import sys
import time
import tempfile
import shutil
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
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_lookahead_time_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
from so import paths
from so.core.trade_execution import get_ohlcv_array_dict
from so.core.trial_log import read_trial_log_pdf
from so.runner import run_development_dict
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_timing_design as timing_design

# KEEP THE REAL REGISTRY PATH AND POINT THIS SCRIPT AT A TEMPORARY FILE
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")


# FUNCTION: TWO PERIODS THAT TILE THE SPAN
def get_two_period_pdf(session_date_list_in):
    """
    Args:
        session_date_list_in (list): Session dates

    Returns:
        pd.DataFrame: Two periods
    """
    # HALF AND HALF
    session_date_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in]
    mid_idx = len(session_date_list) // 2
    row_list = [
        {"period_id": 0, "period_start": session_date_list[0], "period_end": session_date_list[mid_idx - 1],
         "session_count": mid_idx, "valid_start": session_date_list[0], "valid_end": session_date_list[mid_idx - 1]},
        {"period_id": 1, "period_start": session_date_list[mid_idx], "period_end": session_date_list[-1],
         "session_count": len(session_date_list) - mid_idx, "valid_start": session_date_list[mid_idx],
         "valid_end": session_date_list[-1]},
    ]
    return pd.DataFrame(row_list)


# FUNCTION: RUN THE TIMING
def main():
    """
    Args:
        None

    Returns:
        None
    """
    # FOUR CALENDAR YEARS, FOUR CANDIDATES, TWO PERIODS, TWO RANDOM-TIMING SEEDS
    print("generating 2005-01-03 -> 2008-12-31 synthetic bars...", flush=True)
    gen_start = time.perf_counter()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2005-01-03", "2008-12-31", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    gen_seconds = time.perf_counter() - gen_start
    session_count = len(ohlcv_array_dict["session_date_list"])
    print(f"bars ready: {len(ohlcv_pdf)} minutes, {session_count} sessions ({gen_seconds:.1f} s)", flush=True)
    period_pdf = get_two_period_pdf(ohlcv_array_dict["session_date_list"])
    trial_log_path_str = os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "runner_lookahead_timing", "time.csv")
    os.makedirs(os.path.dirname(trial_log_path_str), exist_ok=True)
    n_jobs_int = min(8, len(timing_design.CANDIDATE_LIST))
    run_start = time.perf_counter()
    result_dict = run_development_dict(timing_design, ohlcv_array_dict, run_id_str_in="lookahead_time_4y4c",
                                       n_jobs_int_in=n_jobs_int, period_pdf_in=period_pdf,
                                       trial_log_path_str_in=trial_log_path_str, commit_str_in="testcommit",
                                       code_hash_str_in="testhash", check_clean_tree_bool_in=False,
                                       check_view_bool_in=False, baseline_seed_count_int_in=2)
    run_seconds = time.perf_counter() - run_start
    lookahead_dict = result_dict["lookahead_dict"]
    check_seconds = float(lookahead_dict["elapsed_seconds"])
    trial_pdf = read_trial_log_pdf(trial_log_path_str)
    expected_count = len(timing_design.CANDIDATE_LIST) * len(period_pdf)
    print(f"full run {run_seconds:.1f} s", flush=True)
    print(f"look-ahead check {check_seconds:.1f} s "
          f"(cuts={lookahead_dict['cut_date_list']}, pass={lookahead_dict['pass_bool']}, "
          f"n_jobs={n_jobs_int}, candidates={len(timing_design.CANDIDATE_LIST)})", flush=True)
    print(f"trial rows {len(trial_pdf)} (expected {expected_count})", flush=True)
    print(f"LOOKAHEAD_ADDED_SECONDS={check_seconds:.3f}", flush=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
            os.environ.pop("SO_DATA_PATH", None)
