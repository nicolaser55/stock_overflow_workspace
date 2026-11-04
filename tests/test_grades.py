"""
Workspace Tests: results visible only as grades (roadmap R4, 2026-11-03)

Run from the workspace root:   python tests/test_grades.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required; synthetic data only.)

The grade of every combination of verdict parts; the queue's grade of runs without a verdict; the vocabulary carries no
digit; the error scrubber on realistic tracebacks; state.json trimmed (old entries cut, the old file at the zone root
removed); the grade and technical-status files of a queue run end to end, every value on an allow-list; a retry from the
status file; the results-log switch both ways; the reset of the development records (the count of designs survives).
"""

import datetime
import itertools
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# NO REAL HOLDOUT SETTING REACHES THIS SUITE
for _name_str in ["SO_QUARANTINE_PATH", "SO_HOLDOUT_PATH", "SO_HOLDOUT_EVALUATION_TOKEN"]:
    os.environ.pop(_name_str, None)
# A TEMPORARY DATA ROOT WHEN THE CALLER DID NOT SET ONE
if not os.environ.get("SO_DATA_PATH", "").strip():
    os.environ["SO_DATA_PATH"] = tempfile.mkdtemp(prefix="so_grades_")
# ADD THE WORKSPACE ROOT, THE TESTS AND THE SCRIPTS FOLDERS TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "scripts"))
import run_queue
from so.runner import grade as grade_module
from so.runner.grade import (get_run_grade_dict, get_queue_grade_dict, REASON_DICT, GRADE_LIST, GRADE_PASS_STR,
                             GRADE_NOT_BETTER_STR, GRADE_COSTS_STR, GRADE_INCONSISTENT_STR, GRADE_LUCK_STR,
                             GRADE_TECHNICAL_STR)

# FORCE UTF-8 SO THE PASS MARK PRINTS ON A WINDOWS CONSOLE
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DESIGN_STR = "experiments/exp13_e1m1_robustness"
FAKE_COMMIT_STR = "c0ffee" + "0" * 34
FAKE_JUDGE_STR = "babe00" + "0" * 34
FAKE_RUN_COMMIT_STR = "feed00" + "0" * 34
ISO_TS_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")


# FUNCTION: A VERDICT WITH CHOSEN PARTS
def get_verdict_dict(look_str_in, return_bool_in, consistency_bool_in, baseline_bool_in, multiple_bool_in,
                     enough_decisive_bool_in=True, constant_bool_in=True, dsr_bool_in=None):
    """
    Returns:
        dict: The part dicts get_run_grade_dict reads, and the failed list the verdict would hold
    """
    # THE SAME FAILED-LIST ORDER AS so.runner.verdict
    failed_list = [name_str for name_str, ok_bool in [("return", return_bool_in), ("consistency", consistency_bool_in),
                                                       ("baselines", baseline_bool_in), ("look-ahead", look_str_in == "pass"),
                                                       ("multiple-testing", multiple_bool_in)] if not ok_bool]
    return {"look_ahead_dict": {"status_str": look_str_in, "pass_bool": look_str_in == "pass"},
            "return_dict": {"pass_bool": return_bool_in, "reason_str": "x"},
            "consistency_dict": {"pass_bool": consistency_bool_in, "enough_decisive_bool": enough_decisive_bool_in},
            "baseline_dict": {"pass_bool": baseline_bool_in, "constant_pass_bool": constant_bool_in if not baseline_bool_in else True},
            "multiple_testing_dict": {"pass_bool": multiple_bool_in,
                                      "dsr_pass_bool": multiple_bool_in if dsr_bool_in is None else dsr_bool_in,
                                      "random_pass_bool": True if multiple_bool_in or dsr_bool_in is False else False},
            "failed_list": failed_list}


# FUNCTION: THE EXPECTED GRADE (AN INDEPENDENT STATEMENT OF THE AGREED ORDER)
def get_expected_grade_str(look_str_in, return_bool_in, zero_value_in, consistency_bool_in, baseline_bool_in, multiple_bool_in):
    """
    Returns:
        str: The grade the agreed table gives (zero_value_in: None = no replay, True / False = the zero-slippage check)
    """
    # TECHNICAL, RETURN, COSTS, CONSISTENCY, LUCK, PASS
    if look_str_in != "pass":
        return GRADE_TECHNICAL_STR
    if not return_bool_in:
        return GRADE_COSTS_STR if zero_value_in is True else GRADE_NOT_BETTER_STR
    if not consistency_bool_in:
        return GRADE_INCONSISTENT_STR
    if not (baseline_bool_in and multiple_bool_in):
        return GRADE_LUCK_STR
    return GRADE_PASS_STR


