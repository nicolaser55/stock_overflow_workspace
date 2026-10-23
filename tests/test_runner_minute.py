"""
Workspace Tests: runner minute mode (so.runner; infrastructure step 4b-2b)

Run from the workspace root:   python tests/test_runner_minute.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The data root is a temporary folder. records/holdout_windows.csv is not written.
SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are not set. No real-data run.
"""

import os
import sys
import time
import types
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
    TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_runner_minute_")
    os.environ["SO_DATA_PATH"] = TEMP_ROOT_STR
    OWNED_TEMP_BOOL = True
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
os.environ.pop("SO_QUARANTINE_PATH", None)
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()

from so import config, paths
from so.core.trade_execution import get_ohlcv_array_dict
from so.core.backtest_simulation import simulate_decision_trading_dict, get_daily_equity_pdf
from so.core.point_in_time import (get_ny_timestamp, get_minute_bar_available_ts, get_runner_context,
                                   register_source_dict, unregister_source, SOURCE_SPEC_DICT, DataContext)
from so.runner import (run_minute_dict, run_development_dict, MinuteLoop, get_minute_row_pdf,
                       get_shuffled_signal_list, check_minute_signal, LOOK_AHEAD_PASS_STR)
from so.runner.run import get_candidate_token_str
from so.runner.checkpoint import read_checkpoint_dict
from so.core.trial_log import read_trial_log_pdf
from synthetic_data import get_synthetic_ohlcv_pdf
import runner_minute_design as minute_design
import runner_minute_lgbm_design as lgbm_design
import runner_minute_shared_design as shared_design

# KEEP THE REAL REGISTRY PATH AND POINT THIS SUITE AT A TEMPORARY FILE
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REGISTRY_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR
# TEST SOURCE NAMES (MUST MATCH THE DESIGN MODULE)
MINUTE_FEAT_STR = "MINUTE_TEST_FEAT"
MINUTE_LABEL_STR = "MINUTE_TEST_LABEL"
NY = "America/New_York"


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
    folder_str = os.path.join(paths.LOCAL_EXPERIMENTZONE_PATH_STR, "runner_minute_test")
    os.makedirs(folder_str, exist_ok=True)
    return os.path.join(folder_str, file_name_str_in)


# FUNCTION: NORMALIZE A PLANTED FEATURE FRAME
def add_minute_feature_available_ts_pdf(pdf_in):
    """
    Args:
        pdf_in (pd.DataFrame): Rows with available_ts

    Returns:
        pd.DataFrame: Copy with New York available_ts
    """
    # THE TEST OWNS THE CLOCK COLUMN
    stamped_pdf = pdf_in.copy()
    stamped_pdf["available_ts"] = [get_ny_timestamp(ts) for ts in stamped_pdf["available_ts"]]
    return stamped_pdf


# FUNCTION: NORMALIZE A PLANTED LABEL FRAME
def add_minute_label_known_ts_pdf(pdf_in):
    """
    Args:
        pdf_in (pd.DataFrame): Rows with label_known_ts

    Returns:
        pd.DataFrame: Copy with both clocks
    """
    # A LABEL IS KNOWABLE WHEN ITS OUTCOME IS
    stamped_pdf = pdf_in.copy()
    stamped_pdf["label_known_ts"] = [get_ny_timestamp(ts) for ts in stamped_pdf["label_known_ts"]]
    stamped_pdf["available_ts"] = stamped_pdf["label_known_ts"]
    return stamped_pdf


# FUNCTION: REGISTER THE MINUTE TEST SOURCES
def register_minute_test_sources():
    """
    Args:
        None

    Returns:
        None
    """
    # FEATURE AND LABEL DOORS
    if MINUTE_FEAT_STR not in SOURCE_SPEC_DICT:
        register_source_dict(MINUTE_FEAT_STR, {"loader": "test", "time_zone": NY,
                                               "timestamp_convention": "planted available_ts",
                                               "availability_func": add_minute_feature_available_ts_pdf,
                                               "revision_policy": "not revised", "revision_reason": "test frame",
                                               "role": "feature", "holdout": "test"})
    if MINUTE_LABEL_STR not in SOURCE_SPEC_DICT:
        register_source_dict(MINUTE_LABEL_STR, {"loader": "test", "time_zone": NY,
                                                "timestamp_convention": "planted label_known_ts",
                                                "availability_func": add_minute_label_known_ts_pdf,
                                                "revision_policy": "not revised", "revision_reason": "test frame",
                                                "role": "label", "holdout": "test"})


