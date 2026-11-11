"""
Workspace Tests: intraday decision times in daily mode (so.runner.intraday; step R4c, 2026-11-11)

Run from the workspace root:   python tests/test_runner_intraday.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The data root is a temporary folder. records/holdout_windows.csv is not written.
SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set. No real-data run.
"""

import os
import sys
import json
import types
import shutil
import tempfile
import numpy as np
import pandas as pd

# FORCE UTF-8 SO THE PASS MARK PRINTS ON A WINDOWS CONSOLE
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
_CURRENT_DATA_PATH_STR = os.environ.get("SO_DATA_PATH", "").strip()
_TEMP_DIR_STR = os.path.normcase(os.path.abspath(tempfile.gettempdir()))
OWNED_TEMP_BOOL = False
if _CURRENT_DATA_PATH_STR and os.path.normcase(os.path.abspath(_CURRENT_DATA_PATH_STR)).startswith(_TEMP_DIR_STR + os.sep):
    TEMP_ROOT_STR = _CURRENT_DATA_PATH_STR
else:
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_intraday_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()

from so import config, paths
from so.core.trade_execution import get_ohlcv_array_dict, calculate_side_fee, get_affordable_share_count
from so.core.backtest_simulation import get_session_first_entry_idx
from so.core.reentry_simulation import get_window_session_idx_arr
from so.features.daily_features import get_session_decision_idx_dict
from so.runner import run_daily_dict, run_development_dict, run_engine_decisions_dict, TrailingStopEngine
from so.runner.engine import DECISION_KEY_LIST
from so.runner.loop import DailyLoop, get_stream_loop, fill_bar_buffer_through_decision
from so.runner.view import get_sliced_bar_array_dict
from so.runner.intraday import (INTRADAY_LIST_KEY_STR, get_validated_time_tuple, get_stream_intraday_time_tuple,
                                get_session_call_list, get_intraday_pattern_list, get_random_pattern_list,
                                get_pattern_equal_bool, get_base_pattern)
from so.runner.baselines import get_runner_baseline_dict
from so.runner.lookahead import INTRADAY_KIND_STR_LIST, KIND_STR_LIST, get_decision_equal_bool
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_intraday_design as intraday_design
import runner_candidate_design as cand_design

# KEEP THE REAL REGISTRY PATH AND POINT THIS SUITE AT A TEMPORARY FILE
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR


# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")


# FUNCTION: SYNTHETIC BAR ARRAYS
def get_ohlcv_dict(date1_str_in, date2_str_in, seed_in=4, drop_ts_list_in=None):
    """
    Args:
        date1_str_in, date2_str_in (str): Span
        seed_in (int): Seed
        drop_ts_list_in (list | None): Bar timestamps ("YYYY-MM-DD HH:MM", New York) to remove

    Returns:
        dict: Bar arrays
    """
    # THE REAL NYSE CALENDAR, HALF DAYS INCLUDED
    ohlcv_pdf = get_synthetic_ohlcv_pdf(date1_str_in, date2_str_in, seed_in=seed_in)
    for ts_str in list(drop_ts_list_in or []):
        drop_ts = pd.Timestamp(ts_str, tz="America/New_York")
        ohlcv_pdf = ohlcv_pdf[ohlcv_pdf["timestamp"] != drop_ts].reset_index(drop=True)
    return get_ohlcv_array_dict(ohlcv_pdf)


# FUNCTION: THREE INJECTED PERIODS
def get_injected_period_pdf(session_date_list_in):
    """
    Args:
        session_date_list_in (list): Session dates (at least 12)

    Returns:
        pd.DataFrame: period_id, period_start, period_end, session_count, valid_start, valid_end
    """
    # THREE CONTIGUOUS PERIODS
    session_date_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in]
    assert len(session_date_list) >= 12
    bound_list = [(0, 3), (4, 7), (8, len(session_date_list) - 1)]
    row_dict_list = []
    for period_id, (start_idx, end_idx) in enumerate(bound_list):
        start_date, end_date = session_date_list[start_idx], session_date_list[end_idx]
        row_dict_list.append({"period_id": period_id, "period_start": start_date, "period_end": end_date,
                              "session_count": int(end_idx - start_idx + 1), "valid_start": start_date,
                              "valid_end": end_date})
    return pd.DataFrame(row_dict_list)


