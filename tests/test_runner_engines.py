"""
Workspace Tests: barrier and trailing-stop engines (so.runner; infrastructure step 4b-2a)

Run from the workspace root:   python tests/test_runner_engines.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The data root is a temporary folder. records/holdout_windows.csv is not written.
SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set. No real-data run.
"""

import os
import sys
import time
import tempfile
import shutil
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
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_engines_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()

from so import config, paths
from so.core.trade_execution import get_ohlcv_array_dict, get_ts_bar_idx_arr
from so.core.backtest_simulation import (simulate_decision_trading_dict, get_daily_equity_pdf,
                                         get_session_first_entry_idx)
from so.core.reentry_simulation import (simulate_stop_reentry_dict, get_fixed_delay_reentry_func,
                                        get_window_session_idx_arr)
from so.features.daily_features import get_session_decision_idx_dict
from so.runner import (run_daily_dict, run_development_dict, TrailingStopEngine, BarrierEngine, get_decision_dict,
                       LOOK_AHEAD_PASS_STR)
from so.runner.loop import get_bar_range_event_dict, get_fill_event_dict
from so.runner.run import get_candidate_token_str
from so.runner.checkpoint import read_checkpoint_dict
from so.core.trial_log import read_trial_log_pdf
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_trailing_design as trail_design
import runner_barrier_design as barrier_design

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


# FUNCTION: THREE INJECTED PERIODS ON A SHORT SYNTHETIC SPAN
def get_injected_period_pdf(session_date_list_in):
    """
    Args:
        session_date_list_in (list): Session dates (at least 12)

    Returns:
        pd.DataFrame: period_id, period_start, period_end, session_count, valid_start, valid_end
    """
    # THE SPAN IS LONG ENOUGH FOR THREE PERIODS
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
    folder_str = os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "runner_engine_test")
    os.makedirs(folder_str, exist_ok=True)
    return os.path.join(folder_str, file_name_str_in)


# THE OLD SIMULATOR'S SESSION TIMING (TEST REFERENCE)
from trailing_timing_reference import run_trailing_session_timing_dict as run_trailing_parity_dict


# FUNCTION: ASSERT TRAILING ENGINE MATCHES THE OLD SIMULATOR
def assert_trailing_match(engine_dict_in, sim_dict_in, label_str_in):
    """
    Args:
        engine_dict_in, sim_dict_in (dict): Results
        label_str_in (str): Assertion label

    Returns:
        None
    """
    # TRADES
    engine_pdf, sim_pdf = engine_dict_in["trade_pdf"], sim_dict_in["transaction_pdf"]
    assert len(engine_pdf) == len(sim_pdf), (label_str_in, len(engine_pdf), len(sim_pdf))
    if len(engine_pdf):
        assert engine_pdf["buy_idx"].tolist() == sim_pdf["buy_idx"].tolist(), label_str_in
        assert engine_pdf["sell_idx"].tolist() == sim_pdf["sell_idx"].tolist(), label_str_in
        assert engine_pdf["exit_reason"].tolist() == sim_pdf["exit_reason"].tolist(), label_str_in
        assert engine_pdf["entry_reason"].tolist() == sim_pdf["entry_reason"].tolist(), label_str_in
        assert engine_pdf["share_count"].tolist() == sim_pdf["share_count"].tolist(), label_str_in
        assert np.allclose(engine_pdf["sell_raw_price"], sim_pdf["sell_raw_price"], atol=1e-9, equal_nan=True)
        assert np.allclose(engine_pdf["buy_fill_price"], sim_pdf["buy_fill_price"], atol=1e-9)
        assert np.allclose(engine_pdf["sell_fill_price"], sim_pdf["sell_fill_price"], atol=1e-9)
        assert np.allclose(engine_pdf["net_profit"], sim_pdf["net_profit"], atol=1e-9)
        assert np.allclose(engine_pdf["equity_after"], sim_pdf["equity_after"], atol=1e-9)
    # EQUITY
    assert engine_dict_in["daily_equity_pdf"]["date"].tolist() == sim_dict_in["daily_equity_pdf"]["date"].tolist()
    assert np.allclose(engine_dict_in["daily_equity_pdf"]["equity"], sim_dict_in["daily_equity_pdf"]["equity"], atol=1e-9)
    assert engine_dict_in["daily_equity_pdf"]["in_position"].tolist() == sim_dict_in["daily_equity_pdf"]["in_position"].tolist()
    # METRICS
    for key_str in ("total_return", "final_equity", "trade_count", "stop_count", "signal_exit_count",
                    "rule_reentry_count", "forced_reentry_count", "cash_session_pct"):
        engine_value, sim_value = engine_dict_in["metric_dict"][key_str], sim_dict_in["metric_dict"][key_str]
        if isinstance(engine_value, float) and isinstance(sim_value, float):
            assert np.isclose(engine_value, sim_value, atol=1e-9, equal_nan=True), (label_str_in, key_str, engine_value, sim_value)
        else:
            assert engine_value == sim_value, (label_str_in, key_str, engine_value, sim_value)


