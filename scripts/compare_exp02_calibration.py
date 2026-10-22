import argparse
import os
import sys
import time
from pathlib import Path
import numpy as np
import pandas as pd

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE SHARED CONFIGURATION, THE OLD SIMULATOR AND THE OLD PERIOD SCORE
from so import config
from so.core.reentry_simulation import simulate_stop_reentry_dict, get_window_session_idx_arr
from so.core.holdout import get_equity_total_return_float
from so.features.daily_features import get_daily_feature_pdf
# IMPORT THE RUNNER PIECES AND THE CALIBRATION HELPERS
from so.runner.run import get_candidate_engine
from so.runner.selection import get_session_candidate_dict, run_prior_only_from_decisions_dict
from so.runner.calibration import (get_day, get_first_diff_dict, get_diff_line_str, read_v2_saved_dict, read_run_dict,
                                   get_governing_dict_from_selection_pdf, get_selector_component_dict,
                                   run_trailing_session_timing_dict, get_equity_compare_dict, write_calibration_json)
# IMPORT THE PORT AND THE 2.0 REFERENCE PATH
from experiments.exp02_stop_reentry import config as exp_config
from experiments.exp02_stop_reentry import design as exp02_design
from experiments.exp02_stop_reentry import v2_reference

"""
exp02 v2.1 runner calibration against the saved v2 development files (infrastructure step 4c-b)

Usage (workspace root, after scripts/run_development.py experiments/exp02_stop_reentry):

    python scripts/compare_exp02_calibration.py <run_id>

Reads the run folder and store04_experiments/exp02_stop_reentry_v2/step01_development_data/. Writes
logs/exp02_calibration.json and prints one summary block. Writes no trial row and does not read the holdout.

Components (a match is within so.config.NUMERIC_TOLERANCE unless stated):
    a0  TSDAY (the file the port reads) equals get_daily_feature_pdf on the run's bars (what v2 computed in memory)
    a1  the port's recorded decisions equal the 2.0 model path on every run session: re-entry flag (exact), k (exact),
        volatility; probability, threshold and refits too when the checkpointed designs can be read
    a2  the port's decisions through the OLD simulator, one fresh window per v2 period, reproduce v2's saved
        candidate-period scores (738)
    b   v2's saved scores through the runner's selector give v2's selection (41 periods)
    c1  v2's selection + the port's decisions through TrailingStopEngine with the OLD session timing reproduce v2's
        saved prior-only equity (the engine on real data)
    c2  the same through the runner's prior-only replay (decision-time stop parameters): every difference from v2 is
        the stop-timing rule; the first differing trades are listed
    d   the run itself against v2: periods, period scores (continuous slices vs fresh windows), selection, path, verdict
"""

# THE SAVED V2 FOLDER AND THE OUTPUT FILE
V2_NAME_STR = "exp02_stop_reentry_v2"
OUTPUT_PATH_STR = os.path.join("logs", "exp02_calibration.json")
DESIGN_PATH_STR = os.path.join("experiments", "exp02_stop_reentry", "design.py")


# FUNCTION: A FULL-LENGTH ARRAY FROM PER-SESSION VALUES OF THE RUN
def get_full_arr(session_date_list_in, value_list_in, session_pos_dict_in, length_int_in, fill_value_in=np.nan):
    """
    Args:
        session_date_list_in (list): Run sessions
        value_list_in (list): One value per run session
        session_pos_dict_in (dict): date -> position in the bars
        length_int_in (int): Number of sessions in the bars
        fill_value_in: Value outside the run sessions

    Returns:
        np.ndarray: One value per bar session
    """
    # EVERY OTHER SESSION KEEPS THE FILL VALUE
    full_arr = np.full(length_int_in, fill_value_in, dtype=float)
    for session_date, value in zip(session_date_list_in, value_list_in):
        full_arr[session_pos_dict_in[session_date]] = np.nan if value is None else float(value)
    return full_arr


