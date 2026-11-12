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
# THE WINDOWS UPDATE GUARD READS THE MACHINE'S REGISTRY (2026-11-11); THESE TESTS REPLACE IT WITH A SAFE ONE, AND
# test_queue_windows_update_guard TESTS THE REAL GUARD WITH FAKE READERS
SAFE_UPDATE_GUARD_FUNC = lambda: {"safe_bool": True, "reason_str": "test", "pause_end_str": None, "days_left": None}
run_queue.UPDATE_GUARD_FUNC = SAFE_UPDATE_GUARD_FUNC
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
    assert [row["job_id"] for row in state_dict["recent"]] == [second_dict["job_id"], first_dict["job_id"]]
    assert all(set(row) == {"job_id", "run_id", "status"} and row["status"] == "ran" for row in state_dict["recent"])
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
    assert len(state_recent_list) == 7 and all(row["status"] == "rejected" and "reason" not in row for row in state_recent_list)
    # THE REASON REACHES THE AGENT THROUGH ITS STATUS FILE (ROADMAP R4), NOT state.json
    status_name_list = sorted(os.listdir(path_dict["status"]))
    assert len(status_name_list) == 7 and all(run_queue.read_json(os.path.join(path_dict["status"], name_str))["status"] == "rejected"
                                              and run_queue.read_json(os.path.join(path_dict["status"], name_str))["reason"]
                                              for name_str in status_name_list)
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
        "print('results_row | ok |')\n"
        "if os.environ.get('SO_TEST_TAMPER') == '1':\n"
        "    Path('so/helper.py').write_text('tampered\\n')\n")
    write_file("protected_paths.txt", "so/**\nscripts/**\n")
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
    # THE JUDGE COMMIT OF A NEW JOB: THE LOCAL REF refs/deployed, NO FETCH; THE REF CAN BE CHANGED
    call_list = []
    def fake_git_func(arg_list_in, **kwarg_dict_in):
        call_list.append(list(arg_list_in))
        return FAKE_JUDGE_STR + "\n"
    assert run_queue.get_judge_commit_str(fake_git_func) == FAKE_JUDGE_STR and call_list[-1][-1] == "refs/deployed^{commit}"
    assert not any(call[0] == "fetch" for call in call_list)
    os.environ["SO_QUEUE_JUDGE_REF"] = "refs/other"
    try:
        run_queue.get_judge_commit_str(fake_git_func)
    finally:
        os.environ.pop("SO_QUEUE_JUDGE_REF", None)
    assert call_list[-1][-1] == "refs/other^{commit}"
    # A MERGE TO main WITHOUT A DEPLOY CHANGES NO JUDGE: main IS AT judge2, refs/deployed AT judge1
    try:
        run_queue.get_judge_commit_str(git_func)
        raise AssertionError("a judge resolved before anything was deployed")
    except run_queue.NoDeployedJudgeError:
        pass
    assert run_queue.get_deployed_commit_str(git_func) == ""
    git_func(["update-ref", "refs/deployed", commit_dict["judge1"]])
    assert git_func(["rev-parse", "main"]).strip() == commit_dict["judge2"]
    assert run_queue.get_judge_commit_str(git_func) == commit_dict["judge1"]
    assert run_queue.get_deployed_commit_str(git_func) == commit_dict["judge1"]
    git_func(["update-ref", "refs/deployed", commit_dict["judge2"]])
    assert run_queue.get_judge_commit_str(git_func) == commit_dict["judge2"]
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
    assert len(result_list[0]["judge_hash_before"]) == 64 and result_list[0]["judge_hash_after"] == result_list[0]["judge_hash_before"]
    assert result_list[0]["judge_problem"] is None
    # DESIGN CODE THAT CHANGES A JUDGE FILE DURING THE RUN: THE RUN IS FILED AS FAILED, WITH THE REASON
    tamper_job_dict = get_valid_job_dict("00000c", {"design": "experiments/exp_a", "commit": commit_dict["design"]})
    run_queue.write_job_file(os.path.join(path_dict["pending"], f"{tamper_job_dict['job_id']}.json"), tamper_job_dict)
    environment_update_dict = {"SO_QUEUE_WORKTREE_ROOT": worktree_root_str, "SO_TEST_RUNS_PATH": path_dict["runs"],
                               "SO_TEST_TAMPER": "1"}
    os.environ.update(environment_update_dict)
    try:
        tamper_list = run_queue.run_queue_list(
            path_dict, lambda job_in, run_id_in, log_in: run_queue.run_development_process_dict(job_in, run_id_in, log_in, git_func),
            lambda *args_in: {"sent_bool": True, "detail": ""}, judge_func_in=lambda: commit_dict["judge2"], git_func_in=git_func)
    finally:
        for name_str in environment_update_dict:
            os.environ.pop(name_str, None)
    assert len(tamper_list) == 1 and tamper_list[0]["status"] == "failed", tamper_list
    assert "judge changed during the run" in tamper_list[0]["judge_problem"], tamper_list[0]
    assert tamper_list[0]["judge_hash_after"] != tamper_list[0]["judge_hash_before"]
    assert any("judge changed" in line_str for line_str in tamper_list[0]["log_tail"])
    # THE REPORT'S JUDGE MUST MATCH TOO; NOTHING MEASURED, NOTHING COMPARED
    same_str = "a" * 64
    assert run_queue.get_judge_problem_str({"judge_hash_before": same_str, "judge_hash_after": same_str}, same_str) == ""
    assert "report judge" in run_queue.get_judge_problem_str({"judge_hash_before": same_str, "judge_hash_after": same_str}, "b" * 64)
    assert run_queue.get_judge_problem_str({}, "b" * 64) == ""
    passed("judge hash before and after every run (a design that changes a judge file fails the run; the report's hash "
           "must match)")
    passed("judge = the deployed commit (refs/deployed, not main: a merge without a deploy changes nothing; run commit = "
           "the judge's tree + the job's experiments/, deterministic, parents kept by refs/runs; "
           "outside changes, links and missing experiments/ refused; clean worktree, no secrets, removed afterwards)")