# FUNCTION: DRIVE BarrierEngine BAR BY BAR FROM A DECISION FRAME
def run_barrier_parity_dict(decision_pdf_in, ohlcv_array_dict_in):
    """
    Args:
        decision_pdf_in (pd.DataFrame): decision_ts, buy_flag, delta
        ohlcv_array_dict_in (dict): Bars

    Returns:
        dict: Engine result
    """
    # FILL INDEX FOR EVERY BUY
    buy_pdf = decision_pdf_in[decision_pdf_in["buy_flag"].astype(bool)].sort_values("decision_ts").reset_index(drop=True)
    decision_idx_arr = get_ts_bar_idx_arr(ohlcv_array_dict_in, buy_pdf["decision_ts"]) if not buy_pdf.empty else np.array([], dtype=int)
    fill_delta_dict = {}
    last_bar_idx = len(ohlcv_array_dict_in["close_arr"]) - 1
    for row_idx, decision_idx in enumerate(decision_idx_arr):
        if decision_idx < 0 or decision_idx >= last_bar_idx:
            continue
        fill_idx = int(decision_idx) + int(config.DECISION_TO_ENTRY_BAR_OFFSET)
        if ohlcv_array_dict_in["bar_session_idx_arr"][fill_idx] != ohlcv_array_dict_in["bar_session_idx_arr"][decision_idx]:
            continue
        fill_delta_dict[int(fill_idx)] = (float(buy_pdf.loc[row_idx, "delta"]), buy_pdf.loc[row_idx, "decision_ts"],
                                          int(decision_idx))
    engine = BarrierEngine()
    engine.set_session_bounds(ohlcv_array_dict_in["session_end_idx_arr"], len(ohlcv_array_dict_in["close_arr"]))
    first_session_idx = 0
    first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, first_session_idx)
    timestamp_index = ohlcv_array_dict_in["timestamp_index"]
    engine.open_window({"bar_idx": int(first_entry_idx), "timestamp": timestamp_index[first_entry_idx],
                        "raw_price": float(ohlcv_array_dict_in["open_arr"][first_entry_idx]),
                        "close": float(ohlcv_array_dict_in["close_arr"][first_entry_idx]),
                        "session_idx": first_session_idx,
                        "session_date": ohlcv_array_dict_in["session_date_list"][first_session_idx]}, 0.0)
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    last_session_idx = session_count - 1
    for session_idx in range(session_count):
        start_idx = int(ohlcv_array_dict_in["session_start_idx_arr"][session_idx])
        end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx])
        session_date = ohlcv_array_dict_in["session_date_list"][session_idx]
        cursor_idx = start_idx
        fill_idx_list = sorted(fill_idx for fill_idx in fill_delta_dict if start_idx <= fill_idx <= end_idx)
        for fill_idx in fill_idx_list:
            morning_event_dict = get_bar_range_event_dict(ohlcv_array_dict_in, cursor_idx, fill_idx - 1, session_date)
            if morning_event_dict is not None:
                engine.process_bars(morning_event_dict)
            delta_float, decision_ts, decision_idx = fill_delta_dict[fill_idx]
            engine.apply_decision(get_fill_event_dict(ohlcv_array_dict_in, fill_idx, decision_idx, session_idx,
                                                      session_date, end_idx),
                                  get_decision_dict({"target_weight": 1.0, "delta": delta_float}),
                                  float(ohlcv_array_dict_in["close_arr"][decision_idx]))
            cursor_idx = fill_idx
        rest_event_dict = get_bar_range_event_dict(ohlcv_array_dict_in, cursor_idx, end_idx, session_date)
        if rest_event_dict is not None:
            engine.process_bars(rest_event_dict)
        if session_idx != last_session_idx:
            engine.close_session({"session_date": session_date, "close": float(ohlcv_array_dict_in["close_arr"][end_idx])})
    last_idx = len(ohlcv_array_dict_in["close_arr"]) - 1
    last_session_date = ohlcv_array_dict_in["session_date_list"][last_session_idx]
    engine.close_window({"bar_idx": last_idx, "timestamp": timestamp_index[last_idx],
                         "raw_price": float(ohlcv_array_dict_in["close_arr"][last_idx]),
                         "close": float(ohlcv_array_dict_in["close_arr"][last_idx]),
                         "session_idx": last_session_idx, "session_date": last_session_date})
    engine.close_session({"session_date": last_session_date, "close": float(ohlcv_array_dict_in["close_arr"][last_idx])})
    return engine.get_result_dict()


