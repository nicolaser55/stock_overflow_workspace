import fnmatch
import hashlib
import os
# IMPORT THE WORKSPACE PATH
from so import paths

"""
Judge Identity (design 2026-10-27, docs/AGENTIC_DESIGN.md section 4: judge versioning)

The judge is the protected core code that scores a run: every protected .py file under so/ and scripts/
(protected_paths.txt). Its identity is a content hash of those files, recorded in every report and manifest and in
the run index. Two runs with the same judge hash were scored by identical rules, whatever their commits; a different
hash means the rules changed and the results are not directly comparable. Nothing has to be bumped by hand: any change
to a core file changes the hash.

Line endings are normalized (CRLF -> LF) so a Windows checkout and the Linux CI give the same hash. Tests, notebooks
and documents are not part of the judge: they do not score runs.
"""

# FOLDERS THAT HOLD JUDGE CODE (PROTECTED .py FILES INSIDE THEM ARE THE JUDGE)
JUDGE_FOLDER_LIST = ["so", "scripts"]
# THE PROTECTED-PATH LIST (ONE GLOB PER LINE; "append:" ENTRIES ARE NOT CODE)
PROTECTED_LIST_FILE_STR = "protected_paths.txt"


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


# FUNCTION: THE JUDGE FILES OF A WORKSPACE
def get_judge_file_list(workspace_path_str_in=None):
    """
    Args:
        workspace_path_str_in (str | None): Workspace root (None = this workspace)

    Returns:
        list[str]: Repo-relative paths (forward slashes, sorted) of the protected .py files under so/ and scripts/
    """
    # THE LIST IN THIS WORKSPACE (THE DEPLOYED ONE WHEN THE RUNNER RUNS IT)
    workspace_str = os.path.abspath(workspace_path_str_in or paths.WORKSPACE_PATH_STR)
    with open(os.path.join(workspace_str, PROTECTED_LIST_FILE_STR), "r", encoding="utf-8") as list_file:
        glob_list = get_judge_glob_list(list_file.read())
    file_list = []
    for folder_str in JUDGE_FOLDER_LIST:
        for dir_str, dir_name_list, file_name_list in os.walk(os.path.join(workspace_str, folder_str)):
            dir_name_list[:] = sorted(name_str for name_str in dir_name_list if name_str != "__pycache__")
            for file_name_str in file_name_list:
                if not file_name_str.endswith(".py"):
                    continue
                rel_str = os.path.relpath(os.path.join(dir_str, file_name_str), workspace_str).replace("\\", "/")
                if get_judge_glob_match_bool(rel_str, glob_list):
                    file_list.append(rel_str)
    return sorted(file_list)


# FUNCTION: THE JUDGE HASH
def get_judge_hash_dict(workspace_path_str_in=None):
    """
    Args:
        workspace_path_str_in (str | None): Workspace root (None = this workspace)

    Returns:
        dict: judge_hash (sha256 hex of paths and LF-normalized contents, in path order), judge_file_count
    """
    # PATH, NUL, CONTENT, NUL FOR EVERY FILE
    workspace_str = os.path.abspath(workspace_path_str_in or paths.WORKSPACE_PATH_STR)
    file_list = get_judge_file_list(workspace_str)
    hasher = hashlib.sha256()
    for rel_str in file_list:
        with open(os.path.join(workspace_str, rel_str), "rb") as file_obj:
            content_bytes = file_obj.read().replace(b"\r\n", b"\n")
        hasher.update(rel_str.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content_bytes)
        hasher.update(b"\0")
    return {"judge_hash": hasher.hexdigest(), "judge_file_count": len(file_list)}