# FUNCTION: WITHOUT A DEPLOYED JUDGE NO JOB STARTS; EACH PASS FETCHES BEFORE IT VALIDATES
def test_queue_waits_for_deployed_judge():
    """
    Returns:
        None
    """
    # A PENDING JOB, NO DEPLOYED JUDGE: IT STAYS PENDING, NOTHING IS CLAIMED OR RUN
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    job_dict = get_valid_job_dict("00000d")
    run_queue.write_job_file(os.path.join(path_dict["pending"], f"{job_dict['job_id']}.json"), job_dict)
    def no_judge_func():
        raise run_queue.NoDeployedJudgeError("no deployed judge (test)")
    run_list = []
    result_list = run_fake_queue_list(path_dict, lambda *args_in: run_list.append(args_in), lambda *args_in: None,
                                      judge_func_in=no_judge_func)
    assert result_list == [] and run_list == []
    assert os.listdir(path_dict["pending"]) == [f"{job_dict['job_id']}.json"] and not os.listdir(path_dict["running"])
    state_dict = run_queue.read_json(path_dict["state"])
    assert "deployed_commit" in state_dict and state_dict["pending_count"] == 1
    # ONCE DEPLOYED, THE SAME JOB RUNS UNDER THAT JUDGE; THE FETCH COMES BEFORE THE FIRST EXISTENCE CHECK
    call_list = []
    def recording_git_func(arg_list_in, **kwarg_dict_in):
        call_list.append(list(arg_list_in))
        return ""
    def fake_run_func(job_in, run_id_in, log_in):
        Path(log_in).write_text("ok\n", encoding="utf-8")
        return {"return_code": 1, "log_line_list": ["ok"], "timed_out_bool": False}
    result_list = run_fake_queue_list(path_dict, fake_run_func, lambda *args_in: {"sent_bool": False, "detail": ""},
                                      git_func_in=recording_git_func)
    assert len(result_list) == 1 and result_list[0]["judge_commit"] == FAKE_JUDGE_STR
    first_fetch_int = next(index for index, call in enumerate(call_list) if call[0] == "fetch")
    first_check_int = next(index for index, call in enumerate(call_list) if call[0] == "cat-file")
    assert first_fetch_int < first_check_int, call_list
    passed("no deployed judge: pending jobs wait, nothing is claimed; after a deploy the job runs under it; each pass "
           "fetches origin before it validates pending files")


# FUNCTION: A REPLACE BLOCKED FOR A MOMENT IS RETRIED; ONE FAILED WATCH LOOP DOES NOT STOP THE WATCH (R3)
def test_queue_windows_robustness():
    """
    Returns:
        None
    """
    # os.replace FAILS TWICE WITH PermissionError (A READER HOLDS THE FILE), THEN WORKS
    target_str = os.path.join(tempfile.mkdtemp(prefix="so_replace_"), "state.json")
    real_replace = os.replace
    fail_list = [PermissionError("held by a reader"), PermissionError("held by a reader")]
    def flaky_replace(source_in, target_in):
        if fail_list:
            raise fail_list.pop(0)
        return real_replace(source_in, target_in)
    old_seconds = run_queue.REPLACE_RETRY_SECONDS
    run_queue.os.replace, run_queue.REPLACE_RETRY_SECONDS = flaky_replace, 0.0
    try:
        run_queue.write_json_atomic(target_str, {"a": 1})
        assert run_queue.read_json(target_str) == {"a": 1} and not fail_list
        # ALWAYS BLOCKED: IT RAISES AFTER THE RETRIES AND LEAVES NO TEMPORARY FILE
        def blocked_replace(source_in, target_in):
            raise PermissionError("held")
        run_queue.os.replace = blocked_replace
        try:
            run_queue.write_json_atomic(target_str, {"a": 2})
            raise AssertionError("a permanently blocked replace was accepted")
        except PermissionError:
            pass
        assert os.listdir(os.path.dirname(target_str)) == ["state.json"]
    finally:
        run_queue.os.replace, run_queue.REPLACE_RETRY_SECONDS = real_replace, old_seconds
    # THE WATCH: THE FIRST LOOP RAISES, THE SECOND RUNS THE JOB
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    job_dict = get_valid_job_dict("00000e")
    run_queue.write_job_file(os.path.join(path_dict["pending"], f"{job_dict['job_id']}.json"), job_dict)
    real_run_queue_list = run_queue.run_queue_list
    call_list = []
    def flaky_run_queue_list(*arg_tuple_in, **kwarg_dict_in):
        call_list.append(1)
        if len(call_list) == 1:
            raise OSError("a locked file (test)")
        return real_run_queue_list(*arg_tuple_in, **kwarg_dict_in)
    def fake_run_func(job_in, run_id_in, log_in):
        Path(log_in).write_text("ok\n", encoding="utf-8")
        return {"return_code": 1, "log_line_list": ["ok"], "timed_out_bool": False}
    run_queue.run_queue_list = flaky_run_queue_list
    try:
        job_count_int = run_queue.watch_queue(path_dict, 0, 2, fake_run_func, lambda *args_in: {"sent_bool": False, "detail": ""},
                                              judge_func_in=lambda: FAKE_JUDGE_STR, git_func_in=fake_accepting_git_func,
                                              prepare_func_in=lambda job_in: FAKE_RUN_COMMIT_STR)
    finally:
        run_queue.run_queue_list = real_run_queue_list
    assert len(call_list) == 2 and job_count_int == 1 and not os.listdir(path_dict["pending"])
    passed("Windows robustness: a replace blocked by a reader is retried (and fails cleanly when it never clears); "
           "a failed watch loop is logged and the next loop runs the job")


