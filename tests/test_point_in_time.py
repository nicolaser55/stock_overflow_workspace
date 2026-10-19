"""
Workspace Tests: point-in-time data (so.core.point_in_time; Nicolas, 2026-10-11)

Run from the workspace root:   python tests/test_point_in_time.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The registry, the ledger, the trial log and SO_DATA_PATH are temporary. The data root is a
temporary folder. records/holdout_windows.csv is not written. SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are set
only inside this file, to temporary values.
"""

import os
import sys
import types
import tempfile
import shutil
import numpy as np
import pandas as pd

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_pit_data_")
os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE SHARED MODULES
from so import paths, config
from so.core.holdout import (compute_holdout_window_dict, open_holdout_window_dict, run_holdout_evaluation,
                             get_prior_only_result_dict, get_lookahead_difference_str, get_perturbed_ohlcv_dict,
                             get_truncation_cut_date_list)
from so.core.point_in_time import (add_available_ts_pdf, add_tsbar_label_known_ts_pdf, get_as_of_pdf, get_minute_bar_available_ts, get_decision_ts,
                                   get_vix_daily_available_ts, get_derived_available_ts, get_swing_available_ts,
                                   get_cut_clock_dict, check_feature_available_ts, DataContext, register_source_dict,
                                   unregister_source, raise_if_direct_read_blocked, SOURCE_SPEC_DICT)
from so.core.raw_data import get_complete_ohlcv_pdf
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_session_decision_idx_dict
from so.features.vix_features import read_vix_daily_pdf, get_vix_prev_value_pdf
from synthetic_data import get_synthetic_ohlcv_pdf

# KEEP THE REAL REGISTRY PATHS AND POINT THE SUITE AT TEMPORARY FILES
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REAL_WINDOWS_EXISTS_BOOL = os.path.isfile(REAL_WINDOWS_PATH_STR)
REAL_WINDOWS_SIZE_INT = os.path.getsize(REAL_WINDOWS_PATH_STR) if REAL_WINDOWS_EXISTS_BOOL else None
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR
# A NEW YORK CLOCK USED BY THE SMALL FRAMES
NY = "America/New_York"

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints the passing line for one test.

    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")

# FUNCTION: A ONE-MINUTE BAR LABEL ON A FIXED MORNING
def get_label_ts(hour_int_in, minute_int_in):
    """
    2010-06-01 at the given New York hour and minute.

    Args:
        hour_int_in (int): Hour
        minute_int_in (int): Minute

    Returns:
        pd.Timestamp: Bar-start label
    """
    # RETURN THE LABEL
    return pd.Timestamp(year=2010, month=6, day=1, hour=hour_int_in, minute=minute_int_in, tz=NY)

# FUNCTION: TEST BAR AND DAILY AVAILABILITY
def test_availability():
    """
    A 15:58 bar is knowable at 15:59:00. A VIX daily bar is knowable at 16:15. 15:58:30 excludes the 15:58 bar.

    Returns:
        None
    """
    # THE 15:58 BAR ENDS AT 15:59:00, WHICH IS THE DECISION MOMENT
    label_ts = get_label_ts(15, 58)
    bar_pdf = pd.DataFrame({"timestamp": [label_ts], "open": [1.0], "high": [1.0], "low": [1.0], "close": [2.0]})
    stamped_pdf = add_available_ts_pdf("SPY_1MIN", bar_pdf)
    assert stamped_pdf["available_ts"].iloc[0] == get_label_ts(15, 59)
    assert get_decision_ts(label_ts) == get_label_ts(15, 59)
    # 15:58:30 IS STILL INSIDE THE BAR, SO THE BAR IS NOT VISIBLE YET
    hidden_pdf = get_as_of_pdf("SPY_1MIN", get_label_ts(15, 58) + pd.Timedelta(seconds=30), pdf_in=bar_pdf)
    visible_pdf = get_as_of_pdf("SPY_1MIN", get_label_ts(15, 59), pdf_in=bar_pdf)
    assert len(hidden_pdf) == 0 and len(visible_pdf) == 1 and float(visible_pdf["close"].iloc[0]) == 2.0
    # A VIX DAILY BAR DATED THAT DAY IS KNOWABLE AT 16:15
    daily_pdf = pd.DataFrame({"timestamp": [pd.Timestamp("2010-06-01", tz=NY)], "date": [pd.Timestamp("2010-06-01").date()],
                              "open": [10.0], "high": [11.0], "low": [9.0], "close": [18.0]})
    daily_stamped_pdf = add_available_ts_pdf("VIX_DAILY", daily_pdf)
    assert daily_stamped_pdf["available_ts"].iloc[0] == get_vix_daily_available_ts("2010-06-01")
    assert daily_stamped_pdf["available_ts"].iloc[0] == pd.Timestamp(year=2010, month=6, day=1, hour=16, minute=15, tz=NY)
    # A FEATURE WHOSE CLOCK IS AFTER THE DECISION IS REFUSED
    try:
        check_feature_available_ts(daily_stamped_pdf, [get_label_ts(15, 59)])
        raise AssertionError("a 16:15 feature was accepted at the 15:59 decision")
    except ValueError as error:
        assert "available_ts" in str(error)
    passed("availability (15:58 bar at 15:59:00; VIX daily at 16:15; 15:58:30 excludes the bar)")

