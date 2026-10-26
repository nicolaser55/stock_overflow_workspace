import argparse
import datetime
import importlib.util
import os
import sys
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE DEVELOPMENT SPAN, THE POINT-IN-TIME LOAD, AND THE RUNNER
from so.core.development_span import get_development_ohlcv_dict
from so.core.point_in_time import (get_declared_source_name_list, get_minute_bar_available_ts, get_runner_context,
                                   load_source_frame_dict)
from so.runner import run_development_dict
from so.runner.verdict import REPORT_MD_FILE_STR, REPORT_JSON_FILE_STR
sys.path.insert(1, str(Path(__file__).resolve().parent))
from check_environment import check_environment_list, LOCK_PATH

"""
Development Run (one experiment folder)

Loads the design, the development bars (embargo before the registered holdout start), and the declared sources
through that last session. Calls so.runner.run_development_dict. Prints the report path. Does not read the holdout.
"""


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
    # THE PREFLIGHT RUNS BEFORE ANY DESIGN CODE; THE IMPORT RUNS BEHIND THE FILE GUARD AND MAY NOT CHANGE so.*
    from so.runner.preflight import check_design_file
    from so.runner.guard import design_code_guard, get_module_snapshot_dict, check_module_snapshot
    design_path_str = os.path.join(design_folder_str_in, "design.py")
    check_design_file(design_path_str)
    module_snapshot_dict = get_module_snapshot_dict()
    design_spec = importlib.util.spec_from_file_location("development_design", design_path_str)
    design_module = importlib.util.module_from_spec(design_spec)
    with design_code_guard():
        design_spec.loader.exec_module(design_module)
    # COPY MISSING CONSTANTS FROM config.py
    config_path_str = os.path.join(design_folder_str_in, "config.py")
    if os.path.isfile(config_path_str):
        config_spec = importlib.util.spec_from_file_location("development_design_config", config_path_str)
        config_module = importlib.util.module_from_spec(config_spec)
        with design_code_guard():
            config_spec.loader.exec_module(config_module)
        for key_str, value in vars(config_module).items():
            if key_str.isupper() and not hasattr(design_module, key_str):
                setattr(design_module, key_str, value)
    check_module_snapshot(module_snapshot_dict, f"while importing {design_folder_str_in}")
    # RETURN THE DESIGN
    return design_module


# FUNCTION: LOAD THE DECLARED SOURCES (MINUTE DESIGNS: ONLY THE SAMPLED MINUTES)
def load_declared_frame_dict(design_module_in, declared_name_list_in, development_end_in):
    """
    A daily design loads every declared source at once. A minute design with ROW_SAMPLE_EVERY_N_MINUTES loads one
    source at a time and keeps only the rows of the sampled minutes (the only rows minute mode joins), so the context
    every candidate process unpickles stays small. TSBAR is loaded with SPY_1MIN, which places its label clocks.

    Args:
        design_module_in (module): Design
        declared_name_list_in (list[str]): DATA_SOURCE_LIST
        development_end_in: Last development session

    Returns:
        dict: source name -> stamped frame
    """
    # IMPORT THE MINUTE HELPERS HERE
    import pandas as pd
    from so.runner.minute import get_row_sample_minutes_int, get_source_join_ts_series
    from so.runner.loop import get_design_mode_str, MODE_MINUTE_STR
    sample_minutes_int = get_row_sample_minutes_int(design_module_in) if get_design_mode_str(design_module_in) == MODE_MINUTE_STR else None
    if sample_minutes_int is None:
        return load_source_frame_dict(declared_name_list_in, development_end_in)
    from so.runner.minute import get_sample_mask_arr
    frame_dict = {}
    for source_name_str in declared_name_list_in:
        if source_name_str == "SPY_1MIN":
            continue
        load_list = ["SPY_1MIN", source_name_str] if source_name_str == "TSBAR" else [source_name_str]
        frame_pdf = load_source_frame_dict(load_list, development_end_in)[source_name_str]
        if len(frame_pdf):
            join_index = pd.DatetimeIndex(get_source_join_ts_series(frame_pdf))
            frame_pdf = frame_pdf.loc[get_sample_mask_arr(join_index, sample_minutes_int)].reset_index(drop=True)
        frame_dict[source_name_str] = frame_pdf
        print(f"loaded {source_name_str}: {len(frame_pdf):,} sampled rows", flush=True)
    return frame_dict