# FUNCTION: EVERY COMBINATION OF VERDICT PARTS
def test_grade_every_combination():
    """
    3 look-ahead statuses x return x zero-slippage (none, fail, pass) x consistency x baselines x multiple testing:
    the grade follows the agreed order, the reason belongs to the grade, and a pass is audit pending.

    Returns:
        None
    """
    # 3 * 2 * 3 * 2 * 2 * 2 = 144 CASES
    case_count = 0
    for look_str, return_bool, zero_value, consistency_bool, baseline_bool, multiple_bool in itertools.product(
            ["pass", "fail", "pending"], [True, False], [None, False, True], [True, False], [True, False], [True, False]):
        verdict_dict = get_verdict_dict(look_str, return_bool, consistency_bool, baseline_bool, multiple_bool)
        cost_list = None if zero_value is None else [
            {"slippage_per_share": 0.01, "return_pass_bool": return_bool, "return_reason_str": "x"},
            {"slippage_per_share": 0.0, "return_pass_bool": zero_value, "return_reason_str": "below_comparable"}]
        grade_dict = get_run_grade_dict(verdict_dict, cost_list)
        expected_str = get_expected_grade_str(look_str, return_bool, zero_value, consistency_bool, baseline_bool, multiple_bool)
        assert grade_dict["grade_str"] == expected_str, (look_str, return_bool, zero_value, consistency_bool, baseline_bool, multiple_bool, grade_dict)
        assert REASON_DICT[grade_dict["reason_code_str"]][0] == grade_dict["grade_str"]
        assert grade_dict["audit_str"] == ("pending" if expected_str == GRADE_PASS_STR else "not applicable")
        case_count += 1
    # THE REASONS INSIDE A GRADE
    assert get_run_grade_dict(get_verdict_dict("fail", False, False, False, False))["reason_code_str"] == "look_ahead_failed"
    assert get_run_grade_dict(get_verdict_dict("pending", True, True, True, True))["reason_code_str"] == "look_ahead_not_run"
    assert get_run_grade_dict(get_verdict_dict("pass", False, True, True, True))["reason_code_str"] == "return_below_buy_hold_no_cost_check"
    comparable_list = [{"slippage_per_share": 0.0, "return_pass_bool": False, "return_reason_str": "comparable_without_secondary"}]
    assert get_run_grade_dict(get_verdict_dict("pass", False, True, True, True), comparable_list)["reason_code_str"] == "return_comparable_without_secondary"
    old_row_list = [{"slippage_per_share": 0.0, "strategy_total_return": 0.5, "buy_hold_total_return": 0.1}]
    assert get_run_grade_dict(get_verdict_dict("pass", False, True, True, True), old_row_list)["reason_code_str"] == "return_below_buy_hold_no_cost_check"
    assert get_run_grade_dict(get_verdict_dict("pass", True, False, True, True, enough_decisive_bool_in=False))["reason_code_str"] == "too_few_decisive_windows"
    assert get_run_grade_dict(get_verdict_dict("pass", True, False, True, True))["reason_code_str"] == "behind_in_too_many_windows"
    assert get_run_grade_dict(get_verdict_dict("pass", True, True, False, True, constant_bool_in=False))["reason_code_str"] == "not_above_constant_exposure"
    assert get_run_grade_dict(get_verdict_dict("pass", True, True, False, True))["reason_code_str"] == "not_above_random_timing"
    assert get_run_grade_dict(get_verdict_dict("pass", True, True, True, False, dsr_bool_in=False))["reason_code_str"] == "deflated_sharpe_below_bar"
    assert get_run_grade_dict(get_verdict_dict("pass", True, True, True, False, dsr_bool_in=True))["reason_code_str"] == "random_timing_count_above_bar"
    # A FAILED LIST THAT DISAGREES WITH THE PARTS IS NEVER A PASS
    disagree_dict = {**get_verdict_dict("pass", True, True, True, True), "failed_list": ["return"]}
    assert get_run_grade_dict(disagree_dict)["grade_str"] == GRADE_TECHNICAL_STR
    passed(f"grade of every combination of verdict parts ({case_count} cases; reasons inside each grade; a disagreeing failed list never passes)")


