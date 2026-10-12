import json
import sys
import pandas as pd
# IMPORT THE EXPERIMENT AND THE SHARED PATHS
from experiments.exp03_ath_exit import config as exp_config
from experiments.exp03_ath_exit import design
from so import paths

"""
Old-bounds calibration for exp03_ath_exit_v2 (Nicolas, 2026-10-12).

Replays every candidate with the version 2.0 code on the archived quarter bounds, and only on quarters that end
before the development end. It then applies the protocol selection rule to those scores. This is a diagnostic over
data both versions already used. It informs no decision. It appends one trial-log row with stage "note".

Quarters that end on or after the development end are dropped before any return column is kept. Their numbers are
not printed.

Usage: venv-main/Scripts/python.exe -u scripts/calibrate_exp03_old_bounds.py
"""

# ARCHIVED STEP 02 TABLES (READ). THE SUMMARY BELOW IS A FILE THIS SCRIPT CREATES.
_OLD_FOLDER_STR = f"{paths.LOCAL_EXPERIMENTZONE_PATH_STR}exp03_ath_exit/step02_walk_forward_data/"
# MATCH A FLOAT THAT SURVIVES A CSV ROUND TRIP
_MATCH_ABS_TOLERANCE_FLOAT = 1e-9

# FUNCTION: THE DEVELOPMENT BARS AND THE DEVELOPMENT END
def get_span_dict():
    """
    Loads SPY through the development end. The holdout start is not printed.

    Returns:
        dict: ohlcv_array_dict, development_end, anchor_session_list, data_context
    """
    # LOAD THE BARS, THEN THE POINT-IN-TIME CONTEXT THE REPLAY READS
    from so.core.development_span import get_development_ohlcv_dict
    span_dict = get_development_ohlcv_dict(exp_config.EMBARGO_TRADING_DAYS)
    data_context = design.get_development_data_context(span_dict["anchor_session_list"])
    span_dict["data_context"] = data_context
    return span_dict

# FUNCTION: ARCHIVED QUARTERS THAT END BEFORE THE DEVELOPMENT END
def get_kept_fold_pdf(development_end_in):
    """
    Reads the archived schedule dates and keeps quarters whose validation end is before the development end.

    Args:
        development_end_in (datetime.date): Development end

    Returns:
        pd.DataFrame: fold_id, valid_start, valid_end
    """
    # DATES ONLY. RETURN COLUMNS ARE NOT IN THIS FILE.
    fold_pdf = pd.read_csv(f"{_OLD_FOLDER_STR}fold_schedule_data.csv", usecols=["fold_id", "valid_start", "valid_end"])
    fold_pdf["valid_end_date"] = pd.to_datetime(fold_pdf["valid_end"]).dt.date
    kept_pdf = fold_pdf[fold_pdf["valid_end_date"] < development_end_in].drop(columns=["valid_end_date"])
    return kept_pdf.sort_values("fold_id").reset_index(drop=True)

# FUNCTION: READ RETURN ROWS FOR THE KEPT QUARTERS ONLY
def get_filtered_csv_pdf(file_name_str_in, column_list_in, keep_id_set_in):
    """
    Reads one archived table in chunks and drops every row whose fold is not kept, before the chunk is stored.

    Args:
        file_name_str_in (str): File name inside the archived step 02 folder
        column_list_in (list[str]): Columns to read
        keep_id_set_in (set): Fold ids that end before the development end

    Returns:
        pd.DataFrame: Kept rows
    """
    # DROP EXCLUDED FOLDS INSIDE EACH CHUNK
    piece_list = []
    for chunk_pdf in pd.read_csv(f"{_OLD_FOLDER_STR}{file_name_str_in}", usecols=column_list_in, chunksize=200):
        kept_pdf = chunk_pdf[chunk_pdf["fold_id"].isin(keep_id_set_in)]
        if len(kept_pdf):
            piece_list.append(kept_pdf)
    if not piece_list:
        return pd.DataFrame(columns=column_list_in)
    return pd.concat(piece_list, ignore_index=True)

# FUNCTION: THE ARCHIVED CANDIDATE NAME
def get_old_candidate_name_str(ath_within_in, rule_str_in):
    """
    The version 2.0 name of an archived rule row.

    Args:
        ath_within_in (float): Exit threshold
        rule_str_in (str): Rule name

    Returns:
        str: Candidate name
    """
    # THREE DECIMALS, AS get_candidate_name_str
    return f"{float(ath_within_in):.3f}|{rule_str_in}"

