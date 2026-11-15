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
import numpy as np
import pandas as pd
from so import paths
from so.core.trade_execution import get_ohlcv_array_dict
from so.runner import run_development_dict
from so.runner.preregistration import (check_preregistration_dict, get_protocol_missing_list, get_design_helper_dict,
                                      get_design_helper_file_list, get_trial_log_version_row_list,
                                      REGISTERED_VERSION_COLUMN_LIST)
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
    return ("# expZZ\n\nDerived from: none\n\nFamily: C, idea C1, variant 1 of 5\n\n"
            "## 1. Background and research question\nq\n## 2. Success criteria\ns\n"
            "## 3.1 Data sources\nd\n## 4. Rules\nr\n## 5. Walk-forward and selection\nw\n## 6. Baselines\nb\n"
            "## 7. Stopping rules\nx\n## 9. Discipline, implementation, limitations\nl\n## 11. Change log\n"
            "| Version | Date | Change |\n|---|---|---|\n| 1.0 | 2026-11-14 | Initial protocol |\n"
            "| 1.1 | 2026-11-15 | bug-fix: the exit used the wrong column |\n"
            "| 1.2 | 2026-11-16 | data-dependent: a wider buffer after the 1.1 result |\n"
            "| 1.3 | 2026-11-17 | data-dependent: a fourth version |\n")


