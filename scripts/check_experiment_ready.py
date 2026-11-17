import argparse
import ast
import importlib.util
import os
import re
import subprocess
import sys
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH (THIS CLONE'S so/, NOT AN INSTALLED COPY)
WORKSPACE_PATH = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE_PATH))
# IMPORT THE RUNNER'S OWN PRE-REGISTRATION PIECES (CALLED, NEVER COPIED)
from so import paths
from so.core.multiple_testing import get_experiment_family_str
from so.runner.preregistration import (REGISTERED_VERSIONS_REL_STR, RUNNER_MAX_PROTOCOL_VERSION_COUNT,
                                       get_amendment_label_str, get_candidate_collision_list, get_family_line_dict,
                                       get_family_version_set, get_last_folder_commit_subject_str,
                                       get_logged_version_dict, get_merged_set_dict, get_protocol_missing_list,
                                       get_registered_version_tuple)

"""
Experiment Readiness Check (review 2026-11-17, proposal B1; not part of the judge)

Runs, before a review and before a job is queued, the checks the runner would otherwise run only inside the queued job
(both exp14 crashes were such checks failing an hour after the merge). It calls the runner's own functions; it does not
copy them, and it decides nothing: the runner's check inside the run still decides.

    python scripts/check_experiment_ready.py experiments/expNN_<name>            # before the preregister review, and
                                                                                 # before queueing (nico)
    python scripts/check_experiment_ready.py experiments/expNN_<name> --draft    # while the protocol is still a draft
    python scripts/check_experiment_ready.py experiments/expNN_<name> --reviewed <commit>
                                                    # also prints what changed in the folder since the reviewed commit
                                                    # (the third review: only the DRAFT marker may change)
    python scripts/check_experiment_ready.py --lint-unregistered                 # CI: the protocol lint of every
                                                                                 # version not in registered_versions.csv

What the folder check covers, each line marked PASS, FAIL, PENDING (--draft: not expected yet), SKIPPED (needs the
trial log), HAND (a person compares) or INFO:

    preflight                 so.runner.preflight.check_design_file on design.py and the experiments/ files it imports
    design loads              the design is loaded the way the run loads it (scripts/run_development.py), behind the
                              design-code guard; nothing is loaded when the preflight failed
    folder name               the folder is experiments/<EXPERIMENT_NAME>
    protocol lint             so.runner.preregistration.get_protocol_missing_list (## headings only: keep the
                              template's "## 3.1 Data sources" as written)
    DRAFT marker              no "DRAFT" left in PROTOCOL.md
    Family line               the line, shown next to its row of docs/STAGE1_RESEARCH_PLAN.md section 4 (hand check:
                              the idea, and that the variant is the next free one)
    candidates                CANDIDATE_LIST printed (hand check against the protocol's table; about 3-5 per version)
    versions                  the version against records/legacy/registered_versions.csv (and the trial log when
                              readable): a registered version may rerun only with a folder hash already logged; a new
                              one counts against the limit of RUNNER_MAX_PROTOCOL_VERSION_COUNT per experiment and per
                              family; an amendment needs its change-log label
    candidate names           no candidate already has a design key in records/legacy/pilot_designs.csv (and the
                              trial log when readable)
    uncommitted changes       none in the experiment folder
    preregister commit        the last commit of the folder has a subject starting "preregister"
    only experiments/         git diff --name-only <base>...HEAD touches only experiments/ (default base origin/main;
                              run "git fetch origin" first: the check does not fetch)
    runner check              so.runner.preregistration.check_preregistration_dict itself, the call the run makes

The trial log (store04_experiments/trial_log.csv under SO_DATA_PATH) holds the versions and candidates logged since the
last reset. so_agent cannot read it: those parts are reported as SKIPPED, never as passed, and the runner check runs
on the records in the repository only. Nicolas's queue wrapper (scripts/nico_queue.ps1) passes --require-trial-log, so
a missing or unreadable trial log is a FAIL there.

Accounts: the folder check runs only as so_agent or nico (it executes the design's import-time code, behind the same
guard as a run). --lint-unregistered reads files only and runs from any account, including CI. Exit code 1 when any
line is FAIL, 2 on a wrong account or wrong arguments, 0 otherwise.
"""

