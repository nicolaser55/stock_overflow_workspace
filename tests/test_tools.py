"""
Workspace Tests: operation tools (run queue, state, email, protected paths, package lock, ledger location)

Run from the workspace root:   python tests/test_tools.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

The queue lives under a temporary data root. Development runs are replaced by a function that writes a manifest;
email goes to a fake SMTP class. Git is replaced by a function that returns fixed output.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# NO REAL HOLDOUT SETTING REACHES THIS SUITE
for _name_str in ["SO_QUARANTINE_PATH", "SO_HOLDOUT_PATH", "SO_HOLDOUT_EVALUATION_TOKEN"]:
    os.environ.pop(_name_str, None)
# A TEMPORARY DATA ROOT WHEN THE CALLER DID NOT SET ONE
if not os.environ.get("SO_DATA_PATH", "").strip():
    os.environ["SO_DATA_PATH"] = tempfile.mkdtemp(prefix="so_tools_")
# ADD THE WORKSPACE ROOT AND THE TESTS FOLDER TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "scripts"))
import run_queue
from check_protected_paths import (get_protected_bool, get_append_only_bool, get_violation_list,
                                           read_protected_dict)
from check_environment import check_environment_list

# FORCE UTF-8 SO THE PASS MARK PRINTS ON A WINDOWS CONSOLE
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
# AN EXPERIMENT FOLDER THAT EXISTS IN THE WORKSPACE
DESIGN_STR = "experiments/exp13_e1m1_robustness"


# FIXED 40-CHARACTER COMMITS FOR THE FAKE GIT (A JOB FILE MUST HOLD A FULL HASH)
FAKE_COMMIT_STR = "c0ffee" + "0" * 34
FAKE_JUDGE_STR = "babe00" + "0" * 34
FAKE_RUN_COMMIT_STR = "feed00" + "0" * 34


# FUNCTION: A FAKE GIT THAT ACCEPTS EVERYTHING (EXISTENCE CHECKS OF THE VALIDATION)
def fake_accepting_git_func(arg_list_in, **kwarg_dict_in):
    """
    Returns:
        str: Empty output (success)
    """
    # NOTHING IS CHECKED
    return ""


# FUNCTION: RUN THE QUEUE WITH THE FAKES THAT KEEP IT OFF GIT
def run_fake_queue_list(path_dict_in, run_func_in, send_func_in, **kwarg_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths
        run_func_in, send_func_in (callable): Fake run and send
        **kwarg_dict_in: Overrides of judge_func_in, git_func_in, prepare_func_in, pid_alive_func_in

    Returns:
        list[dict]: Results
    """
    # THE JUDGE, THE EXISTENCE CHECKS AND THE RUN COMMIT ARE FIXED
    defaults_dict = {"judge_func_in": lambda: FAKE_JUDGE_STR, "git_func_in": fake_accepting_git_func,
                     "prepare_func_in": lambda job_in: FAKE_RUN_COMMIT_STR}
    return run_queue.run_queue_list(path_dict_in, run_func_in, send_func_in, **{**defaults_dict, **kwarg_dict_in})


# FUNCTION: A FAKE GIT FOR add (status output, then a fixed HEAD)
def get_git_func(status_str_in=""):
    """
    Args:
        status_str_in (str): What git status --porcelain prints

    Returns:
        callable: args -> stdout
    """
    # status, THEN rev-parse
    def git_func(arg_list_in):
        return status_str_in if arg_list_in[0] == "status" else FAKE_COMMIT_STR + "\n"
    return git_func


CLEAN_GIT_FUNC = get_git_func("")


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


# FUNCTION: A FAKE DEVELOPMENT RUN THAT WRITES A MANIFEST
def get_fake_run_func(path_dict_in, email_worthy_bool_in, return_code_in=0):
    """
    Args:
        path_dict_in (dict): Queue paths
        email_worthy_bool_in (bool): Verdict to write
        return_code_in (int): Exit code (non-zero writes no manifest)

    Returns:
        callable: (job, run_id, log path) -> {return_code, log_line_list}
    """
    # THE SAME OUTPUT SHAPE AS run_development_process_dict
    def run_func(job_dict_in, run_id_str_in, log_path_str_in):
        line_list = ["loaded", f"results_row | row of {run_id_str_in} |"] if return_code_in == 0 else ["Traceback", "ValueError: boom"]
        Path(log_path_str_in).write_text("\n".join(line_list), encoding="utf-8")
        if return_code_in == 0:
            run_folder = Path(path_dict_in["runs"]) / run_id_str_in
            run_folder.mkdir(parents=True, exist_ok=True)
            (run_folder / "manifest.json").write_text(json.dumps({"status": "finished", "verdict": {
                "email_worthy": email_worthy_bool_in, "label": "x", "failed_list": [], "look_ahead": "pass"}}), encoding="utf-8")
        return {"return_code": return_code_in, "log_line_list": line_list}
    return run_func


# FUNCTION: A FAKE SMTP CLASS THAT RECORDS MESSAGES
class FakeSmtp:
    """
    Context manager with starttls, login and send_message.
    """
    sent_list = []

    def __init__(self, host_in, port_in, timeout=None):
        self.host = host_in
        self.port = port_in

    def __enter__(self):
        return self

    def __exit__(self, *args_in):
        return False

    def starttls(self):
        return None

    def login(self, user_in, password_in):
        return None

    def send_message(self, message_in):
        FakeSmtp.sent_list.append(message_in)