# FUNCTION: A TRIAL-LOG PATH INSIDE THE TEMPORARY DATA ROOT
def get_test_trial_log_path_str(file_name_str_in):
    """
    Args:
        file_name_str_in (str): File name

    Returns:
        str: CSV path
    """
    # THE FOLDER IS CREATED HERE
    folder_str = os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "runner_intraday_test")
    os.makedirs(folder_str, exist_ok=True)
    return os.path.join(folder_str, file_name_str_in)


# FUNCTION: A DEVELOPMENT RUN OF THE INTRADAY DESIGN ON A SHORT SPAN
def run_intraday_development_dict(run_id_str_in, trial_file_str_in, seed_count_int_in=4, crash_after_period_id_in=None):
    """
    Args:
        run_id_str_in (str): Run id
        trial_file_str_in (str): Trial log file name
        seed_count_int_in (int): Random-timing draws
        crash_after_period_id_in (int | None): Crash hook

    Returns:
        dict: run_development_dict output plus ohlcv_array_dict
    """
    # IN-PROCESS SO A PATCH ON THE RUNNER STAYS VISIBLE
    ohlcv_array_dict = get_ohlcv_dict("2010-06-01", "2010-06-22", seed_in=4)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    result_dict = run_development_dict(intraday_design, ohlcv_array_dict, run_id_str_in=run_id_str_in, n_jobs_int_in=1,
                                       period_pdf_in=period_pdf,
                                       trial_log_path_str_in=get_test_trial_log_path_str(trial_file_str_in),
                                       commit_str_in="testcommit", code_hash_str_in="testhash",
                                       check_clean_tree_bool_in=False, check_view_bool_in=False,
                                       baseline_seed_count_int_in=seed_count_int_in,
                                       crash_after_period_id_in=crash_after_period_id_in)
    result_dict["ohlcv_array_dict"] = ohlcv_array_dict
    return result_dict


# CLASS: A ONE-RULE DESIGN FOR run_daily_dict
class TimedDesign:
    """intraday_func(view) at the intraday calls, daily_value at 15:58."""

    DATA_SOURCE_LIST = ["SPY_1MIN"]

    def __init__(self, time_list_in, intraday_func_in, daily_value_in=1.0):
        self.INTRADAY_DECISION_TIME_LIST = list(time_list_in)
        self.intraday_func = intraday_func_in
        self.daily_value = daily_value_in

    def decide(self, view_in):
        if view_in.intraday_time_str is None:
            return self.daily_value
        return self.intraday_func(view_in)


# FUNCTION: THE LIST OF TIMES IS CHECKED
def test_time_list_validation():
    """
    Sorted, unique, HH:MM, 10:00 through 15:57, at most 32. None and [] are no times.

    Returns:
        None
    """
    # ACCEPTED
    assert get_validated_time_tuple(["15:30"]) == ("15:30",)
    assert get_validated_time_tuple(["10:00", "12:00", "15:57"]) == ("10:00", "12:00", "15:57")
    assert get_validated_time_tuple(None) == () and get_validated_time_tuple([]) == ()
    # REFUSED
    for bad_value in [["15:30", "12:00"], ["12:00", "12:00"], ["09:59"], ["15:58"], ["1530"], ["24:00"], "15:30",
                      [f"{10 + idx // 60}:{idx % 60:02d}" for idx in range(33)]]:
        try:
            get_validated_time_tuple(bad_value)
            raise AssertionError(f"accepted {bad_value!r}")
        except ValueError:
            pass
    passed("intraday times: sorted, unique, HH:MM, 10:00..15:57, at most 32; anything else refused")