# THE ACCOUNTS THAT MAY RUN THE FOLDER CHECK (THE AGENT BEFORE A REVIEW, NICOLAS BEFORE QUEUEING)
ALLOWED_ACCOUNT_LIST = ["so_agent", "nico"]
# THE LINE MARKS
PASS_STR, FAIL_STR, PENDING_STR, SKIPPED_STR, HAND_STR, INFO_STR = "PASS", "FAIL", "PENDING", "SKIPPED", "HAND", "INFO"
# THE DRAFT MARKER A PREREGISTERED PROTOCOL MAY NOT HOLD
DRAFT_PATTERN = re.compile(r"\bDRAFT\b")
# THE SUBJECT PREFIX OF A PREREGISTER COMMIT (THE RUNNER ACCEPTS IT ANYWHERE IN THE SUBJECT; THE WORKFLOW STARTS WITH IT)
PREREGISTER_PREFIX_STR = "preregister"
# THE ONLY TOP FOLDER A QUEUED JOB MAY CHANGE
EXPERIMENTS_FOLDER_STR = "experiments"
# THE PLAN WHOSE SECTION 4 HOLDS THE FAMILY LEDGER
PLAN_REL_STR = "docs/STAGE1_RESEARCH_PLAN.md"
# THE ADVISED NUMBER OF CANDIDATES PER VERSION (RESEARCH PRACTICE OF 2026-11-17; A GUIDE, NOT A RULE OF THE RUNNER)
ADVISED_CANDIDATE_RANGE_TUPLE = (3, 5)


# FUNCTION: THE ACCOUNT RUNNING THIS PROCESS
def get_account_str():
    """
    Returns:
        str: USERNAME (Windows), else USER, lower case
    """
    # THE SAME SOURCE AS scripts/run_queue.py get_user_str
    return (os.environ.get("USERNAME") or os.environ.get("USER") or "").strip().lower()


# FUNCTION: RUN GIT IN THIS WORKSPACE
def get_git_str(arg_list_in):
    """
    Args:
        arg_list_in (list[str]): git arguments

    Returns:
        str: stdout (raises CalledProcessError on a non-zero exit)
    """
    # TEXT OUT, ERRORS KEPT FOR THE MESSAGE
    return subprocess.check_output(["git"] + list(arg_list_in), cwd=str(WORKSPACE_PATH), text=True, encoding="utf-8",
                                   stderr=subprocess.PIPE)


# FUNCTION: THE ROW OF ONE FAMILY IN THE PLAN'S SECTION 4 TABLE
def get_family_ledger_row_str(family_str_in, plan_text_in=None):
    """
    Args:
        family_str_in (str): Family letter
        plan_text_in (str | None): Plan text (None = docs/STAGE1_RESEARCH_PLAN.md of this workspace)

    Returns:
        str: The table row, or "" when section 4 has no row for the letter
    """
    # SECTION 4 RUNS FROM ITS HEADING TO THE NEXT "## " HEADING
    if plan_text_in is None:
        plan_text_in = (WORKSPACE_PATH / PLAN_REL_STR).read_text(encoding="utf-8")
    in_section_bool = False
    for line_str in str(plan_text_in).splitlines():
        if line_str.startswith("## "):
            in_section_bool = line_str.startswith("## 4.")
            continue
        if in_section_bool and line_str.strip().startswith(f"| **{str(family_str_in).upper()}**"):
            return line_str.strip()
    return ""


# FUNCTION: A LITERAL STRING ASSIGNED AT MODULE LEVEL IN A PYTHON FILE (NO CODE IS RUN)
def get_literal_assignment_str(file_path_in, name_str_in):
    """
    Args:
        file_path_in (Path): Python file
        name_str_in (str): Name, e.g. PROTOCOL_VERSION

    Returns:
        str | None: The string, or None when the file has no "NAME = '<literal>'" at module level
    """
    # THE AST ONLY
    if not Path(file_path_in).is_file():
        return None
    tree = ast.parse(Path(file_path_in).read_text(encoding="utf-8"), filename=str(file_path_in))
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if any(isinstance(target, ast.Name) and target.id == name_str_in for target in node.targets):
                return node.value.value
    return None