# FUNCTION: TEST THE QUEUE
def test_queue_runs_files_and_emails():
    """
    Jobs run oldest first; a finished run is filed in done/ with its results row; an email-worthy one is emailed;
    a failed run is filed in failed/ with the log tail; state.json records the results and no running job.

    Returns:
        None
    """
    # A QUEUE UNDER A FRESH ZONE
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    try:
        run_queue.add_job_dict(path_dict, "experiments/not_a_design", git_func_in=CLEAN_GIT_FUNC)
        raise AssertionError("a folder without design.py was queued")
    except ValueError:
        pass
    # A CLONE WITH UNCOMMITTED CODE CANNOT QUEUE ITS HEAD
    try:
        run_queue.add_job_dict(path_dict, DESIGN_STR, "dirty", git_func_in=get_git_func(" M experiments/exp13_e1m1_robustness/design.py\n"))
        raise AssertionError("a dirty clone was queued")
    except ValueError as error:
        assert "uncommitted" in str(error)
    # THE SAME CLOCK FOR BOTH (A WINDOWS CLOCK TICK): TWO DISTINCT JOBS, STILL IN ADD ORDER
    import datetime as datetime_module
    same_now = datetime_module.datetime(2026, 10, 26, 12, 0, 0)
    first_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "first", now_in=same_now, git_func_in=CLEAN_GIT_FUNC)
    second_dict = run_queue.add_job_dict(path_dict, DESIGN_STR + "/", "second", now_in=same_now + datetime_module.timedelta(microseconds=1),
                                         git_func_in=CLEAN_GIT_FUNC)
    assert first_dict["job_id"] != second_dict["job_id"]
    twin_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "twin", now_in=same_now - datetime_module.timedelta(days=1),
                                       git_func_in=CLEAN_GIT_FUNC)
    twin_two_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "twin", now_in=same_now - datetime_module.timedelta(days=1),
                                           git_func_in=CLEAN_GIT_FUNC)
    assert twin_dict["job_id"] != twin_two_dict["job_id"]
    for job_dict in (twin_dict, twin_two_dict):
        os.remove(os.path.join(path_dict["pending"], f"{job_dict['job_id']}.json"))
    assert first_dict["commit"] == FAKE_COMMIT_STR and first_dict["attempt"] == 1
    assert [job["job_id"] for job in run_queue.get_pending_job_list(path_dict)] == [first_dict["job_id"], second_dict["job_id"]]
    # THE FIRST IS EMAIL-WORTHY, THE SECOND IS NOT
    sent_list = []
    def send_func(path_dict_in, run_id_str_in, subject_str_in, body_str_in):
        sent_list.append(subject_str_in)
        return {"sent_bool": True, "detail": "fake"}
    order_list = []
    def run_func(job_dict_in, run_id_str_in, log_path_str_in):
        order_list.append(job_dict_in["note"])
        return get_fake_run_func(path_dict, job_dict_in["note"] == "first")(job_dict_in, run_id_str_in, log_path_str_in)
    result_list = run_fake_queue_list(path_dict, run_func, send_func)
    assert order_list == ["first", "second"]
    assert [result["status"] for result in result_list] == ["done", "done"]
    assert sent_list == ["Stock Overflow: PASS, audit pending - exp13_e1m1_robustness", "Stock Overflow: exp13_e1m1_robustness - x"], sent_list
    assert result_list[0]["results_row"].startswith("| row of exp13_e1m1_robustness_")
    assert result_list[1]["email"]["sent_bool"]
    assert not os.listdir(path_dict["pending"]) and len(os.listdir(path_dict["done"])) == 2
    assert not os.path.exists(path_dict["lock"])
    state_dict = run_queue.read_json(path_dict["state"])
    assert state_dict["running"] is None and state_dict["pending_count"] == 0
    assert [row["note"] for row in state_dict["recent"]] == ["second", "first"]
    # A FAILING RUN EMAILS AND IS FILED; A RETRY KEEPS ITS RUN ID AND COUNTS THE ATTEMPT
    third_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "third", git_func_in=CLEAN_GIT_FUNC)
    failed_list = run_fake_queue_list(path_dict, get_fake_run_func(path_dict, True, 1), send_func)
    assert failed_list[0]["status"] == "failed" and failed_list[0]["log_tail"][-1] == "ValueError: boom"
    assert len(os.listdir(path_dict["failed"])) == 1 and sent_list[-1].endswith("run failed")
    retry_dict = run_queue.add_retry_job_dict(path_dict, third_dict["job_id"])
    assert retry_dict["run_id"] == failed_list[0]["run_id"] and retry_dict["attempt"] == 2
    assert retry_dict["judge_commit"] == FAKE_JUDGE_STR
    retry_result_list = run_fake_queue_list(path_dict, get_fake_run_func(path_dict, False), send_func)
    assert retry_result_list[0]["run_id"] == failed_list[0]["run_id"] and retry_result_list[0]["status"] == "done"
    # THE RUN INDEX HAS ONE ROW PER ATTEMPT
    import pandas as pd
    index_pdf = pd.read_csv(path_dict["run_index"], dtype=str)
    assert list(index_pdf["status"]) == ["done", "done", "failed", "done"], list(index_pdf["status"])
    assert list(index_pdf["attempt"]) == ["1", "1", "1", "2"] and set(index_pdf["commit"]) == {FAKE_COMMIT_STR} and set(index_pdf["judge_commit"]) == {FAKE_JUDGE_STR}
    assert os.path.isdir(path_dict["running"]) and not os.listdir(path_dict["running"]) and not os.listdir(path_dict["rejected"])
    passed("queue (commit pinned, dirty clone refused, oldest first, filing, failure email, retry under the same run id and judge, run index)")
    # A SECOND RUNNER IS REFUSED WHILE A LIVE LOCK EXISTS; A STALE LOCK (DEAD PROCESS, SAME HOST) IS REPLACED
    import socket
    Path(path_dict["lock"]).write_text(json.dumps({"pid": 4242, "host": socket.gethostname()}), encoding="utf-8")
    try:
        run_fake_queue_list(path_dict, run_func, send_func, pid_alive_func_in=lambda pid_in: True)
        raise AssertionError("a second runner started")
    except SystemExit as error:
        assert "another queue runner" in str(error)
    assert run_fake_queue_list(path_dict, run_func, send_func, pid_alive_func_in=lambda pid_in: False) == []
    assert not os.path.exists(path_dict["lock"])
    passed("queue lock (a live runner refuses a second one; a stale lock is replaced)")