# FUNCTION: ASSERT BARRIER ENGINE MATCHES THE OLD SIMULATOR
def assert_barrier_match(engine_dict_in, sim_dict_in, ohlcv_array_dict_in, date1_in, date2_in, label_str_in):
    """
    Args:
        engine_dict_in, sim_dict_in (dict): Results
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Window
        label_str_in (str): Assertion label

    Returns:
        None
    """
    # TRADES
    engine_pdf, sim_pdf = engine_dict_in["trade_pdf"], sim_dict_in["transaction_pdf"]
    assert len(engine_pdf) == len(sim_pdf), (label_str_in, len(engine_pdf), len(sim_pdf),
                                             engine_pdf["exit_reason"].tolist() if len(engine_pdf) else None,
                                             sim_pdf["exit_reason"].tolist() if len(sim_pdf) else None)
    if len(engine_pdf):
        assert engine_pdf["buy_idx"].tolist() == sim_pdf["buy_idx"].tolist(), label_str_in
        assert engine_pdf["sell_idx"].tolist() == sim_pdf["sell_idx"].tolist(), label_str_in
        assert engine_pdf["exit_reason"].tolist() == sim_pdf["exit_reason"].tolist(), label_str_in
        assert engine_pdf["share_count"].tolist() == sim_pdf["share_count"].tolist(), label_str_in
        assert np.allclose(engine_pdf["sell_raw_price"], sim_pdf["sell_raw_price"], atol=1e-9)
        assert np.allclose(engine_pdf["buy_fill_price"], sim_pdf["buy_fill_price"], atol=1e-9)
        assert np.allclose(engine_pdf["sell_fill_price"], sim_pdf["sell_fill_price"], atol=1e-9)
        assert np.allclose(engine_pdf["net_profit"], sim_pdf["net_profit"], atol=1e-9)
        assert np.allclose(engine_pdf["SL_price"], sim_pdf["SL_price"], atol=1e-9)
        assert np.allclose(engine_pdf["TP_price"], sim_pdf["TP_price"], atol=1e-9)
    assert int(engine_dict_in["skipped_decision_count"]) == int(sim_dict_in["skipped_decision_count"]), label_str_in
    sim_equity_pdf = get_daily_equity_pdf(sim_pdf, ohlcv_array_dict_in, str(date1_in), str(date2_in), config.INITIAL_CAPITAL)
    engine_equity_pdf = engine_dict_in["daily_equity_pdf"]
    if len(sim_equity_pdf) and len(engine_equity_pdf):
        shared_count = min(len(sim_equity_pdf), len(engine_equity_pdf))
        assert np.allclose(engine_equity_pdf["equity"].iloc[:shared_count], sim_equity_pdf["equity"].iloc[:shared_count],
                           atol=1e-6), label_str_in


# FUNCTION: TRAILING ENGINE MATCHES THE OLD SIMULATOR ON RANDOM STREAMS
def test_trailing_parity_random_streams():
    """
    Random k, volatility, delay, exit signals, cooling-off, fresh-exit and max-cash, including half days.

    Returns:
        None
    """
    # TWO SYNTHETIC YEARS COVER HALF DAYS
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-01-04", "2011-12-30", seed_in=11)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_count = len(ohlcv_array_dict["session_date_list"])
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    rng = np.random.default_rng(7)
    volatility_arr = rng.uniform(0.004, 0.03, session_count)
    case_list = []
    case_list.append(("delay1_k2", 2.0, get_fixed_delay_reentry_func(1), None, 20, None, False))
    case_list.append(("delay5_k1", 1.0, get_fixed_delay_reentry_func(5), None, 60, None, False))
    k_arr = rng.choice(np.array([1.0, 2.0, 3.0]), session_count)
    exit_arr = rng.random(session_count) < 0.08

    def cooling_func(session_idx, cash_session_count, episode_dict):
        episode_dict["exit_block_sessions"] = 5
        return cash_session_count >= 1

    def fresh_func(session_idx, cash_session_count, episode_dict):
        episode_dict["require_fresh_exit"] = True
        return cash_session_count >= 1

    case_list.append(("k_arr_signal", k_arr, get_fixed_delay_reentry_func(1), exit_arr, 20, None, False))
    case_list.append(("cooling", 2.0, cooling_func, np.ones(session_count, dtype=bool), None, "rule", False))
    case_list.append(("fresh", 2.0, fresh_func, exit_arr, 20, "rule", False))
    case_list.append(("no_stop", None, get_fixed_delay_reentry_func(1), None, None, None, False))
    half_day_count = 0
    bar_count_arr = ohlcv_array_dict["session_end_idx_arr"] - ohlcv_array_dict["session_start_idx_arr"] + 1
    half_day_count = int((bar_count_arr < 350).sum())
    assert half_day_count > 0
    for name_str, stop_k, reentry_func, exit_arr_case, max_cash, reason_str, _unused in case_list:
        reason_str = "delay" if reason_str is None else reason_str
        sim_dict = simulate_stop_reentry_dict(ohlcv_array_dict, date1, date2, volatility_arr, stop_k, reentry_func,
                                              reason_str, exit_signal_arr_in=exit_arr_case,
                                              max_cash_sessions_in=max_cash)
        engine_dict = run_trailing_parity_dict(ohlcv_array_dict, date1, date2, volatility_arr, stop_k, reentry_func,
                                               reason_str, exit_arr_case, max_cash)
        assert_trailing_match(engine_dict, sim_dict, name_str)
        if name_str == "k_arr_signal":
            sell_session_arr = ohlcv_array_dict["bar_session_idx_arr"][engine_dict["trade_pdf"]["sell_idx"].to_numpy()] if len(engine_dict["trade_pdf"]) else np.array([], dtype=int)
            half_exit_bool = any(int(bar_count_arr[int(session_idx)]) < 350 for session_idx in sell_session_arr)
            assert half_exit_bool or len(engine_dict["trade_pdf"]) > 0
    passed(f"trailing engine matches simulate_stop_reentry_dict on random streams ({half_day_count} half days)")