# FUNCTION: THE MAPPING OF TIMES TO BARS
def test_time_mapping_early_close_and_missing_bar():
    """
    A time maps to the last bar at or before it (a missing 15:30 bar maps to 15:29). An early close (13:00) has no
    15:30 call but keeps its 12:00 call. A design without times has no intraday record key.

    Returns:
        None
    """
    # 2010-11-26 CLOSES AT 13:00; 2010-11-29 LOSES ITS 15:30 BAR
    ohlcv_array_dict = get_ohlcv_dict("2010-11-22", "2010-12-03", seed_in=2, drop_ts_list_in=["2010-11-29 15:30"])
    decision_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict)["decision_idx_arr"]
    session_day_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
    half_idx = session_day_list.index(pd.Timestamp("2010-11-26").date())
    missing_idx = session_day_list.index(pd.Timestamp("2010-11-29").date())
    time_tuple = ("12:00", "15:30")
    half_call_list = get_session_call_list(ohlcv_array_dict, half_idx, time_tuple, int(decision_idx_arr[half_idx]),
                                           get_session_first_entry_idx(ohlcv_array_dict, half_idx))
    assert [time_str for time_str, _bar in half_call_list] == ["12:00"]
    missing_call_list = get_session_call_list(ohlcv_array_dict, missing_idx, time_tuple, int(decision_idx_arr[missing_idx]),
                                              get_session_first_entry_idx(ohlcv_array_dict, missing_idx))
    bar_ts = ohlcv_array_dict["timestamp_index"][missing_call_list[-1][1]]
    assert missing_call_list[-1][0] == "15:30" and (bar_ts.hour, bar_ts.minute) == (15, 29)
    # THE RECORDS FOLLOW THE CALLS; THE LAST SESSION HAS NONE
    seen_list = []
    def record_func(view_in):
        seen_list.append((pd.Timestamp(view_in.session_date).date(), view_in.intraday_time_str, view_in.decision_ts))
        return None
    date1, date2 = session_day_list[0], session_day_list[-1]
    result_dict = run_daily_dict(TimedDesign(list(time_tuple), record_func), ohlcv_array_dict, date1, date2)
    record_dict = {pd.Timestamp(session_date).date(): decision_dict
                   for session_date, decision_dict in zip(result_dict["decision_session_list"], result_dict["decision_dict_list"])}
    assert [entry[0] for entry in record_dict[session_day_list[half_idx]][INTRADAY_LIST_KEY_STR]] == ["12:00"]
    assert INTRADAY_LIST_KEY_STR not in record_dict[session_day_list[-1]]
    missing_seen = [entry for entry in seen_list if entry[0] == session_day_list[missing_idx] and entry[1] == "15:30"]
    assert len(missing_seen) == 1 and (missing_seen[0][2].hour, missing_seen[0][2].minute) == (15, 30)
    # A DAILY-ONLY DESIGN RECORDS EXACTLY THE OLD KEYS
    daily_dict = run_daily_dict(cand_design.WeightDesign(1.0), ohlcv_array_dict, date1, date2)
    assert all(set(decision_dict) == set(DECISION_KEY_LIST) for decision_dict in daily_dict["decision_dict_list"])
    replay_dict = run_engine_decisions_dict(ohlcv_array_dict, date1, date2, daily_dict["decision_dict_list"])
    assert "intraday_skip_count" not in replay_dict
    passed("time mapping: missing bar -> previous bar, early close -> no 15:30 call, last session no call, daily-only records unchanged")


# FUNCTION: "KEEP" AT EVERY INTRADAY CALL EQUALS THE DAILY DESIGN
def test_keep_equals_daily():
    """
    A design that says keep at every intraday call trades exactly like the same design without intraday times.

    Returns:
        None
    """
    # THE SAME SPAN, TWO DESIGNS
    ohlcv_array_dict = get_ohlcv_dict("2010-06-01", "2010-06-22", seed_in=5)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    keep_dict = run_daily_dict(TimedDesign(["10:30", "15:30"], lambda view_in: float("nan"), 0.6), ohlcv_array_dict,
                               date1, date2, initial_weight_in=1.0)
    daily_dict = run_daily_dict(cand_design.WeightDesign(0.6), ohlcv_array_dict, date1, date2, initial_weight_in=1.0)
    assert np.array_equal(keep_dict["daily_equity_pdf"]["equity"].to_numpy(), daily_dict["daily_equity_pdf"]["equity"].to_numpy())
    assert len(keep_dict["trade_pdf"]) == len(daily_dict["trade_pdf"])
    assert all(len(decision_dict.get(INTRADAY_LIST_KEY_STR, ())) == 2 for decision_dict in keep_dict["decision_dict_list"][:-1])
    passed("keep at every intraday call equals the daily-only design exactly")


