import argparse
import json
import os
import pickle
import numpy as np
import pandas as pd
from so import config, paths
from so.core.holdout import get_date
from so.core.continuous_replay import get_period_return_pdf
from so.core.reentry_simulation import simulate_stop_reentry_dict
from so.features.daily_features import get_daily_feature_pdf
from so.runner.checkpoint import get_run_folder_str, read_decisions_list, read_score_row_list
from so.core.development_span import get_development_ohlcv_dict
from so.runner.engine import get_decision_dict
from so.runner.loop import run_engine_decisions_dict
from so.runner.run import get_candidate_engine, get_candidate_token_str
from so.runner.selection import (get_governing_candidate_dict, get_runner_selection_pdf,
                                 run_prior_only_from_decisions_dict)
from experiments.exp04_trend_exit import design as exp04_design
from experiments.exp04_trend_exit.rules import get_trend_exit_signal_arr, get_trend_reentry_signal_arr

"""
exp04 v2.1 runner calibration against the saved v2 development files.

Does not log trials. Does not read the holdout. Reconstructs v2 decisions and trades from the v2 rules on the
runner's development bars (the saved v2 folder has scores, selection and prior-only equity, not per-candidate
trades). A match is identical trades and equity within so.config.NUMERIC_TOLERANCE (1e-6).
"""

# THE SAVED V2 FOLDER AND THE TOLERANCE
V2_NAME_STR = "exp04_trend_exit_v2"
V2_FOLDER_STR = "step01_development_data"
TOLERANCE_FLOAT = float(config.NUMERIC_TOLERANCE)


# FUNCTION: A DATE COLUMN TO datetime.date
def get_day(value_in):
    """
    Args:
        value_in: Date-like

    Returns:
        datetime.date: The date
    """
    # PANDAS AND STRINGS BOTH CONVERT
    return get_date(value_in)


# FUNCTION: FIRST INDEX WHERE TWO SERIES DIFFER BEYOND TOLERANCE
def get_first_diff_dict(left_arr_in, right_arr_in, label_list_in, name_str_in):
    """
    Args:
        left_arr_in, right_arr_in (np.ndarray): Values of equal length
        label_list_in (list): One label per row (usually a date)
        name_str_in (str): What was compared

    Returns:
        dict | None: first_label, left, right, abs_diff, or None when they match
    """
    # NaN EQUALS NaN; FINITE VALUES USE THE TOLERANCE
    left_arr = np.asarray(left_arr_in, dtype=float)
    right_arr = np.asarray(right_arr_in, dtype=float)
    if len(left_arr) != len(right_arr) or len(left_arr) != len(label_list_in):
        return {"first_label": None, "left": len(left_arr), "right": len(right_arr),
                "abs_diff": np.nan, "name_str": name_str_in, "cause_str": "length"}
    nan_equal_arr = np.isnan(left_arr) & np.isnan(right_arr)
    finite_arr = np.isfinite(left_arr) & np.isfinite(right_arr)
    mismatch_arr = ~(nan_equal_arr | (finite_arr & (np.abs(left_arr - right_arr) <= TOLERANCE_FLOAT)))
    if not mismatch_arr.any():
        return None
    idx_int = int(np.flatnonzero(mismatch_arr)[0])
    left_float = float(left_arr[idx_int]) if np.isfinite(left_arr[idx_int]) else np.nan
    right_float = float(right_arr[idx_int]) if np.isfinite(right_arr[idx_int]) else np.nan
    abs_diff_float = abs(left_float - right_float) if np.isfinite(left_float) and np.isfinite(right_float) else np.nan
    return {"first_label": label_list_in[idx_int], "left": left_float, "right": right_float,
            "abs_diff": abs_diff_float, "name_str": name_str_in, "cause_str": "value"}


# FUNCTION: WEIGHT FROM A DECISION DICT (NaN = KEEP)
def get_target_weight_float(decision_in):
    """
    Args:
        decision_in (dict | float): Recorded decision

    Returns:
        float: Target weight
    """
    # A FLOAT IS THE WEIGHT; A DICT STORES IT UNDER target_weight
    if isinstance(decision_in, dict):
        return float(decision_in.get("target_weight", np.nan))
    return float(decision_in)


# FUNCTION: V2-STYLE 0/1/NaN FROM THE SAVED SIGNALS
def get_v2_target_weight_arr(exit_arr_in, reentry_arr_in):
    """
    Exit is 0, re-entry is 1, otherwise NaN. The last session is NaN (both simulators skip it).

    Args:
        exit_arr_in, reentry_arr_in (np.ndarray): Bool per window session

    Returns:
        np.ndarray: Target weights
    """
    # LAST SESSION HAS NO DESIGN CALL
    weight_arr = np.full(len(exit_arr_in), np.nan, dtype=float)
    if len(weight_arr) == 0:
        return weight_arr
    weight_arr[:-1] = np.where(exit_arr_in[:-1], 0.0, np.where(reentry_arr_in[:-1], 1.0, np.nan))
    return weight_arr


