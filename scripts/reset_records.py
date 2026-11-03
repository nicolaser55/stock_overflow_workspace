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
from run_queue import get_queue_path_dict
from append_results_log import RESULTS_LOG_PATH, PHASE_DEVELOPMENT_STR, get_agent_phase_str

"""
Reset The Development Records (Nicolas only, development phase only; roadmap R4, decided 2026-11-03)

Results produced while the system is still being built are disposable; the count of what was tried is not. This
script discards the results and keeps the count:

    1. refuses unless records/agent_phase.txt says "development" (from R6 nothing is ever reset), the runner is not
       running and queue/pending and queue/running are empty;
    2. adds every design of the trial log that the tried-designs ledger (records/legacy/pilot_designs.csv) does not
       hold yet: family and settings only, bookkeeping keys and numbers dropped, source "trial_log_reset_<date>";
    3. checks that N with the pilot included is the same before and after (nothing tried is forgotten);
    4. moves the trial log, the run index, the run folders, the checks, the finished, failed and rejected jobs, the
       logs, the outbox and the visible grades and statuses into <backup folder>/reset_<timestamp>/ (moved, not
       deleted; the backup folder must be outside the data root, where no agent can read);
    5. appends a dated "withdrawn" note row to docs/RESULTS_LOG.md (the log stays append-only).

Stop the scheduled task "SO queue runner" first (Stop-ScheduledTask) and start it again afterwards, so no job can start
in between. Then commit records/legacy/pilot_designs.csv and docs/RESULTS_LOG.md on a branch and open a pull request.

    python scripts/reset_records.py --backup-folder D:\\stock_overflow\\backup_records             # dry run
    python scripts/reset_records.py --backup-folder D:\\stock_overflow\\backup_records --confirm   # reset
"""

# WHAT IS MOVED (queue path keys, then names under store04_experiments)
MOVED_QUEUE_KEY_LIST = ["runs", "done", "failed", "rejected", "logs", "outbox"]
MOVED_ZONE_NAME_LIST = ["trial_log.csv", "trial_log.csv.lock", "run_index.csv", "run_index.csv.lock", "checks",
                        "visible/grades", "visible/status", "visible/state.json"]
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
    for name_str in sorted(os.listdir(zone_str)) if os.path.isdir(zone_str) else []:
        if name_str.startswith("run_index.csv.before_"):
            move_list.append((os.path.join(zone_str, name_str), name_str))
    return move_list


# FUNCTION: WHY A RESET IS REFUSED ("" WHEN IT MAY RUN)
def get_refusal_str(path_dict_in, backup_folder_str_in, phase_str_in):
    """
    Args:
        path_dict_in (dict): Queue paths
        backup_folder_str_in (str): Backup folder
        phase_str_in (str): The phase switch

    Returns:
        str: The reason, or ""
    """
    # THE PHASE, THE RUNNER, THE QUEUE, THE BACKUP FOLDER
    if phase_str_in != PHASE_DEVELOPMENT_STR:
        return f"records/agent_phase.txt says {phase_str_in!r}: from the agent phase on nothing is reset"
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
                       ledger_path_str_in=None, results_log_path_in=RESULTS_LOG_PATH, phase_str_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        backup_folder_str_in (str): Folder outside the data root that receives reset_<timestamp>/
        confirm_bool_in (bool): False = dry run (nothing changes)
        now_in (datetime.datetime | None): Clock (tests)
        ledger_path_str_in (str | None): Ledger (None = records/legacy/pilot_designs.csv of this workspace)
        results_log_path_in (Path): docs/RESULTS_LOG.md
        phase_str_in (str | None): Phase (None = records/agent_phase.txt)

    Returns:
        dict: refused_str, new_ledger_row_count, pilot_included_before, pilot_included_after, move_list, target_str
    """
    # REFUSE FIRST; A DRY RUN STILL SHOWS WHAT WOULD HAPPEN
    now = now_in or datetime.datetime.now()
    ledger_path_str = ledger_path_str_in or os.path.join(paths.WORKSPACE_PATH_STR, *PILOT_LEDGER_REL_STR.split("/"))
    trial_log_path_str = os.path.join(os.path.dirname(path_dict_in["old_state"]), "trial_log.csv")
    refused_str = get_refusal_str(path_dict_in, backup_folder_str_in, phase_str_in or get_agent_phase_str())
    source_str = f"trial_log_reset_{now:%Y%m%d}"
    new_row_list = get_new_ledger_row_list(trial_log_path_str, ledger_path_str, source_str)
    before_int = get_tried_design_count_dict(trial_log_path_str, [ledger_path_str])["pilot_included_count"]
    target_str = os.path.join(os.path.abspath(backup_folder_str_in), f"reset_{now:%Y%m%d_%H%M%S}")
    result_dict = {"refused_str": refused_str, "new_ledger_row_count": len(new_row_list),
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
                f"records/legacy/pilot_designs.csv |")
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
    parser.add_argument("--backup-folder", required=True, help="Folder outside the data root (e.g. D:\\stock_overflow\\backup_records)")
    parser.add_argument("--confirm", action="store_true", help="Reset (without it: show what would happen)")
    arg_dict = parser.parse_args()
    outcome_dict = reset_records_dict(get_queue_path_dict(), arg_dict.backup_folder, arg_dict.confirm)
    if outcome_dict["refused_str"]:
        raise SystemExit(f"refused: {outcome_dict['refused_str']}")
    print(f"ledger rows to add: {outcome_dict['new_ledger_row_count']}; N with the pilot included: "
          f"{outcome_dict['pilot_included_before']}")
    for source_path_str, name_str in outcome_dict["move_list"]:
        print(f"{'moved' if outcome_dict['done_bool'] else 'would move'} {source_path_str} -> {outcome_dict['target_str']}\\{name_str}")
    if outcome_dict["done_bool"]:
        print(f"done; N with the pilot included after the reset: {outcome_dict['pilot_included_after']}. Commit "
              f"records/legacy/pilot_designs.csv and docs/RESULTS_LOG.md on a branch and open a pull request.")
    else:
        print("dry run: nothing changed (add --confirm to reset)")