# FUNCTION: DAILY LOOP WITH CONSTANT k MATCHES THE OLD SIMULATOR
def test_trailing_daily_loop_constant_k():
    """
    Constant k and volatility, delay-1 re-entry, no flatten.

    Returns:
        None
    """
    # ONE SYNTHETIC YEAR
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-01-04", "2010-12-31", seed_in=3)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    session_count = len(ohlcv_array_dict["session_date_list"])
    volatility_arr = np.full(session_count, trail_design.VOLATILITY)
    sim_dict = simulate_stop_reentry_dict(ohlcv_array_dict, date1, date2, volatility_arr, trail_design.TRAIL_MULTIPLE,
                                          get_fixed_delay_reentry_func(1), "delay",
                                          max_cash_sessions_in=trail_design.MAX_CASH_SESSIONS)
    engine = TrailingStopEngine(trail_design.MAX_CASH_SESSIONS)
    engine.set_stop_params(trail_design.TRAIL_MULTIPLE, trail_design.VOLATILITY)
    runner_dict = run_daily_dict(trail_design.TrailDesign(), ohlcv_array_dict, date1, date2, engine_in=engine,
                                 initial_weight_in=1.0)
    assert_trailing_match(runner_dict, sim_dict, "daily_loop_constant_k")
    passed("trailing DailyLoop with constant k matches simulate_stop_reentry_dict")



# FUNCTION: THE REPLAY OF RECORDED DECISIONS REPRODUCES THE STREAM WHEN k AND VOLATILITY VARY
def test_replay_matches_stream_varying_stop():
    """
    A trailing design whose volatility changes every session. The prior-only replay (run_engine_decisions_dict on
    the recorded decisions) must give the same trades and equity as the candidate stream (DailyLoop): a decision's
    stop parameters apply from its fill, in both.

    Returns:
        None
    """
    # IMPORT THE REPLAY HERE
    from so.runner.loop import run_engine_decisions_dict
    # ONE SYNTHETIC YEAR, THE STREAM, THEN THE REPLAY OF ITS DECISIONS
    ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2011-01-03", "2011-12-30", seed_in=11))
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    stream_dict = run_daily_dict(trail_design.VaryingTrailDesign(), ohlcv_array_dict, date1, date2,
                                 engine_in=TrailingStopEngine(trail_design.MAX_CASH_SESSIONS), initial_weight_in=1.0,
                                 design_file_path_str_in=trail_design.__file__)
    replay_dict = run_engine_decisions_dict(ohlcv_array_dict, date1, date2, stream_dict["decision_dict_list"],
                                            engine_in=TrailingStopEngine(trail_design.MAX_CASH_SESSIONS),
                                            initial_weight_in=1.0)
    stream_trade_pdf, replay_trade_pdf = stream_dict["trade_pdf"], replay_dict["trade_pdf"]
    assert int(stream_dict["metric_dict"]["stop_count"]) > 3, "the test needs several stop-outs"
    assert len(stream_trade_pdf) == len(replay_trade_pdf), (len(stream_trade_pdf), len(replay_trade_pdf))
    assert stream_trade_pdf["buy_idx"].tolist() == replay_trade_pdf["buy_idx"].tolist()
    assert stream_trade_pdf["sell_idx"].tolist() == replay_trade_pdf["sell_idx"].tolist()
    assert stream_trade_pdf["exit_reason"].tolist() == replay_trade_pdf["exit_reason"].tolist()
    assert np.allclose(stream_dict["daily_equity_pdf"]["equity"], replay_dict["daily_equity_pdf"]["equity"], atol=1e-9)
    passed(f"trailing replay of recorded decisions == stream with varying k/volatility "
           f"({int(stream_dict['metric_dict']['stop_count'])} stop-outs)")