# FUNCTION: THE TRIAL LOG, IF THIS ACCOUNT CAN READ IT
def get_trial_log_dict():
    """
    Returns:
        dict: path_str (the readable trial log, or "" when it cannot be read), reason_str
    """
    # SO_DATA_PATH, THEN AN ACTUAL READ (A DENIED FOLDER MAY STILL REPORT THE FILE AS PRESENT)
    try:
        path_str = paths.get_named_data_path_str("LOCAL_TRIAL_LOG_FILE_PATH_STR")
    except RuntimeError:
        return {"path_str": "", "reason_str": "SO_DATA_PATH is not set"}
    try:
        with open(path_str, "rb") as trial_file:
            trial_file.read(1)
    except FileNotFoundError:
        return {"path_str": "", "reason_str": f"no trial log at {path_str}"}
    except OSError as error:
        return {"path_str": "", "reason_str": f"cannot read {path_str} ({type(error).__name__})"}
    return {"path_str": path_str, "reason_str": f"readable: {path_str}"}


# FUNCTION: LOAD THE DESIGN THE WAY A RUN LOADS IT
def get_design_module(folder_path_in):
    """
    scripts/run_development.py load_design_module: preflight, then the import behind the design-code guard, then the
    missing constants from config.py.

    Args:
        folder_path_in (Path): Experiment folder

    Returns:
        module: The design
    """
    # THE RUN'S OWN LOADER, IMPORTED FROM ITS FILE (scripts/ IS NOT A PACKAGE)
    loader_path = WORKSPACE_PATH / "scripts" / "run_development.py"
    spec = importlib.util.spec_from_file_location("so_ready_run_development", str(loader_path))
    loader_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader_module)
    return loader_module.load_design_module(str(folder_path_in))


# CLASS: THE LINES OF ONE CHECK
class ReadyReport:
    """
    Collects the lines and prints each as it is added.
    """

    # FUNCTION: START AN EMPTY REPORT
    def __init__(self):
        """
        Args:
            None

        Returns:
            None
        """
        # MARK, NAME, DETAIL PER LINE
        self.line_list = []

    # FUNCTION: ADD AND PRINT ONE LINE
    def add(self, mark_str_in, name_str_in, detail_str_in=""):
        """
        Args:
            mark_str_in (str): PASS, FAIL, PENDING, SKIPPED, HAND or INFO
            name_str_in (str): What was checked
            detail_str_in (str): Why, or what a person must compare

        Returns:
            None
        """
        # ONE LINE, DETAIL INDENTED BELOW
        self.line_list.append((mark_str_in, name_str_in, str(detail_str_in)))
        print(f"{mark_str_in:<8} {name_str_in}", flush=True)
        for detail_line_str in str(detail_str_in).splitlines():
            print(f"         {detail_line_str}", flush=True)

    # FUNCTION: THE NUMBER OF LINES WITH A MARK
    def get_count_int(self, mark_str_in):
        """
        Args:
            mark_str_in (str): Mark

        Returns:
            int: Count
        """
        # COUNT THE MARK
        return sum(1 for line_tuple in self.line_list if line_tuple[0] == mark_str_in)