# FUNCTION: ARCHIVED FRESH-WINDOW RETURNS ON THE KEPT QUARTERS
def get_old_return_pdf(keep_id_set_in):
    """
    One row per kept quarter and candidate.

    Args:
        keep_id_set_in (set): Fold ids

    Returns:
        pd.DataFrame: fold_id, candidate, old_total_return, old_buy_hold_total_return
    """
    # KEEP THE RETURN COLUMNS OF THE KEPT FOLDS
    column_list = ["fold_id", "ath_within", "rule", "valid_total_return", "valid_buy_hold_total_return"]
    old_pdf = get_filtered_csv_pdf("validation_candidate_data.csv", column_list, keep_id_set_in)
    old_pdf["candidate"] = [get_old_candidate_name_str(ath, rule) for ath, rule in zip(old_pdf["ath_within"], old_pdf["rule"])]
    return old_pdf.rename(columns={"valid_total_return": "old_total_return", "valid_buy_hold_total_return": "old_buy_hold_total_return"})

# FUNCTION: ARCHIVED PRIOR-ONLY SELECTIONS ON THE KEPT QUARTERS
def get_old_selection_pdf(keep_id_set_in):
    """
    The candidate the archived run put in force on each kept quarter that has a prior-only row.

    Args:
        keep_id_set_in (set): Fold ids

    Returns:
        pd.DataFrame: fold_id, old_candidate
    """
    # NAMES ONLY
    old_pdf = get_filtered_csv_pdf("prior_only_data.csv", ["fold_id", "ath_within", "rule"], keep_id_set_in)
    old_pdf["old_candidate"] = [get_old_candidate_name_str(ath, rule) for ath, rule in zip(old_pdf["ath_within"], old_pdf["rule"])]
    return old_pdf[["fold_id", "old_candidate"]]

# FUNCTION: REPLAY EVERY CANDIDATE ON THE KEPT BOUNDS
def get_new_return_pdf(span_dict_in, kept_fold_pdf_in):
    """
    Fresh windows, version 2.0 code, archived start and end dates.

    Args:
        span_dict_in (dict): Development bars and context
        kept_fold_pdf_in (pd.DataFrame): Kept quarters

    Returns:
        pd.DataFrame: fold_id, candidate, total_return, buy_hold_total_return, excess_return
    """
    # IMPORT THE RETURN HELPERS HERE
    from so.core.holdout import get_equity_total_return_float
    from so.core.reentry_simulation import get_buy_and_hold_result_dict
    # SCORE EACH KEPT QUARTER
    ohlcv_array_dict = span_dict_in["ohlcv_array_dict"]
    data_context = span_dict_in["data_context"]
    row_dict_list = []
    quarter_count = len(kept_fold_pdf_in)
    for quarter_idx, fold_row in enumerate(kept_fold_pdf_in.itertuples(index=False)):
        print(f"quarter {quarter_idx + 1}/{quarter_count} fold {int(fold_row.fold_id)} {fold_row.valid_start} -> {fold_row.valid_end}", flush=True)
        buy_hold_float = get_buy_and_hold_result_dict(ohlcv_array_dict, fold_row.valid_start, fold_row.valid_end)["metric_dict"]["total_return"]
        for candidate in design.CANDIDATE_LIST:
            replay_dict = design.run_candidate_replay_dict(ohlcv_array_dict, fold_row.valid_start, fold_row.valid_end, candidate, data_context)
            total_float = get_equity_total_return_float(replay_dict["daily_equity_pdf"])
            row_dict_list.append({"fold_id": int(fold_row.fold_id), "candidate": candidate, "total_return": total_float,
                                  "buy_hold_total_return": buy_hold_float, "excess_return": total_float - buy_hold_float})
    return pd.DataFrame(row_dict_list)

# FUNCTION: WHETHER TWO RETURNS MATCH
def get_match_bool(left_float_in, right_float_in):
    """
    True when the absolute difference is within the CSV tolerance.

    Args:
        left_float_in (float): New return
        right_float_in (float): Archived return

    Returns:
        bool: Match
    """
    # ABSOLUTE TOLERANCE
    return abs(float(left_float_in) - float(right_float_in)) <= _MATCH_ABS_TOLERANCE_FLOAT