# FUNCTION: A JOB OVER ITS TIME LIMIT IS KILLED WITH ITS CHILDREN
def test_queue_timeout_kills_tree():
    """
    run_logged_command_dict stops a process that starts a child and sleeps; the log records the timeout.

    Returns:
        None
    """
    # A PARENT THAT STARTS A SLEEPING CHILD
    folder_str = tempfile.mkdtemp(prefix="so_timeout_", dir=os.environ["SO_DATA_PATH"])
    log_path_str = os.path.join(folder_str, "run.log")
    script_str = ("import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                  "print('started', flush=True); time.sleep(60)")
    import time as time_module
    start_float = time_module.time()
    outcome_dict = run_queue.run_logged_command_dict([sys.executable, "-c", script_str], folder_str, dict(os.environ),
                                                     log_path_str, 3.0, "header\n")
    assert outcome_dict["timed_out_bool"] and time_module.time() - start_float < 30
    assert "TIMEOUT" in Path(log_path_str).read_text(encoding="utf-8")
    passed("queue timeout kills the run and its child processes and logs it")


# FUNCTION: TEST THE EMAIL SENDER
def test_email_outbox_and_smtp():
    """
    Without settings the message goes to the outbox. With settings it is sent through SMTP with STARTTLS.

    Returns:
        None
    """
    # NO SETTINGS
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    for name_str in ["SO_SMTP_HOST", "SO_EMAIL_TO", "SO_SMTP_USER", "SO_SMTP_PASSWORD"]:
        os.environ.pop(name_str, None)
    result_dict = run_queue.send_email_dict(path_dict, "run1", "subject", "body", FakeSmtp)
    assert not result_dict["sent_bool"] and os.path.isfile(os.path.join(path_dict["outbox"], "run1.txt"))
    # WITH SETTINGS
    os.environ.update({"SO_SMTP_HOST": "smtp.example", "SO_EMAIL_TO": "to@example.com", "SO_SMTP_USER": "from@example.com",
                       "SO_SMTP_PASSWORD": "x"})
    try:
        result_dict = run_queue.send_email_dict(path_dict, "run2", "subject", "body", FakeSmtp)
    finally:
        for name_str in ["SO_SMTP_HOST", "SO_EMAIL_TO", "SO_SMTP_USER", "SO_SMTP_PASSWORD"]:
            os.environ.pop(name_str, None)
    assert result_dict["sent_bool"] and FakeSmtp.sent_list[-1]["To"] == "to@example.com"
    passed("email (outbox without settings, SMTP with settings)")


# FUNCTION: TEST THE PROTECTED-PATH CHECK
def test_protected_paths():
    """
    The list covers the guards; folder globs cover every depth; an append-only file may only grow.

    Returns:
        None
    """
    # THE REAL LIST
    protected_dict = read_protected_dict()
    for path_str in ["so/core/holdout.py", "so/core/point_in_time.py", "so/runner/lookahead.py", "records/holdout_windows.csv",
                     "AGENTS.md", ".cursor/rules/research-integrity.mdc", "scripts/holdout_evaluate.py", "tests/test_runner_minute.py",
                     "requirements/venv_main_lock.txt", "protected_paths.txt"]:
        assert get_protected_bool(path_str, protected_dict["glob_list"]), path_str
    for path_str in ["so/core/evaluation.py", "so/core/trade_execution.py", "so/runner/guard.py", "tests/runner_guard_design.py",
                     ".github/workflows/ci.yml"]:
        assert get_protected_bool(path_str, protected_dict["glob_list"]), path_str
    for path_str in ["experiments/exp99_new/design.py", "so/features/rule_design.py", "tests/test_experiments.py", "docs/notes.md"]:
        assert not get_protected_bool(path_str, protected_dict["glob_list"]), path_str
    assert "docs/RESULTS_LOG.md" in protected_dict["append_list"]
    # DESIGN 2026-10-27: DESIGN DOCUMENTS, PIPELINE NOTEBOOKS AND THE RESULTS LOG ARE CORE; THE JUDGE IDENTITY IS PROTECTED
    for path_str in ["docs/AGENTIC_DESIGN.md", "docs/AGENTIC_DESIGN.drawio", "docs/RUNNER_DESIGN.md", "docs/DATA_SOURCES.md",
                     "pipeline/step05_TSBAR_data_collection.ipynb", "docs/RESULTS_LOG.md", "so/runner/judge_identity.py",
                     "tests/test_runner_judge.py"]:
        assert get_protected_bool(path_str, protected_dict["glob_list"]), path_str
    assert get_append_only_bool("--- a/x\n+++ b/x\n@@ -10,0 +11 @@\n+| new row |")
    assert not get_append_only_bool("--- a/x\n+++ b/x\n@@ -3 +3 @@\n-| old |\n+| edited |")
    # A BRANCH THAT CHANGES A GUARD, AN EXPERIMENT AND APPENDS A RESULT ROW
    base_list_str = Path(WORKSPACE_PATH_STR, "protected_paths.txt").read_text(encoding="utf-8")
    output_dict = {"merge-base": "abc\n", "--name-only": "so/core/holdout.py\nexperiments/exp99_new/design.py\ndocs/RESULTS_LOG.md\n",
                   "ls-files": "records/new.csv\n", "-U0": "@@ -5,0 +6 @@\n+| row |\n", "show": base_list_str}
    def git_func(arg_list_in):
        for key_str, output_str in output_dict.items():
            if key_str in arg_list_in:
                return output_str
        raise AssertionError(arg_list_in)
    assert get_violation_list("main", git_func) == ["records/new.csv: protected", "so/core/holdout.py: protected"]
    # THE LIST COMES FROM THE BASE: A BRANCH THAT DROPS so/core/evaluation.py FROM ITS OWN COPY IS STILL CAUGHT
    output_dict["--name-only"] = "protected_paths.txt\nso/core/evaluation.py\n"
    output_dict["ls-files"] = ""
    violation_list = get_violation_list("main", git_func)
    assert "so/core/evaluation.py: protected" in violation_list and "protected_paths.txt: protected" in violation_list, violation_list
    # EVERY so/ MODULE THAT PROTECTED CODE IMPORTS IS PROTECTED (AUDIT B4)
    from check_protected_paths import get_unprotected_closure_list
    assert get_unprotected_closure_list() == [], get_unprotected_closure_list()
    reduced_glob_list = [glob_str for glob_str in protected_dict["glob_list"] if glob_str != "so/core/evaluation.py"]
    assert "so/core/evaluation.py" in get_unprotected_closure_list(reduced_glob_list)
    # CODEOWNERS NAMES EVERY PROTECTED GLOB, SO A PROTECTED CHANGE NEEDS NICOLAS'S REVIEW ON GITHUB
    owner_text_str = Path(WORKSPACE_PATH_STR, ".github", "CODEOWNERS").read_text(encoding="utf-8")
    owner_pattern_set = {line_str.split()[0] for line_str in owner_text_str.splitlines() if line_str.strip() and not line_str.startswith("#")}
    for glob_str in protected_dict["glob_list"]:
        pattern_str = "/" + (glob_str[:-2] if glob_str.endswith("/**") else glob_str)
        assert pattern_str in owner_pattern_set, f"CODEOWNERS misses {glob_str}"
    passed("protected paths (guards covered, list read from the base, import closure protected, CODEOWNERS in sync, RESULTS_LOG append-only)")


# FUNCTION: TEST THE PACKAGE LOCK CHECK
def test_environment_lock():
    """
    A missing package and a different version are reported; extra installed packages are not; no lock gives None.

    Returns:
        None
    """
    # A SMALL LOCK
    lock_path = Path(tempfile.mkdtemp(prefix="so_lock_", dir=os.environ["SO_DATA_PATH"])) / "lock.txt"
    lock_path.write_text("pandas==2.3.3\nNumPy==2.1.3\nlight_gbm==4.6.0\n# comment\n-e git+x#egg=y\n", encoding="utf-8")
    difference_list = check_environment_list(lock_path, {"pandas": "2.3.3", "numpy": "2.2.0", "extra": "1"})
    assert difference_list == ["light-gbm: locked 4.6.0, not installed", "numpy: locked 2.1.3, installed 2.2.0"], difference_list
    assert check_environment_list(lock_path, {"pandas": "2.3.3", "numpy": "2.1.3", "light-gbm": "4.6.0"}) == []
    assert check_environment_list(lock_path.parent / "missing.txt", {}) is None
    passed("package lock (missing and different versions reported, extras ignored)")


# FUNCTION: TEST THAT HOLDOUT RESULTS STAY OUT OF THE REPOSITORY
def test_ledger_outside_repository():
    """
    Without SO_HOLDOUT_PATH there is no evaluation ledger path, and reading or writing it raises. records/ holds no
    ledger.

    Returns:
        None
    """
    # THIS SUITE NEVER SETS SO_HOLDOUT_PATH
    from so import paths
    from so.core.holdout import read_holdout_evaluation_pdf, append_holdout_evaluation_dict
    assert not os.environ.get("SO_HOLDOUT_PATH") and paths.HOLDOUT_EVALUATIONS_FILE_PATH_STR is None
    for call_func in (lambda: read_holdout_evaluation_pdf(), lambda: append_holdout_evaluation_dict({"status": "valid"})):
        try:
            call_func()
            raise AssertionError("the ledger was reached without SO_HOLDOUT_PATH")
        except ValueError as error:
            assert "SO_HOLDOUT_PATH" in str(error)
    assert not os.path.exists(os.path.join(WORKSPACE_PATH_STR, "records", "holdout_evaluations.csv"))
    passed("holdout ledger only under SO_HOLDOUT_PATH (none in records/, unreachable without the variable)")


# FUNCTION: COMMITTED NOTEBOOKS CARRY NO OUTPUTS (AUDIT S6)
def test_notebooks_without_outputs():
    """
    Executed notebooks hold data (step 00 once showed raw bars inside the holdout window). The repository keeps the
    code only; executed copies live under the quarantine (scripts/refresh_development_view.py).

    Returns:
        None
    """
    # EVERY .ipynb UNDER THE WORKSPACE
    import json
    notebook_list = sorted(Path(WORKSPACE_PATH_STR).rglob("*.ipynb"))
    assert notebook_list, "no notebook found"
    for notebook_path in notebook_list:
        if ".ipynb_checkpoints" in notebook_path.parts:
            continue
        notebook_dict = json.loads(notebook_path.read_text(encoding="utf-8"))
        for cell_dict in notebook_dict.get("cells", []):
            assert not cell_dict.get("outputs"), f"{notebook_path.name} has committed outputs; clear them before committing"
    passed(f"committed notebooks carry no outputs ({len(notebook_list)} checked)")


# FUNCTION: A JOB'S WORKTREE IS AT ITS COMMIT AND IS REMOVED AFTERWARDS; FINISHED RUNS BECOME RESULTS-LOG ROWS
def test_queue_worktree_and_results_rows():
    """
    A throwaway git repository with two commits: the worktree of the first commit holds the first content, an unknown
    commit is refused, and removal leaves nothing. append_results_log turns a finished index row into one row, once.

    Returns:
        None
    """
    # A REPOSITORY WITH TWO COMMITS
    import subprocess
    repo_str = tempfile.mkdtemp(prefix="so_repo_")
    def git_func(arg_list_in):
        return run_queue.run_git_str(arg_list_in, repo_str)
    for arg_list in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        git_func(arg_list)
    Path(repo_str, "f.txt").write_text("one", encoding="utf-8")
    git_func(["add", "f.txt"]); git_func(["commit", "-q", "-m", "one"])
    first_commit_str = git_func(["rev-parse", "HEAD"]).strip()
    Path(repo_str, "f.txt").write_text("two", encoding="utf-8")
    git_func(["commit", "-q", "-am", "two"])
    worktree_root_str = tempfile.mkdtemp(prefix="so_worktrees_")
    os.environ["SO_QUEUE_WORKTREE_ROOT"] = worktree_root_str
    try:
        worktree_str = run_queue.make_job_worktree_str(first_commit_str, "run_a", git_func)
        assert Path(worktree_str, "f.txt").read_text(encoding="utf-8") == "one"
        run_queue.remove_job_worktree(worktree_str, git_func)
        assert not os.path.exists(worktree_str)
        try:
            run_queue.make_job_worktree_str("0" * 40, "run_b", git_func)
            raise AssertionError("an unknown commit got a worktree")
        except ValueError as error:
            assert "push it to origin" in str(error)
    finally:
        os.environ.pop("SO_QUEUE_WORKTREE_ROOT", None)
    # RESULTS-LOG ROWS FROM THE INDEX
    import pandas as pd
    from append_results_log import get_new_row_list
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    Path(path_dict["runs"], "run_x").mkdir()
    Path(path_dict["runs"], "run_x", "report.json").write_text(json.dumps({
        "experiment_name_str": "expZZ", "protocol_version_str": "1.0", "label_str": "not email-worthy",
        "failed_list": ["return"], "return_dict": {"strategy_total_return": 0.1, "buy_hold_total_return": 0.2},
        "look_ahead_dict": {"status_str": "pass"}}), encoding="utf-8")
    pd.DataFrame([{**{column_str: "" for column_str in run_queue.RUN_INDEX_COLUMN_LIST}, "run_id": "run_x", "status": "done",
                   "note": "n", "finished_ts": "2026-10-26T10:00:00"},
                  {**{column_str: "" for column_str in run_queue.RUN_INDEX_COLUMN_LIST}, "run_id": "run_y", "status": "failed"}]
                 ).to_csv(path_dict["run_index"], index=False)
    log_path = Path(zone_str, "RESULTS_LOG.md")
    log_path.write_text("| Date | ... |\n", encoding="utf-8")
    row_list = get_new_row_list(path_dict, log_path)
    assert row_list == ["| 2026-10-26 | expZZ | 1.0 | run_x | not email-worthy | +10.00% vs +20.00% | return | pass | n |"], row_list
    log_path.write_text("| Date | ... |\n" + row_list[0] + "\n", encoding="utf-8")
    assert get_new_row_list(path_dict, log_path) == []
    passed("queue worktree at the job's commit (unknown commit refused, removed after); results-log rows from the run index, once")


# FUNCTION: EVERY SCRIPT AND MODULE COMPILES (AUDIT 2026-10-26: A BROKEN scripts/run_development.py REACHED main)
def test_every_python_file_compiles():
    """
    py_compile on every .py file of so/, scripts/, experiments/ and tests/, and an import of each script module, so a
    syntax or indentation error in a file no suite imports still fails the tests.

    Returns:
        None
    """
    # COMPILE EVERYTHING
    import importlib
    file_list = []
    for folder_str in ["so", "scripts", "experiments", "tests"]:
        file_list.extend(sorted(Path(WORKSPACE_PATH_STR, folder_str).rglob("*.py")))
    for file_path in file_list:
        if ".worktrees" in file_path.parts:
            continue
        compile(file_path.read_text(encoding="utf-8"), str(file_path), "exec")
    for module_str in ["run_development", "run_queue", "append_results_log", "check_protected_paths",
                       "check_environment", "check_agent_access", "holdout_evaluate", "holdout_window"]:
        importlib.import_module(module_str)
    # THE DEVELOPMENT ENTRY POINT LOADS EVERY EXPERIMENT BEHIND THE GUARD
    run_development_module = importlib.import_module("run_development")
    experiment_list = sorted(path.parent for path in Path(WORKSPACE_PATH_STR, "experiments").glob("exp*/design.py"))
    for experiment_path in experiment_list:
        design_module = run_development_module.load_design_module(str(experiment_path))
        assert hasattr(design_module, "get_candidate_design") and hasattr(design_module, "EXPERIMENT_NAME"), experiment_path
    passed(f"every Python file compiles ({len(file_list)}), the script modules import, and run_development loads {len(experiment_list)} experiments")


# FUNCTION: A VALID PENDING JOB FILE FOR THE VALIDATION TESTS
def get_valid_job_dict(suffix_str_in="aaaaaa", extra_dict_in=None):
    """
    Args:
        suffix_str_in (str): Six hex characters (keeps job ids apart)
        extra_dict_in (dict | None): Fields added or replaced

    Returns:
        dict: A job that passes get_clean_job_dict
    """
    # THE FIELDS add WRITES
    job_dict = {"job_id": f"20261027120000000000_{suffix_str_in}_exp13_e1m1_robustness", "design": DESIGN_STR, "note": "n",
                "commit": FAKE_COMMIT_STR, "n_jobs": None, "added_ts": "2026-10-27T12:00:00", "added_by": "so_agent", "attempt": 1}
    job_dict.update(extra_dict_in or {})
    return job_dict


# FUNCTION: A PENDING FILE IS UNTRUSTED
def test_queue_rejects_bad_pending_files():
    """
    Fields are patterns, unknown fields and a run id or judge commit without a matching failed record are refused,
    and a rejected file is moved to rejected/ with its reason without stopping the valid job behind it.

    Returns:
        None
    """
    # THE FIELD CHECKS
    base_dict = get_valid_job_dict()
    assert run_queue.get_clean_job_dict(base_dict, base_dict["job_id"])["attempt"] == 1
    bad_case_list = [
        ("job_id traversal", {"job_id": "..\\..\\victim"}), ("job_id slash", {"job_id": "20261027120000000000_aaaaaa_a/b"}),
        ("design outside experiments", {"design": "so/runner"}), ("design traversal", {"design": "experiments/../so"}),
        ("design nested", {"design": "experiments/a/b"}), ("commit name", {"commit": "HEAD"}), ("commit short", {"commit": "c0ffee"}),
        ("commit upper", {"commit": FAKE_COMMIT_STR.upper()}), ("unknown field", {"env": {"A": "b"}}),
        ("note too long", {"note": "x" * 501}), ("note not text", {"note": ["a"]}), ("n_jobs zero", {"n_jobs": 0}),
        ("n_jobs huge", {"n_jobs": 1000}), ("n_jobs bool", {"n_jobs": True}), ("attempt text", {"attempt": "1"}),
        ("run_id traversal", {"run_id": "..\\..\\victim", "retry_of": "20261027120000000000_bbbbbb_x"}),
        ("retry_of traversal", {"retry_of": "..\\x", "run_id": "r1"}), ("added_by odd", {"added_by": "a;b"})]
    for label_str, change_dict in bad_case_list:
        try:
            run_queue.get_clean_job_dict({**base_dict, **change_dict}, base_dict["job_id"])
            raise AssertionError(f"accepted: {label_str}")
        except ValueError:
            pass
    try:
        run_queue.get_clean_job_dict(base_dict, "20261027120000000000_zzzzzz_other")
        raise AssertionError("a job id that differs from the file name was accepted")
    except ValueError:
        pass
    assert "\n" not in run_queue.get_clean_job_dict({**base_dict, "note": "a\nb\tc"}, base_dict["job_id"])["note"]
    # PENDING FILES: SEVERAL BAD ONES, THEN A VALID ONE
    import time as time_module
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    def write_pending(job_dict_in, age_seconds_in=0):
        file_str = os.path.join(path_dict["pending"], f"{job_dict_in['job_id']}.json")
        Path(file_str).write_text(json.dumps(job_dict_in), encoding="utf-8")
        if age_seconds_in:
            os.utime(file_str, (time_module.time() - age_seconds_in,) * 2)
        return file_str
    write_pending(get_valid_job_dict("000001", {"commit": "main"}))
    write_pending(get_valid_job_dict("000002", {"env": "x"}))
    write_pending(get_valid_job_dict("000003", {"run_id": "run_forged"}))
    write_pending(get_valid_job_dict("000004", {"judge_commit": FAKE_JUDGE_STR}))
    write_pending(get_valid_job_dict("000005", {"retry_of": "20261027110000000000_cccccc_exp13_e1m1_robustness", "run_id": "run_forged"}))
    Path(path_dict["pending"], "20261027120000000000_000006_exp13_e1m1_robustness.json").write_text("{not json", encoding="utf-8")
    old_broken_str = Path(path_dict["pending"], "20261027120000000000_000007_exp13_e1m1_robustness.json")
    old_broken_str.write_text("{not json", encoding="utf-8")
    os.utime(old_broken_str, (time_module.time() - 7200,) * 2)
    Path(path_dict["pending"], "20261027120000000000_000008_exp13_e1m1_robustness.json").write_text(" " * 70000, encoding="utf-8")
    good_dict = get_valid_job_dict("000009")
    write_pending(good_dict)
    next_dict = run_queue.get_next_job_dict(path_dict, fake_accepting_git_func)
    assert next_dict is not None and next_dict["job_id"] == good_dict["job_id"], next_dict
    rejected_list = sorted(os.listdir(path_dict["rejected"]))
    assert len(rejected_list) == 7, rejected_list
    assert sorted(os.listdir(path_dict["pending"])) == sorted([f"{good_dict['job_id']}.json",
                                                              "20261027120000000000_000006_exp13_e1m1_robustness.json"])
    reason_str = run_queue.read_json(os.path.join(path_dict["rejected"], rejected_list[0]))["reason"]
    assert reason_str
    state_recent_list = run_queue.read_json(path_dict["state"])["recent"]
    assert len(state_recent_list) == 7 and all(row["status"] == "rejected" and row["reason"] for row in state_recent_list)
    # A COMMIT THAT GIT DOES NOT HAVE
    import subprocess as subprocess_module
    def missing_git_func(arg_list_in, **kwarg_dict_in):
        raise subprocess_module.CalledProcessError(128, "git", output="fatal: Not a valid object name")
    try:
        run_queue.get_validated_job_dict(path_dict, good_dict, good_dict["job_id"], missing_git_func)
        raise AssertionError("a commit git does not have was accepted")
    except ValueError as error:
        assert "push it to origin" in str(error)
    # A RETRY MUST MATCH THE RUNNER'S RECORD OF THE FAILED JOB
    failed_id_str = "20261027110000000000_cccccc_exp13_e1m1_robustness"
    run_queue.write_json_atomic(os.path.join(path_dict["failed"], f"{failed_id_str}.json"), {
        "job_id": failed_id_str, "run_id": "run_real", "design": DESIGN_STR, "commit": FAKE_COMMIT_STR,
        "judge_commit": FAKE_JUDGE_STR, "attempt": 1})
    retry_base_dict = get_valid_job_dict("00000a", {"retry_of": failed_id_str, "run_id": "run_real", "attempt": 5})
    accepted_dict = run_queue.get_validated_job_dict(path_dict, retry_base_dict, retry_base_dict["job_id"], fake_accepting_git_func)
    assert accepted_dict["judge_commit"] == FAKE_JUDGE_STR and accepted_dict["attempt"] == 2
    for label_str, change_dict in [("other run id", {"run_id": "run_other"}), ("other design", {"design": "experiments/exp12_vix_fear_reentry"}),
                                   ("other commit", {"commit": "1" * 40}), ("other judge", {"judge_commit": "2" * 40})]:
        try:
            run_queue.get_validated_job_dict(path_dict, {**retry_base_dict, **change_dict}, retry_base_dict["job_id"], fake_accepting_git_func)
            raise AssertionError(f"forged retry accepted: {label_str}")
        except ValueError:
            pass
    passed("pending files are untrusted (patterns, unknown fields, forged run id / judge / retry, missing commit; rejected/ keeps the reason)")


# FUNCTION: A CRASH OR REBOOT RESUMES THE JOB UNDER ITS RUN ID AND ITS JUDGE
def test_queue_claim_resume_and_give_up():
    """
    A claimed job lives in running/. After a crash the next runner resumes it with the same run id and the judge
    commit of the first start (the judge moved on meanwhile), counts the interruption, and files a job interrupted
    too often as failed without starting a process. A refused run commit rejects the job without an email.

    Returns:
        None
    """
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    sent_list = []
    def send_func(path_dict_in, run_id_str_in, subject_str_in, body_str_in):
        sent_list.append(subject_str_in)
        return {"sent_bool": True, "detail": "fake"}
    # CLAIM, THEN "CRASH"
    first_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "crashy", git_func_in=CLEAN_GIT_FUNC)
    claimed_dict = run_queue.claim_job_dict(path_dict, first_dict, lambda: FAKE_JUDGE_STR)
    assert os.path.isfile(os.path.join(path_dict["running"], f"{first_dict['job_id']}.json"))
    assert not os.path.isfile(os.path.join(path_dict["pending"], f"{first_dict['job_id']}.json"))
    assert claimed_dict["judge_commit"] == FAKE_JUDGE_STR and claimed_dict["run_id"].startswith("exp13_e1m1_robustness_")
    seen_list = []
    def run_func(job_dict_in, run_id_str_in, log_path_str_in):
        seen_list.append(dict(job_dict_in))
        return get_fake_run_func(path_dict, False)(job_dict_in, run_id_str_in, log_path_str_in)
    result_list = run_fake_queue_list(path_dict, run_func, send_func, judge_func_in=lambda: "d" * 40)
    assert len(result_list) == 1 and result_list[0]["status"] == "done"
    assert seen_list[0]["run_id"] == claimed_dict["run_id"] and seen_list[0]["judge_commit"] == FAKE_JUDGE_STR
    assert seen_list[0]["attempt"] == 2 and seen_list[0]["resume_count"] == 1 and seen_list[0]["run_commit"] == FAKE_RUN_COMMIT_STR
    assert result_list[0]["log"].endswith(f"{claimed_dict['run_id']}_attempt2.log")
    assert not os.listdir(path_dict["running"]) and not os.listdir(path_dict["pending"])
    # INTERRUPTED TOO OFTEN: FILED AS FAILED, NO PROCESS, ONE FAILURE EMAIL
    second_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "unlucky", git_func_in=CLEAN_GIT_FUNC)
    run_queue.claim_job_dict(path_dict, second_dict, lambda: FAKE_JUDGE_STR)
    running_path_str = os.path.join(path_dict["running"], f"{second_dict['job_id']}.json")
    running_dict = run_queue.read_json(running_path_str)
    run_queue.write_json_atomic(running_path_str, {**running_dict, "resume_count": run_queue.MAX_RESUME_COUNT_INT})
    seen_list.clear()
    result_list = run_fake_queue_list(path_dict, run_func, send_func)
    assert seen_list == [] and result_list[0]["status"] == "failed" and "gave up" in result_list[0]["log_tail"][-1]
    assert sent_list[-1].endswith("run failed") and os.path.isfile(os.path.join(path_dict["failed"], f"{second_dict['job_id']}.json"))
    # A REFUSED RUN COMMIT IS A REJECTED JOB, NOT A FAILED ONE, AND NOBODY IS EMAILED
    third_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "refused", git_func_in=CLEAN_GIT_FUNC)
    email_count_int = len(sent_list)
    def refusing_prepare_func(job_in):
        raise ValueError("the job commit changes files outside experiments/: so/config.py")
    result_list = run_fake_queue_list(path_dict, run_func, send_func, prepare_func_in=refusing_prepare_func)
    assert result_list == [] and len(sent_list) == email_count_int and not os.listdir(path_dict["running"])
    rejected_dict = run_queue.read_json(os.path.join(path_dict["rejected"], f"{third_dict['job_id']}.json"))
    assert "outside experiments/" in rejected_dict["reason"]
    passed("queue claim and resume (same run id and judge after a crash, give-up after too many interruptions, refused commit rejected without email)")


