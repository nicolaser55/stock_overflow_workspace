import argparse
import importlib.util
import os
import sys
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE ARRAY CONVERSION
from so.core.trade_execution import get_ohlcv_array_dict
# IMPORT THE HOLDOUT EVALUATION AND THE DECLARED-SOURCE LOADER
from so.core.holdout import get_active_holdout_window_dict, get_date, run_holdout_evaluation
from so.core.point_in_time import get_declared_source_name_list, load_source_frame_dict

"""
Holdout Evaluation (Nicolas only)

Only Nicolas may run this script. Agents must not (research-integrity.mdc, rule 1). It evaluates one frozen design
once on the active holdout window. Daily paths go under SO_HOLDOUT_PATH. One summary row is appended to
records/holdout_evaluations.csv and one trial-log row (stage "test") is appended to the shared trial log.
"""

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
def get_evaluation_frame_dict(design_module_in):
    """
    Loads each source in DATA_SOURCE_LIST, and SPY_1MIN for the bar arrays, through the active window end.
    Rows after that date are not in the frames. A design without DATA_SOURCE_LIST loads SPY_1MIN only.

    Args:
        design_module_in (module): Design

    Returns:
        dict: source name -> frame stamped with available_ts
    """
    # THE WINDOW END IS THE LAST SESSION THE EVALUATION MAY SEE
    end_date = get_date(get_active_holdout_window_dict()["end"])
    declared_name_list = get_declared_source_name_list(design_module_in)
    # SPY IS ALWAYS LOADED FOR THE SIMULATOR ARRAYS; A DESIGN THAT DID NOT DECLARE IT IS NOT HANDED THE FRAME
    load_name_list = list(dict.fromkeys(["SPY_1MIN"] + declared_name_list))
    frame_dict = load_source_frame_dict(load_name_list, end_date)
    # RETURN ONLY WHAT THE DESIGN DECLARED, PLUS SPY WHEN IT DECLARED SPY
    return {source_name_str: frame_dict[source_name_str] for source_name_str in load_name_list if source_name_str in declared_name_list or source_name_str == "SPY_1MIN"}

# FUNCTION: LOAD BARS UP TO THE WINDOW END
def get_evaluation_ohlcv_array_dict(design_module_in=None):
    """
    SPY bars through the active window end. Forward rows are dropped by the loader, before the arrays are built.
    design_module_in is accepted so a caller can share one load; None loads SPY_1MIN only.

    Args:
        design_module_in (module | None): Design, or None

    Returns:
        dict: Output of get_ohlcv_array_dict
    """
    # LOAD SPY THROUGH THE WINDOW END
    if design_module_in is None:
        end_date = get_date(get_active_holdout_window_dict()["end"])
        frame_dict = load_source_frame_dict(["SPY_1MIN"], end_date)
    else:
        frame_dict = get_evaluation_frame_dict(design_module_in)
    # RETURN THE ARRAYS
    return get_ohlcv_array_dict(frame_dict["SPY_1MIN"])

# PARSE THE COMMAND
if __name__ == "__main__":
    # DEFINE THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Evaluate one frozen design on the active holdout (Nicolas only).")
    parser.add_argument("--design", required=True, help="Experiment folder (contains design.py)")
    parser.add_argument("--token-file", required=True, help="Token file outside the workspace and the data folder")
    arg_dict = parser.parse_args()
    # LOAD THE DESIGN, ITS DECLARED SOURCES THROUGH THE WINDOW END, THEN EVALUATE
    design_module = load_design_module(arg_dict.design)
    frame_dict = get_evaluation_frame_dict(design_module)
    ohlcv_array_dict = get_ohlcv_array_dict(frame_dict["SPY_1MIN"])
    declared_name_list = get_declared_source_name_list(design_module)
    source_frame_dict = {source_name_str: frame_dict[source_name_str] for source_name_str in declared_name_list}
    row_dict = run_holdout_evaluation(design_module, os.path.basename(os.path.abspath(arg_dict.design)), ohlcv_array_dict,
                                      arg_dict.token_file, design_folder_str_in=arg_dict.design, source_frame_dict_in=source_frame_dict)
    # PRINT THE SUMMARY
    print(f"Evaluated {row_dict['design_id']} on {row_dict['window_id']}: status {row_dict['status']}")
    if row_dict["status"] == "valid":
        print(f"total return {row_dict['total_return']} vs buy-and-hold {row_dict['buy_hold_total_return']} "
              f"(primary_pass={row_dict['primary_pass']})")
