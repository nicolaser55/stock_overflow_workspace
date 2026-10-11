import argparse
import importlib.util
import os
import sys
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE ARRAY CONVERSION AND THE RAW LOADER
from so.core.raw_data import get_complete_ohlcv_pdf
from so.core.trade_execution import get_ohlcv_array_dict
# IMPORT THE HOLDOUT EVALUATION
from so.core.holdout import get_active_holdout_window_dict, get_date, run_holdout_evaluation

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

# FUNCTION: LOAD BARS UP TO THE WINDOW END
def get_evaluation_ohlcv_array_dict():
    """
    Reads the raw bars, including the holdout and nothing after the window end (forward data is dropped).

    Returns:
        dict: Output of get_ohlcv_array_dict
    """
    # READ EVERY BAR, THEN DROP FORWARD DATA
    window_dict = get_active_holdout_window_dict()
    ohlcv_pdf = get_complete_ohlcv_pdf(enforce_holdout_bool_in=False)
    end_date = get_date(window_dict["end"])
    ohlcv_pdf = ohlcv_pdf[ohlcv_pdf["date"] <= end_date].reset_index(drop=True)
    # RETURN THE ARRAYS
    return get_ohlcv_array_dict(ohlcv_pdf)

# PARSE THE COMMAND
if __name__ == "__main__":
    # DEFINE THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Evaluate one frozen design on the active holdout (Nicolas only).")
    parser.add_argument("--design", required=True, help="Experiment folder (contains design.py)")
    parser.add_argument("--token-file", required=True, help="Token file outside the workspace and the data folder")
    arg_dict = parser.parse_args()
    # LOAD THE DESIGN AND THE BARS, THEN EVALUATE
    design_module = load_design_module(arg_dict.design)
    ohlcv_array_dict = get_evaluation_ohlcv_array_dict()
    row_dict = run_holdout_evaluation(design_module, os.path.basename(os.path.abspath(arg_dict.design)), ohlcv_array_dict,
                                      arg_dict.token_file, design_folder_str_in=arg_dict.design)
    # PRINT THE SUMMARY
    print(f"Evaluated {row_dict['design_id']} on {row_dict['window_id']}: status {row_dict['status']}")
    if row_dict["status"] == "valid":
        print(f"total return {row_dict['total_return']} vs buy-and-hold {row_dict['buy_hold_total_return']} "
              f"(primary_pass={row_dict['primary_pass']})")
