import json
import os
import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION AND THE PATHS
from so import config, paths
# IMPORT THE WINDOW SESSIONS AND THE FIRST ENTRY BAR
from so.core.reentry_simulation import get_window_session_idx_arr
from so.core.backtest_simulation import get_session_first_entry_idx
from so.features.daily_features import get_session_decision_idx_dict
# IMPORT THE ENGINE, THE LOOP HELPERS, THE SELECTOR AND THE CHECKPOINT READERS
from so.runner.engine import TrailingStopEngine, get_decision_dict
from so.runner.loop import get_bar_range_event_dict, get_fill_event_dict
from so.runner.selection import get_runner_selection_pdf, get_governing_candidate_dict
from so.runner.checkpoint import (get_run_folder_str, read_pickle, read_decisions_list, read_score_row_list,
                                  read_checkpoint_dict)

"""
Port Calibration Helpers (infrastructure step 4c)

Shared by the scripts that compare a runner port with the saved v2 results of the same experiment
(scripts/compare_<exp>_calibration.py). Nothing here is called by a run, a design or the holdout evaluation. Nothing
here writes a trial row or reads the quarantine.

    get_first_diff_dict             first and largest difference of two aligned arrays (NaN-equal, NUMERIC_TOLERANCE)
    read_v2_saved_dict              the v2 development files (periods, scores, selection, prior-only equity, summary)
    read_run_dict                   one runner run (periods, bars, scores, recorded decisions, candidate designs)
    get_selector_component_dict     saved scores through the runner's selector, against a saved selection
    run_trailing_session_timing_dict  TrailingStopEngine driven with the OLD simulator's session timing (k and
                                      volatility of session s set before its morning). It reproduces
                                      simulate_stop_reentry_dict, so it isolates the engine from the runner's
                                      decision-time rule (a decision's parameters apply from its fill on).
    get_equity_compare_dict         two daily equity tables on their common dates
"""

# THE MATCH TOLERANCE OF EVERY CALIBRATION
TOLERANCE_FLOAT = float(config.NUMERIC_TOLERANCE)
# THE FOLDER A V2 DEVELOPMENT NOTEBOOK WROTE
V2_FOLDER_STR = "step01_development_data"


# FUNCTION: A DATE-LIKE VALUE TO datetime.date
def get_day(value_in):
    """
    Args:
        value_in: str, date, datetime or Timestamp

    Returns:
        datetime.date: Calendar day
    """
    # PANDAS PARSES EVERY FORM WE STORE
    return pd.Timestamp(value_in).date()


# FUNCTION: FIRST AND LARGEST DIFFERENCE OF TWO ALIGNED FLOAT ARRAYS
def get_first_diff_dict(left_arr_in, right_arr_in, label_list_in, name_str_in, tolerance_float_in=TOLERANCE_FLOAT):
    """
    NaN equals NaN. A difference above the tolerance, or NaN on one side only, counts.

    Args:
        left_arr_in, right_arr_in (array-like): Same length
        label_list_in (list): One label per position (a date, a period id)
        name_str_in (str): Name printed with the result
        tolerance_float_in (float): Largest difference that still matches

    Returns:
        dict: name, count, diff_count, max_abs_diff, first_label, left, right (first_label None when all match)
    """
    # SAME LENGTH OR A LENGTH DIFFERENCE
    left_arr = np.asarray(left_arr_in, dtype=float)
    right_arr = np.asarray(right_arr_in, dtype=float)
    if len(left_arr) != len(right_arr):
        return {"name": name_str_in, "count": int(min(len(left_arr), len(right_arr))), "diff_count": None,
                "max_abs_diff": None, "first_label": "length", "left": int(len(left_arr)), "right": int(len(right_arr))}
    # ONE-SIDED NaN, OR A FINITE GAP ABOVE THE TOLERANCE
    both_nan_arr = np.isnan(left_arr) & np.isnan(right_arr)
    one_nan_arr = np.isnan(left_arr) ^ np.isnan(right_arr)
    abs_arr = np.where(both_nan_arr | one_nan_arr, 0.0, np.abs(left_arr - right_arr))
    diff_arr = one_nan_arr | (abs_arr > float(tolerance_float_in))
    diff_idx_arr = np.flatnonzero(diff_arr)
    result_dict = {"name": name_str_in, "count": int(len(left_arr)), "diff_count": int(len(diff_idx_arr)),
                   "max_abs_diff": float(abs_arr.max()) if len(abs_arr) else 0.0, "first_label": None,
                   "left": None, "right": None}
    if len(diff_idx_arr):
        first_idx = int(diff_idx_arr[0])
        result_dict.update({"first_label": str(label_list_in[first_idx]), "left": float(left_arr[first_idx]),
                            "right": float(right_arr[first_idx])})
    return result_dict


