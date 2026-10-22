"""
Workspace Tests: rolling retraining (so.core.rolling_retrain; Nicolas, 2026-10-11)

Run from the workspace root:   python tests/test_rolling_retrain.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

Synthetic data only. The registry, the ledger, the trial log and SO_DATA_PATH are temporary. The data root is a
temporary folder. records/holdout_windows.csv is not written. SO_HOLDOUT_PATH and SO_HOLDOUT_EVALUATION_TOKEN are set
only inside this file, to temporary values. No experiment is run.
"""

import os
import sys
import types
import tempfile
import shutil
from io import StringIO
import numpy as np
import pandas as pd

# POINT THE DATA ROOT AT AN EMPTY TEMPORARY FOLDER BEFORE so.paths IS IMPORTED
TEMP_ROOT_STR = tempfile.mkdtemp(prefix="so_retrain_data_")
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
from so.core.holdout import (compute_holdout_window_dict, get_active_holdout_window_dict, get_prior_only_result_dict,
                            open_holdout_window_dict, run_holdout_evaluation)
from so.core.point_in_time import check_feature_available_ts, get_decision_ts
from so.core.rolling_retrain import (
    get_retrain_session_list, get_training_mask_arr, get_barrier_label_known_ts_arr, get_fixed_horizon_label_known_ts_arr,
    get_label_known_ts_pdf, run_rolling_retrain_dict, run_rolling_retrain_candidate_dict, get_rolling_candidate_selection_pdf,
    fit_mean_label_dict, predict_constant_arr)
from so.core.evaluation import (get_performance_over_time_pdf, get_performance_quarter_pdf, get_turnover_switch_dict,
                                get_refit_report_dict, get_pooled_selection_pdf, get_report_float_str, get_tolerance_comparison_dict)
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_session_decision_idx_dict

# KEEP THE REAL PATHS AND POINT THE SUITE AT TEMPORARY FILES
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REAL_WINDOWS_EXISTS_BOOL = os.path.isfile(REAL_WINDOWS_PATH_STR)
REAL_WINDOWS_SIZE_INT = os.path.getsize(REAL_WINDOWS_PATH_STR) if REAL_WINDOWS_EXISTS_BOOL else None
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = os.path.join(TEMP_ROOT_STR, "holdout_windows.csv")
NY_TZ_STR = "America/New_York"

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
    print(f"  {name_str_in}")

# FUNCTION: A NEW YORK TIMESTAMP ON A CALENDAR DAY
def get_ny_ts(day_str_in, hour_int_in=15, minute_int_in=59):
    """
    Builds a New York timestamp.

    Args:
        day_str_in (str): Calendar day
        hour_int_in (int): Hour
        minute_int_in (int): Minute

    Returns:
        pd.Timestamp: Timestamp
    """
    # LOCALIZE THE CLOCK
    return pd.Timestamp(f"{day_str_in} {hour_int_in:02d}:{minute_int_in:02d}").tz_localize(NY_TZ_STR)

# FUNCTION: ONE LABELLED ROW
def get_row_dict(day_str_in, label_known_ts_in, label_float_in, feature_float_in=0.1, available_ts_in=None):
    """
    One synthetic decision row. available_ts defaults to the decision, so the feature is knowable then.

    Args:
        day_str_in (str): Session
        label_known_ts_in (pd.Timestamp | None): Label clock (NaT allowed)
        label_float_in (float): Label (NaN allowed)
        feature_float_in (float): The single feature
        available_ts_in (pd.Timestamp | None): Feature clock

    Returns:
        dict: One row
    """
    # THE DECISION MOMENT IS 15:59
    decision_ts = get_ny_ts(day_str_in)
    return {"session": pd.Timestamp(day_str_in).date(), "row_ts": decision_ts, "decision_ts": decision_ts,
            "label_known_ts": label_known_ts_in, "available_ts": decision_ts if available_ts_in is None else available_ts_in,
            "x": float(feature_float_in) if np.isfinite(feature_float_in) else feature_float_in, "y": label_float_in}

# FUNCTION: TEST 1, RETRAIN SESSIONS
def test_retrain_sessions():
    """
    Weekly with a Monday holiday starts on Tuesday. Monthly, quarterly and daily match. The first session of the span
    is a refit even when it is not the first session of its week.

    Returns:
        None
    """
    # 2024-01-01 WAS A MONDAY AND A MARKET HOLIDAY; THE WEEK STARTS ON TUESDAY 2024-01-02
    session_date_list = [pd.Timestamp(day_str).date() for day_str in
                         ["2023-12-26", "2023-12-27", "2023-12-28", "2023-12-29", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]]
    weekly_list = get_retrain_session_list(session_date_list, "2023-12-26", "2024-01-09", "weekly")
    # TUESDAY 2024-01-02 IS THE FIRST SESSION OF THAT ISO WEEK; MONDAY 2024-01-08 IS THE NEXT
    assert pd.Timestamp("2024-01-02").date() in weekly_list
    assert pd.Timestamp("2024-01-01").date() not in weekly_list
    assert pd.Timestamp("2024-01-03").date() not in weekly_list
    assert pd.Timestamp("2024-01-08").date() in weekly_list
    assert weekly_list[0] == pd.Timestamp("2023-12-26").date()
    # A SPAN THAT STARTS ON WEDNESDAY STILL REFITS THAT WEDNESDAY
    midweek_list = get_retrain_session_list(session_date_list, "2024-01-03", "2024-01-09", "weekly")
    assert midweek_list[0] == pd.Timestamp("2024-01-03").date()
    assert pd.Timestamp("2024-01-08").date() in midweek_list
    assert pd.Timestamp("2024-01-04").date() not in midweek_list
    # MONTHLY, QUARTERLY AND DAILY
    month_list = [pd.Timestamp(day_str).date() for day_str in ["2024-01-31", "2024-02-01", "2024-02-02", "2024-03-01"]]
    assert get_retrain_session_list(month_list, month_list[0], month_list[-1], "monthly") == [month_list[0], month_list[1], month_list[3]]
    quarter_list = [pd.Timestamp(day_str).date() for day_str in ["2024-03-28", "2024-04-01", "2024-04-02", "2024-07-01"]]
    assert get_retrain_session_list(quarter_list, quarter_list[0], quarter_list[-1], "quarterly") == [quarter_list[0], quarter_list[1], quarter_list[3]]
    assert get_retrain_session_list(month_list, month_list[0], month_list[-1], "daily") == month_list
    # AN UNKNOWN FREQUENCY RAISES
    try:
        get_retrain_session_list(month_list, month_list[0], month_list[-1], "hourly")
        raise AssertionError("an unknown frequency was accepted")
    except ValueError as error:
        assert "frequency" in str(error)
    passed("1 retrain sessions (Monday holiday -> Tuesday; monthly; quarterly; daily; first session of the span)")

