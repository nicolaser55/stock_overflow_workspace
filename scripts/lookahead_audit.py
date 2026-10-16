import argparse
import importlib
import json
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

"""
Look-ahead audit on development bars (Nicolas, 2026-10-16).

The reference is the saved development path (decisions, and the refit log when that file exists). There is no fresh
full replay. At each cut the path is replayed twice and stops on the cut session: once with sessions after the cut
removed, once with the full bar span perturbed after the cut session's decision bar. The perturbed context keeps that
full span. The refit schedule stops on the cut. Prices on or after the holdout start are not read. A finished design
writes logs/lookahead_audit/<folder>.json and one trial-log note. A check that fails is a finding: the rules are not
changed.

Usage, from the workspace root:
    venv-main/Scripts/python.exe -u scripts/lookahead_audit.py --design exp03_ath_exit --cuts 4
    venv-main/Scripts/python.exe -u scripts/lookahead_audit.py --queue --cuts 4
"""

# THE WORKSPACE ROOT, THE RESULT FOLDER, AND THE QUEUE (RULES FIRST, MODELS LAST)
_ROOT_PATH = Path(__file__).resolve().parents[1]
_RESULT_DIR_PATH = _ROOT_PATH / "logs" / "lookahead_audit"
_QUEUE_LIST = ["exp03_ath_exit", "exp04_trend_exit", "exp05_vol_scaled_exposure", "exp06_capped_regret_reentry",
               "exp07_warning_lights_exit", "exp12_vix_fear_reentry", "exp13_e1m1_robustness",
               "exp02_stop_reentry", "exp01_minute_entry"]
# COLUMNS OF A REFIT THAT MUST MATCH. FIT TIME IS EXCLUDED (IT IS NOT A DECISION).
_REFIT_COLUMN_LIST = ["model_id", "retrain_session", "train_window", "train_start", "rows_used", "rows_purged",
                      "last_label_known_ts", "label_balance", "prediction_move"]
_FLOAT_COLUMN_SET = {"label_balance", "prediction_move"}
# HOW OFTEN A LONG REPLAY WRITES A PROGRESS LINE
_HEARTBEAT_SECOND_COUNT = 10 * 60

# FUNCTION: PRINT A LINE AND FLUSH IT
def say(message_str_in):
    """
    Writes one progress line to stdout and flushes it.

    Args:
        message_str_in (str): Line

    Returns:
        None
    """
    # FLUSH SO A DETACHED LOG SHOWS THE LINE WHILE THE REPLAY RUNS
    print(message_str_in, flush=True)

# FUNCTION: A HEARTBEAT WHILE A REPLAY RUNS
def start_heartbeat_event():
    """
    Prints a progress line every ten minutes until the returned event is set.

    Returns:
        threading.Event: Set it when the replay returns
    """
    # THE FIRST WAIT IS THE INTERVAL, SO A SHORT REPLAY PRINTS NOTHING EXTRA
    stop_event = threading.Event()

    def heartbeat():
        while not stop_event.wait(_HEARTBEAT_SECOND_COUNT):
            say(f"progress {datetime.now().isoformat(timespec='seconds')} still running")

    threading.Thread(target=heartbeat, daemon=True).start()
    return stop_event

# FUNCTION: PACKAGE NAME FROM A FOLDER OR A PATH
def get_package_str(design_str_in):
    """
    The experiment package, without a trailing slash or a leading experiments/.

    Args:
        design_str_in (str): Folder name or path

    Returns:
        str: Package name
    """
    # NORMALISE SEPARATORS AND DROP A TRAILING SLASH
    text_str = str(design_str_in).replace("\\", "/").strip("/")
    if text_str.startswith("experiments/"):
        text_str = text_str[len("experiments/"):]
    return text_str