# FUNCTION: THE QUEUE'S GRADE AND THE VOCABULARY
def test_queue_grade_and_vocabulary():
    """
    Runs without a verdict are technical problems; a finished run keeps the code its manifest recorded only when that
    code matches its grade (and a pass only with an email-worthy verdict). No grade, code or sentence holds a digit.

    Returns:
        None
    """
    # WITHOUT A VERDICT
    assert get_queue_grade_dict("failed")["reason_code_str"] == "crashed"
    assert get_queue_grade_dict("timeout")["reason_code_str"] == "timeout"
    assert get_queue_grade_dict("done", {}, judge_problem_str_in="judge changed")["reason_code_str"] == "judge_changed"
    assert get_queue_grade_dict("failed", gave_up_bool_in=True)["reason_code_str"] == "gave_up"
    assert get_queue_grade_dict("done", {})["reason_code_str"] == "no_verdict"
    # A FINISHED RUN
    good_dict = {"grade": GRADE_INCONSISTENT_STR, "grade_reason_code": "behind_in_too_many_windows", "email_worthy": False}
    assert get_queue_grade_dict("done", good_dict)["grade_str"] == GRADE_INCONSISTENT_STR
    assert get_queue_grade_dict("done", {**good_dict, "grade": GRADE_PASS_STR})["reason_code_str"] == "no_verdict"
    assert get_queue_grade_dict("done", {**good_dict, "grade_reason_code": "made_up"})["reason_code_str"] == "no_verdict"
    pass_dict = {"grade": GRADE_PASS_STR, "grade_reason_code": "all_checks_passed", "email_worthy": True}
    assert get_queue_grade_dict("done", pass_dict)["audit_str"] == "pending"
    assert get_queue_grade_dict("done", {**pass_dict, "email_worthy": False})["reason_code_str"] == "no_verdict"
    # THE VOCABULARY: SIX GRADES, NO DIGITS ANYWHERE
    assert len(GRADE_LIST) == 6 and len(set(GRADE_LIST)) == 6
    for code_str, (grade_str, reason_str) in REASON_DICT.items():
        assert grade_str in GRADE_LIST and not re.search(r"\d", code_str + grade_str + reason_str), code_str
    assert all(grade_str in {value[0] for value in REASON_DICT.values()} for grade_str in GRADE_LIST)
    try:
        grade_module.get_grade_from_reason_dict("made_up")
        raise AssertionError("an unknown reason code was accepted")
    except ValueError:
        pass
    passed("queue grade (technical without a verdict; a recorded code must match its grade; a pass needs an email-worthy verdict); "
           "six grades, no digit in any grade, code or reason")


# FUNCTION: THE ERROR SCRUBBER ON REALISTIC TRACEBACKS
def test_error_scrubber():
    """
    Numbers in messages (returns, prices, DataFrame cells, dates, counts) become "#"; identifiers, git hashes,
    experiment names and code locations stay; source lines and printed values are dropped.

    Returns:
        None
    """
    # A DESIGN CRASH THAT PRINTS VALUES
    run_id_str = "exp04_trend_exit_20261103120000123456"
    log_str = (
        "run commit feed000000000000000000000000000000000000\n"
        "Traceback (most recent call last):\n"
        f'  File "D:\\stock_overflow\\runner_workspace\\.worktrees\\{run_id_str}\\scripts\\run_development.py", line 170, in <module>\n'
        "    result_dict = run_development_dict(design_module, ohlcv_array_dict)\n"
        f'  File "D:\\stock_overflow\\runner_workspace\\.worktrees\\{run_id_str}\\experiments\\exp04_trend_exit\\design.py", line 88, in decide\n'
        "    assert ret > 0.1, f\"{ret:.2%}\"\n"
        "           ^^^^^^^^^\n"
        "          close   volume\n"
        "0  431.17  1234567\n"
        "AssertionError: return +12.34% vs buy-and-hold 199.04% on 2015-03-02 (2,000 rows; 1.5e-03; -0.25)\n")
    summary_dict = run_queue.get_error_summary_dict(log_str.splitlines(), [run_id_str])
    assert summary_dict["error_type"] == "AssertionError"
    assert not re.search(r"\d", summary_dict["error_text"]), summary_dict
    assert summary_dict["frame_list"] == ["scripts/run_development.py:170 in <module>", "experiments/exp04_trend_exit/design.py:88 in decide"], summary_dict
    # IDENTIFIERS STAY; EVERY OTHER DIGIT GOES
    text_str = run_queue.get_scrubbed_text_str(
        f"commit {FAKE_COMMIT_STR} of {DESIGN_STR} for run {run_id_str}: value 431.17 and 12345678", [run_id_str, FAKE_COMMIT_STR])
    assert FAKE_COMMIT_STR in text_str and DESIGN_STR in text_str and run_id_str in text_str and "431" not in text_str
    assert "12345678" not in text_str and text_str.endswith("value #.# and #")
    assert run_queue.get_scrubbed_text_str("short hash 4a43f0e and 1234567 plain") == "short hash 4a43f0e and # plain"
    # A LOG WITHOUT A TRACEBACK: THE LAST LINE, SCRUBBED
    plain_dict = run_queue.get_error_summary_dict(["loading", "killed after 86400 s"])
    assert plain_dict["error_type"] is None and plain_dict["error_text"] == "killed after # s"
    passed("error scrubber (values in messages scrubbed, identifiers and code locations kept, source lines and printed frames dropped)")