# FUNCTION: ONE PRINT LINE FOR A DIFFERENCE DICT
def get_diff_line_str(diff_dict_in):
    """
    Args:
        diff_dict_in (dict): Output of get_first_diff_dict

    Returns:
        str: MATCH or DIFF line
    """
    # A LENGTH DIFFERENCE IS ITS OWN LINE
    if diff_dict_in["first_label"] == "length":
        return f"DIFF  {diff_dict_in['name']}: length {diff_dict_in['left']} vs {diff_dict_in['right']}"
    if diff_dict_in["first_label"] is None:
        return (f"MATCH {diff_dict_in['name']}: {diff_dict_in['count']} values, "
                f"max abs diff {diff_dict_in['max_abs_diff']:.3e}")
    return (f"DIFF  {diff_dict_in['name']}: {diff_dict_in['diff_count']} of {diff_dict_in['count']} differ, "
            f"max abs diff {diff_dict_in['max_abs_diff']:.3e}, first at {diff_dict_in['first_label']} "
            f"(runner {diff_dict_in['left']}, reference {diff_dict_in['right']})")


# FUNCTION: THE SAVED V2 DEVELOPMENT FILES
def read_v2_saved_dict(experiment_name_str_in, folder_name_str_in=V2_FOLDER_STR):
    """
    period_data.csv, score_data.csv, selection_data.csv, prior_only_daily_equity_data.csv and summary_data.csv of a
    v2 development notebook. Dates become datetime.date. A score table without fold_id gets it from period_id.

    Args:
        experiment_name_str_in (str): v2 EXPERIMENT_NAME (the data folder)
        folder_name_str_in (str): Step folder

    Returns:
        dict: period_pdf, score_pdf, selection_pdf, equity_pdf, summary_pdf, folder_str
    """
    # THE FILES THE NOTEBOOK WROTE
    folder_str = paths.get_experiment_data_path_str(experiment_name_str_in, folder_name_str_in)
    period_pdf = pd.read_csv(folder_str + "period_data.csv")
    score_pdf = pd.read_csv(folder_str + "score_data.csv")
    selection_pdf = pd.read_csv(folder_str + "selection_data.csv")
    equity_pdf = pd.read_csv(folder_str + "prior_only_daily_equity_data.csv")
    summary_path_str = folder_str + "summary_data.csv"
    summary_pdf = pd.read_csv(summary_path_str) if os.path.isfile(summary_path_str) else pd.DataFrame()
    # DATES AND IDS
    for column_str in ("period_start", "period_end", "valid_start", "valid_end"):
        if column_str in period_pdf.columns:
            period_pdf[column_str] = period_pdf[column_str].map(get_day)
    equity_pdf["date"] = equity_pdf["date"].map(get_day)
    if "fold_id" not in score_pdf.columns and "period_id" in score_pdf.columns:
        score_pdf["fold_id"] = score_pdf["period_id"]
    return {"period_pdf": period_pdf, "score_pdf": score_pdf, "selection_pdf": selection_pdf,
            "equity_pdf": equity_pdf, "summary_pdf": summary_pdf, "folder_str": folder_str}


# FUNCTION: A SELECTION TABLE AS period_id -> CANDIDATE IN FORCE
def get_governing_dict_from_selection_pdf(selection_pdf_in):
    """
    Args:
        selection_pdf_in (pd.DataFrame): period_id (or fold_id), candidate

    Returns:
        dict: period_id -> candidate
    """
    # THE SAVED ROW IS THE CANDIDATE IN FORCE
    id_col_str = "period_id" if "period_id" in selection_pdf_in.columns else "fold_id"
    return {int(row[id_col_str]): str(row["candidate"]) for _, row in selection_pdf_in.sort_values(id_col_str).iterrows()}