# FUNCTION: FILL-LEVEL TRADES FROM A ROUND-TRIP TABLE
def get_round_trip_fill_pdf(transaction_pdf_in):
    """
    Args:
        transaction_pdf_in (pd.DataFrame): simulate_stop_reentry_dict transactions

    Returns:
        pd.DataFrame: date, side, shares, price
    """
    # ONE BUY LEG AND ONE SELL LEG PER ROUND TRIP
    if transaction_pdf_in is None or len(transaction_pdf_in) == 0:
        return pd.DataFrame(columns=["date", "side", "shares", "price"])
    row_dict_list = []
    for _, row in transaction_pdf_in.iterrows():
        row_dict_list.append({"date": get_day(row["buy_ts"]), "side": "buy",
                              "shares": int(row["share_count"]), "price": float(row["buy_fill_price"])})
        row_dict_list.append({"date": get_day(row["sell_ts"]), "side": "sell",
                              "shares": int(row["share_count"]), "price": float(row["sell_fill_price"])})
    return pd.DataFrame(row_dict_list)


# FUNCTION: FILL-LEVEL TRADES FROM THE FRACTIONAL ENGINE
def get_engine_fill_pdf(trade_pdf_in):
    """
    Args:
        trade_pdf_in (pd.DataFrame): Engine trade rows

    Returns:
        pd.DataFrame: date, side, shares, price
    """
    # DELTA SIGN IS THE SIDE
    if trade_pdf_in is None or len(trade_pdf_in) == 0:
        return pd.DataFrame(columns=["date", "side", "shares", "price"])
    row_dict_list = []
    for _, row in trade_pdf_in.iterrows():
        delta_int = int(row["delta_share_count"])
        if delta_int == 0:
            continue
        row_dict_list.append({"date": get_day(row["trade_ts"]), "side": "buy" if delta_int > 0 else "sell",
                              "shares": abs(delta_int), "price": float(row["fill_price"])})
    return pd.DataFrame(row_dict_list)


# FUNCTION: FIRST MISMATCHING FILL
def get_first_trade_diff_dict(left_pdf_in, right_pdf_in):
    """
    Args:
        left_pdf_in, right_pdf_in (pd.DataFrame): date, side, shares, price

    Returns:
        dict | None: First differing fill
    """
    # LENGTH FIRST, THEN ROW BY ROW
    left_pdf = left_pdf_in.reset_index(drop=True)
    right_pdf = right_pdf_in.reset_index(drop=True)
    if len(left_pdf) != len(right_pdf):
        n_int = min(len(left_pdf), len(right_pdf))
        for idx_int in range(n_int):
            if (left_pdf.loc[idx_int, "date"] != right_pdf.loc[idx_int, "date"]
                    or left_pdf.loc[idx_int, "side"] != right_pdf.loc[idx_int, "side"]
                    or int(left_pdf.loc[idx_int, "shares"]) != int(right_pdf.loc[idx_int, "shares"])
                    or abs(float(left_pdf.loc[idx_int, "price"]) - float(right_pdf.loc[idx_int, "price"])) > TOLERANCE_FLOAT):
                return {"first_label": left_pdf.loc[idx_int, "date"], "left": left_pdf.loc[idx_int].to_dict(),
                        "right": right_pdf.loc[idx_int].to_dict(), "abs_diff": np.nan, "cause_str": "row",
                        "left_count": len(left_pdf), "right_count": len(right_pdf)}
        extra_pdf = left_pdf if len(left_pdf) > len(right_pdf) else right_pdf
        extra_row = extra_pdf.iloc[n_int]
        return {"first_label": extra_row["date"], "left": None if len(left_pdf) <= n_int else extra_row.to_dict(),
                "right": None if len(right_pdf) <= n_int else extra_row.to_dict(), "abs_diff": np.nan,
                "cause_str": "count", "left_count": len(left_pdf), "right_count": len(right_pdf)}
    for idx_int in range(len(left_pdf)):
        if (left_pdf.loc[idx_int, "date"] != right_pdf.loc[idx_int, "date"]
                or left_pdf.loc[idx_int, "side"] != right_pdf.loc[idx_int, "side"]
                or int(left_pdf.loc[idx_int, "shares"]) != int(right_pdf.loc[idx_int, "shares"])
                or abs(float(left_pdf.loc[idx_int, "price"]) - float(right_pdf.loc[idx_int, "price"])) > TOLERANCE_FLOAT):
            price_diff_float = abs(float(left_pdf.loc[idx_int, "price"]) - float(right_pdf.loc[idx_int, "price"]))
            return {"first_label": left_pdf.loc[idx_int, "date"], "left": left_pdf.loc[idx_int].to_dict(),
                    "right": right_pdf.loc[idx_int].to_dict(), "abs_diff": price_diff_float, "cause_str": "row",
                    "left_count": len(left_pdf), "right_count": len(right_pdf)}
    return None