# FUNCTION: THE GUARD KEEPS ITS MEMORY ACROSS A RESET (records/legacy/registered_versions.csv; 2026-11-09)
def test_registered_versions_survive_reset():
    """
    With the trial log moved away (a reset), a logged version is still a rerun when the registered-versions file holds
    it: the same code passes even with an old protocol; changed folder code, changed helper code and a fourth version
    are still refused. Without the file the old protocol is refused (the crash of the first baseline rerun). A file
    without the columns is refused, never read as empty.

    Returns:
        None
    """
    # A LOG WITH THREE VERSIONS, ITS REGISTERED ROWS, THEN NO LOG
    folder_str = tempfile.mkdtemp(prefix="so_prereg_reset_", dir=TEMP_ROOT_STR)
    with open(os.path.join(folder_str, "PROTOCOL.md"), "w", encoding="utf-8") as file_obj:
        file_obj.write("# expYY\n\n## Hypothesis\nold protocol, before the lint\n")
    log_path_str = os.path.join(TEMP_ROOT_STR, "reset_trial_log.csv")
    registered_str = os.path.join(TEMP_ROOT_STR, "reset_registered_versions.csv")
    missing_log_str = os.path.join(TEMP_ROOT_STR, "moved_trial_log.csv")

    def git_func(arg_list_in):
        return "port expYY\n"

    def refused_bool(call_in):
        try:
            call_in()
        except ValueError:
            return True
        return False

    base_dict = {"experiment": "expYY_reset", "stage": "validation", "metric_json": "{}"}
    pd.DataFrame([{**base_dict, "protocol_version": "1.0", "setting_json": json.dumps({"design_folder_hash": "f1", "helper_hash": "h1"})},
                  {**base_dict, "protocol_version": "1.0", "setting_json": json.dumps({"design_folder_hash": "f1", "helper_hash": "h1"})},
                  {**base_dict, "protocol_version": "1.1", "setting_json": json.dumps({"design_folder_hash": "f2"})},
                  {**base_dict, "protocol_version": "1.2", "stage": "note", "setting_json": "{}"}]).to_csv(log_path_str, index=False)
    row_list = get_trial_log_version_row_list(log_path_str, "test")
    assert [(row_dict["protocol_version"], row_dict["design_folder_hash"], row_dict["helper_hash"]) for row_dict in row_list] == \
        [("1.0", "f1", "h1"), ("1.1", "f2", ""), ("1.2", "", "")]
    pd.DataFrame(row_list, columns=REGISTERED_VERSION_COLUMN_LIST).to_csv(registered_str, index=False)
    module = types.SimpleNamespace(EXPERIMENT_NAME="expYY_reset", PROTOCOL_VERSION="1.0")
    call_dict = {"git_func_in": git_func, "registered_path_str_in": registered_str}
    # THE SAME CODE RERUNS WITH ITS OLD PROTOCOL; CHANGED CODE OR HELPERS DO NOT
    assert check_preregistration_dict(module, folder_str, "f1", missing_log_str, helper_hash_str_in="h1", **call_dict)["status_str"] == "rerun"
    assert refused_bool(lambda: check_preregistration_dict(module, folder_str, "f9", missing_log_str, helper_hash_str_in="h1", **call_dict))
    assert refused_bool(lambda: check_preregistration_dict(module, folder_str, "f1", missing_log_str, helper_hash_str_in="h9", **call_dict))
    # A VERSION WITHOUT LOGGED HELPER HASHES ACCEPTS THE FIRST ONE; A FOURTH VERSION IS STILL REFUSED
    module_11 = types.SimpleNamespace(EXPERIMENT_NAME="expYY_reset", PROTOCOL_VERSION="1.1")
    assert check_preregistration_dict(module_11, folder_str, "f2", missing_log_str, helper_hash_str_in="h5", **call_dict)["status_str"] == "rerun"
    module_13 = types.SimpleNamespace(EXPERIMENT_NAME="expYY_reset", PROTOCOL_VERSION="1.3")
    with open(os.path.join(folder_str, "PROTOCOL.md"), "w", encoding="utf-8") as file_obj:
        file_obj.write(get_full_protocol_str())
    assert refused_bool(lambda: check_preregistration_dict(module_13, folder_str, "f3", missing_log_str,
                                                           git_func_in=lambda arg_list_in: "preregister expYY v1.3",
                                                           registered_path_str_in=registered_str))
    # TRIAL LOG AND FILE TOGETHER: A HASH IN EITHER IS ACCEPTED
    pd.DataFrame([{**base_dict, "protocol_version": "1.0", "setting_json": json.dumps({"design_folder_hash": "f7", "helper_hash": "h1"})}]).to_csv(log_path_str, index=False)
    with open(os.path.join(folder_str, "PROTOCOL.md"), "w", encoding="utf-8") as file_obj:
        file_obj.write("# expYY\n\n## Hypothesis\nold protocol, before the lint\n")
    for hash_str in ["f1", "f7"]:
        assert check_preregistration_dict(module, folder_str, hash_str, log_path_str, helper_hash_str_in="h1", **call_dict)["status_str"] == "rerun"
    # WITHOUT THE FILE (THE FIRST RESET): THE OLD PROTOCOL IS REFUSED AS A NEW VERSION
    empty_registered_str = os.path.join(TEMP_ROOT_STR, "no_registered_versions.csv")
    assert refused_bool(lambda: check_preregistration_dict(module, folder_str, "f1", missing_log_str, git_func_in=git_func,
                                                           helper_hash_str_in="h1", registered_path_str_in=empty_registered_str))
    # A FILE WITHOUT THE COLUMNS IS REFUSED
    bad_str = os.path.join(TEMP_ROOT_STR, "bad_registered_versions.csv")
    pd.DataFrame([{"experiment": "expYY_reset", "protocol_version": "1.0"}]).to_csv(bad_str, index=False)
    assert refused_bool(lambda: check_preregistration_dict(module, folder_str, "f1", missing_log_str, git_func_in=git_func,
                                                           registered_path_str_in=bad_str))
    passed("registered versions survive a reset (old protocol reruns; changed code, changed helper and a fourth version "
           "refused; trial log and file merged; no file = the 2026-11-09 refusal; a malformed file refused)")


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
    # A DESIGN FOLDER ON ANOTHER WINDOWS DRIVE (relpath RAISES THERE): THE CHECK STILL ANSWERS
    import so.runner.preregistration as preregistration_module
    original_relpath = preregistration_module.os.path.relpath

    def raising_relpath(*arg_tuple_in, **kwarg_dict_in):
        raise ValueError("path is on mount 'C:', start on mount 'D:'")
    preregistration_module.os.path.relpath = raising_relpath
    try:
        seen_list = []
        subject_str = preregistration_module.get_last_folder_commit_subject_str(
            folder_str, lambda arg_list_in: seen_list.append(arg_list_in) or "preregister expZZ\n")
        assert subject_str == "preregister expZZ" and seen_list[0][-1] == os.path.abspath(folder_str).replace("\\", "/")
    finally:
        preregistration_module.os.path.relpath = original_relpath
    passed("pre-registration: rerun of logged code, changed code refused, lint, preregister commit, at most three versions, other drive")


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
        report_md_str = file_obj.read()
    assert "Cost sensitivity" in report_md_str and "Random timing counted, not fitted" in report_md_str
    # THE COUNTED RANDOM-TIMING TEST IS IN report.json; A REDUCED SEED COUNT (2) DRAWS NOTHING EXTRA AND CANNOT PASS
    with open(os.path.join(result_dict["run_folder_str"], "report.json"), encoding="utf-8") as file_obj:
        tail_dict = json.load(file_obj)["multiple_testing_dict"]["random_timing_tail_dict"]
    assert tail_dict["method_str"] == "empirical" and tail_dict["draw_count"] == 2 and not tail_dict["extension_bool"]
    assert not tail_dict["pass_bool"] and not tail_dict["tail_mismatch_bool"]
    # R4: EACH LEVEL RE-APPLIES THE RETURN CHECK; THE 0.01 LEVEL AGREES WITH THE VERDICT; THE GRADE IS IN THE REPORT,
    # THE MANIFEST AND report.md, AND N COUNTS THE PILOT LEDGER (2026-11-10)
    assert all(isinstance(row_dict["return_pass_bool"], bool) and row_dict["return_reason_str"] for row_dict in cost_list)
    assert cost_list[1]["return_pass_bool"] == result_dict["verdict_dict"]["return_dict"]["pass_bool"]
    from so.runner.grade import REASON_DICT
    grade_dict = result_dict["report_dict"]["grade_dict"]
    assert REASON_DICT[grade_dict["reason_code_str"]][0] == grade_dict["grade_str"]
    assert grade_dict["reason_code_str"] == "look_ahead_not_run"           # THE LOOK-AHEAD CHECK WAS SKIPPED HERE
    assert result_dict["manifest_dict"]["verdict"]["grade"] == grade_dict["grade_str"]
    assert result_dict["manifest_dict"]["verdict"]["grade_reason_code"] == grade_dict["reason_code_str"]
    assert "Grade (what the planner sees)" in report_md_str and "the verdict's N, pilot included" in report_md_str
    assert "With the pilot designs included" not in report_md_str
    multiple_dict = result_dict["report_dict"]["multiple_testing_dict"]
    assert multiple_dict["design_count"] >= 260 and multiple_dict["design_count_scope_str"] == "pilot_included"
    assert multiple_dict["current_design_count"] < multiple_dict["design_count"] and "pilot_included_dict" not in multiple_dict
    assert multiple_dict["random_timing_tail_dict"]["design_count"] == multiple_dict["design_count"]
    passed("development report carries the prior-only path and buy-and-hold at slippage 0.00 / 0.01 / 0.02, each with the "
           "return check, the grade, and N with the pilot ledger included")
    # THE TAIL-CHECK SCRIPT REBUILDS THIS FINISHED RUN'S PRIOR-ONLY PATH FROM THE PRUNED FOLDER (R3B, 2026-11-02)
    sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "scripts"))
    import check_random_timing_tail as tail_script
    from so.runner.baselines import get_exposure_weight_arr
    from so.runner.run import get_realized_exposure_bool
    from so.runner.checkpoint import set_runs_root_str
    assert not os.path.isfile(os.path.join(result_dict["run_folder_str"], "strategy_daily_equity.csv"))
    try:
        rebuilt_dict, date1, date2 = tail_script.get_rebuilt_prior_only_tuple(cand_design, ohlcv_array_dict,
                                                                              result_dict["run_folder_str"], "protocol_cost")
    finally:
        set_runs_root_str(None)
    report_dict = result_dict["report_dict"]
    assert abs(rebuilt_dict["metric_dict"]["total_return"] - report_dict["return_dict"]["strategy_total_return"]) <= 1e-9
    exposure_arr = get_exposure_weight_arr(rebuilt_dict, get_realized_exposure_bool(cand_design))
    draw_list = tail_script.get_draw_return_list([42, 43], ohlcv_array_dict, date1, date2, exposure_arr, 1)
    assert np.allclose(draw_list, report_dict["baseline_dict"]["random_timing_return_list"][:2], rtol=0, atol=1e-12)
    # THE DEFLATED-SHARPE TAIL SCRIPT'S IDENTITY: THE RUN'S DSR, RECOMPUTED FROM THE REBUILT PATH, EQUALS THE REPORT'S
    import check_deflated_sharpe_tail as dsr_script
    from so.core.multiple_testing import get_quarter_excess_arr
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    from so.runner.verdict import get_equity_daily_return_pdf
    basis_dict, basis_str = tail_script.get_report_basis_bundle_dict(ohlcv_array_dict, report_dict)
    assert basis_str == report_dict["return_basis_str"]
    multiple_dict = report_dict["multiple_testing_dict"]
    buy_hold_return_pdf = get_equity_daily_return_pdf(get_buy_and_hold_result_dict(basis_dict, date1, date2)["daily_equity_pdf"])
    path_excess_arr = get_quarter_excess_arr(get_equity_daily_return_pdf(rebuilt_dict["daily_equity_pdf"]), buy_hold_return_pdf)
    recomputed_float = float(dsr_script.get_dsr_arr([path_excess_arr], float(multiple_dict["trial_sharpe_variance"]),
                                                     int(multiple_dict["design_count"]))[0])
    assert abs(recomputed_float - float(multiple_dict["deflated_sharpe_probability"])) <= 1e-9, (recomputed_float, multiple_dict)
    passed("tail-check script rebuilds a finished run's prior-only path from its pruned folder (same return) and "
           "reproduces its registered random-timing draws; the deflated-Sharpe script recomputes the run's DSR exactly")