# FUNCTION: DROP THE MINUTE TEST SOURCES
def unregister_minute_test_sources():
    """
    Args:
        None

    Returns:
        None
    """
    # DROP ONLY WHEN PRESENT
    if MINUTE_FEAT_STR in SOURCE_SPEC_DICT:
        unregister_source(MINUTE_FEAT_STR)
    if MINUTE_LABEL_STR in SOURCE_SPEC_DICT:
        unregister_source(MINUTE_LABEL_STR)


# FUNCTION: PLANTED FEATURE ROWS, ONE PER BAR, OPTIONAL LATE CLOCK
def get_planted_feature_pdf(ohlcv_array_dict_in, late_bar_idx_in=None):
    """
    x is the bar index as a float so a threshold rule is deterministic. available_ts is the end of the minute,
    unless late_bar_idx_in plants a later clock on that bar.

    Args:
        ohlcv_array_dict_in (dict): Bars
        late_bar_idx_in (int | None): Bar whose available_ts is moved past its moment

    Returns:
        pd.DataFrame: timestamp, x, available_ts
    """
    # ONE ROW PER BAR
    timestamp_index = ohlcv_array_dict_in["timestamp_index"]
    available_list = [get_minute_bar_available_ts(ts) for ts in timestamp_index]
    if late_bar_idx_in is not None:
        late_idx = int(late_bar_idx_in)
        session_idx = int(ohlcv_array_dict_in["bar_session_idx_arr"][late_idx])
        end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx])
        available_list[late_idx] = get_minute_bar_available_ts(timestamp_index[end_idx])
    return pd.DataFrame({"timestamp": list(timestamp_index),
                         "x": np.arange(len(timestamp_index), dtype=float) / max(len(timestamp_index) - 1, 1),
                         "available_ts": available_list})


# FUNCTION: PLANTED LABELS KNOWABLE ONE MINUTE AFTER THE ROW
def get_planted_label_pdf(ohlcv_array_dict_in):
    """
    label_known_ts is the end of the next bar (or NaT on the last bar of the file).

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.DataFrame: timestamp, y, label_known_ts
    """
    # THE NEXT BAR'S END IS STRICTLY AFTER THIS ROW'S DECISION MOMENT
    timestamp_index = ohlcv_array_dict_in["timestamp_index"]
    known_list = []
    y_list = []
    close_arr = np.asarray(ohlcv_array_dict_in["close_arr"], dtype=float)
    for bar_idx in range(len(timestamp_index)):
        if bar_idx + 1 >= len(timestamp_index):
            known_list.append(pd.NaT)
            y_list.append(np.nan)
            continue
        known_list.append(get_minute_bar_available_ts(timestamp_index[bar_idx + 1]))
        y_list.append(1.0 if close_arr[bar_idx + 1] > close_arr[bar_idx] else 0.0)
    return pd.DataFrame({"timestamp": list(timestamp_index), "y": y_list, "label_known_ts": known_list})


# FUNCTION: A CONTEXT WITH THE PLANTED FEATURE (AND OPTIONAL LABEL)
def get_minute_context(ohlcv_array_dict_in, late_bar_idx_in=None, label_bool_in=False):
    """
    Args:
        ohlcv_array_dict_in (dict): Bars
        late_bar_idx_in (int | None): Optional late feature bar
        label_bool_in (bool): Load the label source

    Returns:
        DataContext: Runner context
    """
    # DECLARED NAMES MATCH THE DESIGN
    register_minute_test_sources()
    frame_dict = {MINUTE_FEAT_STR: get_planted_feature_pdf(ohlcv_array_dict_in, late_bar_idx_in)}
    declared_list = list(minute_design.DATA_SOURCE_LIST)
    if label_bool_in:
        frame_dict[MINUTE_LABEL_STR] = get_planted_label_pdf(ohlcv_array_dict_in)
        if MINUTE_LABEL_STR not in declared_list:
            declared_list = list(declared_list) + [MINUTE_LABEL_STR]
    return get_runner_context(ohlcv_array_dict_in, source_frame_dict_in=frame_dict,
                              declared_name_list_in=declared_list)