# FUNCTION: TEST 2, THE PURGE
def test_purge():
    """
    No training row has label_known_ts at or after the retraining decision. A barrier hit two sessions later is usable
    only from that hit onward. A fixed 20-session label is excluded for the last 20 sessions.

    Returns:
        None
    """
    # A CLOCK AT THE DECISION IS NOT USABLE; A CLOCK ONE MINUTE EARLIER IS
    decision_ts = get_ny_ts("2024-06-10")
    early_ts = decision_ts - pd.Timedelta(minutes=1)
    row_pdf = pd.DataFrame([
        get_row_dict("2024-06-03", early_ts, 1.0),
        get_row_dict("2024-06-04", decision_ts, 1.0),
        get_row_dict("2024-06-05", decision_ts + pd.Timedelta(days=1), 1.0),
    ])
    mask_arr = get_training_mask_arr(row_pdf["row_ts"], row_pdf["label_known_ts"], decision_ts, "ALL")
    assert list(mask_arr) == [True, False, False]
    used_known = [pd.Timestamp(label_ts) for label_ts, keep in zip(row_pdf["label_known_ts"], mask_arr) if keep]
    assert all(label_ts < decision_ts for label_ts in used_known)
    # A BARRIER HIT TWO SESSIONS AFTER THE ROW (2024-06-03 HIT AT 2024-06-05 10:00)
    hit_label_ts = get_ny_ts("2024-06-05", 10, 0)
    known_ts = get_barrier_label_known_ts_arr([hit_label_ts])[0]
    assert known_ts == hit_label_ts + pd.Timedelta(minutes=1)
    barrier_pdf = pd.DataFrame([get_row_dict("2024-06-03", known_ts, 1.0)])
    # REGISTERED TSBAR USES THE SAME END-OF-BAR CLOCK
    registered_pdf = get_label_known_ts_pdf(pd.DataFrame({"exit_ts": [hit_label_ts]}), source_name_str_in="TSBAR")
    assert pd.Timestamp(registered_pdf["label_known_ts"].iloc[0]) == known_ts
    before_hit = get_training_mask_arr(barrier_pdf["row_ts"], barrier_pdf["label_known_ts"], get_ny_ts("2024-06-04"), "ALL")
    at_hit_open = get_training_mask_arr(barrier_pdf["row_ts"], barrier_pdf["label_known_ts"], get_ny_ts("2024-06-05", 10, 0), "ALL")
    after_hit = get_training_mask_arr(barrier_pdf["row_ts"], barrier_pdf["label_known_ts"], get_ny_ts("2024-06-05"), "ALL")
    assert list(before_hit) == [False] and list(at_hit_open) == [False] and list(after_hit) == [True]
    # A FIXED 20-SESSION LABEL: THE LAST 20 ROWS HAVE NO LATER SESSION
    day_list = list(pd.bdate_range("2024-01-02", periods=25))
    decision_list = [get_ny_ts(str(day.date())) for day in day_list]
    horizon_known = get_fixed_horizon_label_known_ts_arr(decision_list, 20)
    assert all(pd.isna(label_ts) for label_ts in horizon_known[-20:])
    assert pd.Timestamp(horizon_known[0]) == decision_list[20]
    horizon_mask = get_training_mask_arr(decision_list, horizon_known, decision_list[-1], "ALL")
    assert not horizon_mask[-20:].any()
    # THE ROW WHOSE CLOCK EQUALS THE RETRAIN DECISION IS ALSO OUT (STRICTLY BEFORE)
    assert horizon_mask[-21] == False
    assert horizon_mask[-22] == True
    # A FINITE LABEL WITH NO CLOCK RAISES
    try:
        get_label_known_ts_pdf(pd.DataFrame({"y": [1.0]}))
        raise AssertionError("a labelled row without label_known_ts was accepted")
    except ValueError as error:
        assert "label_known_ts" in str(error)
    passed("2 purge (no label_known_ts at or after the decision; barrier usable from the hit; fixed 20 excluded for the last 20)")
    print(f"    test 2 detail: barrier known {known_ts}; last-20 excluded {int((~horizon_mask[-20:]).sum())} of 20; equality row excluded")

