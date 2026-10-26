import json
import os
import subprocess
# IMPORT THE WORKSPACE PATH AND THE TRIAL-LOG READER
from so import paths
from so.core.multiple_testing import read_trial_record_pdf

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
"""

# SECTIONS A NEW PROTOCOL VERSION MUST HAVE (A ## HEADING CONTAINING EACH WORD OR PHRASE)
PROTOCOL_REQUIRED_SECTION_LIST = ["question", "success criteria", "data sources", "rules", "selection", "baselines",
                                  "stopping", "limitations", "change log"]
# THE LINE THAT DECLARES WHERE A DESIGN CAME FROM ("none", or the earlier experiment and how it was chosen)
DERIVED_FROM_PREFIX_STR = "derived from:"
# AT MOST 1.0 PLUS TWO AMENDMENTS
RUNNER_MAX_PROTOCOL_VERSION_COUNT = 3


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
                               git_func_in=None):
    """
    Args:
        design_module_in (module): Design (EXPERIMENT_NAME, PROTOCOL_VERSION)
        design_folder_str_in (str): Design folder
        design_folder_hash_str_in (str): Its content hash (run.get_design_folder_hash_str)
        trial_log_path_str_in (str): Trial log
        git_func_in (callable | None): Injected git (tests)

    Returns:
        dict: status_str ("rerun" or "first_run"), experiment, protocol_version, derived_from_str
    """
    # THE VERSION AND WHAT THE LOG ALREADY HOLDS
    experiment_str = str(getattr(design_module_in, "EXPERIMENT_NAME", ""))
    version_str = str(getattr(design_module_in, "PROTOCOL_VERSION", ""))
    if not experiment_str or not version_str:
        raise ValueError("a development run needs EXPERIMENT_NAME and PROTOCOL_VERSION.")
    version_dict = get_logged_version_dict(trial_log_path_str_in, experiment_str)
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
        return {"status_str": "rerun", "experiment": experiment_str, "protocol_version": version_str,
                "derived_from_str": derived_from_str}
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
            "derived_from_str": derived_from_str}