# FUNCTION: A FRESH QUEUE UNDER THE DATA ROOT
def get_fresh_path_dict():
    """
    Returns:
        dict: Queue paths of a new zone, folders made
    """
    # ONE ZONE PER TEST
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    return path_dict


# FUNCTION: state.json TRIMMED, THE OLD FILE REMOVED
def test_state_trimmed():
    """
    Returns:
        None
    """
    # AN OLD state.json AT THE ZONE ROOT AND A visible/state.json WITH FULL ENTRIES (AS EARLIER VERSIONS WROTE THEM)
    path_dict = get_fresh_path_dict()
    full_entry_dict = {"job_id": "j1", "run_id": "r1", "status": "done", "results_row": "| +12.34% vs +5.00% |",
                       "verdict": {"failed_list": ["return"]}, "log_tail": ["ret 0.1234"], "note": "n"}
    Path(path_dict["old_state"]).write_text(json.dumps({"recent": [full_entry_dict]}), encoding="utf-8")
    os.makedirs(os.path.dirname(path_dict["state"]), exist_ok=True)
    Path(path_dict["state"]).write_text(json.dumps({"recent": [full_entry_dict, "junk"]}), encoding="utf-8")
    running_dict = {"job_id": "j2", "design": DESIGN_STR, "commit": FAKE_COMMIT_STR, "run_id": "r2", "attempt": 1,
                    "note": "secret note", "judge_commit": FAKE_JUDGE_STR, "started_ts": "2026-11-03T10:00:00"}
    state_dict = run_queue.write_state_dict(path_dict, running_dict, {**full_entry_dict, "job_id": "j3", "status": "failed"})
    assert not os.path.exists(path_dict["old_state"])
    assert state_dict["recent"] == [{"job_id": "j3", "run_id": "r1", "status": "crashed"}, {"job_id": "j1", "run_id": "r1", "status": "ran"}]
    assert set(state_dict["running"]) == set(run_queue.STATE_RUNNING_KEY_LIST) and "note" not in state_dict["running"]
    text_str = Path(path_dict["state"]).read_text(encoding="utf-8")
    assert "12.34" not in text_str and "results_row" not in text_str and "log_tail" not in text_str and "verdict" not in text_str
    passed("state.json trimmed (job id, run id, status; old full entries cut, the zone-root state.json of earlier versions removed)")


# FUNCTION: A FAKE RUN THAT WRITES A MANIFEST WITH A GRADE
def get_graded_run_func(path_dict_in, verdict_dict_in, cost_list_in=None, return_code_in=0, log_line_list_in=None):
    """
    Returns:
        callable: (job, run id, log path) -> the run function's result
    """
    # THE MANIFEST AS so.runner.run WRITES IT SINCE R4
    def run_func(job_dict_in, run_id_str_in, log_path_str_in):
        line_list = list(log_line_list_in or ["loaded", f"results_row | {run_id_str_in} | +12.34% vs +5.00% |"])
        Path(log_path_str_in).write_text("\n".join(line_list), encoding="utf-8")
        if return_code_in == 0:
            grade_dict = get_run_grade_dict(verdict_dict_in, cost_list_in)
            run_folder = Path(path_dict_in["runs"]) / run_id_str_in
            run_folder.mkdir(parents=True, exist_ok=True)
            (run_folder / "manifest.json").write_text(json.dumps({"status": "finished", "verdict": {
                "email_worthy": not verdict_dict_in["failed_list"], "label": "x", "failed_list": verdict_dict_in["failed_list"],
                "look_ahead": verdict_dict_in["look_ahead_dict"]["status_str"], "grade": grade_dict["grade_str"],
                "grade_reason_code": grade_dict["reason_code_str"]}}), encoding="utf-8")
        return {"return_code": return_code_in, "log_line_list": line_list}
    return run_func