# FUNCTION: SAVED SCORES THROUGH THE RUNNER'S SELECTOR
def get_selector_component_dict(score_pdf_in, period_pdf_in, design_module_in, reference_governing_dict_in):
    """
    get_runner_selection_pdf then get_governing_candidate_dict on the given scores, compared period by period with a
    reference candidate-in-force table.

    Args:
        score_pdf_in (pd.DataFrame): fold_id, candidate, excess_return (and tie columns the runner attaches)
        period_pdf_in (pd.DataFrame): Periods
        design_module_in (module): Design (CANDIDATE_LIST, SELECTION_RULE, CANDIDATE_TIE_VALUE_DICT)
        reference_governing_dict_in (dict): period_id -> candidate

    Returns:
        dict: match_int, period_count_int, first_period_id, runner, reference, governing_dict
    """
    # THE SAME SELECTOR A RUN USES
    candidate_list = list(design_module_in.CANDIDATE_LIST)
    selection_pdf = get_runner_selection_pdf(score_pdf_in.copy(), design_module_in)
    governing_dict = get_governing_candidate_dict(selection_pdf, period_pdf_in, candidate_list)
    period_id_list = [int(period_id) for period_id in period_pdf_in.sort_values("period_id")["period_id"]]
    mismatch_list = [period_id for period_id in period_id_list
                     if governing_dict.get(period_id) != reference_governing_dict_in.get(period_id)]
    first_id = mismatch_list[0] if mismatch_list else None
    return {"match_int": len(period_id_list) - len(mismatch_list), "period_count_int": len(period_id_list),
            "first_period_id": first_id,
            "runner": None if first_id is None else governing_dict.get(first_id),
            "reference": None if first_id is None else reference_governing_dict_in.get(first_id),
            "governing_dict": governing_dict}


# FUNCTION: ONE RUNNER RUN FROM ITS FOLDER
def read_run_dict(run_id_str_in, design_module_in, design_file_path_str_in=None):
    """
    Periods, the bar arrays the run used, every candidate-period score, every candidate's recorded decisions, and
    (when the class can be loaded) the candidate design objects of the last checkpoint.

    Args:
        run_id_str_in (str): Run id under store04_experiments/runs/
        design_module_in (module): Design (CANDIDATE_LIST)
        design_file_path_str_in (str | None): design.py of the run (needed to unpickle the checkpointed designs)

    Returns:
        dict: run_folder_str, period_pdf, ohlcv_array_dict, score_pdf, decision_dict, session_date_list, date1,
              date2, design_dict, report_dict
    """
    # IMPORT THE TOKEN AND THE DESIGN LOADER HERE (RUN-LEVEL HELPERS)
    from so.runner.run import get_candidate_token_str, get_file_design_module
    # THE SHARED PAYLOAD
    run_folder_str = get_run_folder_str(run_id_str_in)
    period_pdf = read_pickle(os.path.join(run_folder_str, "period.pkl")).copy()
    for column_str in ("period_start", "period_end", "valid_start", "valid_end"):
        if column_str in period_pdf.columns:
            period_pdf[column_str] = period_pdf[column_str].map(get_day)
    ohlcv_array_dict = read_pickle(os.path.join(run_folder_str, "ohlcv.pkl"))
    period_pdf = period_pdf.sort_values("period_id").reset_index(drop=True)
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    window_idx_arr = get_window_session_idx_arr(ohlcv_array_dict, date1, date2)
    session_date_list = [get_day(ohlcv_array_dict["session_date_list"][int(idx)]) for idx in window_idx_arr]
    # THE DESIGN CLASS MUST BE IMPORTABLE UNDER THE RUN'S MODULE NAME BEFORE A CHECKPOINT IS READ
    design_loaded_bool = False
    if design_file_path_str_in:
        try:
            get_file_design_module(os.path.abspath(design_file_path_str_in))
            design_loaded_bool = True
        except Exception as error:
            print(f"note: design module not loaded for the checkpoints ({error})")
    # SCORES, DECISIONS AND DESIGNS PER CANDIDATE
    score_row_list, decision_dict, design_dict = [], {}, {}
    for candidate in design_module_in.CANDIDATE_LIST:
        token_str = get_candidate_token_str(candidate)
        score_row_list.extend(read_score_row_list(run_id_str_in, token_str) or [])
        decision_dict[candidate] = read_decisions_list(run_id_str_in, token_str) or []
        if design_loaded_bool:
            try:
                checkpoint_dict = read_checkpoint_dict(run_id_str_in, token_str)
                design_dict[candidate] = None if checkpoint_dict is None else checkpoint_dict.get("design")
            except Exception as error:
                print(f"note: checkpoint of {candidate} not readable ({error})")
                design_dict[candidate] = None
    score_pdf = pd.DataFrame(score_row_list)
    if len(score_pdf) and "fold_id" not in score_pdf.columns and "period_id" in score_pdf.columns:
        score_pdf["fold_id"] = score_pdf["period_id"]
    report_path_str = os.path.join(run_folder_str, "report.json")
    report_dict = None
    if os.path.isfile(report_path_str):
        with open(report_path_str, encoding="utf-8") as file_obj:
            report_dict = json.load(file_obj)
    return {"run_folder_str": run_folder_str, "period_pdf": period_pdf, "ohlcv_array_dict": ohlcv_array_dict,
            "score_pdf": score_pdf, "decision_dict": decision_dict, "session_date_list": session_date_list,
            "date1": date1, "date2": date2, "design_dict": design_dict, "report_dict": report_dict}


