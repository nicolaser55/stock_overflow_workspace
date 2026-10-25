"""
Workspace Tests: design-code guard (so.runner.guard and the preflight write rule; audit B2, 2026-10-25)

Run from the workspace root:   python tests/test_runner_guard.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The data root is a temporary folder.
"""

import os
import sys
import tempfile
import shutil
import subprocess

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_guard_")
os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
from so import config
from so.core.trade_execution import get_ohlcv_array_dict
from so.runner import run_daily_dict, check_design_file
from so.runner.guard import design_code_guard, get_module_snapshot_dict, check_module_snapshot
from so.runner.run import get_file_design_module
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_guard_design as guard_design


def passed(name_str_in):
    """
    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")


# FUNCTION: THE SHORT SYNTHETIC SPAN EVERY TEST USES
def get_span_tuple():
    """
    Returns:
        tuple: ohlcv_array_dict, date1, date2
    """
    # THREE WEEKS OF BARS
    ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=4))
    return ohlcv_array_dict, ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]


# FUNCTION: THE FILE GUARD REFUSES DATA FILES, SUBPROCESSES, AND NOTHING OUTSIDE
def test_file_guard_unit():
    """
    Inside a guarded block: opening or listing under SO_DATA_PATH and starting a subprocess raise PermissionError.
    Outside the block, and for a file outside the data root, nothing is refused.

    Returns:
        None
    """
    # A FILE UNDER THE DATA ROOT AND ONE OUTSIDE IT
    inside_path_str = os.path.join(TEMP_ROOT_STR, "store02_workzone", "x.csv")
    os.makedirs(os.path.dirname(inside_path_str), exist_ok=True)
    with open(inside_path_str, "w", encoding="utf-8") as file_obj:
        file_obj.write("a\n1\n")
    outside_dir_str = tempfile.mkdtemp(prefix="so_guard_outside_")
    outside_path_str = os.path.join(outside_dir_str, "y.txt")
    try:
        with open(outside_path_str, "w", encoding="utf-8") as file_obj:
            file_obj.write("ok")
        for action_str, action in [("open", lambda: open(inside_path_str, encoding="utf-8").read()),
                                   ("listdir", lambda: os.listdir(TEMP_ROOT_STR)),
                                   ("remove", lambda: os.remove(inside_path_str)),
                                   ("subprocess", lambda: subprocess.run([sys.executable, "-c", "pass"]))]:
            refused_bool = False
            with design_code_guard():
                try:
                    action()
                except PermissionError:
                    refused_bool = True
            assert refused_bool, f"the guard allowed {action_str}"
        with design_code_guard():
            assert open(outside_path_str, encoding="utf-8").read() == "ok"
        assert open(inside_path_str, encoding="utf-8").read().startswith("a")
    finally:
        shutil.rmtree(outside_dir_str, ignore_errors=True)
    passed("file guard: data-root open, list, delete and subprocesses refused inside design code only")


# FUNCTION: A DESIGN READING A CACHE THROUGH A SHARED HELPER STOPS THE RUN
def test_reading_design_fails():
    """
    so.core.local_file_management.read_csv_file_from_path was not blocked by the old direct-read flag. Called from
    decide(), the run must stop.

    Returns:
        None
    """
    # A CSV UNDER THE DATA ROOT
    ohlcv_array_dict, date1, date2 = get_span_tuple()
    file_path_str = os.path.join(TEMP_ROOT_STR, "store03_goldzone", "labels.csv")
    os.makedirs(os.path.dirname(file_path_str), exist_ok=True)
    with open(file_path_str, "w", encoding="utf-8") as file_obj:
        file_obj.write("date,value\n2010-06-02,1\n")
    guard_design.TARGET_FILE_PATH_STR = file_path_str
    refused_bool = False
    try:
        run_daily_dict(guard_design.ReadingDesign(), ohlcv_array_dict, date1, date2)
    except PermissionError:
        refused_bool = True
    assert refused_bool, "a design read a data file from decide()"
    run_daily_dict(guard_design.CleanDesign(), ohlcv_array_dict, date1, date2)
    passed("a design reading a data file through a shared helper stops the run; a clean design runs")


# FUNCTION: A DESIGN REWRITING so.config STOPS THE RUN
def test_rewriting_design_fails():
    """
    Setting so.config.ENTRY_SLIPPAGE_PER_SHARE from decide() is caught by the module guard.

    Returns:
        None
    """
    # RESTORE THE CONSTANT WHATEVER HAPPENS
    ohlcv_array_dict, date1, date2 = get_span_tuple()
    original_float = config.ENTRY_SLIPPAGE_PER_SHARE
    refused_bool = False
    try:
        run_daily_dict(guard_design.RewritingDesign(), ohlcv_array_dict, date1, date2)
    except RuntimeError as error:
        refused_bool = "ENTRY_SLIPPAGE_PER_SHARE" in str(error)
    finally:
        config.ENTRY_SLIPPAGE_PER_SHARE = original_float
    assert refused_bool, "a design rewrote so.config unnoticed"
    passed("a design rewriting so.config from decide() stops the run and names the constant")


# FUNCTION: A DESIGN FILE REWRITING SHARED CODE AT IMPORT IS REFUSED
def test_import_rewrite_refused():
    """
    get_file_design_module executes the file behind the guard and compares so.* afterwards: a top-level
    reassignment of a shared function or of the label horizon raises. The preflight refuses the same file first.

    Returns:
        None
    """
    # TWO FILES: ONE REPLACES THE FEE FUNCTION, ONE CHANGES THE LABEL HORIZON
    temp_dir_str = tempfile.mkdtemp(prefix="so_guard_import_")
    original_horizon = config.LABEL_HORIZON_SESSIONS
    import so.core.trade_execution as trade_execution
    original_fee = trade_execution.calculate_side_fee
    source_dict = {
        "fee": "from so.core import trade_execution\ntrade_execution.calculate_side_fee = lambda a, b: 0.0\n",
        "horizon": "from so import config as so_config\nso_config.LABEL_HORIZON_SESSIONS = 5\n",
        "setattr": "from so import config\nsetattr(config, 'LABEL_HORIZON_SESSIONS', 5)\n",
        "sys": "import sys\nsys.modules['so.config'].LABEL_HORIZON_SESSIONS = 5\n",
    }
    try:
        for name_str, source_str in source_dict.items():
            file_path_str = os.path.join(temp_dir_str, f"design_{name_str}.py")
            with open(file_path_str, "w", encoding="utf-8") as file_obj:
                file_obj.write(source_str)
            preflight_bool = False
            try:
                check_design_file(file_path_str)
            except ValueError:
                preflight_bool = True
            assert preflight_bool, f"the preflight accepted the {name_str} rewrite"
            runtime_bool = False
            try:
                get_file_design_module(file_path_str)
            except RuntimeError:
                runtime_bool = True
            finally:
                config.LABEL_HORIZON_SESSIONS = original_horizon
                trade_execution.calculate_side_fee = original_fee
            assert runtime_bool, f"the module guard accepted the {name_str} rewrite at import"
    finally:
        shutil.rmtree(temp_dir_str, ignore_errors=True)
    passed("a design file rewriting the fee function or the label horizon is refused by the preflight and at import")


# FUNCTION: AN UNCHANGED PROCESS PASSES THE MODULE CHECK
def test_snapshot_stable():
    """
    Two snapshots with no design in between compare equal, so the guard does not stop a clean run.

    Returns:
        None
    """
    # NOTHING CHANGES BETWEEN THE TWO
    snapshot_dict = get_module_snapshot_dict()
    assert len(snapshot_dict) > 100
    check_module_snapshot(snapshot_dict, "in the stability test")
    passed(f"module snapshot is stable on a clean process ({len(snapshot_dict)} attributes compared)")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY DATA ROOT
    try:
        test_snapshot_stable()
        test_file_guard_unit()
        test_reading_design_fails()
        test_rewriting_design_fails()
        test_import_rewrite_refused()
        print("\nAll runner guard tests passed ✅")
    finally:
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
