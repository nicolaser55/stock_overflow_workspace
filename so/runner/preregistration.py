import ast
import datetime
import hashlib
import json
import os
import re
import subprocess
# IMPORT THE WORKSPACE PATH AND THE TRIAL-LOG READER
from so import paths
from so.core.multiple_testing import (read_trial_record_pdf, get_experiment_family_str, get_design_key_set,
                                      get_design_key_str, PILOT_LEDGER_REL_STR)
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

New versions must be visible to the count (decided by Nicolas on 2026-11-14, review F1 and F4). The multiple-testing
design key is the family and the candidate name, so a first run of a version not logged yet is also refused when:
    (4) its folder sits under experiments/ and its name differs from EXPERIMENT_NAME (a renamed copy would be counted
        as a new experiment and escape the version limit);
    (5) its family (EXPERIMENT_NAME without a trailing _v<digits> suffix) already holds RUNNER_MAX_PROTOCOL_VERSION_COUNT
        versions over all its experiment names (the limit counts per family, not per name);
    (6) any of its candidate names already has a design key in the trial log or the pilot ledger (an amended version
        reusing a name would add nothing to N and push the earlier version out of V): an amendment renames every
        candidate, for example with a "v1.1|" prefix;
    (7) PROTOCOL.md lacks the "Family:" line ("Family: C, idea C1, variant 1 of 5"; a variant is a protocol version,
        at most 5 per idea), or, for an amendment (the family already has a logged version), the change-log row of this
        version lacks exactly one label: "bug-fix" or "data-dependent".
A crash before the first trial row logs nothing, so the version is not logged yet: a fix may rerun as the same version
after a new preregister commit (record it in the change log as "pre-run fix: <what>"). Versions logged before
2026-11-14 are reruns and are not checked against (4)-(7).