# FUNCTION: THE TAIL-CHECK SCRIPT REPRODUCES THE BASELINE'S RANDOM DRAWS (R3, AUDIT S4)
def test_random_timing_tail_script():
    """
    Returns:
        None
    """
    # SYNTHETIC BARS, AN EXPOSURE PATH WITH A FEW CASH SPELLS, THE REFEREE'S OWN BASELINE AS THE REFERENCE
    import numpy as np
    import pandas as pd
    import check_random_timing_tail as tail_script
    from so.core.trade_execution import get_ohlcv_array_dict
    from so.runner.baselines import get_runner_baseline_dict, get_random_timing_seed_list
    from synthetic_data import get_synthetic_ohlcv_pdf
    ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2010-06-01", "2010-08-31", seed_in=7))
    session_list = list(ohlcv_array_dict["session_date_list"])
    date1, date2 = session_list[0], session_list[-1]
    in_position_arr = np.ones(len(session_list), dtype=bool)
    in_position_arr[[5, 6, 7, 20, 21, 40, 41, 42, 43]] = False
    prior_only_dict = {"daily_equity_pdf": pd.DataFrame({"in_position": in_position_arr}), "metric_dict": {"total_return": 0.01}}
    baseline_dict = get_runner_baseline_dict(ohlcv_array_dict, date1, date2, prior_only_dict, seed_count_int_in=6,
                                             realized_exposure_bool_in=True)
    exposure_arr = in_position_arr.astype(float)
    exposure_arr[-1] = np.nan
    seed_list = get_random_timing_seed_list(6)
    script_list = tail_script.get_draw_return_list(seed_list, ohlcv_array_dict, date1, date2, exposure_arr, 1)
    assert np.allclose(script_list, baseline_dict["random_timing_return_list"], rtol=0, atol=1e-12)
    pool_list = tail_script.get_draw_return_list(seed_list, ohlcv_array_dict, date1, date2, exposure_arr, 2)
    assert np.allclose(pool_list, script_list, rtol=0, atol=1e-12)
    # THE SUMMARY: A NORMAL SAMPLE GIVES ABOUT THE EXPECTED EXCEEDANCES; A HEAVY RIGHT TAIL GIVES MANY MORE
    rng = np.random.default_rng(1)
    normal_dict = tail_script.get_tail_summary_dict(list(rng.normal(0.0, 1.0, 20000)), 0.5, 20)
    assert normal_dict["draws_at_or_above_critical"] <= 1.5 * normal_dict["draws_at_or_above_critical_expected"] + 10
    heavy_dict = tail_script.get_tail_summary_dict(list(rng.standard_t(2, 20000)), 0.5, 20)
    assert heavy_dict["draws_at_or_above_critical"] > 2 * heavy_dict["draws_at_or_above_critical_expected"]
    assert "Draws at or above it" in tail_script.get_tail_markdown_str("r", heavy_dict, {"registered_count": 6, "max_abs_difference": 0.0})
    passed("tail-check script: reproduces the referee's random-timing draws (in process and with worker processes); "
           "its summary flags a heavy right tail and not a normal one")