# FUNCTION: THE HEARTBEAT, THE CHILD ENVIRONMENT
def test_queue_heartbeat_and_child_environment():
    """
    state.json is refreshed while a job runs; the child process environment lacks SMTP settings, tokens and keys.

    Returns:
        None
    """
    # A SLOW FAKE RUN WITH A SHORT HEARTBEAT
    import time as time_module
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    run_queue.add_job_dict(path_dict, DESIGN_STR, "slow", git_func_in=CLEAN_GIT_FUNC)
    seen_dict = {}
    def slow_run_func(job_dict_in, run_id_str_in, log_path_str_in):
        seen_dict["before_ns"] = os.stat(path_dict["state"]).st_mtime_ns
        time_module.sleep(0.8)
        seen_dict["after_ns"] = os.stat(path_dict["state"]).st_mtime_ns
        seen_dict["running"] = run_queue.read_json(path_dict["state"])["running"]
        return get_fake_run_func(path_dict, False)(job_dict_in, run_id_str_in, log_path_str_in)
    os.environ["SO_QUEUE_HEARTBEAT_SECONDS"] = "0.1"
    try:
        result_list = run_fake_queue_list(path_dict, slow_run_func, lambda *args_in: {"sent_bool": True, "detail": ""})
    finally:
        os.environ.pop("SO_QUEUE_HEARTBEAT_SECONDS", None)
    assert result_list[0]["status"] == "done" and seen_dict["after_ns"] > seen_dict["before_ns"]
    assert seen_dict["running"]["run_id"] == result_list[0]["run_id"]
    # SECRETS DO NOT REACH THE CHILD; THE REST DOES
    child_dict = run_queue.get_child_environment_dict({
        "PATH": "/bin", "SystemRoot": "C:\\Windows", "SO_DATA_PATH": "d", "SO_QUEUE_PYTHON": "py", "HOME": "/h",
        "SO_SMTP_PASSWORD": "p", "SO_SMTP_HOST": "h", "SO_EMAIL_TO": "a@b", "so_email_extra": "x", "GITHUB_TOKEN": "t",
        "GH_TOKEN": "t", "MY_API_KEY": "k", "db_password": "q", "ANTHROPIC_API_KEY": "a", "SO_HOLDOUT_EVALUATION_TOKEN": "h",
        "AWS_SECRET_ACCESS_KEY": "s"})
    assert sorted(child_dict) == ["HOME", "PATH", "SO_DATA_PATH", "SO_QUEUE_PYTHON", "SystemRoot"], sorted(child_dict)
    passed("queue heartbeat (state.json refreshed during a job) and child environment (no SMTP, token or key variables)")