# FUNCTION: ONE RESULTS-LOG ROW FROM A RUN'S REPORT
def get_results_row_str(report_dict_in, run_id_str_in, note_str_in, date_str_in=None):
    """
    The docs/RESULTS_LOG.md row of a run: date, experiment, protocol, run id, verdict, prior-only and buy-and-hold
    total return, failed parts, look-ahead, note. The run prints it; scripts/append_results_log.py writes it.

    Args:
        report_dict_in (dict): report.json of the run
        run_id_str_in (str): Run id
        note_str_in (str): The --note text
        date_str_in (str | None): Date shown (None = today)

    Returns:
        str: The row
    """
    # THE NUMBERS THE VERDICT USED
    return_dict = report_dict_in.get("return_dict", {})
    look_ahead_str = str((report_dict_in.get("look_ahead_dict") or {}).get("status_str", ""))
    date_str = date_str_in or datetime.date.today().isoformat()
    return (f"| {date_str} | {report_dict_in.get('experiment_name_str', '')} | "
            f"{report_dict_in.get('protocol_version_str', '')} | {run_id_str_in} | {report_dict_in.get('label_str', '')} | "
            f"{float(return_dict.get('strategy_total_return', float('nan'))):+.2%} vs "
            f"{float(return_dict.get('buy_hold_total_return', float('nan'))):+.2%} | "
            f"{', '.join(report_dict_in.get('failed_list') or []) or 'none'} | {look_ahead_str} | "
            f"{str(note_str_in).replace('|', '/')} |")


# PARSE THE COMMAND
if __name__ == "__main__":
    # DEFINE THE ARGUMENTS
    parser = argparse.ArgumentParser(description="Run one experiment on the development view through the runner.")
    parser.add_argument("design", help="Experiment folder (contains design.py)")
    parser.add_argument("--note", default="", help="Free text copied onto each candidate-period trial row")
    parser.add_argument("--n-jobs", type=int, default=None, help="Candidate process count (default min(8, candidates))")
    parser.add_argument("--run-id", default=None, help="Resume key (default experiment name plus timestamp)")
    arg_dict = parser.parse_args()
    # THE INSTALLED PACKAGES MUST MATCH THE LOCK (WITHOUT A LOCK: A WARNING)
    difference_list = check_environment_list()
    if difference_list is None:
        print(f"warning: no package lock at {LOCK_PATH}; the run does not check package versions", flush=True)
    elif difference_list:
        raise SystemExit("installed packages differ from the lock:\n" + "\n".join(difference_list))
    # LOAD THE DESIGN, THE DEVELOPMENT BARS, AND THE DECLARED SOURCES THROUGH THE LAST SESSION
    design_module = load_design_module(arg_dict.design)
    if not hasattr(design_module, "get_candidate_design"):
        raise ValueError(f"{arg_dict.design} has no get_candidate_design; port it to the runner first.")
    embargo_int = int(design_module.PERIOD_RULE["embargo_sessions"])
    span_dict = get_development_ohlcv_dict(embargo_int)
    ohlcv_array_dict = span_dict["ohlcv_array_dict"]
    development_end = span_dict["development_end"]
    declared_name_list = get_declared_source_name_list(design_module)
    source_frame_dict = load_declared_frame_dict(design_module, declared_name_list, development_end)
    limit_ts = get_minute_bar_available_ts(ohlcv_array_dict["timestamp_index"][-1])
    data_context = get_runner_context(ohlcv_array_dict, source_frame_dict, limit_ts, declared_name_list)
    # RUN ON THE DEVELOPMENT VIEW
    result_dict = run_development_dict(design_module, ohlcv_array_dict, data_context_in=data_context,
                                       run_id_str_in=arg_dict.run_id, n_jobs_int_in=arg_dict.n_jobs,
                                       note_str_in=arg_dict.note)
    run_folder_str = result_dict["run_folder_str"]
    report_md_str = os.path.join(run_folder_str, REPORT_MD_FILE_STR)
    report_json_str = os.path.join(run_folder_str, REPORT_JSON_FILE_STR)
    verdict_dict = result_dict["verdict_dict"]
    print(f"report {report_md_str}")
    print(f"report_json {report_json_str}")
    print(f"run_id {result_dict['run_id_str']}")
    print(f"verdict {verdict_dict['label_str']}")
    print(f"email_worthy {bool(verdict_dict['email_worthy_bool'])}")
    print(f"failed {list(verdict_dict['failed_list'])}")
    print(f"results_row {get_results_row_str(result_dict['report_dict'], result_dict['run_id_str'], arg_dict.note)}")
    print(f"saved {report_md_str}")
