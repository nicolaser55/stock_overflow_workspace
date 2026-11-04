import argparse
import glob
import os
import sys
import uuid
from pathlib import Path

"""
Account Access Check (run as so_agent after scripts/setup_so_agent.ps1, or as so_runner after setup_so_runner.ps1)

    python scripts/check_agent_access.py --make-sample-list <file>                       # as nico, first
    python scripts/check_agent_access.py --sample-list <file> --quarantine <folder> --nicolas-workspace <folder> [--holdout <folder>]
    python scripts/check_agent_access.py --role runner --sample-list <file> --quarantine <folder> --nicolas-workspace <folder>

so_agent (roadmap R4, 2026-11-03) may read only store04_experiments\\visible (state.json; grades through
so_grade_readers, technical status through so_status_readers), list and add files in queue\\pending, and read control
(the kill switch). Everything else in the data root (market data, runs, the trial log, the run index, the queue
folders, checks, VIEW.json), the quarantine, the holdout, the backup and archive folders and the runner's clone must
answer "access denied". so_runner may write all of store04_experiments.

A denied check passes only on PermissionError. A path that does not exist is a FAIL ("missing"), not a pass: a check
that cannot find its target proves nothing. The agent cannot list the folders it must not read, so the real files it
tries are named in a sample list that nico writes first (--make-sample-list): one run's report.json, the run index,
the trial log, one raw-zone file, one work-zone file, one log, one finished job; the list holds paths only.

Prints one line per check, OK or FAIL. A write test creates a uniquely named empty file and removes it when the account
may delete (so_agent may not delete in queue\\pending: its probe file stays and the runner ignores it, since it is not
.json). Exit 1 on any FAIL.
"""

# PROBE FILES START WITH THIS (SO A LEFTOVER IS EASY TO RECOGNIZE)
PROBE_PREFIX_STR = "access_probe_"
# SAMPLE-LIST LABELS -> HOW TO FIND ONE REAL FILE UNDER THE DATA ROOT (GLOBS, FIRST MATCH)
SAMPLE_GLOB_DICT = {"report.json of a run": "store04_experiments/runs/*/report.json",
                    "manifest.json of a run": "store04_experiments/runs/*/manifest.json",
                    "run index": "store04_experiments/run_index.csv",
                    "trial log": "store04_experiments/trial_log.csv",
                    "a finished job": "store04_experiments/queue/done/*.json",
                    "a run log": "store04_experiments/queue/logs/*.log",
                    "a raw-zone file": "store01_rawzone/*/*.*",
                    "a work-zone file": "store02_workzone/*/*.*",
                    "a gold-zone file": "store03_goldzone/*/*.*",
                    "the view stamp": "VIEW.json",
                    "the view manifest": "view_manifest.json"}
# FOLDERS UNDER THE DATA ROOT THE AGENT MUST NOT LIST
DENIED_FOLDER_LIST = ["", "store01_rawzone", "store02_workzone", "store03_goldzone", "store04_experiments",
                      "store04_experiments/runs", "store04_experiments/checks", "store04_experiments/queue",
                      "store04_experiments/queue/done", "store04_experiments/queue/failed",
                      "store04_experiments/queue/rejected", "store04_experiments/queue/running",
                      "store04_experiments/queue/logs", "store04_experiments/queue/outbox"]
# FOLDERS NEXT TO THE DATA ROOT THE AGENT MUST NOT LIST
DENIED_SIBLING_LIST = ["archive", "backup_records", "move_logs", "runner_workspace"]


# FUNCTION: LIST A FOLDER: "ok", "denied" OR "missing"
def get_list_outcome_str(folder_str_in):
    """
    Args:
        folder_str_in (str): Folder

    Returns:
        str: ok, denied (PermissionError), missing (FileNotFoundError / NotADirectoryError) or error
    """
    # ONLY A PERMISSION ERROR IS A DENIAL
    try:
        os.listdir(folder_str_in)
        return "ok"
    except PermissionError:
        return "denied"
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except OSError:
        return "error"


# FUNCTION: READ THE FIRST BYTE OF A FILE: "ok", "denied" OR "missing"
def get_read_outcome_str(file_str_in):
    """
    Args:
        file_str_in (str): File

    Returns:
        str: ok, denied, missing or error
    """
    # OPEN AND READ ONE BYTE
    try:
        with open(file_str_in, "rb") as file_obj:
            file_obj.read(1)
        return "ok"
    except PermissionError:
        return "denied"
    except (FileNotFoundError, NotADirectoryError):
        return "missing"
    except OSError:
        return "error"