# FUNCTION: READING THE RESULT MID-STREAM DOES NOT CHANGE THE STREAM
def test_result_read_is_pure():
    """
    The runner reads get_result_dict at every period end. A trailing-stop stream read after every session must give
    the same trades and equity as one read at the end (an open cash episode stays open in the engine).

    Returns:
        None
    """
    # IMPORT THE LOOP HERE
    from so.runner.loop import DailyLoop
    ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2012-01-03", "2012-12-31", seed_in=17))
    session_list = list(ohlcv_array_dict["session_date_list"])
    date1, date2 = session_list[0], session_list[-1]
    result_list = []
    for read_every_bool in (False, True):
        engine = TrailingStopEngine(trail_design.MAX_CASH_SESSIONS)
        loop = DailyLoop(trail_design.DelayedTrailDesign(), ohlcv_array_dict, date1, date2, engine_in=engine,
                         initial_weight_in=1.0, design_file_path_str_in=trail_design.__file__)
        if read_every_bool:
            for session_date in session_list:
                loop.run_through_date(session_date)
                loop.get_result_dict()
        else:
            loop.run_through_date(date2)
        result_list.append(loop.get_result_dict())
    once_dict, every_dict = result_list
    assert int(once_dict["metric_dict"]["stop_count"]) > 2 and len(once_dict["trade_pdf"]) == len(every_dict["trade_pdf"])
    assert once_dict["trade_pdf"]["buy_idx"].tolist() == every_dict["trade_pdf"]["buy_idx"].tolist()
    assert np.allclose(once_dict["daily_equity_pdf"]["equity"], every_dict["daily_equity_pdf"]["equity"], atol=1e-9)
    passed(f"reading the trailing engine result after every session changes nothing ({len(once_dict['trade_pdf'])} trades)")


# FUNCTION: BARRIER ENGINE MATCHES THE OLD SIMULATOR ON RANDOM STREAMS
def test_barrier_parity_random_streams():
    """
    Random daily and minute buy streams, including same-session re-entry after an exit.

    Returns:
        None
    """
    # TWO SYNTHETIC YEARS
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-01-04", "2011-06-30", seed_in=19)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
    rng = np.random.default_rng(5)
    session_count = len(ohlcv_array_dict["session_date_list"])
    buy_session_arr = rng.random(session_count) < 0.25
    buy_session_arr[-1] = False
    decision_row_list = []
    for session_idx, buy_bool in enumerate(buy_session_arr):
        if not buy_bool:
            continue
        decision_idx = int(idx_dict["decision_idx_arr"][session_idx])
        decision_row_list.append({"decision_ts": ohlcv_array_dict["timestamp_index"][decision_idx], "buy_flag": True,
                                  "delta": float(rng.choice([0.005, 0.01, 0.02]))})
    daily_decision_pdf = pd.DataFrame(decision_row_list)
    sim_dict = simulate_decision_trading_dict(daily_decision_pdf, ohlcv_array_dict)
    engine_dict = run_barrier_parity_dict(daily_decision_pdf, ohlcv_array_dict)
    assert_barrier_match(engine_dict, sim_dict, ohlcv_array_dict, date1, date2, "daily_buys")
    minute_row_list = []
    for session_idx in range(0, session_count - 1, 3):
        start_idx = int(ohlcv_array_dict["session_start_idx_arr"][session_idx]) + 30
        end_idx = int(idx_dict["decision_idx_arr"][session_idx])
        if start_idx >= end_idx:
            continue
        pick_idx = int(rng.integers(start_idx, end_idx))
        minute_row_list.append({"decision_ts": ohlcv_array_dict["timestamp_index"][pick_idx], "buy_flag": True,
                                "delta": float(rng.choice([0.004, 0.008, 0.015]))})
    minute_decision_pdf = pd.DataFrame(minute_row_list)
    sim_minute_dict = simulate_decision_trading_dict(minute_decision_pdf, ohlcv_array_dict)
    engine_minute_dict = run_barrier_parity_dict(minute_decision_pdf, ohlcv_array_dict)
    assert_barrier_match(engine_minute_dict, sim_minute_dict, ohlcv_array_dict, date1, date2, "minute_buys")
    passed("barrier engine matches simulate_decision_trading_dict on random daily and minute streams")


# FUNCTION: SAME-BAR TAKE-PROFIT AND STOP-LOSS, SL WINS
def test_barrier_same_bar_sl_wins():
    """
    One handmade bar hits both barriers. The engine exits at the stop.

    Returns:
        None
    """
    # DECISION AT BAR 0, ENTRY AT BAR 1, BOTH BARRIERS ON BAR 2 (THE FIRST ACTIVE BAR)
    timestamp_index = pd.DatetimeIndex(
        ["2010-06-01 10:00", "2010-06-01 10:01", "2010-06-01 10:02", "2010-06-01 10:03"], tz="America/New_York")
    ohlcv_array_dict = {
        "timestamp_index": timestamp_index,
        "open_arr": np.array([100.0, 100.0, 100.0, 100.0]),
        "high_arr": np.array([100.2, 100.2, 102.0, 100.2]),
        "low_arr": np.array([99.8, 99.8, 98.0, 99.8]),
        "close_arr": np.array([100.0, 100.0, 100.0, 100.0]),
        "bar_session_idx_arr": np.array([0, 0, 0, 0]),
        "session_date_list": [pd.Timestamp("2010-06-01").date()],
        "session_start_idx_arr": np.array([0]),
        "session_end_idx_arr": np.array([3]),
        "date_session_idx_dict": {pd.Timestamp("2010-06-01").date(): 0},
    }
    decision_pdf = pd.DataFrame([{"decision_ts": timestamp_index[0], "buy_flag": True, "delta": 0.01}])
    sim_dict = simulate_decision_trading_dict(decision_pdf, ohlcv_array_dict)
    engine_dict = run_barrier_parity_dict(decision_pdf, ohlcv_array_dict)
    assert list(sim_dict["transaction_pdf"]["exit_reason"]) == [config.EXIT_REASON_SL]
    assert list(engine_dict["trade_pdf"]["exit_reason"]) == [config.EXIT_REASON_SL]
    assert int(engine_dict["trade_pdf"]["sell_idx"].iloc[0]) == 2
    assert_barrier_match(engine_dict, sim_dict, ohlcv_array_dict, ohlcv_array_dict["session_date_list"][0],
                         ohlcv_array_dict["session_date_list"][0], "same_bar")
    passed("same-bar take-profit and stop-loss: SL wins, engine matches the old resolver")