# FUNCTION: EVERY VALUE OF A GRADE OR STATUS FILE IS ON THE ALLOW-LIST
def check_allowed_file(file_path_str_in, kind_str_in):
    """
    Args:
        file_path_str_in (str): visible/grades/<run_id>.json or visible/status/<job_id>.json
        kind_str_in (str): grade or status

    Returns:
        dict: The parsed file
    """
    # A VALIDATOR PER KEY; AN UNKNOWN KEY FAILS
    payload_dict = json.loads(Path(file_path_str_in).read_text(encoding="utf-8"))
    identifier_dict = {"run_id": run_queue.RUN_ID_PATTERN, "job_id": run_queue.JOB_ID_PATTERN, "design": run_queue.DESIGN_PATTERN,
                       "design_commit": run_queue.COMMIT_PATTERN, "commit": run_queue.COMMIT_PATTERN,
                       "judge_commit": run_queue.COMMIT_PATTERN, "finished_ts": ISO_TS_PATTERN}
    sentence_set = {value[1] for value in REASON_DICT.values()}
    for key_str, value in payload_dict.items():
        if key_str in identifier_dict:
            assert value is None or identifier_dict[key_str].match(str(value)), (key_str, value)
        elif key_str in ("attempt", "n_jobs"):
            assert value is None or (isinstance(value, int) and not isinstance(value, bool)), (key_str, value)
        elif kind_str_in == "grade" and key_str == "grade":
            assert value in GRADE_LIST
        elif kind_str_in == "grade" and key_str == "reason_code":
            assert value in REASON_DICT
        elif kind_str_in == "grade" and key_str == "reason":
            assert value in sentence_set
        elif kind_str_in == "grade" and key_str == "audit":
            assert value in ("pending", "not applicable")
        elif kind_str_in == "status" and key_str == "status":
            assert value in ("ran", "crashed", "timeout", "rejected")
        elif kind_str_in == "status" and key_str == "look_ahead":
            assert value in (None, "pass", "fail", "pending")
        elif kind_str_in == "status" and key_str in ("look_ahead_failed", "retry_possible"):
            assert isinstance(value, bool)
        elif kind_str_in == "status" and key_str == "note":
            assert value is None or isinstance(value, str)      # THE JOB'S OWN NOTE, WRITTEN BY WHOEVER QUEUED IT
        elif kind_str_in == "status" and key_str in ("reason", "error_type", "error_text"):
            stripped_str = str(value or "")
            for identifier_str in [payload_dict.get(name_str) for name_str in ("job_id", "run_id", "design", "commit", "judge_commit")] + [FAKE_RUN_COMMIT_STR]:
                if identifier_str:
                    stripped_str = stripped_str.replace(str(identifier_str), "")
            stripped_str = re.sub(r"\bexp[0-9]{2}_[A-Za-z0-9_]+", "", stripped_str)
            assert not re.search(r"\d", stripped_str), (key_str, value)
        elif kind_str_in == "status" and key_str == "error_frame_list":
            assert all(re.match(r"^[A-Za-z0-9_./<>#-]+:\d+ in [A-Za-z0-9_<>.#]+$", frame_str) for frame_str in value), value
        else:
            raise AssertionError(f"unexpected key {key_str} in {file_path_str_in}")
    return payload_dict