# FUNCTION: THE DEFLATED-SHARPE TAIL SCRIPT REPRODUCES THE DRAWS, COUNTS AS DESIGNED, AND REBUILDS ON THE REPORT'S BASIS
def test_deflated_sharpe_tail_script():
    """
    Returns:
        None
    """
    # THE SAME SYNTHETIC SETUP AS THE RANDOM-TIMING TAIL TEST
    import numpy as np
    import pandas as pd
    import check_deflated_sharpe_tail as dsr_script
    import check_random_timing_tail as tail_script
    from so.core.trade_execution import get_ohlcv_array_dict
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    from so.runner.baselines import get_runner_baseline_dict, get_random_timing_seed_list
    from so.runner.verdict import get_equity_daily_return_pdf
    from so.runner.total_return import TOTAL_RETURN_BASIS_STR, PRICE_ONLY_BASIS_STR
    from synthetic_data import get_synthetic_ohlcv_pdf
    ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2010-01-04", "2010-12-31", seed_in=7))
    session_list = list(ohlcv_array_dict["session_date_list"])
    date1, date2 = session_list[0], session_list[-1]
    in_position_arr = np.ones(len(session_list), dtype=bool)
    in_position_arr[[5, 6, 7, 60, 61, 140, 141, 142, 143, 200]] = False
    prior_only_dict = {"daily_equity_pdf": pd.DataFrame({"in_position": in_position_arr}), "metric_dict": {"total_return": 0.01}}
    baseline_dict = get_runner_baseline_dict(ohlcv_array_dict, date1, date2, prior_only_dict, seed_count_int_in=4,
                                             realized_exposure_bool_in=True)
    exposure_arr = in_position_arr.astype(float)
    exposure_arr[-1] = np.nan
    buy_hold_return_pdf = get_equity_daily_return_pdf(get_buy_and_hold_result_dict(ohlcv_array_dict, date1, date2)["daily_equity_pdf"])
    seed_list = get_random_timing_seed_list(4)
    draw_list = dsr_script.get_draw_tuple_list(seed_list, ohlcv_array_dict, date1, date2, exposure_arr, buy_hold_return_pdf, 1)
    assert np.allclose([draw[0] for draw in draw_list], baseline_dict["random_timing_return_list"], rtol=0, atol=1e-12)
    assert all(len(draw[1]) == 4 for draw in draw_list)
    pool_list = dsr_script.get_draw_tuple_list(seed_list, ohlcv_array_dict, date1, date2, exposure_arr, buy_hold_return_pdf, 2)
    assert np.allclose(np.asarray([draw[1] for draw in pool_list]), np.asarray([draw[1] for draw in draw_list]), rtol=0, atol=1e-12)
    # THE COUNT: AT N = 1 THE DSR IS THE PROBABILISTIC SHARPE RATIO, SO NORMAL NOISE PASSES ABOUT 5% OF THE TIME; A LARGE
    # COMMON HANDICAP STOPS EVERY RAW DRAW BUT NOT THE CENTERED ONES
    rng = np.random.default_rng(3)
    noise_matrix = rng.normal(0.0, 0.05, (4000, 80))
    count_dict = dsr_script.get_count_dict(noise_matrix - 0.05, 1.0 / 80, 1, 0.05)
    assert count_dict["expected_count"] == 200.0 and count_dict["raw_count"] == 0
    assert 100 <= count_dict["centered_count"] <= 400, count_dict
    # THE REPORT'S BASIS: A REPORT WITHOUT ONE (BEFORE R4b) IS REBUILT ON PRICE RETURNS; A TOTAL-RETURN REPORT ON THE BUNDLE AS IT IS
    scheduled_dict = {**ohlcv_array_dict, "dividend_per_share_arr": np.full(len(session_list), 0.1),
                      "cash_growth_arr": np.full(len(session_list), 0.0001), "total_return_basis_str": TOTAL_RETURN_BASIS_STR}
    old_dict, old_basis_str = tail_script.get_report_basis_bundle_dict(scheduled_dict, {})
    assert old_basis_str == PRICE_ONLY_BASIS_STR and not old_dict["dividend_per_share_arr"].any() and not old_dict["cash_growth_arr"].any()
    new_dict, new_basis_str = tail_script.get_report_basis_bundle_dict(scheduled_dict, {"return_basis_str": TOTAL_RETURN_BASIS_STR})
    assert new_basis_str == TOTAL_RETURN_BASIS_STR and new_dict is scheduled_dict
    markdown_str = dsr_script.get_markdown_str("r", {"return_basis_str": "price_only", "draw_count": 4000, "quarter_count": 80,
                                                     "rebuilt_return": 0.1, "registered_count": 100, "max_abs_difference": 0.0,
                                                     "report_dsr": 0.01, "report_design_count": 1, "trial_sharpe_variance": 0.0125,
                                                     "trial_sharpe_variance_source_str": "null_1_over_T", "count_list": [count_dict]})
    assert "centered / expected" in markdown_str
    passed("deflated-Sharpe tail script: reproduces the referee's draws (in process and with workers); at N = 1 normal noise "
           "passes about 5%; centering removes a common handicap; old reports are rebuilt on price returns")


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
    assert "audit" not in body_str and "pilot included" not in body_str         # A REPORT WITHOUT THE N SCOPE (BEFORE 2026-11-10)
    Path(path_dict["runs"], "run_s").mkdir()
    Path(path_dict["runs"], "run_s", "report.json").write_text(json.dumps({
        "multiple_testing_dict": {"design_count": 260, "design_count_scope_str": "pilot_included", "current_design_count": 18}}),
        encoding="utf-8")
    scope_body_str = run_queue.get_finished_run_email_tuple(path_dict, {**result_dict, "run_id": "run_s"}, negative_dict)[1]
    assert "Designs tried (the multiple-testing N) 260 (pilot included; 18 in the trial log)" in scope_body_str, scope_body_str
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
        # THE IDLE LOOP UNDER STOP WRITES NOTHING (R4d, 2026-11-12): A RESET MOVES state.json AND FOLDERS; THEY STAY GONE
        import shutil as shutil_module
        os.remove(path_dict["state"])
        shutil_module.rmtree(path_dict["outbox"], ignore_errors=True)
        run_queue.watch_queue(path_dict, 0, 2, run_func, send_func, judge_func_in=lambda: FAKE_JUDGE_STR,
                              git_func_in=fake_accepting_git_func, prepare_func_in=lambda job_in: FAKE_RUN_COMMIT_STR)
        assert not os.path.exists(path_dict["state"]) and not os.path.exists(path_dict["outbox"]) and called_list == []
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
    passed("kill switch (no job starts or resumes while STOP exists, state says stopped, the idle loop writes nothing, work resumes after removal, unreadable flag counts as set)")


# CLASS: A FAKE REGISTRY FOR THE WINDOWS UPDATE GUARD
class FakeRegistryReader:
    """values: name -> value (a missing name raises FileNotFoundError); keys: existing restart keys; error: raised by
    every read when set."""

    def __init__(self, value_dict_in, key_set_in=None, error_in=None):
        self.value_dict = dict(value_dict_in)
        self.key_set = set(key_set_in or [])
        self.error = error_in

    def get_value(self, key_str_in, name_str_in):
        if self.error is not None:
            raise self.error
        if name_str_in not in self.value_dict:
            raise FileNotFoundError(name_str_in)
        return self.value_dict[name_str_in]

    def has_key(self, key_str_in):
        if self.error is not None:
            raise self.error
        return key_str_in in self.key_set