# FUNCTION: SELL AT 15:30, BUY AT 15:58: THE HAND-COMPUTED PATH
def test_sell_and_buy_back_hand_path():
    """
    Every session: sell everything at the 15:31 open (the bar after 15:30), buy back at the 15:59 open. The equity
    equals a hand computation with the shared fee and share-count rules; the replay of the recorded decisions equals the
    live stream.

    Returns:
        None
    """
    # THE LIVE STREAM
    ohlcv_array_dict = get_ohlcv_dict("2010-06-01", "2010-06-15", seed_in=6)
    session_date_list = list(ohlcv_array_dict["session_date_list"])
    date1, date2 = session_date_list[0], session_date_list[-1]
    live_dict = run_daily_dict(TimedDesign(["15:30"], lambda view_in: 0.0, 1.0), ohlcv_array_dict, date1, date2,
                               initial_weight_in=1.0, dead_band_in=0.0)
    # THE HAND COMPUTATION
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
    open_arr, close_arr = ohlcv_array_dict["open_arr"], ohlcv_array_dict["close_arr"]
    entry_slip, exit_slip = float(config.ENTRY_SLIPPAGE_PER_SHARE), float(config.MARKET_EXIT_SLIPPAGE_PER_SHARE)
    window_idx_arr = get_window_session_idx_arr(ohlcv_array_dict, date1, date2)
    cash_float, share_int = float(config.INITIAL_CAPITAL), 0
    def buy(raw_price_in):
        nonlocal cash_float, share_int
        fill_float = float(raw_price_in) + entry_slip
        count_int = get_affordable_share_count(cash_float, fill_float)
        cash_float -= count_int * fill_float + calculate_side_fee(count_int, fill_float)
        share_int += count_int
    def sell(raw_price_in):
        nonlocal cash_float, share_int
        if share_int == 0:
            return
        fill_float = float(raw_price_in) - exit_slip
        cash_float += share_int * fill_float - calculate_side_fee(share_int, fill_float)
        share_int = 0
    first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict, int(window_idx_arr[0]))
    buy(open_arr[first_entry_idx])
    expected_sell_idx_list = []
    for session_pos, session_idx in enumerate(window_idx_arr):
        session_idx = int(session_idx)
        if session_pos == len(window_idx_arr) - 1:
            sell(close_arr[int(ohlcv_array_dict["session_end_idx_arr"][session_idx])])
            continue
        call_list = get_session_call_list(ohlcv_array_dict, session_idx, ("15:30",), int(idx_dict["decision_idx_arr"][session_idx]),
                                          get_session_first_entry_idx(ohlcv_array_dict, session_idx))
        sell_idx = call_list[0][1] + 1
        expected_sell_idx_list.append(sell_idx)
        sell(open_arr[sell_idx])
        buy(open_arr[int(idx_dict["fill_idx_arr"][session_idx])])
    assert abs(float(live_dict["daily_equity_pdf"]["equity"].iloc[-1]) - cash_float) < 1e-6
    trade_pdf = live_dict["trade_pdf"]
    sell_pdf = trade_pdf[(trade_pdf["delta_share_count"] < 0) & (trade_pdf["reason"] == "rebalance")]
    assert sell_pdf["trade_idx"].astype(int).tolist() == expected_sell_idx_list
    assert np.array_equal(sell_pdf["raw_price"].to_numpy(dtype=float), open_arr[expected_sell_idx_list].astype(float))
    # THE REPLAY OF THE RECORDED DECISIONS IS THE SAME PATH
    replay_dict = run_engine_decisions_dict(ohlcv_array_dict, date1, date2, live_dict["decision_dict_list"],
                                            initial_weight_in=1.0, dead_band_in=0.0)
    assert np.array_equal(replay_dict["daily_equity_pdf"]["equity"].to_numpy(), live_dict["daily_equity_pdf"]["equity"].to_numpy())
    assert replay_dict["intraday_skip_count"] == 0
    passed("sell at 15:31 and buy at 15:59: equity equals the hand computation, fills at the bar after the call, replay equals live")


