import ast
import hashlib
import json
import os
import subprocess
# IMPORT THE WORKSPACE PATH AND THE TRIAL-LOG READER
from so import paths
from so.core.multiple_testing import read_trial_record_pdf
# IMPORT THE DESIGN-FILE WALK AND THE PROTECTED-PATH MATCH
from so.runner.preflight import (get_design_follow_path_list, get_import_follow_path_list, get_import_name_list,
                                 get_module_file_path_str)
from so.runner.judge_identity import get_judge_glob_list, get_judge_glob_match_bool, PROTECTED_LIST_FILE_STR

"""
Pre-Registration Guard For Development Runs (audit S5, 2026-10-25)

research-integrity.mdc asks for PROTOCOL.md, config.py, design.py and tests to be committed in a "preregister expNN"
commit before the first run of an experiment version, for a new PROTOCOL_VERSION after any change, and for at most two
new versions per experiment. Until now only the holdout evaluation checked this. A development run now checks:

    a version already in the trial log   the design folder hash must be one already logged for that version: the
                                         same code may run again (a rerun after a runner fix), a changed folder may
                                         not (bump PROTOCOL_VERSION).
    a version not yet in the trial log   (1) at most RUNNER_MAX_PROTOCOL_VERSION_COUNT versions per experiment, this
                                         one included; (2) PROTOCOL.md has every required section
                                         (PROTOCOL_REQUIRED_SECTION_LIST, matched case-insensitively in ## headings)
                                         and a "Derived from:" line; (3) the last commit that touched the design
                                         folder has "preregister" in its subject.

Versions logged before 2026-10-25 keep their protocols as they are (the lint applies to new versions only).

Registered versions survive a reset (2026-11-09). "Logged" means logged in the trial log OR in
records/legacy/registered_versions.csv (REGISTERED_VERSIONS_REL_STR): one row per experiment, protocol version, design
folder hash and helper hash ever logged, without results. scripts/reset_records.py adds the trial log's rows to it
before it moves the trial log away, so a reset no longer makes every logged version look new: the folder-hash lock, the
helper-hash lock and the three-version limit hold across resets. The file is protected and part of the judge hash;
the runner reads the copy of the deployed commit, so a reset that adds rows is followed by a merge and a deploy.

Shared helpers (roadmap R3, audit S2, 2026-10-29). A design may import unprotected shared code from so/ (for example
so/features/rule_design.py). That code is not in the design folder, so a change to it would change a pre-registered
design without changing its folder hash. Every run therefore also records a helper hash: the content of the
unprotected so/ files the design imports, followed transitively (protected files are already in the judge hash). A
version whose logged rows carry helper hashes may rerun only with one of them; a change is a new PROTOCOL_VERSION.
Rows logged before this rule have no helper hash: the first run under the rule records it. The helper hash is run
bookkeeping in the multiple-testing design key (so.core.multiple_testing), not part of it: putting it in the key would
count every rerun of an unchanged design as a new design; the forced new version is what records a changed helper.
"""

# SECTIONS A NEW PROTOCOL VERSION MUST HAVE (A ## HEADING CONTAINING EACH WORD OR PHRASE)
PROTOCOL_REQUIRED_SECTION_LIST = ["question", "success criteria", "data sources", "rules", "selection", "baselines",
                                  "stopping", "limitations", "change log"]
# THE LINE THAT DECLARES WHERE A DESIGN CAME FROM ("none", or the earlier experiment and how it was chosen)
DERIVED_FROM_PREFIX_STR = "derived from:"
# AT MOST 1.0 PLUS TWO AMENDMENTS
RUNNER_MAX_PROTOCOL_VERSION_COUNT = 3
# THE VERSIONS THAT SURVIVE A RESET (ONE ROW PER EXPERIMENT, VERSION, FOLDER HASH AND HELPER HASH; NO RESULTS)
REGISTERED_VERSIONS_REL_STR = "records/legacy/registered_versions.csv"
REGISTERED_VERSION_COLUMN_LIST = ["source", "experiment", "protocol_version", "design_folder_hash", "helper_hash"]