# FUNCTION: THE WINDOWS UPDATE GUARD (2026-11-11)
def test_queue_windows_update_guard():
    """
    The guard is safe only with every pause value readable, at least 3 days left on the earliest one, and no pending
    restart; anything unreadable is not safe; off Windows it is not applicable. add refuses while it is not safe; the
    runner starts and resumes no job; the watch emails once per reason and state.json shows the guard.

    Returns:
        None
    """
    # THE GUARD ITSELF, WITH FAKE READERS (THE FORMAT OF nicodesktop ON 2026-11-11)
    import datetime as datetime_module
    now_utc = datetime_module.datetime(2026, 11, 11, 14, 0, tzinfo=datetime_module.timezone.utc)
    paused_dict = {name_str: "2026-11-30T13:59:06Z" for name_str in run_queue.UPDATE_PAUSE_VALUE_LIST}
    safe_dict = run_queue.get_update_guard_dict(FakeRegistryReader(paused_dict), now_utc)
    assert safe_dict["safe_bool"] is True and safe_dict["pause_end_str"] == "2026-11-30T13:59:06+00:00"
    # 18.9994 DAYS, ROUNDED TO TWO DECIMALS = 19.0 (THE FIRST RUN ON nicodesktop USED < 19.0 AND FAILED, 2026-11-12)
    assert 18.9 < safe_dict["days_left"] <= 19.0
    late_now = datetime_module.datetime(2026, 11, 28, 0, 0, tzinfo=datetime_module.timezone.utc)
    late_dict = run_queue.get_update_guard_dict(FakeRegistryReader(paused_dict), late_now)
    assert late_dict["safe_bool"] is False and "ends 2026-11-30" in late_dict["reason_str"]
    early_dict = dict(paused_dict, PauseQualityUpdatesEndTime="2026-11-12T00:00:00Z")
    assert run_queue.get_update_guard_dict(FakeRegistryReader(early_dict), now_utc)["safe_bool"] is False
    missing_dict = {key_str: value for key_str, value in paused_dict.items() if key_str != "PauseUpdatesExpiryTime"}
    missing_guard = run_queue.get_update_guard_dict(FakeRegistryReader(missing_dict), now_utc)
    assert missing_guard["safe_bool"] is False and "not paused" in missing_guard["reason_str"]
    restart_reader = FakeRegistryReader(paused_dict, {run_queue.UPDATE_RESTART_KEY_LIST[0]})
    restart_dict = run_queue.get_update_guard_dict(restart_reader, now_utc)
    assert restart_dict["safe_bool"] is False and "restart is pending" in restart_dict["reason_str"]
    denied_dict = run_queue.get_update_guard_dict(FakeRegistryReader(paused_dict, error_in=PermissionError(13, "denied")), now_utc)
    assert denied_dict["safe_bool"] is False and "cannot read" in denied_dict["reason_str"]
    garbled_dict = run_queue.get_update_guard_dict(FakeRegistryReader(dict(paused_dict, PauseUpdatesExpiryTime="soon")), now_utc)
    assert garbled_dict["safe_bool"] is False and "cannot read" in garbled_dict["reason_str"]
    no_zone_dict = run_queue.get_update_guard_dict(FakeRegistryReader(dict(paused_dict, PauseUpdatesExpiryTime="2026-11-30T13:59:06")), now_utc)
    assert no_zone_dict["safe_bool"] is False
    assert run_queue.get_update_guard_dict(platform_str_in="linux")["safe_bool"] is True
    # A GUARD THAT CRASHES IS NOT SAFE
    def crashing_guard_func():
        raise RuntimeError("boom")
    run_queue.UPDATE_GUARD_FUNC = crashing_guard_func
    try:
        assert run_queue.get_checked_update_guard_dict()["safe_bool"] is False
    finally:
        run_queue.UPDATE_GUARD_FUNC = SAFE_UPDATE_GUARD_FUNC
    # THE QUEUE: add REFUSES, THE RUNNER WAITS, THE WATCH EMAILS ONCE, THE STATE SHOWS IT
    zone_str = tempfile.mkdtemp(prefix="so_zone_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    run_queue.make_runner_folder_list(path_dict)
    pending_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "waits", git_func_in=CLEAN_GIT_FUNC)
    unsafe_dict = {"safe_bool": False, "reason_str": "the Windows Update pause ends 2026-11-30T13:59:06+00:00 (1.0 days; at least 3 needed)",
                   "pause_end_str": None, "days_left": 1.0}
    run_queue.UPDATE_GUARD_FUNC = lambda: dict(unsafe_dict)
    try:
        try:
            run_queue.add_job_dict(path_dict, DESIGN_STR, "refused", git_func_in=CLEAN_GIT_FUNC)
            raise AssertionError("add accepted a job while the guard was not safe")
        except ValueError as error:
            assert "not adding the job" in str(error) and "Pause updates" in str(error)
        called_list, guard_mail_list = [], []
        def run_func(job_dict_in, run_id_str_in, log_path_str_in):
            called_list.append(job_dict_in["note"])
            return get_fake_run_func(path_dict, False)(job_dict_in, run_id_str_in, log_path_str_in)
        send_func = lambda *args_in: {"sent_bool": True, "detail": ""}
        assert run_fake_queue_list(path_dict, run_func, send_func) == [] and called_list == []
        assert os.path.isfile(os.path.join(path_dict["pending"], f"{pending_dict['job_id']}.json"))
        state_dict = run_queue.read_json(path_dict["state"])
        assert state_dict["update_guard"] == {"safe_bool": False, "reason_str": unsafe_dict["reason_str"]}
        guard_send_func = lambda *args_in: guard_mail_list.append(args_in[2]) or {"sent_bool": True, "detail": ""}
        # THE DAYS LEFT CHANGE DURING THE WATCH, THE REASON DOES NOT: ONE EMAIL
        guard_call_list = []
        def changing_guard_func():
            guard_call_list.append(1)
            days_str = "1.0" if len(guard_call_list) <= 3 else "0.9"
            return dict(unsafe_dict, reason_str=unsafe_dict["reason_str"].replace("(1.0 days", f"({days_str} days"))
        run_queue.UPDATE_GUARD_FUNC = changing_guard_func
        assert run_queue.watch_queue(path_dict, 0, 4, run_func, send_func, judge_func_in=lambda: FAKE_JUDGE_STR,
                                     git_func_in=fake_accepting_git_func, prepare_func_in=lambda job_in: FAKE_RUN_COMMIT_STR,
                                     guard_send_func_in=guard_send_func) == 0
        assert len(guard_call_list) > 3, "the guard reason never changed during the watch"
        assert called_list == [] and len(guard_mail_list) == 1 and "Windows Update guard" in guard_mail_list[0]
    finally:
        run_queue.UPDATE_GUARD_FUNC = SAFE_UPDATE_GUARD_FUNC
    # SAFE AGAIN: THE JOB RUNS
    result_list = run_fake_queue_list(path_dict, run_func, send_func)
    assert called_list == ["waits"] and [result["status"] for result in result_list] == ["done"]
    assert run_queue.read_json(path_dict["state"])["update_guard"]["safe_bool"] is True
    passed("Windows Update guard (pause end, pending restart, unreadable or garbled values not safe; add refuses, the runner waits, the watch emails once per reason)")