# FUNCTION: THE REFUSALS
def test_refusals():
    """
    A non-fractional engine with intraday times, a design that returns the intraday record key, an intraday call that
    sets a non-weight field, a module and class that declare different times, minute mode with times, and a strict
    replay of an entry that does not map are all refused.

    Returns:
        None
    """
    # A SHORT SPAN
    ohlcv_array_dict = get_ohlcv_dict("2010-06-01", "2010-06-08", seed_in=7)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    def expect_value_error(func_in, text_str_in):
        try:
            func_in()
        except ValueError as error:
            assert text_str_in in str(error), str(error)
            return
        raise AssertionError(f"not refused: {text_str_in}")
    expect_value_error(lambda: DailyLoop(TimedDesign(["15:30"], lambda view_in: None), ohlcv_array_dict, date1, date2,
                                         engine_in=TrailingStopEngine(None)), "fractional engine")
    class InjectingDesign(TimedDesign):
        def decide(self, view_in):
            if view_in.intraday_time_str is None:
                return {"target_weight": 1.0, INTRADAY_LIST_KEY_STR: (("15:30", 0.0),)}
            return None
    expect_value_error(lambda: run_daily_dict(InjectingDesign(["15:30"], None), ohlcv_array_dict, date1, date2),
                       "only the runner writes it")
    expect_value_error(lambda: run_daily_dict(TimedDesign(["15:30"], lambda view_in: {"target_weight": 0.0, "stop_price": 90.0}),
                                              ohlcv_array_dict, date1, date2), "only target_weight is allowed")
    module_ns = types.SimpleNamespace(INTRADAY_DECISION_TIME_LIST=["12:00"])
    expect_value_error(lambda: get_stream_intraday_time_tuple(TimedDesign(["15:30"], None), module_ns), "differs")
    minute_ns = types.SimpleNamespace(MODE="minute", INTRADAY_DECISION_TIME_LIST=["15:30"])
    expect_value_error(lambda: get_stream_loop(TimedDesign(["15:30"], None), ohlcv_array_dict, date1, date2,
                                               check_source_bool_in=False, design_module_in=minute_ns), "daily-mode")
    bad_list = [{"target_weight": 1.0, INTRADAY_LIST_KEY_STR: (("15:30", 0.0),)} for _session in ohlcv_array_dict["session_date_list"]]
    bad_list[1] = {"target_weight": 1.0, INTRADAY_LIST_KEY_STR: (("09:00", 0.0),)}
    bad_list[-1] = {"target_weight": float("nan")}
    expect_value_error(lambda: run_engine_decisions_dict(ohlcv_array_dict, date1, date2, bad_list), "maps to no bar")
    lenient_dict = run_engine_decisions_dict(ohlcv_array_dict, date1, date2, bad_list, lenient_intraday_bool_in=True)
    assert lenient_dict["intraday_skip_count"] == 1
    passed("refused: non-fractional engine, injected intraday record, non-weight intraday field, module/class mismatch, minute mode, strict unmapped replay")


