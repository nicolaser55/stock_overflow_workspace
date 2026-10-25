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
import tempfile
import shutil
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
from so import paths
from so.core.rolling_retrain import get_retrain_session_list
from so.core.trade_execution import get_ohlcv_array_dict

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
        test_template_refit_log()
        print("\nAll rolling-retrain tests passed")
    finally:
        shutil.rmtree(TEMP_ROOT_STR, ignore_errors=True)
        os.environ.pop("SO_HOLDOUT_PATH", None)
        os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
