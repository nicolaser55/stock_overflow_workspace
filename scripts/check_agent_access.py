import argparse
import os
import sys
import uuid
from pathlib import Path

"""
Agent Access Check (run as so_agent after scripts/setup_so_agent.ps1)

    python scripts/check_agent_access.py --quarantine <folder> --nicolas-workspace <folder> [--holdout <folder>]

Tries each access the account must have or must not have and prints one line per check, OK or FAIL. A write test
creates a uniquely named empty file and removes it at once; nothing existing is touched. Exit 1 on any FAIL.
"""


# FUNCTION: CAN THIS ACCOUNT LIST A FOLDER
def get_can_list_bool(folder_str_in):
    """
    Args:
        folder_str_in (str): Folder

    Returns:
        bool: True when listing works
    """
    # A DENIED FOLDER RAISES PermissionError
    try:
        os.listdir(folder_str_in)
        return True
    except OSError:
        return False


# FUNCTION: CAN THIS ACCOUNT CREATE A FILE IN A FOLDER
def get_can_write_bool(folder_str_in):
    """
    Args:
        folder_str_in (str): Folder

    Returns:
        bool: True when a new empty file could be created (it is removed again)
    """
    # A UNIQUE NAME, SO NO EXISTING FILE IS EVER OPENED FOR WRITING
    probe_path = Path(folder_str_in) / f"so_agent_probe_{uuid.uuid4().hex}.tmp"
    try:
        with open(probe_path, "x", encoding="utf-8"):
            pass
    except OSError:
        return False
    try:
        probe_path.unlink()
    except OSError:
        print(f"note: could not remove {probe_path}; remove it by hand")
    return True


# RUN
if __name__ == "__main__":
    # ARGUMENTS
    parser = argparse.ArgumentParser(description="Check so_agent's file access.")
    parser.add_argument("--quarantine", required=True)
    parser.add_argument("--nicolas-workspace", required=True)
    parser.add_argument("--holdout", default="")
    arg_dict = parser.parse_args()
    data_root_str = os.environ.get("SO_DATA_PATH", "").strip()
    check_list = []
    check_list.append(("SO_DATA_PATH is set", bool(data_root_str)))
    for name_str in ["SO_QUARANTINE_PATH", "SO_HOLDOUT_PATH", "SO_HOLDOUT_EVALUATION_TOKEN"]:
        check_list.append((f"{name_str} is not set", not os.environ.get(name_str, "").strip()))
    if data_root_str:
        for zone_str in ["store01_rawzone", "store02_workzone", "store03_goldzone"]:
            zone_path_str = os.path.join(data_root_str, zone_str)
            if os.path.isdir(zone_path_str):
                check_list.append((f"{zone_str} can be read", get_can_list_bool(zone_path_str)))
                check_list.append((f"{zone_str} cannot be written", not get_can_write_bool(zone_path_str)))
        experiment_zone_str = os.path.join(data_root_str, "store04_experiments")
        check_list.append(("store04_experiments can be written", get_can_write_bool(experiment_zone_str)))
    check_list.append(("quarantine cannot be read", not get_can_list_bool(arg_dict.quarantine)))
    if arg_dict.holdout:
        check_list.append(("holdout results cannot be read", not get_can_list_bool(arg_dict.holdout)))
    check_list.append(("Nicolas's workspace can be read", get_can_list_bool(arg_dict.nicolas_workspace)))
    check_list.append(("Nicolas's workspace cannot be written", not get_can_write_bool(arg_dict.nicolas_workspace)))
    check_list.append(("Nicolas's records cannot be written",
                       not get_can_write_bool(os.path.join(arg_dict.nicolas_workspace, "records"))))
    check_list.append(("this workspace can be written", get_can_write_bool(str(Path(__file__).resolve().parents[1]))))
    for label_str, ok_bool in check_list:
        print(f"{'OK  ' if ok_bool else 'FAIL'} {label_str}")
    sys.exit(0 if all(ok_bool for _, ok_bool in check_list) else 1)
