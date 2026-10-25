import argparse
import ast
import fnmatch
import os
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

The list is read from the merge base (git show <base>:protected_paths.txt), not from the branch under review, so a
branch cannot unprotect a file by editing the list (audit B4, 2026-10-25). CI runs the base's copy of this script.

    python scripts/check_protected_paths.py --closure      # so/ modules that protected code imports but the list misses

The closure check: every so/ module imported (transitively) by a protected so/ module must itself be protected,
otherwise an unprotected helper (fees, success criteria, period slices) could change what the runner decides.
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
    # THE FILE'S TEXT
    return read_protected_text_dict(Path(list_path_in).read_text(encoding="utf-8"))


# FUNCTION: READ THE GLOBS AND THE APPEND-ONLY FILES FROM A LIST'S TEXT
def read_protected_text_dict(list_text_in):
    """
    Args:
        list_text_in (str): Content of a protected_paths.txt (the working tree's, or the base's through git show)

    Returns:
        dict: glob_list, append_list
    """
    # ONE ENTRY PER LINE; # STARTS A COMMENT
    glob_list, append_list = [], []
    for line_str in str(list_text_in).splitlines():
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
    merge_base_str = git_func(["merge-base", base_str_in, "HEAD"]).strip()
    if protected_dict_in is None:
        base_list_str = git_func(["show", f"{merge_base_str}:protected_paths.txt"])
        protected_dict = read_protected_text_dict(base_list_str)
    else:
        protected_dict = protected_dict_in
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


# FUNCTION: THE FILE OF A DOTTED so.* MODULE
def get_module_file_str(module_name_str_in, workspace_path_in=WORKSPACE_PATH):
    """
    Args:
        module_name_str_in (str): Dotted module name
        workspace_path_in (Path): Workspace root

    Returns:
        str | None: Repo-relative file (forward slashes), or None when it is not a workspace file
    """
    # A MODULE FILE OR A PACKAGE
    rel_str = module_name_str_in.replace(".", "/")
    for candidate_str in [rel_str + ".py", rel_str + "/__init__.py"]:
        if (Path(workspace_path_in) / candidate_str).is_file():
            return candidate_str
    return None


# FUNCTION: so.* NAMES ONE FILE IMPORTS
def get_so_import_name_set(file_rel_str_in, workspace_path_in=WORKSPACE_PATH):
    """
    Args:
        file_rel_str_in (str): Repo-relative .py file
        workspace_path_in (Path): Workspace root

    Returns:
        set[str]: so.* names (from a import b also counts a.b, which may be a module)
    """
    # EVERY IMPORT STATEMENT, ALSO INSIDE FUNCTIONS
    tree = ast.parse((Path(workspace_path_in) / file_rel_str_in).read_text(encoding="utf-8"))
    name_set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            name_set.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            name_set.add(node.module)
            name_set.update(f"{node.module}.{alias.name}" for alias in node.names)
    return {name_str for name_str in name_set if name_str == "so" or name_str.startswith("so.")}


# FUNCTION: UNPROTECTED so/ FILES THAT PROTECTED CODE IMPORTS
def get_unprotected_closure_list(glob_list_in=None, workspace_path_in=WORKSPACE_PATH):
    """
    so/ files imported, directly or through other so/ files, by a protected so/ file, that are not protected.

    Args:
        glob_list_in (list[str] | None): Protected globs (None = the working-tree list)
        workspace_path_in (Path): Workspace root

    Returns:
        list[str]: Repo-relative files, sorted
    """
    # START FROM EVERY PROTECTED so/ FILE, FOLLOW so.* IMPORTS
    glob_list = glob_list_in if glob_list_in is not None else read_protected_dict()["glob_list"]
    start_list = []
    for dir_str, _dir_list, file_list in os.walk(Path(workspace_path_in) / "so"):
        for file_str in file_list:
            if file_str.endswith(".py"):
                rel_str = os.path.relpath(os.path.join(dir_str, file_str), workspace_path_in).replace(os.sep, "/")
                if get_protected_bool(rel_str, glob_list):
                    start_list.append(rel_str)
    seen_set, stack_list = set(start_list), list(start_list)
    while stack_list:
        rel_str = stack_list.pop()
        for name_str in get_so_import_name_set(rel_str, workspace_path_in):
            module_file_str = get_module_file_str(name_str, workspace_path_in)
            if module_file_str is not None and module_file_str not in seen_set:
                seen_set.add(module_file_str)
                stack_list.append(module_file_str)
    return sorted(rel_str for rel_str in seen_set if not get_protected_bool(rel_str, glob_list))


# RUN
if __name__ == "__main__":
    # ARGUMENTS
    parser = argparse.ArgumentParser(description="List changed files that are protected.")
    parser.add_argument("--base", default="main", help="Base ref (default main)")
    parser.add_argument("--closure", action="store_true", help="List unprotected modules that protected code imports")
    arg_dict = parser.parse_args()
    if arg_dict.closure:
        missing_list = get_unprotected_closure_list()
        if missing_list:
            print("protected code imports unprotected modules:")
            print("\n".join(f"  {path_str}" for path_str in missing_list))
            sys.exit(1)
        print("every module that protected code imports is protected")
        sys.exit(0)
    violation_list = get_violation_list(arg_dict.base)
    if violation_list:
        print("protected paths changed:")
        print("\n".join(f"  {line_str}" for line_str in violation_list))
        sys.exit(1)
    print(f"no protected path changed against {arg_dict.base}")
