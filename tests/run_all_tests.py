import os
import sys
import shutil
import subprocess
import tempfile
import time

"""
Run the Test Suites

    python tests/run_all_tests.py           every suite (before a merge or a pull request)
    python tests/run_all_tests.py --fast    every suite except the two slow ones (minute mode, experiments), after an edit

Each suite runs in its own interpreter with its own empty temporary SO_DATA_PATH. A failing suite does not stop the
others; the end lists every failing suite. If SO_DATA_PATH was already set, the trial log under that folder must keep
the same size and modification time. Output is forced to UTF-8 (the suites print emoji).

Suite (fast set marked F):
    test_pipeline_shared.py       F  pipeline code: execution, barrier targets, features, costs, plots, bad ticks
    test_daily_shared.py          F  daily features and label, simulator reference, schedule
    test_vix_features.py          F  VIX data layer (loader cutoffs, _prev / _intraday timing, staleness, formulas)
    test_holdout.py               F  holdout window, roll, slide, guards, quarantine load, view stamp, design hash
    test_point_in_time.py         F  point-in-time registry, availability, labels, vintages
    test_rolling_retrain.py       F  retrain calendar, template refit log
    test_trial_log_append.py      F  locked CSV append (concurrent rows, byte prefix, refused header and newline, lock timeout)
    test_tools.py                 F  run queue, state, email, protected paths, package lock
    test_execute_notebook.py      F  notebook execution saves a failed run
    test_runner.py                F  runner view, daily loop, fractional engine
    test_runner_engines.py        F  barrier and trailing-stop engines vs the old simulators
    test_runner_candidates.py     F  candidates, selection, trial log, checkpoints, parallel
    test_runner_verdict.py        F  baselines, verdict, report, manifest, imported-folder guards
    test_runner_lookahead.py      F  automatic look-ahead check (truncation, perturbation, leaks)
    test_runner_holdout.py        F  holdout evaluation through the runner
    test_refresh_development_view.py F  development-view refresh (cut, redact, slide, scan)
    test_runner_minute.py            minute mode (rows, shuffle check, models, fill, look-ahead, shared fits)
    test_experiments.py              every experiment design on the runner, view histories, look-ahead
"""

# DEFINE THE SUITES AND THE FAST SET
SUITE_LIST = ["test_pipeline_shared.py", "test_daily_shared.py", "test_vix_features.py", "test_holdout.py",
              "test_point_in_time.py", "test_rolling_retrain.py", "test_trial_log_append.py", "test_tools.py",
              "test_execute_notebook.py", "test_runner.py", "test_runner_engines.py", "test_runner_candidates.py",
              "test_runner_verdict.py", "test_runner_lookahead.py", "test_runner_holdout.py",
              "test_refresh_development_view.py", "test_runner_minute.py", "test_experiments.py"]
SLOW_SUITE_SET = {"test_runner_minute.py", "test_experiments.py"}
FAST_SUITE_LIST = [suite_str for suite_str in SUITE_LIST if suite_str not in SLOW_SUITE_SET]
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
    failed_list = []
    try:
        # THE FAST SET OR EVERY SUITE
        suite_list = FAST_SUITE_LIST if "--fast" in sys.argv[1:] else SUITE_LIST
        print(f"{'fast set' if suite_list is FAST_SUITE_LIST else 'all suites'}: {len(suite_list)} suites", flush=True)
        for suite_str in suite_list:
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
            # RECORD A FAILURE AND CONTINUE, SO ONE RUN LISTS EVERY FAILING SUITE
            elapsed_str = f"{time.time() - start_time:.0f} s"
            if result.returncode != 0:
                print(f"\n❌ {suite_str} failed ({elapsed_str})", flush=True)
                failed_list.append(suite_str)
                exit_code_int = exit_code_int or result.returncode
            else:
                print(f"({elapsed_str})", flush=True)
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
        print(f"\n❌ failed suites: {', '.join(failed_list) if failed_list else '(trial log changed)'}")
        raise SystemExit(exit_code_int)
    print("\nAll test suites passed ✅")