# FUNCTION: THE READINESS CHECK OF ONE EXPERIMENT FOLDER
def run_folder_check_report(folder_str_in, draft_bool_in=False, require_trial_log_bool_in=False, base_str_in="origin/main",
                            reviewed_str_in=None):
    """
    Args:
        folder_str_in (str): Experiment folder (relative to the workspace, or absolute inside it)
        draft_bool_in (bool): The protocol is still a draft: DRAFT, the preregister commit, uncommitted changes and
                              files outside experiments/ are PENDING or INFO instead of FAIL, and the runner check is
                              not called
        require_trial_log_bool_in (bool): A trial log that cannot be read is a FAIL (Nicolas before queueing)
        base_str_in (str): Base of the "only experiments/" diff
        reviewed_str_in (str | None): The commit the second review saw; prints what changed in the folder since

    Returns:
        ReadyReport: The lines
    """
    # THE FOLDER MUST BE experiments/<name> OF THIS WORKSPACE
    report = ReadyReport()
    folder_path = Path(folder_str_in)
    folder_path = (folder_path if folder_path.is_absolute() else WORKSPACE_PATH / folder_path).resolve()
    experiments_path = (WORKSPACE_PATH / EXPERIMENTS_FOLDER_STR).resolve()
    if folder_path.parent != experiments_path or not folder_path.is_dir():
        report.add(FAIL_STR, "folder", f"{folder_path} is not a folder directly under {experiments_path}")
        return report
    folder_rel_str = f"{EXPERIMENTS_FOLDER_STR}/{folder_path.name}"
    design_path, protocol_path = folder_path / "design.py", folder_path / "PROTOCOL.md"
    missing_file_list = [name_str for name_str in ("design.py", "config.py", "PROTOCOL.md") if not (folder_path / name_str).is_file()]
    if missing_file_list:
        report.add(FAIL_STR, "files", f"missing in {folder_rel_str}: {', '.join(missing_file_list)}")
        if not design_path.is_file():
            return report
    protocol_text_str = protocol_path.read_text(encoding="utf-8") if protocol_path.is_file() else ""
    # WHERE THIS CHECK STANDS
    try:
        head_str = get_git_str(["rev-parse", "HEAD"]).strip()
    except (OSError, subprocess.CalledProcessError):
        head_str = "unknown"
    report.add(INFO_STR, "workspace", f"{WORKSPACE_PATH}\nHEAD {head_str}\naccount {get_account_str() or 'unknown'}"
                                      f"{chr(10) + 'mode: draft' if draft_bool_in else ''}")
    # 1. THE PREFLIGHT (AST ONLY, NO DESIGN CODE RUNS)
    from so.runner.preflight import check_design_file
    preflight_ok_bool = False
    try:
        check_design_file(str(design_path))
        preflight_ok_bool = True
        report.add(PASS_STR, "preflight", "so.runner.preflight.check_design_file")
    except Exception as error:
        report.add(FAIL_STR, "preflight", f"{type(error).__name__}: {error}")
    # 2. THE DESIGN, LOADED AS THE RUN LOADS IT (ONLY AFTER A CLEAN PREFLIGHT)
    design_module = None
    if preflight_ok_bool:
        try:
            design_module = get_design_module(folder_path)
            report.add(PASS_STR, "design loads", "scripts/run_development.py load_design_module")
        except Exception as error:
            report.add(FAIL_STR, "design loads", f"{type(error).__name__}: {error}")
    else:
        report.add(SKIPPED_STR, "design loads", "not loaded: the preflight failed")
    experiment_str = str(getattr(design_module, "EXPERIMENT_NAME", "")) if design_module is not None else ""
    version_str = str(getattr(design_module, "PROTOCOL_VERSION", "")) if design_module is not None else ""
    # 3. FOLDER NAME = EXPERIMENT_NAME
    if design_module is not None:
        if not experiment_str or not version_str:
            report.add(FAIL_STR, "folder name", "the design has no EXPERIMENT_NAME or no PROTOCOL_VERSION")
        elif experiment_str != folder_path.name:
            report.add(FAIL_STR, "folder name", f"folder {folder_path.name} != EXPERIMENT_NAME {experiment_str}")
        else:
            report.add(PASS_STR, "folder name", f"{experiment_str}, PROTOCOL_VERSION {version_str}")
    # 4. THE PROTOCOL LINT (THE RUNNER'S FUNCTION)
    missing_list = get_protocol_missing_list(protocol_text_str)
    if not missing_list:
        report.add(PASS_STR, "protocol lint", "get_protocol_missing_list returned []")
    else:
        deep_heading_list = [line_str.strip() for line_str in protocol_text_str.splitlines()
                             if line_str.startswith("###") and any(section_str.lower() in line_str.lower() for section_str in missing_list)]
        hint_str = (f"\nthese headings would match as '## ' headings: {deep_heading_list}" if deep_heading_list else "")
        report.add(FAIL_STR, "protocol lint", f"missing: {missing_list}{hint_str}")
    # 5. NO DRAFT MARKER
    draft_line_list = [f"line {idx + 1}: {line_str.strip()[:100]}" for idx, line_str in enumerate(protocol_text_str.splitlines())
                       if DRAFT_PATTERN.search(line_str)]
    if not draft_line_list:
        report.add(PASS_STR, "DRAFT marker", "none in PROTOCOL.md")
    else:
        report.add(PENDING_STR if draft_bool_in else FAIL_STR, "DRAFT marker", "\n".join(draft_line_list[:5]))
    # 6. THE FAMILY LINE NEXT TO THE LEDGER ROW (HAND CHECK)
    family_dict = get_family_line_dict(protocol_text_str)
    if family_dict is not None:
        ledger_row_str = get_family_ledger_row_str(family_dict["family"])
        report.add(HAND_STR, "Family line vs plan section 4",
                   f"protocol: {family_dict['line']}\nsection 4: {ledger_row_str or '(no row for family ' + family_dict['family'] + ')'}\n"
                   f"check: the idea is eligible in this family, and variant {family_dict['variant']} is the next free "
                   f"variant of idea {family_dict['idea']} (versions already used by the idea, across experiments)")
    # 7. THE CANDIDATES (HAND CHECK AGAINST THE PROTOCOL'S TABLE)
    candidate_list = []
    if design_module is not None:
        candidate_list = list(getattr(design_module, "CANDIDATE_LIST", []) or [])
        if not candidate_list:
            report.add(FAIL_STR, "candidates", "CANDIDATE_LIST is missing or empty")
        else:
            low_int, high_int = ADVISED_CANDIDATE_RANGE_TUPLE
            size_note_str = ("" if low_int <= len(candidate_list) <= high_int
                             else f"\nnote: {len(candidate_list)} candidates; research practice is about {low_int}-{high_int} per version")
            report.add(HAND_STR, "candidates vs the protocol's table",
                       f"{len(candidate_list)} in CANDIDATE_LIST: " + ", ".join(repr(candidate) for candidate in candidate_list[:20])
                       + (" ..." if len(candidate_list) > 20 else "") + size_note_str)
    # 8. THE TRIAL LOG
    trial_dict = get_trial_log_dict()
    trial_path_str = trial_dict["path_str"]
    if trial_path_str:
        report.add(PASS_STR, "trial log", trial_dict["reason_str"])
    elif require_trial_log_bool_in:
        report.add(FAIL_STR, "trial log", f"{trial_dict['reason_str']}; --require-trial-log was given")
    else:
        report.add(SKIPPED_STR, "trial log", f"{trial_dict['reason_str']}: versions and candidates logged since the last "
                                             f"reset are not checked here (the runner checks them in the run)")
    # 9. VERSIONS (REGISTERED FILE, PLUS THE TRIAL LOG WHEN READABLE)
    first_run_bool = None
    folder_hash_str = None
    if design_module is not None and experiment_str and version_str:
        from so.runner.run import get_design_folder_hash_str
        registered_path_str = str(WORKSPACE_PATH / REGISTERED_VERSIONS_REL_STR)
        folder_hash_str = get_design_folder_hash_str(str(folder_path))
        registered_version_dict = get_registered_version_tuple(registered_path_str, experiment_str)[0]
        version_dict = get_merged_set_dict(get_logged_version_dict(trial_path_str, experiment_str), registered_version_dict)
        scope_str = "registered_versions.csv and the trial log" if trial_path_str else "registered_versions.csv only"
        if version_str in version_dict:
            first_run_bool = False
            logged_hash_set = version_dict[version_str]
            if logged_hash_set and folder_hash_str not in logged_hash_set:
                report.add(FAIL_STR, "version", f"{experiment_str} {version_str} already ran with different code (folder hash "
                                                f"{folder_hash_str[:12]} not among the logged ones); a change after a run is a new "
                                                f"PROTOCOL_VERSION")
            else:
                report.add(INFO_STR, "version", f"{experiment_str} {version_str} is already logged ({scope_str}): a rerun of "
                                                f"the same code, not a first run")
        else:
            first_run_bool = True
            count_int = len(version_dict) + 1
            report.add(PASS_STR if count_int <= RUNNER_MAX_PROTOCOL_VERSION_COUNT else FAIL_STR, "version",
                       f"{version_str} is new ({scope_str}); it would be version {count_int} of at most "
                       f"{RUNNER_MAX_PROTOCOL_VERSION_COUNT} for {experiment_str}; logged: {sorted(version_dict) or 'none'}")
            family_str = get_experiment_family_str(experiment_str)
            family_version_set = get_family_version_set(trial_path_str, registered_path_str, family_str)
            family_count_int = len(family_version_set) + 1
            report.add(PASS_STR if family_count_int <= RUNNER_MAX_PROTOCOL_VERSION_COUNT else FAIL_STR, "versions of the family",
                       f"version {family_count_int} of at most {RUNNER_MAX_PROTOCOL_VERSION_COUNT} for {family_str} "
                       f"({scope_str}); logged: {sorted(family_version_set) or 'none'}")
            if family_version_set:
                label_str = get_amendment_label_str(protocol_text_str, version_str)
                report.add(PASS_STR if label_str else FAIL_STR, "amendment label",
                           f"change-log row of {version_str}: {label_str or 'needs exactly one of bug-fix / data-dependent'}")
            if not trial_path_str:
                report.add(SKIPPED_STR, "versions logged since the last reset", "needs the trial log")
    # 10. CANDIDATE NAMES ARE NEW DESIGNS IN N (FIRST RUN ONLY, AS IN THE RUNNER)
    if design_module is not None and first_run_bool:
        collision_list = get_candidate_collision_list(design_module, trial_path_str)
        scope_str = "pilot ledger and trial log" if trial_path_str else "pilot ledger only"
        if collision_list:
            report.add(FAIL_STR, "candidate names", f"already logged ({scope_str}): {collision_list[:5]}; rename every "
                                                    f"candidate of an amended version (e.g. 'v{version_str}|<name>')")
        else:
            report.add(PASS_STR, "candidate names", f"none already logged ({scope_str})")
        if not trial_path_str:
            report.add(SKIPPED_STR, "candidate names in the trial log", "needs the trial log")
    # 11. GIT: THE FOLDER IS COMMITTED, ITS LAST COMMIT IS A preregister COMMIT, THE BRANCH CHANGES ONLY experiments/
    try:
        dirty_str = get_git_str(["status", "--porcelain", "--", folder_rel_str]).strip()
        if dirty_str:
            report.add(INFO_STR if draft_bool_in else FAIL_STR, "uncommitted changes", dirty_str)
        else:
            report.add(PASS_STR, "uncommitted changes", f"none in {folder_rel_str}")
        subject_str = get_last_folder_commit_subject_str(str(folder_path))
        if subject_str.lower().startswith(PREREGISTER_PREFIX_STR):
            report.add(PASS_STR, "preregister commit", f"last commit of the folder: {subject_str!r}")
        else:
            report.add(PENDING_STR if draft_bool_in else FAIL_STR, "preregister commit",
                       f"last commit of the folder: {subject_str!r}; expected a subject starting "
                       f"'{PREREGISTER_PREFIX_STR} {experiment_str or folder_path.name}'")
    except (OSError, subprocess.CalledProcessError) as error:
        report.add(FAIL_STR, "git", f"{type(error).__name__}: {getattr(error, 'stderr', '') or error}")
    try:
        base_sha_str = get_git_str(["rev-parse", "--verify", f"{base_str_in}^{{commit}}"]).strip()
        changed_list = [path_str for path_str in get_git_str(["diff", "--name-only", f"{base_str_in}...HEAD"]).splitlines() if path_str]
        outside_list = [path_str for path_str in changed_list if not path_str.startswith(EXPERIMENTS_FOLDER_STR + "/")]
        if outside_list:
            report.add(INFO_STR if draft_bool_in else FAIL_STR, "only experiments/ changed",
                       f"{base_str_in} ({base_sha_str[:8]})...HEAD also changes: {', '.join(outside_list[:15])}"
                       + (" ..." if len(outside_list) > 15 else ""))
        else:
            report.add(PASS_STR, "only experiments/ changed", f"{base_str_in} ({base_sha_str[:8]})...HEAD: {len(changed_list)} file(s), "
                                                              f"all under experiments/")
    except (OSError, subprocess.CalledProcessError) as error:
        report.add(FAIL_STR, "only experiments/ changed", f"cannot diff against {base_str_in} (git fetch origin first?): "
                                                          f"{getattr(error, 'stderr', '') or error}")
    # 12. THE RUNNER'S OWN CHECK, AS THE RUN CALLS IT
    if draft_bool_in:
        report.add(PENDING_STR, "runner check", "check_preregistration_dict is not called in draft mode")
    elif design_module is None or folder_hash_str is None:
        report.add(SKIPPED_STR, "runner check", "the design did not load")
    else:
        from so.runner.preregistration import check_preregistration_dict, get_design_helper_dict
        try:
            helper_hash_str = get_design_helper_dict(str(design_path))["helper_hash"]
            result_dict = check_preregistration_dict(design_module, str(folder_path), folder_hash_str, trial_path_str,
                                                     helper_hash_str_in=helper_hash_str)
            scope_str = ("with the trial log" if trial_path_str
                         else "on the repository's records only (the trial-log part is SKIPPED, not passed)")
            report.add(PASS_STR, "runner check", f"check_preregistration_dict {scope_str}: {result_dict['status_str']}")
        except Exception as error:
            report.add(FAIL_STR, "runner check", f"{type(error).__name__}: {error}")
    # 13. WHAT CHANGED SINCE THE REVIEWED COMMIT (THE THIRD REVIEW, B6)
    if reviewed_str_in:
        try:
            stat_str = get_git_str(["diff", "--stat", f"{reviewed_str_in}..HEAD"]).rstrip()
            folder_diff_str = get_git_str(["diff", "--unified=0", f"{reviewed_str_in}..HEAD", "--", folder_rel_str]).rstrip()
            report.add(HAND_STR, f"changes since the reviewed commit {reviewed_str_in}",
                       (stat_str or "(no change)") + "\n\n" + (folder_diff_str or "(no change in the folder)")
                       + "\n\ncheck: only the DRAFT marker (and the change-log row's status) changed")
        except (OSError, subprocess.CalledProcessError) as error:
            report.add(FAIL_STR, "changes since the reviewed commit", f"{getattr(error, 'stderr', '') or error}")
    return report