# FUNCTION: A GIT REPOSITORY WITH A JUDGE ON MAIN AND TWO BRANCHES
def make_judge_test_repo():
    """
    main: so/helper.py (v1), scripts/run_development.py, experiments/exp_a. Branch design: changes experiments only.
    Then main moves on (helper v2). Branch bad_outside changes so/helper.py. Branch bad_link adds a symbolic link
    under experiments/. Branch bad_none deletes experiments/.

    Returns:
        dict: repo path, git function, commits (judge1, judge2, design, bad_outside, bad_link, bad_none)
    """
    # A SCRIPT THAT PRINTS WHAT THE RUN SEES
    repo_str = tempfile.mkdtemp(prefix="so_judge_repo_")
    def git_func(arg_list_in, **kwarg_dict_in):
        # WINDOWS TURNS "\n" INTO "\r\n" ON A TEXT PIPE; NO GIT INPUT OF THE QUEUE MAY DEPEND ON A NEWLINE
        assert "\n" not in (kwarg_dict_in.get("input_str_in") or ""), "git input must not contain a newline"
        return run_queue.run_git_str(arg_list_in, repo_str, **kwarg_dict_in)
    def write_file(relative_str_in, text_str_in):
        file_path = Path(repo_str, relative_str_in)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(text_str_in, encoding="utf-8")
    for arg_list in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        git_func(arg_list)
    script_str = (
        "import json, os, subprocess, sys\n"
        "from pathlib import Path\n"
        "run_id = sys.argv[sys.argv.index('--run-id') + 1]\n"
        "print('secret_visible', bool(os.environ.get('SO_SMTP_PASSWORD')))\n"
        "print('judge', Path('so/helper.py').read_text().strip())\n"
        "print('design', Path('experiments/exp_a/design.py').read_text().strip())\n"
        "print('head', subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip())\n"
        "print('dirty', repr(subprocess.check_output(['git', 'status', '--porcelain'], text=True)))\n"
        "folder = Path(os.environ['SO_TEST_RUNS_PATH'], run_id); folder.mkdir(parents=True, exist_ok=True)\n"
        "(folder / 'manifest.json').write_text(json.dumps({'status': 'finished', 'verdict': {'email_worthy': False, 'label': 'x', 'failed_list': [], 'look_ahead': 'pass'}}))\n"
        "print('results_row | ok |')\n")
    write_file("so/helper.py", "judge v1\n")
    write_file("scripts/run_development.py", script_str)
    write_file("experiments/exp_a/design.py", "design v1\n")
    git_func(["add", "-A"]); git_func(["commit", "-q", "-m", "judge1"])
    judge1_str = git_func(["rev-parse", "HEAD"]).strip()
    commit_dict = {"judge1": judge1_str}
    git_func(["checkout", "-q", "-b", "design"])
    write_file("experiments/exp_a/design.py", "design v2\n"); write_file("experiments/exp_b/design.py", "design b\n")
    git_func(["add", "-A"]); git_func(["commit", "-q", "-m", "design"])
    commit_dict["design"] = git_func(["rev-parse", "HEAD"]).strip()
    git_func(["checkout", "-q", "-b", "bad_outside", judge1_str])
    write_file("so/helper.py", "judge forged\n"); write_file("experiments/exp_a/design.py", "design v2\n")
    git_func(["add", "-A"]); git_func(["commit", "-q", "-m", "bad outside"])
    commit_dict["bad_outside"] = git_func(["rev-parse", "HEAD"]).strip()
    git_func(["checkout", "-q", "-b", "bad_link", judge1_str])
    link_blob_str = git_func(["hash-object", "-w", "--stdin"], input_str_in="../so/helper.py").strip()
    git_func(["update-index", "--add", "--cacheinfo", f"120000,{link_blob_str},experiments/exp_a/link.py"])
    git_func(["commit", "-q", "-m", "bad link"])
    commit_dict["bad_link"] = git_func(["rev-parse", "HEAD"]).strip()
    git_func(["checkout", "-q", "-b", "unicode_ok", judge1_str])
    write_file("experiments/exp_a/é.py", "x = 1\n")
    git_func(["add", "-A"]); git_func(["commit", "-q", "-m", "unicode inside"])
    commit_dict["unicode_ok"] = git_func(["rev-parse", "HEAD"]).strip()
    git_func(["checkout", "-q", "-b", "unicode_outside", judge1_str])
    write_file("so/é.py", "x = 1\n")
    git_func(["add", "-A"]); git_func(["commit", "-q", "-m", "unicode outside"])
    commit_dict["unicode_outside"] = git_func(["rev-parse", "HEAD"]).strip()
    git_func(["checkout", "-q", "-b", "bad_none", judge1_str])
    git_func(["rm", "-r", "-q", "experiments"]); git_func(["commit", "-q", "-m", "bad none"])
    commit_dict["bad_none"] = git_func(["rev-parse", "HEAD"]).strip()
    git_func(["checkout", "-q", "main"])
    write_file("so/helper.py", "judge v2\n")
    git_func(["add", "-A"]); git_func(["commit", "-q", "-m", "judge2"])
    commit_dict["judge2"] = git_func(["rev-parse", "HEAD"]).strip()
    return {"repo": repo_str, "git": git_func, "commit": commit_dict}


