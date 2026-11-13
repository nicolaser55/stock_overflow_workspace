import argparse
import csv
import datetime
import json
import os
import shutil
import sys
from pathlib import Path

# ADD THE WORKSPACE AND THE SCRIPTS FOLDER TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parent))
# IMPORT THE DESIGN KEYS, THE QUEUE PATHS AND THE PHASE SWITCH
from so import paths
from so.core.multiple_testing import (BOOKKEEPING_KEY_SET, NON_DESIGN_STAGE_SET, PILOT_LEDGER_REL_STR,
                                      get_design_key_set, get_design_key_str, get_tried_design_count_dict,
                                      read_trial_record_pdf)
from so.runner.preregistration import (REGISTERED_VERSION_COLUMN_LIST, get_logged_helper_dict, get_logged_version_dict,
                                       get_registered_version_tuple, get_registered_versions_path_str,
                                       get_trial_log_version_row_list)
from run_queue import get_queue_path_dict
from append_results_log import RESULTS_LOG_PATH, PHASE_DEVELOPMENT_STR, get_agent_phase_str

"""
Reset The Development Records (Nicolas only, development phase only; roadmap R4, decided 2026-11-03)

Results produced while the system is still being built are disposable; the count of what was tried is not. This
script discards the results and keeps the count:

    1. refuses unless records/agent_phase.txt says "development" (from R6 nothing is ever reset), the kill switch
       <SO_DATA_PATH>/control/STOP exists (decided 2026-11-10), the runner holds no lock and queue/pending and
       queue/running are empty. The kill switch must be confirmed: a flag that is missing or cannot be read refuses (the
       runner reads an unreadable flag as set; for a reset the safe reading is the opposite), and so does
       SO_STOP_FLAG_PATH set in this window (the reset could not tell which flag the runner's account reads). Why: the
       runner takes its lock only during a pass, so the lock alone cannot show that the task is stopped (on 2026-11-09 a
       reset ran with the task still running, after a PowerShell check failed open). With STOP set the runner starts no
       job and resumes none; only Nicolas can write control/;
    2. adds every design of the trial log that the tried-designs ledger (records/legacy/pilot_designs.csv) does not
       hold yet: family and settings only, bookkeeping keys and numbers dropped, source "trial_log_reset_<date>";
    3. checks that N with the pilot included is the same before and after (nothing tried is forgotten);
    4. adds every (experiment, protocol version, folder hash, helper hash) of the trial log that
       records/legacy/registered_versions.csv does not hold yet, and checks that the file now gives the pre-registration
       guard everything the trial log gave it (2026-11-09: the first reset moved the log and the guard took every logged
       version for a new one, so all nine baseline reruns were refused);
    5. moves the trial log, the run index, the run folders, the checks, the finished, failed and rejected jobs, the
       logs, the outbox, visible/state.json and the files inside visible/grades and visible/status into
       <backup folder>/reset_<timestamp>/ (moved, not deleted; the backup folder must be outside the data root, where
       no agent can read). The folders visible/grades and visible/status stay, with the read grants
       scripts/setup_so_agent.ps1 gave them (a folder the runner recreates would only inherit);
    6. appends a dated "withdrawn" note row to docs/RESULTS_LOG.md (the log stays append-only).

Create the kill switch first (New-Item <SO_DATA_PATH>\\control\\STOP) and stop the scheduled task "SO queue runner"
(Stop-ScheduledTask, in an elevated window). Both: before R4d (2026-11-12) the runner's idle loop rewrote
visible/state.json and recreated empty queue folders about every 60 s even with STOP set; it now writes nothing while
STOP is set, so after a reset under STOP visible/state.json is absent until STOP is removed (the deploy check and the
status command then read the queue folders, not state.json). Stopping the task stays the belt to that brace. A refused command prints
the plan, then the reason, and exits 1; nothing changes. Then commit records/legacy/pilot_designs.csv,
records/legacy/registered_versions.csv and docs/RESULTS_LOG.md on a branch and open a pull request. When either records
file changed, merge and deploy before starting the task again: the runner reads the deployed copies.

    python scripts/reset_records.py --backup-folder D:\\stock_overflow\\backup_records             # dry run
    python scripts/reset_records.py --backup-folder D:\\stock_overflow\\backup_records --confirm   # reset
    python scripts/reset_records.py --register-from <a backed-up trial_log.csv> [--confirm]
        # only step 4, from a trial log an earlier reset moved (dry run unless --confirm); nothing is moved
"""