# FUNCTION: FREEZING THE REFERENCE V (R4d, 2026-11-12)
def test_freeze_v_reference():
    """
    scripts/freeze_v_reference.py refuses without a confirmed kill switch, with a job running, or with SO_QUARANTINE_PATH
    set; a dry run writes nothing; a write keeps the previous file beside it and logs every build; the file reads back.

    Returns:
        None
    """
    # A TRIAL LOG OF SIX DESIGNS, A KILL SWITCH AND A RUNNING FOLDER OF ITS OWN
    import datetime as datetime_module
    import pandas as pd
    import freeze_v_reference
    from so.core.multiple_testing import read_v_reference_dict
    root_str = tempfile.mkdtemp(prefix="v_freeze_", dir=os.environ["SO_DATA_PATH"])
    row_list = []
    for idx in range(6):
        for fold_id in range(5):
            row_list.append({"trial_id": f"r_{idx}_{fold_id}", "logged_ts": "2026-11-11T01:00:00", "experiment": "expV",
                             "stage": "validation", "fold_id": fold_id,
                             "setting_json": json.dumps({"run_id": "run_a", "candidate": f"c{idx}"}),
                             "metric_json": json.dumps({"excess_return": 0.001 * idx + 0.002 * ((fold_id * 7 + idx) % 5)})})
    log_str = os.path.join(root_str, "trial_log.csv")
    pd.DataFrame(row_list).to_csv(log_str, index=False)
    flag_str = os.path.join(root_str, "control", "STOP")
    running_str = os.path.join(root_str, "running")
    os.makedirs(running_str)
    path_dict = {"stop_flag": flag_str, "running": running_str}
    reference_str = os.path.join(root_str, "judge", "v_reference.json")
    def freeze(confirm_bool_in, environment_dict_in=None, now_in=None):
        return freeze_v_reference.freeze_v_reference_dict(path_dict, confirm_bool_in, "test", log_str, reference_str,
                                                          environment_dict_in if environment_dict_in is not None else {},
                                                          now_in or datetime_module.datetime(2026, 11, 12, 17, 0, 0), "tester")
    refused_dict = freeze(True)
    assert "does not exist" in refused_dict["refused_str"] and not os.path.exists(reference_str)
    assert refused_dict["reference_dict"]["design_count"] == 6
    os.makedirs(os.path.dirname(flag_str))
    Path(flag_str).write_text("stop", encoding="utf-8")
    assert "SO_STOP_FLAG_PATH" in freeze(True, {"SO_STOP_FLAG_PATH": flag_str})["refused_str"]
    assert "SO_QUARANTINE_PATH" in freeze(True, {"SO_QUARANTINE_PATH": "x"})["refused_str"]
    Path(running_str, "job.json").write_text("{}", encoding="utf-8")
    assert "a job is running" in freeze(True)["refused_str"] and not os.path.exists(reference_str)
    os.remove(os.path.join(running_str, "job.json"))
    dry_dict = freeze(False)
    assert dry_dict["refused_str"] == "" and not dry_dict["done_bool"] and not os.path.exists(reference_str)
    first_dict = freeze(True)
    assert first_dict["done_bool"] and first_dict["replaced_path_str"] == ""
    assert read_v_reference_dict(reference_str)["content_sha256"] == first_dict["reference_dict"]["content_sha256"]
    second_dict = freeze(True, now_in=datetime_module.datetime(2026, 11, 13, 9, 30, 0))
    assert second_dict["done_bool"] and os.path.basename(second_dict["replaced_path_str"]) == "v_reference_20261112T170000.json"
    assert read_v_reference_dict(reference_str)["built_ts"] == "2026-11-13T09:30:00"
    assert read_v_reference_dict(second_dict["replaced_path_str"])["built_ts"] == "2026-11-12T17:00:00"
    log_pdf = pd.read_csv(os.path.join(root_str, "judge", freeze_v_reference.V_REFERENCE_LOG_NAME_STR), dtype=str)
    assert len(log_pdf) == 2 and list(log_pdf["replaced_file"].fillna("")) == ["", "v_reference_20261112T170000.json"]
    passed("freeze V reference (refused without a confirmed STOP, with a job running or a quarantine variable; dry run "
           "writes nothing; a write keeps the previous file and logs each build)")


