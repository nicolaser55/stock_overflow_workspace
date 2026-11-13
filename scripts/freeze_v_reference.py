import argparse
import csv
import datetime
import getpass
import json
import os
import sys
from pathlib import Path

# ADD THE WORKSPACE AND THE SCRIPTS FOLDER TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(1, str(Path(__file__).resolve().parent))
# IMPORT THE REFERENCE BUILDER, THE QUEUE PATHS AND THE KILL-SWITCH RULE OF THE RESET
from so import paths
from so.core.multiple_testing import (VReferenceError, build_v_reference_dict, get_v_reference_path_str,
                                      read_v_reference_dict)
from run_queue import get_queue_path_dict
from reset_records import get_stop_flag_refusal_str

"""
Freeze The Reference V (Nicolas only; R4d, decided 2026-11-12)

The verdict's deflated Sharpe ratio uses V, the spread of Sharpe ratios across the designs tried. A run on the real
development view reads V from a frozen file, so its verdict does not depend on queue order, reruns or resets
(so.core.multiple_testing, "the frozen V"). This script builds that file from the trial log: one entry per design key,
each design's latest run only.

    python scripts/freeze_v_reference.py                          dry run: what would be written
    python scripts/freeze_v_reference.py --confirm --note "<why>" write it

Refuses (exit 1, nothing written) unless the kill switch <SO_DATA_PATH>/control/STOP is confirmed to exist (the rule of
scripts/reset_records.py; SO_STOP_FLAG_PATH set in the window refuses), no job is running (the queue's running/ folder
is empty), the quarantine root is not set (so.paths.check_quarantine_refused), and the trial log gives at least MT_MIN_DESIGN_COUNT designs.

Writes <SO_DATA_PATH>/store04_experiments/judge/v_reference.json (write to a temporary file, then replace). A file that
was there is kept beside it as v_reference_<its build time>.json. Every write appends a row to v_reference_log.csv in
the same folder. The reset (scripts/reset_records.py) does not move this folder. Output: counts, the variance and the
hashes; no market data and no data dates.

Stage 1 refreshes the reference only at a reset; the policy from R6 is decided before R6.
"""

# THE LOG BESIDE THE REFERENCE
V_REFERENCE_LOG_NAME_STR = "v_reference_log.csv"
V_REFERENCE_LOG_COLUMN_LIST = ["built_ts", "built_by", "variance", "design_count", "experiment_count", "run_count",
                               "trial_log_sha256", "content_sha256", "replaced_file", "note"]