# FUNCTION: MISSING SECTIONS OF A PROTOCOL
def get_protocol_missing_list(protocol_text_in):
    """
    Args:
        protocol_text_in (str): PROTOCOL.md content

    Returns:
        list[str]: Required sections with no matching ## heading, plus "Derived from:" when that line is missing
    """
    # HEADINGS ONLY, LOWER CASE
    heading_list = [line_str.lstrip("#").strip().lower() for line_str in str(protocol_text_in).splitlines()
                    if line_str.startswith("## ")]
    missing_list = [section_str for section_str in PROTOCOL_REQUIRED_SECTION_LIST
                    if not any(section_str in heading_str for heading_str in heading_list)]
    if not any(line_str.strip().lower().startswith(DERIVED_FROM_PREFIX_STR) for line_str in str(protocol_text_in).splitlines()):
        missing_list.append("Derived from: line")
    return missing_list


# FUNCTION: VERSIONS AND FOLDER HASHES ALREADY LOGGED FOR AN EXPERIMENT
def get_logged_version_dict(trial_log_path_str_in, experiment_str_in):
    """
    Args:
        trial_log_path_str_in (str): Trial log
        experiment_str_in (str): Experiment name

    Returns:
        dict: protocol version -> set of design folder hashes (empty set when a row has none)
    """
    # ROWS OF THIS EXPERIMENT
    record_pdf = read_trial_record_pdf(trial_log_path_str_in)
    version_dict = {}
    if len(record_pdf) == 0 or "protocol_version" not in record_pdf.columns:
        return version_dict
    for experiment_str, version_str, setting_str in zip(record_pdf["experiment"], record_pdf["protocol_version"],
                                                        record_pdf["setting_json"]):
        if str(experiment_str) != str(experiment_str_in):
            continue
        hash_set = version_dict.setdefault(str(version_str), set())
        try:
            folder_hash_str = json.loads(setting_str).get("design_folder_hash")
        except (ValueError, TypeError, AttributeError):
            folder_hash_str = None
        if folder_hash_str:
            hash_set.add(str(folder_hash_str))
    return version_dict


# FUNCTION: THE UNPROTECTED so/ FILES A DESIGN IMPORTS, TRANSITIVELY
def get_design_helper_file_list(design_file_path_str_in, workspace_path_str_in=None):
    """
    Args:
        design_file_path_str_in (str): design.py
        workspace_path_str_in (str | None): Workspace root (None = this workspace)

    Returns:
        list[str]: Repo-relative paths (forward slashes, sorted) of unprotected so/ files reached from the design
    """
    # THE DESIGN'S OWN FILES (experiments/ AND SAME-FOLDER HELPERS), THEN EVERY so.* IMPORT FROM THEM AND FROM HELPERS
    workspace_str = os.path.abspath(workspace_path_str_in or paths.WORKSPACE_PATH_STR)
    so_folder_str = os.path.normcase(os.path.join(workspace_str, "so"))
    with open(os.path.join(workspace_str, PROTECTED_LIST_FILE_STR), "r", encoding="utf-8") as list_file:
        glob_list = get_judge_glob_list(list_file.read())
    design_file_list = get_design_follow_path_list(design_file_path_str_in)
    helper_set, seen_set = set(), set(os.path.abspath(path_str) for path_str in design_file_list)
    stack_list = list(design_file_list)
    while stack_list:
        file_path_str = stack_list.pop()
        with open(file_path_str, "r", encoding="utf-8") as file_obj:
            tree = ast.parse(file_obj.read(), filename=file_path_str)
        in_so_bool = os.path.normcase(os.path.abspath(file_path_str)).startswith(so_folder_str + os.sep)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            target_list = []
            if isinstance(node, ast.ImportFrom) and int(node.level or 0) > 0:
                if in_so_bool:
                    target_list = get_import_follow_path_list(file_path_str, node)
            else:
                for name_str in get_import_name_list(node):
                    if name_str == "so" or name_str.startswith("so."):
                        resolved_str = get_module_file_path_str(workspace_str, name_str)
                        if resolved_str is not None:
                            target_list.append(resolved_str)
            for target_str in target_list:
                abs_str = os.path.abspath(target_str)
                if not os.path.normcase(abs_str).startswith(so_folder_str + os.sep) or abs_str in seen_set:
                    continue
                seen_set.add(abs_str)
                rel_str = os.path.relpath(abs_str, workspace_str).replace("\\", "/")
                if get_judge_glob_match_bool(rel_str, glob_list):
                    continue
                helper_set.add(rel_str)
                stack_list.append(abs_str)
    return sorted(helper_set)


