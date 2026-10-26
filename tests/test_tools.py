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
        return status_str_in if arg_list_in[0] == "status" else "c0ffee\n"
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
        run_queue.add_job_dict(path_dict, DESIGN_STR, "dirty", git_func_in=get_git_func(" M so/config.py\n"))
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
    assert first_dict["commit"] == "c0ffee" and first_dict["attempt"] == 1
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
    result_list = run_queue.run_queue_list(path_dict, run_func, send_func)
    assert order_list == ["first", "second"]
    assert [result["status"] for result in result_list] == ["done", "done"]
    assert sent_list == ["Stock Overflow: exp13_e1m1_robustness is email-worthy"]
    assert result_list[0]["results_row"].startswith("| row of exp13_e1m1_robustness_")
    assert result_list[1]["email"] is None
    assert not os.listdir(path_dict["pending"]) and len(os.listdir(path_dict["done"])) == 2
    assert not os.path.exists(path_dict["lock"])
    state_dict = run_queue.read_json(path_dict["state"])
    assert state_dict["running"] is None and state_dict["pending_count"] == 0
    assert [row["note"] for row in state_dict["recent"]] == ["second", "first"]
    # A FAILING RUN EMAILS AND IS FILED; A RETRY KEEPS ITS RUN ID AND COUNTS THE ATTEMPT
    third_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "third", git_func_in=CLEAN_GIT_FUNC)
    failed_list = run_queue.run_queue_list(path_dict, get_fake_run_func(path_dict, True, 1), send_func)
    assert failed_list[0]["status"] == "failed" and failed_list[0]["log_tail"][-1] == "ValueError: boom"
    assert len(os.listdir(path_dict["failed"])) == 1 and sent_list[-1].endswith("run failed")
    retry_dict = run_queue.add_retry_job_dict(path_dict, third_dict["job_id"])
    assert retry_dict["run_id"] == failed_list[0]["run_id"] and retry_dict["attempt"] == 2
    retry_result_list = run_queue.run_queue_list(path_dict, get_fake_run_func(path_dict, False), send_func)
    assert retry_result_list[0]["run_id"] == failed_list[0]["run_id"] and retry_result_list[0]["status"] == "done"
    # THE RUN INDEX HAS ONE ROW PER ATTEMPT
    import pandas as pd
    index_pdf = pd.read_csv(path_dict["run_index"], dtype=str)
    assert list(index_pdf["status"]) == ["done", "done", "failed", "done"], list(index_pdf["status"])
    assert list(index_pdf["attempt"]) == ["1", "1", "1", "2"] and set(index_pdf["commit"]) == {"c0ffee"}
    passed("queue (commit pinned, dirty clone refused, oldest first, filing, failure email, retry under the same run id, run index)")
    # A SECOND RUNNER IS REFUSED WHILE A LIVE LOCK EXISTS; A STALE LOCK (DEAD PROCESS, SAME HOST) IS REPLACED
    import socket
    Path(path_dict["lock"]).write_text(json.dumps({"pid": 4242, "host": socket.gethostname()}), encoding="utf-8")
    try:
        run_queue.run_queue_list(path_dict, run_func, send_func, pid_alive_func_in=lambda pid_in: True)
        raise AssertionError("a second runner started")
    except SystemExit as error:
        assert "another queue runner" in str(error)
    assert run_queue.run_queue_list(path_dict, run_func, send_func, pid_alive_func_in=lambda pid_in: False) == []
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


# RUN THE SUITE
if __name__ == "__main__":
    test_queue_runs_files_and_emails()
    test_every_python_file_compiles()
    test_queue_timeout_kills_tree()
    test_queue_worktree_and_results_rows()
    test_email_outbox_and_smtp()
    test_protected_paths()
    test_notebooks_without_outputs()
    test_environment_lock()
    test_ledger_outside_repository()
    print("\nAll tool tests passed ✅")