# FUNCTION: THE AGENT VIEW OF A QUEUE RUN, END TO END
def test_agent_view_end_to_end():
    """
    A finished run, a crashed run and a rejected job through run_queue_list on the fake runner: each finished job gets
    a grade file (planner) and a status file (coder); a rejected job only a status file; the coder's status of a run
    that ran says "ran" and its look-ahead status, nothing about the grade; a retry reads the status file.

    Returns:
        None
    """
    # TWO JOBS: AN INCONSISTENT RUN, THEN A RUN WITH A LOOK-AHEAD FAILURE
    path_dict = get_fresh_path_dict()
    git_func = lambda arg_list_in, **kwarg_dict_in: FAKE_COMMIT_STR + "\n" if arg_list_in[0] == "rev-parse" else ""
    first_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "first", git_func_in=git_func)
    second_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "second", git_func_in=git_func)
    verdict_by_note_dict = {"first": get_verdict_dict("pass", True, False, False, False),
                            "second": get_verdict_dict("fail", False, False, False, False)}
    sent_list = []

    def send_func(path_dict_in, run_id_str_in, subject_str_in, body_str_in):
        sent_list.append(body_str_in)
        return {"sent_bool": True, "detail": "fake"}

    def run_func(job_dict_in, run_id_str_in, log_path_str_in):
        return get_graded_run_func(path_dict, verdict_by_note_dict[job_dict_in["note"]])(job_dict_in, run_id_str_in, log_path_str_in)
    common_dict = {"judge_func_in": lambda: FAKE_JUDGE_STR, "git_func_in": lambda *args_in, **kwargs_in: "",
                   "prepare_func_in": lambda job_in: FAKE_RUN_COMMIT_STR}
    result_list = run_queue.run_queue_list(path_dict, run_func, send_func, **common_dict)
    assert [result["status"] for result in result_list] == ["done", "done"]
    grade_list = [check_allowed_file(os.path.join(path_dict["grades"], f"{result['run_id']}.json"), "grade") for result in result_list]
    assert [(row["grade"], row["reason_code"]) for row in grade_list] == [
        (GRADE_INCONSISTENT_STR, "behind_in_too_many_windows"), (GRADE_TECHNICAL_STR, "look_ahead_failed")]
    assert grade_list[0]["job_id"] == first_dict["job_id"] and grade_list[0]["design_commit"] == FAKE_COMMIT_STR
    status_list = [check_allowed_file(os.path.join(path_dict["status"], f"{result['job_id']}.json"), "status") for result in result_list]
    assert [(row["status"], row["look_ahead"], row["look_ahead_failed"]) for row in status_list] == [("ran", "pass", False), ("ran", "fail", True)]
    assert "Grade (what the planner sees) Failed: inconsistent over time" in sent_list[0]
    # A CRASH THAT PRINTS A RETURN: THE STATUS HOLDS THE ERROR WITHOUT THE NUMBER; A RETRY READS THE STATUS
    third_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "third", git_func_in=git_func)
    crash_line_list = ["Traceback (most recent call last):",
                       '  File "C:\\w\\.worktrees\\r\\experiments\\exp13_e1m1_robustness\\design.py", line 12, in decide',
                       "    raise ValueError(f'{ret}')", "ValueError: return was 0.4512 at 2019-01-02"]
    crash_list = run_queue.run_queue_list(path_dict, get_graded_run_func(path_dict, {}, return_code_in=1, log_line_list_in=crash_line_list),
                                          send_func, **common_dict)
    assert crash_list[0]["status"] == "failed"
    crash_status_dict = check_allowed_file(os.path.join(path_dict["status"], f"{third_dict['job_id']}.json"), "status")
    assert crash_status_dict["status"] == "crashed" and crash_status_dict["error_type"] == "ValueError"
    assert crash_status_dict["error_text"] == "return was #.# at #-#-#" and crash_status_dict["retry_possible"]
    assert crash_status_dict["error_frame_list"] == ["experiments/exp13_e1m1_robustness/design.py:12 in decide"]
    crash_grade_dict = check_allowed_file(os.path.join(path_dict["grades"], f"{crash_list[0]['run_id']}.json"), "grade")
    assert (crash_grade_dict["grade"], crash_grade_dict["reason_code"]) == (GRADE_TECHNICAL_STR, "crashed")
    os.remove(os.path.join(path_dict["failed"], f"{third_dict['job_id']}.json"))          # THE AGENT CANNOT READ failed/
    retry_dict = run_queue.add_retry_job_dict(path_dict, third_dict["job_id"])
    assert retry_dict["run_id"] == crash_list[0]["run_id"] and retry_dict["attempt"] == 2 and retry_dict["judge_commit"] == FAKE_JUDGE_STR
    assert retry_dict["design"] == DESIGN_STR and retry_dict["commit"] == FAKE_COMMIT_STR and retry_dict["note"] == "third"
    try:
        run_queue.add_retry_job_dict(path_dict, first_dict["job_id"])            # IT RAN: NOT RETRYABLE
        raise AssertionError("a job that ran was retried")
    except ValueError:
        pass
    os.remove(os.path.join(path_dict["pending"], f"{retry_dict['job_id']}.json"))
    # A REJECTED JOB: A STATUS WITH THE SCRUBBED REASON, NO GRADE
    bad_path_str = os.path.join(path_dict["pending"], "20261103120000000000_abcdef_exp13_e1m1_robustness.json")
    Path(bad_path_str).write_text(json.dumps({"job_id": "20261103120000000000_abcdef_exp13_e1m1_robustness", "design": "so/runner",
                                              "commit": FAKE_COMMIT_STR}), encoding="utf-8")
    grade_count_int = len(os.listdir(path_dict["grades"]))
    assert run_queue.get_next_job_dict(path_dict, lambda *args_in, **kwargs_in: "") is None
    rejected_status_dict = check_allowed_file(os.path.join(path_dict["status"], "20261103120000000000_abcdef_exp13_e1m1_robustness.json"), "status")
    assert rejected_status_dict["status"] == "rejected" and rejected_status_dict["reason"] and not rejected_status_dict["retry_possible"]
    assert len(os.listdir(path_dict["grades"])) == grade_count_int
    # THE STATE THE AGENT READS HOLDS NO RESULT
    state_text_str = Path(path_dict["state"]).read_text(encoding="utf-8")
    assert "12.34" not in state_text_str and "results_row" not in state_text_str and "grade" not in state_text_str
    passed("agent view end to end (grade per run for the planner, technical status per job for the coder, allow-listed values, "
           "look-ahead failure reaches the coder, crash error scrubbed, retry from the status, rejected job: status only)")