# FUNCTION: TrailingStopEngine WITH THE OLD SIMULATOR'S SESSION TIMING
def run_trailing_session_timing_dict(ohlcv_array_dict_in, date1_in, date2_in, volatility_arr_in, stop_k_in,
                                     reentry_func_in, reentry_reason_str_in="model", exit_signal_arr_in=None,
                                     max_cash_sessions_in=None):
    """
    Sets session s's k and volatility before its morning bars (the old simulator's rule), then asks the old-style
    re-entry rule from the engine snapshot. Same arguments as so.core.reentry_simulation.simulate_stop_reentry_dict.
    Used by the engine tests and by the port calibrations; a run never uses this timing.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Window
        volatility_arr_in (np.ndarray): Volatility per session position
        stop_k_in (float | np.ndarray | None): k (scalar or one per session position)
        reentry_func_in: f(session_idx, cash_session_count, episode_dict) -> bool
        reentry_reason_str_in (str): Label of the rule's re-entries
        exit_signal_arr_in (np.ndarray | None): Flatten flag per session position
        max_cash_sessions_in (int | None): Forced re-entry

    Returns:
        dict: Engine result (trade_pdf, episode_pdf, daily_equity_pdf, metric_dict)
    """
    # THE SAME WINDOW AS THE OLD SIMULATOR
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    engine = TrailingStopEngine(max_cash_sessions_in)
    engine.set_session_bounds(ohlcv_array_dict_in["session_end_idx_arr"], len(ohlcv_array_dict_in["close_arr"]))
    first_session_idx = int(window_session_idx_arr[0])
    first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, first_session_idx)
    timestamp_index = ohlcv_array_dict_in["timestamp_index"]
    engine.open_window({"bar_idx": int(first_entry_idx), "timestamp": timestamp_index[first_entry_idx],
                        "raw_price": float(ohlcv_array_dict_in["open_arr"][first_entry_idx]),
                        "close": float(ohlcv_array_dict_in["close_arr"][first_entry_idx]),
                        "session_idx": first_session_idx,
                        "session_date": ohlcv_array_dict_in["session_date_list"][first_session_idx]}, 1.0)
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    # ONE SESSION AT A TIME
    for session_pos, session_idx in enumerate(window_session_idx_arr):
        session_idx = int(session_idx)
        start_idx = int(ohlcv_array_dict_in["session_start_idx_arr"][session_idx])
        decision_idx = int(idx_dict["decision_idx_arr"][session_idx])
        fill_idx = int(idx_dict["fill_idx_arr"][session_idx])
        end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx])
        session_date = ohlcv_array_dict_in["session_date_list"][session_idx]
        is_last_session = session_pos == len(window_session_idx_arr) - 1
        session_k = stop_k_in if stop_k_in is None or np.ndim(stop_k_in) == 0 else stop_k_in[session_idx]
        # THE OLD RULE: THIS SESSION'S PARAMETERS ALSO COVER ITS MORNING
        engine.set_stop_params(session_k, volatility_arr_in[session_idx])
        morning_event_dict = get_bar_range_event_dict(ohlcv_array_dict_in, start_idx, decision_idx, session_date)
        if morning_event_dict is not None:
            engine.process_bars(morning_event_dict)
        flatten_bool = False if exit_signal_arr_in is None else bool(exit_signal_arr_in[session_idx])
        target_weight, exit_block_sessions, require_fresh_exit = 0.0, 0, False
        state_dict = engine.get_state_dict()
        if (not state_dict["in_position"]) and engine.episode_dict is not None and reentry_func_in is not None:
            if bool(reentry_func_in(int(session_idx), int(state_dict["cash_session_count"]), engine.episode_dict)):
                target_weight = 1.0
                exit_block_sessions = int(engine.episode_dict.get("exit_block_sessions", 0))
                require_fresh_exit = bool(engine.episode_dict.get("require_fresh_exit", False))
        decision_dict = get_decision_dict({"target_weight": target_weight, "flatten_bool": flatten_bool,
                                           "trail_multiple": session_k, "volatility": volatility_arr_in[session_idx],
                                           "exit_block_sessions": exit_block_sessions,
                                           "require_fresh_exit": require_fresh_exit,
                                           "reentry_reason": reentry_reason_str_in})
        if not is_last_session:
            engine.apply_decision(get_fill_event_dict(ohlcv_array_dict_in, fill_idx, decision_idx, session_idx,
                                                      session_date, end_idx),
                                  decision_dict, float(ohlcv_array_dict_in["close_arr"][decision_idx]))
        afternoon_event_dict = get_bar_range_event_dict(ohlcv_array_dict_in, decision_idx + 1, end_idx, session_date)
        if afternoon_event_dict is not None:
            engine.process_bars(afternoon_event_dict)
        if is_last_session:
            engine.close_window({"bar_idx": end_idx, "timestamp": timestamp_index[end_idx],
                                 "raw_price": float(ohlcv_array_dict_in["close_arr"][end_idx]),
                                 "close": float(ohlcv_array_dict_in["close_arr"][end_idx]),
                                 "session_idx": session_idx, "session_date": session_date})
        engine.close_session({"session_date": session_date, "close": float(ohlcv_array_dict_in["close_arr"][end_idx])})
    return engine.get_result_dict()