# FUNCTION: THE HELPER HASH: WHICH FILES, WHAT CHANGES IT, AND THE RERUN RULE (R3, 2026-10-29)
def test_helper_hash():
    """
    Returns:
        None
    """
    # A SMALL WORKSPACE: ONE PROTECTED MODULE, THREE UNPROTECTED HELPERS (ONE REACHED BY A RELATIVE IMPORT), ONE UNUSED
    root_str = tempfile.mkdtemp(prefix="so_helper_ws_", dir=TEMP_ROOT_STR)

    def write(rel_str_in, text_bytes_in):
        path_str = os.path.join(root_str, *rel_str_in.split("/"))
        os.makedirs(os.path.dirname(path_str), exist_ok=True)
        with open(path_str, "wb") as file_obj:
            file_obj.write(text_bytes_in)
    write("protected_paths.txt", b"so/__init__.py\nso/features/__init__.py\nso/runner/**\n")
    write("so/__init__.py", b"")
    write("so/features/__init__.py", b"")
    write("so/runner/core_rule.py", b"R = 1\n")
    write("so/features/h1.py", b"from so.features.h2 import f\nfrom so.runner.core_rule import R\n")
    write("so/features/h2.py", b"from . import h3\ndef f():\n    return 1\n")
    write("so/features/h3.py", b"Z = 3\n")
    write("so/features/unused.py", b"U = 0\n")
    write("experiments/expH/design.py", b"from so.features.h1 import f\nfrom so.features import h1\n")
    design_str = os.path.join(root_str, "experiments", "expH", "design.py")
    assert get_design_helper_file_list(design_str, root_str) == ["so/features/h1.py", "so/features/h2.py", "so/features/h3.py"]
    base_dict = get_design_helper_dict(design_str, root_str)
    # CRLF AND AN UNUSED OR PROTECTED FILE DO NOT CHANGE IT; A USED HELPER DOES
    write("so/features/h3.py", b"Z = 3\r\n")
    write("so/features/unused.py", b"U = 1\n")
    write("so/runner/core_rule.py", b"R = 2\n")
    assert get_design_helper_dict(design_str, root_str)["helper_hash"] == base_dict["helper_hash"]
    write("so/features/h3.py", b"Z = 4\n")
    changed_str = get_design_helper_dict(design_str, root_str)["helper_hash"]
    assert changed_str != base_dict["helper_hash"]
    # THE RERUN RULE: LOGGED WITHOUT A HELPER HASH (BEFORE R3) -> ANY; LOGGED WITH ONE -> ONLY THAT ONE
    log_path_str = os.path.join(TEMP_ROOT_STR, "helper_trial_log.csv")
    module = types.SimpleNamespace(EXPERIMENT_NAME="expH_test", PROTOCOL_VERSION="1.0")
    row_dict = {"experiment": "expH_test", "protocol_version": "1.0", "stage": "validation", "metric_json": "{}",
                "setting_json": json.dumps({"candidate": "A", "design_folder_hash": "f1"})}
    pd.DataFrame([row_dict]).to_csv(log_path_str, index=False)
    git_func = lambda arg_list_in: "anything\n"
    assert check_preregistration_dict(module, root_str, "f1", log_path_str, git_func, helper_hash_str_in=changed_str)["status_str"] == "rerun"
    pd.DataFrame([row_dict, {**row_dict, "setting_json": json.dumps({"candidate": "A", "design_folder_hash": "f1",
                                                                     "helper_hash": base_dict["helper_hash"]})}]).to_csv(log_path_str, index=False)
    assert check_preregistration_dict(module, root_str, "f1", log_path_str, git_func,
                                      helper_hash_str_in=base_dict["helper_hash"])["helper_hash"] == base_dict["helper_hash"]
    try:
        check_preregistration_dict(module, root_str, "f1", log_path_str, git_func, helper_hash_str_in=changed_str)
        raise AssertionError("a changed helper was accepted under a logged version")
    except ValueError as error:
        assert "shared helper code" in str(error)
    # THE HELPER HASH IS BOOKKEEPING IN THE DESIGN KEY (A RERUN IS NOT A NEW DESIGN)
    from so.core.multiple_testing import get_design_key_str
    assert get_design_key_str("expH_test", {"candidate": "A", "helper_hash": "x"}) == get_design_key_str("expH_test", {"candidate": "A"})
    passed("helper hash: unprotected so/ files a design imports (transitively, relative imports too), CRLF-neutral, "
           "changes with a used helper; a logged version reruns only with its helper hash; not part of the design key")