# FUNCTION: THE PROTOCOL LINT OF EVERY EXPERIMENT VERSION NOT REGISTERED YET (CI)
def run_unregistered_lint_report(workspace_path_in=WORKSPACE_PATH):
    """
    Reads EXPERIMENT_NAME and PROTOCOL_VERSION as literals from config.py (else design.py), without running any code,
    and lints PROTOCOL.md of every folder whose version is not in records/legacy/registered_versions.csv. Registered
    versions predate the lint and are skipped. Versions logged only in the trial log (CI cannot read it) are linted:
    they passed the lint to run at all.

    Args:
        workspace_path_in (Path): Workspace

    Returns:
        ReadyReport: One line per experiment folder
    """
    # EVERY FOLDER WITH A PROTOCOL, THE TEMPLATE EXCEPTED
    report = ReadyReport()
    registered_path_str = str(Path(workspace_path_in) / REGISTERED_VERSIONS_REL_STR)
    for folder_path in sorted((Path(workspace_path_in) / EXPERIMENTS_FOLDER_STR).iterdir()):
        if not folder_path.is_dir() or folder_path.name.startswith(("_", ".")) or not (folder_path / "PROTOCOL.md").is_file():
            continue
        name_str, version_str = None, None
        for file_name_str in ("config.py", "design.py"):
            name_str = name_str or get_literal_assignment_str(folder_path / file_name_str, "EXPERIMENT_NAME")
            version_str = version_str or get_literal_assignment_str(folder_path / file_name_str, "PROTOCOL_VERSION")
        if not name_str or not version_str:
            report.add(FAIL_STR, folder_path.name, "EXPERIMENT_NAME or PROTOCOL_VERSION is not a string literal in config.py "
                                                   "or design.py")
            continue
        if version_str in get_registered_version_tuple(registered_path_str, name_str)[0]:
            report.add(INFO_STR, folder_path.name, f"{name_str} {version_str} is registered: not linted")
            continue
        problem_list = []
        if name_str != folder_path.name:
            problem_list.append(f"folder name != EXPERIMENT_NAME {name_str}")
        missing_list = get_protocol_missing_list((folder_path / "PROTOCOL.md").read_text(encoding="utf-8"))
        if missing_list:
            problem_list.append(f"protocol lint: missing {missing_list} (## headings only)")
        report.add(FAIL_STR if problem_list else PASS_STR, folder_path.name,
                   "; ".join(problem_list) if problem_list else f"{name_str} {version_str}: protocol lint returned []")
    return report