# FUNCTION: AN EXIT ON A SHORT SECOND SESSION (HALF DAY)
def test_barrier_half_day_exit():
    """
    Two sessions; the second is three bars. A wide delta leaves the trade unresolved, so both paths close as END
    at the last bar of the short session.

    Returns:
        None
    """
    # SESSION 1 IS A SHORT EARLY-CLOSE SESSION
    timestamp_index = pd.DatetimeIndex(
        ["2010-11-24 10:00", "2010-11-24 10:01", "2010-11-24 15:59",
         "2010-11-26 10:00", "2010-11-26 12:58", "2010-11-26 12:59"], tz="America/New_York")
    ohlcv_array_dict = {
        "timestamp_index": timestamp_index,
        "open_arr": np.array([100.0, 100.1, 100.2, 100.3, 100.4, 100.5]),
        "high_arr": np.array([100.2, 100.3, 100.4, 100.5, 100.6, 100.7]),
        "low_arr": np.array([99.8, 99.9, 100.0, 100.1, 100.2, 100.3]),
        "close_arr": np.array([100.1, 100.2, 100.3, 100.4, 100.5, 100.6]),
        "bar_session_idx_arr": np.array([0, 0, 0, 1, 1, 1]),
        "session_date_list": [pd.Timestamp("2010-11-24").date(), pd.Timestamp("2010-11-26").date()],
        "session_start_idx_arr": np.array([0, 3]),
        "session_end_idx_arr": np.array([2, 5]),
        "date_session_idx_dict": {pd.Timestamp("2010-11-24").date(): 0, pd.Timestamp("2010-11-26").date(): 1},
    }
    decision_pdf = pd.DataFrame([{"decision_ts": timestamp_index[0], "buy_flag": True, "delta": 0.5}])
    sim_dict = simulate_decision_trading_dict(decision_pdf, ohlcv_array_dict)
    engine_dict = run_barrier_parity_dict(decision_pdf, ohlcv_array_dict)
    assert list(sim_dict["transaction_pdf"]["exit_reason"]) == [config.EXIT_REASON_END]
    assert list(engine_dict["trade_pdf"]["exit_reason"]) == [config.EXIT_REASON_END]
    assert int(engine_dict["trade_pdf"]["sell_idx"].iloc[0]) == 5
    assert int(sim_dict["transaction_pdf"]["sell_idx"].iloc[0]) == 5
    passed("barrier exit on a short second session matches the old resolver")


# FUNCTION: A STOP AFTER THE DECISION IS INVISIBLE UNTIL THE NEXT CALL
def test_stop_out_visible_next_decision():
    """
    The design's snapshot on the stop session is still in position when the stop fills after 15:58.

    Returns:
        None
    """
    # A LOOSE STOP STAYS INVESTED THROUGH THE MORNING; THE FILL-BAR LOW IS PLANTED BELOW IT
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-01-04", "2010-03-31", seed_in=9)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
    fill_idx_arr = idx_dict["fill_idx_arr"]
    for session_idx in range(2, len(ohlcv_array_dict["session_date_list"]) - 1):
        fill_idx = int(fill_idx_arr[session_idx])
        crash_price = float(ohlcv_array_dict["open_arr"][fill_idx]) * 0.5
        ohlcv_array_dict["low_arr"][fill_idx] = min(float(ohlcv_array_dict["low_arr"][fill_idx]), crash_price)
        ohlcv_array_dict["open_arr"][fill_idx] = min(float(ohlcv_array_dict["open_arr"][fill_idx]), crash_price + 0.01)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    design = trail_design.TrailDesign(trail_multiple_in=2.0, volatility_in=0.01)
    engine = TrailingStopEngine(trail_design.MAX_CASH_SESSIONS)
    engine.set_stop_params(2.0, 0.01)
    runner_dict = run_daily_dict(design, ohlcv_array_dict, date1, date2, engine_in=engine, initial_weight_in=1.0)
    trade_pdf = runner_dict["trade_pdf"]
    stop_pdf = trade_pdf[trade_pdf["exit_reason"] == "STOP"] if len(trade_pdf) else trade_pdf
    found_bool = False
    for _, stop_row in stop_pdf.iterrows():
        sell_idx = int(stop_row["sell_idx"])
        session_idx = int(ohlcv_array_dict["bar_session_idx_arr"][sell_idx])
        decision_idx = int(idx_dict["decision_idx_arr"][session_idx])
        if sell_idx <= decision_idx:
            continue
        session_date = ohlcv_array_dict["session_date_list"][session_idx]
        if session_date not in design.session_date_list:
            continue
        log_idx = design.session_date_list.index(session_date)
        assert design.state_log_list[log_idx]["in_position"] is True, "afternoon stop was visible on this decision"
        next_idx = log_idx + 1
        if next_idx < len(design.state_log_list):
            assert design.state_log_list[next_idx]["in_position"] is False
            assert design.state_log_list[next_idx]["last_exit_reason"] == "STOP"
        found_bool = True
        break
    assert found_bool, "no afternoon stop to check visibility"
    passed("a design sees a stop-out only from the next decision on")