# FUNCTION: PRIOR-ONLY CANDIDATES FROM THE NEW SCORES
def get_new_selection_pdf(score_pdf_in, kept_fold_pdf_in):
    """
    The protocol selection rule: mean excess over the last 4 quarters, then the tie order. The choice at quarter f
    governs quarter f + 1. Quarter 0 has no history.

    Args:
        score_pdf_in (pd.DataFrame): New scores
        kept_fold_pdf_in (pd.DataFrame): Kept quarters

    Returns:
        pd.DataFrame: period_id, candidate
    """
    # THE SAME FUNCTION THE DEVELOPMENT RUN USES
    from so.core.holdout import get_governing_selection_pdf
    period_pdf = pd.DataFrame({"period_id": kept_fold_pdf_in["fold_id"].astype(int),
                               "period_start": kept_fold_pdf_in["valid_start"],
                               "period_end": kept_fold_pdf_in["valid_end"]})
    return get_governing_selection_pdf(design, score_pdf_in, period_pdf)

# FUNCTION: HOW MANY NOTE ROWS THIS EXPERIMENT ALREADY HAS
def get_note_count_int():
    """
    Counts stage "note" rows of exp03_ath_exit_v2.

    Returns:
        int: Count
    """
    # THE STAGE COLUMN ONLY
    trial_pdf = pd.read_csv(paths.LOCAL_TRIAL_LOG_FILE_PATH_STR, usecols=["experiment", "stage"])
    note_pdf = trial_pdf[(trial_pdf["experiment"] == exp_config.EXPERIMENT_NAME) & (trial_pdf["stage"] == "note")]
    return int(len(note_pdf))