# FUNCTION: CAN THIS ACCOUNT CREATE A FILE IN A FOLDER
def get_can_write_bool(folder_str_in, remove_bool_in=True):
    """
    Args:
        folder_str_in (str): Folder
        remove_bool_in (bool): Remove the probe afterwards (False where the account may not delete)

    Returns:
        bool: True when a new empty file could be created
    """
    # A UNIQUE NAME, SO NO EXISTING FILE IS EVER OPENED FOR WRITING
    probe_path = Path(folder_str_in) / f"{PROBE_PREFIX_STR}{uuid.uuid4().hex}.tmp"
    try:
        with open(probe_path, "x", encoding="utf-8"):
            pass
    except OSError:
        return False
    if remove_bool_in:
        try:
            probe_path.unlink()
        except OSError:
            print(f"note: could not remove {probe_path}; remove it by hand")
    return True


# FUNCTION: WRITE THE SAMPLE LIST (AS NICO)
def write_sample_list(data_root_str_in, list_path_str_in):
    """
    Args:
        data_root_str_in (str): Data root
        list_path_str_in (str): File to write (somewhere so_agent can read, e.g. the agent workspace)

    Returns:
        int: Samples found
    """
    # ONE MATCH PER LABEL; A LABEL WITHOUT A MATCH IS LEFT OUT (AND SAID)
    line_list, found_int = [], 0
    for label_str, glob_str in SAMPLE_GLOB_DICT.items():
        match_list = sorted(path_str for path_str in glob.glob(os.path.join(data_root_str_in, *glob_str.split("/")))
                            if os.path.isfile(path_str))
        if match_list:
            line_list.append(f"{label_str}\t{match_list[0]}")
            found_int += 1
        else:
            print(f"note: no file for '{label_str}' ({glob_str}); not checked")
    Path(list_path_str_in).write_text("\n".join(line_list) + "\n", encoding="utf-8")
    return found_int


# FUNCTION: READ THE SAMPLE LIST
def read_sample_list(list_path_str_in):
    """
    Args:
        list_path_str_in (str): File written by write_sample_list

    Returns:
        list[tuple[str, str]]: (label, path)
    """
    # TAB-SEPARATED
    pair_list = []
    for line_str in Path(list_path_str_in).read_text(encoding="utf-8").splitlines():
        if "\t" in line_str:
            label_str, path_str = line_str.split("\t", 1)
            pair_list.append((label_str.strip(), path_str.strip()))
    return pair_list