# FUNCTION: A LATE FEATURE ROW STOPS THE RUN
def test_late_available_ts_stops():
    """
    Returns:
        None
    """
    # A MORNING BAR OF THE SECOND SESSION, WITH available_ts AT THAT SESSION'S LAST BAR
    register_minute_test_sources()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=3)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    late_bar_idx = int(ohlcv_array_dict["session_start_idx_arr"][1]) + 29
    data_context = get_minute_context(ohlcv_array_dict, late_bar_idx_in=late_bar_idx)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    raised_bool = False
    try:
        get_minute_row_pdf(minute_design, ohlcv_array_dict, date1, date2, data_context)
    except ValueError as error:
        message_str = str(error)
        assert "available_ts" in message_str
        raised_bool = True
    assert raised_bool, "a late available_ts should stop the run"
    passed("a row with available_ts after its moment stops the run")


# FUNCTION: NEIGHBOURING-ROW SIGNALS FAIL THE SHUFFLE CHECK
def test_neighbour_signal_refused():
    """
    Returns:
        None
    """
    # TEN ROWS, THREE LEAKS
    row_pdf = pd.DataFrame({"x": np.arange(10, dtype=float)})

    def shift_signal(rows_in, model_in):
        _ = model_in
        return pd.DataFrame({"enter": rows_in["x"].shift(1).fillna(0).to_numpy() > 0, "delta": [0.01] * len(rows_in)})

    def rolling_signal(rows_in, model_in):
        _ = model_in
        return pd.DataFrame({"enter": rows_in["x"].rolling(3, min_periods=1).mean().to_numpy() > 4.0,
                             "delta": [0.01] * len(rows_in)})

    def cumsum_signal(rows_in, model_in):
        _ = model_in
        return pd.DataFrame({"enter": rows_in["x"].cumsum().to_numpy() > 10.0, "delta": [0.01] * len(rows_in)})

    for name_str, signal_func in (("shift", shift_signal), ("rolling", rolling_signal), ("cumsum", cumsum_signal)):
        raised_bool = False
        try:
            get_shuffled_signal_list(row_pdf, None, signal_func, name_str, ["x"])
        except ValueError as error:
            assert "not row-local" in str(error)
            assert name_str in str(error)
            raised_bool = True
        assert raised_bool, f"{name_str} should fail the shuffle check"
    passed("shift, rolling and cumsum signals are refused by the shuffle check")


# FUNCTION: A COUNTER ACROSS CALLS FAILS THE SHUFFLE CHECK
def test_stateful_signal_refused():
    """
    Returns:
        None
    """
    # THE COUNTER LIVES ACROSS THE TWO SHUFFLE CALLS
    row_pdf = pd.DataFrame({"x": np.arange(8, dtype=float)})
    counter_dict = {"n": 0}

    def stateful_signal(rows_in, model_in):
        _ = model_in
        output_list = []
        for _row in range(len(rows_in)):
            counter_dict["n"] += 1
            output_list.append({"enter": counter_dict["n"] % 2 == 0, "delta": 0.01})
        return output_list

    raised_bool = False
    try:
        get_shuffled_signal_list(row_pdf, None, stateful_signal, "stateful", ["x"])
    except ValueError as error:
        assert "not row-local" in str(error)
        assert "stateful" in str(error)
        raised_bool = True
    assert raised_bool, "a stateful signal should fail the shuffle check"
    passed("a stateful signal (counter across calls) is refused")