# FUNCTION: A FULL DEVELOPMENT RUN, ITS BASELINES AND A RESUME
def test_development_run_baselines_and_resume():
    """
    The three candidates run end to end: the look-ahead check passes with intraday cuts present, the baselines use
    patterns and the bar-weighted mean weight, and a run killed after the first period resumes to the same path.

    Returns:
        None
    """
    # A CLEAN RUN
    clean_dict = run_intraday_development_dict("intraday_clean", "clean.csv")
    lookahead_dict = clean_dict["lookahead_dict"]
    assert lookahead_dict["pass_bool"] is True, lookahead_dict.get("first_fail_dict")
    kind_set = {row["kind_str"] for candidate_dict in lookahead_dict["candidate_dict"].values() for row in candidate_dict["check_list"]}
    assert set(INTRADAY_KIND_STR_LIST) <= kind_set and set(KIND_STR_LIST) <= kind_set
    for candidate in intraday_design.CANDIDATE_LIST:
        assert len(lookahead_dict["candidate_dict"][candidate]["intraday_cut_list"]) > 0, candidate
    baseline_dict = clean_dict["baseline_dict"]
    assert baseline_dict["exposure_basis_str"] == "intraday_pattern"
    assert baseline_dict["constant_exposure_weight_basis_str"] == "bar_weighted"
    assert isinstance(baseline_dict["random_timing_intraday_skip_count"], int)
    assert len(baseline_dict["random_timing_return_list"]) == 4
    # THE PRIOR-ONLY PATH CARRIES THE INTRADAY RECORDS AND REPLAYS STRICTLY
    prior_list = clean_dict["prior_only_dict"]["decision_dict_list"]
    assert any(INTRADAY_LIST_KEY_STR in decision_dict for decision_dict in prior_list)
    # A KILLED RUN RESUMES TO THE SAME PATH
    try:
        run_intraday_development_dict("intraday_resume", "resume.csv", crash_after_period_id_in=0)
        raise AssertionError("the crash hook did not fire")
    except RuntimeError as error:
        assert "runner crash after period 0" in str(error)
    resumed_dict = run_intraday_development_dict("intraday_resume", "resume.csv")
    assert np.array_equal(resumed_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(),
                          clean_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy())
    for candidate in intraday_design.CANDIDATE_LIST:
        resumed_list = resumed_dict["candidate_decision_dict"][candidate]
        clean_list = clean_dict["candidate_decision_dict"][candidate]
        assert len(resumed_list) == len(clean_list)
        assert all(get_decision_equal_bool(left, right, 0.0) for left, right in zip(resumed_list, clean_list)), candidate
    passed("development run: look-ahead passes with intraday cuts, pattern baselines, bar-weighted constant exposure, resume equals clean run")


# FUNCTION: THE PATTERN DRAW KEEPS TIME AT EACH PATTERN AND THE TIME OF DAY
def test_pattern_random_timing():
    """
    A random draw is a permutation of the path's sessions into spells: the count of each pattern is kept, every
    pattern keeps its time-of-day weights, and the base pattern is the most common one. On a real span the drop
    candidate's bar-weighted mean weight is below 1 while its close weights are all 1.

    Returns:
        None
    """
    # A HAND-MADE PATH: MOSTLY INVESTED, A FEW 15:30 EXITS, ONE TWO-DAY SPELL
    base_pattern, exit_pattern, cash_pattern = (1.0, 1.0, 1.0), (1.0, 0.0, 1.0), (1.0, 0.0, 0.0)
    pattern_list = [base_pattern] * 20 + [exit_pattern] + [base_pattern] * 5 + [cash_pattern, (0.0, 0.0, 1.0)] + [base_pattern] * 10 + [exit_pattern]
    assert get_base_pattern(pattern_list) == base_pattern
    for seed_int in range(20):
        random_list = get_random_pattern_list(pattern_list, seed_int)
        assert len(random_list) == len(pattern_list)
        for pattern in {base_pattern, exit_pattern, cash_pattern, (0.0, 0.0, 1.0)}:
            assert sum(get_pattern_equal_bool(item, pattern) for item in random_list) == sum(get_pattern_equal_bool(item, pattern) for item in pattern_list)
        spell_pos = [idx for idx, item in enumerate(random_list) if get_pattern_equal_bool(item, cash_pattern)][0]
        assert get_pattern_equal_bool(random_list[spell_pos + 1], (0.0, 0.0, 1.0)), "a two-session spell was split"
    # THE PATTERNS OF RECORDED DECISIONS (KEEP CARRIES)
    decision_list = [{"target_weight": 1.0, INTRADAY_LIST_KEY_STR: (("12:00", float("nan")), ("15:30", 0.0))},
                     {"target_weight": float("nan"), INTRADAY_LIST_KEY_STR: (("12:00", float("nan")),)},
                     {"target_weight": 1.0, INTRADAY_LIST_KEY_STR: ()}]
    assert get_intraday_pattern_list(decision_list, ("12:00", "15:30"), 1.0) == [(1.0, 0.0, 1.0), (1.0, 1.0, 1.0), (1.0, 1.0, 1.0)]
    # A REAL SPAN: THE DROP CANDIDATE ALONE
    ohlcv_array_dict = get_ohlcv_dict("2010-06-01", "2010-07-15", seed_in=8)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    path_dict = run_daily_dict(intraday_design.get_candidate_design("drop"), ohlcv_array_dict, date1, date2,
                               initial_weight_in=1.0, dead_band_in=0.0)
    exit_count = sum(1 for decision_dict in path_dict["decision_dict_list"]
                     for _time, weight in decision_dict.get(INTRADAY_LIST_KEY_STR, ()) if weight == 0.0)
    assert exit_count > 0, "the synthetic span has no 15:30 exit"
    baseline_dict = get_runner_baseline_dict(ohlcv_array_dict, date1, date2, path_dict, seed_count_int_in=5,
                                             intraday_time_tuple_in=("12:00", "15:30"), initial_weight_in=1.0)
    assert 0.9 < baseline_dict["constant_exposure_weight"] < 1.0
    assert np.nanmin(path_dict["target_weight_arr"][:-1]) == 1.0
    assert len(set(round(value, 10) for value in baseline_dict["random_timing_return_list"])) > 1
    passed("pattern random timing: counts and time of day kept, spells intact, keep carries, bar-weighted mean weight below 1")


