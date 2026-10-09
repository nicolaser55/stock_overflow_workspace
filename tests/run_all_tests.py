import os
import sys
import subprocess
import time

"""
Run Every Test Suite

Run from the workspace root:   python tests/run_all_tests.py
Each suite runs in its own interpreter (plain asserts; a failing suite stops with its error). Takes a few minutes.

    tests/test_shared_and_exp01.py   shared pipeline code (execution, targets, features, schedule, bad ticks) and exp01
    tests/test_exp02.py              daily features, exit/re-entry simulator, evaluation helpers, trial log and exp02
    tests/test_exp03.py              exp03 rules, random baselines, walk-forward and exploration table
    tests/test_continuous_replay.py  continuous replay, episode scorecard, log-excess bootstrap, fractional exposure (Step 0)
    tests/test_exp04.py              exp04 trend exit rules and the continuous walk-forward (so.core.replay_walk_forward)
    tests/test_exp05.py              exp05 volatility targets, weights, fractional walk-forward, baselines and signal check
    tests/test_exp06.py              exp06 capped re-entry rule, the simulator's cooling-off option and the walk-forward
    tests/test_exp07.py              exp07 warning lights, the k-of-5 rule and the walk-forward
    tests/test_exp01_step04.py       exp01 step 04 multivariate signal check (planted interaction, noise, null, parallel)
    tests/test_vix_features.py       VIX data layer (loader cutoffs, _prev / _intraday timing, staleness, no look-ahead, formulas)
    tests/test_exp08.py              exp08 VIX gate (analysis rows, shifted null, G1-G4 on planted data, gate decisions)
    tests/test_exp12.py              exp12 VIX re-entry rules (M1-M3, fresh-exit option of the simulator, walk-forward, reports)

    Output is forced to UTF-8 (the suites print emoji; a Windows console or pipe in cp1252 would otherwise crash the print).
"""

# DEFINE THE SUITES
SUITE_LIST = ["test_shared_and_exp01.py", "test_exp02.py", "test_exp03.py", "test_continuous_replay.py", "test_exp04.py", "test_exp05.py", "test_exp06.py", "test_exp07.py", "test_exp01_step04.py", "test_vix_features.py", "test_exp08.py", "test_exp12.py"]
# DEFINE THE TESTS FOLDER
TESTS_PATH_STR = os.path.dirname(os.path.abspath(__file__))

# RUN THE SUITES
if __name__ == "__main__":
    # FORCE UTF-8 OUTPUT IN THIS PROCESS AND IN THE SUITES
    sys.stdout.reconfigure(encoding="utf-8")
    suite_env_dict = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # ITERATE OVER THE SUITES
    for suite_str in SUITE_LIST:
        # DISPLAY INFORMATION
        print(f"\n===== {suite_str} =====", flush=True)
        start_time = time.time()
        # RUN THE SUITE
        result = subprocess.run([sys.executable, os.path.join(TESTS_PATH_STR, suite_str)], env=suite_env_dict)
        # STOP AT THE FIRST FAILURE
        if result.returncode != 0:
            print(f"\n❌ {suite_str} failed")
            raise SystemExit(result.returncode)
        # DISPLAY INFORMATION
        print(f"({time.time() - start_time:.0f} s)", flush=True)
    # DISPLAY THE RESULT
    print("\nAll test suites passed ✅")