# FUNCTION: PREFLIGHT REFUSES A METHOD OR A CLOSURE
def test_preflight_refuses_method_and_closure():
    """
    Returns:
        None
    """
    # A BOUND METHOD
    class MethodDesign:
        def signal(self, rows_in, model_in):
            _ = rows_in, model_in
            return []

    method_module = types.SimpleNamespace(signal=MethodDesign().signal, EXPERIMENT_NAME="method_design")
    raised_bool = False
    try:
        check_minute_signal(method_module)
    except ValueError as error:
        assert "method" in str(error)
        raised_bool = True
    assert raised_bool, "a method should be refused"

    def get_closure_signal():
        closed_int = 0

        def signal(rows_in, model_in):
            _ = closed_int, model_in
            return [{"enter": False, "delta": 0.01}] * len(rows_in)

        return signal

    closure_module = types.SimpleNamespace(signal=get_closure_signal(), EXPERIMENT_NAME="closure_design")
    raised_bool = False
    try:
        check_minute_signal(closure_module)
    except ValueError as error:
        assert "closure" in str(error)
        raised_bool = True
    assert raised_bool, "a closure should be refused"
    passed("preflight refuses a signal that is a method or a closure")


# FUNCTION: SCORING WINDOWS AND THE LABEL DOOR
def test_model_windows_and_label_door():
    """
    Returns:
        None
    """
    # A FEW WEEKS SO THERE IS MORE THAN ONE REFIT
    register_minute_test_sources()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-30", seed_in=6)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    minute_design.LABEL_SOURCE_LIST = [MINUTE_LABEL_STR]
    try:
        data_context = get_minute_context(ohlcv_array_dict, label_bool_in=True)
        date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
        design = minute_design.get_candidate_design("lo")
        loop = MinuteLoop(design, ohlcv_array_dict, date1, date2, data_context, None, 0.0, 0.0,
                          config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE, config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                          None, False, minute_design)
        loop.run_through_date(date2)
        assert len(loop.score_log_list) >= 2, "need at least two refit blocks"
        for log_dict in loop.score_log_list:
            refit_ts = get_ny_timestamp(log_dict["refit_ts"])
            next_refit_ts = log_dict["next_refit_ts"]
            for decision_ts in log_dict["decision_ts_list"]:
                row_ts = get_ny_timestamp(decision_ts)
                assert row_ts >= refit_ts, (row_ts, refit_ts)
                if next_refit_ts is not None:
                    assert row_ts < get_ny_timestamp(next_refit_ts), (row_ts, next_refit_ts)
        assert len(loop.train_log_list) >= 1
        for log_dict in loop.train_log_list:
            refit_ts = get_ny_timestamp(log_dict["refit_ts"])
            for label_ts in log_dict["label_known_ts_list"]:
                if pd.isna(label_ts):
                    raise AssertionError("unfinished labels must be dropped, not passed to fit")
                assert get_ny_timestamp(label_ts) < refit_ts, (label_ts, refit_ts)
    finally:
        if hasattr(minute_design, "LABEL_SOURCE_LIST"):
            delattr(minute_design, "LABEL_SOURCE_LIST")
    passed("a model never scores rows before its refit or after the next; training drops unfinished and future labels")



