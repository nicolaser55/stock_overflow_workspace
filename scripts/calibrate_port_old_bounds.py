import importlib
import json
import sys
import numpy as np
import pandas as pd
# IMPORT THE SHARED PATHS AND THE NUMERIC TOLERANCE
from so import config, paths

"""
Old-bounds calibration for one version-2.0 rule experiment (Nicolas, 2026-10-12; corrected 2026-10-13).

Replays every candidate with the version 2.0 code on the archived quarter bounds, the same comparison exp03's
calibration runs. These experiments scored a quarter as a slice of one continuous path, so the replay is that path
on the old bounds, not a fresh window and not a development-period date match. Bars start before the first quarter,
so the moving average, the volatility and the VIX features exist at the first decision. They are read through the
point-in-time context inside the design. Quarters that end on or after the development end are dropped before any
replay. A comparison of 0 rows, or any nan return, stops the script before a summary file and before the note row.
A complete comparison appends one trial-log row with stage "note" and refuses to run when that row already exists.

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
# SESSIONS OF HISTORY REQUIRED BEFORE THE FIRST QUARTER (MA 200, VOLATILITY 60, VIX PERCENTILE 250)
_WARMUP_SESSION_COUNT = 250
# RETURN COLUMNS READ FROM THE ARCHIVE AFTER THE QUARTER DATES HAVE BEEN FILTERED
_RETURN_COLUMN_LIST = ["fold_id", "candidate_idx", "candidate_name", "valid_start", "valid_end", "valid_total_return",
                       "valid_buy_hold_total_return", "valid_excess_return"]

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

# FUNCTION: SESSIONS STRICTLY BEFORE A QUARTER START
def get_warmup_count_int(session_date_list_in, quarter_start_in):
    """
    Counts price sessions before the quarter. The replay needs them for the moving average, the volatility and the
    VIX features.

    Args:
        session_date_list_in (list): Session dates of the bars
        quarter_start_in: First session of the first replayed quarter

    Returns:
        int: Sessions before the quarter
    """
    # COUNT SESSIONS WHOSE DATE IS BEFORE THE QUARTER
    start_date = pd.Timestamp(quarter_start_in).date()
    return int(sum(pd.Timestamp(session_date).date() < start_date for session_date in session_date_list_in))

# FUNCTION: FOLD IDS WHOSE QUARTER ENDS BEFORE THE DEVELOPMENT END
def get_kept_fold_id_set(date_pdf_in, development_end_in):
    """
    Keeps a fold only when its quarter ends before the development end. An end on that date is dropped.

    Args:
        date_pdf_in (pd.DataFrame): fold_id, valid_end
        development_end_in (datetime.date): Development end

    Returns:
        set: Kept fold ids
    """
    # THE END DATE IS COMPARED BEFORE ANY RETURN COLUMN IS USED
    end_date_series = pd.to_datetime(date_pdf_in["valid_end"]).dt.date
    return set(int(fold_id) for fold_id in date_pdf_in.loc[end_date_series < development_end_in, "fold_id"])

# FUNCTION: ARCHIVED QUARTER ROWS THAT END BEFORE THE DEVELOPMENT END
def get_archived_pdf(spec_dict_in, development_end_in, candidate_list_in):
    """
    Reads the archived dates, drops every quarter that ends on or after the development end, then reads return
    columns for the kept folds only.

    Args:
        spec_dict_in (dict): Archive location
        development_end_in (datetime.date): Development end
        candidate_list_in (list[str]): Version 2.0 candidate names, in order

    Returns:
        pd.DataFrame: Kept rows with a candidate name, valid_total_return, valid_buy_hold_total_return, valid_excess_return
    """
    # DATES FIRST. RETURN COLUMNS OF A DROPPED QUARTER ARE NOT KEPT.
    file_str = f"{paths.LOCAL_EXPERIMENTZONE_PATH_STR}{spec_dict_in['old_name']}/{spec_dict_in['folder']}/candidate_period_data.csv"
    date_pdf = pd.read_csv(file_str, usecols=["fold_id", "valid_start", "valid_end"])
    kept_id_set = get_kept_fold_id_set(date_pdf, development_end_in)
    header_list = list(pd.read_csv(file_str, nrows=0).columns)
    column_list = [column_str for column_str in _RETURN_COLUMN_LIST if column_str in header_list]
    piece_list = []
    for chunk_pdf in pd.read_csv(file_str, usecols=column_list, chunksize=200):
        kept_pdf = chunk_pdf[chunk_pdf["fold_id"].isin(kept_id_set)]
        if len(kept_pdf):
            piece_list.append(kept_pdf)
    if not piece_list:
        return pd.DataFrame(columns=column_list + ["candidate"])
    archived_pdf = pd.concat(piece_list, ignore_index=True)
    # NAME EACH ROW THE WAY THE VERSION 2.0 DESIGN NAMES IT
    if "candidate_name" in archived_pdf.columns:
        archived_pdf["candidate"] = archived_pdf["candidate_name"].astype(str)
    else:
        archived_pdf["candidate"] = archived_pdf["candidate_idx"].map(lambda idx: candidate_list_in[int(idx)])
    if "only_candidate" in spec_dict_in:
        archived_pdf = archived_pdf[archived_pdf["candidate"] == spec_dict_in["only_candidate"]].copy()
    return archived_pdf.sort_values(["fold_id", "candidate"]).reset_index(drop=True)

# FUNCTION: OLD QUARTER BOUNDS PLUS A TAIL SO THE LAST SCORED QUARTER IS NOT LIQUIDATED
def get_replay_period_pdf(archived_pdf_in, session_date_list_in, tail_end_in):
    """
    One period per kept fold, then a tail through tail_end_in when any session sits after the last scored quarter.
    The tail is not scored. It keeps the last scored session off the end of the simulation, which is how the archived
    continuous path treated that session.

    Args:
        archived_pdf_in (pd.DataFrame): Kept archived rows
        session_date_list_in (list): Session dates of the bars
        tail_end_in: Last session the tail may use

    Returns:
        pd.DataFrame: period_id, period_start, period_end. period_id -1 is the tail.
    """
    # ONE ROW PER FOLD, IN FOLD ORDER
    fold_pdf = archived_pdf_in[["fold_id", "valid_start", "valid_end"]].drop_duplicates("fold_id").sort_values("fold_id")
    row_dict_list = [{"period_id": int(fold_id), "period_start": pd.Timestamp(start).date(), "period_end": pd.Timestamp(end).date()}
                     for fold_id, start, end in zip(fold_pdf["fold_id"], fold_pdf["valid_start"], fold_pdf["valid_end"])]
    last_end = row_dict_list[-1]["period_end"]
    tail_end = pd.Timestamp(tail_end_in).date()
    tail_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in
                 if last_end < pd.Timestamp(session_date).date() <= tail_end]
    if tail_list:
        row_dict_list.append({"period_id": -1, "period_start": tail_list[0], "period_end": tail_list[-1]})
    return pd.DataFrame(row_dict_list)

# FUNCTION: REPLAY EVERY CANDIDATE ON THE OLD BOUNDS
def get_replayed_return_pdf(design_module_in, ohlcv_array_dict_in, data_context_in, period_pdf_in, candidate_list_in):
    """
    Installs the old periods as the design's period table and calls run_candidate_replay_dict on each scored bound.
    The design then replays one continuous path over those bounds, with features from the whole bar array. The tail
    period is not requested.

    Args:
        design_module_in (module): Design. The function that is called is the module that defines run_candidate_replay_dict.
        ohlcv_array_dict_in (dict): Bars, including the warmup sessions before the first quarter
        data_context_in (DataContext | None): Point-in-time context
        period_pdf_in (pd.DataFrame): Old periods and the optional tail
        candidate_list_in (list[str]): Candidates, in order

    Returns:
        pd.DataFrame: fold_id, candidate, replay_return
    """
    # THE DESIGN LOOKS UP get_bar_period_pdf IN ITS OWN MODULE. INSTALL THE OLD PERIODS THERE FOR THIS CALL.
    module = sys.modules[design_module_in.run_candidate_replay_dict.__module__]
    original_func = module.get_bar_period_pdf
    module._cache_dict.clear()
    def get_installed_period_pdf(ohlcv_array_dict_in, period_pdf=period_pdf_in):
        return period_pdf.copy()
    module.get_bar_period_pdf = get_installed_period_pdf
    try:
        # SCORE EVERY OLD QUARTER. THE TAIL (period_id < 0) IS ONLY THERE SO THE PATH DOES NOT END ON A SCORED SESSION.
        from so.core.holdout import get_equity_total_return_float
        row_dict_list = []
        scored_pdf = period_pdf_in[period_pdf_in["period_id"] >= 0]
        for period_row in scored_pdf.itertuples(index=False):
            for candidate in candidate_list_in:
                replay_dict = module.run_candidate_replay_dict(ohlcv_array_dict_in, period_row.period_start, period_row.period_end,
                                                               candidate, data_context_in)
                row_dict_list.append({"fold_id": int(period_row.period_id), "candidate": candidate,
                                      "replay_return": get_equity_total_return_float(replay_dict["daily_equity_pdf"])})
                print(f"fold {int(period_row.period_id)} {candidate}", flush=True)
        return pd.DataFrame(row_dict_list)
    finally:
        # RESTORE THE DEVELOPMENT PERIODS AND DROP THE PATH CACHED FOR THE OLD BOUNDS
        module.get_bar_period_pdf = original_func
        module._cache_dict.clear()

# FUNCTION: BUY-AND-HOLD SLICES ON THE SAME PATH
def get_buy_hold_return_pdf(ohlcv_array_dict_in, period_pdf_in):
    """
    Buy-and-hold from the first period start through the last period end (the tail, when there is one), cut into the
    scored quarters.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Old periods and the optional tail

    Returns:
        pd.DataFrame: fold_id, buy_hold_return
    """
    # THE SAME SLICE THE ARCHIVED CONTINUOUS PATH USED
    from so.core.continuous_replay import get_period_return_pdf
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    scored_pdf = period_pdf_in[period_pdf_in["period_id"] >= 0]
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1])
    slice_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], scored_pdf)
    return pd.DataFrame({"fold_id": slice_pdf["period_id"].astype(int), "buy_hold_return": slice_pdf["total_return"].to_numpy()})

# FUNCTION: WHY A COMPARISON MUST NOT BE PUBLISHED
def get_calibration_failure_str(replay_return_list_in, archived_return_list_in, missing_count_int_in=0):
    """
    A comparison of 0 rows, a row that did not join, or any nan is not published.

    Args:
        replay_return_list_in (list[float]): Replayed returns
        archived_return_list_in (list[float]): Archived returns
        missing_count_int_in (int): Rows that failed to join

    Returns:
        str: The reason, or "" when the comparison is complete
    """
    # AN INCOMPLETE JOIN IS NOT A COMPLETE COMPARISON
    if int(missing_count_int_in):
        return "a candidate row did not join"
    replay_arr = np.asarray(list(replay_return_list_in), dtype=float)
    archived_arr = np.asarray(list(archived_return_list_in), dtype=float)
    if replay_arr.size == 0 or archived_arr.size == 0 or replay_arr.size != archived_arr.size:
        return "compared 0 rows"
    if not np.isfinite(replay_arr).all() or not np.isfinite(archived_arr).all():
        return "a return is nan"
    return ""

# FUNCTION: WRITE THE SUMMARY AND THE NOTE ONLY AFTER A COMPLETE COMPARISON
def publish_calibration_dict(compare_pdf_in, summary_dict_in, exp_config_in, log_func_in, write_func_in):
    """
    Publishes one calibration. An empty comparison or a nan raises, and neither callback is called.

    Args:
        compare_pdf_in (pd.DataFrame): Joined rows with replay_return and valid_total_return
        summary_dict_in (dict): Summary already computed from that comparison
        exp_config_in (module): Experiment config
        log_func_in (callable): Trial-log writer (the real log in the script, a stub in the test)
        write_func_in (callable): Summary writer

    Returns:
        dict: The summary
    """
    # REFUSE BEFORE EITHER WRITE
    replay_list = [] if compare_pdf_in is None or len(compare_pdf_in) == 0 or "replay_return" not in compare_pdf_in.columns else compare_pdf_in["replay_return"]
    archived_list = [] if compare_pdf_in is None or len(compare_pdf_in) == 0 or "valid_total_return" not in compare_pdf_in.columns else compare_pdf_in["valid_total_return"]
    failure_str = get_calibration_failure_str(replay_list, archived_list, 0)
    if failure_str:
        raise RuntimeError(failure_str)
    write_func_in(summary_dict_in)
    log_func_in(exp_config_in, "note", {"calibration": "old-bounds"}, summary_dict_in, False,
                note_str_in="old-bounds calibration; diagnostic; informs no decision")
    return summary_dict_in

# FUNCTION: ONE ARCHIVED QUARTER, FOR THE CHECK THAT DOES NOT LOG
def get_one_quarter_match_dict(package_str_in, valid_start_str_in, valid_end_str_in, ohlcv_pdf_in=None):
    """
    Replays every candidate of one archived quarter on those bounds and compares the returns with the archive.
    Does not read the trial log and does not write a note.

    Args:
        package_str_in (str): Package name, without the experiments. prefix
        valid_start_str_in (str): Quarter start
        valid_end_str_in (str): Quarter end
        ohlcv_pdf_in (pd.DataFrame | None): Bars already loaded

    Returns:
        dict: package, match_count, row_count, max_abs_diff, warmup_count
    """
    # LOAD THE DESIGN, THE DEVELOPMENT BARS AND THE KEPT ARCHIVE
    from so.core.development_span import get_development_ohlcv_dict
    from so.core.evaluation import get_tolerance_comparison_dict
    spec_dict = _SPEC_DICT[package_str_in]
    design = importlib.import_module(f"experiments.{package_str_in}.design")
    span_dict = get_development_ohlcv_dict(int(design.PERIOD_RULE["embargo_sessions"]), ohlcv_pdf_in)
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    archived_pdf = get_archived_pdf(spec_dict, span_dict["development_end"], list(design.CANDIDATE_LIST))
    start_date, end_date = pd.Timestamp(valid_start_str_in).date(), pd.Timestamp(valid_end_str_in).date()
    quarter_pdf = archived_pdf[(pd.to_datetime(archived_pdf["valid_start"]).dt.date == start_date)
                               & (pd.to_datetime(archived_pdf["valid_end"]).dt.date == end_date)].copy()
    if len(quarter_pdf) == 0:
        return {"package": package_str_in, "match_count": 0, "row_count": 0, "finite_count": 0, "max_abs_diff": float("nan"), "warmup_count": 0}
    # THE TAIL IS THE NEXT KEPT QUARTER, SO THIS QUARTER IS NOT THE END OF THE PATH
    later_pdf = archived_pdf[pd.to_datetime(archived_pdf["valid_start"]).dt.date > start_date][["fold_id", "valid_start", "valid_end"]].drop_duplicates("fold_id")
    tail_end = later_pdf["valid_end"].iloc[0] if len(later_pdf) else span_dict["development_end"]
    warmup_count = get_warmup_count_int(span_dict["ohlcv_array_dict"]["session_date_list"], start_date)
    if warmup_count < _WARMUP_SESSION_COUNT:
        raise RuntimeError(f"{package_str_in} has {warmup_count} sessions before {start_date}.")
    period_pdf = get_replay_period_pdf(quarter_pdf, span_dict["ohlcv_array_dict"]["session_date_list"], tail_end)
    replay_pdf = get_replayed_return_pdf(design, span_dict["ohlcv_array_dict"], data_context, period_pdf, list(design.CANDIDATE_LIST))
    # JOIN ON THE CANDIDATE NAME AND COMPARE AT THE NUMERIC TOLERANCE
    compare_pdf = replay_pdf.merge(quarter_pdf[["fold_id", "candidate", "valid_total_return"]], on=["fold_id", "candidate"], how="outer", indicator=True)
    both_pdf = compare_pdf[compare_pdf["_merge"] == "both"]
    comparison_dict = get_tolerance_comparison_dict(both_pdf["replay_return"], both_pdf["valid_total_return"]) if len(both_pdf) else {"match_count": 0, "row_count": 0, "max_abs_diff": float("nan")}
    finite_count = int(np.isfinite(both_pdf["replay_return"].to_numpy(dtype=float)).sum()) if len(both_pdf) else 0
    return {"package": package_str_in, "match_count": int(comparison_dict["match_count"]), "row_count": int(comparison_dict["row_count"]),
            "finite_count": finite_count, "max_abs_diff": comparison_dict["max_abs_diff"], "warmup_count": int(warmup_count)}

# FUNCTION: RUN THE CALIBRATION
def main():
    """
    Compares archived and replayed returns, writes a summary, and logs one note. A 0-row comparison or a nan does
    neither.

    Returns:
        None
    """
    # IMPORT THE DESIGN AFTER THE PACKAGE IS KNOWN
    package_str = get_package_str()
    if package_str not in _SPEC_DICT:
        raise SystemExit(f"no old-bounds calibration for {package_str}.")
    exp_config = importlib.import_module(f"experiments.{package_str}.config")
    design = importlib.import_module(f"experiments.{package_str}.design")
    if get_note_count_int(exp_config.EXPERIMENT_NAME) > 0:
        raise SystemExit(f"{exp_config.EXPERIMENT_NAME} already has an old-bounds calibration note. Refusing to run twice.")
    # BARS THROUGH THE DEVELOPMENT END, INCLUDING THE HISTORY BEFORE THE FIRST QUARTER
    from so.core.development_span import get_development_ohlcv_dict
    from so.core.evaluation import get_tolerance_comparison_dict
    from so.core.holdout import get_governing_selection_pdf
    span_dict = get_development_ohlcv_dict(int(design.PERIOD_RULE["embargo_sessions"]))
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    archived_pdf = get_archived_pdf(_SPEC_DICT[package_str], span_dict["development_end"], list(design.CANDIDATE_LIST))
    if len(archived_pdf) == 0:
        raise SystemExit("old-bounds calibration failed: compared 0 rows")
    warmup_count = get_warmup_count_int(span_dict["ohlcv_array_dict"]["session_date_list"], archived_pdf["valid_start"].iloc[0])
    if warmup_count < _WARMUP_SESSION_COUNT:
        raise SystemExit(f"old-bounds calibration failed: {warmup_count} sessions before the first quarter.")
    print(f"development_end {span_dict['development_end']} kept_rows {len(archived_pdf)} warmup_sessions {warmup_count}", flush=True)
    # REPLAY ON THE OLD BOUNDS, THEN BUY-AND-HOLD ON THE SAME SPAN
    period_pdf = get_replay_period_pdf(archived_pdf, span_dict["ohlcv_array_dict"]["session_date_list"], span_dict["development_end"])
    replay_pdf = get_replayed_return_pdf(design, span_dict["ohlcv_array_dict"], data_context, period_pdf, list(design.CANDIDATE_LIST))
    buy_hold_pdf = get_buy_hold_return_pdf(span_dict["ohlcv_array_dict"], period_pdf)
    compare_pdf = replay_pdf.merge(archived_pdf[["fold_id", "candidate", "valid_total_return", "valid_buy_hold_total_return", "valid_excess_return"]],
                                   on=["fold_id", "candidate"], how="outer", indicator=True)
    missing_count = int((compare_pdf["_merge"] != "both").sum())
    both_pdf = compare_pdf[compare_pdf["_merge"] == "both"].copy()
    both_pdf = both_pdf.merge(buy_hold_pdf, on="fold_id", how="left")
    # STRATEGY AND BUY-AND-HOLD TOGETHER: A NAN IN EITHER REFUSES THE NOTE
    failure_str = get_calibration_failure_str(list(both_pdf["replay_return"]) + list(both_pdf["buy_hold_return"]),
                                              list(both_pdf["valid_total_return"]) + list(both_pdf["valid_buy_hold_total_return"]), missing_count)
    if failure_str:
        raise SystemExit(f"old-bounds calibration failed: {failure_str}")
    # THE PROTOCOL SELECTION RULE, WITH NUMERIC_TOLERANCE, ON THE ARCHIVED SCORES AND ON THE REPLAYED SCORES
    comparison_dict = get_tolerance_comparison_dict(both_pdf["replay_return"], both_pdf["valid_total_return"])
    buy_hold_comparison_dict = get_tolerance_comparison_dict(both_pdf["buy_hold_return"], both_pdf["valid_buy_hold_total_return"])
    score_period_pdf = period_pdf[period_pdf["period_id"] >= 0][["period_id", "period_start", "period_end"]]
    archived_score_pdf = both_pdf.rename(columns={"valid_excess_return": "excess_return"})[["fold_id", "candidate", "excess_return"]]
    replay_score_pdf = both_pdf.assign(excess_return=both_pdf["replay_return"] - both_pdf["buy_hold_return"])[["fold_id", "candidate", "excess_return"]]
    archived_selection_pdf = get_governing_selection_pdf(design, archived_score_pdf, score_period_pdf)
    replay_selection_pdf = get_governing_selection_pdf(design, replay_score_pdf, score_period_pdf)
    selection_match_count = int((archived_selection_pdf["candidate"].to_numpy() == replay_selection_pdf["candidate"].to_numpy()).sum())
    summary_dict = {"package": package_str, "archived_rows": int(len(archived_pdf)), "compared_rows": int(len(both_pdf)),
                    "returns_matched": int(comparison_dict["match_count"]), "returns_total": int(comparison_dict["row_count"]),
                    "buy_hold_matched": int(buy_hold_comparison_dict["match_count"]), "buy_hold_total": int(buy_hold_comparison_dict["row_count"]),
                    "selections_matched": selection_match_count, "selections_total": int(len(archived_selection_pdf)),
                    "max_abs_return_diff": comparison_dict["max_abs_diff"], "warmup_sessions": int(warmup_count)}
    # THE SUMMARY FILE AND THE NOTE ROW ARE THE PUBLISH STEP. IT RAISES AGAIN IF THE FRAME IS EMPTY OR HAS A NAN.
    from so.core.local_file_management import write_csv_file_to_path
    from so.core.trial_log import log_trial_dict
    output_folder_str = paths.get_experiment_data_path_str(exp_config.EXPERIMENT_NAME, "old_bounds_calibration")
    def write_summary(summary_dict_in, folder_str=output_folder_str):
        write_csv_file_to_path(pd.DataFrame([summary_dict_in]), f"{folder_str}summary_data.csv", "W", alert_in=False)
    publish_calibration_dict(both_pdf, summary_dict, exp_config, log_trial_dict, write_summary)
    print(json.dumps(summary_dict), flush=True)
    print(f"returns matched {comparison_dict['match_count']}/{comparison_dict['row_count']} within {config.NUMERIC_TOLERANCE}; max abs return diff {comparison_dict['max_abs_diff']}", flush=True)
    print("logged one note row", flush=True)

# RUN WHEN CALLED AS A SCRIPT
if __name__ == "__main__":
    main()