# FUNCTION: NEW VERSIONS ARE NEW DESIGNS IN N (REVIEW F1, F4; DECIDED 2026-11-14)
def test_new_versions_are_counted():
    """
    An amended version that reuses a candidate name is refused; with new names it runs and N grows. The version limit
    counts per family, so a renamed copy (expQQ_amend_v2) cannot add a fourth version. A folder under experiments/ must
    carry EXPERIMENT_NAME. The Family line is linted; an amendment needs exactly one change-log label.

    Returns:
        None
    """
    # A LOGGED 1.0 WITH CANDIDATES A AND B
    from so.core.multiple_testing import get_tried_design_count_dict
    from so.runner.preregistration import get_family_line_dict, get_amendment_label_str
    folder_str = tempfile.mkdtemp(prefix="so_prereg_amend_", dir=TEMP_ROOT_STR)
    log_path_str = os.path.join(TEMP_ROOT_STR, "amend_trial_log.csv")
    registered_str = os.path.join(TEMP_ROOT_STR, "amend_registered_versions.csv")
    ledger_str = os.path.join(TEMP_ROOT_STR, "amend_no_ledger.csv")
    base_row = {"experiment": "expQQ_amend", "protocol_version": "1.0", "stage": "validation", "metric_json": "{}"}
    pd.DataFrame([{**base_row, "setting_json": json.dumps({"candidate": name_str, "design_folder_hash": "q1", "run_id": "r1"})}
                  for name_str in ("A", "B")]).to_csv(log_path_str, index=False)
    with open(os.path.join(folder_str, "PROTOCOL.md"), "w", encoding="utf-8") as file_obj:
        file_obj.write(get_full_protocol_str())
    git_func = lambda arg_list_in: "preregister expQQ v1.1\n"
    call_dict = {"git_func_in": git_func, "registered_path_str_in": registered_str}

    def refusal_str(call_in):
        try:
            call_in()
        except ValueError as error:
            return str(error)
        return ""
    # A REUSED NAME IS REFUSED; NEW NAMES PASS, WITH THE LABEL AND THE FAMILY LINE IN THE RESULT
    module_reuse = types.SimpleNamespace(EXPERIMENT_NAME="expQQ_amend", PROTOCOL_VERSION="1.1", CANDIDATE_LIST=["A", "C"])
    assert "already logged" in refusal_str(lambda: check_preregistration_dict(module_reuse, folder_str, "q2", log_path_str, **call_dict))
    module_new = types.SimpleNamespace(EXPERIMENT_NAME="expQQ_amend", PROTOCOL_VERSION="1.1", CANDIDATE_LIST=["v1.1|A", "v1.1|B"])
    first_dict = check_preregistration_dict(module_new, folder_str, "q2", log_path_str, **call_dict)
    assert first_dict["status_str"] == "first_run" and first_dict["amendment_label_str"] == "bug-fix"
    assert first_dict["family_dict"] == {"family": "C", "idea": "C1", "variant": 1, "line": "Family: C, idea C1, variant 1 of 5"}
    # N GROWS ONCE THE AMENDED VERSION'S ROWS ARE LOGGED
    before_int = get_tried_design_count_dict(log_path_str, [ledger_str])["total_count"]
    amended_pdf = pd.concat([pd.read_csv(log_path_str, dtype=str, keep_default_na=False), pd.DataFrame(
        [{**base_row, "protocol_version": "1.1", "setting_json": json.dumps({"candidate": name_str, "design_folder_hash": "q2", "run_id": "r2"})}
         for name_str in ("v1.1|A", "v1.1|B")])])
    amended_pdf.to_csv(log_path_str, index=False)
    assert (before_int, get_tried_design_count_dict(log_path_str, [ledger_str])["total_count"]) == (2, 4)
    # AN AMENDMENT WITHOUT A LABEL, OR WITH BOTH LABELS, IS REFUSED
    module_12 = types.SimpleNamespace(EXPERIMENT_NAME="expQQ_amend", PROTOCOL_VERSION="1.2", CANDIDATE_LIST=["v1.2|A"])
    unlabelled_str = get_full_protocol_str().replace("| 1.2 | 2026-11-16 | data-dependent: a wider buffer after the 1.1 result |\n", "")
    with open(os.path.join(folder_str, "PROTOCOL.md"), "w", encoding="utf-8") as file_obj:
        file_obj.write(unlabelled_str)
    assert "label" in refusal_str(lambda: check_preregistration_dict(module_12, folder_str, "q3", log_path_str, **call_dict))
    assert get_amendment_label_str(unlabelled_str + "| 1.2 | x | bug-fix, then data-dependent |\n", "1.2") is None
    assert get_amendment_label_str(get_full_protocol_str(), "1.2") == "data-dependent"
    # THE LIMIT COUNTS PER FAMILY: WITH 1.0, 1.1 AND 1.2 LOGGED, A RENAMED COPY CANNOT ADD A FOURTH
    with open(os.path.join(folder_str, "PROTOCOL.md"), "w", encoding="utf-8") as file_obj:
        file_obj.write(get_full_protocol_str())
    pd.concat([amended_pdf, pd.DataFrame([{**base_row, "protocol_version": "1.2",
                                            "setting_json": json.dumps({"candidate": "v1.2|A", "design_folder_hash": "q3"})}])]).to_csv(log_path_str, index=False)
    module_copy = types.SimpleNamespace(EXPERIMENT_NAME="expQQ_amend_v2", PROTOCOL_VERSION="1.0", CANDIDATE_LIST=["v2|A"])
    assert "per family" in refusal_str(lambda: check_preregistration_dict(module_copy, folder_str, "q4", log_path_str, **call_dict))
    # THE FAMILY LINE: MISSING OR MALFORMED (VARIANT 6 OF 5) IS A MISSING SECTION
    assert get_family_line_dict("Family: c, idea C2, variant 5 of 5.")["family"] == "C"
    for bad_str in ["", "Family: C, idea C1, variant 6 of 5", "Family: C1, variant 1 of 5", "Family: none"]:
        assert any(item_str.startswith("Family:") for item_str in get_protocol_missing_list(get_full_protocol_str().replace(
            "Family: C, idea C1, variant 1 of 5", bad_str))), bad_str
    # A FOLDER UNDER experiments/ CARRIES ITS EXPERIMENT'S NAME (A TEMPORARY WORKSPACE)
    workspace_str = tempfile.mkdtemp(prefix="so_prereg_workspace_", dir=TEMP_ROOT_STR)
    wrong_folder_str = os.path.join(workspace_str, "experiments", "expRR_other")
    os.makedirs(wrong_folder_str)
    with open(os.path.join(wrong_folder_str, "PROTOCOL.md"), "w", encoding="utf-8") as file_obj:
        file_obj.write(get_full_protocol_str())
    module_rr = types.SimpleNamespace(EXPERIMENT_NAME="expRR_name", PROTOCOL_VERSION="1.0", CANDIDATE_LIST=["a"])
    real_workspace_str = paths.WORKSPACE_PATH_STR
    paths.WORKSPACE_PATH_STR = workspace_str
    try:
        assert "does not match EXPERIMENT_NAME" in refusal_str(lambda: check_preregistration_dict(
            module_rr, wrong_folder_str, "r1", log_path_str, **call_dict))
        module_ok = types.SimpleNamespace(EXPERIMENT_NAME="expRR_other", PROTOCOL_VERSION="1.0", CANDIDATE_LIST=["a"])
        ok_dict = check_preregistration_dict(module_ok, wrong_folder_str, "r1", log_path_str, **call_dict)
        assert ok_dict["status_str"] == "first_run" and ok_dict["amendment_label_str"] is None
    finally:
        paths.WORKSPACE_PATH_STR = real_workspace_str
    passed("new versions are new designs: a reused candidate name refused, new names counted in N, the version limit per "
           "family (a renamed copy refused), the folder carries EXPERIMENT_NAME, the Family line linted, one amendment label")