# FUNCTION: TRAINING USES EARLIER ROWS; CANDIDATES WITH ONE FIT KEY SHARE THE FIT
def test_history_and_shared_fit():
    """
    The scored span starts in the third week. With TRAIN_ROW_HISTORY_BOOL the first refit trains on the rows of the
    first two weeks (labels known before the refit only) and scores only the span. Two candidates with one fit key
    and a fit cache folder fit once per refit; the second candidate loads the first one's fit.

    Returns:
        None
    """
    # IMPORT THE CACHE SETTER HERE
    from so.runner.minute import set_fit_cache_folder_str
    register_minute_test_sources()
    ohlcv_array_dict = get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2010-06-01", "2010-07-09", seed_in=12))
    session_list = list(ohlcv_array_dict["session_date_list"])
    date1, date2 = session_list[10], session_list[-1]
    frame_dict = {MINUTE_FEAT_STR: get_planted_feature_pdf(ohlcv_array_dict),
                  MINUTE_LABEL_STR: get_planted_label_pdf(ohlcv_array_dict)}
    data_context = get_runner_context(ohlcv_array_dict, source_frame_dict_in=frame_dict,
                                      declared_name_list_in=list(shared_design.DATA_SOURCE_LIST))
    cache_folder_str = tempfile.mkdtemp(prefix="so_fit_cache_", dir=TEMP_ROOT_STR)
    set_fit_cache_folder_str(cache_folder_str)
    shared_design.FIT_CALL_LIST.clear()
    try:
        loop_list = []
        for candidate in shared_design.CANDIDATE_LIST:
            loop = MinuteLoop(shared_design.get_candidate_design(candidate), ohlcv_array_dict, date1, date2, data_context,
                              None, 0.0, 0.0, config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE,
                              config.MARKET_EXIT_SLIPPAGE_PER_SHARE, shared_design.__file__, True, shared_design)
            loop.run_through_date(date2)
            loop_list.append(loop)
    finally:
        set_fit_cache_folder_str(None)
    first_loop = loop_list[0]
    refit_count = len(first_loop.train_log_list)
    assert refit_count >= 3, refit_count
    # ONE REAL FIT PER REFIT, SHARED BY BOTH CANDIDATES
    assert len(shared_design.FIT_CALL_LIST) == refit_count, (shared_design.FIT_CALL_LIST, refit_count)
    # THE FIRST REFIT TRAINS ON ROWS BEFORE THE SCORED SPAN; EVERY LABEL WAS KNOWN BEFORE ITS REFIT
    first_rows = int(first_loop.train_log_list[0]["row_count"])
    assert first_rows > 0 and first_rows == shared_design.FIT_CALL_LIST[0]
    assert first_loop.current_model is not None
    for log_dict in first_loop.train_log_list:
        refit_ts = get_ny_timestamp(log_dict["refit_ts"])
        assert all(get_ny_timestamp(label_ts) < refit_ts for label_ts in log_dict["label_known_ts_list"])
    # SCORED ROWS ARE THE SPAN ONLY
    first_day = pd.Timestamp(date1).date()
    assert all(pd.Timestamp(day).date() >= first_day for day in first_loop.row_pdf["session"])
    passed(f"training uses {first_rows} rows from before the scored span at the first refit; "
           f"2 candidates share {refit_count} fits")


# FUNCTION: MINUTE MODE MATCHES THE OLD EXP01 SIMULATOR ON A FIXED MODEL
def test_parity_with_old_exp01_replay():
    """
    Returns:
        None
    """
    # TWO WEEKS, A FIXED THRESHOLD, THE SAME SAMPLED ROWS
    register_minute_test_sources()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-18", seed_in=8)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    data_context = get_minute_context(ohlcv_array_dict)
    date1, date2 = ohlcv_array_dict["session_date_list"][0], ohlcv_array_dict["session_date_list"][-1]
    design = minute_design.get_candidate_design("lo")
    runner_dict = run_minute_dict(design, ohlcv_array_dict, date1, date2, data_context, None, 0.0, 0.0,
                                  config.INITIAL_CAPITAL, config.ENTRY_SLIPPAGE_PER_SHARE,
                                  config.MARKET_EXIT_SLIPPAGE_PER_SHARE, None, minute_design)
    row_pdf = get_minute_row_pdf(minute_design, ohlcv_array_dict, date1, date2, data_context)
    decision_pdf = pd.DataFrame({
        "decision_ts": list(row_pdf["bar_ts"]),
        "buy_flag": row_pdf["x"].to_numpy(dtype=float) > 0.0,
        "delta": np.full(len(row_pdf), minute_design.DELTA, dtype=float),
    })
    sim_dict = simulate_decision_trading_dict(decision_pdf, ohlcv_array_dict)
    engine_pdf = runner_dict["trade_pdf"]
    sim_pdf = sim_dict["transaction_pdf"]
    assert len(engine_pdf) == len(sim_pdf), (len(engine_pdf), len(sim_pdf),
                                             engine_pdf["exit_reason"].tolist() if len(engine_pdf) else None,
                                             sim_pdf["exit_reason"].tolist() if len(sim_pdf) else None)
    if len(engine_pdf):
        assert list(engine_pdf["exit_reason"]) == list(sim_pdf["exit_reason"])
        assert np.allclose(engine_pdf["net_profit"].to_numpy(dtype=float), sim_pdf["net_profit"].to_numpy(dtype=float),
                           atol=float(config.NUMERIC_TOLERANCE))
        assert list(pd.to_datetime(engine_pdf["buy_ts"])) == list(pd.to_datetime(sim_pdf["buy_ts"]))
        assert list(pd.to_datetime(engine_pdf["sell_ts"])) == list(pd.to_datetime(sim_pdf["sell_ts"]))
    sim_equity_pdf = get_daily_equity_pdf(sim_pdf, ohlcv_array_dict, str(date1), str(date2), config.INITIAL_CAPITAL)
    runner_equity_pdf = runner_dict["daily_equity_pdf"]
    assert len(runner_equity_pdf) == len(sim_equity_pdf)
    assert np.allclose(runner_equity_pdf["equity"].to_numpy(dtype=float), sim_equity_pdf["equity"].to_numpy(dtype=float),
                       atol=float(config.NUMERIC_TOLERANCE))
    passed("minute-mode results match a hand-run of the old exp01 replay on a fixed model")


