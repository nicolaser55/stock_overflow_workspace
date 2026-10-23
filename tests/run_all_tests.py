import os
import sys
import shutil
import subprocess
import tempfile
import time

"""
Run Every Test Suite

Run from the workspace root:   python tests/run_all_tests.py
Each suite runs in its own interpreter (plain asserts; a failing suite stops with its error). Takes a few minutes.
Each suite gets its own empty temporary SO_DATA_PATH. If SO_DATA_PATH was already set, the trial log under that
folder must keep the same size and modification time.

    tests/test_shared_and_exp01.py   shared pipeline code (execution, targets, features, schedule, bad ticks) and exp01
    tests/test_exp02.py              daily features, exit/re-entry simulator, evaluation helpers, trial log and exp02
    tests/test_exp03.py              exp03 rules, random baselines, walk-forward and exploration table
    tests/test_continuous_replay.py  continuous replay, episode scorecard, log-excess bootstrap, fractional exposure (Step 0)
    tests/test_exp04.py              exp04 trend exit rules and the continuous walk-forward (so.core.replay_walk_forward)
    tests/test_exp05.py              exp05 volatility targets, weights, fractional walk-forward, baselines and signal check
    tests/test_exp06.py              exp06 capped re-entry rule, the simulator's cooling-off option and the walk-forward
    tests/test_exp07.py              exp07 warning lights, the k-of-5 rule and the walk-forward
    tests/test_vix_features.py       VIX data layer (loader cutoffs, _prev / _intraday timing, staleness, no look-ahead, formulas)
    tests/test_exp12.py              exp12 VIX re-entry rules (M1-M3, fresh-exit option of the simulator, walk-forward, reports)
    tests/test_exp13.py              exp13 E1M1 robustness (average distances, variants = frozen, delay, VIX shift, nulls, reports, verdict)
    tests/test_holdout.py            rolling holdout (window, roll, guards, ledger, causal replay; synthetic data only)
    tests/test_point_in_time.py      point-in-time registry, availability, labels, vintages, runner guards (synthetic data only)
    tests/test_runner.py             point-in-time runner view, daily loop, fractional engine (synthetic data only)
    tests/test_runner_candidates.py  runner 4b-1a: candidates, selection, trial log, checkpoints, parallel (synthetic)
    tests/test_runner_verdict.py     runner 4b-1b: baselines, verdict, report, manifest, imported-folder guards (synthetic)
    tests/test_runner_lookahead.py   runner 4b-1c: automatic look-ahead check (truncation, perturbation, leaks; synthetic)
    tests/test_runner_holdout.py     runner 4b-1d: holdout evaluation through the runner (synthetic)
    tests/test_runner_engines.py     runner 4b-2a: barrier and trailing-stop engines vs old simulators (synthetic)
    tests/test_runner_minute.py      runner 4b-2b: minute mode (rows, shuffle check, models, fill, look-ahead; synthetic)
    tests/test_rolling_retrain.py    rolling retrain sessions, purge, windows, label leak, selection, reporting (synthetic data only)
    tests/test_execute_notebook.py   notebook execution saves a failed run (synthetic notebook only)
    tests/test_holdout_baselines.py  family statistics and the span cut (the development replay is a separate argument)
    tests/test_trial_log_append.py   locked CSV append (concurrent trial rows, byte prefix, refused header and newline, lock timeout)
    tests/test_refresh_development_view.py  development-view refresh (cut, redact, slide, scan; synthetic trees only)

    Output is forced to UTF-8 (the suites print emoji; a Windows console or pipe in cp1252 would otherwise crash the print).
"""

# DEFINE THE SUITES
SUITE_LIST = ["test_shared_and_exp01.py", "test_exp02.py", "test_exp03.py", "test_continuous_replay.py", "test_exp04.py", "test_exp05.py", "test_exp06.py", "test_exp07.py", "test_vix_features.py", "test_exp12.py", "test_exp13.py", "test_holdout.py", "test_point_in_time.py", "test_runner.py", "test_runner_candidates.py", "test_runner_verdict.py", "test_runner_lookahead.py", "test_runner_holdout.py", "test_runner_engines.py", "test_runner_minute.py", "test_rolling_retrain.py", "test_execute_notebook.py", "test_holdout_baselines.py", "test_trial_log_append.py", "test_refresh_development_view.py"]
# DEFINE THE TESTS FOLDER
TESTS_PATH_STR = os.path.dirname(os.path.abspath(__file__))