# FUNCTION: THE RESET MARKER (REVIEW F3; DECIDED 2026-11-14)
def test_reset_marker():
    """
    No marker passes. A marker matching the judge's two records passes (CRLF-neutral). A changed record, an
    unreadable marker or another schema stops the run.

    Returns:
        None
    """
    # A TEMPORARY WORKSPACE WITH THE TWO RECORDS
    from so.runner.preregistration import write_reset_marker_dict, check_reset_marker_dict, get_reset_record_path_dict
    workspace_str = tempfile.mkdtemp(prefix="so_marker_workspace_", dir=TEMP_ROOT_STR)
    os.makedirs(os.path.join(workspace_str, "records", "legacy"))
    file_dict = get_reset_record_path_dict(workspace_str)
    for path_str in file_dict.values():
        with open(path_str, "wb") as file_obj:
            file_obj.write(b"source,experiment\nx,exp\n")
    marker_str = os.path.join(TEMP_ROOT_STR, "judge_test", "reset_marker.json")
    assert check_reset_marker_dict(marker_str, workspace_str)["status_str"] == "no_marker"
    write_reset_marker_dict("reset_test", marker_str, file_dict)
    assert check_reset_marker_dict(marker_str, workspace_str)["status_str"] == "match"
    with open(list(file_dict.values())[0], "wb") as file_obj:      # A WINDOWS CHECKOUT OF THE SAME FILE
        file_obj.write(b"source,experiment\r\nx,exp\r\n")
    assert check_reset_marker_dict(marker_str, workspace_str)["status_str"] == "match"
    with open(list(file_dict.values())[1], "ab") as file_obj:      # THE DEPLOYED JUDGE LACKS A ROW THE RESET WROTE
        file_obj.write(b"y,exp2\n")

    def refused_bool(call_in):
        try:
            call_in()
        except ValueError:
            return True
        return False
    assert refused_bool(lambda: check_reset_marker_dict(marker_str, workspace_str))
    with open(marker_str, "w", encoding="utf-8") as file_obj:
        file_obj.write("{not json")
    assert refused_bool(lambda: check_reset_marker_dict(marker_str, workspace_str))
    with open(marker_str, "w", encoding="utf-8") as file_obj:
        json.dump({"schema": "other", "file_sha256_dict": {}}, file_obj)
    assert refused_bool(lambda: check_reset_marker_dict(marker_str, workspace_str))
    passed("reset marker: no marker passes, a matching judge passes (CRLF-neutral), a changed record, an unreadable "
           "marker or another schema stops the run")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY DATA ROOT
    try:
        test_preregistration_guard()
        test_registered_versions_survive_reset()
        test_new_versions_are_counted()
        test_reset_marker()
        test_helper_hash()
        test_cost_sensitivity_in_report()
        print("\nAll runner protocol tests passed ✅")
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