# FUNCTION: ENGINE STATE ON THE VIEW IS A READ-ONLY COPY
def test_engine_state_is_readonly_copy():
    """
    Mutating the snapshot does not change the engine. MappingProxyType refuses item assignment.

    Returns:
        None
    """
    # A SHORT SPAN
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]

    design = trail_design.MutatingTrailDesign()
    engine = TrailingStopEngine()
    engine.set_stop_params(trail_design.TRAIL_MULTIPLE, trail_design.VOLATILITY)
    run_daily_dict(design, ohlcv_array_dict, date1, date2, engine_in=engine, initial_weight_in=1.0)
    assert design.raised_bool is True
    assert design.state_log_list[0]["in_position"] is True
    passed("engine_state is a read-only copy; mutating it does not write the engine")


# FUNCTION: LOOK-AHEAD PASSES FOR A TRAILING-STOP DESIGN
def test_lookahead_trailing_passes():
    """
    Returns:
        None
    """
    # THREE INJECTED PERIODS
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    result_dict = run_development_dict(trail_design, ohlcv_array_dict, run_id_str_in="engine_trail_look",
                                       n_jobs_int_in=1, period_pdf_in=period_pdf,
                                       trial_log_path_str_in=get_test_trial_log_path_str("trail_look.csv"),
                                       commit_str_in="testcommit", code_hash_str_in="testhash",
                                       check_clean_tree_bool_in=False, check_view_bool_in=False,
                                       baseline_seed_count_int_in=2)
    assert result_dict["lookahead_dict"]["pass_bool"] is True
    assert result_dict["lookahead_dict"]["status_str"] == LOOK_AHEAD_PASS_STR
    passed("look-ahead check passes for a trailing-stop design")


# FUNCTION: LOOK-AHEAD PASSES FOR A BARRIER DESIGN
def test_lookahead_barrier_passes():
    """
    Returns:
        None
    """
    # THREE INJECTED PERIODS
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    result_dict = run_development_dict(barrier_design, ohlcv_array_dict, run_id_str_in="engine_barrier_look",
                                       n_jobs_int_in=1, period_pdf_in=period_pdf,
                                       trial_log_path_str_in=get_test_trial_log_path_str("barrier_look.csv"),
                                       commit_str_in="testcommit", code_hash_str_in="testhash",
                                       check_clean_tree_bool_in=False, check_view_bool_in=False,
                                       baseline_seed_count_int_in=2)
    assert result_dict["lookahead_dict"]["pass_bool"] is True
    assert result_dict["lookahead_dict"]["status_str"] == LOOK_AHEAD_PASS_STR
    passed("look-ahead check passes for a barrier design")


# FUNCTION: CHECKPOINT AND RESUME MATCH A CLEAN RUN
def test_checkpoint_resume_matches(design_module_in, run_prefix_str_in, initial_weight_in):
    """
    Args:
        design_module_in (module): Design
        run_prefix_str_in (str): Run id prefix
        initial_weight_in (float): Unused besides documenting the design's start

    Returns:
        None
    """
    # CRASH AFTER PERIOD 0, THEN RESUME
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    crash_log_str = get_test_trial_log_path_str(f"{run_prefix_str_in}_crash.csv")
    crashed_bool = False
    try:
        run_development_dict(design_module_in, ohlcv_array_dict, run_id_str_in=f"{run_prefix_str_in}_resume",
                             n_jobs_int_in=1, period_pdf_in=period_pdf, trial_log_path_str_in=crash_log_str,
                             commit_str_in="testcommit", code_hash_str_in="testhash",
                             crash_after_period_id_in=0, check_clean_tree_bool_in=False, check_view_bool_in=False,
                             baseline_seed_count_int_in=2)
    except RuntimeError as error:
        crashed_bool = "runner crash after period 0" in str(error)
    assert crashed_bool, "the crash hook did not fire"
    checkpoint_dict = read_checkpoint_dict(f"{run_prefix_str_in}_resume",
                                           get_candidate_token_str(design_module_in.CANDIDATE_LIST[0]))
    assert checkpoint_dict is not None and int(checkpoint_dict["period_id"]) == 0
    resumed_dict = run_development_dict(design_module_in, ohlcv_array_dict, run_id_str_in=f"{run_prefix_str_in}_resume",
                                        n_jobs_int_in=1, period_pdf_in=period_pdf, trial_log_path_str_in=crash_log_str,
                                        commit_str_in="testcommit", code_hash_str_in="testhash",
                                        check_clean_tree_bool_in=False, check_view_bool_in=False,
                                        baseline_seed_count_int_in=2)
    clean_dict = run_development_dict(design_module_in, ohlcv_array_dict, run_id_str_in=f"{run_prefix_str_in}_clean",
                                      n_jobs_int_in=1, period_pdf_in=period_pdf,
                                      trial_log_path_str_in=get_test_trial_log_path_str(f"{run_prefix_str_in}_clean.csv"),
                                      commit_str_in="testcommit", code_hash_str_in="testhash",
                                      check_clean_tree_bool_in=False, check_view_bool_in=False,
                                      baseline_seed_count_int_in=2)
    resumed_equity = resumed_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float)
    clean_equity = clean_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float)
    assert np.allclose(resumed_equity, clean_equity, atol=0.0)
    trial_pdf = read_trial_log_pdf(crash_log_str)
    assert trial_pdf["trial_id"].is_unique
    passed(f"checkpoint and resume match a clean run ({run_prefix_str_in}, initial_weight={initial_weight_in})")