# FUNCTION: THE WATCH WRITES ITS OWN LOG (ROADMAP R7, 2026-11-05)
def test_watch_log():
    """
    Lines printed by the watch reach the original stream and, stamped, queue/logs/runner_watch.log; a partial line waits
    for its end; past the size limit the log moves to .1 and a new one starts; an unwritable log never stops the watch.

    Returns:
        None
    """
    # A TEE ON A FAKE STREAM INSIDE A TEMPORARY QUEUE
    import io
    zone_str = tempfile.mkdtemp(prefix="watch_log_", dir=os.environ["SO_DATA_PATH"])
    path_dict = run_queue.get_queue_path_dict(zone_str)
    os.makedirs(path_dict["logs"], exist_ok=True)
    log_path_str = os.path.join(path_dict["logs"], run_queue.WATCH_LOG_FILE_STR)
    fake_stream = io.StringIO()
    tee = run_queue.WatchLogTee(fake_stream, log_path_str, max_bytes_in=200)
    tee.write("warning: watch loop failed (OSError: locked)\nhalf ")
    tee.write("line\n")
    tee.flush()
    assert fake_stream.getvalue() == "warning: watch loop failed (OSError: locked)\nhalf line\n"
    log_line_list = Path(log_path_str).read_text(encoding="utf-8").splitlines()
    assert len(log_line_list) == 2 and log_line_list[0].endswith(" warning: watch loop failed (OSError: locked)")
    assert log_line_list[1].endswith(" half line") and log_line_list[0][:4].isdigit() and "T" in log_line_list[0][:20]
    # ROTATION: ONE OLD COPY, A FRESH LOG
    for index_int in range(10):
        tee.write(f"heartbeat line {index_int} with some padding to grow the file\n")
    assert os.path.isfile(log_path_str + ".1") and os.path.getsize(log_path_str) < 400
    assert not os.path.exists(log_path_str + ".2")
    # AN UNWRITABLE LOG (A FOLDER IN ITS PLACE) AND A MISSING STREAM DO NOT RAISE
    bad_tee = run_queue.WatchLogTee(None, path_dict["logs"])
    assert bad_tee.write("still running\n") == len("still running\n")
    bad_tee.flush()
    passed("watch log (stamped lines in queue/logs/runner_watch.log, partial lines wait, rotation to .1, a broken log never stops the watch)")


