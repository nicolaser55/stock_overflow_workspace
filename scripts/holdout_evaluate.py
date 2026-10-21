import argparse
import importlib.util
import os
import sys
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE ARRAY CONVERSION
from so.core.trade_execution import get_ohlcv_array_dict
# IMPORT THE HOLDOUT EVALUATION AND THE QUARANTINE WINDOW-END LOADER
from so.core.holdout import load_evaluation_source_frame_dict, run_holdout_evaluation
from so.core.point_in_time import (get_declared_source_name_list, get_minute_bar_available_ts, get_runner_context)
from so.runner import run_holdout_dict

"""
Holdout Evaluation (Nicolas only)

Only Nicolas may run this script. Agents must not (research-integrity.mdc, rule 1). It evaluates one frozen design
once on the active holdout window. Bars and declared sources are read from the quarantine root (SO_QUARANTINE_PATH),
not from the development view. Daily paths go under SO_HOLDOUT_PATH. One summary row is appended to
records/holdout_evaluations.csv and one trial-log row (stage "test") is appended to the shared trial log.

A design that declares get_candidate_design is evaluated through the runner (run_holdout_dict). A design not yet
ported keeps the old replay (run_holdout_evaluation) until the 4c calibration retires that path. The first printed
line after the design is loaded says which path ran.
"""

# THE TWO EVALUATION PATHS (PRINTED AT THE TOP OF THE SCRIPT'S OUTPUT)
RUNNER_PATH_STR = "path: runner (run_holdout_dict)"
REPLAY_PATH_STR = "path: replay (run_holdout_evaluation)"


# FUNCTION: WHICH EVALUATION PATH A DESIGN TAKES
def get_holdout_evaluate_path_str(design_module_in):
    """
    Runner path when the design has get_candidate_design. Replay path until that design is ported.

    Args:
        design_module_in (module): Design

    Returns:
        str: One of RUNNER_PATH_STR, REPLAY_PATH_STR
    """
    # A PORTED DESIGN WRITES get_candidate_design; THE OLD REPLAY WRITES run_candidate_replay_dict
    if hasattr(design_module_in, "get_candidate_design"):
        return RUNNER_PATH_STR
    return REPLAY_PATH_STR

# PRINT WHO MAY RUN THE SCRIPT
print("Only Nicolas may run scripts/holdout_evaluate.py. Agents must not.")

# FUNCTION: LOAD A DESIGN MODULE
def load_design_module(design_folder_str_in):
    """
    Loads <folder>/design.py and copies uppercase constants from <folder>/config.py onto it when the design does not
    already define them (the trial log and the design hash read those constants).

    Args:
        design_folder_str_in (str): Experiment folder

    Returns:
        module: The design
    """
    # LOAD design.py
    design_path_str = os.path.join(design_folder_str_in, "design.py")
    design_spec = importlib.util.spec_from_file_location("holdout_design", design_path_str)
    design_module = importlib.util.module_from_spec(design_spec)
    design_spec.loader.exec_module(design_module)
    # COPY MISSING CONSTANTS FROM config.py
    config_path_str = os.path.join(design_folder_str_in, "config.py")
    if os.path.isfile(config_path_str):
        config_spec = importlib.util.spec_from_file_location("holdout_design_config", config_path_str)
        config_module = importlib.util.module_from_spec(config_spec)
        config_spec.loader.exec_module(config_module)
        for key_str, value in vars(config_module).items():
            if key_str.isupper() and not hasattr(design_module, key_str):
                setattr(design_module, key_str, value)
    # RETURN THE DESIGN
    return design_module