# FUNCTION: TEST DERIVED ROWS AND A DELAYED SWING
def test_derived():
    """
    A row computed from bars up to t is knowable when the last of those bars ends. A swing confirmed k bars later waits.

    Returns:
        None
    """
    # THREE INPUT BARS: THE ROW IS KNOWABLE AT THE END OF THE THIRD
    first_ts = get_label_ts(10, 0)
    label_list = [first_ts + pd.Timedelta(minutes=offset) for offset in range(3)]
    assert get_derived_available_ts(label_list) == get_minute_bar_available_ts(label_list[-1])
    cache_pdf = pd.DataFrame({"timestamp": [label_list[-1]], "close": [5.0]})
    cache_stamped_pdf = add_available_ts_pdf("TSCTX", cache_pdf)
    assert cache_stamped_pdf["available_ts"].iloc[0] == get_derived_available_ts(label_list)
    # A SWING STORED ON ITS OWN BAR, CONFIRMED 3 BARS LATER, IS INVISIBLE UNTIL THAT CONFIRMATION BAR ENDS
    swing_pdf = pd.DataFrame({"timestamp": [first_ts], "close": [4.0], "confirm_lag_bars": [3]})
    swing_stamped_pdf = add_available_ts_pdf("TSSEG", swing_pdf)
    confirmation_ts = get_swing_available_ts(first_ts, 3)
    assert swing_stamped_pdf["available_ts"].iloc[0] == confirmation_ts
    assert confirmation_ts == get_minute_bar_available_ts(first_ts + pd.Timedelta(minutes=3))
    assert len(get_as_of_pdf("TSSEG", confirmation_ts - pd.Timedelta(seconds=1), pdf_in=swing_pdf)) == 0
    assert len(get_as_of_pdf("TSSEG", confirmation_ts, pdf_in=swing_pdf)) == 1
    passed("derived (latest input bar; swing available only after confirmation)")

# FUNCTION: TEST THAT A REVISION IS INVISIBLE UNTIL IT IS RELEASED
def test_vintage():
    """
    The revised value is hidden before its available_ts. Each date sees the value known then.

    Returns:
        None
    """
    # REGISTER A VINTAGE SOURCE FOR THIS TEST ONLY
    register_source_dict("SYNTH_MACRO", {"loader": "test", "time_zone": NY, "timestamp_convention": "release time",
                                         "availability_func": None, "revision_policy": "vintage", "vintage_key_list": ["obs_date"],
                                         "revision_reason": "test vintage", "role": "feature", "holdout": "development boundary"})
    try:
        # TWO RELEASES OF THE SAME OBSERVATION
        vintage_pdf = pd.DataFrame({"obs_date": ["2010-01-01", "2010-01-01"], "value": [1.0, 2.0],
                                    "available_ts": [pd.Timestamp("2010-02-01", tz=NY), pd.Timestamp("2010-03-01", tz=NY)]})
        before_pdf = get_as_of_pdf("SYNTH_MACRO", pd.Timestamp("2010-01-15", tz=NY), pdf_in=vintage_pdf)
        first_pdf = get_as_of_pdf("SYNTH_MACRO", pd.Timestamp("2010-02-15", tz=NY), pdf_in=vintage_pdf)
        revised_pdf = get_as_of_pdf("SYNTH_MACRO", pd.Timestamp("2010-03-15", tz=NY), pdf_in=vintage_pdf)
        # NOTHING, THEN THE FIRST PRINT, THEN THE REVISION
        assert len(before_pdf) == 0
        assert float(first_pdf["value"].iloc[0]) == 1.0
        assert float(revised_pdf["value"].iloc[0]) == 2.0
    finally:
        unregister_source("SYNTH_MACRO")
    passed("vintages (revision invisible until its available_ts)")

# FUNCTION: TEST THAT LABELS USE label_known_ts AND NOT THE FEATURE DOOR
def test_labels():
    """
    TSBAR is refused through get. get_labels returns a row only when label_known_ts is strictly before the cutoff.

    Returns:
        None
    """
    # TWO LABELS, KNOWN AT 11:00 AND AT 15:00
    early_ts = get_label_ts(11, 0)
    late_ts = get_label_ts(15, 0)
    label_pdf = pd.DataFrame({"timestamp": [get_label_ts(10, 0), get_label_ts(10, 0)], "label_known_ts": [early_ts, late_ts], "y": [1, 0]})
    context = DataContext("development", frame_dict_in={"TSBAR": label_pdf})
    # THE FEATURE DOOR REFUSES THE LABEL
    try:
        context.get("TSBAR", late_ts)
        raise AssertionError("TSBAR was returned through get")
    except ValueError as error:
        assert "get_labels" in str(error)
    # ONLY THE LABEL KNOWN STRICTLY BEFORE THE CUTOFF
    early_pdf = context.get_labels("TSBAR", late_ts)
    none_pdf = context.get_labels("TSBAR", early_ts)
    assert list(early_pdf["y"]) == [1] and len(none_pdf) == 0
    passed("labels (TSBAR refused through get; get_labels keeps label_known_ts before the cutoff)")

# FUNCTION: TEST THAT A STORED TSBAR CELL BECOMES label_known_ts
def test_tsbar_cell_clock():
    """
    Distance cells have no label_known_ts column. The row clock is the end of the latest exit bar on a synthetic
    minute index. An unresolved cell, a missing entry, and an exit past the index stay unfinished. A frame that
    already has label_known_ts or exit_ts keeps that clock.

    Returns:
        None
    """
    # FIVE MINUTE BARS, 10:00 THROUGH 10:04. THE LATEST CELL EXITS THREE BARS AFTER 10:00.
    bar_list = [get_label_ts(10, minute) for minute in range(5)]
    cell_pdf = pd.DataFrame({
        "entry_ts": [get_label_ts(10, 0), get_label_ts(10, 1), get_label_ts(10, 0), get_label_ts(11, 0)],
        "0.0010": ["1|1|TP", "1|1|TP", "1|1|TP", "1|1|TP"],
        "0.0200": ["3|1|SL", "-1|nan|NA", "9|1|TL", "1|1|TP"],
    })
    stamped_pdf = add_tsbar_label_known_ts_pdf(cell_pdf, timestamp_index_in=bar_list)
    assert pd.Timestamp(stamped_pdf["label_known_ts"].iloc[0]) == get_label_ts(10, 4)
    assert pd.Timestamp(stamped_pdf["available_ts"].iloc[0]) == get_label_ts(10, 4)
    assert pd.isna(stamped_pdf["label_known_ts"].iloc[1])
    assert pd.isna(stamped_pdf["label_known_ts"].iloc[2])
    assert pd.isna(stamped_pdf["label_known_ts"].iloc[3])
    # AN EXISTING CLOCK IS KEPT. exit_ts IS THE BAR START, KNOWABLE ONE MINUTE LATER.
    kept_pdf = add_tsbar_label_known_ts_pdf(pd.DataFrame({"label_known_ts": [get_label_ts(15, 0)], "y": [1]}))
    assert pd.Timestamp(kept_pdf["label_known_ts"].iloc[0]) == get_label_ts(15, 0)
    exit_pdf = add_tsbar_label_known_ts_pdf(pd.DataFrame({"exit_ts": [get_label_ts(10, 1)]}))
    assert pd.Timestamp(exit_pdf["label_known_ts"].iloc[0]) == get_minute_bar_available_ts(get_label_ts(10, 1))
    passed("TSBAR cells (latest exit bar; unresolved, missing and out-of-index rows stay unfinished)")

