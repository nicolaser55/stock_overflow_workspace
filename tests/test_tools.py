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
    try:
        run_queue.add_job_dict(path_dict, "experiments/not_a_design")
        raise AssertionError("a folder without design.py was queued")
    except ValueError:
        pass
    first_dict = run_queue.add_job_dict(path_dict, DESIGN_STR, "first")
    second_dict = run_queue.add_job_dict(path_dict, DESIGN_STR + "/", "second")
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
    # A FAILING RUN
    run_queue.add_job_dict(path_dict, DESIGN_STR, "third")
    failed_list = run_queue.run_queue_list(path_dict, get_fake_run_func(path_dict, True, 1), send_func)
    assert failed_list[0]["status"] == "failed" and failed_list[0]["log_tail"][-1] == "ValueError: boom"
    assert len(os.listdir(path_dict["failed"])) == 1 and len(sent_list) == 1
    passed("queue (oldest first, done/failed filing, results row, email only when email-worthy, state.json)")
    # A SECOND RUNNER IS REFUSED WHILE THE LOCK EXISTS
    Path(path_dict["lock"]).write_text("1", encoding="utf-8")
    try:
        run_queue.run_queue_list(path_dict, run_func, send_func)
        raise AssertionError("a second runner started")
    except SystemExit as error:
        assert "another queue runner" in str(error)
    os.remove(path_dict["lock"])
    passed("queue lock (a second runner is refused)")


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
    for path_str in ["experiments/exp99_new/design.py", "so/features/rule_design.py", "tests/test_experiments.py", "docs/notes.md"]:
        assert not get_protected_bool(path_str, protected_dict["glob_list"]), path_str
    assert "docs/RESULTS_LOG.md" in protected_dict["append_list"]
    assert get_append_only_bool("--- a/x\n+++ b/x\n@@ -10,0 +11 @@\n+| new row |")
    assert not get_append_only_bool("--- a/x\n+++ b/x\n@@ -3 +3 @@\n-| old |\n+| edited |")
    # A BRANCH THAT CHANGES A GUARD, AN EXPERIMENT AND APPENDS A RESULT ROW
    output_dict = {"merge-base": "abc\n", "--name-only": "so/core/holdout.py\nexperiments/exp99_new/design.py\ndocs/RESULTS_LOG.md\n",
                   "ls-files": "records/new.csv\n", "-U0": "@@ -5,0 +6 @@\n+| row |\n"}
    def git_func(arg_list_in):
        for key_str, output_str in output_dict.items():
            if key_str in arg_list_in:
                return output_str
        raise AssertionError(arg_list_in)
    assert get_violation_list("main", git_func) == ["records/new.csv: protected", "so/core/holdout.py: protected"]
    passed("protected paths (guards covered, experiments free, RESULTS_LOG append-only)")


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


# RUN THE SUITE
if __name__ == "__main__":
    test_queue_runs_files_and_emails()
    test_email_outbox_and_smtp()
    test_protected_paths()
    test_environment_lock()
    test_ledger_outside_repository()
    print("\nAll tool tests passed ✅")