Resets (2026-11-14, review F3): scripts/reset_records.py writes store04_experiments/judge/reset_marker.json with the
LF-normalized SHA-256 of the pilot ledger and the registered-versions file it wrote. Every development run on the real
view checks that this workspace's copies (the deployed judge's) have those hashes, and stops otherwise: the records PR of
a reset must be merged and deployed before any run. No marker (no reset since the rule) passes.
"""

# SECTIONS A NEW PROTOCOL VERSION MUST HAVE (A ## HEADING CONTAINING EACH WORD OR PHRASE)
PROTOCOL_REQUIRED_SECTION_LIST = ["question", "success criteria", "data sources", "rules", "selection", "baselines",
                                  "stopping", "limitations", "change log"]
# THE LINE THAT DECLARES WHERE A DESIGN CAME FROM ("none", or the earlier experiment and how it was chosen)
DERIVED_FROM_PREFIX_STR = "derived from:"
# AT MOST 1.0 PLUS TWO AMENDMENTS (PER FAMILY SINCE 2026-11-14)
RUNNER_MAX_PROTOCOL_VERSION_COUNT = 3
# THE FAMILY LINE (2026-11-14): "Family: <letter>, idea <id>, variant <k> of 5" (A VARIANT IS A PROTOCOL VERSION)
FAMILY_LINE_PATTERN = re.compile(r"^family:\s*([A-Za-z])\s*,\s*idea\s+([A-Za-z0-9_.-]+)\s*,\s*variant\s+([1-5])\s+of\s+5\s*\.?\s*$",
                                 re.IGNORECASE)
FAMILY_PREFIX_STR = "family:"
# THE AMENDMENT LABELS (2026-11-14): ONE OF THEM IN THE CHANGE-LOG ROW OF EVERY AMENDED VERSION
AMENDMENT_LABEL_LIST = ["bug-fix", "data-dependent"]
# THE RESET MARKER (2026-11-14): THE RECORDS A RESET WROTE, BY LF-NORMALIZED SHA-256
RESET_MARKER_SCHEMA_STR = "so_reset_marker_v1"
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
    if get_family_line_dict(protocol_text_in) is None:
        missing_list.append("Family: line (\"Family: <letter>, idea <id>, variant <k> of 5\")")
    return missing_list


# FUNCTION: THE FAMILY LINE OF A PROTOCOL (2026-11-14)
def get_family_line_dict(protocol_text_in):
    """
    Args:
        protocol_text_in (str): PROTOCOL.md content

    Returns:
        dict | None: family (upper case), idea, variant (int, 1-5), line; None when the first Family: line is missing
            or malformed
    """
    # THE FIRST LINE THAT STARTS WITH "Family:" DECIDES
    for line_str in str(protocol_text_in).splitlines():
        if line_str.strip().lower().startswith(FAMILY_PREFIX_STR):
            match = FAMILY_LINE_PATTERN.match(line_str.strip())
            if match is None:
                return None
            return {"family": match.group(1).upper(), "idea": match.group(2), "variant": int(match.group(3)),
                    "line": line_str.strip()}
    return None


# FUNCTION: THE AMENDMENT LABEL OF ONE VERSION IN THE CHANGE LOG (2026-11-14)
def get_amendment_label_str(protocol_text_in, version_str_in):
    """
    The change-log table rows whose first cell is the version; their text must hold exactly one label of
    AMENDMENT_LABEL_LIST.

    Args:
        protocol_text_in (str): PROTOCOL.md content
        version_str_in (str): PROTOCOL_VERSION

    Returns:
        str | None: The label, or None when no row of this version holds exactly one label
    """
    # TABLE ROWS ONLY: | version | date | change |
    found_set = set()
    for line_str in str(protocol_text_in).splitlines():
        stripped_str = line_str.strip()
        if not stripped_str.startswith("|"):
            continue
        cell_list = [cell_str.strip() for cell_str in stripped_str.strip("|").split("|")]
        if not cell_list or cell_list[0] != str(version_str_in):
            continue
        row_text_str = " ".join(cell_list[1:]).lower()
        found_set |= {label_str for label_str in AMENDMENT_LABEL_LIST if label_str in row_text_str}
    return next(iter(found_set)) if len(found_set) == 1 else None


# FUNCTION: EVERY (EXPERIMENT, VERSION) OF A FAMILY IN THE TRIAL LOG AND THE REGISTERED-VERSIONS FILE (2026-11-14)
def get_family_version_set(trial_log_path_str_in, registered_path_str_in, family_str_in):
    """
    Args:
        trial_log_path_str_in (str): Trial log
        registered_path_str_in (str): records/legacy/registered_versions.csv
        family_str_in (str): so.core.multiple_testing.get_experiment_family_str of the experiment

    Returns:
        set[tuple[str, str]]: (experiment, protocol version) pairs whose experiment belongs to the family
    """
    # BOTH RECORDS; A ROW WITHOUT A protocol_version COLUMN HOLDS NOTHING THE GUARD COULD READ
    pair_set = set()
    for path_str in (trial_log_path_str_in, registered_path_str_in):
        record_pdf = read_trial_record_pdf(path_str)
        if len(record_pdf) == 0 or "protocol_version" not in record_pdf.columns:
            continue
        for experiment_str, version_str in zip(record_pdf["experiment"], record_pdf["protocol_version"]):
            if get_experiment_family_str(experiment_str) == str(family_str_in) and str(version_str):
                pair_set.add((str(experiment_str), str(version_str)))
    return pair_set


# FUNCTION: CANDIDATE NAMES OF A NEW VERSION THAT ALREADY HAVE A DESIGN KEY (2026-11-14)
def get_candidate_collision_list(design_module_in, trial_log_path_str_in, ledger_path_str_in=None):
    """
    The design key is the family and the candidate (so.core.multiple_testing.get_design_key_str), so a reused name in
    the same family counts nothing new.

    Args:
        design_module_in (module): Design (EXPERIMENT_NAME, CANDIDATE_LIST)
        trial_log_path_str_in (str): Trial log
        ledger_path_str_in (str | None): Pilot ledger (None = records/legacy/pilot_designs.csv of this workspace)

    Returns:
        list: The candidates whose key is already logged, in CANDIDATE_LIST order
    """
    # THE SAME NORMALIZATION AS A LOGGED ROW: THE CANDIDATE THROUGH JSON
    experiment_str = str(getattr(design_module_in, "EXPERIMENT_NAME", ""))
    ledger_path_str = ledger_path_str_in or os.path.join(paths.WORKSPACE_PATH_STR, *PILOT_LEDGER_REL_STR.split("/"))
    logged_key_set = get_design_key_set(read_trial_record_pdf(trial_log_path_str_in))
    logged_key_set |= get_design_key_set(read_trial_record_pdf(ledger_path_str))
    collision_list = []
    for candidate in list(getattr(design_module_in, "CANDIDATE_LIST", []) or []):
        setting_json_str = json.dumps({"candidate": json.loads(json.dumps(candidate, default=str))}, sort_keys=True)
        if get_design_key_str(experiment_str, setting_json_str) in logged_key_set:
            collision_list.append(candidate)
    return collision_list


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
    # (4) A FOLDER UNDER experiments/ CARRIES ITS EXPERIMENT'S NAME (2026-11-14)
    experiments_root_str = os.path.normcase(os.path.abspath(os.path.join(paths.WORKSPACE_PATH_STR, "experiments")))
    folder_abs_str = os.path.abspath(design_folder_str_in)
    if os.path.normcase(os.path.dirname(folder_abs_str)) == experiments_root_str and os.path.basename(folder_abs_str) != experiment_str:
        raise ValueError(f"the folder {os.path.basename(folder_abs_str)} does not match EXPERIMENT_NAME {experiment_str}; "
                         f"an amendment keeps the experiment's name and folder and raises PROTOCOL_VERSION.")
    # (5) THE VERSION LIMIT COUNTS PER FAMILY (2026-11-14)
    family_str = get_experiment_family_str(experiment_str)
    family_version_set = get_family_version_set(trial_log_path_str_in, registered_path_str_in or get_registered_versions_path_str(),
                                                family_str)
    if len(family_version_set) + 1 > RUNNER_MAX_PROTOCOL_VERSION_COUNT:
        raise ValueError(f"the family {family_str} already has versions {sorted(family_version_set)}; at most "
                         f"{RUNNER_MAX_PROTOCOL_VERSION_COUNT} versions per family, whatever the experiment name.")
    # (6) A NEW VERSION'S CANDIDATES ARE NEW DESIGNS IN N (2026-11-14)
    collision_list = get_candidate_collision_list(design_module_in, trial_log_path_str_in)
    if collision_list:
        raise ValueError(f"{experiment_str} version {version_str}: candidates {collision_list[:5]} are already logged for the "
                         f"family {family_str}, so they would not count as new designs; rename every candidate of an "
                         f"amended version (for example 'v{version_str}|<name>').")
    if not protocol_text_str:
        raise ValueError(f"{protocol_path_str} is missing; write and commit the protocol before the first run.")
    missing_list = get_protocol_missing_list(protocol_text_str)
    if missing_list:
        raise ValueError(f"{protocol_path_str} lacks required sections: {', '.join(missing_list)}.")
    # (7) AN AMENDMENT SAYS WHY (2026-11-14)
    amendment_label_str = None
    if family_version_set:
        amendment_label_str = get_amendment_label_str(protocol_text_str, version_str)
        if amendment_label_str is None:
            raise ValueError(f"{protocol_path_str}: version {version_str} amends {sorted(family_version_set)}; its change-log "
                             f"row needs exactly one label of {AMENDMENT_LABEL_LIST} (when in doubt: data-dependent).")
    subject_str = get_last_folder_commit_subject_str(design_folder_str_in, git_func_in)
    if "preregister" not in subject_str.lower():
        raise ValueError(f"the last commit of {design_folder_str_in} is not a preregister commit ({subject_str!r}); "
                         f"commit PROTOCOL.md, config.py, design.py and tests with 'preregister {experiment_str}' first.")
    return {"status_str": "first_run", "experiment": experiment_str, "protocol_version": version_str,
            "derived_from_str": derived_from_str, "helper_hash": helper_hash_str_in,
            "family_dict": get_family_line_dict(protocol_text_str), "amendment_label_str": amendment_label_str}


"""
The Reset Marker (2026-11-14, review F3)
"""


# FUNCTION: LF-NORMALIZED SHA-256 OF A FILE ("" WHEN IT DOES NOT EXIST)
def get_lf_sha256_str(file_path_str_in):
    """
    Args:
        file_path_str_in (str): File

    Returns:
        str: Hex digest of the bytes with CRLF turned into LF (a git checkout on Windows may convert line ends), or ""
    """
    # THE SAME NORMALIZATION AS THE JUDGE HASH
    if not os.path.isfile(file_path_str_in):
        return ""
    with open(file_path_str_in, "rb") as file_obj:
        return hashlib.sha256(file_obj.read().replace(b"\r\n", b"\n")).hexdigest()


# FUNCTION: THE RECORD FILES A RESET WRITES, BY REPO PATH
def get_reset_record_path_dict(workspace_path_str_in=None):
    """
    Args:
        workspace_path_str_in (str | None): Workspace (None = this workspace; in a run: the deployed judge's worktree)

    Returns:
        dict: repo-relative path -> absolute path, for the pilot ledger and the registered-versions file
    """
    # THE TWO FILES THE RUNNER READS FROM THE DEPLOYED COMMIT
    workspace_str = workspace_path_str_in or paths.WORKSPACE_PATH_STR
    return {rel_str: os.path.join(workspace_str, *rel_str.split("/")) for rel_str in (PILOT_LEDGER_REL_STR, REGISTERED_VERSIONS_REL_STR)}


# FUNCTION: WRITE THE MARKER AFTER A RESET WROTE THE RECORDS (scripts/reset_records.py)
def write_reset_marker_dict(reason_str_in, marker_path_str_in=None, file_path_dict_in=None, now_in=None):
    """
    Args:
        reason_str_in (str): What wrote the records ("reset_<time>", "register_from")
        marker_path_str_in (str | None): Marker file (None = paths.LOCAL_RESET_MARKER_FILE_PATH_STR of the data root)
        file_path_dict_in (dict | None): repo-relative path -> the file written (None = this workspace's two files)
        now_in (datetime.datetime | None): Clock (tests)

    Returns:
        dict: The marker written
    """
    # THE HASHES OF THE FILES AS THE RESET LEFT THEM
    marker_path_str = marker_path_str_in or paths.get_named_data_path_str("LOCAL_RESET_MARKER_FILE_PATH_STR")
    now = now_in or datetime.datetime.now()
    marker_dict = {"schema": RESET_MARKER_SCHEMA_STR, "written_ts": now.strftime("%Y-%m-%dT%H:%M:%S"),
                   "reason": str(reason_str_in),
                   "file_sha256_dict": {rel_str: get_lf_sha256_str(path_str)
                                        for rel_str, path_str in (file_path_dict_in or get_reset_record_path_dict()).items()}}
    os.makedirs(os.path.dirname(marker_path_str), exist_ok=True)
    temporary_path_str = marker_path_str + ".tmp"
    with open(temporary_path_str, "w", encoding="utf-8", newline="\n") as marker_file:
        json.dump(marker_dict, marker_file, indent=2, sort_keys=True)
        marker_file.write("\n")
    os.replace(temporary_path_str, marker_path_str)
    return marker_dict


# FUNCTION: REFUSE A RUN WHOSE JUDGE READS OTHER RECORDS THAN THE LAST RESET WROTE
def check_reset_marker_dict(marker_path_str_in=None, workspace_path_str_in=None):
    """
    No marker passes (no reset since 2026-11-14). A marker that cannot be read, has another schema, or names a hash
    this workspace's file does not have stops the run: merge and deploy the reset's records PR first.

    Args:
        marker_path_str_in (str | None): Marker file (None = the data root's)
        workspace_path_str_in (str | None): Workspace (None = this workspace: in a queued run, the deployed judge's)

    Returns:
        dict: status_str ("no_marker" or "match"), file_sha256_dict
    """
    # FAILS CLOSED ON ANYTHING BUT A MISSING FILE OR AN EXACT MATCH
    marker_path_str = marker_path_str_in or paths.get_named_data_path_str("LOCAL_RESET_MARKER_FILE_PATH_STR")
    if not os.path.isfile(marker_path_str):
        return {"status_str": "no_marker", "file_sha256_dict": {}}
    try:
        with open(marker_path_str, "r", encoding="utf-8") as marker_file:
            marker_dict = json.load(marker_file)
        expected_dict = dict(marker_dict["file_sha256_dict"])
        schema_ok_bool = marker_dict.get("schema") == RESET_MARKER_SCHEMA_STR
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"the reset marker {marker_path_str} cannot be read ({type(error).__name__}); the run stops") from error
    if not schema_ok_bool:
        raise ValueError(f"the reset marker {marker_path_str} has another schema; the run stops")
    actual_dict = {rel_str: get_lf_sha256_str(path_str) for rel_str, path_str in get_reset_record_path_dict(workspace_path_str_in).items()}
    mismatch_list = [rel_str for rel_str in sorted(actual_dict) if expected_dict.get(rel_str) != actual_dict[rel_str]]
    if mismatch_list:
        raise ValueError(f"{', '.join(mismatch_list)} of this judge differ from what the last reset wrote "
                         f"({marker_dict.get('reason')}, {marker_dict.get('written_ts')}): merge and deploy the reset's "
                         f"records pull request before any run (review F3, 2026-11-14)")
    return {"status_str": "match", "file_sha256_dict": actual_dict}