# FUNCTION: TEST THAT AN UNKNOWN SOURCE RAISES
def test_unregistered():
    """
    A name that is not in the registry cannot be read.

    Returns:
        None
    """
    # ASK FOR A NAME THAT WAS NEVER REGISTERED
    try:
        get_as_of_pdf("NOT_A_SOURCE", get_label_ts(12, 0), pdf_in=pd.DataFrame({"timestamp": [get_label_ts(12, 0)]}))
        raise AssertionError("an unregistered source was accepted")
    except ValueError as error:
        assert "Unregistered" in str(error)
    passed("unregistered source raises")

# FUNCTION: BUILD A ONE-CANDIDATE DESIGN MODULE
def get_design_module(name_str_in, candidate_func_in, path_func_in, source_name_list_in=None):
    """
    A design module the runner can hash and call.

    Args:
        name_str_in (str): Experiment name
        candidate_func_in (callable): run_candidate_replay_dict
        path_func_in (callable): run_prior_only_path_dict
        source_name_list_in (list | None): DATA_SOURCE_LIST (None = the attribute is absent)

    Returns:
        module: Design
    """
    # THE CONSTANTS THE RUNNER HASHES
    design_module = types.ModuleType(name_str_in)
    design_module.EXPERIMENT_NAME = name_str_in
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = ["constant"]
    design_module.SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}
    design_module.run_candidate_replay_dict = candidate_func_in
    design_module.run_prior_only_path_dict = path_func_in
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict, date1, date2: {"flat": 0.0}
    if source_name_list_in is not None:
        design_module.DATA_SOURCE_LIST = list(source_name_list_in)
    return design_module

# FUNCTION: A FLAT PATH WHOSE TARGET IS WHATEVER THE CALLER COMPUTED
def get_flat_path_dict(ohlcv_array_dict_in, period_pdf_in, target_arr_in):
    """
    Daily equity of 1 share of cash-free exposure, with the given target on each session of the path.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        target_arr_in (np.ndarray): Target per session position

    Returns:
        dict: Path fields the truncation test compares
    """
    # KEEP THE SESSIONS INSIDE THE PATH
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    date1 = pd.Timestamp(period_pdf_in["period_start"].iloc[0]).date()
    date2 = pd.Timestamp(period_pdf_in["period_end"].iloc[-1]).date()
    row_list, target_list, decision_list = [], [], []
    for session_idx, session_date in enumerate(session_date_list):
        if date1 <= session_date <= date2:
            row_list.append({"date": session_date, "equity": config.INITIAL_CAPITAL, "in_position": True, "weight": 1.0})
            target_list.append(float(target_arr_in[session_idx]))
            decision_list.append(session_date)
    return {"daily_equity_pdf": pd.DataFrame(row_list), "trade_pdf": pd.DataFrame(),
            "target_weight_arr": np.array(target_list, dtype=float), "decision_session_list": decision_list}

# FUNCTION: A CANDIDATE REPLAY THAT DOES NOT READ DATA
def run_dummy_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
    """
    One row of equity so the period score exists. It does not read a source.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Period bounds
        candidate_in (str): Candidate
        data_context_in: Unused

    Returns:
        dict: daily_equity_pdf, trade_pdf
    """
    # ONE SESSION AT THE PERIOD END
    return {"daily_equity_pdf": pd.DataFrame({"date": [pd.Timestamp(date2_in).date()], "equity": [config.INITIAL_CAPITAL],
                                              "in_position": [True], "weight": [1.0]}), "trade_pdf": pd.DataFrame()}

# FUNCTION: OPEN A TEMPORARY WINDOW AND BUILD SYNTHETIC BARS
def get_runner_world_dict():
    """
    Synthetic minute bars, a temporary holdout window, and the token the runner requires.

    Returns:
        dict: ohlcv_array_dict, token_path_str, results_path_str, git_dict
    """
    # BARS THROUGH THE EXAMPLE END DATE, THEN THE WINDOW THEY IMPLY
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2023-06-01", "2026-10-09", minute_vol_in=0.0004, seed_in=11)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
    proposed_dict = compute_holdout_window_dict(session_date_list)
    open_holdout_window_dict(session_date_list, f"OPEN {proposed_dict['start']} {proposed_dict['end']}", file_path_str_in=REGISTRY_PATH_STR)
    # TOKEN AND RESULTS OUTSIDE THE REAL DATA FOLDER
    token_dir_str = tempfile.mkdtemp(prefix="so_pit_token_")
    token_path_str = os.path.join(token_dir_str, "token.txt")
    with open(token_path_str, "w", encoding="utf-8") as token_file:
        token_file.write("holdout-token\n")
    os.environ["SO_HOLDOUT_PATH"] = tempfile.mkdtemp(prefix="so_pit_results_")
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
    git_dict = {"clean_bool": True, "on_main_bool": True, "preregister_bool": True, "commit_str": "abc123",
                "design_tree_str": "design-tree", "so_tree_str": "so-tree"}
    return {"ohlcv_array_dict": ohlcv_array_dict, "token_path_str": token_path_str, "git_dict": git_dict,
            "session_date_list": session_date_list}

