import fnmatch
import hashlib
import os
# IMPORT THE WORKSPACE PATH
from so import paths

"""
Judge Identity (design 2026-10-27, docs/AGENTIC_DESIGN.md section 4: judge versioning)

The judge is what scores a run: every protected .py file under so/ and scripts/ (protected_paths.txt), plus two
inputs that change reports without being code (roadmap R3, 2026-10-29): the tried-designs ledger in
records/legacy/*.csv (the pilot-included multiple-testing view since R4) and the package lock requirements/venv_main_lock.txt (it fixes
the numerics). Its identity is a content hash of those files, recorded in every report and manifest and in the run
index. Two runs with the same judge hash were scored by identical rules, whatever their commits; a different hash means
the rules changed and the results are not directly comparable. Nothing has to be bumped by hand.

The queue takes the hash of the run's worktree before the run process starts (a fresh checkout of the run commit) and
again after it ends, and files the run as failed when the two differ or the report shows another value: design code
ran in between and must not have changed the judge (audit S9).

Line endings are normalized (CRLF -> LF) so a Windows checkout, a git blob and the Linux CI give the same hash. Tests,
notebooks and documents are not part of the judge: they do not score runs.
"""

# FOLDERS THAT HOLD JUDGE CODE (PROTECTED .py FILES INSIDE THEM ARE THE JUDGE)
JUDGE_FOLDER_LIST = ["so", "scripts"]
# THE PROTECTED-PATH LIST (ONE GLOB PER LINE; "append:" ENTRIES ARE NOT CODE)
PROTECTED_LIST_FILE_STR = "protected_paths.txt"
# NON-CODE INPUTS OF THE VERDICT THAT ARE PART OF THE JUDGE (REPO-RELATIVE GLOBS)
JUDGE_EXTRA_GLOB_LIST = ["records/legacy/*.csv", "requirements/venv_main_lock.txt"]
# FOLDERS THE EXTRA GLOBS LIVE IN (SEARCHED WITH THE JUDGE FOLDERS)
JUDGE_EXTRA_FOLDER_LIST = ["records/legacy", "requirements"]


# FUNCTION: THE PROTECTED GLOBS FROM A LIST'S TEXT
def get_judge_glob_list(list_text_in):
    """
    Args:
        list_text_in (str): Content of protected_paths.txt

    Returns:
        list[str]: Globs (comments, blank lines and append: entries dropped)
    """
    # SAME FORMAT AS scripts/check_protected_paths.py
    glob_list = []
    for line_str in str(list_text_in).splitlines():
        entry_str = line_str.split("#", 1)[0].strip()
        if entry_str and not entry_str.startswith("append:"):
            glob_list.append(entry_str)
    return glob_list


# FUNCTION: WHETHER A REPO-RELATIVE PATH MATCHES A GLOB
def get_judge_glob_match_bool(path_str_in, glob_list_in):
    """
    "dir/**" matches everything under dir; other globs match case-sensitively on the forward-slash path (the same on
    every platform).

    Args:
        path_str_in (str): Repo-relative path, forward slashes
        glob_list_in (list[str]): Globs

    Returns:
        bool: True when protected
    """
    # A FOLDER GLOB COVERS EVERY DEPTH
    for glob_str in glob_list_in:
        if glob_str.endswith("/**") and (path_str_in + "/").startswith(glob_str[:-2]):
            return True
        if fnmatch.fnmatchcase(path_str_in, glob_str):
            return True
    return False


# FUNCTION: THE JUDGE FILES AMONG A LIST OF REPO-RELATIVE PATHS
def get_judge_rel_path_list(rel_path_list_in, protected_text_in):
    """
    Args:
        rel_path_list_in (list[str]): Candidate paths (forward slashes)
        protected_text_in (str): Content of protected_paths.txt

    Returns:
        list[str]: Sorted judge files: protected .py files under so/ and scripts/, and the extra inputs
    """
    # CODE BY THE PROTECTED LIST, EXTRAS BY THEIR GLOBS
    glob_list = get_judge_glob_list(protected_text_in)
    judge_set = set()
    for rel_str in rel_path_list_in:
        top_str = rel_str.split("/", 1)[0]
        if top_str in JUDGE_FOLDER_LIST and rel_str.endswith(".py") and "/__pycache__/" not in f"/{rel_str}":
            if get_judge_glob_match_bool(rel_str, glob_list):
                judge_set.add(rel_str)
        elif any(fnmatch.fnmatchcase(rel_str, glob_str) for glob_str in JUDGE_EXTRA_GLOB_LIST):
            judge_set.add(rel_str)
    return sorted(judge_set)


# FUNCTION: THE HASH OF A LIST OF FILES, READ BY A FUNCTION
def get_judge_hash_from_reader_dict(rel_path_list_in, read_bytes_func_in):
    """
    Args:
        rel_path_list_in (list[str]): Sorted judge files
        read_bytes_func_in (callable): rel path -> bytes

    Returns:
        dict: judge_hash (sha256 hex of path, NUL, LF-normalized content, NUL, per file in order), judge_file_count
    """
    # PATH, NUL, CONTENT, NUL FOR EVERY FILE
    hasher = hashlib.sha256()
    for rel_str in rel_path_list_in:
        content_bytes = read_bytes_func_in(rel_str).replace(b"\r\n", b"\n")
        hasher.update(rel_str.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content_bytes)
        hasher.update(b"\0")
    return {"judge_hash": hasher.hexdigest(), "judge_file_count": len(rel_path_list_in)}


# FUNCTION: THE JUDGE FILES OF A WORKSPACE
def get_judge_file_list(workspace_path_str_in=None):
    """
    Args:
        workspace_path_str_in (str | None): Workspace root (None = this workspace)

    Returns:
        list[str]: Repo-relative paths (forward slashes, sorted) of the judge files on disk
    """
    # THE LIST IN THIS WORKSPACE (THE RUN COMMIT'S WORKTREE WHEN THE RUNNER RUNS IT)
    workspace_str = os.path.abspath(workspace_path_str_in or paths.WORKSPACE_PATH_STR)
    with open(os.path.join(workspace_str, PROTECTED_LIST_FILE_STR), "r", encoding="utf-8") as list_file:
        protected_text_str = list_file.read()
    rel_list = []
    for folder_str in JUDGE_FOLDER_LIST + JUDGE_EXTRA_FOLDER_LIST:
        for dir_str, dir_name_list, file_name_list in os.walk(os.path.join(workspace_str, *folder_str.split("/"))):
            dir_name_list[:] = sorted(name_str for name_str in dir_name_list if name_str != "__pycache__")
            for file_name_str in file_name_list:
                rel_list.append(os.path.relpath(os.path.join(dir_str, file_name_str), workspace_str).replace("\\", "/"))
    return get_judge_rel_path_list(rel_list, protected_text_str)


# FUNCTION: THE JUDGE HASH OF A FOLDER
def get_judge_hash_dict(workspace_path_str_in=None):
    """
    Args:
        workspace_path_str_in (str | None): Workspace root (None = this workspace)

    Returns:
        dict: judge_hash, judge_file_count
    """
    # THE FILES ON DISK
    workspace_str = os.path.abspath(workspace_path_str_in or paths.WORKSPACE_PATH_STR)

    def read_bytes(rel_str_in):
        with open(os.path.join(workspace_str, *rel_str_in.split("/")), "rb") as file_obj:
            return file_obj.read()
    return get_judge_hash_from_reader_dict(get_judge_file_list(workspace_str), read_bytes)