# FUNCTION: RUN THE DIAGNOSTIC AND LOG ONE NOTE
def run_calibration_dict():
    """
    Compares returns and prior-only selections, writes a summary, and appends one note row.

    Returns:
        dict: The summary
    """
    # REFUSE A SECOND NOTE
    print("old-bounds calibration started", flush=True)
    if get_note_count_int():
        print("a note row for exp03_ath_exit_v2 already exists; this diagnostic is not repeated", flush=True)
        return {}
    # BARS, THEN THE QUARTERS THAT END BEFORE THE DEVELOPMENT END
    span_dict = get_span_dict()
    development_end = span_dict["development_end"]
    kept_fold_pdf = get_kept_fold_pdf(development_end)
    keep_id_set = set(int(fold_id) for fold_id in kept_fold_pdf["fold_id"])
    schedule_pdf = pd.read_csv(f"{_OLD_FOLDER_STR}fold_schedule_data.csv", usecols=["fold_id", "valid_end"])
    excluded_count = int((pd.to_datetime(schedule_pdf["valid_end"]).dt.date >= development_end).sum())
    print(f"development_end {development_end}", flush=True)
    print(f"kept_quarters {len(kept_fold_pdf)} excluded_quarters {excluded_count}", flush=True)
    print(f"kept_span {kept_fold_pdf['valid_start'].iloc[0]} -> {kept_fold_pdf['valid_end'].iloc[-1]}", flush=True)
    # ARCHIVED NUMBERS FOR THE KEPT QUARTERS, THEN THE REPLAY
    old_return_pdf = get_old_return_pdf(keep_id_set)
    old_selection_pdf = get_old_selection_pdf(keep_id_set)
    new_return_pdf = get_new_return_pdf(span_dict, kept_fold_pdf)
    # JOIN RETURNS
    compare_pdf = new_return_pdf.merge(old_return_pdf[["fold_id", "candidate", "old_total_return", "old_buy_hold_total_return"]],
                                       on=["fold_id", "candidate"], how="outer", indicator=True)
    missing_count = int((compare_pdf["_merge"] != "both").sum())
    both_pdf = compare_pdf[compare_pdf["_merge"] == "both"].copy()
    both_pdf["return_match"] = [get_match_bool(new_float, old_float) for new_float, old_float in zip(both_pdf["total_return"], both_pdf["old_total_return"])]
    both_pdf["buy_hold_match"] = [get_match_bool(new_float, old_float) for new_float, old_float in zip(both_pdf["buy_hold_total_return"], both_pdf["old_buy_hold_total_return"])]
    both_pdf["abs_diff"] = (both_pdf["total_return"] - both_pdf["old_total_return"]).abs()
    # SELECTION ON THE NEW SCORES
    new_selection_pdf = get_new_selection_pdf(new_return_pdf, kept_fold_pdf)
    selection_pdf = old_selection_pdf.merge(new_selection_pdf.rename(columns={"period_id": "fold_id", "candidate": "new_candidate"}),
                                            on="fold_id", how="left")
    selection_pdf["selection_match"] = selection_pdf["old_candidate"] == selection_pdf["new_candidate"]
    # COUNTS
    return_matched = int(both_pdf["return_match"].sum())
    return_total = int(len(both_pdf))
    buy_hold_matched = int(both_pdf["buy_hold_match"].sum())
    selection_matched = int(selection_pdf["selection_match"].sum())
    selection_total = int(len(selection_pdf))
    max_abs_diff = float(both_pdf["abs_diff"].max()) if return_total else float("nan")
    mismatch_pdf = both_pdf[~both_pdf["return_match"]][["fold_id", "candidate", "old_total_return", "total_return", "abs_diff", "buy_hold_match"]]
    selection_mismatch_pdf = selection_pdf[~selection_pdf["selection_match"]]
    # A CAUSE SENTENCE FOR THE SUMMARY
    if missing_count:
        cause_str = f"{missing_count} candidate rows did not join"
    elif return_matched == return_total and selection_matched == selection_total:
        cause_str = "every kept return and every kept prior-only selection matches"
    elif buy_hold_matched < return_total:
        cause_str = "buy-and-hold differs on a kept quarter, so the price path differs"
    elif return_matched < return_total:
        cause_str = "buy-and-hold matches and a candidate return does not, so the rule replay differs"
    else:
        cause_str = "returns match and a prior-only selection does not"
    summary_dict = {"development_end": str(development_end), "kept_quarters": int(len(kept_fold_pdf)),
                    "excluded_quarters": excluded_count, "kept_start": str(kept_fold_pdf["valid_start"].iloc[0]),
                    "kept_end": str(kept_fold_pdf["valid_end"].iloc[-1]), "returns_matched": return_matched,
                    "returns_total": return_total, "buy_hold_matched": buy_hold_matched, "buy_hold_total": return_total,
                    "selections_matched": selection_matched, "selections_total": selection_total,
                    "max_abs_return_diff": max_abs_diff, "missing_joins": missing_count, "cause": cause_str,
                    "return_mismatch_count": int(len(mismatch_pdf)), "selection_mismatch_count": int(len(selection_mismatch_pdf))}
    # WRITE THE SUMMARY UNDER THE V2 FOLDER. THIS SCRIPT CREATES THE FOLDER.
    from so.core.local_file_management import write_csv_file_to_path
    out_folder_str = paths.get_experiment_data_path_str(exp_config.EXPERIMENT_NAME, "old_bounds_calibration")
    write_csv_file_to_path(pd.DataFrame([summary_dict]), f"{out_folder_str}summary_data.csv", "W", alert_in=False)
    if len(mismatch_pdf):
        write_csv_file_to_path(mismatch_pdf, f"{out_folder_str}return_mismatch_data.csv", "W", alert_in=False)
    if len(selection_mismatch_pdf):
        write_csv_file_to_path(selection_mismatch_pdf, f"{out_folder_str}selection_mismatch_data.csv", "W", alert_in=False)
    print(json.dumps(summary_dict, sort_keys=True), flush=True)
    # ONE NOTE ROW. NOT A VALIDATION TRIAL.
    from so.core.trial_log import log_trial_dict
    log_trial_dict(exp_config, "note", {"diagnostic": "old_bounds", "kept_quarters": int(len(kept_fold_pdf))},
                   {"returns_matched": return_matched, "returns_total": return_total,
                    "selections_matched": selection_matched, "selections_total": selection_total,
                    "max_abs_return_diff": max_abs_diff, "buy_hold_matched": buy_hold_matched},
                   False, note_str_in="old-bounds calibration; diagnostic; informs no decision")
    print("logged one note row", flush=True)
    return summary_dict

# RUN WHEN CALLED AS A SCRIPT
if __name__ == "__main__":
    run_calibration_dict()
    sys.exit(0)
