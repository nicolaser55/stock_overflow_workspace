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
"""

# DEFINE THE SUITES
SUITE_LIST = ["test_shared_and_exp01.py", "test_exp02.py", "test_exp03.py"]
# DEFINE THE TESTS FOLDER
TESTS_PATH_STR = os.path.dirname(os.path.abspath(__file__))

# RUN THE SUITES
if __name__ == "__main__":
    # ITERATE OVER THE SUITES
    for suite_str in SUITE_LIST:
        # DISPLAY INFORMATION
        print(f"\n===== {suite_str} =====", flush=True)
        start_time = time.time()
        # RUN THE SUITE
        result = subprocess.run([sys.executable, os.path.join(TESTS_PATH_STR, suite_str)])
        # STOP AT THE FIRST FAILURE
        if result.returncode != 0:
            print(f"\n❌ {suite_str} failed")
            raise SystemExit(result.returncode)
        # DISPLAY INFORMATION
        print(f"({time.time() - start_time:.0f} s)")
    # DISPLAY THE RESULT
    print("\nAll test suites passed ✅")