# WHAT IS MOVED (queue path keys, then names under store04_experiments)
MOVED_QUEUE_KEY_LIST = ["runs", "done", "failed", "rejected", "logs", "outbox"]
MOVED_ZONE_NAME_LIST = ["trial_log.csv", "trial_log.csv.lock", "run_index.csv", "run_index.csv.lock", "checks",
                        "visible/state.json"]
# FOLDERS WHOSE CONTENTS ARE MOVED AND WHICH STAY (THEIR OWN ACLs: scripts/setup_so_agent.ps1)
KEPT_FOLDER_NAME_LIST = ["visible/grades", "visible/status"]
# THE LEDGER COLUMNS
LEDGER_COLUMN_LIST = ["source", "experiment", "stage", "setting_json"]


# FUNCTION: THE LEDGER ROWS A TRIAL LOG ADDS
def get_new_ledger_row_list(trial_log_path_str_in, ledger_path_str_in, source_str_in):
    """
    Args:
        trial_log_path_str_in (str): Trial log
        ledger_path_str_in (str): records/legacy/pilot_designs.csv
        source_str_in (str): Source label of the new rows

    Returns:
        list[dict]: One row per design key of the trial log that the ledger lacks (settings without bookkeeping)
    """
    # THE KEYS THE LEDGER HOLDS, THEN THE TRIAL LOG'S DESIGN ROWS
    ledger_key_set = get_design_key_set(read_trial_record_pdf(ledger_path_str_in))
    record_pdf = read_trial_record_pdf(trial_log_path_str_in)
    row_list, seen_set = [], set()
    if len(record_pdf) == 0:
        return row_list
    for experiment_str, stage_str, setting_str in zip(record_pdf["experiment"], record_pdf["stage"], record_pdf["setting_json"]):
        if str(stage_str) in NON_DESIGN_STAGE_SET:
            continue
        key_str = get_design_key_str(experiment_str, setting_str)
        if key_str in ledger_key_set or key_str in seen_set:
            continue
        try:
            setting_value = json.loads(setting_str) if str(setting_str).strip() else {}
        except ValueError:
            setting_value = {"raw": setting_str}
        if not isinstance(setting_value, dict):
            setting_value = {"value": setting_value}
        kept_dict = {name_str: value for name_str, value in setting_value.items() if name_str not in BOOKKEEPING_KEY_SET}
        row_list.append({"source": source_str_in, "experiment": str(experiment_str), "stage": str(stage_str),
                         "setting_json": json.dumps(kept_dict, sort_keys=True, default=str)})
        seen_set.add(key_str)
    return row_list


# FUNCTION: APPEND ROWS TO THE LEDGER
def append_ledger_row_list(ledger_path_str_in, row_list_in):
    """
    Args:
        ledger_path_str_in (str): records/legacy/pilot_designs.csv
        row_list_in (list[dict]): Rows

    Returns:
        int: Rows appended
    """
    # THE HEADER IS WRITTEN ONLY FOR A NEW FILE
    new_bool = not os.path.isfile(ledger_path_str_in) or os.path.getsize(ledger_path_str_in) == 0
    with open(ledger_path_str_in, "a", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=LEDGER_COLUMN_LIST, lineterminator="\n")
        if new_bool:
            writer.writeheader()
        for row_dict in row_list_in:
            writer.writerow(row_dict)
    return len(row_list_in)


# FUNCTION: THE REGISTERED-VERSION ROWS A TRIAL LOG ADDS
def get_new_registered_row_list(trial_log_path_str_in, registered_path_str_in, source_str_in):
    """
    Args:
        trial_log_path_str_in (str): Trial log
        registered_path_str_in (str): records/legacy/registered_versions.csv
        source_str_in (str): Source label of the new rows

    Returns:
        list[dict]: The trial log's (experiment, version, folder hash, helper hash) rows the file lacks
    """
    # COMPARE ON THE FOUR KEY COLUMNS, NOT THE SOURCE
    held_set = set()
    if os.path.isfile(registered_path_str_in) and os.path.getsize(registered_path_str_in) > 0:
        held_pdf = read_trial_record_pdf(registered_path_str_in)
        if len(held_pdf):
            get_registered_version_tuple(registered_path_str_in, "")        # REFUSES A FILE WITHOUT THE COLUMNS
            held_set = set(zip(held_pdf["experiment"], held_pdf["protocol_version"], held_pdf["design_folder_hash"],
                               held_pdf["helper_hash"]))
    return [row_dict for row_dict in get_trial_log_version_row_list(trial_log_path_str_in, source_str_in)
            if (row_dict["experiment"], row_dict["protocol_version"], row_dict["design_folder_hash"],
                row_dict["helper_hash"]) not in held_set]