# FUNCTION: LOOK-AHEAD PASSES FOR A CLEAN MINUTE DESIGN
def test_lookahead_minute_passes():
    """
    Returns:
        None
    """
    # THREE INJECTED PERIODS, CUTS AT SESSION ENDS
    register_minute_test_sources()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    data_context = get_minute_context(ohlcv_array_dict)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    trial_log_path_str = get_test_trial_log_path_str("lookahead.csv")
    result_dict = run_development_dict(minute_design, ohlcv_array_dict, data_context_in=data_context,
                                       run_id_str_in="minute_lookahead", n_jobs_int_in=1, period_pdf_in=period_pdf,
                                       trial_log_path_str_in=trial_log_path_str, commit_str_in="testcommit",
                                       code_hash_str_in="testhash", check_clean_tree_bool_in=False,
                                       check_view_bool_in=False, baseline_seed_count_int_in=2)
    assert result_dict["lookahead_dict"]["status_str"] == LOOK_AHEAD_PASS_STR
    assert result_dict["lookahead_dict"]["pass_bool"] is True
    passed("look-ahead check passes for a clean minute design")


# FUNCTION: A CRASH AFTER A PERIOD RESUMES
def test_checkpoint_resume_matches():
    """
    Returns:
        None
    """
    # CRASH AFTER PERIOD 0, THEN RESUME
    register_minute_test_sources()
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-06-01", "2010-06-22", seed_in=4)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    data_context = get_minute_context(ohlcv_array_dict)
    period_pdf = get_injected_period_pdf(ohlcv_array_dict["session_date_list"])
    crash_log_str = get_test_trial_log_path_str("crash.csv")
    raised_bool = False
    try:
        run_development_dict(minute_design, ohlcv_array_dict, data_context_in=data_context,
                             run_id_str_in="minute_crash", n_jobs_int_in=1, period_pdf_in=period_pdf,
                             trial_log_path_str_in=crash_log_str, commit_str_in="testcommit",
                             code_hash_str_in="testhash", check_clean_tree_bool_in=False, check_view_bool_in=False,
                             baseline_seed_count_int_in=2, crash_after_period_id_in=0, run_lookahead_bool_in=False)
    except RuntimeError as error:
        assert "runner crash after period 0" in str(error)
        raised_bool = True
    assert raised_bool
    token_str = get_candidate_token_str(minute_design.CANDIDATE_LIST[0])
    checkpoint_dict = read_checkpoint_dict("minute_crash", token_str)
    assert checkpoint_dict is not None
    assert int(checkpoint_dict["period_id"]) == 0
    resume_dict = run_development_dict(minute_design, ohlcv_array_dict, data_context_in=data_context,
                                       run_id_str_in="minute_crash", n_jobs_int_in=1, period_pdf_in=period_pdf,
                                       trial_log_path_str_in=crash_log_str, commit_str_in="testcommit",
                                       code_hash_str_in="testhash", check_clean_tree_bool_in=False,
                                       check_view_bool_in=False, baseline_seed_count_int_in=2,
                                       run_lookahead_bool_in=False)
    clean_log_str = get_test_trial_log_path_str("clean.csv")
    clean_dict = run_development_dict(minute_design, ohlcv_array_dict, data_context_in=data_context,
                                      run_id_str_in="minute_clean", n_jobs_int_in=1, period_pdf_in=period_pdf,
                                      trial_log_path_str_in=clean_log_str, commit_str_in="testcommit",
                                      code_hash_str_in="testhash", check_clean_tree_bool_in=False,
                                      check_view_bool_in=False, baseline_seed_count_int_in=2,
                                      run_lookahead_bool_in=False)
    resume_equity = resume_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float)
    clean_equity = clean_dict["prior_only_dict"]["daily_equity_pdf"]["equity"].to_numpy(dtype=float)
    assert np.allclose(resume_equity, clean_equity, atol=float(config.NUMERIC_TOLERANCE))
    trial_pdf = read_trial_log_pdf(crash_log_str)
    period_id_list = sorted(set(int(period_id) for period_id in trial_pdf["fold_id"]))
    assert period_id_list == [0, 1, 2]
    passed("minute checkpoint after a period resumes and matches a clean run")


