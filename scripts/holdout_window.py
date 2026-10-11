import argparse
import sys
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE SHARED CONFIGURATION
from so import config
# IMPORT THE HOLDOUT REGISTRY
from so.core.holdout import (compute_holdout_window_dict, get_active_holdout_window_dict, get_forward_session_count,
                             get_latest_session_date, get_raw_session_date_list, open_holdout_window_dict,
                             read_holdout_evaluation_pdf, roll_holdout_window_dict)

"""
Holdout Window (Nicolas only)

Only Nicolas may run this script. Agents must not (research-integrity.mdc, rule 1). It opens, reports or rolls the
registered holdout window. It does not evaluate a design and it does not write a trial-log row.
"""

# PRINT WHO MAY RUN THE SCRIPT
print("Only Nicolas may run scripts/holdout_window.py. Agents must not.")

# FUNCTION: PRINT THE PROPOSED WINDOW
def print_window_dict(window_dict_in, title_str_in):
    """
    Prints a window's bounds and length.

    Args:
        window_dict_in (dict): start, end, session_count, months_covered
        title_str_in (str): Heading

    Returns:
        None
    """
    # PRINT THE WINDOW
    print(f"{title_str_in}: {window_dict_in['start']} -> {window_dict_in['end']} "
          f"({window_dict_in['session_count']} sessions, {window_dict_in['months_covered']:.2f} months)")
    print(f"Type exactly: OPEN {window_dict_in['start']} {window_dict_in['end']}")

# FUNCTION: OPEN A WINDOW
def run_open():
    """
    Computes the window from the latest session, asks for the typed confirmation and appends the registry row.

    Returns:
        None
    """
    # REQUIRE A FRESH PIPELINE AND THE SESSION LIST
    latest_date = get_latest_session_date()
    session_date_list = get_raw_session_date_list()
    # COMPUTE AND SHOW THE WINDOW BEFORE ASKING
    window_dict = compute_holdout_window_dict(session_date_list)
    print(f"Latest session (raw and step06): {latest_date}")
    print_window_dict(window_dict, "Proposed holdout")
    # ASK AND OPEN
    confirm_str = input("Confirmation: ")
    row_dict = open_holdout_window_dict(session_date_list, confirm_str)
    # PRINT THE REGISTERED WINDOW
    print(f"Opened {row_dict['window_id']}")

# FUNCTION: PRINT THE STATUS
def run_status():
    """
    Prints the active window, evaluations used against the budget, and the forward-session count (no prices).

    Returns:
        None
    """
    # READ THE WINDOW, THE LEDGER AND THE SESSION COUNT AFTER THE END
    window_dict = get_active_holdout_window_dict()
    ledger_pdf = read_holdout_evaluation_pdf()
    used_count = int((ledger_pdf["window_id"] == window_dict["window_id"]).sum()) if len(ledger_pdf) else 0
    forward_count = get_forward_session_count(get_raw_session_date_list())
    # PRINT THE STATUS
    print(f"Active window {window_dict['window_id']}: {window_dict['start']} -> {window_dict['end']} "
          f"({window_dict['session_count']} sessions)")
    print(f"Evaluations: {used_count} / {config.HOLDOUT_EVALUATION_BUDGET}")
    print(f"Forward sessions after the window: {forward_count}")

# FUNCTION: ROLL THE WINDOW
def run_roll(reason_str_in, allow_short_bool_in):
    """
    Shows the next window, asks for the typed confirmation, retires the active window and opens the next one.

    Args:
        reason_str_in (str): Why the active window is retired
        allow_short_bool_in (bool): Accept a span shorter than HOLDOUT_MIN_WINDOW_MONTHS

    Returns:
        None
    """
    # COMPUTE THE NEXT WINDOW BEFORE ASKING (A REFUSAL HERE DOES NOT RETIRE THE ACTIVE WINDOW)
    session_date_list = get_raw_session_date_list()
    active_dict = get_active_holdout_window_dict()
    window_dict = compute_holdout_window_dict(session_date_list, start_after_date_in=active_dict["end"])
    print_window_dict(window_dict, "Next holdout")
    # ASK AND ROLL
    confirm_str = input("Confirmation: ")
    row_dict = roll_holdout_window_dict(session_date_list, reason_str_in, confirm_str, allow_short_bool_in)
    # PRINT THE NEW WINDOW
    print(f"Rolled to {row_dict['window_id']}")

# PARSE THE COMMAND
if __name__ == "__main__":
    # DEFINE THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Open, report or roll the holdout window (Nicolas only).")
    parser.add_argument("command_str", choices=["open", "status", "roll"])
    parser.add_argument("--reason", default="", help="Why the active window is retired (roll only)")
    parser.add_argument("--allow-short", action="store_true", help="Accept a roll shorter than the minimum")
    arg_dict = parser.parse_args()
    # RUN THE COMMAND
    if arg_dict.command_str == "open":
        run_open()
    elif arg_dict.command_str == "status":
        run_status()
    else:
        run_roll(arg_dict.reason, arg_dict.allow_short)