# FUNCTION: ONE VIX DAILY ROW PER SESSION, KNOWABLE AT 16:15
def get_vix_daily_pdf(session_date_list_in):
    """
    A rising close so the same-day print and the previous print are different numbers.

    Args:
        session_date_list_in (list): Session dates

    Returns:
        pd.DataFrame: Daily bars
    """
    # CLOSE IS 10 PLUS THE SESSION NUMBER
    return pd.DataFrame({"date": list(session_date_list_in), "timestamp": [pd.Timestamp(session_date, tz=NY) for session_date in session_date_list_in],
                         "open": np.arange(len(session_date_list_in), dtype=float) + 10.0,
                         "high": np.arange(len(session_date_list_in), dtype=float) + 11.0,
                         "low": np.arange(len(session_date_list_in), dtype=float) + 9.0,
                         "close": np.arange(len(session_date_list_in), dtype=float) + 10.0})

# FUNCTION: ONE TSCTX ROW PER SESSION, ON THE FILL BAR
def get_fill_bar_cache_pdf(ohlcv_array_dict_in):
    """
    A cache row whose timestamp is the fill bar. It is knowable at the end of that bar, after the decision.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.DataFrame: timestamp, value
    """
    # THE FILL BAR OF EVERY SESSION
    fill_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict_in)["fill_idx_arr"]
    timestamp_list = [ohlcv_array_dict_in["timestamp_index"][int(fill_idx)] for fill_idx in fill_idx_arr]
    value_arr = np.arange(len(timestamp_list), dtype=float) + 100.0
    return pd.DataFrame({"timestamp": timestamp_list, "value": value_arr})

# FUNCTION: RUN ONE EVALUATION ON ITS OWN LEDGER
def run_one_evaluation(design_module_in, design_id_str_in, world_dict_in, source_frame_dict_in=None):
    """
    Evaluates one design against the temporary window.

    Args:
        design_module_in (module): Design
        design_id_str_in (str): Design id
        world_dict_in (dict): Bars, token, git probe
        source_frame_dict_in (dict | None): Extra frames

    Returns:
        dict: Ledger row
    """
    # A FRESH LEDGER AND TRIAL LOG SO DESIGNS DO NOT COLLIDE
    ledger_path_str = os.path.join(TEMP_ROOT_STR, f"{design_id_str_in}_ledger.csv")
    trial_path_str = os.path.join(TEMP_ROOT_STR, f"{design_id_str_in}_trials.csv")
    return run_holdout_evaluation(design_module_in, design_id_str_in, world_dict_in["ohlcv_array_dict"], world_dict_in["token_path_str"],
                                  world_dict_in["git_dict"], ledger_path_str_in=ledger_path_str, trial_log_path_str_in=trial_path_str,
                                  source_frame_dict_in=source_frame_dict_in)