# FUNCTION: WHY THE REFERENCE MAY NOT BE WRITTEN NOW ("" WHEN IT MAY)
def get_freeze_refusal_str(path_dict_in, environment_dict_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths (stop_flag, running)
        environment_dict_in (dict | None): Environment (None = os.environ; tests)

    Returns:
        str: The reason, or ""
    """
    # THE QUARANTINE NEVER (READ FROM THIS PROCESS, THROUGH so.paths: THE ONLY PLACE THAT NAMES IT), THE KILL SWITCH
    # CONFIRMED, NO JOB RUNNING
    environment_dict = os.environ if environment_dict_in is None else environment_dict_in
    try:
        paths.check_quarantine_refused()
    except RuntimeError:
        return "the quarantine root is set in this window (so.paths.check_quarantine_refused); open a window without it"
    stop_refusal_str = get_stop_flag_refusal_str(path_dict_in, environment_dict)
    if stop_refusal_str:
        return stop_refusal_str
    running_str = path_dict_in.get("running") or ""
    try:
        running_list = [name_str for name_str in os.listdir(running_str)] if os.path.isdir(running_str) else []
    except OSError as error:
        return f"the queue's running folder cannot be read ({type(error).__name__})"
    if running_list:
        return f"a job is running ({len(running_list)} file(s) in {running_str}); wait for it"
    return ""


# FUNCTION: BUILD, AND WRITE WHEN CONFIRMED
def freeze_v_reference_dict(path_dict_in, confirm_bool_in=False, note_str_in="", trial_log_path_str_in=None,
                            reference_path_str_in=None, environment_dict_in=None, now_in=None, built_by_str_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        confirm_bool_in (bool): Write (False = dry run)
        note_str_in (str): Why
        trial_log_path_str_in, reference_path_str_in (str | None): Files (None = the data root's)
        environment_dict_in (dict | None): Environment (tests)
        now_in (datetime.datetime | None): Clock (tests)
        built_by_str_in (str | None): Builder (None = the Windows user)

    Returns:
        dict: reference_dict, refused_str, done_bool, reference_path_str, replaced_path_str
    """
    # THE PLAN FIRST (A REFUSED RUN STILL SHOWS IT)
    trial_log_path_str = trial_log_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR
    reference_path_str = reference_path_str_in or get_v_reference_path_str()
    result_dict = {"reference_dict": None, "refused_str": "", "done_bool": False, "reference_path_str": reference_path_str,
                   "replaced_path_str": ""}
    try:
        result_dict["reference_dict"] = build_v_reference_dict(trial_log_path_str, built_by_str_in or getpass.getuser(),
                                                               note_str_in, now_in)
    except VReferenceError as error:
        result_dict["refused_str"] = str(error)
        return result_dict
    result_dict["refused_str"] = get_freeze_refusal_str(path_dict_in, environment_dict_in)
    if result_dict["refused_str"] or not confirm_bool_in:
        return result_dict
    # KEEP THE PREVIOUS FILE, WRITE THE NEW ONE, CHECK IT READS BACK, LOG IT
    reference_dict = result_dict["reference_dict"]
    folder_str = os.path.dirname(reference_path_str)
    os.makedirs(folder_str, exist_ok=True)
    if os.path.isfile(reference_path_str):
        try:
            old_stamp_str = str(read_v_reference_dict(reference_path_str)["built_ts"]).replace(":", "").replace("-", "")
        except VReferenceError:
            old_stamp_str = "unreadable_" + datetime.datetime.now().strftime("%Y%m%dT%H%M%S")
        replaced_path_str = os.path.join(folder_str, f"v_reference_{old_stamp_str}.json")
        suffix_int = 1
        while os.path.exists(replaced_path_str):
            replaced_path_str = os.path.join(folder_str, f"v_reference_{old_stamp_str}_{suffix_int}.json")
            suffix_int += 1
        os.replace(reference_path_str, replaced_path_str)
        result_dict["replaced_path_str"] = replaced_path_str
    temporary_path_str = reference_path_str + ".tmp"
    with open(temporary_path_str, "w", encoding="utf-8", newline="\n") as json_file:
        json.dump(reference_dict, json_file, indent=2, sort_keys=True)
        json_file.write("\n")
    os.replace(temporary_path_str, reference_path_str)
    read_v_reference_dict(reference_path_str)
    log_path_str = os.path.join(folder_str, V_REFERENCE_LOG_NAME_STR)
    new_log_bool = not os.path.isfile(log_path_str)
    with open(log_path_str, "a", encoding="utf-8", newline="") as log_file:
        writer = csv.DictWriter(log_file, fieldnames=V_REFERENCE_LOG_COLUMN_LIST)
        if new_log_bool:
            writer.writeheader()
        writer.writerow({"built_ts": reference_dict["built_ts"], "built_by": reference_dict["built_by"],
                         "variance": repr(float(reference_dict["variance"])), "design_count": reference_dict["design_count"],
                         "experiment_count": len(reference_dict["experiment_list"]),
                         "run_count": len(reference_dict["run_id_list"]),
                         "trial_log_sha256": reference_dict["trial_log_sha256"],
                         "content_sha256": reference_dict["content_sha256"],
                         "replaced_file": os.path.basename(result_dict["replaced_path_str"]), "note": reference_dict["note"]})
    result_dict["done_bool"] = True
    return result_dict


# PARSE THE COMMAND
if __name__ == "__main__":
    # DRY RUN UNLESS --confirm
    parser = argparse.ArgumentParser(description="Freeze the reference V the verdict uses (Nicolas only).")
    parser.add_argument("--confirm", action="store_true", help="Write the reference (without it: show what would be written)")
    parser.add_argument("--note", default="", help="Why it is built (kept in the file and the log)")
    arg_dict = parser.parse_args()
    outcome_dict = freeze_v_reference_dict(get_queue_path_dict(), arg_dict.confirm, arg_dict.note)
    reference_dict = outcome_dict["reference_dict"]
    if reference_dict is not None:
        quarter_list = reference_dict["quarter_count_list"]
        print(f"reference: variance {reference_dict['variance']!r} over {reference_dict['design_count']} designs "
              f"({len(reference_dict['experiment_list'])} experiments, {len(reference_dict['run_id_list'])} runs; "
              f"quarters per design {min(quarter_list)} to {max(quarter_list)})")
        print(f"experiments: {', '.join(reference_dict['experiment_list'])}")
        print(f"trial log sha256 {reference_dict['trial_log_sha256']} ({reference_dict['trial_log_row_count']} rows)")
        print(f"content sha256 {reference_dict['content_sha256']}")
        print(f"target {outcome_dict['reference_path_str']}")
    if outcome_dict["refused_str"]:
        raise SystemExit(f"refused: {outcome_dict['refused_str']} (nothing written)")
    if outcome_dict["done_bool"]:
        if outcome_dict["replaced_path_str"]:
            print(f"previous reference kept as {outcome_dict['replaced_path_str']}")
        print("done; every new run on the development view uses this V")
    else:
        print("dry run: nothing written (add --confirm to write)")