# PARSE THE COMMAND
if __name__ == "__main__":
    # DEFINE THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Readiness check of an experiment folder before review and queueing "
                                                 "(calls the runner's own checks; decides nothing).")
    parser.add_argument("folder", nargs="?", help="Experiment folder, e.g. experiments/exp15_<name>")
    parser.add_argument("--draft", action="store_true", help="The protocol is still a draft (before the preregister commit)")
    parser.add_argument("--require-trial-log", action="store_true", help="A trial log that cannot be read is a failure (nico)")
    parser.add_argument("--base", default="origin/main", help="Base of the 'only experiments/' diff (default origin/main)")
    parser.add_argument("--reviewed", default=None, help="Commit of the second review: print the changes since")
    parser.add_argument("--lint-unregistered", action="store_true",
                        help="Lint PROTOCOL.md of every version not in registered_versions.csv (CI; any account)")
    arg_dict = parser.parse_args()
    # ONE MODE AT A TIME
    if arg_dict.lint_unregistered:
        if arg_dict.folder:
            print("give either a folder or --lint-unregistered", flush=True)
            sys.exit(2)
        final_report = run_unregistered_lint_report()
    else:
        if not arg_dict.folder:
            print("usage: python scripts/check_experiment_ready.py experiments/<name> [--draft] [--reviewed <commit>]", flush=True)
            sys.exit(2)
        account_str = get_account_str()
        if account_str not in ALLOWED_ACCOUNT_LIST:
            print(f"STOP: run this check as {' or '.join(ALLOWED_ACCOUNT_LIST)} (this process runs as {account_str or 'unknown'})",
                  flush=True)
            sys.exit(2)
        final_report = run_folder_check_report(arg_dict.folder, arg_dict.draft, arg_dict.require_trial_log, arg_dict.base,
                                               arg_dict.reviewed)
    # THE SUMMARY AND THE EXIT CODE
    fail_int = final_report.get_count_int(FAIL_STR)
    print(f"\nsummary: {fail_int} FAIL, {final_report.get_count_int(PENDING_STR)} PENDING, "
          f"{final_report.get_count_int(SKIPPED_STR)} SKIPPED, {final_report.get_count_int(HAND_STR)} HAND, "
          f"{final_report.get_count_int(PASS_STR)} PASS", flush=True)
    print("NOT READY" if fail_int else "no failure found (SKIPPED and HAND lines still need their check)", flush=True)
    sys.exit(1 if fail_int else 0)