# FUNCTION: TEST THE RUNNER GUARDS
def test_runner():
    """
    Direct loads raise. The same-day VIX close and a late cache row are invalid_lookahead. The access log is exact.

    Returns:
        None
    """
    # BUILD THE WINDOW ONCE
    world_dict = get_runner_world_dict()
    ohlcv_array_dict = world_dict["ohlcv_array_dict"]
    vix_pdf = get_vix_daily_pdf(world_dict["session_date_list"])
    cache_pdf = get_fill_bar_cache_pdf(ohlcv_array_dict)
    # A DESIGN THAT OPENS THE RAW SPY FILE
    def run_raw_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
        get_complete_ohlcv_pdf()
        return run_dummy_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in)
    raw_module = get_design_module("exp_pit_raw", run_raw_candidate_replay_dict, run_dummy_candidate_replay_dict)
    try:
        run_one_evaluation(raw_module, "raw", world_dict)
        raise AssertionError("a direct raw load was accepted")
    except ValueError as error:
        assert str(error) == "read data through the DataContext"
    # A DESIGN THAT OPENS A VIX FILE
    def run_vix_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
        read_vix_daily_pdf("vix", "2010-01-04")
        return run_dummy_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in)
    vix_loader_module = get_design_module("exp_pit_vix_loader", run_vix_candidate_replay_dict, run_dummy_candidate_replay_dict)
    try:
        run_one_evaluation(vix_loader_module, "vix_loader", world_dict)
        raise AssertionError("a direct VIX load was accepted")
    except ValueError as error:
        assert str(error) == "read data through the DataContext"
    # THE FLAG IS CLEAR AFTER THE DESIGN RETURNS
    raise_if_direct_read_blocked()
    passed("runner direct load (get_complete_ohlcv_pdf and the VIX loader raise)")
    # THE SAME SESSION'S VIX CLOSE, TAKEN AT 20:00, IS AFTER THE 15:59 DECISION
    def run_same_day_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
        # ONE READ AT 20:00 OF THE LAST SESSION IN THIS BAR SET, WHICH INCLUDES THAT SESSION'S 16:15 CLOSE
        session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
        last_date = session_date_list[-1]
        as_of_ts = pd.Timestamp(year=last_date.year, month=last_date.month, day=last_date.day, hour=20, tz=NY)
        known_pdf = data_context_in.get("VIX_DAILY", as_of_ts)
        close_dict = {pd.Timestamp(day).date(): float(close) for day, close in zip(known_pdf["date"], known_pdf["close"])}
        target_arr = np.array([close_dict.get(session_date, 0.0) for session_date in session_date_list])
        return get_flat_path_dict(ohlcv_array_dict_in, period_pdf_in, target_arr)
    leak_module = get_design_module("exp_pit_vix_leak", run_dummy_candidate_replay_dict, run_same_day_path_dict, ["SPY_1MIN", "VIX_DAILY"])
    leak_row = run_one_evaluation(leak_module, "vix_leak", world_dict, {"VIX_DAILY": vix_pdf})
    assert leak_row["status"] == "invalid_lookahead"
    # THE PERTURBATION CHECK, ON ITS OWN, ALSO CHANGES THAT CLOSE
    cut_date = get_truncation_cut_date_list(ohlcv_array_dict["session_date_list"], compute_holdout_window_dict(world_dict["session_date_list"]))[0]
    from so.core.point_in_time import get_runner_context
    full_context = get_runner_context(ohlcv_array_dict, {"VIX_DAILY": vix_pdf})
    clock_dict = get_cut_clock_dict(ohlcv_array_dict, cut_date)
    full_result_dict = get_prior_only_result_dict(leak_module, ohlcv_array_dict, compute_holdout_window_dict(world_dict["session_date_list"]), full_context)
    perturbed_context = full_context.get_perturbed_context(clock_dict["decision_ts"], int(pd.Timestamp(cut_date).strftime("%Y%m%d")), get_perturbed_ohlcv_dict(ohlcv_array_dict, cut_date))
    perturbed_result_dict = get_prior_only_result_dict(leak_module, get_perturbed_ohlcv_dict(ohlcv_array_dict, cut_date), compute_holdout_window_dict(world_dict["session_date_list"]), perturbed_context)
    perturbed_difference_str = get_lookahead_difference_str(full_result_dict, perturbed_result_dict, cut_date)
    assert perturbed_difference_str is not None
    assert "decision bar" in f"{cut_date} decision bar: {perturbed_difference_str}"
    # THE PREVIOUS SESSION'S CLOSE IS KNOWABLE AT TODAY'S DECISION AND SURVIVES BOTH CHECKS
    def run_prev_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
        # AS OF THE LAST DECISION, THE SAME-DAY 16:15 CLOSE IS NOT VISIBLE; EARLIER CLOSES ARE
        session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
        decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][-1])
        decision_ts = get_decision_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])
        data_context_in.set_decision_ts(decision_ts)
        known_pdf = data_context_in.get("VIX_DAILY", decision_ts)
        data_context_in.set_decision_ts(None)
        vix_date_list = [pd.Timestamp(day).date() for day in known_pdf["date"]]
        vix_close_arr = known_pdf["close"].to_numpy(dtype=float)
        target_arr = np.zeros(len(session_date_list))
        for session_idx, session_date in enumerate(session_date_list):
            prior_idx_list = [idx for idx, vix_date in enumerate(vix_date_list) if vix_date < session_date]
            target_arr[session_idx] = float(vix_close_arr[prior_idx_list[-1]]) if prior_idx_list else 0.0
        return get_flat_path_dict(ohlcv_array_dict_in, period_pdf_in, target_arr)
    prev_module = get_design_module("exp_pit_vix_prev", run_dummy_candidate_replay_dict, run_prev_path_dict, ["SPY_1MIN", "VIX_DAILY"])
    prev_row = run_one_evaluation(prev_module, "vix_prev", world_dict, {"VIX_DAILY": vix_pdf})
    assert prev_row["status"] == "valid"
    passed("VIX leak (same-day close invalid_lookahead; perturbation differs; vix_level_prev valid)")
    # A CACHE ROW ON THE FILL BAR IS STILL INSIDE THE SESSION, SO ONLY THE PERTURBATION CATCHES IT
    def run_cache_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
        # THE FILL-BAR ROW IS KNOWABLE AT THE SESSION END, WHICH IS AFTER THE DECISION
        fill_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict_in)["fill_idx_arr"]
        session_end_ts = get_minute_bar_available_ts(ohlcv_array_dict_in["timestamp_index"][int(ohlcv_array_dict_in["session_end_idx_arr"][-1])])
        known_pdf = data_context_in.get("TSCTX", session_end_ts)
        value_dict = {pd.Timestamp(label): float(value) for label, value in zip(known_pdf["timestamp"], known_pdf["value"])}
        target_arr = np.array([value_dict.get(pd.Timestamp(ohlcv_array_dict_in["timestamp_index"][int(fill_idx)]), 0.0) for fill_idx in fill_idx_arr])
        return get_flat_path_dict(ohlcv_array_dict_in, period_pdf_in, target_arr)
    cache_module = get_design_module("exp_pit_cache", run_dummy_candidate_replay_dict, run_cache_path_dict, ["SPY_1MIN", "TSCTX"])
    cache_row = run_one_evaluation(cache_module, "cache", world_dict, {"TSCTX": cache_pdf})
    assert cache_row["status"] == "invalid_lookahead"
    passed("cache leak (TSCTX row after the decision is invalid_lookahead)")
    # THE ACCESS LOG LISTS THE SOURCES THE DESIGN ACTUALLY READ
    def run_logged_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
        decision_ts = get_decision_ts(ohlcv_array_dict_in["timestamp_index"][int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][0])])
        data_context_in.set_decision_ts(decision_ts)
        data_context_in.get("SPY_1MIN", decision_ts)
        data_context_in.get("VIX_DAILY", decision_ts)
        data_context_in.set_decision_ts(None)
        return get_flat_path_dict(ohlcv_array_dict_in, period_pdf_in, np.ones(len(ohlcv_array_dict_in["session_date_list"])))
    logged_module = get_design_module("exp_pit_log", run_dummy_candidate_replay_dict, run_logged_path_dict, ["SPY_1MIN", "VIX_DAILY"])
    logged_row = run_one_evaluation(logged_module, "log", world_dict, {"VIX_DAILY": vix_pdf})
    assert logged_row["status"] == "valid"
    assert logged_row["sources_read"] == "SPY_1MIN,VIX_DAILY"
    passed("access log (SPY_1MIN, VIX_DAILY)")