# FUNCTION: TEST 3, DROP RATHER THAN FILL
def test_drop_not_fill():
    """
    Unfinished rows are absent from the fit input. No NaN label is handed to the fit, and a missing label is not replaced by 0.

    Returns:
        None
    """
    # SIX FINISHED LABELS AND FOUR UNFINISHED ONES (NaN, CLOCK IN THE FUTURE)
    row_dict_list = []
    for row_idx, day in enumerate(pd.bdate_range("2024-03-01", periods=10)):
        if row_idx < 6:
            row_dict_list.append(get_row_dict(str(day.date()), get_ny_ts("2024-01-02"), float(row_idx + 1)))
        else:
            row_dict_list.append(get_row_dict(str(day.date()), get_ny_ts("2024-12-31"), np.nan))
    row_pdf = pd.DataFrame(row_dict_list)
    seen_list = []
    # THE FIT RECORDS EXACTLY THE FRAME IT WAS GIVEN
    def fit_record_dict(train_pdf_in, feature_col_list_in, label_col_str_in, seed_int_in):
        seen_list.append(train_pdf_in.copy())
        return fit_mean_label_dict(train_pdf_in, feature_col_list_in, label_col_str_in, seed_int_in)
    decision_day = str(row_pdf["session"].iloc[-1])
    result_dict = run_rolling_retrain_dict(row_pdf, ["x"], "y", fit_record_dict, predict_constant_arr,
                                           [row_pdf["session"].iloc[-1]], "ALL", "daily", 1, 1, True)
    fit_pdf = seen_list[0]
    mask_arr = get_training_mask_arr(row_pdf["row_ts"], row_pdf["label_known_ts"], get_ny_ts(decision_day), "ALL")
    # THE MASKED FINITE ROWS, AND ONLY THOSE, REACH THE FIT
    assert len(fit_pdf) == int(mask_arr.sum()) == 6
    assert set(fit_pdf["session"]) == set(row_pdf["session"].iloc[:6])
    assert list(fit_pdf["y"]) == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert fit_pdf["y"].isna().sum() == 0
    assert 0.0 not in set(fit_pdf["y"])
    assert result_dict["refit_log_pdf"]["rows_purged"].iloc[0] == 4
    assert result_dict["refit_log_pdf"]["rows_used"].iloc[0] == 6
    passed("3 drop, not fill (unfinished rows absent; no 0 and no NaN label in the fit)")

# FUNCTION: TEST 4, THE TRAINING WINDOWS
def test_windows():
    """
    6M, 2Y, 10Y and ALL keep exactly the row dates on or after the window start.

    Returns:
        None
    """
    # BOUNDARY DATES AROUND A RETRAIN ON 2024-07-15
    day_list = ["2000-01-03", "2014-07-14", "2014-07-15", "2022-07-14", "2022-07-15", "2024-01-14", "2024-01-15", "2024-07-14"]
    known_ts = get_ny_ts("1999-01-04")
    row_pdf = pd.DataFrame([get_row_dict(day_str, known_ts, 1.0) for day_str in day_list])
    decision_ts = get_ny_ts("2024-07-15")
    expected_dict = {
        "6M": ["2024-01-15", "2024-07-14"],
        "2Y": ["2022-07-15", "2024-01-14", "2024-01-15", "2024-07-14"],
        "3Y": ["2022-07-14", "2022-07-15", "2024-01-14", "2024-01-15", "2024-07-14"],
        "5Y": ["2022-07-14", "2022-07-15", "2024-01-14", "2024-01-15", "2024-07-14"],
        "10Y": ["2014-07-15", "2022-07-14", "2022-07-15", "2024-01-14", "2024-01-15", "2024-07-14"],
        "ALL": day_list,
    }
    # EACH WINDOW KEEPS THOSE DATES AND NO OTHERS
    for window_str, expected_list in expected_dict.items():
        mask_arr = get_training_mask_arr(row_pdf["row_ts"], row_pdf["label_known_ts"], decision_ts, window_str)
        kept_list = [str(day) for day, keep in zip(row_pdf["session"], mask_arr) if keep]
        assert kept_list == expected_list, (window_str, kept_list)
    passed("6 windows (6M, 2Y, 3Y, 5Y, 10Y, ALL keep exactly the boundary dates)")

# FUNCTION: TEST 5, THE MODEL BETWEEN REFITS
def test_model_id_held():
    """
    Every prediction between two refits uses the last fitted model_id.

    Returns:
        None
    """
    # TWO WEEKS: TUESDAY 2024-01-02 (MONDAY WAS A HOLIDAY) THROUGH TUESDAY 2024-01-09
    day_list = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08", "2024-01-09"]
    row_pdf = pd.DataFrame([get_row_dict(day_str, get_ny_ts("2020-01-02"), 1.0) for day_str in day_list])
    result_dict = run_rolling_retrain_dict(row_pdf, ["x"], "y", fit_mean_label_dict, predict_constant_arr,
                                           row_pdf["session"], "ALL", "weekly", 3, 1, True)
    prediction_pdf = result_dict["prediction_pdf"]
    # THE FIRST FOUR SESSIONS SHARE THE FIRST MODEL; THE NEXT WEEK IS A NEW ONE
    assert list(prediction_pdf["model_id"]) == [0, 0, 0, 0, 1, 1]
    assert list(result_dict["refit_log_pdf"]["retrain_session"]) == [pd.Timestamp("2024-01-02").date(), pd.Timestamp("2024-01-08").date()]
    passed("5 model id held between refits")

# FUNCTION: TEST 6, A FEATURE KNOWN AFTER THE DECISION
def test_feature_leak():
    """
    check_feature_available_ts raises when a feature clock is after the decision, and the rolling fit raises the same way.

    Returns:
        None
    """
    # THE FEATURE CLOCK IS ONE MINUTE AFTER THE DECISION
    decision_ts = get_ny_ts("2024-04-01")
    late_ts = decision_ts + pd.Timedelta(minutes=1)
    feature_pdf = pd.DataFrame({"available_ts": [late_ts], "x": [1.0]})
    try:
        check_feature_available_ts(feature_pdf, [decision_ts])
        raise AssertionError("a late feature was accepted")
    except ValueError as error:
        assert "available_ts" in str(error)
    # THE ROLLING FIT USES THAT SAME CHECK
    row_pdf = pd.DataFrame([get_row_dict("2024-04-01", get_ny_ts("2020-01-02"), 1.0, available_ts_in=late_ts)])
    try:
        run_rolling_retrain_dict(row_pdf, ["x"], "y", fit_mean_label_dict, predict_constant_arr,
                                 row_pdf["session"], "ALL", "daily", 1, 1, True)
        raise AssertionError("a rolling fit accepted a late feature")
    except ValueError as error:
        assert "available_ts" in str(error)
    passed("6 feature leak (check_feature_available_ts raises; the rolling fit raises the same check)")