# FUNCTION: SPEED OF EACH ENGINE VS THE OLD SIMULATOR ON FOUR SYNTHETIC YEARS
def test_speed_four_synthetic_years():
    """
    One candidate. Prints seconds for the old simulator and the engine. Does not fail on speed.

    Returns:
        None
    """
    # FOUR YEARS, ONE PATH
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-01-04", "2013-12-31", seed_in=2)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    session_count = len(ohlcv_array_dict["session_date_list"])
    volatility_arr = np.full(session_count, 0.01)
    reentry_func = get_fixed_delay_reentry_func(1)
    run_trailing_parity_dict(ohlcv_array_dict, date1, date1, volatility_arr, 2.0, reentry_func, "delay", None, 20)
    start_time = time.perf_counter()
    sim_dict = simulate_stop_reentry_dict(ohlcv_array_dict, date1, date2, volatility_arr, 2.0, reentry_func, "delay",
                                          max_cash_sessions_in=20)
    sim_trail_s = time.perf_counter() - start_time
    start_time = time.perf_counter()
    engine_dict = run_trailing_parity_dict(ohlcv_array_dict, date1, date2, volatility_arr, 2.0, reentry_func, "delay",
                                           None, 20)
    engine_trail_s = time.perf_counter() - start_time
    assert_trailing_match(engine_dict, sim_dict, "speed_trail")
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict)
    decision_row_list = []
    for session_idx in range(0, session_count - 1, 5):
        decision_idx = int(idx_dict["decision_idx_arr"][session_idx])
        decision_row_list.append({"decision_ts": ohlcv_array_dict["timestamp_index"][decision_idx], "buy_flag": True,
                                  "delta": 0.01})
    decision_pdf = pd.DataFrame(decision_row_list)
    run_barrier_parity_dict(decision_pdf.iloc[:1], ohlcv_array_dict)
    start_time = time.perf_counter()
    sim_barrier_dict = simulate_decision_trading_dict(decision_pdf, ohlcv_array_dict)
    sim_barrier_s = time.perf_counter() - start_time
    start_time = time.perf_counter()
    engine_barrier_dict = run_barrier_parity_dict(decision_pdf, ohlcv_array_dict)
    engine_barrier_s = time.perf_counter() - start_time
    assert_barrier_match(engine_barrier_dict, sim_barrier_dict, ohlcv_array_dict, date1, date2, "speed_barrier")
    print(f"speed 4y one candidate: trailing old {sim_trail_s:.3f}s engine {engine_trail_s:.3f}s; "
          f"barrier old {sim_barrier_s:.3f}s engine {engine_barrier_s:.3f}s")
    passed(f"speed 4y: trailing old {sim_trail_s:.3f}s vs engine {engine_trail_s:.3f}s; "
           f"barrier old {sim_barrier_s:.3f}s vs engine {engine_barrier_s:.3f}s")


# RUN THE SUITE
if __name__ == "__main__":
    try:
        test_trailing_parity_random_streams()
        test_trailing_daily_loop_constant_k()
        test_replay_matches_stream_varying_stop()
        test_result_read_is_pure()
        test_barrier_parity_random_streams()
        test_barrier_same_bar_sl_wins()
        test_barrier_half_day_exit()
        test_stop_out_visible_next_decision()
        test_engine_state_is_readonly_copy()
        test_lookahead_trailing_passes()
        test_lookahead_barrier_passes()
        test_checkpoint_resume_matches(trail_design, "trail_ckpt", 1.0)
        test_checkpoint_resume_matches(barrier_design, "barrier_ckpt", 0.0)
        test_speed_four_synthetic_years()
        print("\nAll runner engine tests passed ✅")
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
        os.environ.pop("SO_QUARANTINE_PATH", None)