# FUNCTION: TEST THAT THE EXISTING VIX FUNCTIONS ARE UNCHANGED FOR AN OLD CALLER
def test_vix_regression():
    """
    get_vix_prev_value_pdf and read_vix_daily_pdf return the values written into the synthetic frame.

    Returns:
        None
    """
    # THE PREVIOUS CLOSE IS THE HAND VALUE, NOT A NEW DEFINITION
    session_date_list = [pd.Timestamp("2010-06-01").date(), pd.Timestamp("2010-06-02").date(), pd.Timestamp("2010-06-03").date()]
    daily_pdf = pd.DataFrame({"date": session_date_list, "close": [10.0, 12.0, 11.0]})
    prev_pdf = get_vix_prev_value_pdf(session_date_list, daily_pdf, "2005-10-03")
    assert float(prev_pdf["value"].iloc[1]) == 10.0 and float(prev_pdf["value"].iloc[2]) == 12.0
    # A ONE-ROW YEAR FILE COMES BACK WITH THE CLOSE THAT WAS WRITTEN
    folder_str = os.path.join(TEMP_ROOT_STR, "vix_daily").replace("\\", "/") + "/"
    os.makedirs(folder_str, exist_ok=True)
    raw_pdf = pd.DataFrame({"timestamp": ["2010-06-01 04:00:00+00:00"], "open": [17.0], "high": [18.0], "low": [16.0],
                            "close": [17.25], "volume": [0], "created_ts": ["2010-06-01 20:00:00+00:00"], "date": ["2010-06-01"]})
    raw_pdf.to_csv(os.path.join(folder_str, "ohlcv_data_2010.csv"), index=False)
    loaded_pdf = read_vix_daily_pdf("vix", "2010-06-15", raw_path_str_in=folder_str, enforce_holdout_bool_in=False)
    again_pdf = read_vix_daily_pdf("vix", "2010-06-15", raw_path_str_in=folder_str, enforce_holdout_bool_in=False)
    assert float(loaded_pdf["close"].iloc[0]) == 17.25 and float(again_pdf["close"].iloc[0]) == 17.25
    passed("VIX regression (previous close and the loaded close match the file)")

