import json
import sys
import pandas as pd
# IMPORT THE SHARED PATHS AND THE NUMERIC TOLERANCE
from so import config, paths

"""
Old-bounds calibration for one version-2.0 rule experiment (Nicolas, 2026-10-12).

Replays the version 2.0 candidates on the archived quarter bounds that end before the development end, and compares
those returns with the archived returns. A date that is a development period is scored as a slice of the continuous
path. This is a diagnostic. It informs no decision. It appends one trial-log row with stage "note" and refuses to
run when that row already exists.

Usage: venv-main/Scripts/python.exe -u scripts/calibrate_port_old_bounds.py <package>
    package is experiments.exp04_trend_exit, or the short name exp04_trend_exit.
"""

# ARCHIVED QUARTER TABLES, AND THE VERSION 2.0 PACKAGE THAT REPLAYS THEM
_SPEC_DICT = {
    "exp04_trend_exit": {"old_name": "exp04_trend_exit", "folder": "step02_continuous_replay_data"},
    "exp05_vol_scaled_exposure": {"old_name": "exp05_vol_scaled_exposure", "folder": "step02_continuous_replay_data"},
    "exp06_capped_regret_reentry": {"old_name": "exp06_capped_regret_reentry", "folder": "step02_continuous_replay_data"},
    "exp07_warning_lights_exit": {"old_name": "exp07_warning_lights_exit", "folder": "step02_continuous_replay_data"},
    "exp12_vix_fear_reentry": {"old_name": "exp12_vix_fear_reentry", "folder": "step02_continuous_replay_data"},
    "exp13_e1m1_robustness": {"old_name": "exp12_vix_fear_reentry", "folder": "step02_continuous_replay_data", "only_candidate": "E1M1"},
}
# A MATCH IS AN ABSOLUTE DIFFERENCE OF AT MOST so.config.NUMERIC_TOLERANCE. THE SUMMARY ALSO STORES THE MAXIMUM GAP.

# FUNCTION: THE PACKAGE NAME ON THE COMMAND LINE
def get_package_str():
    """
    Returns the experiment package, without the experiments. prefix.

    Returns:
        str: Package name
    """
    # THE ONLY ARGUMENT
    if len(sys.argv) != 2:
        raise SystemExit("usage: calibrate_port_old_bounds.py <experiment package>")
    return sys.argv[1].replace("experiments.", "")

# FUNCTION: HOW MANY NOTE ROWS THIS CALIBRATION ALREADY LOGGED
def get_note_count_int(experiment_name_str_in):
    """
    Counts existing old-bounds note rows for this experiment.

    Args:
        experiment_name_str_in (str): Trial-log experiment name

    Returns:
        int: Count
    """
    # READ THE SHARED LOG
    from so.core.trial_log import read_trial_log_pdf
    trial_pdf = read_trial_log_pdf()
    if trial_pdf.empty:
        return 0
    note_pdf = trial_pdf[(trial_pdf["experiment"] == experiment_name_str_in) & (trial_pdf["stage"] == "note")]
    return int(note_pdf["note"].astype(str).str.contains("old-bounds calibration").sum())

# FUNCTION: ARCHIVED QUARTER ROWS THAT END BEFORE THE DEVELOPMENT END
def get_archived_pdf(spec_dict_in, development_end_in, candidate_list_in):
    """
    Reads the archived candidate periods and drops every quarter that ends on or after the development end.

    Args:
        spec_dict_in (dict): Archive location
        development_end_in (datetime.date): Development end
        candidate_list_in (list[str]): Version 2.0 candidate names, in order

    Returns:
        pd.DataFrame: Kept rows with a candidate name
    """
    # DATES AND RETURNS. QUARTERS PAST THE DEVELOPMENT END ARE DROPPED BEFORE A REPLAY.
    folder_str = f"{paths.LOCAL_EXPERIMENTZONE_PATH_STR}{spec_dict_in['old_name']}/{spec_dict_in['folder']}/"
    period_pdf = pd.read_csv(f"{folder_str}candidate_period_data.csv")
    period_pdf["valid_end_date"] = pd.to_datetime(period_pdf["valid_end"]).dt.date
    kept_pdf = period_pdf[period_pdf["valid_end_date"] < development_end_in].copy()
    if "only_candidate" in spec_dict_in and "candidate_name" in kept_pdf.columns:
        kept_pdf = kept_pdf[kept_pdf["candidate_name"] == spec_dict_in["only_candidate"]].copy()
        kept_pdf["candidate"] = spec_dict_in["only_candidate"]
    else:
        kept_pdf["candidate"] = kept_pdf["candidate_idx"].map(lambda idx: candidate_list_in[int(idx)])
    return kept_pdf.reset_index(drop=True)