# FUNCTION: SPEED OF A 4-YEAR SYNTHETIC MINUTE RUN
def test_speed_four_year_lgbm():
    """
    Returns:
        None
    """
    # FOUR SYNTHETIC YEARS, TWELVE CANDIDATES, WEEKLY REFITS, EIGHT PROCESSES
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2010-01-04", "2013-12-31", seed_in=1)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_date_list = ohlcv_array_dict["session_date_list"]
    period_pdf = get_injected_period_pdf(session_date_list)
    data_context = get_runner_context(ohlcv_array_dict, declared_name_list_in=list(lgbm_design.DATA_SOURCE_LIST))
    trial_log_path_str = get_test_trial_log_path_str("speed.csv")
    start_time = time.perf_counter()
    result_dict = run_development_dict(lgbm_design, ohlcv_array_dict, data_context_in=data_context,
                                       run_id_str_in="minute_speed", n_jobs_int_in=8, period_pdf_in=period_pdf,
                                       trial_log_path_str_in=trial_log_path_str, commit_str_in="testcommit",
                                       code_hash_str_in="testhash", check_clean_tree_bool_in=False,
                                       check_view_bool_in=False, baseline_seed_count_int_in=2,
                                       run_lookahead_bool_in=False)
    elapsed_seconds = float(time.perf_counter() - start_time)
    year_span_float = 4.0
    projected_seconds = elapsed_seconds * (21.0 / year_span_float)
    assert "prior_only_dict" in result_dict
    print(f"SPEED 4y synthetic minute LightGBM 12 candidates weekly n_jobs=8: {elapsed_seconds:.1f} s")
    print(f"PROJECTED 2005-2025 (21y / 4y, linear): {projected_seconds:.1f} s "
          f"({projected_seconds / 60.0:.1f} min)")
    passed(f"4-year synthetic minute run timed ({elapsed_seconds:.1f} s; 2005-2025 ~ {projected_seconds:.1f} s)")


# FUNCTION: RUN EVERY TEST
def run_all_tests():
    """
    Returns:
        None
    """
    # UNIT CHECKS FIRST, THEN THE STREAM, THEN SPEED
    test_late_available_ts_stops()
    test_neighbour_signal_refused()
    test_stateful_signal_refused()
    test_preflight_refuses_method_and_closure()
    test_model_windows_and_label_door()
    test_history_and_shared_fit()
    test_parity_with_old_exp01_replay()
    test_lookahead_minute_passes()
    test_checkpoint_resume_matches()
    test_speed_four_year_lgbm()


if __name__ == "__main__":
    try:
        run_all_tests()
        print("All tests passed.")
    finally:
        unregister_minute_test_sources()
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REAL_WINDOWS_PATH_STR
        if OWNED_TEMP_BOOL:
            shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
