"""
Workspace Tests: judge identity (so.runner.judge_identity; design 2026-10-27)

Run from the workspace root:   python tests/test_runner_judge.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic files only. The data root is a temporary folder.
"""

import os
import sys
import shutil
import tempfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_judge_")
os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
from so.runner.judge_identity import get_judge_file_list, get_judge_hash_dict, get_judge_glob_list


# FUNCTION: PRINT A PASSED TEST
def passed(message_str_in):
    print(f"✅ {message_str_in}")


# FUNCTION: WRITE A FILE WITH EXACT BYTES
def write_bytes(root_str_in, rel_str_in, content_bytes_in):
    path_str = os.path.join(root_str_in, *rel_str_in.split("/"))
    os.makedirs(os.path.dirname(path_str), exist_ok=True)
    with open(path_str, "wb") as file_obj:
        file_obj.write(content_bytes_in)


# TEST: THE REAL WORKSPACE'S JUDGE
def test_workspace_judge():
    file_list = get_judge_file_list()
    for rel_str in ["so/runner/verdict.py", "so/runner/run.py", "so/runner/judge_identity.py", "so/core/multiple_testing.py",
                    "so/core/trial_log.py", "scripts/run_queue.py", "scripts/run_development.py"]:
        assert rel_str in file_list, rel_str
    for rel_str in ["so/features/rule_design.py", "tests/test_runner_judge.py"]:
        assert rel_str not in file_list, rel_str
    first_dict = get_judge_hash_dict()
    assert len(first_dict["judge_hash"]) == 64 and first_dict["judge_file_count"] == len(file_list)
    assert get_judge_hash_dict() == first_dict
    passed(f"workspace judge: {first_dict['judge_file_count']} protected files, hash {first_dict['judge_hash'][:12]}…, stable")


# TEST: WHAT CHANGES THE HASH AND WHAT DOES NOT
def test_judge_hash_rules():
    root_str = tempfile.mkdtemp(prefix="so_judge_ws_")
    try:
        write_bytes(root_str, "protected_paths.txt", b"# list\nso/runner/**\nscripts/run_queue.py\nappend:docs/LOG.md\n")
        write_bytes(root_str, "so/runner/verdict.py", b"A = 1\nB = 2\n")
        write_bytes(root_str, "scripts/run_queue.py", b"print('queue')\n")
        write_bytes(root_str, "so/features/helper.py", b"X = 1\n")
        write_bytes(root_str, "so/runner/__pycache__/verdict.cpython-312.pyc", b"\x00\x01")
        assert get_judge_glob_list("a/**\n# c\n\nappend:x.md\nb.py  # note\n") == ["a/**", "b.py"]
        assert get_judge_file_list(root_str) == ["scripts/run_queue.py", "so/runner/verdict.py"]
        base_str = get_judge_hash_dict(root_str)["judge_hash"]
        # A WINDOWS CHECKOUT (CRLF) GIVES THE SAME HASH
        write_bytes(root_str, "so/runner/verdict.py", b"A = 1\r\nB = 2\r\n")
        assert get_judge_hash_dict(root_str)["judge_hash"] == base_str
        # AN UNPROTECTED HELPER, A .pyc OR A NON-.py FILE DOES NOT CHANGE IT
        write_bytes(root_str, "so/features/helper.py", b"X = 2\n")
        write_bytes(root_str, "so/runner/__pycache__/verdict.cpython-312.pyc", b"\x09")
        write_bytes(root_str, "so/runner/notes.md", b"text\n")
        assert get_judge_hash_dict(root_str)["judge_hash"] == base_str
        # A CHANGED RULE, A NEW CORE FILE, OR A RENAMED CORE FILE DOES
        write_bytes(root_str, "so/runner/verdict.py", b"A = 1\nB = 3\n")
        changed_str = get_judge_hash_dict(root_str)["judge_hash"]
        assert changed_str != base_str
        write_bytes(root_str, "so/runner/extra.py", b"")
        assert get_judge_hash_dict(root_str)["judge_hash"] != changed_str
        os.remove(os.path.join(root_str, "so", "runner", "extra.py"))
        assert get_judge_hash_dict(root_str)["judge_hash"] == changed_str
        os.rename(os.path.join(root_str, "so", "runner", "verdict.py"), os.path.join(root_str, "so", "runner", "verdict2.py"))
        assert get_judge_hash_dict(root_str)["judge_hash"] != changed_str
        # PROTECTING ONE MORE FILE ADDS IT TO THE JUDGE
        write_bytes(root_str, "protected_paths.txt", b"so/runner/**\nscripts/run_queue.py\nso/features/helper.py\n")
        assert "so/features/helper.py" in get_judge_file_list(root_str)
    finally:
        shutil.rmtree(root_str, ignore_errors=True)
    passed("judge hash: CRLF-neutral; ignores unprotected helpers, .pyc and non-.py; changes on a rule, file added, removed or renamed")


if __name__ == "__main__":
    try:
        test_workspace_judge()
        test_judge_hash_rules()
    finally:
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
    print("\nAll judge identity tests passed.")