# FUNCTION: REPLAY ONE V2 CANDIDATE ON A SPAN
def get_v2_candidate_replay_dict(ohlcv_array_dict_in, daily_pdf_in, date1_in, date2_in, candidate_str_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bars
        daily_pdf_in (pd.DataFrame): Daily features aligned to every session
        date1_in, date2_in: Inclusive span
        candidate_str_in (str): Candidate name

    Returns:
        dict: simulation, window dates, target weights, fill trades
    """
    # THE SAME SIGNALS AND SIMULATOR V2 USED
    candidate_dict = exp04_design.parse_candidate_dict(candidate_str_in)
    exit_all_arr = get_trend_exit_signal_arr(daily_pdf_in, candidate_dict["buffer"], candidate_dict["confirmation"])
    reentry_all_arr = get_trend_reentry_signal_arr(daily_pdf_in, candidate_dict["buffer"])
    session_date_list = [get_day(session_date) for session_date in ohlcv_array_dict_in["session_date_list"]]
    date1, date2 = get_day(date1_in), get_day(date2_in)
    window_idx_list = [idx_int for idx_int, session_date in enumerate(session_date_list) if date1 <= session_date <= date2]
    window_date_list = [session_date_list[idx_int] for idx_int in window_idx_list]
    exit_arr = exit_all_arr[window_idx_list]
    reentry_arr = reentry_all_arr[window_idx_list]
    weight_arr = get_v2_target_weight_arr(exit_arr, reentry_arr)
    reentry_func = lambda session_idx, cash_session_count, episode_dict: bool(reentry_all_arr[session_idx])
    simulation_dict = simulate_stop_reentry_dict(
        ohlcv_array_dict_in, date1, date2, np.full(len(daily_pdf_in), np.nan), None, reentry_func, "rule",
        exit_signal_arr_in=exit_all_arr, max_cash_sessions_in=exp04_design.MAX_CASH_SESSIONS)
    return {"simulation_dict": simulation_dict, "window_date_list": window_date_list, "target_weight_arr": weight_arr,
            "fill_pdf": get_round_trip_fill_pdf(simulation_dict["transaction_pdf"])}


# FUNCTION: LOAD THE SAVED V2 TABLES
def get_v2_saved_dict():
    """
    Returns:
        dict: period, score, selection, equity, summary
    """
    # THE FILES WRITTEN ON 2026-10-13
    folder_str = paths.get_experiment_data_path_str(V2_NAME_STR, V2_FOLDER_STR)
    period_pdf = pd.read_csv(folder_str + "period_data.csv")
    score_pdf = pd.read_csv(folder_str + "score_data.csv")
    selection_pdf = pd.read_csv(folder_str + "selection_data.csv")
    equity_pdf = pd.read_csv(folder_str + "prior_only_daily_equity_data.csv")
    summary_pdf = pd.read_csv(folder_str + "summary_data.csv")
    for column_str in ("period_start", "period_end", "valid_start", "valid_end"):
        period_pdf[column_str] = period_pdf[column_str].map(get_day)
    equity_pdf["date"] = equity_pdf["date"].map(get_day)
    return {"period_pdf": period_pdf, "score_pdf": score_pdf, "selection_pdf": selection_pdf,
            "equity_pdf": equity_pdf, "summary_pdf": summary_pdf, "folder_str": folder_str}


# FUNCTION: LOAD ONE RUNNER RUN
def get_runner_run_dict(run_id_str_in):
    """
    Args:
        run_id_str_in (str): Run id under store04_experiments/runs/

    Returns:
        dict: periods, scores, decisions, engines, optional report
    """
    # CHECKPOINTS HOLD THE ENGINE; DECISIONS.PKL HOLDS THE WEIGHTS
    run_folder_str = get_run_folder_str(run_id_str_in)
    period_pdf = pickle.load(open(os.path.join(run_folder_str, "period.pkl"), "rb"))
    ohlcv_array_dict = pickle.load(open(os.path.join(run_folder_str, "ohlcv.pkl"), "rb"))
    for column_str in ("period_start", "period_end", "valid_start", "valid_end"):
        period_pdf[column_str] = period_pdf[column_str].map(get_day)
    candidate_list = list(exp04_design.CANDIDATE_LIST)
    score_row_list = []
    decision_dict = {}
    trade_dict = {}
    equity_dict = {}
    session_dict = {}
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    for candidate_str in candidate_list:
        token_str = get_candidate_token_str(candidate_str)
        score_row_list.extend(read_score_row_list(run_id_str_in, token_str))
        decision_list = read_decisions_list(run_id_str_in, token_str) or []
        decision_dict[candidate_str] = decision_list
        engine_result_dict = run_engine_decisions_dict(
            ohlcv_array_dict, date1, date2, decision_list, get_candidate_engine(exp04_design),
            float(exp04_design.INITIAL_WEIGHT), float(exp04_design.DEAD_BAND))
        trade_pdf = engine_result_dict.get("trade_pdf")
        equity_pdf = engine_result_dict.get("daily_equity_pdf")
        if equity_pdf is not None and len(equity_pdf):
            equity_pdf = equity_pdf.copy()
            equity_pdf["date"] = equity_pdf["date"].map(get_day)
        else:
            equity_pdf = pd.DataFrame()
        trade_dict[candidate_str] = get_engine_fill_pdf(trade_pdf)
        equity_dict[candidate_str] = equity_pdf
        session_dict[candidate_str] = [get_day(session_date) for session_date in list(engine_result_dict.get("decision_session_list") or [])]
    score_pdf = pd.DataFrame(score_row_list)
    if "fold_id" not in score_pdf.columns and "period_id" in score_pdf.columns:
        score_pdf["fold_id"] = score_pdf["period_id"]
    selection_pdf = get_runner_selection_pdf(score_pdf, exp04_design)
    governing_dict = get_governing_candidate_dict(selection_pdf, period_pdf, candidate_list)
    report_dict = None
    report_path_str = os.path.join(run_folder_str, "report.json")
    if os.path.isfile(report_path_str):
        report_dict = json.load(open(report_path_str, encoding="utf-8"))
    return {"run_folder_str": run_folder_str, "period_pdf": period_pdf, "ohlcv_array_dict": ohlcv_array_dict,
            "score_pdf": score_pdf, "selection_pdf": selection_pdf, "governing_dict": governing_dict,
            "decision_dict": decision_dict, "trade_dict": trade_dict, "equity_dict": equity_dict,
            "session_dict": session_dict, "report_dict": report_dict, "candidate_list": candidate_list}


# FUNCTION: DECISION DICTS FROM A TARGET-WEIGHT ARRAY
def get_decision_list(weight_arr_in):
    """
    Args:
        weight_arr_in (np.ndarray): Target weight per session (NaN = keep)

    Returns:
        list: Decision dicts
    """
    # ONE DECISION PER SESSION
    return [get_decision_dict(float(weight_float) if np.isfinite(weight_float) else None)
            for weight_float in np.asarray(weight_arr_in, dtype=float)]


# FUNCTION: V2 SELECTION TABLE AS period_id -> CANDIDATE IN FORCE
def get_v2_governing_dict(v2_dict_in):
    """
    Args:
        v2_dict_in (dict): Saved v2 tables

    Returns:
        dict: period_id -> candidate
    """
    # THE SAVED ROW IS THE CANDIDATE IN FORCE
    selection_pdf = v2_dict_in["selection_pdf"].copy()
    id_col_str = "period_id" if "period_id" in selection_pdf.columns else "fold_id"
    return {int(row[id_col_str]): str(row["candidate"])
            for _, row in selection_pdf.sort_values(id_col_str).iterrows()}


# FUNCTION: COMPONENT (a): V2 SCORES THROUGH THE RUNNER SELECTOR
def run_component_a_dict(v2_dict_in):
    """
    Feeds the saved v2 candidate-period scores into get_runner_selection_pdf and get_governing_candidate_dict.

    Args:
        v2_dict_in (dict): Saved v2 tables

    Returns:
        dict: match_int, period_count_int, first_diff, governing_dict
    """
    # THE SAME SELECTOR THE RUNNER USES, ON THE SAVED SCORES
    score_pdf = v2_dict_in["score_pdf"].copy()
    if "fold_id" not in score_pdf.columns and "period_id" in score_pdf.columns:
        score_pdf["fold_id"] = score_pdf["period_id"]
    period_pdf = v2_dict_in["period_pdf"]
    candidate_list = list(exp04_design.CANDIDATE_LIST)
    selection_pdf = get_runner_selection_pdf(score_pdf, exp04_design)
    governing_dict = get_governing_candidate_dict(selection_pdf, period_pdf, candidate_list)
    v2_governing_dict = get_v2_governing_dict(v2_dict_in)
    period_id_list = [int(period_id) for period_id in period_pdf.sort_values("period_id")["period_id"]]
    match_int = 0
    first_diff = None
    for period_id in period_id_list:
        runner_candidate_str = governing_dict.get(period_id)
        v2_candidate_str = v2_governing_dict.get(period_id)
        if runner_candidate_str == v2_candidate_str:
            match_int += 1
        elif first_diff is None:
            first_diff = {"first_label": period_id, "left": runner_candidate_str, "right": v2_candidate_str,
                          "abs_diff": np.nan, "cause_str": "candidate"}
    return {"match_int": match_int, "period_count_int": len(period_id_list), "first_diff": first_diff,
            "governing_dict": governing_dict, "v2_governing_dict": v2_governing_dict}


# FUNCTION: COMPONENT (b): RUNNER ENGINE ON V2 GOVERNING AND V2 PERIODS
def run_component_b_dict(v2_dict_in, ohlcv_array_dict_in, daily_pdf_in):
    """
    Drives FractionalWeightEngine with v2's candidate-in-force and v2's period bounds. Compares daily equity to the
    saved prior-only path within NUMERIC_TOLERANCE.

    Args:
        v2_dict_in (dict): Saved v2 tables
        ohlcv_array_dict_in (dict): Bars covering the v2 span
        daily_pdf_in (pd.DataFrame): Daily features aligned to every session of those bars

    Returns:
        dict: equity_diff, match_bool, runner_equity_pdf
    """
    # V2 SPAN, V2 GOVERNING, RUNNER ENGINE
    period_pdf = v2_dict_in["period_pdf"]
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    governing_dict = get_v2_governing_dict(v2_dict_in)
    candidate_decision_dict = {}
    window_date_list = None
    for candidate_str in exp04_design.CANDIDATE_LIST:
        replay_dict = get_v2_candidate_replay_dict(ohlcv_array_dict_in, daily_pdf_in, date1, date2, candidate_str)
        candidate_decision_dict[candidate_str] = get_decision_list(replay_dict["target_weight_arr"])
        window_date_list = replay_dict["window_date_list"]
    prior_only_dict = run_prior_only_from_decisions_dict(
        ohlcv_array_dict_in, date1, date2, window_date_list, candidate_decision_dict, governing_dict, period_pdf,
        dead_band_in=float(exp04_design.DEAD_BAND), initial_weight_in=float(exp04_design.INITIAL_WEIGHT),
        engine_in=get_candidate_engine(exp04_design), design_module_in=exp04_design)
    runner_equity_pdf = prior_only_dict["daily_equity_pdf"].copy()
    runner_equity_pdf["date"] = runner_equity_pdf["date"].map(get_day)
    v2_equity_pdf = v2_dict_in["equity_pdf"]
    merged_pdf = runner_equity_pdf.merge(v2_equity_pdf, on="date", suffixes=("_runner", "_v2"))
    if len(merged_pdf) != len(v2_equity_pdf) or len(runner_equity_pdf) != len(v2_equity_pdf):
        return {"equity_diff": {"first_label": None, "left": len(runner_equity_pdf), "right": len(v2_equity_pdf),
                                "abs_diff": np.nan, "cause_str": "length", "merged_int": len(merged_pdf)},
                "match_bool": False, "runner_equity_pdf": runner_equity_pdf, "merged_pdf": merged_pdf}
    equity_diff = get_first_diff_dict(merged_pdf["equity_runner"].to_numpy(dtype=float),
                                      merged_pdf["equity_v2"].to_numpy(dtype=float),
                                      list(merged_pdf["date"]), "component b equity")
    return {"equity_diff": equity_diff, "match_bool": equity_diff is None, "runner_equity_pdf": runner_equity_pdf,
            "merged_pdf": merged_pdf}


# FUNCTION: PRINT ONE DIFFERENCE LINE
def print_diff_line(title_str_in, diff_dict_in):
    """
    Args:
        title_str_in (str): Heading
        diff_dict_in (dict | None): Output of a first-diff helper

    Returns:
        None
    """
    # MATCH IS A SINGLE WORD
    if diff_dict_in is None:
        print(f"MATCH {title_str_in}")
        return
    print(f"DIFF {title_str_in} first={diff_dict_in.get('first_label')} "
          f"left={diff_dict_in.get('left')} right={diff_dict_in.get('right')} "
          f"abs_diff={diff_dict_in.get('abs_diff')} cause={diff_dict_in.get('cause_str')}")


# PARSE THE COMMAND
if __name__ == "__main__":
    # RUN ID IS OPTIONAL WHEN ONLY THE COMPONENT CHECKS ARE REQUESTED
    parser = argparse.ArgumentParser(description="Compare an exp04 runner run to the saved v2 development files.")
    parser.add_argument("run_id", nargs="?", default=None, help="store04_experiments/runs/<run_id>")
    parser.add_argument("--components-only", action="store_true",
                        help="Selection from v2 scores and engine path from v2 governing; no runner-run compare")
    arg_dict = parser.parse_args()
    v2_dict = get_v2_saved_dict()
    print("COMPONENT a: v2 scores into runner selection")
    component_a_dict = run_component_a_dict(v2_dict)
    print(f"component a selection {component_a_dict['match_int']} / {component_a_dict['period_count_int']}")
    print_diff_line("component a governing vs v2 selection_data.csv", component_a_dict["first_diff"])
    runner_dict = None
    ohlcv_array_dict = None
    daily_pdf = None
    if arg_dict.run_id:
        runner_dict = get_runner_run_dict(arg_dict.run_id)
        ohlcv_array_dict = runner_dict["ohlcv_array_dict"]
    if ohlcv_array_dict is None:
        print("loading development bars for component b")
        span_dict = get_development_ohlcv_dict(int(exp04_design.PERIOD_RULE["embargo_sessions"]))
        ohlcv_array_dict = span_dict["ohlcv_array_dict"]
        print("development_end", span_dict["development_end"], "last_price", span_dict["last_price_date"])
    print("ohlcv", ohlcv_array_dict["session_date_list"][0], "->", ohlcv_array_dict["session_date_list"][-1],
          "n", len(ohlcv_array_dict["session_date_list"]))
    print("building daily features for component b")
    daily_pdf = get_daily_feature_pdf(ohlcv_array_dict)
    print("COMPONENT b: runner engine with v2 governing and v2 periods")
    component_b_dict = run_component_b_dict(v2_dict, ohlcv_array_dict, daily_pdf)
    if component_b_dict["match_bool"]:
        print(f"MATCH component b prior-only equity {len(component_b_dict['runner_equity_pdf'])} sessions within {TOLERANCE_FLOAT}")
    else:
        print_diff_line("component b prior-only equity vs v2", component_b_dict["equity_diff"])
    if arg_dict.components_only:
        print("done")
        raise SystemExit(0)
    if runner_dict is None:
        raise SystemExit("run_id is required unless --components-only")
    v2_period_pdf = v2_dict["period_pdf"]
    runner_period_pdf = runner_dict["period_pdf"]
    print("v2 span", v2_period_pdf["period_start"].iloc[0], "->", v2_period_pdf["period_end"].iloc[-1],
          "sessions", int(v2_period_pdf["session_count"].sum()), "periods", len(v2_period_pdf))
    print("runner span", runner_period_pdf["period_start"].iloc[0], "->", runner_period_pdf["period_end"].iloc[-1],
          "sessions", int(runner_period_pdf["session_count"].sum()), "periods", len(runner_period_pdf))
    bound_match_int = 0
    for _, row in runner_period_pdf.iterrows():
        v2_row_pdf = v2_period_pdf[v2_period_pdf["period_id"] == int(row["period_id"])]
        if len(v2_row_pdf) and get_day(v2_row_pdf["period_start"].iloc[0]) == row["period_start"] and get_day(v2_row_pdf["period_end"].iloc[0]) == row["period_end"]:
            bound_match_int += 1
    print(f"period bounds matched {bound_match_int} / {len(runner_period_pdf)}")
    if bound_match_int < len(runner_period_pdf):
        print("DIFF period bounds first_date",
              f"runner {runner_period_pdf['period_start'].iloc[0]}->{runner_period_pdf['period_end'].iloc[0]}",
              f"v2 {v2_period_pdf['period_start'].iloc[0]}->{v2_period_pdf['period_end'].iloc[0]}")
        print("CAUSE period bounds still differ. Last scored session runner",
              runner_period_pdf["period_end"].iloc[-1], "v2", v2_period_pdf["period_end"].iloc[-1], ".")
    v2_date1, v2_date2 = v2_period_pdf["period_start"].iloc[0], v2_period_pdf["period_end"].iloc[-1]
    runner_date1, runner_date2 = runner_period_pdf["period_start"].iloc[0], runner_period_pdf["period_end"].iloc[-1]
    overlap_date1 = max(v2_date1, runner_date1)
    overlap_date2 = min(v2_date2, runner_date2)
    print("overlap", overlap_date1, "->", overlap_date2)
    # RECONSTRUCT V2 ON THE SAVED V2 SPAN AND CHECK IT AGAINST THE SAVED FILES
    v2_recon_score_list = []
    v2_replay_dict = {}
    for candidate_str in runner_dict["candidate_list"]:
        replay_dict = get_v2_candidate_replay_dict(ohlcv_array_dict, daily_pdf, v2_date1, v2_date2, candidate_str)
        v2_replay_dict[candidate_str] = replay_dict
        period_return_pdf = get_period_return_pdf(replay_dict["simulation_dict"]["daily_equity_pdf"], v2_period_pdf)
        for _, row in period_return_pdf.iterrows():
            v2_recon_score_list.append({"fold_id": int(row["period_id"]), "candidate": candidate_str,
                                        "total_return": float(row["total_return"])})
    v2_recon_score_pdf = pd.DataFrame(v2_recon_score_list)
    saved_score_pdf = v2_dict["score_pdf"]
    recon_match_int = 0
    recon_first_diff = None
    for _, row in saved_score_pdf.iterrows():
        recon_row_pdf = v2_recon_score_pdf[(v2_recon_score_pdf["fold_id"] == int(row["fold_id"]))
                                           & (v2_recon_score_pdf["candidate"] == row["candidate"])]
        if len(recon_row_pdf) == 0:
            recon_first_diff = recon_first_diff or {"first_label": (int(row["fold_id"]), row["candidate"]),
                                                    "cause_str": "missing recon"}
            continue
        abs_diff_float = abs(float(recon_row_pdf["total_return"].iloc[0]) - float(row["total_return"]))
        if abs_diff_float <= TOLERANCE_FLOAT:
            recon_match_int += 1
        elif recon_first_diff is None:
            recon_first_diff = {"first_label": (int(row["fold_id"]), row["candidate"]),
                                "left": float(recon_row_pdf["total_return"].iloc[0]),
                                "right": float(row["total_return"]), "abs_diff": abs_diff_float, "cause_str": "value"}
    print(f"v2 reconstruction vs saved scores {recon_match_int} / {len(saved_score_pdf)}")
    print_diff_line("v2 reconstruction scores", recon_first_diff)
    # PRIOR-ONLY EQUITY OF THE RECONSTRUCTION IS NOT THE SAVED PATH (SELECTION MAY DIFFER); COMPARE SAVED EQUITY LENGTH
    print("saved prior-only rows", len(v2_dict["equity_pdf"]),
          "first", v2_dict["equity_pdf"]["date"].iloc[0], "last", v2_dict["equity_pdf"]["date"].iloc[-1],
          "total_return", float(v2_dict["summary_pdf"]["path_return"].iloc[0]))
    # DECISIONS, TRADES, SCORES PER CANDIDATE
    decision_match_dict = {}
    trade_match_dict = {}
    for candidate_str in runner_dict["candidate_list"]:
        runner_session_list = runner_dict["session_dict"][candidate_str]
        runner_weight_arr = np.array([get_target_weight_float(decision) for decision in runner_dict["decision_dict"][candidate_str]], dtype=float)
        runner_on_overlap_idx_list = [idx_int for idx_int, session_date in enumerate(runner_session_list)
                                      if overlap_date1 <= session_date <= overlap_date2]
        v2_replay_dict_one = get_v2_candidate_replay_dict(ohlcv_array_dict, daily_pdf, runner_date1, runner_date2, candidate_str)
        v2_session_list = v2_replay_dict_one["window_date_list"]
        v2_weight_arr = v2_replay_dict_one["target_weight_arr"]
        v2_on_overlap_idx_list = [idx_int for idx_int, session_date in enumerate(v2_session_list)
                                  if overlap_date1 <= session_date <= overlap_date2]
        runner_overlap_arr = runner_weight_arr[runner_on_overlap_idx_list]
        v2_overlap_arr = v2_weight_arr[v2_on_overlap_idx_list]
        overlap_date_list = [runner_session_list[idx_int] for idx_int in runner_on_overlap_idx_list]
        decision_diff = get_first_diff_dict(runner_overlap_arr, v2_overlap_arr, overlap_date_list, candidate_str)
        decision_match_dict[candidate_str] = decision_diff
        print_diff_line(f"decisions {candidate_str} overlap n={len(overlap_date_list)}", decision_diff)
        runner_fill_pdf = runner_dict["trade_dict"][candidate_str]
        v2_fill_pdf = v2_replay_dict_one["fill_pdf"]
        trade_diff = get_first_trade_diff_dict(runner_fill_pdf, v2_fill_pdf)
        trade_match_dict[candidate_str] = trade_diff
        print_diff_line(f"trades {candidate_str} runner={len(runner_fill_pdf)} v2sim={len(v2_fill_pdf)}", trade_diff)
        runner_cand_score_pdf = runner_dict["score_pdf"][runner_dict["score_pdf"]["candidate"] == candidate_str].sort_values("fold_id")
        v2_cand_score_pdf = saved_score_pdf[saved_score_pdf["candidate"] == candidate_str].sort_values("fold_id")
        n_int = min(len(runner_cand_score_pdf), len(v2_cand_score_pdf))
        score_diff = get_first_diff_dict(runner_cand_score_pdf["total_return"].to_numpy(dtype=float)[:n_int],
                                         v2_cand_score_pdf["total_return"].to_numpy(dtype=float)[:n_int],
                                         list(runner_cand_score_pdf["fold_id"].astype(int))[:n_int],
                                         f"score {candidate_str}")
        print_diff_line(f"period scores {candidate_str} (aligned by fold_id)", score_diff)
    # SELECTION IN FORCE
    runner_gov_list = [runner_dict["governing_dict"][int(period_id)] for period_id in runner_period_pdf.sort_values("period_id")["period_id"]]
    v2_gov_list = [str(row["candidate"]) for _, row in v2_dict["selection_pdf"].sort_values("period_id").iterrows()]
    n_int = min(len(runner_gov_list), len(v2_gov_list))
    sel_mismatch_list = [idx_int for idx_int in range(n_int) if runner_gov_list[idx_int] != v2_gov_list[idx_int]]
    if not sel_mismatch_list and len(runner_gov_list) == len(v2_gov_list):
        print("MATCH selection in force on every period_id")
    else:
        first_idx = sel_mismatch_list[0] if sel_mismatch_list else 0
        print("DIFF selection first period_id", first_idx,
              "runner", runner_gov_list[first_idx] if first_idx < len(runner_gov_list) else None,
              "v2", v2_gov_list[first_idx] if first_idx < len(v2_gov_list) else None,
              f"matched {n_int - len(sel_mismatch_list)} / {n_int}")
    # RUNNER PRIOR-ONLY FROM RECORDED DECISIONS
    date1, date2 = runner_date1, runner_date2
    window_session_date_list = runner_dict["session_dict"][runner_dict["candidate_list"][0]]
    prior_only_dict = run_prior_only_from_decisions_dict(
        ohlcv_array_dict, date1, date2, window_session_date_list, runner_dict["decision_dict"],
        runner_dict["governing_dict"], runner_period_pdf, dead_band_in=float(exp04_design.DEAD_BAND),
        initial_weight_in=float(exp04_design.INITIAL_WEIGHT), engine_in=get_candidate_engine(exp04_design),
        design_module_in=exp04_design)
    runner_equity_pdf = prior_only_dict["daily_equity_pdf"].copy()
    runner_equity_pdf["date"] = runner_equity_pdf["date"].map(get_day)
    runner_total_float = float(runner_equity_pdf["equity"].iloc[-1] / config.INITIAL_CAPITAL - 1.0)
    v2_total_float = float(v2_dict["summary_pdf"]["path_return"].iloc[0])
    print(f"runner prior-only total return {runner_total_float:.8f} over {len(runner_equity_pdf)} sessions")
    print(f"v2 saved prior-only total return {v2_total_float:.8f} over {len(v2_dict['equity_pdf'])} sessions")
    overlap_runner_pdf = runner_equity_pdf[(runner_equity_pdf["date"] >= overlap_date1) & (runner_equity_pdf["date"] <= overlap_date2)]
    overlap_v2_pdf = v2_dict["equity_pdf"][(v2_dict["equity_pdf"]["date"] >= overlap_date1) & (v2_dict["equity_pdf"]["date"] <= overlap_date2)]
    merged_equity_pdf = overlap_runner_pdf.merge(overlap_v2_pdf, on="date", suffixes=("_runner", "_v2"))
    print("overlap equity rows", len(merged_equity_pdf), "runner", len(overlap_runner_pdf), "v2", len(overlap_v2_pdf))
    if len(merged_equity_pdf):
        equity_diff = get_first_diff_dict(merged_equity_pdf["equity_runner"].to_numpy(dtype=float),
                                          merged_equity_pdf["equity_v2"].to_numpy(dtype=float),
                                          list(merged_equity_pdf["date"]), "prior-only equity")
        print_diff_line("prior-only equity on overlapping dates (levels)", equity_diff)
        runner_ret_arr = merged_equity_pdf["equity_runner"].to_numpy(dtype=float)
        v2_ret_arr = merged_equity_pdf["equity_v2"].to_numpy(dtype=float)
        runner_day_arr = np.concatenate([[np.nan], runner_ret_arr[1:] / runner_ret_arr[:-1] - 1.0])
        v2_day_arr = np.concatenate([[np.nan], v2_ret_arr[1:] / v2_ret_arr[:-1] - 1.0])
        day_diff = get_first_diff_dict(runner_day_arr[1:], v2_day_arr[1:], list(merged_equity_pdf["date"])[1:],
                                       "prior-only daily return")
        print_diff_line("prior-only daily returns on overlapping dates", day_diff)
    report_dict = runner_dict["report_dict"]
    if report_dict is None:
        print("runner report.json not written yet")
    else:
        verdict_dict = report_dict.get("verdict_dict") or report_dict.get("verdict") or {}
        print("verdict", verdict_dict.get("label_str") or verdict_dict.get("label") or report_dict.get("label_str"))
        print("email_worthy", verdict_dict.get("email_worthy_bool") if "email_worthy_bool" in verdict_dict else report_dict.get("email_worthy"))
        print("failed", verdict_dict.get("failed_list") or report_dict.get("failed_list"))
        print("report_keys", sorted(report_dict.keys())[:20])
    print("done")