# FUNCTION: TWO DAILY EQUITY TABLES ON THEIR COMMON DATES
def get_equity_compare_dict(left_equity_pdf_in, right_equity_pdf_in, name_str_in):
    """
    Merges on date. Reports both lengths, the common count, the level difference and both total returns over the
    common dates (equity / first equity of the common span - 1 is not used: each side's own initial capital is).

    Args:
        left_equity_pdf_in, right_equity_pdf_in (pd.DataFrame): date, equity
        name_str_in (str): Name

    Returns:
        dict: left_count, right_count, common_count, diff (get_first_diff_dict), left_total_return, right_total_return
    """
    # COMMON DATES ONLY
    left_pdf = left_equity_pdf_in[["date", "equity"]].copy()
    right_pdf = right_equity_pdf_in[["date", "equity"]].copy()
    left_pdf["date"] = left_pdf["date"].map(get_day)
    right_pdf["date"] = right_pdf["date"].map(get_day)
    merged_pdf = left_pdf.merge(right_pdf, on="date", suffixes=("_left", "_right"))
    diff_dict = get_first_diff_dict(merged_pdf["equity_left"].to_numpy(dtype=float),
                                    merged_pdf["equity_right"].to_numpy(dtype=float), list(merged_pdf["date"]),
                                    name_str_in)
    return {"left_count": int(len(left_pdf)), "right_count": int(len(right_pdf)), "common_count": int(len(merged_pdf)),
            "diff": diff_dict,
            "left_total_return": float(left_pdf["equity"].iloc[-1] / config.INITIAL_CAPITAL - 1.0) if len(left_pdf) else None,
            "right_total_return": float(right_pdf["equity"].iloc[-1] / config.INITIAL_CAPITAL - 1.0) if len(right_pdf) else None}


# FUNCTION: WRITE A CALIBRATION RESULT AS JSON
def write_calibration_json(file_path_str_in, result_dict_in):
    """
    Dates, numpy numbers and anything else unusual become strings or plain numbers.

    Args:
        file_path_str_in (str): Output path
        result_dict_in (dict): Result

    Returns:
        None
    """
    # FOLDER, THEN THE FILE
    os.makedirs(os.path.dirname(os.path.abspath(file_path_str_in)), exist_ok=True)

    # FUNCTION: ONE VALUE JSON CANNOT WRITE BY ITSELF
    def get_plain_value(value_in):
        if isinstance(value_in, (np.integer,)):
            return int(value_in)
        if isinstance(value_in, (np.floating,)):
            return None if not np.isfinite(value_in) else float(value_in)
        return str(value_in)

    with open(file_path_str_in, "w", encoding="utf-8") as file_obj:
        json.dump(result_dict_in, file_obj, indent=1, default=get_plain_value)