# FUNCTION: THE HELPER HASH OF A DESIGN
def get_design_helper_dict(design_file_path_str_in, workspace_path_str_in=None):
    """
    Args:
        design_file_path_str_in (str): design.py
        workspace_path_str_in (str | None): Workspace root (None = this workspace)

    Returns:
        dict: helper_hash (sha256 hex of path, NUL, LF-normalized content, NUL per file), helper_file_list
    """
    # THE SAME FORMAT AS THE JUDGE HASH (CRLF-NEUTRAL)
    workspace_str = os.path.abspath(workspace_path_str_in or paths.WORKSPACE_PATH_STR)
    file_list = get_design_helper_file_list(design_file_path_str_in, workspace_str)
    hasher = hashlib.sha256()
    for rel_str in file_list:
        with open(os.path.join(workspace_str, *rel_str.split("/")), "rb") as file_obj:
            content_bytes = file_obj.read().replace(b"\r\n", b"\n")
        hasher.update(rel_str.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(content_bytes)
        hasher.update(b"\0")
    return {"helper_hash": hasher.hexdigest(), "helper_file_list": file_list}


# FUNCTION: HELPER HASHES ALREADY LOGGED FOR AN EXPERIMENT
def get_logged_helper_dict(trial_log_path_str_in, experiment_str_in):
    """
    Args:
        trial_log_path_str_in (str): Trial log
        experiment_str_in (str): Experiment name

    Returns:
        dict: protocol version -> set of helper hashes (empty set when its rows have none)
    """
    # THE SAME ROWS AS get_logged_version_dict
    record_pdf = read_trial_record_pdf(trial_log_path_str_in)
    helper_dict = {}
    if len(record_pdf) == 0 or "protocol_version" not in record_pdf.columns:
        return helper_dict
    for experiment_str, version_str, setting_str in zip(record_pdf["experiment"], record_pdf["protocol_version"],
                                                        record_pdf["setting_json"]):
        if str(experiment_str) != str(experiment_str_in):
            continue
        hash_set = helper_dict.setdefault(str(version_str), set())
        try:
            helper_hash_str = json.loads(setting_str).get("helper_hash")
        except (ValueError, TypeError, AttributeError):
            helper_hash_str = None
        if helper_hash_str:
            hash_set.add(str(helper_hash_str))
    return helper_dict


# FUNCTION: THE REGISTERED-VERSIONS FILE OF THIS WORKSPACE (IN A RUN: THE WORKTREE OF THE DEPLOYED JUDGE COMMIT)
def get_registered_versions_path_str():
    """
    Returns:
        str: <workspace>/records/legacy/registered_versions.csv
    """
    # THE SAME ROOT AS THE PILOT LEDGER
    return os.path.join(paths.WORKSPACE_PATH_STR, *REGISTERED_VERSIONS_REL_STR.split("/"))


# FUNCTION: THE REGISTERED-VERSION ROWS A TRIAL LOG HOLDS
def get_trial_log_version_row_list(trial_log_path_str_in, source_str_in):
    """
    The same rows get_logged_version_dict and get_logged_helper_dict read (every row with a protocol_version column,
    notes included), reduced to distinct (experiment, version, folder hash, helper hash); a missing hash is "".

    Args:
        trial_log_path_str_in (str): Trial log
        source_str_in (str): Source label of the rows

    Returns:
        list[dict]: Rows with REGISTERED_VERSION_COLUMN_LIST, in first-seen order
    """
    # NO protocol_version COLUMN: NOTHING THE GUARD COULD READ
    record_pdf = read_trial_record_pdf(trial_log_path_str_in)
    row_list, seen_set = [], set()
    if len(record_pdf) == 0 or "protocol_version" not in record_pdf.columns:
        return row_list
    for experiment_str, version_str, setting_str in zip(record_pdf["experiment"], record_pdf["protocol_version"],
                                                        record_pdf["setting_json"]):
        try:
            setting_dict = json.loads(setting_str)
        except (ValueError, TypeError):
            setting_dict = {}
        if not isinstance(setting_dict, dict):
            setting_dict = {}
        key_tuple = (str(experiment_str), str(version_str), str(setting_dict.get("design_folder_hash") or ""),
                     str(setting_dict.get("helper_hash") or ""))
        if key_tuple in seen_set:
            continue
        seen_set.add(key_tuple)
        row_list.append(dict(zip(REGISTERED_VERSION_COLUMN_LIST, (str(source_str_in),) + key_tuple)))
    return row_list


# FUNCTION: VERSIONS, FOLDER HASHES AND HELPER HASHES OF AN EXPERIMENT IN THE REGISTERED-VERSIONS FILE
def get_registered_version_tuple(registered_path_str_in, experiment_str_in):
    """
    Args:
        registered_path_str_in (str): records/legacy/registered_versions.csv (a missing file holds nothing)
        experiment_str_in (str): Experiment name

    Returns:
        tuple[dict, dict]: protocol version -> set of folder hashes, protocol version -> set of helper hashes (the
                           shapes of get_logged_version_dict and get_logged_helper_dict)
    """
    # A MISSING FILE IS AN EMPTY REGISTER; A FILE WITHOUT THE COLUMNS IS AN ERROR (NEVER READ AS EMPTY)
    version_dict, helper_dict = {}, {}
    record_pdf = read_trial_record_pdf(registered_path_str_in)
    if len(record_pdf) == 0:
        return version_dict, helper_dict
    missing_list = [name_str for name_str in REGISTERED_VERSION_COLUMN_LIST if name_str not in record_pdf.columns]
    if missing_list:
        raise ValueError(f"{registered_path_str_in} lacks columns {missing_list}.")
    for experiment_str, version_str, folder_hash_str, helper_hash_str in zip(
            record_pdf["experiment"], record_pdf["protocol_version"], record_pdf["design_folder_hash"],
            record_pdf["helper_hash"]):
        if str(experiment_str) != str(experiment_str_in):
            continue
        folder_set = version_dict.setdefault(str(version_str), set())
        helper_set = helper_dict.setdefault(str(version_str), set())
        if str(folder_hash_str):
            folder_set.add(str(folder_hash_str))
        if str(helper_hash_str):
            helper_set.add(str(helper_hash_str))
    return version_dict, helper_dict


# FUNCTION: MERGE TWO VERSION -> SET DICTS
def get_merged_set_dict(first_dict_in, second_dict_in):
    """
    Args:
        first_dict_in (dict): version -> set
        second_dict_in (dict): version -> set

    Returns:
        dict: version -> union of the sets (a version in either dict is present)
    """
    # COPY, THEN ADD
    merged_dict = {key_str: set(value_set) for key_str, value_set in first_dict_in.items()}
    for key_str, value_set in second_dict_in.items():
        merged_dict.setdefault(key_str, set()).update(value_set)
    return merged_dict


# FUNCTION: THE SUBJECT OF THE LAST COMMIT THAT TOUCHED A FOLDER
def get_last_folder_commit_subject_str(design_folder_str_in, git_func_in=None):
    """
    Args:
        design_folder_str_in (str): Design folder
        git_func_in (callable | None): (args list) -> stdout str (tests)

    Returns:
        str: Commit subject ("" when the folder has no commit)
    """
    # git log -1 ON THE FOLDER
    def run_git(arg_list_in):
        return subprocess.check_output(["git"] + arg_list_in, cwd=paths.WORKSPACE_PATH_STR, text=True, encoding="utf-8")
    git_func = git_func_in or run_git
    # A FOLDER ON ANOTHER WINDOWS DRIVE THAN THE WORKSPACE HAS NO RELATIVE PATH: PASS IT ABSOLUTE (GIT THEN FINDS NO
    # COMMIT FOR IT, SO THE GUARD REFUSES THE FIRST RUN, WHICH IS THE SAFE ANSWER)
    abs_folder_str = os.path.abspath(design_folder_str_in)
    try:
        path_str = os.path.relpath(abs_folder_str, paths.WORKSPACE_PATH_STR).replace("\\", "/")
    except ValueError:
        path_str = abs_folder_str.replace("\\", "/")
    return str(git_func(["log", "-1", "--format=%s", "--", path_str])).strip()


# FUNCTION: REFUSE A DEVELOPMENT RUN THAT BREAKS PRE-REGISTRATION
def check_preregistration_dict(design_module_in, design_folder_str_in, design_folder_hash_str_in, trial_log_path_str_in,
                               git_func_in=None, helper_hash_str_in=None, registered_path_str_in=None):
    """
    Args:
        design_module_in (module): Design (EXPERIMENT_NAME, PROTOCOL_VERSION)
        design_folder_str_in (str): Design folder
        design_folder_hash_str_in (str): Its content hash (run.get_design_folder_hash_str)
        trial_log_path_str_in (str): Trial log
        git_func_in (callable | None): Injected git (tests)
        helper_hash_str_in (str | None): Helper hash of the design (get_design_helper_dict)
        registered_path_str_in (str | None): Registered versions (None = records/legacy/registered_versions.csv of
                                             this workspace)

    Returns:
        dict: status_str ("rerun" or "first_run"), experiment, protocol_version, derived_from_str
    """
    # THE VERSION AND WHAT THE LOG ALREADY HOLDS
    experiment_str = str(getattr(design_module_in, "EXPERIMENT_NAME", ""))
    version_str = str(getattr(design_module_in, "PROTOCOL_VERSION", ""))
    if not experiment_str or not version_str:
        raise ValueError("a development run needs EXPERIMENT_NAME and PROTOCOL_VERSION.")
    registered_version_dict, registered_helper_dict = get_registered_version_tuple(
        registered_path_str_in or get_registered_versions_path_str(), experiment_str)
    version_dict = get_merged_set_dict(get_logged_version_dict(trial_log_path_str_in, experiment_str),
                                       registered_version_dict)
    protocol_path_str = os.path.join(design_folder_str_in, "PROTOCOL.md")
    protocol_text_str = open(protocol_path_str, encoding="utf-8").read() if os.path.isfile(protocol_path_str) else ""
    derived_line_list = [line_str.strip()[len(DERIVED_FROM_PREFIX_STR):].strip() for line_str in protocol_text_str.splitlines()
                         if line_str.strip().lower().startswith(DERIVED_FROM_PREFIX_STR)]
    derived_from_str = derived_line_list[0] if derived_line_list else ""
    if version_str in version_dict:
        logged_hash_set = version_dict[version_str]
        if logged_hash_set and design_folder_hash_str_in not in logged_hash_set:
            raise ValueError(f"{experiment_str} version {version_str} already ran with different code; a change after a "
                             f"run is a new PROTOCOL_VERSION (research-integrity.mdc).")
        logged_helper_set = get_merged_set_dict(get_logged_helper_dict(trial_log_path_str_in, experiment_str),
                                                registered_helper_dict).get(version_str, set())
        if helper_hash_str_in is not None and logged_helper_set and str(helper_hash_str_in) not in logged_helper_set:
            raise ValueError(f"{experiment_str} version {version_str} already ran with different shared helper code "
                             f"(unprotected so/ files it imports); a change after a run is a new PROTOCOL_VERSION.")
        return {"status_str": "rerun", "experiment": experiment_str, "protocol_version": version_str,
                "derived_from_str": derived_from_str, "helper_hash": helper_hash_str_in}
    if len(version_dict) + 1 > RUNNER_MAX_PROTOCOL_VERSION_COUNT:
        raise ValueError(f"{experiment_str} already has versions {sorted(version_dict)}; at most two new versions per "
                         f"experiment (research-integrity.mdc).")
    if not protocol_text_str:
        raise ValueError(f"{protocol_path_str} is missing; write and commit the protocol before the first run.")
    missing_list = get_protocol_missing_list(protocol_text_str)
    if missing_list:
        raise ValueError(f"{protocol_path_str} lacks required sections: {', '.join(missing_list)}.")
    subject_str = get_last_folder_commit_subject_str(design_folder_str_in, git_func_in)
    if "preregister" not in subject_str.lower():
        raise ValueError(f"the last commit of {design_folder_str_in} is not a preregister commit ({subject_str!r}); "
                         f"commit PROTOCOL.md, config.py, design.py and tests with 'preregister {experiment_str}' first.")
    return {"status_str": "first_run", "experiment": experiment_str, "protocol_version": version_str,
            "derived_from_str": derived_from_str, "helper_hash": helper_hash_str_in}