# FUNCTION: THE EQUIVALENCE CHECK OF TWO RUNS (DESIGN 4.4, 2026-11-05)
def test_check_equivalence():
    """
    Two synthetic run folders: identical scoring numbers with different identities are equivalent; one changed number,
    one changed decision, a missing candidate or another experiment is not; a multiple-testing change with a different
    N is explained by N, the same change with the same N is not.

    Returns:
        None
    """
    # TWO RUN FOLDERS WITH A REPORT AND ONE CANDIDATE EACH
    import copy
    import pandas as pd
    import check_equivalence
    root_str = tempfile.mkdtemp(prefix="equivalence_", dir=os.environ["SO_DATA_PATH"])
    report_dict = {"run_id_str": "exp_a_1", "experiment_name_str": "exp_a", "protocol_version_str": "v1",
                   "commit_str": "a" * 40, "code_hash_str": "b" * 64, "judge_hash_str": "c" * 64, "judge_file_count": 40,
                   "trial_id_list": ["t1"], "date1": "2010-01-04", "date2": "2020-12-31", "label_str": "not email-worthy",
                   "email_worthy_bool": False, "failed_list": ["return"],
                   "return_dict": {"strategy_total_return": 0.4321, "pass_bool": False},
                   "look_ahead_dict": {"status_str": "pass", "elapsed_seconds": 12.5, "cut_date_list": ["2015-01-02"]},
                   "multiple_testing_dict": {"design_count": 300, "deflated_sharpe_probability": 0.41,
                                             "random_timing_tail_dict": {"draw_count": 1000}},
                   "view_stamp_dict": {"window_id": "w1", "built_ts": "2026-11-01T10:00:00"},
                   "grade_dict": {"grade_str": "Not better than buy-and-hold"},
                   "cost_sensitivity_list": [{"slippage_per_share": 0.0, "total_return": float("nan")}]}

    def make_run_str(name_str_in, report_in, decision_list_in, token_list_in=("c0",)):
        folder_str = os.path.join(root_str, name_str_in)
        for token_str in token_list_in:
            os.makedirs(os.path.join(folder_str, "candidates", token_str), exist_ok=True)
            pd.DataFrame({"date": ["2010-01-04", "2010-01-05"], "target": decision_list_in}).to_pickle(
                os.path.join(folder_str, "candidates", token_str, "decisions.pkl"))
            pd.Series([0.1, float("nan")]).to_pickle(os.path.join(folder_str, "candidates", token_str, "scores.pkl"))
        Path(folder_str, "report.json").write_text(json.dumps(report_in), encoding="utf-8")
        return folder_str

    baseline_str = make_run_str("base", report_dict, [1.0, 0.0])
    # ONLY IDENTITY CHANGED: EQUIVALENT
    same_dict = copy.deepcopy(report_dict)
    same_dict.update({"run_id_str": "exp_a_2", "commit_str": "d" * 40, "judge_hash_str": "e" * 64, "judge_file_count": 41,
                      "trial_id_list": ["t9"]})
    same_dict["look_ahead_dict"]["elapsed_seconds"] = 99.0
    same_dict["view_stamp_dict"]["built_ts"] = "2026-11-05T09:00:00"
    outcome_dict = check_equivalence.get_equivalence_dict(baseline_str, make_run_str("same", same_dict, [1.0, 0.0]))
    assert outcome_dict["equivalent_bool"], outcome_dict
    # ONE SCORING NUMBER, ONE DECISION, ONE CANDIDATE, ANOTHER EXPERIMENT: NOT EQUIVALENT
    number_dict = copy.deepcopy(same_dict)
    number_dict["return_dict"]["strategy_total_return"] = 0.4322
    outcome_dict = check_equivalence.get_equivalence_dict(baseline_str, make_run_str("number", number_dict, [1.0, 0.0]))
    assert not outcome_dict["equivalent_bool"]
    assert outcome_dict["scoring_difference_list"] == ["return_dict.strategy_total_return: 0.4321 -> 0.4322"]
    assert not check_equivalence.get_equivalence_dict(baseline_str, make_run_str("decision", same_dict, [1.0, 0.5]))["equivalent_bool"]
    missing_dict = check_equivalence.get_equivalence_dict(baseline_str, make_run_str("tokens", same_dict, [1.0, 0.0], ("c0", "c1")))
    assert not missing_dict["equivalent_bool"] and missing_dict["candidate_difference_list"] == ["candidates/c1: only in the new run"]
    window_dict = copy.deepcopy(same_dict)
    window_dict["view_stamp_dict"]["window_id"] = "w2"
    assert not check_equivalence.get_equivalence_dict(baseline_str, make_run_str("window", window_dict, [1.0, 0.0]))["equivalent_bool"]
    other_dict = copy.deepcopy(same_dict)
    other_dict["experiment_name_str"] = "exp_b"
    assert not check_equivalence.get_equivalence_dict(baseline_str, make_run_str("other", other_dict, [1.0, 0.0]))["equivalent_bool"]
    # A LARGER N: THE MULTIPLE-TESTING CHANGE IS EXPLAINED; THE SAME CHANGE WITH THE SAME N IS NOT
    n_dict = copy.deepcopy(same_dict)
    n_dict["multiple_testing_dict"].update({"design_count": 302, "deflated_sharpe_probability": 0.39})
    n_dict["grade_dict"]["grade_str"] = "Could be luck"
    outcome_dict = check_equivalence.get_equivalence_dict(baseline_str, make_run_str("n", n_dict, [1.0, 0.0]))
    assert outcome_dict["equivalent_bool"] and len(outcome_dict["n_difference_list"]) == 3 and outcome_dict["n_pair"] == (300, 302)
    same_n_dict = copy.deepcopy(same_dict)
    same_n_dict["multiple_testing_dict"]["deflated_sharpe_probability"] = 0.39
    assert not check_equivalence.get_equivalence_dict(baseline_str, make_run_str("same_n", same_n_dict, [1.0, 0.0]))["equivalent_bool"]
    # A V INPUT CHANGED (R4d; THE 2026-11-12 CASE: THE SAME N, MORE DESIGNS BEHIND V): ITS DEPENDENT FIELDS ARE EXPLAINED
    # BY V AND NAME THE INPUT; THE TRIAL LOG'S OWN COUNT IS INFORMATION; A RANDOM-TIMING CHANGE STAYS UNEXPLAINED
    v_base_dict = copy.deepcopy(report_dict)
    v_base_dict["multiple_testing_dict"].update({"trial_sharpe_design_count": 18, "current_design_count": 18,
                                                 "trial_sharpe_variance": 0.0117, "trial_sharpe_variance_source_str": "trial_log",
                                                 "dsr_pass_bool": False, "random_timing_p": 0.0045})
    v_baseline_str = make_run_str("v_base", v_base_dict, [1.0, 0.0])
    v_new_dict = copy.deepcopy(v_base_dict)
    v_new_dict.update({"run_id_str": "exp_a_3", "commit_str": "f" * 40})
    v_new_dict["multiple_testing_dict"].update({"trial_sharpe_design_count": 80, "current_design_count": 80,
                                                "trial_sharpe_variance": 0.0132, "deflated_sharpe_probability": 0.40})
    v_outcome_dict = check_equivalence.get_equivalence_dict(v_baseline_str, make_run_str("v_new", v_new_dict, [1.0, 0.0]))
    assert v_outcome_dict["equivalent_bool"], v_outcome_dict
    assert v_outcome_dict["v_input_list"] == ["trial_sharpe_design_count: 18 -> 80"]
    assert len(v_outcome_dict["v_difference_list"]) == 3 and len(v_outcome_dict["information_difference_list"]) == 1
    graded_dict = copy.deepcopy(v_new_dict)
    graded_dict["grade_dict"]["grade_str"] = "Could be luck"
    assert not check_equivalence.get_equivalence_dict(v_baseline_str, make_run_str("v_grade", graded_dict, [1.0, 0.0]))["equivalent_bool"]
    graded_dict["multiple_testing_dict"]["dsr_pass_bool"] = True
    assert check_equivalence.get_equivalence_dict(v_baseline_str, make_run_str("v_pass", graded_dict, [1.0, 0.0]))["equivalent_bool"]
    random_dict = copy.deepcopy(v_new_dict)
    random_dict["multiple_testing_dict"]["random_timing_p"] = 0.0046
    random_outcome_dict = check_equivalence.get_equivalence_dict(v_baseline_str, make_run_str("v_random", random_dict, [1.0, 0.0]))
    assert not random_outcome_dict["equivalent_bool"]
    assert random_outcome_dict["scoring_difference_list"] == ["multiple_testing_dict.random_timing_p: 0.0045 -> 0.0046"]
    no_input_dict = copy.deepcopy(v_base_dict)
    no_input_dict["multiple_testing_dict"]["trial_sharpe_variance"] = 0.0132
    assert not check_equivalence.get_equivalence_dict(v_baseline_str, make_run_str("v_none", no_input_dict, [1.0, 0.0]))["equivalent_bool"]
    passed("equivalence check (identities ignored, any scoring number, decision or candidate difference fails, N changes "
           "explained; V changes explained only with a changed V input, named; the trial log's own count is information)")


# RUN THE SUITE
if __name__ == "__main__":
    test_queue_runs_files_and_emails()
    test_queue_rejects_bad_pending_files()
    test_queue_claim_resume_and_give_up()
    test_queue_heartbeat_and_child_environment()
    test_queue_judge_from_main_run_commit()
    test_queue_waits_for_deployed_judge()
    test_queue_windows_robustness()
    test_random_timing_tail_script()
    test_deflated_sharpe_tail_script()
    test_queue_run_index_upgrade()
    test_run_email_content()
    test_queue_kill_switch()
    test_queue_windows_update_guard()
    test_freeze_v_reference()
    test_every_python_file_compiles()
    test_queue_timeout_kills_tree()
    test_queue_worktree_and_results_rows()
    test_email_outbox_and_smtp()
    test_protected_paths()
    test_notebooks_without_outputs()
    test_environment_lock()
    test_ledger_outside_repository()
    test_watch_log()
    test_check_equivalence()
    print("\nAll tool tests passed ✅")