# FUNCTION: LAST SESSION OF FOUR MONTHS, SPREAD OVER ONE DESIGN'S SPAN
def get_audit_cut_date_list(session_date_list_in, first_decision_date_in, development_end_date_in, cut_count_in):
    """
    The last session of cut_count_in months, spread from just after the first prior-only decision to one quarter
    before the development end. A cut on or before the first decision is not returned (it would pass without testing
    a decision). The last cut is on or before the development end minus three calendar months.

    Args:
        session_date_list_in (list): Sessions of this design (a price calendar or a path)
        first_decision_date_in (datetime.date): First session of the prior-only path
        development_end_date_in (datetime.date): Last development session
        cut_count_in (int): How many cuts

    Returns:
        list[datetime.date]: Cut dates, earliest first
    """
    # IMPORT THE DATE NORMALISER HERE
    from so.core.holdout import get_date
    # REQUIRE A POSITIVE COUNT
    cut_count = int(cut_count_in)
    if cut_count < 1:
        raise ValueError("cut_count_in must be at least 1.")
    # THE LAST ALLOWED SESSION IS ONE QUARTER BEFORE THE DEVELOPMENT END
    first_decision_date = get_date(first_decision_date_in)
    development_end_date = get_date(development_end_date_in)
    latest_date = (pd.Timestamp(development_end_date) - pd.DateOffset(months=3)).date()
    # THE LAST SESSION OF EACH MONTH, STRICTLY AFTER THE FIRST DECISION AND ON OR BEFORE THE QUARTER LIMIT
    month_dict = {}
    for session_date in session_date_list_in:
        session_day = get_date(session_date)
        month_dict[(session_day.year, session_day.month)] = session_day
    eligible_list = sorted(session_day for session_day in month_dict.values()
                           if first_decision_date < session_day <= latest_date)
    if len(eligible_list) < cut_count:
        raise ValueError(f"need {cut_count} month-ends after {first_decision_date} and on or before {latest_date}; "
                         f"found {len(eligible_list)}.")
    # SPREAD THE CUTS ACROSS THE ELIGIBLE MONTH-ENDS, INCLUDING BOTH ENDS
    index_list = []
    for rank in range(cut_count):
        index = 0 if cut_count == 1 else int(round(rank * (len(eligible_list) - 1) / (cut_count - 1)))
        if index not in index_list:
            index_list.append(index)
    unused_list = [index for index in range(len(eligible_list)) if index not in index_list]
    while len(index_list) < cut_count and unused_list:
        index_list.append(unused_list.pop(len(unused_list) // 2))
    index_list.sort()
    return [eligible_list[index] for index in index_list[:cut_count]]

# FUNCTION: PERIODS THAT END AFTER THE CUT, CLIPPED SO THE CUT SESSION IS STILL DECIDED
def get_clipped_period_pdf(period_pdf_in, cut_date_in):
    """
    Drops periods that start after the cut. A period that contains the cut keeps its id and ends on the cut, so the
    path still decides on the cut session. Periods that already end before the cut are unchanged.

    Args:
        period_pdf_in (pd.DataFrame): Development periods
        cut_date_in (datetime.date): Cut session

    Returns:
        pd.DataFrame: Periods the truncated replay scores
    """
    # IMPORT THE DATE NORMALISER HERE
    from so.core.holdout import get_date
    # CLIP EACH PERIOD THAT STARTS ON OR BEFORE THE CUT
    cut_date = get_date(cut_date_in)
    row_dict_list = []
    for row_dict in period_pdf_in.to_dict("records"):
        start_date = get_date(row_dict["period_start"])
        end_date = get_date(row_dict["period_end"])
        if start_date > cut_date:
            continue
        row_dict["period_end"] = min(end_date, cut_date)
        if get_date(row_dict["period_end"]) >= start_date:
            row_dict_list.append(row_dict)
    if not row_dict_list:
        raise ValueError(f"no period starts on or before {cut_date}.")
    return pd.DataFrame(row_dict_list)

# FUNCTION: ONE FRESH REPLAY
def get_replay_result_dict(design_module_in, ohlcv_array_dict_in, period_pdf_in, data_context_in):
    """
    Scores every candidate and runs the prior-only path on a fresh design module.

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: period_pdf, score_pdf, selection_pdf, path_dict
    """
    # IMPORT THE RUNNER'S REPLAY PIECES HERE
    from so.core.holdout import call_design_replay, get_candidate_score_pdf, get_fresh_design_module, get_governing_selection_pdf
    # A FRESH MODULE, SO THIS REPLAY DOES NOT SEE ANOTHER CUT'S CACHE
    design_module = get_fresh_design_module(design_module_in)
    score_pdf = get_candidate_score_pdf(design_module, ohlcv_array_dict_in, period_pdf_in, data_context_in)
    selection_pdf = get_governing_selection_pdf(design_module, score_pdf, period_pdf_in)
    path_dict = call_design_replay(design_module.run_prior_only_path_dict,
                                   [ohlcv_array_dict_in, period_pdf_in, selection_pdf], data_context_in)
    return {"period_pdf": period_pdf_in, "score_pdf": score_pdf, "selection_pdf": selection_pdf, "path_dict": path_dict}

# FUNCTION: ONE REFIT CELL, SO A TIMESTAMP AND A NAN COMPARE
def get_refit_cell(value_in, column_str_in):
    """
    A value that can be compared across two refit logs.

    Args:
        value_in: Cell
        column_str_in (str): Column name

    Returns:
        The comparable value
    """
    # A MISSING CELL MATCHES ANOTHER MISSING CELL
    if value_in is None or (not isinstance(value_in, str) and pd.isna(value_in)):
        return None
    # FLOATS USE A TOLERANCE AT COMPARE TIME
    if column_str_in in _FLOAT_COLUMN_SET:
        return float(value_in)
    # DATES AND TIMESTAMPS BECOME TEXT
    if column_str_in in {"retrain_session", "train_start", "last_label_known_ts", "decision_ts"}:
        if hasattr(value_in, "isoformat"):
            return value_in.isoformat()
        return str(pd.Timestamp(value_in))
    return value_in

# FUNCTION: REFIT ROWS ON OR BEFORE THE CUT
def get_refit_row_list(path_dict_in, cut_date_in):
    """
    Refit rows whose retrain session is on or before the cut, in a stable order. Fit time is not included.

    Args:
        path_dict_in (dict): Path
        cut_date_in (datetime.date): Cut session

    Returns:
        list[tuple]: Comparable rows
    """
    # AN EMPTY LOG HAS NO REFIT TO COMPARE
    from so.core.holdout import get_date
    refit_pdf = path_dict_in.get("refit_log_pdf")
    if refit_pdf is None or len(refit_pdf) == 0 or "retrain_session" not in refit_pdf.columns:
        return []
    cut_date = get_date(cut_date_in)
    work_pdf = refit_pdf.copy()
    work_pdf["_cut_day"] = work_pdf["retrain_session"].map(get_date)
    work_pdf = work_pdf[work_pdf["_cut_day"] <= cut_date]
    sort_list = [column_str for column_str in ["train_window", "retrain_session", "model_id"] if column_str in work_pdf.columns]
    if sort_list:
        work_pdf = work_pdf.sort_values(sort_list)
    column_list = [column_str for column_str in _REFIT_COLUMN_LIST if column_str in work_pdf.columns]
    return [tuple(get_refit_cell(row_dict[column_str], column_str) for column_str in column_list)
            for row_dict in work_pdf[column_list].to_dict("records")]

# FUNCTION: THE FIRST REFIT THAT DIFFERS ON OR BEFORE THE CUT
def get_refit_difference_str(full_result_dict_in, short_result_dict_in, cut_date_in):
    """
    None when every refit on or before the cut matches. A path with no refit log is unchanged.

    Args:
        full_result_dict_in (dict): Replay on the original bars
        short_result_dict_in (dict): Replay on the cut bars
        cut_date_in (datetime.date): Cut session

    Returns:
        str | None: The refit that differed, or None
    """
    # COMPARE THE ROWS THAT THE CUT IS ALLOWED TO HAVE SEEN
    full_row_list = get_refit_row_list(full_result_dict_in["path_dict"], cut_date_in)
    short_row_list = get_refit_row_list(short_result_dict_in["path_dict"], cut_date_in)
    if full_row_list == short_row_list:
        return None
    if len(full_row_list) != len(short_row_list):
        return f"refit count at {cut_date_in} ({len(full_row_list)} vs {len(short_row_list)})"
    for row_idx, (full_row, short_row) in enumerate(zip(full_row_list, short_row_list)):
        for full_value, short_value in zip(full_row, short_row):
            if isinstance(full_value, float) and isinstance(short_value, float):
                if abs(full_value - short_value) > 1e-12:
                    return f"refit row {row_idx} at {cut_date_in}"
            elif full_value != short_value:
                return f"refit row {row_idx} at {cut_date_in}"
    return None

# FUNCTION: CONTEXT FOR ONE CHECK
def get_cut_context(data_context_in, ohlcv_array_dict_in, cut_ohlcv_dict_in, cut_date_in, kind_str_in):
    """
    The truncated or perturbed context. None when the replay has no context.

    Args:
        data_context_in (DataContext | None): Development context
        ohlcv_array_dict_in (dict): Bars the clock is read from
        cut_ohlcv_dict_in (dict): Bars the child context serves as SPY
        cut_date_in (datetime.date): Cut session
        kind_str_in (str): "truncation" or "perturbation"

    Returns:
        DataContext | None: Child context
    """
    # A DESIGN THAT DOES NOT TAKE A CONTEXT KEEPS THE OLD CALL
    if data_context_in is None:
        return None
    from so.core.holdout import get_date
    from so.core.point_in_time import get_cut_clock_dict
    clock_dict = get_cut_clock_dict(ohlcv_array_dict_in, cut_date_in)
    if kind_str_in == "truncation":
        return data_context_in.get_truncated_context(clock_dict["session_end_ts"], cut_ohlcv_dict_in)
    seed_int = int(get_date(cut_date_in).strftime("%Y%m%d"))
    return data_context_in.get_perturbed_context(clock_dict["decision_ts"], seed_int, cut_ohlcv_dict_in)

# FUNCTION: STOP REFITS AND ROLLING DECISIONS AFTER THE CUT
def stop_decision_schedule(design_module_in, period_pdf_in, cut_date_in):
    """
    The bars and the context may still hold later rows. The refit schedule and the rolling decision list stop on the
    cut. A design without those hooks is unchanged; its path still ends where the clipped periods end.

    Args:
        design_module_in (module): The fresh module this replay will call
        period_pdf_in (pd.DataFrame): Periods that include the cut
        cut_date_in (datetime.date): Last decision session

    Returns:
        None
    """
    # THE SCORED SPAN AND THE DECISION LIST BOTH END ON THE CUT
    from so.core.holdout import get_date
    cut_date = get_date(cut_date_in)
    start_date = get_date(period_pdf_in["period_start"].iloc[0])
    if hasattr(design_module_in, "set_score_span"):
        design_module_in.set_score_span(start_date, cut_date)
    if hasattr(design_module_in, "get_decision_session_list"):
        original_func = design_module_in.get_decision_session_list

        def stopped_decision_session_list(row_pdf_in, original_func_in=original_func, end_date_in=cut_date):
            return [session_date for session_date in original_func_in(row_pdf_in) if get_date(session_date) <= end_date_in]

        design_module_in.get_decision_session_list = stopped_decision_session_list

# FUNCTION: REPLAY THE SAVED SELECTION THROUGH THE CUT ONLY
def get_cut_replay_result_dict(design_module_in, ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in, cut_date_in):
    """
    One fresh module. Periods that start after the cut are dropped. The open period ends on the cut. The saved
    candidate stays in force. Nothing after the cut is decided.

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Bars for this check
        period_pdf_in (pd.DataFrame): Saved periods
        selection_pdf_in (pd.DataFrame): Saved candidate in force
        data_context_in (DataContext | None): Context for this check
        cut_date_in (datetime.date): Last decision session

    Returns:
        dict: period_pdf, selection_pdf, path_dict
    """
    # A FRESH MODULE, THEN THE SCHEDULE STOPS ON THE CUT
    from so.core.holdout import call_design_replay, get_fresh_design_module
    design_module = get_fresh_design_module(design_module_in)
    clipped_pdf = get_clipped_period_pdf(period_pdf_in, cut_date_in)
    stop_decision_schedule(design_module, clipped_pdf, cut_date_in)
    kept_id_set = set(clipped_pdf["period_id"].astype(int))
    kept_pdf = selection_pdf_in[selection_pdf_in["period_id"].astype(int).isin(kept_id_set)].copy()
    path_dict = call_design_replay(design_module.run_prior_only_path_dict, [ohlcv_array_dict_in, clipped_pdf, kept_pdf], data_context_in)
    return {"period_pdf": clipped_pdf, "selection_pdf": kept_pdf, "path_dict": path_dict}

# FUNCTION: TRUE WHEN THE CUT SESSION'S TARGET IS THE FORCED END-OF-WINDOW SALE
def get_terminal_target_bool(path_dict_in, cut_date_in):
    """
    True when the path ends on the cut, an END trade is on that session, and the target weights are the equity
    weights. That last weight is the liquidation, not a decision.

    Args:
        path_dict_in (dict): Path
        cut_date_in (datetime.date): Cut session

    Returns:
        bool: The cut target is the liquidation
    """
    # AN INDEPENDENT TARGET (A PREDICTION, A LEAK) IS NOT THE LIQUIDATION
    from so.core.holdout import get_date
    if "target_weight_arr" not in path_dict_in or "daily_equity_pdf" not in path_dict_in:
        return False
    equity_pdf = path_dict_in["daily_equity_pdf"]
    if "weight" not in equity_pdf.columns or "date" not in equity_pdf.columns or len(equity_pdf) == 0:
        return False
    if get_date(equity_pdf["date"].iloc[-1]) != get_date(cut_date_in):
        return False
    target_arr = np.asarray(path_dict_in["target_weight_arr"], dtype=float)
    weight_arr = equity_pdf["weight"].to_numpy(dtype=float)
    if len(target_arr) != len(weight_arr) or not np.allclose(target_arr, weight_arr, equal_nan=True):
        return False
    trade_pdf = path_dict_in.get("trade_pdf")
    if trade_pdf is None or len(trade_pdf) == 0:
        return False
    reason_str = "reason" if "reason" in trade_pdf.columns else ("exit_reason" if "exit_reason" in trade_pdf.columns else "")
    if not reason_str or not (trade_pdf[reason_str].astype(str) == "END").any():
        return False
    return True

# FUNCTION: DECISIONS THROUGH THE CUT AGAINST THE REFERENCE
def get_decision_difference_str(reference_result_dict_in, short_result_dict_in, cut_date_in):
    """
    None when the decisions through the cut match the reference. A forced sale on the cut session is not a decision.
    Signals are compared when the reference has them. Refits are compared when the reference has a refit log.

    Args:
        reference_result_dict_in (dict): Saved path, or the test's stand-in
        short_result_dict_in (dict): Replay that stops on the cut
        cut_date_in (datetime.date): Cut session

    Returns:
        str | None: The first difference, or None
    """
    # THE RUNNER'S COMPARE, WITH THE TERMINAL SALE AND A MISSING TRADE TABLE TAKEN OUT
    from so.core.holdout import get_date, get_lookahead_difference_str, get_signal_difference_str
    reference_path_dict = dict(reference_result_dict_in["path_dict"])
    short_path_dict = dict(short_result_dict_in["path_dict"])
    if get_terminal_target_bool(short_result_dict_in["path_dict"], cut_date_in) and "target_weight_arr" in reference_path_dict:
        reference_date_list = [get_date(session_date) for session_date in reference_path_dict["decision_session_list"]]
        cut_date = get_date(cut_date_in)
        if cut_date in reference_date_list:
            target_arr = np.array(short_path_dict["target_weight_arr"], dtype=float, copy=True)
            target_arr[-1] = float(reference_path_dict["target_weight_arr"][reference_date_list.index(cut_date)])
            short_path_dict["target_weight_arr"] = target_arr
    if reference_result_dict_in["path_dict"].get("trade_pdf") is None:
        empty_pdf = pd.DataFrame(columns=["trade_ts", "delta_share_count", "reason"])
        reference_path_dict["trade_pdf"] = empty_pdf
        short_path_dict["trade_pdf"] = empty_pdf
    difference_str = get_lookahead_difference_str({**reference_result_dict_in, "path_dict": reference_path_dict},
                                                  {**short_result_dict_in, "path_dict": short_path_dict}, cut_date_in)
    if difference_str is not None:
        return difference_str
    # A SIGNAL THE REFERENCE DOES NOT CARRY IS NOT A DIFFERENCE
    if "signal_arr" in reference_result_dict_in["path_dict"]:
        difference_str = get_signal_difference_str(reference_result_dict_in, short_result_dict_in, cut_date_in)
        if difference_str is not None:
            return difference_str
    reference_refit_pdf = reference_result_dict_in["path_dict"].get("refit_log_pdf")
    if reference_refit_pdf is None or len(reference_refit_pdf) == 0 or "retrain_session" not in getattr(reference_refit_pdf, "columns", []):
        return None
    return get_refit_difference_str(reference_result_dict_in, short_result_dict_in, cut_date_in)

# FUNCTION: THE SAVED DEVELOPMENT PATH
def get_saved_reference_dict(experiment_name_str_in):
    """
    Periods, the candidate in force, the daily equity, and the refit log when the development run saved one.

    Args:
        experiment_name_str_in (str): Experiment name, including the _v2 suffix

    Returns:
        dict: period_pdf, selection_pdf, path_dict
    """
    # READ THE DEVELOPMENT FOLDER. THE EQUITY WEIGHT IS THE SAVED DECISION.
    from so.core.holdout import get_date
    from so.paths import get_experiment_data_path_str
    folder_str = get_experiment_data_path_str(experiment_name_str_in, "step01_development_data")
    period_pdf = pd.read_csv(folder_str + "period_data.csv")
    selection_pdf = pd.read_csv(folder_str + "selection_data.csv")
    equity_pdf = pd.read_csv(folder_str + "prior_only_daily_equity_data.csv")
    equity_pdf["date"] = equity_pdf["date"].map(get_date)
    path_dict = {"daily_equity_pdf": equity_pdf, "target_weight_arr": equity_pdf["weight"].to_numpy(dtype=float),
                 "decision_session_list": list(equity_pdf["date"])}
    refit_path = Path(folder_str + "refit_log_data.csv")
    if refit_path.is_file():
        path_dict["refit_log_pdf"] = pd.read_csv(refit_path)
    return {"period_pdf": period_pdf, "selection_pdf": selection_pdf, "path_dict": path_dict}

# FUNCTION: RUN BOTH CHECKS AT EVERY CUT
def get_audit_result_dict(design_module_in, ohlcv_array_dict_in, period_pdf_in, data_context_in, cut_count_in,
                          reference_result_dict_in, development_end_date_in=None):
    """
    Truncation and perturbation at each cut, compared with the reference. The reference is not recomputed. Each
    replay stops on the cut. The perturbed bars and context keep the full span.

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Development bars
        period_pdf_in (pd.DataFrame): Periods (the saved periods for a real design)
        data_context_in (DataContext | None): Development context
        cut_count_in (int): How many cuts
        reference_result_dict_in (dict): Saved path, or the test's stand-in
        development_end_date_in (datetime.date | None): Development end (None = the last bar session)

    Returns:
        dict: passed, cut_date_list, first_difference, check
    """
    # IMPORT THE RUNNER'S BAR EDITS HERE
    from so.core.holdout import get_date, get_perturbed_ohlcv_dict, get_truncated_ohlcv_dict
    # CUTS COME FROM THE REFERENCE'S FIRST DECISION, NOT FROM A NEW FULL REPLAY
    decision_list = list(reference_result_dict_in["path_dict"]["decision_session_list"])
    if not decision_list:
        raise ValueError("the reference path has no decision session.")
    first_decision_date = get_date(decision_list[0])
    session_list = [get_date(session_date) for session_date in ohlcv_array_dict_in["session_date_list"]]
    development_end_date = get_date(development_end_date_in) if development_end_date_in is not None else session_list[-1]
    cut_date_list = get_audit_cut_date_list(session_list, first_decision_date, development_end_date, cut_count_in)
    say(f"cuts {', '.join(str(cut_date) for cut_date in cut_date_list)} (first decision {first_decision_date})")
    # EACH CUT: TRUNCATION, THEN PERTURBATION. THE FIRST DIFFERENCE IS THE FINDING.
    for cut_date in cut_date_list:
        say(f"truncation {cut_date}")
        truncated_dict = get_truncated_ohlcv_dict(ohlcv_array_dict_in, cut_date)
        stop_event = start_heartbeat_event()
        try:
            short_result_dict = get_cut_replay_result_dict(
                design_module_in, truncated_dict, period_pdf_in, reference_result_dict_in["selection_pdf"],
                get_cut_context(data_context_in, ohlcv_array_dict_in, truncated_dict, cut_date, "truncation"), cut_date)
        finally:
            stop_event.set()
        difference_str = get_decision_difference_str(reference_result_dict_in, short_result_dict, cut_date)
        if difference_str is not None:
            return {"passed": False, "cut_date_list": [str(cut) for cut in cut_date_list],
                    "first_difference": f"truncation {difference_str}", "check": "truncation"}
        say(f"perturbation {cut_date}")
        perturbed_dict = get_perturbed_ohlcv_dict(ohlcv_array_dict_in, cut_date)
        stop_event = start_heartbeat_event()
        try:
            perturbed_result_dict = get_cut_replay_result_dict(
                design_module_in, perturbed_dict, period_pdf_in, reference_result_dict_in["selection_pdf"],
                get_cut_context(data_context_in, ohlcv_array_dict_in, perturbed_dict, cut_date, "perturbation"), cut_date)
        finally:
            stop_event.set()
        difference_str = get_decision_difference_str(reference_result_dict_in, perturbed_result_dict, cut_date)
        if difference_str is not None:
            return {"passed": False, "cut_date_list": [str(cut) for cut in cut_date_list],
                    "first_difference": f"perturbation {difference_str}", "check": "perturbation"}
    return {"passed": True, "cut_date_list": [str(cut) for cut in cut_date_list], "first_difference": "", "check": ""}

# FUNCTION: THE RESULT FILE FOR ONE DESIGN
def get_result_path(package_str_in):
    """
    The JSON file a later session reads.

    Args:
        package_str_in (str): Experiment package

    Returns:
        Path: Result file
    """
    # ONE FILE PER DESIGN
    return _RESULT_DIR_PATH / f"{get_package_str(package_str_in)}.json"

# FUNCTION: WRITE THE RESULT AND REPLACE ANY PARTIAL FILE
def write_audit_result_dict(package_str_in, result_dict_in):
    """
    Writes the result JSON. A reader sees the file only after the write finishes.

    Args:
        package_str_in (str): Experiment package
        result_dict_in (dict): Result

    Returns:
        Path: The file
    """
    # WRITE A TEMPORARY FILE, THEN REPLACE
    result_path = get_result_path(package_str_in)
    result_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = result_path.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(result_dict_in, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(result_path)
    return result_path

# FUNCTION: TRUE WHEN A PREVIOUS RUN ALREADY FINISHED THIS DESIGN
def get_finished_bool(package_str_in):
    """
    True when the result file exists and says the audit completed.

    Args:
        package_str_in (str): Experiment package

    Returns:
        bool: Finished
    """
    # AN ABSENT OR PARTIAL FILE IS NOT FINISHED
    result_path = get_result_path(package_str_in)
    if not result_path.is_file():
        return False
    result_dict = json.loads(result_path.read_text(encoding="utf-8"))
    return bool(result_dict.get("complete"))

# FUNCTION: LOAD DEVELOPMENT BARS, PERIODS AND THE CONTEXT
def get_development_audit_dict(design_module_in):
    """
    Bars through the development end and the design's development context. Periods come from the saved development
    run. The holdout start is a date on the anchor list. Its prices are not loaded.

    Args:
        design_module_in (module): Design

    Returns:
        dict: ohlcv_array_dict, data_context, development_end
    """
    # IMPORT THE DEVELOPMENT SPAN HERE
    from so.core.development_span import get_development_ohlcv_dict
    # THE EMBARGO IS THE DESIGN'S PERIOD RULE. PRICES STOP AT THE DEVELOPMENT END.
    embargo_int = int(design_module_in.PERIOD_RULE["embargo_sessions"])
    span_dict = get_development_ohlcv_dict(embargo_int)
    data_context = design_module_in.get_development_data_context(span_dict["anchor_session_list"])
    return {"ohlcv_array_dict": span_dict["ohlcv_array_dict"], "data_context": data_context,
            "development_end": span_dict["development_end"]}

# FUNCTION: AUDIT ONE DESIGN, WRITE THE FILE, THEN THE NOTE
def run_design_audit(package_str_in, cut_count_in):
    """
    Runs the audit when this design has no completed result file. The trial-log note is written only after the
    result file, and only when the audit completed.

    Args:
        package_str_in (str): Experiment package
        cut_count_in (int): How many cuts

    Returns:
        dict: The result
    """
    # SKIP A DESIGN WHOSE RESULT FILE IS ALREADY COMPLETE
    package_str = get_package_str(package_str_in)
    if get_finished_bool(package_str):
        say(f"skip {package_str} (result file already complete)")
        return json.loads(get_result_path(package_str).read_text(encoding="utf-8"))
    say(f"start {package_str} {datetime.now().isoformat(timespec='seconds')}")
    design_module = importlib.import_module(f"experiments.{package_str}.design")
    loaded_dict = get_development_audit_dict(design_module)
    reference_dict = get_saved_reference_dict(design_module.EXPERIMENT_NAME)
    result_dict = get_audit_result_dict(design_module, loaded_dict["ohlcv_array_dict"], reference_dict["period_pdf"],
                                        loaded_dict["data_context"], cut_count_in, reference_dict, loaded_dict["development_end"])
    result_dict.update({"experiment": design_module.EXPERIMENT_NAME, "package": package_str, "complete": True,
                        "finished_ts": datetime.now().isoformat(timespec="seconds")})
    result_path = write_audit_result_dict(package_str, result_dict)
    say(f"wrote {result_path} passed={result_dict['passed']}")
    # THE NOTE COMES AFTER THE FILE, SO A KILLED PROCESS LEAVES NO NOTE FOR AN UNFINISHED DESIGN
    from so.core.trial_log import log_trial_dict
    config_module = importlib.import_module(f"experiments.{package_str}.config")
    difference_str = str(result_dict.get("first_difference") or "")
    log_trial_dict(config_module, "note",
                   {"cut_dates": ",".join(result_dict["cut_date_list"]), "check": result_dict.get("check") or ""},
                   {"passed": int(bool(result_dict["passed"])), "first_difference": difference_str[:500]},
                   False, note_str_in="lookahead audit")
    say(f"note {design_module.EXPERIMENT_NAME}")
    return result_dict

# FUNCTION: AUDIT ONE DESIGN AND KEEP GOING AFTER AN EXCEPTION
def run_design_audit_bool(package_str_in, cut_count_in):
    """
    Runs one design. An exception writes an incomplete result and does not append a trial-log note.

    Args:
        package_str_in (str): Experiment package
        cut_count_in (int): How many cuts

    Returns:
        bool: True when the audit completed (pass or finding)
    """
    # A FINDING COMPLETES. AN EXCEPTION DOES NOT.
    try:
        result_dict = run_design_audit(package_str_in, cut_count_in)
    except Exception:
        package_str = get_package_str(package_str_in)
        error_str = traceback.format_exc()
        say(error_str)
        write_audit_result_dict(package_str, {"package": package_str, "complete": False, "passed": False,
                                              "cut_date_list": [], "first_difference": error_str[-2000:],
                                              "check": "error", "finished_ts": datetime.now().isoformat(timespec="seconds")})
        return False
    return bool(result_dict.get("complete"))

# FUNCTION: THE COMMAND LINE
def main(argument_list_in):
    """
    One design, or the queue. Returns 0 when every requested design completed.

    Args:
        argument_list_in (list[str]): Arguments after the script name

    Returns:
        int: Exit code
    """
    # PARSE THE FOLDER AND THE CUT COUNT
    parser = argparse.ArgumentParser(description="Look-ahead audit on development bars")
    parser.add_argument("--design", default="", help="Experiment folder, e.g. exp03_ath_exit")
    parser.add_argument("--queue", action="store_true", help="Run the nine designs in order")
    parser.add_argument("--cuts", type=int, default=4, help="Cut dates per design")
    argument_namespace = parser.parse_args(argument_list_in)
    if argument_namespace.queue:
        package_list = list(_QUEUE_LIST)
    elif argument_namespace.design:
        package_list = [get_package_str(argument_namespace.design)]
    else:
        say("usage: python scripts/lookahead_audit.py --design <folder> --cuts 4")
        return 2
    # ONE DESIGN AT A TIME. A FINDING DOES NOT STOP THE QUEUE.
    failed_bool = False
    for package_str in package_list:
        if not run_design_audit_bool(package_str, argument_namespace.cuts):
            failed_bool = True
    return 1 if failed_bool else 0

# RUN THE AUDIT
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