# FUNCTION: APPEND ROWS TO THE REGISTERED-VERSIONS FILE
def append_registered_row_list(registered_path_str_in, row_list_in):
    """
    Args:
        registered_path_str_in (str): records/legacy/registered_versions.csv
        row_list_in (list[dict]): Rows

    Returns:
        int: Rows appended
    """
    # THE HEADER IS WRITTEN ONLY FOR A NEW FILE
    new_bool = not os.path.isfile(registered_path_str_in) or os.path.getsize(registered_path_str_in) == 0
    os.makedirs(os.path.dirname(os.path.abspath(registered_path_str_in)), exist_ok=True)
    with open(registered_path_str_in, "a", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=REGISTERED_VERSION_COLUMN_LIST, lineterminator="\n")
        if new_bool:
            writer.writeheader()
        for row_dict in row_list_in:
            writer.writerow(row_dict)
    return len(row_list_in)


# FUNCTION: THE EXPERIMENTS WHOSE GUARD VIEW THE REGISTERED-VERSIONS FILE DOES NOT REPRODUCE
def get_registered_gap_list(trial_log_path_str_in, registered_path_str_in):
    """
    For every experiment of the trial log, the versions, folder hashes and helper hashes the guard reads from the trial
    log must all be in the file (the file may hold more: earlier resets).

    Args:
        trial_log_path_str_in (str): Trial log
        registered_path_str_in (str): records/legacy/registered_versions.csv

    Returns:
        list[str]: Experiments with a gap (empty when the file covers the log)
    """
    # COMPARE PER EXPERIMENT AND VERSION
    record_pdf = read_trial_record_pdf(trial_log_path_str_in)
    if len(record_pdf) == 0 or "protocol_version" not in record_pdf.columns:
        return []
    gap_list = []
    for experiment_str in sorted(set(str(value) for value in record_pdf["experiment"])):
        log_version_dict = get_logged_version_dict(trial_log_path_str_in, experiment_str)
        log_helper_dict = get_logged_helper_dict(trial_log_path_str_in, experiment_str)
        held_version_dict, held_helper_dict = get_registered_version_tuple(registered_path_str_in, experiment_str)
        for version_str, hash_set in log_version_dict.items():
            if (version_str not in held_version_dict or not hash_set <= held_version_dict[version_str]
                    or not log_helper_dict.get(version_str, set()) <= held_helper_dict.get(version_str, set())):
                gap_list.append(experiment_str)
                break
    return gap_list


# FUNCTION: REGISTER THE VERSIONS OF A TRIAL LOG (STEP 4 ALONE, FOR A LOG AN EARLIER RESET MOVED)
def register_versions_dict(trial_log_path_str_in, confirm_bool_in=False, registered_path_str_in=None, source_str_in=None):
    """
    Args:
        trial_log_path_str_in (str): A trial log (for example a backed-up one)
        confirm_bool_in (bool): False = dry run
        registered_path_str_in (str | None): None = records/legacy/registered_versions.csv of this workspace
        source_str_in (str | None): None = "trial_log_<name of the log's folder>"

    Returns:
        dict: new_row_count, experiment_count, gap_list (after the append; empty on success), done_bool
    """
    # A LOG THAT DOES NOT EXIST IS AN ERROR HERE (A RESET MAY HAVE NONE, A REGISTRATION MAY NOT)
    if not os.path.isfile(trial_log_path_str_in):
        raise FileNotFoundError(f"trial log not found: {trial_log_path_str_in}")
    registered_path_str = registered_path_str_in or get_registered_versions_path_str()
    source_str = source_str_in or f"trial_log_{os.path.basename(os.path.dirname(os.path.abspath(trial_log_path_str_in)))}"
    new_row_list = get_new_registered_row_list(trial_log_path_str_in, registered_path_str, source_str)
    result_dict = {"new_row_count": len(new_row_list),
                   "experiment_count": len({row_dict["experiment"] for row_dict in
                                            get_trial_log_version_row_list(trial_log_path_str_in, source_str)}),
                   "gap_list": None, "done_bool": False}
    if not confirm_bool_in:
        return result_dict
    append_registered_row_list(registered_path_str, new_row_list)
    result_dict["gap_list"] = get_registered_gap_list(trial_log_path_str_in, registered_path_str)
    if result_dict["gap_list"]:
        raise RuntimeError(f"registered_versions.csv does not cover the trial log for {result_dict['gap_list']}")
    result_dict["done_bool"] = True
    return result_dict