# FUNCTION: LOAD DECLARED SOURCES UP TO THE WINDOW END
def get_evaluation_frame_dict(design_module_in, token_file_path_str_in):
    """
    Loads each source in DATA_SOURCE_LIST, and SPY_1MIN for the bar arrays, from the quarantine root through the
    active window end. The token is checked before that root is read. Rows after the window end are not in the
    frames. A design without DATA_SOURCE_LIST loads SPY_1MIN only.

    Args:
        design_module_in (module): Design
        token_file_path_str_in (str): Token file path

    Returns:
        dict: source name -> frame stamped with available_ts
    """
    # THE DECLARED NAMES, WITH SPY ALWAYS LOADED FOR THE SIMULATOR ARRAYS
    declared_name_list = get_declared_source_name_list(design_module_in)
    load_name_list = list(dict.fromkeys(["SPY_1MIN"] + declared_name_list))
    # THE QUARANTINE LOADER CHECKS THE TOKEN AND SO_QUARANTINE_PATH, THEN READS THROUGH THE WINDOW END
    frame_dict = load_evaluation_source_frame_dict(load_name_list, token_file_path_str_in)
    # RETURN ONLY WHAT THE DESIGN DECLARED, PLUS SPY WHEN IT DECLARED SPY
    return {source_name_str: frame_dict[source_name_str] for source_name_str in load_name_list if source_name_str in declared_name_list or source_name_str == "SPY_1MIN"}

# FUNCTION: LOAD BARS UP TO THE WINDOW END
def get_evaluation_ohlcv_array_dict(design_module_in, token_file_path_str_in):
    """
    SPY bars from the quarantine root through the active window end. Forward rows are dropped by the loader, before
    the arrays are built. Pass a design to share its declared-source load; None loads SPY_1MIN only.

    Args:
        design_module_in (module | None): Design, or None
        token_file_path_str_in (str): Token file path

    Returns:
        dict: Output of get_ohlcv_array_dict
    """
    # LOAD SPY THROUGH THE WINDOW END FROM THE QUARANTINE
    if design_module_in is None:
        frame_dict = load_evaluation_source_frame_dict(["SPY_1MIN"], token_file_path_str_in)
    else:
        frame_dict = get_evaluation_frame_dict(design_module_in, token_file_path_str_in)
    # RETURN THE ARRAYS
    return get_ohlcv_array_dict(frame_dict["SPY_1MIN"])

# PARSE THE COMMAND
if __name__ == "__main__":
    # DEFINE THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Evaluate one frozen design on the active holdout (Nicolas only).")
    parser.add_argument("--design", required=True, help="Experiment folder (contains design.py)")
    parser.add_argument("--token-file", required=True, help="Token file outside the workspace and the data folder")
    arg_dict = parser.parse_args()
    # LOAD THE DESIGN, SAY WHICH PATH WILL RUN, THEN LOAD DECLARED SOURCES THROUGH THE WINDOW END
    design_module = load_design_module(arg_dict.design)
    path_str = get_holdout_evaluate_path_str(design_module)
    print(path_str)
    frame_dict = get_evaluation_frame_dict(design_module, arg_dict.token_file)
    ohlcv_array_dict = get_ohlcv_array_dict(frame_dict["SPY_1MIN"])
    declared_name_list = get_declared_source_name_list(design_module)
    source_frame_dict = {source_name_str: frame_dict[source_name_str] for source_name_str in declared_name_list}
    design_id_str = os.path.basename(os.path.abspath(arg_dict.design))
    if path_str == RUNNER_PATH_STR:
        limit_ts = get_minute_bar_available_ts(ohlcv_array_dict["timestamp_index"][-1])
        data_context = get_runner_context(ohlcv_array_dict, source_frame_dict, limit_ts, declared_name_list)
        result_dict = run_holdout_dict(design_module, design_id_str, ohlcv_array_dict, arg_dict.token_file,
                                       data_context_in=data_context, design_folder_str_in=arg_dict.design)
        row_dict = result_dict["ledger_row_dict"]
    else:
        row_dict = run_holdout_evaluation(design_module, design_id_str, ohlcv_array_dict, arg_dict.token_file,
                                          design_folder_str_in=arg_dict.design, source_frame_dict_in=source_frame_dict)
    # PRINT THE SUMMARY
    print(f"Evaluated {row_dict['design_id']} on {row_dict['window_id']}: status {row_dict['status']}")
    if row_dict["status"] == "valid":
        print(f"total return {row_dict['total_return']} vs buy-and-hold {row_dict['buy_hold_total_return']} "
              f"(primary_pass={row_dict['primary_pass']})")