# FUNCTION: WRITE ONE RAW SPY FILE, INCLUDING A BAR AFTER THE WINDOW
def write_spy_file_with_forward_bar(ohlcv_pdf_in, forward_date_in):
    """
    Writes the synthetic bars plus one bar on forward_date_in into the temporary raw folder.

    Args:
        ohlcv_pdf_in (pd.DataFrame): Synthetic minute bars
        forward_date_in (datetime.date): A session after the window end

    Returns:
        None
    """
    # ONE BAR ON THE FORWARD DATE, THEN UTC STRINGS THE RAW LOADER PARSES
    forward_ts = pd.Timestamp(year=forward_date_in.year, month=forward_date_in.month, day=forward_date_in.day, hour=14, minute=30, tz="UTC")
    extra_pdf = pd.DataFrame({"timestamp": [forward_ts], "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.0], "volume": [1000], "date": [forward_date_in]})
    full_pdf = pd.concat([ohlcv_pdf_in, extra_pdf], ignore_index=True)
    raw_pdf = pd.DataFrame({"timestamp": pd.to_datetime(full_pdf["timestamp"], utc=True).dt.strftime("%Y-%m-%d %H:%M:%S+00:00"),
                            "open": full_pdf["open"], "high": full_pdf["high"], "low": full_pdf["low"], "close": full_pdf["close"], "volume": full_pdf["volume"]})
    os.makedirs(paths.LOCAL_OHLCV_DATA_FILE_PATH_STR, exist_ok=True)
    raw_pdf.to_csv(paths.LOCAL_OHLCV_DATA_FILE_PATH_STR + "ohlcv_data_synthetic.csv", index=False)

# FUNCTION: WRITE VIX DAILY YEAR FILES, INCLUDING A CLOSE AFTER THE WINDOW
def write_vix_files_with_forward_row(session_date_list_in, forward_date_in):
    """
    One daily row per session (close 10 + index) and one row on forward_date_in with close 999, in the year files.

    Args:
        session_date_list_in (list): Session dates inside the series used to open the window
        forward_date_in (datetime.date): A date after the window end

    Returns:
        None
    """
    # MIDNIGHT NEW YORK, STORED AS UTC, WHICH IS WHAT THE DAILY LOADER REQUIRES
    row_list = []
    for session_idx, session_date in enumerate(list(session_date_list_in) + [forward_date_in]):
        stamp_ts = pd.Timestamp(session_date).tz_localize(NY).tz_convert("UTC")
        close_float = 999.0 if session_date == forward_date_in else float(session_idx) + 10.0
        row_list.append({"timestamp": stamp_ts.strftime("%Y-%m-%d %H:%M:%S+00:00"), "open": close_float, "high": close_float + 1.0,
                         "low": close_float - 1.0, "close": close_float, "volume": 0,
                         "created_ts": stamp_ts.strftime("%Y-%m-%d %H:%M:%S+00:00"), "date": str(session_date)})
    raw_pdf = pd.DataFrame(row_list)
    os.makedirs(paths.LOCAL_VIX_DAILY_DATA_FILE_PATH_STR, exist_ok=True)
    for year_str, year_pdf in raw_pdf.groupby(raw_pdf["date"].str.slice(0, 4)):
        year_pdf.to_csv(paths.LOCAL_VIX_DAILY_DATA_FILE_PATH_STR + f"ohlcv_data_{year_str}.csv", index=False)

# FUNCTION: LOAD THE EVALUATION SCRIPT WITHOUT RUNNING IT
def get_evaluate_script_module():
    """
    Imports scripts/holdout_evaluate.py so the test can call its loaders. The script's __main__ is not executed.

    Returns:
        module: The evaluation script
    """
    # LOAD BY PATH (scripts/ IS NOT A PACKAGE)
    import importlib.util
    script_path_str = os.path.join(WORKSPACE_PATH_STR, "scripts", "holdout_evaluate.py")
    script_spec = importlib.util.spec_from_file_location("holdout_evaluate_e2e", script_path_str)
    script_module = importlib.util.module_from_spec(script_spec)
    script_spec.loader.exec_module(script_module)
    return script_module

# FUNCTION: TEST DECLARED SOURCES ON A SYNTHETIC EVALUATION
def test_declared_load():
    """
    Fake SPY and VIX files, a temporary window, a token and injected git. vix_level_prev is valid. The same-session
    close is invalid_lookahead. An undeclared read is invalid_undeclared. An unregistered declaration raises and
    writes no ledger row. A row after the window end never reaches the loaded frame or the context.

    Returns:
        None
    """
    # A SEPARATE REGISTRY SO THE EARLIER RUNNER WINDOW STAYS WHERE IT IS
    saved_registry_str = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    registry_path_str = os.path.join(TEMP_ROOT_STR, "e2e_windows.csv")
    paths.HOLDOUT_WINDOWS_FILE_PATH_STR = registry_path_str
    try:
        # BARS THROUGH MID-2025, THEN THE WINDOW THEY IMPLY (THE FORWARD BAR IS NOT PART OF THIS CALENDAR)
        ohlcv_pdf = get_synthetic_ohlcv_pdf("2022-01-03", "2025-06-30", minute_vol_in=0.0004, seed_in=12)
        session_date_list = sorted({pd.Timestamp(session_date).date() for session_date in ohlcv_pdf["date"]})
        proposed_dict = compute_holdout_window_dict(session_date_list)
        open_holdout_window_dict(session_date_list, f"OPEN {proposed_dict['start']} {proposed_dict['end']}", file_path_str_in=registry_path_str)
        from so.core.holdout import get_active_holdout_window_dict, get_date, get_runner_active_bool
        end_date = get_date(get_active_holdout_window_dict()["end"])
        forward_date = (pd.Timestamp(end_date) + pd.Timedelta(days=14)).date()
        assert forward_date > end_date and forward_date.year == end_date.year
        # WRITE THE FILES, INCLUDING THE FORWARD SPY BAR AND THE FORWARD VIX CLOSE OF 999
        write_spy_file_with_forward_bar(ohlcv_pdf, forward_date)
        write_vix_files_with_forward_row(session_date_list, forward_date)
        token_path_str = os.path.join(tempfile.mkdtemp(prefix="so_pit_e2e_token_"), "token.txt")
        with open(token_path_str, "w", encoding="utf-8") as token_file:
            token_file.write("holdout-token\n")
        os.environ["SO_HOLDOUT_PATH"] = tempfile.mkdtemp(prefix="so_pit_e2e_results_")
        os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "holdout-token"
        git_dict = {"clean_bool": True, "on_main_bool": True, "preregister_bool": True, "commit_str": "abc123",
                    "design_tree_str": "e2e-design-tree", "so_tree_str": "e2e-so-tree"}
        # THE PREVIOUS SESSION'S CLOSE, READ THROUGH THE CONTEXT
        def run_prev_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
            session_dates = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
            decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][-1])
            decision_ts = get_decision_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])
            data_context_in.set_decision_ts(decision_ts)
            known_pdf = data_context_in.get("VIX_DAILY", decision_ts)
            data_context_in.set_decision_ts(None)
            vix_date_list = [pd.Timestamp(day).date() for day in known_pdf["date"]]
            vix_close_arr = known_pdf["close"].to_numpy(dtype=float)
            target_arr = np.zeros(len(session_dates))
            for session_idx, session_date in enumerate(session_dates):
                prior_idx_list = [idx for idx, vix_date in enumerate(vix_date_list) if vix_date < session_date]
                target_arr[session_idx] = float(vix_close_arr[prior_idx_list[-1]]) if prior_idx_list else 0.0
            return get_flat_path_dict(ohlcv_array_dict_in, period_pdf_in, target_arr)
        # THE SAME SESSION'S CLOSE, TAKEN AT 20:00
        def run_same_day_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
            session_dates = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
            last_date = session_dates[-1]
            as_of_ts = pd.Timestamp(year=last_date.year, month=last_date.month, day=last_date.day, hour=20, tz=NY)
            known_pdf = data_context_in.get("VIX_DAILY", as_of_ts)
            close_dict = {pd.Timestamp(day).date(): float(close) for day, close in zip(known_pdf["date"], known_pdf["close"])}
            target_arr = np.array([close_dict.get(session_date, 0.0) for session_date in session_dates])
            return get_flat_path_dict(ohlcv_array_dict_in, period_pdf_in, target_arr)
        # A READ OF VIX BY A DESIGN THAT DECLARED ONLY SPY
        def run_undeclared_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
            decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][0])
            decision_ts = get_decision_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])
            data_context_in.get("VIX_DAILY", decision_ts)
            return get_flat_path_dict(ohlcv_array_dict_in, period_pdf_in, np.ones(len(ohlcv_array_dict_in["session_date_list"])))
        prev_module = get_design_module("exp_pit_e2e_prev", run_dummy_candidate_replay_dict, run_prev_path_dict, ["SPY_1MIN", "VIX_DAILY"])
        leak_module = get_design_module("exp_pit_e2e_leak", run_dummy_candidate_replay_dict, run_same_day_path_dict, ["SPY_1MIN", "VIX_DAILY"])
        undeclared_module = get_design_module("exp_pit_e2e_undeclared", run_dummy_candidate_replay_dict, run_undeclared_path_dict, ["SPY_1MIN"])
        bad_module = get_design_module("exp_pit_e2e_bad", run_dummy_candidate_replay_dict, run_undeclared_path_dict, ["NOT_A_SOURCE"])
        # THE SCRIPT LOADS THE DECLARED SOURCES; ITS __main__ IS NOT RUN
        evaluate_module = get_evaluate_script_module()
        frame_dict = evaluate_module.get_evaluation_frame_dict(prev_module)
        ohlcv_array_dict = get_ohlcv_array_dict(frame_dict["SPY_1MIN"])
        assert get_runner_active_bool() is False
        # THE FORWARD VIX CLOSE AND THE FORWARD SPY BAR ARE NOT IN THE FRAMES
        vix_date_list = [pd.Timestamp(day).date() for day in frame_dict["VIX_DAILY"]["date"]]
        spy_date_list = [pd.Timestamp(day).date() for day in ohlcv_array_dict["session_date_list"]]
        assert forward_date not in vix_date_list and forward_date not in spy_date_list
        assert 999.0 not in set(frame_dict["VIX_DAILY"]["close"].astype(float))
        assert max(vix_date_list) <= end_date and max(spy_date_list) <= end_date
        # THE SAME ABSENCE INSIDE A CONTEXT BUILT FROM THOSE FRAMES
        from so.core.point_in_time import get_runner_context, get_minute_bar_available_ts
        limit_ts = get_minute_bar_available_ts(ohlcv_array_dict["timestamp_index"][-1])
        context = get_runner_context(ohlcv_array_dict, {"VIX_DAILY": frame_dict["VIX_DAILY"]}, limit_ts, ["SPY_1MIN", "VIX_DAILY"])
        visible_pdf = context.get("VIX_DAILY", pd.Timestamp("2099-01-01", tz=NY))
        visible_date_list = [pd.Timestamp(day).date() for day in visible_pdf["date"]]
        assert forward_date not in visible_date_list and 999.0 not in set(visible_pdf["close"].astype(float))
        passed("forward data after the window end never reaches the context")
        # AN UNREGISTERED NAME RAISES BEFORE THE REPLAY AND WRITES NO LEDGER ROW
        bad_ledger_str = os.path.join(TEMP_ROOT_STR, "e2e_bad_ledger.csv")
        try:
            run_holdout_evaluation(bad_module, "e2e_bad", ohlcv_array_dict, token_path_str, git_dict,
                                   ledger_path_str_in=bad_ledger_str, trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "e2e_bad_trials.csv"),
                                   source_frame_dict_in={"VIX_DAILY": frame_dict["VIX_DAILY"]})
            raise AssertionError("an unregistered source was accepted")
        except ValueError as error:
            assert "Unregistered" in str(error)
        assert not os.path.isfile(bad_ledger_str)
        passed("unregistered DATA_SOURCE_LIST refused (no ledger row)")
        # A DESIGN THAT READS VIX WITHOUT DECLARING IT IS NOT VALID AND WRITES NO PATH
        undeclared_row = run_holdout_evaluation(undeclared_module, "e2e_undeclared", ohlcv_array_dict, token_path_str, git_dict,
                                                ledger_path_str_in=os.path.join(TEMP_ROOT_STR, "e2e_undeclared_ledger.csv"),
                                                trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "e2e_undeclared_trials.csv"),
                                                source_frame_dict_in={"VIX_DAILY": frame_dict["VIX_DAILY"]})
        assert undeclared_row["status"] == "invalid_undeclared"
        assert "VIX_DAILY" in undeclared_row["sources_read"]
        equity_path_str = os.path.join(os.environ["SO_HOLDOUT_PATH"], undeclared_row["window_id"], "e2e_undeclared", "strategy_daily_equity.csv")
        assert not os.path.isfile(equity_path_str)
        passed("undeclared source refused (invalid_undeclared, no daily path)")
        # THE SAME-SESSION CLOSE, LOADED FROM THE FILE, IS A LEAK
        leak_row = run_holdout_evaluation(leak_module, "e2e_leak", ohlcv_array_dict, token_path_str, git_dict,
                                          ledger_path_str_in=os.path.join(TEMP_ROOT_STR, "e2e_leak_ledger.csv"),
                                          trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "e2e_leak_trials.csv"),
                                          source_frame_dict_in={"SPY_1MIN": frame_dict["SPY_1MIN"], "VIX_DAILY": frame_dict["VIX_DAILY"]})
        assert leak_row["status"] == "invalid_lookahead"
        passed("same-session VIX close is invalid_lookahead")
        # THE PREVIOUS CLOSE, LOADED FROM THE FILE, IS VALID
        prev_row = run_holdout_evaluation(prev_module, "e2e_prev", ohlcv_array_dict, token_path_str, git_dict,
                                          ledger_path_str_in=os.path.join(TEMP_ROOT_STR, "e2e_prev_ledger.csv"),
                                          trial_log_path_str_in=os.path.join(TEMP_ROOT_STR, "e2e_prev_trials.csv"),
                                          source_frame_dict_in={"SPY_1MIN": frame_dict["SPY_1MIN"], "VIX_DAILY": frame_dict["VIX_DAILY"]})
        assert prev_row["status"] == "valid"
        assert "VIX_DAILY" in prev_row["sources_read"]
        passed("vix_level_prev loaded through the evaluation script is valid")
    finally:
        # PUT THE EARLIER REGISTRY BACK
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = saved_registry_str

# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY FOLDERS
    try:
        test_availability()
        test_derived()
        test_vintage()
        test_labels()
        test_tsbar_cell_clock()
        test_unregistered()
        test_vix_regression()
        test_runner()
        test_declared_load()
        assert os.path.isfile(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_EXISTS_BOOL
        if REAL_WINDOWS_EXISTS_BOOL:
            assert os.path.getsize(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_SIZE_INT
        assert "SYNTH_MACRO" not in SOURCE_SPEC_DICT
        print("\nAll point-in-time tests passed ✅")
    finally:
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