# FUNCTION: REPLAY ONE ARCHIVED QUARTER WHEN IT IS A DEVELOPMENT PERIOD
def get_replay_return_float(design_module_in, ohlcv_array_dict_in, data_context_in, row_in):
    """
    The version 2.0 return of one archived quarter. A date that is not a development period is left unmatched.

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Bars
        data_context_in (DataContext): Point-in-time context
        row_in (pd.Series): Archived quarter

    Returns:
        float: Return, or NaN when the quarter is not a development period
    """
    # THE CONTINUOUS SLICE WHEN THE DATES MATCH A DEVELOPMENT PERIOD; OTHERWISE DO NOT FALL BACK TO A FRESH WINDOW
    from so.core.holdout import get_equity_total_return_float
    period_pdf = design_module_in.get_bar_period_pdf(ohlcv_array_dict_in)
    start_date, end_date = pd.Timestamp(row_in["valid_start"]).date(), pd.Timestamp(row_in["valid_end"]).date()
    match_pdf = period_pdf[(period_pdf["period_start"].map(lambda value: pd.Timestamp(value).date()) == start_date)
                           & (period_pdf["period_end"].map(lambda value: pd.Timestamp(value).date()) == end_date)]
    if len(match_pdf) != 1:
        return float("nan")
    replay_dict = design_module_in.run_candidate_replay_dict(ohlcv_array_dict_in, row_in["valid_start"], row_in["valid_end"], row_in["candidate"], data_context_in)
    return get_equity_total_return_float(replay_dict["daily_equity_pdf"])

# FUNCTION: RUN THE CALIBRATION
def main():
    """
    Compares archived and replayed returns, writes a summary, and logs one note.

    Returns:
        None
    """
    # IMPORT THE DESIGN AFTER THE PACKAGE IS KNOWN
    import importlib
    package_str = get_package_str()
    if package_str not in _SPEC_DICT:
        raise SystemExit(f"no old-bounds calibration for {package_str}.")
    exp_config = importlib.import_module(f"experiments.{package_str}.config")
    design = importlib.import_module(f"experiments.{package_str}.design")
    if get_note_count_int(exp_config.EXPERIMENT_NAME) > 0:
        raise SystemExit(f"{exp_config.EXPERIMENT_NAME} already has an old-bounds calibration note. Refusing to run twice.")
    from so.core.development_span import get_development_ohlcv_dict
    from so.core.holdout import get_governing_selection_pdf
    from so.core.trial_log import log_trial_dict
    span_dict = get_development_ohlcv_dict(int(design.PERIOD_RULE["embargo_sessions"]))
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    archived_pdf = get_archived_pdf(_SPEC_DICT[package_str], span_dict["development_end"], list(design.CANDIDATE_LIST))
    replay_list = []
    for row in archived_pdf.itertuples(index=False):
        replay_list.append(get_replay_return_float(design, span_dict["ohlcv_array_dict"], data_context, row))
        print(f"fold {int(row.fold_id)} {row.candidate}")
    archived_pdf["replay_return"] = replay_list
    comparable_pdf = archived_pdf[archived_pdf["replay_return"].notna()].copy()
    comparable_pdf["return_diff"] = comparable_pdf["replay_return"] - comparable_pdf["valid_total_return"]
    from so.core.evaluation import get_tolerance_comparison_dict
    comparison_dict = get_tolerance_comparison_dict(comparable_pdf["replay_return"], comparable_pdf["valid_total_return"])
    return_match_count = int(comparison_dict["match_count"])
    # SELECTIONS FROM THE ARCHIVED EXCESS AND FROM THE REPLAYED EXCESS, WITH THE VERSION 2.0 RULE
    archived_score_pdf = comparable_pdf.rename(columns={"valid_excess_return": "excess_return"})[["fold_id", "candidate", "excess_return"]]
    replay_score_pdf = comparable_pdf.assign(excess_return=comparable_pdf["replay_return"] - comparable_pdf["valid_buy_hold_total_return"])[["fold_id", "candidate", "excess_return"]]
    period_pdf = comparable_pdf[["fold_id", "valid_start", "valid_end"]].drop_duplicates().rename(columns={"fold_id": "period_id", "valid_start": "period_start", "valid_end": "period_end"})
    archived_selection_pdf = get_governing_selection_pdf(design, archived_score_pdf, period_pdf)
    replay_selection_pdf = get_governing_selection_pdf(design, replay_score_pdf, period_pdf)
    selection_match_count = int((archived_selection_pdf["candidate"].to_numpy() == replay_selection_pdf["candidate"].to_numpy()).sum())
    summary_dict = {"package": package_str, "archived_rows": int(len(archived_pdf)), "compared_rows": int(len(comparable_pdf)),
                    "returns_matched": return_match_count, "returns_total": int(len(comparable_pdf)),
                    "selections_matched": selection_match_count, "selections_total": int(len(archived_selection_pdf)),
                    "max_abs_return_diff": comparison_dict["max_abs_diff"]}
    output_folder_str = f"{paths.LOCAL_EXPERIMENTZONE_PATH_STR}{exp_config.EXPERIMENT_NAME}/old_bounds_calibration/"
    from so.core.local_file_management import write_csv_file_to_path
    write_csv_file_to_path(pd.DataFrame([summary_dict]), "summary_data.csv", output_folder_str)
    print(json.dumps(summary_dict))
    print(f"returns matched {return_match_count}/{comparison_dict['row_count']} within {config.NUMERIC_TOLERANCE}; max abs return diff {comparison_dict['max_abs_diff']}")
    log_trial_dict(exp_config, "note", {"calibration": "old-bounds"}, summary_dict, False,
                   note_str_in="old-bounds calibration; diagnostic; informs no decision")
    print("logged one note row")

# RUN WHEN CALLED AS A SCRIPT
if __name__ == "__main__":
    main()