# RUN
if __name__ == "__main__":
    # ARGUMENTS
    parser = argparse.ArgumentParser(description="Check an account's file access.")
    parser.add_argument("--quarantine", default="")
    parser.add_argument("--nicolas-workspace", default="")
    parser.add_argument("--holdout", default="")
    parser.add_argument("--role", choices=["agent", "runner"], default="agent")
    parser.add_argument("--sample-list", default="", help="File written by --make-sample-list (real files to try)")
    parser.add_argument("--make-sample-list", default="", help="As nico: write the sample list to this file and exit")
    arg_dict = parser.parse_args()
    data_root_str = os.environ.get("SO_DATA_PATH", "").strip()
    if arg_dict.make_sample_list:
        if not data_root_str:
            raise SystemExit("SO_DATA_PATH is not set")
        print(f"{write_sample_list(data_root_str, arg_dict.make_sample_list)} sample files listed in {arg_dict.make_sample_list}")
        sys.exit(0)
    if not (arg_dict.quarantine and arg_dict.nicolas_workspace):
        raise SystemExit("--quarantine and --nicolas-workspace are required")
    agent_bool = arg_dict.role == "agent"
    check_list = []

    def add_check(label_str_in, ok_bool_in, detail_str_in=""):
        check_list.append((label_str_in + (f" ({detail_str_in})" if detail_str_in else ""), bool(ok_bool_in)))

    def add_denied_list_check(label_str_in, folder_str_in):
        outcome_str = get_list_outcome_str(folder_str_in)
        add_check(f"{label_str_in} cannot be listed", outcome_str == "denied", "" if outcome_str == "denied" else outcome_str)

    def add_readable_list_check(label_str_in, folder_str_in):
        outcome_str = get_list_outcome_str(folder_str_in)
        add_check(f"{label_str_in} can be listed", outcome_str == "ok", "" if outcome_str == "ok" else outcome_str)
    add_check("SO_DATA_PATH is set", bool(data_root_str))
    for name_str in ["SO_QUARANTINE_PATH", "SO_HOLDOUT_PATH", "SO_HOLDOUT_EVALUATION_TOKEN"]:
        add_check(f"{name_str} is not set", not os.environ.get(name_str, "").strip())
    if data_root_str:
        experiment_zone_str = os.path.join(data_root_str, "store04_experiments")
        pending_str = os.path.join(experiment_zone_str, "queue", "pending")
        visible_str = os.path.join(experiment_zone_str, "visible")
        control_str = os.path.join(data_root_str, "control")
        # WHAT EVERY ACCOUNT NEEDS: PENDING, THE KILL SWITCH, THE VISIBLE STATE, GRADES AND STATUS
        add_check("queue/pending can be written", get_can_write_bool(pending_str, remove_bool_in=not agent_bool))
        add_readable_list_check("queue/pending", pending_str)
        add_readable_list_check("control (the kill switch)", control_str)
        stop_str = os.path.join(control_str, "STOP")
        try:
            os.stat(stop_str)
            stop_outcome_str = "set"
        except FileNotFoundError:
            stop_outcome_str = "not set"
        except OSError as error:
            stop_outcome_str = f"unreadable ({type(error).__name__})"
        add_check("the kill switch can be read", not stop_outcome_str.startswith("unreadable"), stop_outcome_str)
        add_readable_list_check("visible", visible_str)
        state_str = os.path.join(visible_str, "state.json")
        if os.path.exists(state_str) or not agent_bool:
            state_outcome_str = get_read_outcome_str(state_str)
            add_check("visible/state.json can be read", state_outcome_str == "ok",
                      "" if state_outcome_str == "ok" else state_outcome_str)
        else:
            add_check("visible/state.json can be read", False, "missing: run the runner once after the deploy")
        add_readable_list_check("visible/grades", os.path.join(visible_str, "grades"))
        add_readable_list_check("visible/status", os.path.join(visible_str, "status"))
        if agent_bool:
            # NOTHING ELSE IN THE DATA ROOT
            for rel_str in DENIED_FOLDER_LIST:
                add_denied_list_check(f"data root{'/' + rel_str if rel_str else ''}",
                                      os.path.join(data_root_str, *[part for part in rel_str.split("/") if part]))
            for name_str in ["trial_log.csv", "run_index.csv", "state.json"]:
                file_str = os.path.join(experiment_zone_str, name_str)
                outcome_str = get_read_outcome_str(file_str)
                # THE OLD state.json AT THE ZONE ROOT IS REMOVED BY THE RUNNER: MISSING IS FINE THERE
                ok_bool = outcome_str == "denied" or (name_str == "state.json" and outcome_str == "missing")
                add_check(f"store04_experiments/{name_str} cannot be read", ok_bool, "" if outcome_str == "denied" else outcome_str)
            add_check("store04_experiments cannot be written", not get_can_write_bool(experiment_zone_str))
            add_check("visible cannot be written", not get_can_write_bool(visible_str))
            add_check("control cannot be written", not get_can_write_bool(control_str))
            parent_str = os.path.dirname(os.path.abspath(data_root_str.rstrip("\\/")))
            for name_str in DENIED_SIBLING_LIST:
                add_denied_list_check(name_str, os.path.join(parent_str, name_str))
        else:
            add_check("store04_experiments can be written", get_can_write_bool(experiment_zone_str))
            add_check("visible can be written", get_can_write_bool(visible_str))
            for zone_str in ["store01_rawzone", "store02_workzone", "store03_goldzone"]:
                add_readable_list_check(zone_str, os.path.join(data_root_str, zone_str))
                add_check(f"{zone_str} cannot be written", not get_can_write_bool(os.path.join(data_root_str, zone_str)))
    # THE REAL FILES OF THE SAMPLE LIST: DENIED FOR THE AGENT, READABLE FOR THE RUNNER
    if arg_dict.sample_list:
        try:
            sample_list = read_sample_list(arg_dict.sample_list)
        except OSError as error:
            sample_list = []
            add_check("the sample list can be read", False, type(error).__name__)
        for label_str, path_str in sample_list:
            outcome_str = get_read_outcome_str(path_str)
            if agent_bool:
                add_check(f"{label_str} cannot be read", outcome_str == "denied", "" if outcome_str == "denied" else outcome_str)
            else:
                add_check(f"{label_str} can be read", outcome_str == "ok", "" if outcome_str == "ok" else outcome_str)
    elif agent_bool:
        add_check("a sample list was given (real files tried)", False, "run --make-sample-list as nico first")
    add_check("quarantine cannot be read", get_list_outcome_str(arg_dict.quarantine) == "denied")
    if arg_dict.holdout:
        add_check("holdout results cannot be read", get_list_outcome_str(arg_dict.holdout) == "denied")
    add_check("Nicolas's workspace can be read", get_list_outcome_str(arg_dict.nicolas_workspace) == "ok")
    add_check("Nicolas's workspace cannot be written", not get_can_write_bool(arg_dict.nicolas_workspace))
    add_check("Nicolas's records cannot be written",
              not get_can_write_bool(os.path.join(arg_dict.nicolas_workspace, "records")))
    add_check("this workspace can be written", get_can_write_bool(str(Path(__file__).resolve().parents[1])))
    for label_str, ok_bool in check_list:
        print(f"{'OK  ' if ok_bool else 'FAIL'} {label_str}")
    sys.exit(0 if all(ok_bool for _, ok_bool in check_list) else 1)