# FUNCTION: FOUR BARS A DAY SO THE DECISION IS 15:58 AND THE CLOSE IS THE NEXT BAR
def get_four_bar_ohlcv_pdf(session_date_list_in, seed_int_in):
    """
    Four bars per session: 09:30, 15:57, 15:58, 15:59. The decision bar is 15:58. The close is 15:59, after it.

    Args:
        session_date_list_in (list): Sessions
        seed_int_in (int): Price seed

    Returns:
        pd.DataFrame: Minute bars
    """
    # A SMALL RANDOM WALK, ONE PRICE PER BAR
    rng = np.random.default_rng(seed_int_in)
    price_float = 100.0
    row_dict_list = []
    for session_date in session_date_list_in:
        for hour_int, minute_int in [(9, 30), (15, 57), (15, 58), (15, 59)]:
            open_float = price_float
            price_float = price_float * float(np.exp(rng.normal(0.0, 0.01)))
            close_float = price_float
            row_dict_list.append({"timestamp": pd.Timestamp(year=session_date.year, month=session_date.month, day=session_date.day,
                                                            hour=hour_int, minute=minute_int, tz=NY_TZ_STR),
                                  "open": open_float, "high": max(open_float, close_float) + 0.01,
                                  "low": min(open_float, close_float) - 0.01, "close": close_float, "volume": 1000})
    return pd.DataFrame(row_dict_list)

# FUNCTION: LABELLED ROWS WHOSE LABEL IS THE CLOSE `horizon` SESSIONS LATER
def get_horizon_row_pdf(ohlcv_array_dict_in, horizon_int_in):
    """
    One row per session. The label is the close of the session horizon_int_in sessions later. Its clock is that
    session's decision moment. The feature is the previous session's close, knowable at this decision.

    Args:
        ohlcv_array_dict_in (dict): Bars
        horizon_int_in (int): Horizon in sessions

    Returns:
        pd.DataFrame: Rows for run_rolling_retrain_dict
    """
    # DECISION MOMENTS AND SESSION CLOSES
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    decision_list = [get_decision_ts(ohlcv_array_dict_in["timestamp_index"][int(bar_idx)]) for bar_idx in idx_dict["decision_idx_arr"]]
    close_arr = ohlcv_array_dict_in["close_arr"][ohlcv_array_dict_in["session_end_idx_arr"]].astype(float)
    known_arr = get_fixed_horizon_label_known_ts_arr(decision_list, horizon_int_in)
    row_dict_list = []
    for row_idx, session_date in enumerate(session_date_list):
        label_float = np.nan if row_idx + horizon_int_in >= len(session_date_list) else float(close_arr[row_idx + horizon_int_in])
        feature_float = np.nan if row_idx == 0 else float(close_arr[row_idx - 1])
        row_dict_list.append({"session": session_date, "row_ts": decision_list[row_idx], "decision_ts": decision_list[row_idx],
                              "label_known_ts": known_arr[row_idx], "available_ts": decision_list[row_idx],
                              "x": feature_float, "y": label_float})
    return pd.DataFrame(row_dict_list)

# FUNCTION: A ONE-CANDIDATE DESIGN THAT TRAINS WITH OR WITHOUT THE PURGE
def get_purge_design(purge_bool_in, name_str_in, horizon_int_in=5, warmup_int_in=40):
    """
    Daily predictions from a mean of the training labels. purge_bool_in False keeps labels that are not yet knowable.

    Args:
        purge_bool_in (bool): Drop unfinished labels
        name_str_in (str): Experiment name (also the design hash input)
        horizon_int_in (int): Label horizon
        warmup_int_in (int): First decision session index

    Returns:
        module: Design
    """
    # THE MODULE THE RUNNER CALLS
    design_module = types.ModuleType(name_str_in)
    design_module.EXPERIMENT_NAME = name_str_in
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = ["6M"]
    design_module.SELECTION_RULE = {"pooled_periods": 4, "tie_break": [("candidate", True)]}
    design_module.RETRAIN_FREQUENCY_STR = "weekly"
    design_module.TRAIN_WINDOW_CANDIDATE_LIST = ["6M"]
    # THE PERIOD SCORE DOES NOT READ PRICES
    def run_candidate_replay_dict(ohlcv_array_dict, date1, date2, candidate, data_context_in=None):
        return {"daily_equity_pdf": pd.DataFrame({"date": [pd.Timestamp(date2).date()], "equity": [config.INITIAL_CAPITAL], "in_position": [True], "weight": [1.0]}),
                "trade_pdf": pd.DataFrame()}
    # THE PATH'S WEIGHT IS THE MODEL'S PREDICTION
    def run_prior_only_path_dict(ohlcv_array_dict, period_pdf, selection_pdf, data_context_in=None):
        row_pdf = get_horizon_row_pdf(ohlcv_array_dict, horizon_int_in)
        decision_list = list(row_pdf["session"].iloc[warmup_int_in:])
        result_dict = run_rolling_retrain_dict(row_pdf, ["x"], "y", fit_mean_label_dict, predict_constant_arr,
                                              decision_list, "6M", "weekly", 11, 15, purge_bool_in)
        prediction_pdf = result_dict["prediction_pdf"]
        pred_dict = {session_date: float(prediction) for session_date, prediction in zip(prediction_pdf["session"], prediction_pdf["prediction"])}
        date1 = pd.Timestamp(period_pdf["period_start"].iloc[0]).date()
        date2 = pd.Timestamp(period_pdf["period_end"].iloc[-1]).date()
        row_dict_list, weight_list, signal_list, session_list = [], [], [], []
        for session_date in row_pdf["session"]:
            if not (date1 <= session_date <= date2) or session_date not in pred_dict:
                continue
            weight_float = float(pred_dict[session_date])
            row_dict_list.append({"date": session_date, "equity": config.INITIAL_CAPITAL, "in_position": True, "weight": weight_float})
            weight_list.append(weight_float)
            signal_list.append(weight_float)
            session_list.append(session_date)
        # REFITS WHOSE MODEL WAS USED ON THE PATH
        used_id_set = set(prediction_pdf["model_id"])
        refit_pdf = result_dict["refit_log_pdf"]
        refit_pdf = refit_pdf[refit_pdf["model_id"].isin(used_id_set)].copy()
        return {"daily_equity_pdf": pd.DataFrame(row_dict_list), "trade_pdf": pd.DataFrame(),
                "target_weight_arr": np.asarray(weight_list, dtype=float), "signal_arr": np.asarray(signal_list, dtype=float),
                "decision_session_list": session_list, "refit_log_pdf": refit_pdf}
    design_module.run_candidate_replay_dict = run_candidate_replay_dict
    design_module.run_prior_only_path_dict = run_prior_only_path_dict
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict, date1, date2: {"flat": 0.0}
    return design_module