# FUNCTION: THE RUN COMMIT TAKES THE JUDGE FROM MAIN AND THE DESIGN FROM THE JOB
def test_queue_judge_from_main_run_commit():
    """
    In a throwaway repository: the run commit has main's so/ and the branch's experiments/ (even though main moved on
    after the branch point), the same pair always gives the same commit, a job commit that changes anything outside
    experiments/, holds a link, or has no experiments/ is refused, a full queue run executes the script of the
    judge in a clean worktree with no secret variables, refs/runs/<run id> keeps the run commit, and the worktree is
    removed.

    Returns:
        None
    """
    repo_dict = make_judge_test_repo()
    git_func, commit_dict = repo_dict["git"], repo_dict["commit"]
    run_commit_str = run_queue.make_composite_commit_str(commit_dict["judge2"], commit_dict["design"], git_func)
    assert git_func(["show", f"{run_commit_str}:so/helper.py"]).strip() == "judge v2"
    assert git_func(["show", f"{run_commit_str}:experiments/exp_a/design.py"]).strip() == "design v2"
    assert git_func(["show", f"{run_commit_str}:experiments/exp_b/design.py"]).strip() == "design b"
    assert git_func(["rev-parse", f"{run_commit_str}^@"]).split() == [commit_dict["judge2"], commit_dict["design"]]
    assert run_queue.make_composite_commit_str(commit_dict["judge2"], commit_dict["design"], git_func) == run_commit_str
    run_queue.make_composite_commit_str(commit_dict["judge2"], commit_dict["unicode_ok"], git_func)
    for key_str, fragment_str in [("bad_outside", "outside experiments/"), ("bad_link", "symbolic link"), ("bad_none", "no experiments/"),
                                  ("unicode_outside", "outside experiments/")]:
        try:
            run_queue.make_composite_commit_str(commit_dict["judge2"], commit_dict[key_str], git_func)
            raise AssertionError(f"{key_str} was accepted")
        except ValueError as error:
            assert fragment_str in str(error), (key_str, str(error))
    same_commit_str = run_queue.make_composite_commit_str(commit_dict["judge2"], commit_dict["judge2"], git_func)
    assert git_func(["rev-parse", f"{same_commit_str}^@"]).split() == [commit_dict["judge2"]]
    # THE JUDGE COMMIT OF A NEW JOB: A FAILED FETCH FALLS BACK TO THE LOCAL REF; THE REF CAN BE CHANGED
    import subprocess as subprocess_module
    call_list = []
    def fake_git_func(arg_list_in, **kwarg_dict_in):
        call_list.append(list(arg_list_in))
        if arg_list_in[0] == "fetch":
            raise subprocess_module.CalledProcessError(128, "git", output="no network")
        return FAKE_JUDGE_STR + "\n"
    assert run_queue.get_judge_commit_str(fake_git_func) == FAKE_JUDGE_STR and call_list[-1][-1] == "origin/main^{commit}"
    os.environ["SO_QUEUE_JUDGE_REF"] = "origin/other"
    try:
        run_queue.get_judge_commit_str(fake_git_func)
    finally:
        os.environ.pop("SO_QUEUE_JUDGE_REF", None)
    assert call_list[-1][-1] == "origin/other^{commit}"
    # A FULL QUEUE RUN WITH THE REAL SCRIPT ENTRY: JOB FILE -> VALIDATION -> CLAIM -> RUN COMMIT -> WORKTREE -> PROCESS
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    job_dict = get_valid_job_dict("00000b", {"design": "experiments/exp_a", "commit": commit_dict["design"]})
    run_queue.write_job_file(os.path.join(path_dict["pending"], f"{job_dict['job_id']}.json"), job_dict)
    worktree_root_str = tempfile.mkdtemp(prefix="so_worktrees_")
    environment_update_dict = {"SO_QUEUE_WORKTREE_ROOT": worktree_root_str, "SO_TEST_RUNS_PATH": path_dict["runs"],
                               "SO_SMTP_PASSWORD": "hunter2"}
    os.environ.update(environment_update_dict)
    try:
        result_list = run_queue.run_queue_list(
            path_dict, lambda job_in, run_id_in, log_in: run_queue.run_development_process_dict(job_in, run_id_in, log_in, git_func),
            lambda *args_in: {"sent_bool": True, "detail": ""}, judge_func_in=lambda: commit_dict["judge2"], git_func_in=git_func)
    finally:
        for name_str in environment_update_dict:
            os.environ.pop(name_str, None)
    assert len(result_list) == 1 and result_list[0]["status"] == "done", result_list
    log_str = Path(result_list[0]["log"]).read_text(encoding="utf-8")
    assert "secret_visible False" in log_str and "judge judge v2" in log_str and "design design v2" in log_str, log_str
    assert f"head {run_commit_str}" in log_str and "dirty ''" in log_str, log_str
    assert result_list[0]["run_commit"] == run_commit_str and result_list[0]["judge_commit"] == commit_dict["judge2"]
    assert git_func(["rev-parse", f"refs/runs/{result_list[0]['run_id']}"]).strip() == run_commit_str
    assert not os.listdir(worktree_root_str) and not os.listdir(path_dict["running"])
    passed("judge from main (run commit = main's tree + the job's experiments/, deterministic, parents kept by refs/runs; "
           "outside changes, links and missing experiments/ refused; clean worktree, no secrets, removed afterwards)")


