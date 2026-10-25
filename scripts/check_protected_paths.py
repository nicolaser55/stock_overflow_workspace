import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

"""
Protected Paths Check (run by Nicolas before merging an agent branch)

    python scripts/check_protected_paths.py                 # the current branch against main
    python scripts/check_protected_paths.py --base <ref>

protected_paths.txt (workspace root) lists the files an agent must not change: the holdout and point-in-time guards,
the runner, the rules, the records, the guard tests, the environment. One glob per line; "append:<path>" marks a
file that may only grow at its end (docs/RESULTS_LOG.md). The check lists every changed file that matches, against
the merge base with --base and including uncommitted changes, and exits 1 when there is one. Exit 0 means the branch
touches no protected path. It is a review aid: a protected change is not wrong by itself, but only Nicolas merges it.
"""

# THE LIST FILE
WORKSPACE_PATH = Path(__file__).resolve().parents[1]
PROTECTED_LIST_PATH = WORKSPACE_PATH / "protected_paths.txt"


# FUNCTION: READ THE GLOBS AND THE APPEND-ONLY FILES
def read_protected_dict(list_path_in=PROTECTED_LIST_PATH):
    """
    Args:
        list_path_in (Path): protected_paths.txt

    Returns:
        dict: glob_list, append_list
    """
    # ONE ENTRY PER LINE; # STARTS A COMMENT
    glob_list, append_list = [], []
    for line_str in Path(list_path_in).read_text(encoding="utf-8").splitlines():
        entry_str = line_str.split("#", 1)[0].strip()
        if not entry_str:
            continue
        if entry_str.startswith("append:"):
            append_list.append(entry_str[len("append:"):].strip())
        else:
            glob_list.append(entry_str)
    return {"glob_list": glob_list, "append_list": append_list}


# FUNCTION: DOES A PATH MATCH A GLOB
def get_protected_bool(path_str_in, glob_list_in):
    """
    "dir/**" matches everything under dir; other globs use fnmatch on the repo-relative path.

    Args:
        path_str_in (str): Repo-relative path with forward slashes
        glob_list_in (list[str]): Globs

    Returns:
        bool: True when protected
    """
    # A FOLDER GLOB COVERS EVERY DEPTH
    for glob_str in glob_list_in:
        if glob_str.endswith("/**") and (path_str_in + "/").startswith(glob_str[:-2]):
            return True
        if fnmatch.fnmatch(path_str_in, glob_str):
            return True
    return False


# FUNCTION: IS A DIFF OF AN APPEND-ONLY FILE PURELY AN APPEND
def get_append_only_bool(diff_str_in):
    """
    Args:
        diff_str_in (str): git diff -U0 of one file

    Returns:
        bool: True when no existing line is removed or changed
    """
    # ANY "-" LINE (OTHER THAN THE FILE HEADER) REMOVES OR CHANGES AN EXISTING LINE
    for line_str in diff_str_in.splitlines():
        if line_str.startswith("-") and not line_str.startswith("---"):
            return False
    return True


# FUNCTION: THE CHANGED FILES THAT ARE PROTECTED
def get_violation_list(base_str_in="main", git_func_in=None, protected_dict_in=None):
    """
    Args:
        base_str_in (str): Base ref
        git_func_in (callable | None): (args list) -> stdout str (tests)
        protected_dict_in (dict | None): Output of read_protected_dict (None = the file)

    Returns:
        list[str]: "<path>: <reason>" lines
    """
    # GIT FROM THE WORKSPACE
    def run_git(arg_list_in):
        return subprocess.check_output(["git"] + arg_list_in, cwd=str(WORKSPACE_PATH), text=True, encoding="utf-8")
    git_func = git_func_in or run_git
    protected_dict = protected_dict_in or read_protected_dict()
    merge_base_str = git_func(["merge-base", base_str_in, "HEAD"]).strip()
    changed_set = set(git_func(["diff", "--name-only", merge_base_str]).split())
    changed_set |= set(git_func(["ls-files", "--others", "--exclude-standard"]).split())
    violation_list = []
    for path_str in sorted(changed_set):
        if path_str in protected_dict["append_list"]:
            if not get_append_only_bool(git_func(["diff", "-U0", merge_base_str, "--", path_str])):
                violation_list.append(f"{path_str}: append-only file has a removed or changed line")
        elif get_protected_bool(path_str, protected_dict["glob_list"]):
            violation_list.append(f"{path_str}: protected")
    return violation_list


# RUN
if __name__ == "__main__":
    # ARGUMENTS
    parser = argparse.ArgumentParser(description="List changed files that are protected.")
    parser.add_argument("--base", default="main", help="Base ref (default main)")
    arg_dict = parser.parse_args()
    violation_list = get_violation_list(arg_dict.base)
    if violation_list:
        print("protected paths changed:")
        print("\n".join(f"  {line_str}" for line_str in violation_list))
        sys.exit(1)
    print(f"no protected path changed against {arg_dict.base}")