# FUNCTION: TEST 7, THE HOLDOUT TRUNCATION TEST CATCHES A LABEL LEAK
def test_label_leak():
    """
    A design that trains on unfinished labels is invalid_lookahead. The same design with the purge is valid.
    The real trial log is not written.

    Returns:
        None
    """
    # SESSIONS LONG ENOUGH FOR A 1-YEAR TRAINING WINDOW AND A 12-MONTH HOLDOUT
    session_date_list = [day.date() for day in pd.bdate_range("2021-01-04", "2024-06-28")]
    ohlcv_pdf = get_four_bar_ohlcv_pdf(session_date_list, 5)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    window_dict = compute_holdout_window_dict(session_date_list)
    open_holdout_window_dict(session_date_list, f"OPEN {window_dict['start']} {window_dict['end']}", file_path_str_in=paths.HOLDOUT_WINDOWS_FILE_PATH_STR)
    # TOKEN AND RESULTS OUTSIDE THE REPOSITORY AND THE DATA FOLDER
    token_dir_str = tempfile.mkdtemp(prefix="so_retrain_token_")
    token_path_str = os.path.join(token_dir_str, "token.txt")
    with open(token_path_str, "w", encoding="utf-8") as token_file:
        token_file.write("retrain-token\n")
    results_path_str = tempfile.mkdtemp(prefix="so_retrain_results_")
    os.environ["SO_HOLDOUT_PATH"] = results_path_str
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "retrain-token"
    git_dict = {"clean_bool": True, "on_main_bool": True, "preregister_bool": True, "commit_str": "abc123",
                "design_tree_str": "retrain-design", "so_tree_str": "retrain-so"}
    ledger_path_str = os.path.join(TEMP_ROOT_STR, "retrain_evaluations.csv")
    trial_path_str = os.path.join(TEMP_ROOT_STR, "retrain_trial_log.csv")
    # THE PURGE-OFF DESIGN IS REJECTED AND WRITES NO DAILY PATH
    leak_stdout = StringIO()
    saved_stdout = sys.stdout
    sys.stdout = leak_stdout
    try:
        leak_row = run_holdout_evaluation(get_purge_design(False, "exp_retrain_purge_off"), "purge_off", ohlcv_array_dict,
                                          token_path_str, git_dict, ledger_path_str_in=ledger_path_str, trial_log_path_str_in=trial_path_str)
    finally:
        sys.stdout = saved_stdout
    assert leak_row["status"] == "invalid_lookahead"
    assert "invalid_lookahead" in leak_stdout.getvalue()
    assert not os.path.isfile(os.path.join(results_path_str, leak_row["window_id"], "purge_off", "strategy_daily_equity.csv"))
    # THE SAME DESIGN WITH THE PURGE PASSES, AND THE REFIT LOG IS SAVED ONLY UNDER THE TEMPORARY RESULTS FOLDER
    git_dict["design_tree_str"] = "retrain-design-purged"
    valid_row = run_holdout_evaluation(get_purge_design(True, "exp_retrain_purge_on"), "purge_on", ohlcv_array_dict,
                                       token_path_str, git_dict, ledger_path_str_in=ledger_path_str, trial_log_path_str_in=trial_path_str)
    assert valid_row["status"] == "valid"
    refit_path_str = os.path.join(results_path_str, valid_row["window_id"], "purge_on", "refit_log.csv")
    assert os.path.isfile(refit_path_str)
    assert int(valid_row["holdout_refit_count"]) > 0
    if REAL_WINDOWS_EXISTS_BOOL:
        assert os.path.getsize(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_SIZE_INT
    else:
        assert not os.path.isfile(REAL_WINDOWS_PATH_STR)
    passed("7 label leak (purge off -> invalid_lookahead; purge on -> valid)")
    print(f"    test 7 detail: purge off {leak_row['status']}; purge on {valid_row['status']}; holdout refits {valid_row['holdout_refit_count']}; share purged {valid_row['average_share_purged']}")
    # CLEAR THE EVALUATION ENVIRONMENT
    os.environ.pop("SO_HOLDOUT_PATH", None)
    os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
    shutil.rmtree(token_dir_str, ignore_errors=True)
    shutil.rmtree(results_path_str, ignore_errors=True)

# FUNCTION: TEST 8, THE SAME SEED WITH 1 WORKER AND WITH 4
def test_determinism():
    """
    Two training windows, same seed, same predictions with 1 worker and with 4.

    Returns:
        None
    """
    # THIRTY SESSIONS, LABELS ALREADY KNOWABLE, TWO WINDOWS
    day_list = list(pd.bdate_range("2023-01-02", periods=30))
    row_dict_list = []
    for row_idx, day in enumerate(day_list):
        row_dict_list.append(get_row_dict(str(day.date()), get_ny_ts("2020-01-02"), float((row_idx % 5) - 1), feature_float_in=float(row_idx) / 30.0))
    row_pdf = pd.DataFrame(row_dict_list)
    decision_list = list(row_pdf["session"].iloc[10:])
    one_dict = run_rolling_retrain_candidate_dict(row_pdf, ["x"], "y", fit_mean_label_dict, predict_constant_arr,
                                                  decision_list, ["6M", "2Y"], "weekly", 19, 5, job_count_in=1)
    four_dict = run_rolling_retrain_candidate_dict(row_pdf, ["x"], "y", fit_mean_label_dict, predict_constant_arr,
                                                   decision_list, ["6M", "2Y"], "weekly", 19, 5, job_count_in=4)
    # EVERY WINDOW MATCHES, IN THE REQUESTED ORDER
    for window_str in ["6M", "2Y"]:
        assert list(one_dict[window_str]["prediction_pdf"]["prediction"]) == list(four_dict[window_str]["prediction_pdf"]["prediction"])
        assert list(one_dict[window_str]["prediction_pdf"]["model_id"]) == list(four_dict[window_str]["prediction_pdf"]["model_id"])
    passed("8 determinism (1 worker and 4 workers, same seed, same predictions)")

# FUNCTION: TEST 9, FOUR-QUARTER POOLED SELECTION
def test_selection():
    """
    A candidate that wins one quarter by a lot and loses the other three is not selected over a consistent one.
    A tie takes the longer training window.

    Returns:
        None
    """
    # FOLDS 1-4 ARE THE HISTORY; FOLD 5 IS THE QUARTER BEING GOVERNED (ITS OWN SCORE MUST NOT DECIDE)
    row_dict_list = []
    short_list = [10.0, -4.0, -4.0, -4.0, 100.0]
    long_list = [0.2, 0.2, 0.2, 0.2, 0.2]
    for fold_id, (short_float, long_float) in enumerate(zip(short_list, long_list), start=1):
        row_dict_list.append({"fold_id": fold_id, "train_window": "6M", "excess_return": short_float})
        row_dict_list.append({"fold_id": fold_id, "train_window": "10Y", "excess_return": long_float})
    selection_pdf = get_rolling_candidate_selection_pdf(pd.DataFrame(row_dict_list), ["train_window"], "excess_return", 4, None)
    governed_pdf = selection_pdf[selection_pdf["fold_id"] == 5]
    assert len(governed_pdf) == 1
    assert governed_pdf["train_window"].iloc[0] == "10Y"
    # EQUAL POOLED SCORES: THE LONGER WINDOW WINS
    tie_pdf = pd.DataFrame([{"fold_id": fold_id, "train_window": window_str, "excess_return": 1.0}
                            for fold_id in range(1, 6) for window_str in ["6M", "10Y"]])
    tie_selection_pdf = get_rolling_candidate_selection_pdf(tie_pdf, ["train_window"], "excess_return", 4, None)
    assert tie_selection_pdf.loc[tie_selection_pdf["fold_id"] == 5, "train_window"].iloc[0] == "10Y"
    passed("9 selection (a one-quarter spike loses to a consistent window; a tie takes the longer window)")
    print(f"    test 9 detail: quarter 5 candidate {governed_pdf['train_window'].iloc[0]}; tie candidate 10Y")

# FUNCTION: TEST 9B, SCORES WITHIN 1e-6 ARE TIED AND THE STORED SCORE STAYS EXACT
def test_numeric_tolerance():
    """
    Scores within NUMERIC_TOLERANCE of the best score take the tie order. A gap of 1e-5 does not. The stored pooled
    score is the unrounded mean. A comparison reports the maximum absolute difference.

    Returns:
        None
    """
    # SELECT ONE FOLD. TIE ORDER IS ASCENDING, SO THE SMALLEST tie_order WINS A TIE.
    def get_selected_row(score_list_in, order_list_in):
        score_pdf = pd.DataFrame({"fold_id": [1] * len(score_list_in), "candidate": [f"c{idx}" for idx in range(len(score_list_in))],
                                  "excess_return": score_list_in, "tie_order": order_list_in})
        return get_pooled_selection_pdf(score_pdf, ["candidate"], "excess_return", 1, [("tie_order", True)]).iloc[0]
    # 0, +1e-16 AND -1e-16 ARE ONE TIE. THE NUMERIC MAXIMUM IS c1. THE TIE ORDER SELECTS c2.
    noise_row = get_selected_row([0.0, 1e-16, -1e-16], [1, 2, 0])
    assert noise_row["candidate"] == "c2" and noise_row["pooled_score"] == -1e-16
    # 0.0123455 - 0.0123450 = 5e-7, INSIDE THE BAND. THE NUMERIC MAXIMUM IS c1. THE TIE ORDER SELECTS c0.
    close_row = get_selected_row([0.0123450, 0.0123455], [0, 1])
    assert close_row["candidate"] == "c0" and close_row["pooled_score"] == 0.0123450
    # A GAP OF 1e-5 IS OUTSIDE THE BAND. THE HIGHER SCORE WINS, AND ITS STORED SCORE IS NOT ROUNDED.
    apart_row = get_selected_row([0.0, 1e-5], [0, 1])
    assert apart_row["candidate"] == "c1" and apart_row["pooled_score"] == 1e-5
    # DISPLAY USES 6 DECIMAL PLACES. THE COMPARISON COUNTS A 1e-16 GAP AS A MATCH AND STILL REPORTS IT.
    assert config.NUMERIC_TOLERANCE == 1e-6 and config.REPORT_DECIMALS == 6
    assert get_report_float_str(0.01234549) == "0.012345"
    comparison_dict = get_tolerance_comparison_dict([0.0, 0.0], [1e-16, 1e-5])
    assert comparison_dict["match_count"] == 1 and comparison_dict["row_count"] == 2 and comparison_dict["max_abs_diff"] == abs(1e-5)
    passed("9b numeric tolerance (1e-16 and 5e-7 tie; 1e-5 does not; stored score stays exact; max abs diff reported)")

# FUNCTION: TEST 10, THE PERFORMANCE REPORT ON A TINY HAND-COMPUTED EXAMPLE
def test_reporting():
    """
    Cumulative log excess, drawdown, rolling windows, turnover and switch counts match the hand calculation.

    Returns:
        None
    """
    # THREE SESSIONS
    date_list = [pd.Timestamp("2024-01-02").date(), pd.Timestamp("2024-01-03").date(), pd.Timestamp("2024-01-04").date()]
    strategy_pdf = pd.DataFrame({"date": date_list, "daily_return": [0.10, -0.05, 0.02]})
    buy_hold_pdf = pd.DataFrame({"date": date_list, "daily_return": [0.01, 0.01, 0.00]})
    performance_pdf = get_performance_over_time_pdf(strategy_pdf, buy_hold_pdf)
    # CUMULATIVE LOG EXCESS BY HAND
    log_excess_list = [np.log1p(0.10) - np.log1p(0.01), np.log1p(-0.05) - np.log1p(0.01), np.log1p(0.02) - np.log1p(0.00)]
    assert np.allclose(performance_pdf["cumulative_log_excess"], np.cumsum(log_excess_list))
    # DRAWDOWN BY HAND: EQUITY 1.10, 1.045, 1.0659; PEAK 1.10
    equity_list = [1.10, 1.10 * 0.95, 1.10 * 0.95 * 1.02]
    peak_list = np.maximum.accumulate(equity_list)
    assert np.allclose(performance_pdf["strategy_drawdown"], np.array(equity_list) / peak_list - 1.0)
    # 63 AND 252 ARE EMPTY ON A THREE-SESSION SERIES
    assert performance_pdf["rolling_63_excess_return"].isna().all()
    assert performance_pdf["rolling_252_excess_return"].isna().all()
    # THE QUARTER TABLE IS ONE QUARTER
    quarter_pdf = get_performance_quarter_pdf(strategy_pdf, buy_hold_pdf)
    assert len(quarter_pdf) == 1
    assert np.isclose(quarter_pdf["excess_return"].iloc[0], (np.prod(1 + strategy_pdf["daily_return"]) - 1) - (np.prod(1 + buy_hold_pdf["daily_return"]) - 1))
    # TURNOVER 0.6 OVER 3 SESSIONS, ONE SWITCH
    activity_dict = get_turnover_switch_dict([1.0, 0.4, 0.4], 2, ["6M", "6M", "10Y"])
    assert np.isclose(activity_dict["turnover_per_year"], 0.6 * 252 / 3)
    assert activity_dict["trade_count"] == 2
    assert activity_dict["candidate_switch_count"] == 1
    assert np.isclose(activity_dict["candidate_switches_per_year"], 1 * 252 / 3)
    assert np.isclose(activity_dict["candidate_time_share_dict"]["6M"], 2 / 3)
    assert np.isclose(activity_dict["candidate_time_share_dict"]["10Y"], 1 / 3)
    # REFIT LOG: MEAN ROWS, MEAN PURGE SHARE, MEAN PREDICTION MOVE
    refit_pdf = pd.DataFrame({"rows_used": [10, 20], "rows_purged": [2, 5], "prediction_move": [np.nan, 0.25]})
    refit_dict = get_refit_report_dict(refit_pdf, None)
    assert np.isclose(refit_dict["mean_rows_used"], 15.0)
    assert np.isclose(refit_dict["mean_share_purged"], np.mean([2 / 12, 5 / 25]))
    assert np.isclose(refit_dict["mean_prediction_move"], 0.25)
    passed("10 reporting (log excess, drawdown, turnover 50.4, one switch, purge share by hand)")

# FUNCTION: LOAD THE FILE-BASED CACHE-LEAK DESIGN
def get_cache_leak_design():
    """
    Loads tests/cache_leak_design.py. The runner reloads that file for every replay.

    Returns:
        module: Design
    """
    # A NEW MODULE OBJECT FROM THE FILE
    import importlib.util
    design_path_str = os.path.join(WORKSPACE_PATH_STR, "tests", "cache_leak_design.py")
    design_spec = importlib.util.spec_from_file_location("cache_leak_design_test", design_path_str)
    design_module = importlib.util.module_from_spec(design_spec)
    design_spec.loader.exec_module(design_module)
    return design_module

# FUNCTION: TEST THAT A WINDOW-ONLY CACHE CANNOT HIDE A ONE-SESSION LEAK, AND THAT THE TEMPLATE CACHE IS PER REPLAY
def test_fresh_design_module():
    """
    A design that caches by training window and reads one session ahead is invalid_lookahead. The template's imported
    cache stays empty. Inside one template replay each training window is fit once.

    Returns:
        None
    """
    # THE SAME SPAN AS THE LABEL-LEAK TEST; OPEN A WINDOW ONLY WHEN THIS TEST RUNS ALONE
    session_date_list = [day.date() for day in pd.bdate_range("2021-01-04", "2024-06-28")]
    if get_active_holdout_window_dict(missing_ok_bool_in=True) is None:
        window_dict = compute_holdout_window_dict(session_date_list)
        open_holdout_window_dict(session_date_list, f"OPEN {window_dict['start']} {window_dict['end']}", file_path_str_in=paths.HOLDOUT_WINDOWS_FILE_PATH_STR)
    ohlcv_array_dict = get_ohlcv_array_dict(get_four_bar_ohlcv_pdf(session_date_list, 5))
    token_dir_str = tempfile.mkdtemp(prefix="so_retrain_token_")
    token_path_str = os.path.join(token_dir_str, "token.txt")
    with open(token_path_str, "w", encoding="utf-8") as token_file:
        token_file.write("retrain-token\n")
    results_path_str = tempfile.mkdtemp(prefix="so_retrain_results_")
    os.environ["SO_HOLDOUT_PATH"] = results_path_str
    os.environ["SO_HOLDOUT_EVALUATION_TOKEN"] = "retrain-token"
    git_dict = {"clean_bool": True, "on_main_bool": True, "preregister_bool": True, "commit_str": "abc123",
                "design_tree_str": "cache-leak-design", "so_tree_str": "cache-leak-so"}
    ledger_path_str = os.path.join(TEMP_ROOT_STR, "cache_leak_evaluations.csv")
    trial_path_str = os.path.join(TEMP_ROOT_STR, "cache_leak_trial_log.csv")
    # THE LEAK IS CAUGHT BECAUSE THE TRUNCATED REPLAY DOES NOT SEE THE FULL RUN'S CACHE
    leak_stdout = StringIO()
    saved_stdout = sys.stdout
    sys.stdout = leak_stdout
    try:
        leak_module = get_cache_leak_design()
        leak_row = run_holdout_evaluation(leak_module, "cache_leak", ohlcv_array_dict, token_path_str, git_dict,
                                          ledger_path_str_in=ledger_path_str, trial_log_path_str_in=trial_path_str)
    finally:
        sys.stdout = saved_stdout
    assert leak_row["status"] == "invalid_lookahead"
    assert "invalid_lookahead" in leak_stdout.getvalue()
    assert not os.path.isfile(os.path.join(results_path_str, leak_row["window_id"], "cache_leak", "strategy_daily_equity.csv"))
    assert leak_module._fit_cache_dict == {}
    os.environ.pop("SO_HOLDOUT_PATH", None)
    os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
    shutil.rmtree(token_dir_str, ignore_errors=True)
    shutil.rmtree(results_path_str, ignore_errors=True)
    # THE TEMPLATE IS ON THE RUNNER: NO MODULE-LEVEL FIT CACHE, get_candidate_design RETURNS A FRESH OBJECT
    from experiments._template import design as template_design
    from so.runner.preflight import check_design_file
    check_design_file(template_design.__file__)
    assert not hasattr(template_design, "_retrain_cache_dict")
    assert hasattr(template_design, "get_candidate_design")
    first_design = template_design.get_candidate_design(template_design.CANDIDATE_LIST[0])
    second_design = template_design.get_candidate_design(template_design.CANDIDATE_LIST[0])
    assert first_design is not second_design
    passed("fresh module (window-only cache -> invalid_lookahead; template has no module cache)")
    print(f"    fresh module detail: cache leak {leak_row['status']}; template candidates {len(template_design.CANDIDATE_LIST)}")

# FUNCTION: THE TEMPLATE'S FIRST THREE REFITS ON A SHORT SYNTHETIC SERIES
def test_template_refit_log():
    """
    The template design's first three weekly refits report rows used, rows purged and the last label clock.

    Returns:
        None
    """
    # ABOUT FOUR MONTHS OF FOUR-BAR SESSIONS, ENOUGH FOR A 20-SESSION LABEL AND THE MINIMUM ROW COUNT
    from experiments._template import design as template_design
    from so.core.point_in_time import add_tsday_fwd_label_known_ts_pdf, get_minute_bar_available_ts, get_runner_context
    from so.features.daily_features import get_daily_feature_pdf
    from so.runner import run_daily_dict
    session_date_list = [day.date() for day in pd.bdate_range("2022-01-03", periods=120)]
    ohlcv_array_dict = get_ohlcv_array_dict(get_four_bar_ohlcv_pdf(session_date_list, 2))
    label_pdf = add_tsday_fwd_label_known_ts_pdf(get_daily_feature_pdf(ohlcv_array_dict))
    limit_ts = get_minute_bar_available_ts(ohlcv_array_dict["timestamp_index"][-1])
    data_context = get_runner_context(ohlcv_array_dict, {"TSDAY_FWD": label_pdf}, limit_ts, list(template_design.DATA_SOURCE_LIST))
    date1, date2 = session_date_list[50], session_date_list[-1]
    candidate_design = template_design.get_candidate_design("6M")
    run_daily_dict(candidate_design, ohlcv_array_dict, date1, date2, data_context_in=data_context,
                   design_file_path_str_in=template_design.__file__)
    refit_pdf = pd.DataFrame(candidate_design.refit_log_list).head(3)
    assert len(refit_pdf) == 3
    assert (refit_pdf["rows_used"] >= template_design.MIN_TRAIN_ROW_COUNT).all()
    def get_ny_ts(value_in):
        timestamp = pd.Timestamp(value_in)
        if timestamp.tzinfo is None:
            return timestamp.tz_localize("America/New_York")
        return timestamp.tz_convert("America/New_York")
    assert all(get_ny_ts(left_ts) < get_ny_ts(right_ts)
               for left_ts, right_ts in zip(refit_pdf["last_label_known_ts"], refit_pdf["decision_ts"]))
    # PRINT THE THREE ROWS THE REPLY QUOTES
    print("    template first 3 refits:")
    for refit_row in refit_pdf.itertuples(index=False):
        print(f"    session {refit_row.retrain_session} rows_used {refit_row.rows_used} rows_purged {refit_row.rows_purged} last_label_known_ts {refit_row.last_label_known_ts}")
    passed("template refit log (first 3 refits; last label before the decision)")

# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY FOLDER
    try:
        test_retrain_sessions()
        test_purge()
        test_drop_not_fill()
        test_windows()
        test_model_id_held()
        test_feature_leak()
        test_label_leak()
        test_determinism()
        test_selection()
        test_numeric_tolerance()
        test_reporting()
        test_fresh_design_module()
        test_template_refit_log()
        print("\nAll rolling-retrain tests passed")
    finally:
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
