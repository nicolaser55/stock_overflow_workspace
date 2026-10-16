import argparse
import importlib
import json
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd

"""
Look-ahead audit on development bars (Nicolas, 2026-10-16).

For one design, replay the prior-only path, then replay it again at each cut date under the two checks the holdout
runner uses: sessions after the cut dropped, and every bar after the cut session's decision bar perturbed. Decisions
through the cut must match, including refits on or before the cut. Prices on or after the holdout start are not read.
A finished design writes logs/lookahead_audit/<folder>.json and one trial-log note. A check that fails is a finding:
the rules are not changed.

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

# FUNCTION: RUN BOTH CHECKS AT EVERY CUT
def get_audit_result_dict(design_module_in, ohlcv_array_dict_in, period_pdf_in, data_context_in, cut_count_in,
                          development_end_date_in=None):
    """
    The full prior-only path, then truncation and perturbation at each cut. The first difference stops the audit.

    Args:
        design_module_in (module): Design
        ohlcv_array_dict_in (dict): Development bars
        period_pdf_in (pd.DataFrame): Development periods
        data_context_in (DataContext | None): Development context
        cut_count_in (int): How many cuts
        development_end_date_in (datetime.date | None): Development end (None = the last bar session)

    Returns:
        dict: passed, cut_date_list, first_difference, check
    """
    # IMPORT THE RUNNER'S CHECKS HERE
    from so.core.holdout import (get_date, get_lookahead_difference_str, get_perturbed_ohlcv_dict,
                                 get_signal_difference_str, get_truncated_ohlcv_dict)
    # THE FULL PATH, WITH A HEARTBEAT SO A LONG FIT STILL WRITES THE LOG
    say("full replay")
    stop_event = start_heartbeat_event()
    try:
        full_result_dict = get_replay_result_dict(design_module_in, ohlcv_array_dict_in, period_pdf_in, data_context_in)
    finally:
        stop_event.set()
    decision_list = list(full_result_dict["path_dict"]["decision_session_list"])
    if not decision_list:
        raise ValueError("the prior-only path has no decision session.")
    first_decision_date = get_date(decision_list[0])
    session_list = [get_date(session_date) for session_date in ohlcv_array_dict_in["session_date_list"]]
    development_end_date = get_date(development_end_date_in) if development_end_date_in is not None else session_list[-1]
    cut_date_list = get_audit_cut_date_list(session_list, first_decision_date, development_end_date, cut_count_in)
    say(f"cuts {', '.join(str(cut_date) for cut_date in cut_date_list)} (first decision {first_decision_date})")
    # EACH CUT: TRUNCATION, THEN PERTURBATION. THE FIRST DIFFERENCE IS THE FINDING.
    for cut_date in cut_date_list:
        say(f"truncation {cut_date}")
        truncated_dict = get_truncated_ohlcv_dict(ohlcv_array_dict_in, cut_date)
        clipped_pdf = get_clipped_period_pdf(period_pdf_in, cut_date)
        stop_event = start_heartbeat_event()
        try:
            short_result_dict = get_replay_result_dict(design_module_in, truncated_dict, clipped_pdf,
                                                       get_cut_context(data_context_in, ohlcv_array_dict_in, truncated_dict, cut_date, "truncation"))
        finally:
            stop_event.set()
        difference_str = get_lookahead_difference_str(full_result_dict, short_result_dict, cut_date)
        if difference_str is None:
            difference_str = get_signal_difference_str(full_result_dict, short_result_dict, cut_date)
        if difference_str is None:
            difference_str = get_refit_difference_str(full_result_dict, short_result_dict, cut_date)
        if difference_str is not None:
            return {"passed": False, "cut_date_list": [str(cut) for cut in cut_date_list],
                    "first_difference": f"truncation {difference_str}", "check": "truncation"}
        say(f"perturbation {cut_date}")
        perturbed_dict = get_perturbed_ohlcv_dict(ohlcv_array_dict_in, cut_date)
        stop_event = start_heartbeat_event()
        try:
            perturbed_result_dict = get_replay_result_dict(design_module_in, perturbed_dict, period_pdf_in,
                                                           get_cut_context(data_context_in, ohlcv_array_dict_in, perturbed_dict, cut_date, "perturbation"))
        finally:
            stop_event.set()
        difference_str = get_lookahead_difference_str(full_result_dict, perturbed_result_dict, cut_date)
        if difference_str is None:
            difference_str = get_signal_difference_str(full_result_dict, perturbed_result_dict, cut_date)
        if difference_str is None:
            difference_str = get_refit_difference_str(full_result_dict, perturbed_result_dict, cut_date)
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
    Bars through the development end, the development periods, and the design's development context. The holdout
    start is a date on the anchor list. Its prices are not loaded.

    Args:
        design_module_in (module): Design

    Returns:
        dict: ohlcv_array_dict, period_pdf, data_context, development_end
    """
    # IMPORT THE DEVELOPMENT SPAN HERE
    from so.core.development_span import get_development_ohlcv_dict, get_development_period_pdf
    # THE EMBARGO AND THE FOLD LENGTH ARE THE DESIGN'S PERIOD RULE
    embargo_int = int(design_module_in.PERIOD_RULE["embargo_sessions"])
    train_years_int = int(max(design_module_in.PERIOD_RULE["train_years"]))
    span_dict = get_development_ohlcv_dict(embargo_int)
    period_pdf, _fold_pdf = get_development_period_pdf(span_dict["anchor_session_list"], span_dict["ohlcv_array_dict"],
                                                       embargo_int, train_years_int)
    data_context = design_module_in.get_development_data_context(span_dict["anchor_session_list"])
    return {"ohlcv_array_dict": span_dict["ohlcv_array_dict"], "period_pdf": period_pdf, "data_context": data_context,
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
    result_dict = get_audit_result_dict(design_module, loaded_dict["ohlcv_array_dict"], loaded_dict["period_pdf"],
                                        loaded_dict["data_context"], cut_count_in, loaded_dict["development_end"])
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