# FUNCTION: THE FIRST DIFFERING TRADES OF TWO TRADE TABLES
def get_trade_diff_list(left_trade_pdf_in, right_trade_pdf_in, timestamp_index_in, max_count_int_in=5):
    """
    Trades are compared by buy bar, sell bar and exit reason.

    Args:
        left_trade_pdf_in, right_trade_pdf_in (pd.DataFrame): buy_idx, sell_idx, exit_reason, share_count
        timestamp_index_in: Bar timestamps
        max_count_int_in (int): Rows to keep

    Returns:
        list[dict]: position, left and right buy / sell / reason
    """
    # SIDE BY SIDE, IN ORDER
    def get_row_list(trade_pdf_in):
        if trade_pdf_in is None or len(trade_pdf_in) == 0:
            return []
        return [(int(row.buy_idx), int(row.sell_idx), str(row.exit_reason)) for row in trade_pdf_in.itertuples(index=False)]

    def get_text(row_in):
        if row_in is None:
            return None
        return f"buy {timestamp_index_in[row_in[0]]} sell {timestamp_index_in[row_in[1]]} {row_in[2]}"

    left_list, right_list = get_row_list(left_trade_pdf_in), get_row_list(right_trade_pdf_in)
    diff_list = []
    for pos in range(max(len(left_list), len(right_list))):
        left_row = left_list[pos] if pos < len(left_list) else None
        right_row = right_list[pos] if pos < len(right_list) else None
        if left_row != right_row:
            diff_list.append({"position": pos, "runner": get_text(left_row), "reference": get_text(right_row)})
            if len(diff_list) >= int(max_count_int_in):
                break
    return diff_list