# FUNCTION: THE RESULTS-LOG SWITCH, BOTH WAYS
def test_results_log_switch():
    """
    development: rows with returns, as before; agents: identifiers, grade and reason, no numbers, under a graded section
    header added once. The repository's switch is "development" until R6; a missing or unknown value is "agents".

    Returns:
        None
    """
    # IMPORTED HERE: run_development PULLS IN THE RUNNER
    import pandas as pd
    import append_results_log
    path_dict = get_fresh_path_dict()
    run_id_str = "exp13_e1m1_robustness_20261103120000000000"
    run_folder = Path(path_dict["runs"]) / run_id_str
    run_folder.mkdir(parents=True)
    grade_dict = get_run_grade_dict(get_verdict_dict("pass", True, False, True, True))
    (run_folder / "report.json").write_text(json.dumps({
        "experiment_name_str": "exp13_e1m1_robustness", "protocol_version_str": "1.0", "label_str": "not email-worthy",
        "return_dict": {"strategy_total_return": 2.7385, "buy_hold_total_return": 1.9904}, "failed_list": ["consistency"],
        "look_ahead_dict": {"status_str": "pass"}, "grade_dict": grade_dict}), encoding="utf-8")
    pd.DataFrame([{"run_id": run_id_str, "status": "done", "note": "why", "finished_ts": "2026-11-03T12:00:00"}]).to_csv(path_dict["run_index"], index=False)
    log_path = Path(tempfile.mkdtemp(prefix="so_log_")) / "RESULTS_LOG.md"
    log_path.write_text("# Results log\n\n| a |\n|---|\n", encoding="utf-8")
    development_list = append_results_log.get_new_row_list(path_dict, log_path, "development")
    assert len(development_list) == 1 and "+273.85% vs +199.04%" in development_list[0]
    agents_list = append_results_log.get_new_row_list(path_dict, log_path, "agents")
    assert agents_list[1] == append_results_log.GRADED_SECTION_STR and len(agents_list) == 5
    graded_row_str = agents_list[-1]
    assert GRADE_INCONSISTENT_STR in graded_row_str and run_id_str in graded_row_str and "%" not in graded_row_str
    assert not re.search(r"\d", graded_row_str.replace(run_id_str, "").replace("2026-11-03", "").replace("1.0", "").replace("exp13_e1m1_robustness", ""))
    log_path.write_text(log_path.read_text(encoding="utf-8") + "\n".join(agents_list[:-1]) + "\n", encoding="utf-8")
    assert append_results_log.get_new_row_list(path_dict, log_path, "agents") == [graded_row_str]     # THE HEADER ONCE
    # THE SWITCH FILE
    switch_folder = Path(tempfile.mkdtemp(prefix="so_phase_"))
    assert append_results_log.get_agent_phase_str(switch_folder / "missing.txt") == "agents"
    (switch_folder / "a.txt").write_text("# comment\n development \n", encoding="utf-8")
    (switch_folder / "b.txt").write_text("# comment\nmaybe\n", encoding="utf-8")
    assert append_results_log.get_agent_phase_str(switch_folder / "a.txt") == "development"
    assert append_results_log.get_agent_phase_str(switch_folder / "b.txt") == "agents"
    assert append_results_log.get_agent_phase_str() == "development", "the switch is flipped in R6, not before"
    assert not append_results_log.AGENT_PHASE_PATH.name.endswith(".py")
    passed("results-log switch (development: returns as before; agents: grade rows without numbers, header once; off by default)")