# FUNCTION: AN OLD run_index.csv IS BROUGHT TO THE CURRENT COLUMNS BEFORE THE NEXT APPEND
def test_queue_run_index_upgrade():
    """
    The append refuses a header that differs from the column list, so a new column would stop every append to an
    existing index. The runner rewrites an index that only lacks columns (keeping a copy) and leaves other files alone.

    Returns:
        None
    """
    import pandas as pd
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    assert run_queue.upgrade_run_index_file(path_dict) is False
    old_column_list = [name_str for name_str in run_queue.RUN_INDEX_COLUMN_LIST if name_str not in ("judge_hash", "judge_commit", "run_commit")]
    pd.DataFrame([{name_str: f"v_{name_str}" for name_str in old_column_list}]).to_csv(path_dict["run_index"], index=False)
    assert run_queue.upgrade_run_index_file(path_dict) is True
    upgraded_pdf = pd.read_csv(path_dict["run_index"], dtype=str, keep_default_na=False)
    assert list(upgraded_pdf.columns) == run_queue.RUN_INDEX_COLUMN_LIST
    assert upgraded_pdf.loc[0, "run_id"] == "v_run_id" and upgraded_pdf.loc[0, "judge_commit"] == ""
    assert len([name_str for name_str in os.listdir(zone_str) if name_str.startswith("run_index.csv.before_")]) == 1
    assert run_queue.upgrade_run_index_file(path_dict) is False
    run_queue.append_run_index_row(path_dict, {"run_id": "run_new", "job_id": "job_new", "design": DESIGN_STR, "status": "done",
                                               "judge_commit": FAKE_JUDGE_STR})
    final_pdf = pd.read_csv(path_dict["run_index"], dtype=str, keep_default_na=False)
    assert list(final_pdf["run_id"]) == ["v_run_id", "run_new"] and final_pdf.loc[1, "judge_commit"] == FAKE_JUDGE_STR
    # A FILE WITH A COLUMN THE LIST DOES NOT KNOW IS NOT TOUCHED
    other_str = os.path.join(tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"]), "run_index.csv")
    Path(other_str).write_text("run_id,mystery\nx,y\n", encoding="utf-8")
    assert run_queue.upgrade_run_index_file({"run_index": other_str}) is False
    assert Path(other_str).read_text(encoding="utf-8") == "run_id,mystery\nx,y\n"
    passed("run index upgrade (missing columns added with a copy of the old file, unknown columns left alone, appends work afterwards)")


# FUNCTION: ONE EMAIL PER FINISHED RUN, WITH THE NUMBERS BEHIND THE VERDICT
def test_run_email_content():
    """
    A negative and a positive run both get an email; the body carries the verdict, failed parts, returns, the number
    of designs tried, the judge hash, the commits and the paths; a missing number reads "n/a".

    Returns:
        None
    """
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    Path(path_dict["runs"], "run_p").mkdir()
    Path(path_dict["runs"], "run_p", "report.json").write_text(json.dumps({
        "return_dict": {"strategy_total_return": 0.1234, "buy_hold_total_return": 0.05},
        "multiple_testing_dict": {"design_count": 12}, "judge_hash_str": "abcdef0123456789abcdef"}), encoding="utf-8")
    result_dict = {"run_id": "run_p", "design": DESIGN_STR, "note": "why", "commit": FAKE_COMMIT_STR, "judge_commit": FAKE_JUDGE_STR,
                   "run_commit": FAKE_RUN_COMMIT_STR, "log": "L.log", "results_row": "| row |"}
    negative_dict = {"verdict": {"label": "not email-worthy", "email_worthy": False, "failed_list": ["return", "baselines"], "look_ahead": "pass"}}
    subject_str, body_str = run_queue.get_finished_run_email_tuple(path_dict, result_dict, negative_dict)
    assert subject_str == "Stock Overflow: exp13_e1m1_robustness - not email-worthy"
    for fragment_str in ["Run run_p", "Failed parts return, baselines", "Look-ahead check pass", "Total return +12.34% vs buy-and-hold +5.00%",
                         "Designs tried (the multiple-testing N) 12", "Judge hash abcdef0123456789", f"run {FAKE_RUN_COMMIT_STR}",
                         "report.md", "Log L.log", "| row |"]:
        assert fragment_str in body_str, (fragment_str, body_str)
    assert "audit" not in body_str
    positive_dict = {"verdict": {"label": "match or beat", "email_worthy": True, "failed_list": [], "look_ahead": "pass"}}
    subject_str, body_str = run_queue.get_finished_run_email_tuple(path_dict, result_dict, positive_dict)
    assert subject_str == "Stock Overflow: PASS, audit pending - exp13_e1m1_robustness"
    assert "Failed parts none" in body_str and "not rejected" in body_str
    subject_str, body_str = run_queue.get_finished_run_email_tuple(path_dict, {**result_dict, "run_id": "run_none"}, negative_dict)
    assert "Total return n/a vs buy-and-hold n/a" in body_str and "Judge hash n/a" in body_str
    assert "\n" not in run_queue.get_finished_run_email_tuple(
        path_dict, result_dict, {"verdict": {"label": "a\nBcc: x@y", "failed_list": []}})[0]
    passed("run email (one per finished run: verdict, failed parts, returns, N, judge hash, commits, paths; PASS subject; no header injection)")


# FUNCTION: THE KILL SWITCH STOPS NEW WORK AND FAILS CLOSED
def test_queue_kill_switch():
    """
    While the STOP file exists no job starts and an interrupted job is not resumed (its counters stay); the running job
    is not touched; removing the file lets the work go on. An unreadable flag counts as set, a missing one (or a missing
    control folder) does not.

    Returns:
        None
    """
    control_str = tempfile.mkdtemp(prefix="so_control_")
    flag_str = os.path.join(control_str, "control", "STOP")
    os.environ["SO_STOP_FLAG_PATH"] = flag_str
    try:
        zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
        path_dict = run_queue.get_queue_path_dict(zone_str)
        run_queue.make_runner_folder_list(path_dict)
        assert path_dict["stop_flag"] == flag_str and run_queue.get_stop_flag_bool(path_dict) is False
        sent_list = []
        send_func = lambda *args_in: sent_list.append(args_in[2]) or {"sent_bool": True, "detail": ""}
        pending_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "waits", git_func_in=CLEAN_GIT_FUNC)
        crashed_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "crashed", git_func_in=CLEAN_GIT_FUNC)
        run_queue.claim_job_dict(path_dict, crashed_dict, lambda: FAKE_JUDGE_STR)
        running_path_str = os.path.join(path_dict["running"], f"{crashed_dict['job_id']}.json")
        running_before_str = Path(running_path_str).read_text(encoding="utf-8")
        # SET: NOTHING STARTS, NOTHING IS TOUCHED, THE STATE SAYS SO
        os.makedirs(os.path.dirname(flag_str))
        Path(flag_str).write_text("stop", encoding="utf-8")
        assert run_queue.get_stop_flag_bool(path_dict) is True
        called_list = []
        def run_func(job_dict_in, run_id_str_in, log_path_str_in):
            called_list.append(job_dict_in["note"])
            return get_fake_run_func(path_dict, False)(job_dict_in, run_id_str_in, log_path_str_in)
        assert run_fake_queue_list(path_dict, run_func, send_func) == [] and called_list == []
        assert Path(running_path_str).read_text(encoding="utf-8") == running_before_str
        assert os.path.isfile(os.path.join(path_dict["pending"], f"{pending_dict['job_id']}.json"))
        assert run_queue.read_json(path_dict["state"])["stopped"] is True
        assert run_queue.watch_queue(path_dict, 0, 2, run_func, send_func, judge_func_in=lambda: FAKE_JUDGE_STR,
                                     git_func_in=fake_accepting_git_func, prepare_func_in=lambda job_in: FAKE_RUN_COMMIT_STR) == 0
        assert called_list == [] and run_queue.read_json(path_dict["state"])["stopped"] is True
        # REMOVED: THE INTERRUPTED JOB RESUMES FIRST, THEN THE PENDING ONE
        os.remove(flag_str)
        result_list = run_fake_queue_list(path_dict, run_func, send_func)
        assert called_list == ["crashed", "waits"] and [result["status"] for result in result_list] == ["done", "done"]
        assert run_queue.read_json(path_dict["state"])["stopped"] is False
        # FAILS CLOSED: A FLAG THAT CANNOT BE CHECKED COUNTS AS SET
        real_stat_func = os.stat
        def denying_stat_func(path_in, *args_in, **kwarg_dict_in):
            if str(path_in) == flag_str:
                raise PermissionError(13, "Access is denied")
            return real_stat_func(path_in, *args_in, **kwarg_dict_in)
        os.stat = denying_stat_func
        try:
            assert run_queue.get_stop_flag_bool(path_dict) is True
        finally:
            os.stat = real_stat_func
        assert run_queue.get_stop_flag_bool({"stop_flag": os.path.join(control_str, "no_such_folder", "STOP")}) is False
        assert run_queue.get_stop_flag_bool({"stop_flag": ""}) is False and run_queue.get_stop_flag_bool({}) is False
    finally:
        os.environ.pop("SO_STOP_FLAG_PATH", None)
    # THE DEFAULT PLACE IS <SO_DATA_PATH>/control/STOP
    assert run_queue.get_stop_flag_path_str() == os.path.join(os.environ["SO_DATA_PATH"], "control", "STOP")
    passed("kill switch (no job starts or resumes while STOP exists, state says stopped, work resumes after removal, unreadable flag counts as set)")


# RUN THE SUITE
if __name__ == "__main__":
    test_queue_runs_files_and_emails()
    test_queue_rejects_bad_pending_files()
    test_queue_claim_resume_and_give_up()
    test_queue_heartbeat_and_child_environment()
    test_queue_judge_from_main_run_commit()
    test_queue_run_index_upgrade()
    test_run_email_content()
    test_queue_kill_switch()
    test_every_python_file_compiles()
    test_queue_timeout_kills_tree()
    test_queue_worktree_and_results_rows()
    test_email_outbox_and_smtp()
    test_protected_paths()
    test_notebooks_without_outputs()
    test_environment_lock()
    test_ledger_outside_repository()
    print("\nAll tool tests passed ✅")
