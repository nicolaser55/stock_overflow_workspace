"""
Workspace Tests: pre-registration guard and cost sensitivity (so.runner.preregistration, so.runner.run; audit S5 and
S8, 2026-10-25)

Run from the workspace root:   python tests/test_runner_protocol.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The data root is a temporary folder.
"""

import json
import os
import sys
import tempfile
import shutil
import types

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_protocol_")
os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
import pandas as pd
from so import paths
from so.core.trade_execution import get_ohlcv_array_dict
from so.runner import run_development_dict
from so.runner.preregistration import check_preregistration_dict, get_protocol_missing_list
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_candidate_design as cand_design

# KEEP THE REAL REGISTRY PATH AND POINT THIS SUITE AT A TEMPORARY FILE
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")


def passed(name_str_in):
    """
    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")


# FUNCTION: A FULL PROTOCOL TEXT THAT PASSES THE LINT
def get_full_protocol_str():
    """
    Returns:
        str: Markdown with every required section
    """
    # THE TEMPLATE'S SECTIONS, SHORT
    return ("# expZZ\n\nDerived from: none\n\n## 1. Background and research question\nq\n## 2. Success criteria\ns\n"
            "## 3.1 Data sources\nd\n## 4. Rules\nr\n## 5. Walk-forward and selection\nw\n## 6. Baselines\nb\n"
            "## 7. Stopping rules\nx\n## 9. Discipline, implementation, limitations\nl\n## 11. Change log\nc\n")


# FUNCTION: EVERY BRANCH OF THE PRE-REGISTRATION GUARD
def test_preregistration_guard():
    """
    Rerun of logged code passes; changed code under a logged version, a protocol missing sections, a non-preregister
    last commit and a fourth version are refused; a proper first run passes and returns its Derived from line.

    Returns:
        None
    """
    # A DESIGN FOLDER AND A TRIAL LOG
    folder_str = tempfile.mkdtemp(prefix="so_prereg_design_", dir=TEMP_ROOT_STR)
    log_path_str = os.path.join(TEMP_ROOT_STR, "prereg_trial_log.csv")
    module = types.SimpleNamespace(EXPERIMENT_NAME="expZZ_test", PROTOCOL_VERSION="1.0")

    def write_log(row_list_in):
        pd.DataFrame(row_list_in).to_csv(log_path_str, index=False)

    def git_func_factory(subject_str_in):
        return lambda arg_list_in: subject_str_in + "\n"

    def refused_bool(call_in):
        try:
            call_in()
        except ValueError:
            return True
        return False

    row_dict = {"experiment": "expZZ_test", "protocol_version": "1.0", "stage": "validation",
                "setting_json": json.dumps({"candidate": "A", "design_folder_hash": "hash_one"}), "metric_json": "{}"}
    write_log([row_dict])
    rerun_dict = check_preregistration_dict(module, folder_str, "hash_one", log_path_str, git_func_factory("anything"))
    assert rerun_dict["status_str"] == "rerun"
    assert refused_bool(lambda: check_preregistration_dict(module, folder_str, "hash_two", log_path_str, git_func_factory("x")))
    # A NEW VERSION
    module_new = types.SimpleNamespace(EXPERIMENT_NAME="expZZ_test", PROTOCOL_VERSION="1.1")
    protocol_path_str = os.path.join(folder_str, "PROTOCOL.md")
    with open(protocol_path_str, "w", encoding="utf-8") as file_obj:
        file_obj.write("# expZZ\n\n## Question\nq\n## Rules\nr\n## Change log\nc\n")
    assert refused_bool(lambda: check_preregistration_dict(module_new, folder_str, "hash_two", log_path_str,
                                                           git_func_factory("preregister expZZ")))
    with open(protocol_path_str, "w", encoding="utf-8") as file_obj:
        file_obj.write(get_full_protocol_str())
    assert refused_bool(lambda: check_preregistration_dict(module_new, folder_str, "hash_two", log_path_str,
                                                           git_func_factory("tweak expZZ after results")))
    first_dict = check_preregistration_dict(module_new, folder_str, "hash_two", log_path_str,
                                            git_func_factory("preregister expZZ v1.1"))
    assert first_dict["status_str"] == "first_run" and first_dict["derived_from_str"] == "none"
    # A FOURTH VERSION
    write_log([row_dict, {**row_dict, "protocol_version": "1.1"}, {**row_dict, "protocol_version": "1.2"}])
    module_fourth = types.SimpleNamespace(EXPERIMENT_NAME="expZZ_test", PROTOCOL_VERSION="1.3")
    assert refused_bool(lambda: check_preregistration_dict(module_fourth, folder_str, "hash_two", log_path_str,
                                                           git_func_factory("preregister expZZ v1.3")))
    # THE TEMPLATE PASSES THE LINT; A PORTED 1.0 PROTOCOL DOES NOT (IT IS GRANDFATHERED BY ITS LOGGED RUNS)
    assert get_protocol_missing_list(open(os.path.join(WORKSPACE_PATH_STR, "experiments", "_template", "PROTOCOL.md"),
                                          encoding="utf-8").read()) == []
    assert get_protocol_missing_list("## Question\n## Rules\n") != []
    passed("pre-registration: rerun of logged code, changed code refused, lint, preregister commit, at most three versions")


# FUNCTION: THE REPORT CARRIES THE COST SENSITIVITY
def test_cost_sensitivity_in_report():
    """
    A development run reports the prior-only path and buy-and-hold at slippage 0.00, 0.01 and 0.02; more slippage
    never helps.

    Returns:
        None
    """
    # THE 4B-1A SYNTHETIC DESIGN ON THREE WEEKS
    ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4))
    session_list = [pd.Timestamp(day).date() for day in ohlcv_array_dict["session_date_list"]]
    bound_list = [(0, 3), (4, 7), (8, len(session_list) - 1)]
    period_pdf = pd.DataFrame([{"period_id": idx, "period_start": session_list[start_idx], "period_end": session_list[end_idx],
                                "session_count": end_idx - start_idx + 1, "valid_start": session_list[start_idx],
                                "valid_end": session_list[end_idx]} for idx, (start_idx, end_idx) in enumerate(bound_list)])
    result_dict = run_development_dict(cand_design, ohlcv_array_dict, run_id_str_in="protocol_cost", n_jobs_int_in=1,
                                       period_pdf_in=period_pdf, trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "cost.csv"),
                                       commit_str_in="testcommit", code_hash_str_in="testhash", check_clean_tree_bool_in=False,
                                       check_view_bool_in=False, baseline_seed_count_int_in=2, run_lookahead_bool_in=False)
    cost_list = result_dict["report_dict"]["cost_sensitivity_list"]
    assert [row_dict["slippage_per_share"] for row_dict in cost_list] == [0.0, 0.01, 0.02]
    assert cost_list[0]["strategy_total_return"] >= cost_list[2]["strategy_total_return"]
    assert cost_list[0]["buy_hold_total_return"] >= cost_list[2]["buy_hold_total_return"]
    with open(os.path.join(result_dict["run_folder_str"], "report.md"), encoding="utf-8") as file_obj:
        assert "Cost sensitivity" in file_obj.read()
    passed("development report carries the prior-only path and buy-and-hold at slippage 0.00 / 0.01 / 0.02")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY DATA ROOT
    try:
        test_preregistration_guard()
        test_cost_sensitivity_in_report()
        print("\nAll runner protocol tests passed ✅")
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