# FUNCTION: THE RESET KEEPS THE COUNT AND DISCARDS THE RESULTS
def test_reset_records():
    """
    Refused in the agent phase, with a pending job, or with a backup folder inside the data root; a dry run changes
    nothing; a reset adds the trial log's designs to the ledger, keeps N with the pilot included, moves the results and
    appends one note row to the results log.

    Returns:
        None
    """
    # A ZONE WITH A TRIAL LOG (ONE DESIGN ALREADY IN THE LEDGER, ONE NEW, ONE NOTE), RUNS, AN INDEX
    import pandas as pd
    import reset_records
    from so.core.multiple_testing import get_tried_design_count_dict
    path_dict = get_fresh_path_dict()
    zone_str = os.path.dirname(path_dict["old_state"])
    ledger_str = os.path.join(tempfile.mkdtemp(prefix="so_ledger_"), "pilot_designs.csv")
    pd.DataFrame([{"source": "s", "experiment": "exp02_stop_reentry", "stage": "validation",
                   "setting_json": json.dumps({"candidate": "A"})}]).to_csv(ledger_str, index=False, lineterminator="\n")
    trial_log_str = os.path.join(zone_str, "trial_log.csv")
    pd.DataFrame([{"experiment": "exp02_stop_reentry_v2", "stage": "validation", "setting_json": json.dumps({"candidate": "A", "run_id": "r1"}), "metric_json": "{\"excess_return\": 0.1}"},
                  {"experiment": "exp04_trend_exit", "stage": "validation", "setting_json": json.dumps({"ma": 200, "window": "w"}), "metric_json": "{\"excess_return\": -0.2}"},
                  {"experiment": "exp04_trend_exit", "stage": "note", "setting_json": json.dumps({"x": 1}), "metric_json": "{}"}]).to_csv(trial_log_str, index=False)
    Path(path_dict["run_index"]).write_text("run_id\nr1\n", encoding="utf-8")
    Path(path_dict["runs"], "r1").mkdir()
    Path(path_dict["runs"], "r1", "report.json").write_text("{}", encoding="utf-8")
    log_path = Path(tempfile.mkdtemp(prefix="so_log_")) / "RESULTS_LOG.md"
    log_path.write_text("# Results log\n", encoding="utf-8")
    backup_str = tempfile.mkdtemp(prefix="so_backup_")
    before_int = get_tried_design_count_dict(trial_log_str, [ledger_str])["pilot_included_count"]
    assert before_int == 2
    keyword_dict = {"ledger_path_str_in": ledger_str, "results_log_path_in": log_path}
    # REFUSALS
    assert "agent phase" in reset_records.reset_records_dict(path_dict, backup_str, True, phase_str_in="agents", **keyword_dict)["refused_str"]
    inside_str = os.path.join(os.environ["SO_DATA_PATH"], "inside_backup")
    os.makedirs(inside_str, exist_ok=True)
    assert "outside the data root" in reset_records.reset_records_dict(path_dict, inside_str, True, phase_str_in="development", **keyword_dict)["refused_str"]
    Path(path_dict["pending"], "job.json").write_text("{}", encoding="utf-8")
    assert "pending" in reset_records.reset_records_dict(path_dict, backup_str, True, phase_str_in="development", **keyword_dict)["refused_str"]
    os.remove(os.path.join(path_dict["pending"], "job.json"))
    # A DRY RUN CHANGES NOTHING
    dry_dict = reset_records.reset_records_dict(path_dict, backup_str, False, phase_str_in="development", **keyword_dict)
    assert not dry_dict["refused_str"] and dry_dict["new_ledger_row_count"] == 1 and not dry_dict["done_bool"]
    assert os.path.isfile(trial_log_str) and len(pd.read_csv(ledger_str)) == 1 and os.listdir(backup_str) == []
    # THE RESET
    done_dict = reset_records.reset_records_dict(path_dict, backup_str, True, phase_str_in="development",
                                                 now_in=datetime.datetime(2026, 11, 3, 12, 0, 0), **keyword_dict)
    assert done_dict["done_bool"] and done_dict["pilot_included_after"] == before_int == 2
    ledger_pdf = pd.read_csv(ledger_str, dtype=str, keep_default_na=False)
    assert list(ledger_pdf["source"]) == ["s", "trial_log_reset_20261103"]
    assert json.loads(ledger_pdf["setting_json"].iloc[-1]) == {"ma": 200}        # BOOKKEEPING DROPPED, NO METRIC COLUMN
    assert "metric_json" not in ledger_pdf.columns
    assert not os.path.exists(trial_log_str) and not os.path.exists(path_dict["run_index"]) and not os.path.exists(path_dict["runs"])
    target_str = done_dict["target_str"]
    assert os.path.isfile(os.path.join(target_str, "trial_log.csv")) and os.path.isfile(os.path.join(target_str, "runs", "r1", "report.json"))
    assert get_tried_design_count_dict(trial_log_str, [ledger_str]) == {"current_count": 0, "pilot_count": 2, "total_count": 1,
                                                                         "pilot_included_count": 2}
    assert "| withdrawn |" in log_path.read_text(encoding="utf-8").splitlines()[-1]
    passed("reset of the development records (refused in the agent phase / with pending jobs / backup inside the data root; dry run; "
           "designs kept in the ledger, N with the pilot unchanged, results moved, one note row)")


# RUN THE SUITE
if __name__ == "__main__":
    test_grade_every_combination()
    test_queue_grade_and_vocabulary()
    test_error_scrubber()
    test_state_trimmed()
    test_agent_view_end_to_end()
    test_results_log_switch()
    test_reset_records()
    print("\nAll grade tests passed ✅")