# FUNCTION: WHAT A RESET WOULD MOVE
def get_move_list(path_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths

    Returns:
        list[tuple[str, str]]: (source path, name inside the backup folder) for each item that exists
    """
    # QUEUE FOLDERS, THEN THE ZONE'S FILES AND FOLDERS
    zone_str = os.path.dirname(path_dict_in["old_state"])
    move_list = []
    for key_str in MOVED_QUEUE_KEY_LIST:
        if os.path.exists(path_dict_in[key_str]):
            move_list.append((path_dict_in[key_str], os.path.relpath(path_dict_in[key_str], zone_str)))
    for name_str in MOVED_ZONE_NAME_LIST:
        source_str = os.path.join(zone_str, *name_str.split("/"))
        if os.path.exists(source_str):
            move_list.append((source_str, name_str))
    for name_str in KEPT_FOLDER_NAME_LIST:
        folder_str = os.path.join(zone_str, *name_str.split("/"))
        for child_str in sorted(os.listdir(folder_str)) if os.path.isdir(folder_str) else []:
            move_list.append((os.path.join(folder_str, child_str), f"{name_str}/{child_str}"))
    for name_str in sorted(os.listdir(zone_str)) if os.path.isdir(zone_str) else []:
        if name_str.startswith("run_index.csv.before_"):
            move_list.append((os.path.join(zone_str, name_str), name_str))
    return move_list


# FUNCTION: WHY THE KILL SWITCH DOES NOT ALLOW A RESET ("" WHEN IT IS CONFIRMED SET)
def get_stop_flag_refusal_str(path_dict_in, environment_dict_in=None):
    """
    The opposite reading of run_queue.get_stop_flag_bool, on the same path (run_queue.get_stop_flag_path_str): there, a
    flag that cannot be read counts as set (the runner stops); here only a flag whose existence is confirmed allows the
    reset.

    Args:
        path_dict_in (dict): Queue paths (stop_flag)
        environment_dict_in (dict | None): Environment (None = os.environ; tests)

    Returns:
        str: The reason, or ""
    """
    # AN OVERRIDE IN THIS WINDOW MAY NOT BE WHAT THE RUNNER'S ACCOUNT READS
    environment_dict = os.environ if environment_dict_in is None else environment_dict_in
    if str(environment_dict.get("SO_STOP_FLAG_PATH", "")).strip():
        return ("SO_STOP_FLAG_PATH is set in this window: the reset cannot tell which kill switch the runner reads; "
                "remove it ($env:SO_STOP_FLAG_PATH = $null) and use <SO_DATA_PATH>\\control\\STOP")
    flag_str = path_dict_in.get("stop_flag") or ""
    if not flag_str:
        return "no kill-switch path (SO_DATA_PATH is not set)"
    try:
        os.stat(flag_str)
    except FileNotFoundError:
        return f"the kill switch {flag_str} does not exist: create it first (then the runner starts no job)"
    except OSError as error:
        return f"the kill switch {flag_str} cannot be checked ({type(error).__name__}): a reset needs it confirmed"
    return ""


# FUNCTION: WHY A RESET IS REFUSED ("" WHEN IT MAY RUN)
def get_refusal_str(path_dict_in, backup_folder_str_in, phase_str_in, environment_dict_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        backup_folder_str_in (str): Backup folder
        phase_str_in (str): The phase switch
        environment_dict_in (dict | None): Environment for the kill-switch check (None = os.environ; tests)

    Returns:
        str: The reason, or ""
    """
    # THE PHASE, THE KILL SWITCH, THE RUNNER, THE QUEUE, THE BACKUP FOLDER
    if phase_str_in != PHASE_DEVELOPMENT_STR:
        return f"records/agent_phase.txt says {phase_str_in!r}: from the agent phase on nothing is reset"
    stop_refusal_str = get_stop_flag_refusal_str(path_dict_in, environment_dict_in)
    if stop_refusal_str:
        return stop_refusal_str
    if os.path.exists(path_dict_in["lock"]):
        return f"the runner holds {path_dict_in['lock']}: stop the task (or wait for the job) first"
    for key_str in ["pending", "running"]:
        folder_str = path_dict_in[key_str]
        if os.path.isdir(folder_str) and any(name_str.endswith(".json") for name_str in os.listdir(folder_str)):
            return f"queue/{key_str} is not empty"
    data_root_str = os.path.abspath(paths.get_data_root_str())
    backup_abs_str = os.path.abspath(backup_folder_str_in)
    if os.path.normcase(backup_abs_str + os.sep).startswith(os.path.normcase(data_root_str.rstrip("\\/") + os.sep)):
        return "the backup folder must be outside the data root"
    if not os.path.isdir(backup_abs_str):
        return f"backup folder not found: {backup_abs_str}"
    return ""


# FUNCTION: THE RESET
def reset_records_dict(path_dict_in, backup_folder_str_in, confirm_bool_in=False, now_in=None,
                       ledger_path_str_in=None, results_log_path_in=RESULTS_LOG_PATH, phase_str_in=None,
                       registered_path_str_in=None, environment_dict_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        backup_folder_str_in (str): Folder outside the data root that receives reset_<timestamp>/
        confirm_bool_in (bool): False = dry run (nothing changes)
        now_in (datetime.datetime | None): Clock (tests)
        ledger_path_str_in (str | None): Ledger (None = records/legacy/pilot_designs.csv of this workspace)
        results_log_path_in (Path): docs/RESULTS_LOG.md
        phase_str_in (str | None): Phase (None = records/agent_phase.txt)
        registered_path_str_in (str | None): None = records/legacy/registered_versions.csv of this workspace
        environment_dict_in (dict | None): Environment for the kill-switch check (None = os.environ; tests)

    Returns:
        dict: refused_str, new_ledger_row_count, new_registered_row_count, pilot_included_before,
              pilot_included_after, move_list, target_str
    """
    # REFUSE FIRST; THE PLAN IS STILL RETURNED (THE COMMAND PRINTS IT BEFORE THE REASON)
    now = now_in or datetime.datetime.now()
    ledger_path_str = ledger_path_str_in or os.path.join(paths.WORKSPACE_PATH_STR, *PILOT_LEDGER_REL_STR.split("/"))
    trial_log_path_str = os.path.join(os.path.dirname(path_dict_in["old_state"]), "trial_log.csv")
    refused_str = get_refusal_str(path_dict_in, backup_folder_str_in, phase_str_in or get_agent_phase_str(),
                                  environment_dict_in)
    source_str = f"trial_log_reset_{now:%Y%m%d}"
    new_row_list = get_new_ledger_row_list(trial_log_path_str, ledger_path_str, source_str)
    registered_path_str = registered_path_str_in or get_registered_versions_path_str()
    new_registered_row_list = get_new_registered_row_list(trial_log_path_str, registered_path_str, source_str)
    before_int = get_tried_design_count_dict(trial_log_path_str, [ledger_path_str])["pilot_included_count"]
    target_str = os.path.join(os.path.abspath(backup_folder_str_in), f"reset_{now:%Y%m%d_%H%M%S}")
    result_dict = {"refused_str": refused_str, "new_ledger_row_count": len(new_row_list),
                   "new_registered_row_count": len(new_registered_row_list),
                   "pilot_included_before": before_int, "pilot_included_after": None,
                   "move_list": get_move_list(path_dict_in), "target_str": target_str, "done_bool": False}
    if refused_str or not confirm_bool_in:
        return result_dict
    # THE LEDGER GROWS, THEN THE COUNT IS CHECKED AGAINST AN EMPTY TRIAL LOG (WHAT THE NEXT RUN WILL SEE)
    append_ledger_row_list(ledger_path_str, new_row_list)
    after_int = get_tried_design_count_dict(os.path.join(target_str, "no_trial_log.csv"), [ledger_path_str])["pilot_included_count"]
    result_dict["pilot_included_after"] = after_int
    if after_int != before_int:
        raise RuntimeError(f"the ledger would forget designs: pilot-included N {before_int} before, {after_int} after; "
                           f"nothing was moved")
    # THE REGISTERED VERSIONS GROW, THEN MUST GIVE THE GUARD EVERYTHING THE TRIAL LOG GAVE IT
    append_registered_row_list(registered_path_str, new_registered_row_list)
    gap_list = get_registered_gap_list(trial_log_path_str, registered_path_str)
    if gap_list:
        raise RuntimeError(f"registered_versions.csv would forget logged versions of {gap_list}; nothing was moved")
    # MOVE (NOT DELETE) EVERYTHING THAT HOLDS RESULTS
    os.makedirs(target_str, exist_ok=False)
    for source_path_str, name_str in result_dict["move_list"]:
        dest_str = os.path.join(target_str, *name_str.replace("\\", "/").split("/"))
        os.makedirs(os.path.dirname(dest_str), exist_ok=True)
        shutil.move(source_path_str, dest_str)
    # ONE NOTE ROW IN THE RESULTS LOG (APPEND-ONLY)
    note_str = (f"| {now:%Y-%m-%d} | all rows above | n/a | n/a | withdrawn | n/a | n/a | n/a | reset by "
                f"scripts/reset_records.py: results produced before this date are discarded (moved to "
                f"{os.path.basename(target_str)} in the backup folder); the designs they tried stay counted in "
                f"records/legacy/pilot_designs.csv and their versions in records/legacy/registered_versions.csv |")
    log_text_str = Path(results_log_path_in).read_text(encoding="utf-8")
    with open(results_log_path_in, "a", encoding="utf-8", newline="\n") as file_obj:
        if not log_text_str.endswith("\n"):
            file_obj.write("\n")
        file_obj.write(note_str + "\n")
    result_dict["done_bool"] = True
    return result_dict


# PARSE THE COMMAND
if __name__ == "__main__":
    # DRY RUN UNLESS --confirm
    parser = argparse.ArgumentParser(description="Discard development results; keep the count of designs tried.")
    parser.add_argument("--backup-folder", help="Folder outside the data root (e.g. D:\\stock_overflow\\backup_records)")
    parser.add_argument("--register-from", help="Only register the versions of this (backed-up) trial log; move nothing")
    parser.add_argument("--confirm", action="store_true", help="Reset (without it: show what would happen)")
    arg_dict = parser.parse_args()
    if arg_dict.register_from:
        if arg_dict.backup_folder:
            raise SystemExit("refused: --register-from and --backup-folder are separate operations")
        register_dict = register_versions_dict(arg_dict.register_from, arg_dict.confirm)
        print(f"registered-version rows to add: {register_dict['new_row_count']} "
              f"(experiments in the log: {register_dict['experiment_count']})")
        if register_dict["done_bool"]:
            print("done; records/legacy/registered_versions.csv covers the log. Commit it on a branch and open a pull "
                  "request; merge and deploy before the next run.")
        else:
            print("dry run: nothing changed (add --confirm to register)")
        raise SystemExit(0)
    if not arg_dict.backup_folder:
        raise SystemExit("refused: --backup-folder is required for a reset")
    outcome_dict = reset_records_dict(get_queue_path_dict(), arg_dict.backup_folder, arg_dict.confirm)
    print(f"ledger rows to add: {outcome_dict['new_ledger_row_count']}; registered-version rows to add: "
          f"{outcome_dict['new_registered_row_count']}; N with the pilot included: {outcome_dict['pilot_included_before']}")
    for source_path_str, name_str in outcome_dict["move_list"]:
        print(f"{'moved' if outcome_dict['done_bool'] else 'would move'} {source_path_str} -> {outcome_dict['target_str']}\\{name_str}")
    if outcome_dict["refused_str"]:
        # THE PLAN ABOVE, THEN THE REASON; EXIT 1 (A DRY RUN TOO: A BLOCK THAT CHECKS THE EXIT CODE STOPS HERE)
        raise SystemExit(f"refused: {outcome_dict['refused_str']} (nothing changed)")
    if outcome_dict["done_bool"]:
        print(f"done; N with the pilot included after the reset: {outcome_dict['pilot_included_after']}. Commit "
              f"records/legacy/pilot_designs.csv, records/legacy/registered_versions.csv and docs/RESULTS_LOG.md on a "
              f"branch and open a pull request.")
    else:
        print("dry run: nothing changed (add --confirm to reset)")