# FUNCTION: A LEAK INSIDE THE SESSION FAILS THE INTRADAY CUTS ONLY
def test_intraday_leak_fails():
    """
    The runner is patched so an intraday call sees 20 bars past its bar (the 15:58 call is honest). The session cuts
    cannot see it (the leaked bars are before the 15:58 decision bar); the intraday cuts fail it.

    Returns:
        None
    """
    # PATCH THE LOOP'S FILL AND THE VIEW SLICE, THEN RESTORE BOTH
    original_fill = fill_bar_buffer_through_decision
    original_slice = get_sliced_bar_array_dict

    def leaking_fill(buffer_dict_in, ohlcv_array_dict_in, session_idx_in, decision_idx_in):
        decision_bar_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][int(session_idx_in)])
        target_idx = int(decision_idx_in)
        if target_idx < decision_bar_idx:
            target_idx = min(target_idx + 20, decision_bar_idx - 1)
        original_fill(buffer_dict_in, ohlcv_array_dict_in, session_idx_in, target_idx)

    def leaking_slice(buffer_dict_in, last_bar_idx_in, session_idx_in):
        return original_slice(buffer_dict_in, int(buffer_dict_in.get("copied_through_idx", last_bar_idx_in)), session_idx_in)

    import so.runner.loop as loop_mod
    import so.runner.view as view_mod
    loop_mod.fill_bar_buffer_through_decision = leaking_fill
    view_mod.get_sliced_bar_array_dict = leaking_slice
    try:
        result_dict = run_intraday_development_dict("intraday_leak", "leak.csv", seed_count_int_in=2)
    finally:
        loop_mod.fill_bar_buffer_through_decision = original_fill
        view_mod.get_sliced_bar_array_dict = original_slice
    lookahead_dict = result_dict["lookahead_dict"]
    assert lookahead_dict["pass_bool"] is False
    packed_dict = lookahead_dict["candidate_dict"]["packed"]
    assert packed_dict["pass_bool"] is False and packed_dict["first_fail_dict"]["kind_str"] in INTRADAY_KIND_STR_LIST
    assert all(row["pass_bool"] for row in packed_dict["check_list"] if row["kind_str"] in KIND_STR_LIST)
    assert "look-ahead" in result_dict["verdict_dict"]["failed_list"]
    with open(os.path.join(result_dict["run_folder_str"], "lookahead.json"), "r", encoding="utf-8") as json_file:
        assert json.load(json_file)["pass_bool"] is False
    passed("an intraday call that sees 20 bars ahead passes every session cut and fails the intraday cuts")


# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE A TEMPORARY FOLDER THIS FILE CREATED
    try:
        test_time_list_validation()
        test_time_mapping_early_close_and_missing_bar()
        test_keep_equals_daily()
        test_sell_and_buy_back_hand_path()
        test_refusals()
        test_pattern_random_timing()
        test_development_run_baselines_and_resume()
        test_intraday_leak_fails()
        print("\nAll runner intraday tests passed ✅")
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
            if _CURRENT_DATA_PATH_STR:
                os.environ["SO_DATA_PATH"] = _CURRENT_DATA_PATH_STR
            else:
                os.environ.pop("SO_DATA_PATH", None)