# FUNCTION: SIZE AND MODIFICATION TIME OF A DATA ROOT'S TRIAL LOG
def get_trial_log_stamp_tuple(data_path_str_in):
    """
    The size and modification time of store04_experiments/trial_log.csv under a data root. The file is not read.

    Args:
        data_path_str_in (str): Data root

    Returns:
        tuple: (file path, None) when the file is absent, otherwise (file path, (size, mtime_ns))
    """
    # THE TRIAL LOG LIVES IN THE EXPERIMENT ZONE
    trial_log_path_str = os.path.join(data_path_str_in, "store04_experiments", "trial_log.csv")
    # AN ABSENT FILE IS A STAMP: THE RUN MUST NOT CREATE IT
    if not os.path.isfile(trial_log_path_str):
        return (trial_log_path_str, None)
    # RECORD THE SIZE AND THE MODIFICATION TIME
    trial_stat = os.stat(trial_log_path_str)
    return (trial_log_path_str, (trial_stat.st_size, trial_stat.st_mtime_ns))

# FUNCTION: ONE LINE FOR A TRIAL-LOG STAMP
def get_trial_log_stamp_str(stamp_in):
    """
    Formats a stamp from get_trial_log_stamp_tuple.

    Args:
        stamp_in (tuple | None): (size, mtime_ns), or None when the file is absent

    Returns:
        str: size and modification time, or "absent"
    """
    # ABSENT AND PRESENT ARE BOTH REPORTED
    if stamp_in is None:
        return "absent"
    return f"size={stamp_in[0]} mtime_ns={stamp_in[1]}"

# RUN THE SUITES
if __name__ == "__main__":
    # FORCE UTF-8 OUTPUT IN THIS PROCESS AND IN THE SUITES
    sys.stdout.reconfigure(encoding="utf-8")
    # THE CALLER'S DATA FOLDER, IF ANY, BEFORE THE SUITES REPLACE IT
    caller_data_path_str = os.environ.get("SO_DATA_PATH", "").strip()
    before_stamp_tuple = get_trial_log_stamp_tuple(caller_data_path_str) if caller_data_path_str else None
    # SUITES INHERIT THIS ENVIRONMENT, THEN RECEIVE THEIR OWN EMPTY DATA FOLDER
    suite_env_base_dict = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # A PARENT SHELL MUST NOT HAND A REAL QUARANTINE ROOT TO A SUITE
    suite_env_base_dict.pop("SO_QUARANTINE_PATH", None)
    exit_code_int = 0
    try:
        # ITERATE OVER THE SUITES
        for suite_str in SUITE_LIST:
            # DISPLAY INFORMATION
            print(f"\n===== {suite_str} =====", flush=True)
            # ONE EMPTY TEMPORARY DATA FOLDER FOR THIS SUITE
            suite_dir_str = tempfile.mkdtemp(prefix="so_suite_")
            suite_env_dict = {**suite_env_base_dict, "SO_DATA_PATH": suite_dir_str}
            start_time = time.time()
            try:
                # RUN THE SUITE
                result = subprocess.run([sys.executable, os.path.join(TESTS_PATH_STR, suite_str)], env=suite_env_dict)
            finally:
                # REMOVE THE SUITE'S TEMPORARY FOLDER
                shutil.rmtree(suite_dir_str, ignore_errors=True)
            # STOP AT THE FIRST FAILURE
            if result.returncode != 0:
                print(f"\n❌ {suite_str} failed")
                exit_code_int = result.returncode
                break
            # DISPLAY INFORMATION
            print(f"({time.time() - start_time:.0f} s)", flush=True)
    finally:
        # WHEN THE CALLER NAMED A DATA FOLDER, ITS TRIAL LOG MUST BE UNCHANGED
        if before_stamp_tuple is not None:
            after_stamp_tuple = get_trial_log_stamp_tuple(caller_data_path_str)
            print(f"trial_log before {get_trial_log_stamp_str(before_stamp_tuple[1])}", flush=True)
            print(f"trial_log after {get_trial_log_stamp_str(after_stamp_tuple[1])}", flush=True)
            if after_stamp_tuple[1] != before_stamp_tuple[1]:
                print("\n❌ trial_log.csv size or modification time changed")
                exit_code_int = exit_code_int or 1
    # DISPLAY THE RESULT
    if exit_code_int != 0:
        raise SystemExit(exit_code_int)
    print("\nAll test suites passed ✅")