# RUN THE COMPARISON
if __name__ == "__main__":
    # ARGUMENTS
    parser = argparse.ArgumentParser(description="Compare the exp02 v2.1 runner run with the saved v2 results.")
    parser.add_argument("run_id", help="store04_experiments/runs/<run_id>")
    arg_dict = parser.parse_args()
    start_time = time.perf_counter()
    result_dict = {"run_id": arg_dict.run_id}
    line_list = []
    candidate_list = list(exp02_design.CANDIDATE_LIST)
    max_cash_int = int(exp_config.MAX_CASH_SESSIONS)
    # THE SAVED V2 FILES AND THE RUN
    v2_dict = read_v2_saved_dict(V2_NAME_STR)
    run_dict = read_run_dict(arg_dict.run_id, exp02_design, os.path.abspath(DESIGN_PATH_STR))
    ohlcv_array_dict = run_dict["ohlcv_array_dict"]
    bar_session_list = [get_day(day) for day in ohlcv_array_dict["session_date_list"]]
    session_pos_dict = {day: pos for pos, day in enumerate(bar_session_list)}
    session_count_int = len(bar_session_list)
    run_session_list = run_dict["session_date_list"]
    decision_session_list = run_session_list[:-1]
    v2_period_pdf = v2_dict["period_pdf"].sort_values("period_id").reset_index(drop=True)
    v2_governing_dict = get_governing_dict_from_selection_pdf(v2_dict["selection_pdf"])
    line_list.append(f"run {arg_dict.run_id}: {len(run_session_list)} sessions {run_session_list[0]} -> {run_session_list[-1]}, "
                     f"{len(run_dict['period_pdf'])} periods; v2: {len(v2_period_pdf)} periods "
                     f"{v2_period_pdf['period_start'].iloc[0]} -> {v2_period_pdf['period_end'].iloc[-1]}")
    # (a0) THE TSDAY FILE AGAINST THE IN-MEMORY TABLE OF THE SAME BARS
    daily_pdf = get_daily_feature_pdf(ohlcv_array_dict)
    try:
        from so.core.point_in_time import load_source_frame_dict
        tsday_pdf = load_source_frame_dict(["TSDAY"], bar_session_list[-1])["TSDAY"].copy()
        tsday_pdf["day"] = tsday_pdf["date"].map(get_day)
        memory_pdf = daily_pdf.copy()
        memory_pdf["day"] = memory_pdf["date"].map(get_day)
        merged_pdf = memory_pdf.merge(tsday_pdf, on="day", suffixes=("_memory", "_file"))
        worst_dict = {"column": None, "max_abs_diff": 0.0}
        for column_str in exp02_design.FEATURE_COL_LIST:
            memory_arr = pd.to_numeric(merged_pdf[f"{column_str}_memory"], errors="coerce").to_numpy(dtype=float)
            file_arr = pd.to_numeric(merged_pdf[f"{column_str}_file"], errors="coerce").to_numpy(dtype=float)
            diff_dict = get_first_diff_dict(file_arr, memory_arr, list(merged_pdf["day"]), column_str, 1e-9)
            if diff_dict["first_label"] is not None or (diff_dict["max_abs_diff"] or 0.0) > worst_dict["max_abs_diff"]:
                worst_dict = {"column": column_str, **diff_dict}
                if diff_dict["first_label"] is not None:
                    break
        result_dict["a0"] = {"memory_rows": len(memory_pdf), "file_rows": len(tsday_pdf), "common_rows": len(merged_pdf), "worst": worst_dict}
        status_str = "MATCH" if worst_dict.get("first_label") is None else "DIFF "
        line_list.append(f"{status_str} a0 TSDAY file vs in-memory features: {len(merged_pdf)} common rows "
                         f"(memory {len(memory_pdf)}, file {len(tsday_pdf)}); worst {worst_dict}")
    except Exception as error:
        result_dict["a0"] = {"error": str(error)}
        line_list.append(f"SKIP  a0 TSDAY file not compared: {error}")
    # (a1) THE 2.0 MODEL PATH ON THE SAME BARS
    row_pdf = v2_reference.get_labelled_row_pdf(ohlcv_array_dict)
    retrain_dict = {window_str: v2_reference.get_window_retrain_dict(ohlcv_array_dict, window_str, row_pdf)
                    for window_str in exp_config.TRAIN_WINDOW_CANDIDATE_LIST}
    v2_volatility_arr = row_pdf["daily_volatility"].to_numpy(dtype=float)
    decision_pos_list = [session_pos_dict[day] for day in decision_session_list]
    runner_bool_full_dict, a1_dict = {}, {}
    flag_total_int, flag_diff_int, k_diff_int = 0, 0, 0
    volatility_worst, proba_worst, threshold_worst, refit_diff_int = 0.0, 0.0, 0.0, 0
    first_flag_diff = None
    for candidate_str in candidate_list:
        candidate_dict = exp02_design.parse_candidate_dict(candidate_str)
        aligned_dict = v2_reference.get_aligned_prediction_dict(ohlcv_array_dict, retrain_dict[candidate_dict["train_window"]],
                                                                candidate_dict["threshold_offset"])
        v2_bool_arr = v2_reference.get_reentry_bool_arr(aligned_dict["proba_arr"], aligned_dict["threshold_arr"])
        decision_list = run_dict["decision_dict"][candidate_str][:-1]
        runner_bool_arr = np.asarray([float(row.get("target_weight", np.nan)) == 1.0 for row in decision_list], dtype=bool)
        runner_k_arr = np.asarray([np.nan if row.get("trail_multiple") is None else float(row["trail_multiple"]) for row in decision_list], dtype=float)
        runner_vol_arr = np.asarray([np.nan if row.get("volatility") is None else float(row["volatility"]) for row in decision_list], dtype=float)
        runner_bool_full_dict[candidate_str] = get_full_arr(decision_session_list, runner_bool_arr.astype(float).tolist(),
                                                            session_pos_dict, session_count_int, 0.0) == 1.0
        flag_mismatch_arr = runner_bool_arr != v2_bool_arr[decision_pos_list]
        flag_total_int += int(len(runner_bool_arr))
        flag_diff_int += int(flag_mismatch_arr.sum())
        if flag_mismatch_arr.any() and first_flag_diff is None:
            first_flag_diff = {"candidate": candidate_str, "session": str(decision_session_list[int(np.flatnonzero(flag_mismatch_arr)[0])])}
        k_diff_int += int((runner_k_arr != float(candidate_dict["stop_k"])).sum())
        volatility_diff = get_first_diff_dict(runner_vol_arr, v2_volatility_arr[decision_pos_list], decision_session_list, "volatility")
        volatility_worst = max(volatility_worst, float(volatility_diff["max_abs_diff"] or 0.0))
        candidate_result = {"flag_diff": int(flag_mismatch_arr.sum()), "volatility": volatility_diff,
                            "runner_reentry_signals": int(runner_bool_arr.sum()), "v2_reentry_signals": int(v2_bool_arr[decision_pos_list].sum())}
        # PROBABILITY, THRESHOLD AND REFITS FROM THE CHECKPOINTED DESIGN, WHEN READABLE
        candidate_design = run_dict["design_dict"].get(candidate_str)
        if candidate_design is not None and hasattr(candidate_design, "decision_log_list"):
            log_pdf = pd.DataFrame(candidate_design.decision_log_list)
            log_pos_list = [session_pos_dict[get_day(day)] for day in log_pdf["session"]]
            proba_diff = get_first_diff_dict(log_pdf["proba"], aligned_dict["proba_arr"][log_pos_list], list(log_pdf["session"]), "proba")
            threshold_diff = get_first_diff_dict(log_pdf["threshold"], aligned_dict["threshold_arr"][log_pos_list], list(log_pdf["session"]), "threshold")
            proba_worst = max(proba_worst, float(proba_diff["max_abs_diff"] or 0.0))
            threshold_worst = max(threshold_worst, float(threshold_diff["max_abs_diff"] or 0.0))
            refit_pdf = pd.DataFrame(candidate_design.refit_log_list)
            v2_refit_pdf = retrain_dict[candidate_dict["train_window"]]["refit_log_pdf"].copy()
            v2_refit_pdf["day"] = v2_refit_pdf["retrain_session"].map(get_day)
            refit_pdf["day"] = refit_pdf["retrain_session"].map(get_day)
            merged_refit_pdf = refit_pdf.merge(v2_refit_pdf, on="day", how="outer", suffixes=("_runner", "_v2"), indicator=True)
            merged_refit_pdf = merged_refit_pdf[merged_refit_pdf["day"] >= refit_pdf["day"].min()]
            merged_refit_pdf = merged_refit_pdf[merged_refit_pdf["day"] <= refit_pdf["day"].max()]
            refit_bad_pdf = merged_refit_pdf[(merged_refit_pdf["_merge"] != "both")
                                             | (merged_refit_pdf["rows_used_runner"] != merged_refit_pdf["rows_used_v2"])
                                             | ((merged_refit_pdf["label_balance_runner"] - merged_refit_pdf["label_balance_v2"]).abs() > 1e-12)]
            refit_diff_int += int(len(refit_bad_pdf))
            candidate_result.update({"proba": proba_diff, "threshold": threshold_diff, "refit_count": int(len(refit_pdf)),
                                     "refit_diff_count": int(len(refit_bad_pdf)),
                                     "first_refit_diff": None if refit_bad_pdf.empty else str(refit_bad_pdf["day"].iloc[0])})
        a1_dict[candidate_str] = candidate_result
    result_dict["a1"] = {"candidate_dict": a1_dict, "flag_total": flag_total_int, "flag_diff": flag_diff_int,
                         "first_flag_diff": first_flag_diff, "k_diff": k_diff_int, "volatility_max_abs_diff": volatility_worst,
                         "proba_max_abs_diff": proba_worst, "threshold_max_abs_diff": threshold_worst, "refit_diff": refit_diff_int,
                         "designs_read": int(sum(1 for value in run_dict["design_dict"].values() if value is not None))}
    status_str = "MATCH" if flag_diff_int == 0 and k_diff_int == 0 and volatility_worst <= config.NUMERIC_TOLERANCE else "DIFF "
    line_list.append(f"{status_str} a1 decisions vs 2.0 model path: re-entry flags {flag_total_int - flag_diff_int}/{flag_total_int} "
                     f"(first diff {first_flag_diff}), k diffs {k_diff_int}, volatility max {volatility_worst:.3e}; "
                     f"designs read {result_dict['a1']['designs_read']}/18, proba max {proba_worst:.3e}, threshold max "
                     f"{threshold_worst:.3e}, refit diffs {refit_diff_int}")
    # (a2) THE PORT'S DECISIONS THROUGH THE OLD SIMULATOR, ONE FRESH WINDOW PER V2 PERIOD
    v2_score_pdf = v2_dict["score_pdf"].copy()
    v2_score_lookup = {(int(row.fold_id), str(row.candidate)): float(row.total_return) for row in v2_score_pdf.itertuples(index=False)}
    a2_left_list, a2_right_list, a2_label_list = [], [], []
    for candidate_str in candidate_list:
        candidate_dict = exp02_design.parse_candidate_dict(candidate_str)
        bool_full_arr = runner_bool_full_dict[candidate_str]
        reentry_func = (lambda bool_arr_in: (lambda session_idx, cash_count, episode_dict: bool(bool_arr_in[session_idx])))(bool_full_arr)
        for period_row in v2_period_pdf.itertuples(index=False):
            simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict, period_row.period_start, period_row.period_end,
                                                         v2_volatility_arr, float(candidate_dict["stop_k"]), reentry_func, "model",
                                                         max_cash_sessions_in=max_cash_int)
            a2_left_list.append(get_equity_total_return_float(simulation_dict["daily_equity_pdf"]))
            a2_right_list.append(v2_score_lookup.get((int(period_row.period_id), candidate_str), np.nan))
            a2_label_list.append(f"{candidate_str}@{int(period_row.period_id)}")
    a2_diff = get_first_diff_dict(a2_left_list, a2_right_list, a2_label_list, "a2 fresh-window scores (port decisions, old simulator) vs v2 score_data")
    result_dict["a2"] = a2_diff
    line_list.append(get_diff_line_str(a2_diff))
    # (b) V2'S SAVED SCORES THROUGH THE RUNNER'S SELECTOR
    b_dict = get_selector_component_dict(v2_score_pdf, v2_period_pdf, exp02_design, v2_governing_dict)
    result_dict["b"] = {key: value for key, value in b_dict.items() if key != "governing_dict"}
    status_str = "MATCH" if b_dict["match_int"] == b_dict["period_count_int"] else "DIFF "
    line_list.append(f"{status_str} b  v2 scores -> runner selector: {b_dict['match_int']}/{b_dict['period_count_int']} periods "
                     f"(first diff {b_dict['first_period_id']}: runner {b_dict['runner']}, v2 {b_dict['reference']})")
    # (c1) V2'S SELECTION, THE PORT'S DECISIONS, TrailingStopEngine WITH THE OLD SESSION TIMING
    v2_date1, v2_date2 = v2_period_pdf["period_start"].iloc[0], v2_period_pdf["period_end"].iloc[-1]
    v2_window_list = [bar_session_list[int(idx)] for idx in get_window_session_idx_arr(ohlcv_array_dict, v2_date1, v2_date2)]
    v2_session_candidate_dict = get_session_candidate_dict(v2_window_list, v2_period_pdf, v2_governing_dict)
    k_full_arr = np.full(session_count_int, np.nan)
    governing_bool_full_arr = np.zeros(session_count_int, dtype=bool)
    for session_date in v2_window_list:
        candidate_str = v2_session_candidate_dict.get(session_date)
        if candidate_str is None:
            continue
        pos = session_pos_dict[session_date]
        k_full_arr[pos] = float(exp02_design.parse_candidate_dict(candidate_str)["stop_k"])
        governing_bool_full_arr[pos] = bool(runner_bool_full_dict[candidate_str][pos])
    c1_result = run_trailing_session_timing_dict(ohlcv_array_dict, v2_date1, v2_date2, v2_volatility_arr, k_full_arr,
                                                 lambda session_idx, cash_count, episode_dict: bool(governing_bool_full_arr[session_idx]),
                                                 "model", None, max_cash_int)
    c1_dict = get_equity_compare_dict(c1_result["daily_equity_pdf"], v2_dict["equity_pdf"], "c1 engine (old timing) on v2 selection vs v2 prior-only equity")
    result_dict["c1"] = c1_dict
    line_list.append(get_diff_line_str(c1_dict["diff"]) + f" [rows runner {c1_dict['left_count']}, v2 {c1_dict['right_count']}, "
                     f"common {c1_dict['common_count']}; total {c1_dict['left_total_return']:.6f} vs {c1_dict['right_total_return']:.6f}]")
    # (c2) THE SAME SELECTION THROUGH THE RUNNER'S PRIOR-ONLY REPLAY (DECISION-TIME STOP PARAMETERS)
    if v2_window_list == run_session_list:
        c2_result = run_prior_only_from_decisions_dict(ohlcv_array_dict, v2_date1, v2_date2, run_session_list,
                                                       run_dict["decision_dict"], v2_governing_dict, v2_period_pdf,
                                                       initial_weight_in=float(exp02_design.INITIAL_WEIGHT),
                                                       engine_in=get_candidate_engine(exp02_design),
                                                       design_module_in=exp02_design)
        c2_dict = get_equity_compare_dict(c2_result["daily_equity_pdf"], v2_dict["equity_pdf"], "c2 runner replay on v2 selection vs v2 prior-only equity")
        trade_diff_list = get_trade_diff_list(c2_result["trade_pdf"], c1_result["trade_pdf"], ohlcv_array_dict["timestamp_index"])
        c2_dict.update({"runner_trade_count": int(len(c2_result["trade_pdf"])), "old_timing_trade_count": int(len(c1_result["trade_pdf"])),
                        "first_trade_diff_list": trade_diff_list})
        result_dict["c2"] = c2_dict
        line_list.append(get_diff_line_str(c2_dict["diff"]) + f" [total {c2_dict['left_total_return']:.6f} vs {c2_dict['right_total_return']:.6f}; "
                         f"trades {c2_dict['runner_trade_count']} vs {c2_dict['old_timing_trade_count']} (old timing)]")
        for trade_diff in trade_diff_list:
            line_list.append(f"      trade #{trade_diff['position']}: runner {trade_diff['runner']} | old timing {trade_diff['reference']}")
    else:
        result_dict["c2"] = {"error": "run sessions differ from the v2 span"}
        line_list.append(f"SKIP  c2: run span {run_session_list[0]} -> {run_session_list[-1]} differs from v2 {v2_date1} -> {v2_date2}")
    # (d) THE RUN ITSELF AGAINST V2
    run_period_pdf = run_dict["period_pdf"]
    period_bound_match_int = 0
    for run_row, v2_row in zip(run_period_pdf.itertuples(index=False), v2_period_pdf.itertuples(index=False)):
        period_bound_match_int += int(run_row.period_start == v2_row.period_start and run_row.period_end == v2_row.period_end)
    run_score_pdf = run_dict["score_pdf"]
    run_score_lookup = {(int(row.fold_id), str(row.candidate)): float(row.total_return) for row in run_score_pdf.itertuples(index=False)}
    score_key_list = sorted(set(run_score_lookup) & set(v2_score_lookup))
    score_diff = get_first_diff_dict([run_score_lookup[key] for key in score_key_list], [v2_score_lookup[key] for key in score_key_list],
                                     [f"{key[1]}@{key[0]}" for key in score_key_list], "d  run period scores (continuous slices) vs v2 (fresh windows)")
    run_selector_dict = get_selector_component_dict(run_score_pdf, run_period_pdf, exp02_design, v2_governing_dict)
    run_governing_dict = run_selector_dict["governing_dict"]
    path_result = run_prior_only_from_decisions_dict(ohlcv_array_dict, run_dict["date1"], run_dict["date2"], run_session_list,
                                                     run_dict["decision_dict"], run_governing_dict, run_period_pdf,
                                                     initial_weight_in=float(exp02_design.INITIAL_WEIGHT),
                                                     engine_in=get_candidate_engine(exp02_design), design_module_in=exp02_design)
    path_dict = get_equity_compare_dict(path_result["daily_equity_pdf"], v2_dict["equity_pdf"], "d  run prior-only equity vs v2 prior-only equity")
    report_dict = run_dict["report_dict"] or {}
    result_dict["d"] = {"period_bound_match": period_bound_match_int, "run_period_count": int(len(run_period_pdf)),
                        "score": score_diff, "selection_match": run_selector_dict["match_int"],
                        "selection_first_diff": run_selector_dict["first_period_id"],
                        "selection_first_runner": run_selector_dict["runner"], "selection_first_v2": run_selector_dict["reference"],
                        "path": path_dict, "report_keys": sorted(report_dict.keys())}
    line_list.append(f"{'MATCH' if period_bound_match_int == len(v2_period_pdf) == len(run_period_pdf) else 'DIFF '} d  period bounds "
                     f"{period_bound_match_int}/{len(v2_period_pdf)}")
    line_list.append(get_diff_line_str(score_diff))
    line_list.append(f"INFO  d  selection in force: {run_selector_dict['match_int']}/{run_selector_dict['period_count_int']} periods equal v2 "
                     f"(first diff {run_selector_dict['first_period_id']}: run {run_selector_dict['runner']}, v2 {run_selector_dict['reference']})")
    line_list.append(get_diff_line_str(path_dict["diff"]) + f" [total {path_dict['left_total_return']:.6f} vs v2 {path_dict['right_total_return']:.6f}]")
    # THE VERDICT THE RUN WROTE
    verdict_text = {key: report_dict.get(key) for key in ("label_str", "email_worthy_bool", "failed_list") if key in report_dict}
    if "return_dict" in report_dict:
        verdict_text["return_dict"] = {key: value for key, value in report_dict["return_dict"].items() if np.isscalar(value)}
    result_dict["verdict"] = verdict_text if verdict_text else {"report_keys": sorted(report_dict.keys())}
    line_list.append(f"INFO  verdict {result_dict['verdict']}")
    # WRITE, THEN PRINT ONE BLOCK
    result_dict["elapsed_seconds"] = round(time.perf_counter() - start_time, 1)
    write_calibration_json(OUTPUT_PATH_STR, result_dict)
    print("\n===== exp02 calibration summary (paste this block) =====")
    for line_str in line_list:
        print(line_str)
    print(f"elapsed {result_dict['elapsed_seconds']} s; details in {OUTPUT_PATH_STR}")
