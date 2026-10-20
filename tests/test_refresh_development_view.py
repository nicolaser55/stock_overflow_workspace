"""
Workspace Tests: development-view refresh (scripts/refresh_development_view.py)

Run from the workspace root:   python tests/test_refresh_development_view.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

Synthetic trees in temporary folders only. SO_DATA_PATH is the development view, SO_QUARANTINE_PATH is the complete
tree. records/holdout_windows.csv is not written. If that registry file already exists, its size is unchanged.
"""

import os
import sys
import json
import tempfile
import shutil
import io
from contextlib import redirect_stdout

# POINT BOTH ROOTS AT EMPTY TEMPORARY FOLDERS BEFORE so.paths IS IMPORTED
TEMP_VIEW_STR = tempfile.mkdtemp(prefix="so_view_")
TEMP_QUARANTINE_STR = tempfile.mkdtemp(prefix="so_quarantine_")
os.environ["SO_DATA_PATH"] = TEMP_VIEW_STR
os.environ["SO_QUARANTINE_PATH"] = TEMP_QUARANTINE_STR
os.environ.pop("SO_HOLDOUT_PATH", None)
os.environ.pop("SO_HOLDOUT_EVALUATION_TOKEN", None)
# ADD THE WORKSPACE AND THE SCRIPTS FOLDER TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "scripts"))
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE SHARED MODULES AND THE REFRESH SCRIPT
import pandas as pd
from so import paths, config
from so.core.datetime_utils import ny_tz, get_date_range_market_schedule_pdf
from so.core.holdout import compute_holdout_window_dict, open_holdout_window_dict, get_active_holdout_window_dict
from so.features.barrier_labels import encode_TSBAR_cell_str
from refresh_development_view import (
    UNRESOLVED_TSBAR_CELL_STR,
    check_refresh_roots_dict,
    get_bar_position_dict,
    get_file_name_date_span_tuple,
    get_source_file_action_str,
    get_tsbar_exit_on_or_after_bool,
    run_refresh_development_view_dict,
)

# KEEP THE REAL REGISTRY UNCHANGED
REAL_WINDOWS_PATH_STR = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
REAL_WINDOWS_EXISTS_BOOL = os.path.isfile(REAL_WINDOWS_PATH_STR)
REAL_WINDOWS_SIZE_INT = os.path.getsize(REAL_WINDOWS_PATH_STR) if REAL_WINDOWS_EXISTS_BOOL else None
# POINT THE SUITE AT A TEMPORARY REGISTRY
REGISTRY_PATH_STR = os.path.join(TEMP_VIEW_STR, "holdout_windows.csv")
paths.HOLDOUT_WINDOWS_FILE_PATH_STR = REGISTRY_PATH_STR

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints a passing check.

    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}")

# FUNCTION: NYSE SESSION DATES
def get_session_date_list(date1_str_in, date2_str_in):
    """
    Session dates of the real NYSE calendar between two dates.

    Args:
        date1_str_in, date2_str_in (str): Inclusive bounds

    Returns:
        list[datetime.date]: Session dates
    """
    # READ THE CALENDAR AND RETURN THE NEW YORK DATES
    schedule_pdf = get_date_range_market_schedule_pdf(date1_str_in, date2_str_in)
    return list(pd.to_datetime(schedule_pdf["market_open_ts"]).dt.tz_convert(ny_tz).dt.date)

# FUNCTION: TWO UTC BAR TIMESTAMPS OF ONE SESSION
def get_session_bar_str_list(session_date_in):
    """
    Two UTC timestamp strings (14:30 and 14:31) for one session.

    Args:
        session_date_in (datetime.date): Session

    Returns:
        list[str]: Timestamp texts
    """
    # THE RAW LOADER PARSES THESE AS UTC AND CONVERTS TO NEW YORK
    day_str = pd.Timestamp(session_date_in).strftime("%Y-%m-%d")
    return [f"{day_str} 14:30:00+00:00", f"{day_str} 14:31:00+00:00"]

# FUNCTION: WRITE A RAW-STYLE CSV WITH EXACT BYTES
def write_raw_csv_bytes(file_path_str_in, session_date_list_in):
    """
    Writes a raw OHLCV CSV (two bars per session) and returns the bytes written.

    Args:
        file_path_str_in (str): Destination
        session_date_list_in (list): Session dates

    Returns:
        bytes: File contents
    """
    # BUILD THE TEXT SO A LATER COPY CAN BE COMPARED BYTE FOR BYTE
    os.makedirs(os.path.dirname(file_path_str_in), exist_ok=True)
    line_list = ["timestamp,open,high,low,close,volume"]
    for session_date in session_date_list_in:
        for stamp_str in get_session_bar_str_list(session_date):
            line_list.append(f"{stamp_str},100.0,101.0,99.0,100.5,1000")
    text_str = "\n".join(line_list) + "\n"
    file_bytes = text_str.encode("utf-8")
    with open(file_path_str_in, "wb") as file_handle:
        file_handle.write(file_bytes)
    return file_bytes

# FUNCTION: WRITE A ONE-ROW-PER-DATE TABLE
def write_dated_csv(file_path_str_in, session_date_list_in, extra_column_dict_in=None):
    """
    Writes a CSV with a date column and optional extra columns (same value on every row unless a dict of lists).

    Args:
        file_path_str_in (str): Destination
        session_date_list_in (list): Session dates
        extra_column_dict_in (dict | None): Column -> value or list

    Returns:
        None
    """
    # ONE ROW PER SESSION
    os.makedirs(os.path.dirname(file_path_str_in), exist_ok=True)
    extra_dict = extra_column_dict_in or {}
    row_dict_list = []
    for row_idx, session_date in enumerate(session_date_list_in):
        row_dict = {"date": str(pd.Timestamp(session_date).date())}
        for column_str, value in extra_dict.items():
            row_dict[column_str] = value[row_idx] if isinstance(value, list) else value
        row_dict_list.append(row_dict)
    pd.DataFrame(row_dict_list).to_csv(file_path_str_in, index=False)

# FUNCTION: WRITE ONE TSBAR FILE
def write_tsbar_csv(file_path_str_in, session_date_in, cell_0010_str_in, cell_0020_str_in):
    """
    Writes one TSBAR day file with two distance cells.

    Args:
        file_path_str_in (str): Destination
        session_date_in (datetime.date): Session
        cell_0010_str_in, cell_0020_str_in (str): Encoded cells

    Returns:
        None
    """
    # ENTRY IS THE FIRST UTC BAR OF THE SESSION
    os.makedirs(os.path.dirname(file_path_str_in), exist_ok=True)
    stamp_str = get_session_bar_str_list(session_date_in)[0]
    day_str = str(pd.Timestamp(session_date_in).date())
    pd.DataFrame([{"decision_ts": stamp_str, "entry_ts": stamp_str, "entry_price": "100.0", "horizon_complete": "True",
                   "rr_ratio": "1.0", "0.0010": cell_0010_str_in, "0.0020": cell_0020_str_in, "date": day_str}]).to_csv(file_path_str_in, index=False)

# FUNCTION: RELATIVE PATH UNDER A ROOT
def get_rel_str(root_str_in, *part_str_in):
    """
    Joins a root and path parts.

    Args:
        root_str_in (str): Root
        *part_str_in: Path parts

    Returns:
        str: Joined path
    """
    # JOIN ON THIS PLATFORM
    return os.path.join(root_str_in, *part_str_in)

# FUNCTION: BUILD THE SYNTHETIC QUARANTINE TREE
def build_quarantine_tree_dict(add_later_bool_in=False):
    """
    Writes a small quarantine tree: yearly, monthly and daily raw names, cache day files, TSBAR exits that cross
    the first holdout start, and a TSDAY table. Optional later sessions slide the window.

    Args:
        add_later_bool_in (bool): Append 2025-06-16 to raw and TSDAY

    Returns:
        dict: session lists, expected first window, paths of files used in checks
    """
    # SESSIONS: 25 BEFORE 2024-01-16, HOLDOUT FROM THAT DATE, LAST SESSION 2025-01-15
    before_list = get_session_date_list("2023-01-03", "2024-01-12")
    pre_s_list = before_list[-25:]
    early_list = [session_date for session_date in before_list if session_date < pre_s_list[0]][:3]
    start_date = get_session_date_list("2024-01-16", "2024-01-16")[0]
    june_date = get_session_date_list("2024-06-03", "2024-06-03")[0]
    holdout_mid_list = get_session_date_list("2024-01-16", "2024-06-28")
    last_date = get_session_date_list("2025-01-15", "2025-01-15")[0]
    later_date = get_session_date_list("2025-06-16", "2025-06-16")[0]
    session_date_list = []
    for session_date in early_list + pre_s_list + holdout_mid_list + [last_date]:
        if session_date not in session_date_list:
            session_date_list.append(session_date)
    if add_later_bool_in and later_date not in session_date_list:
        session_date_list.append(later_date)
    window_dict = compute_holdout_window_dict(session_date_list)
    # FOLDERS THE RESEARCH CODE READS
    spy_str = get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_spy_1min")
    vix_1min_str = get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_vix_family", "vix_1min")
    vix_daily_str = get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_vix_family", "vix_daily")
    vix3m_1min_str = get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_vix_family", "vix3m_1min")
    vix3m_daily_str = get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_vix_family", "vix3m_daily")
    pa_str = get_rel_str(TEMP_QUARANTINE_STR, "store02_workzone", "step01_PA_ohlcv_data")
    tsind_str = get_rel_str(TEMP_QUARANTINE_STR, "store02_workzone", "step02_TSIND_data")
    tsseg_str = get_rel_str(TEMP_QUARANTINE_STR, "store02_workzone", "step03_TSSEG_data")
    tsctx_str = get_rel_str(TEMP_QUARANTINE_STR, "store02_workzone", "step04_TSCTX_data")
    tsbar_str = get_rel_str(TEMP_QUARANTINE_STR, "store03_goldzone", "step05_TSBAR_data")
    tsday_str = get_rel_str(TEMP_QUARANTINE_STR, "store02_workzone", "step06_TSDAY_data")
    os.makedirs(spy_str, exist_ok=True)
    # EACH SESSION LIVES IN EXACTLY ONE RAW FILE (THE LOADER REFUSES DUPLICATE ROWS)
    daily_before_date = pre_s_list[-1]
    year_2023_list = [session_date for session_date in early_list + pre_s_list if session_date.year == 2023]
    month_202401_list = [session_date for session_date in pre_s_list
                         if session_date.year == 2024 and session_date.month == 1 and session_date != daily_before_date]
    year_2024_list = [session_date for session_date in holdout_mid_list if session_date > start_date and session_date != june_date]
    year_2025_list = [last_date] + ([later_date] if add_later_bool_in else [])
    # YEARLY 2023 (ENTIRELY BEFORE THE FIRST S)
    path_year_2023_str = os.path.join(spy_str, "ohlcv_data_2023.csv")
    bytes_year_2023 = write_raw_csv_bytes(path_year_2023_str, year_2023_list)
    # MONTHLY 202401 (NAME STRADDLES THE FIRST S; ROWS ARE ALL BEFORE S)
    path_month_202401_str = os.path.join(spy_str, "ohlcv_data_202401.csv")
    bytes_month_202401 = write_raw_csv_bytes(path_month_202401_str, month_202401_list)
    # DAILY FILE ON S (NOT COPIED ON THE FIRST BUILD) AND ONE DAILY FILE BEFORE S
    path_daily_before_str = os.path.join(spy_str, f"ohlcv_data_{daily_before_date.strftime('%Y%m%d')}.csv")
    bytes_daily_before = write_raw_csv_bytes(path_daily_before_str, [daily_before_date])
    path_daily_s_str = os.path.join(spy_str, f"ohlcv_data_{start_date.strftime('%Y%m%d')}.csv")
    write_raw_csv_bytes(path_daily_s_str, [start_date])
    # YEARLY 2024: HOLDOUT SESSIONS AFTER S, EXCLUDING THE JUNE MONTHLY FILE
    path_year_2024_str = os.path.join(spy_str, "ohlcv_data_2024.csv")
    write_raw_csv_bytes(path_year_2024_str, year_2024_list)
    # YEARLY 2025: THE FIRST-WAVE LAST SESSION, AND THE LATER SESSION WHEN ASKED
    path_year_2025_str = os.path.join(spy_str, "ohlcv_data_2025.csv")
    write_raw_csv_bytes(path_year_2025_str, year_2025_list)
    # MONTHLY JUNE 2024 (AFTER THE FIRST S, BEFORE THE SLID S)
    path_month_202406_str = os.path.join(spy_str, "ohlcv_data_202406.csv")
    write_raw_csv_bytes(path_month_202406_str, [june_date])
    # VIX FAMILY: YEARLY DAILY AND ONE 1-MINUTE FILE BEFORE S AND ONE ON S
    write_raw_csv_bytes(os.path.join(vix_daily_str, "ohlcv_data_2023.csv"), year_2023_list[-2:])
    write_raw_csv_bytes(os.path.join(vix_daily_str, "ohlcv_data_2024.csv"), [start_date, last_date])
    write_raw_csv_bytes(os.path.join(vix_1min_str, f"ohlcv_data_{pre_s_list[-1].strftime('%Y%m%d')}.csv"), [pre_s_list[-1]])
    write_raw_csv_bytes(os.path.join(vix_1min_str, f"ohlcv_data_{start_date.strftime('%Y%m%d')}.csv"), [start_date])
    write_raw_csv_bytes(os.path.join(vix3m_daily_str, "ohlcv_data_2023.csv"), year_2023_list[-1:])
    write_raw_csv_bytes(os.path.join(vix3m_1min_str, f"ohlcv_data_{pre_s_list[-2].strftime('%Y%m%d')}.csv"), [pre_s_list[-2]])
    write_raw_csv_bytes(os.path.join(vix3m_1min_str, f"ohlcv_data_{start_date.strftime('%Y%m%d')}.csv"), [start_date])
    # CACHE DAY FILES (INCLUDING ONE ON S)
    write_dated_csv(os.path.join(pa_str, f"PA_ohlcv_{pre_s_list[-1].strftime('%Y%m%d')}.csv"), [pre_s_list[-1]], {"close": "100.5"})
    write_dated_csv(os.path.join(pa_str, f"PA_ohlcv_{start_date.strftime('%Y%m%d')}.csv"), [start_date], {"close": "101.0"})
    write_dated_csv(os.path.join(tsind_str, f"TSIND_{pre_s_list[-1].strftime('%Y%m%d')}.csv"), [pre_s_list[-1]], {"rsi": "50"})
    write_dated_csv(os.path.join(tsseg_str, f"TSSEG_{pre_s_list[-1].strftime('%Y%m%d')}.csv"), [pre_s_list[-1]], {"seg": "1"})
    write_dated_csv(os.path.join(tsctx_str, f"TSCTX_{pre_s_list[-1].strftime('%Y%m%d')}.csv"), [pre_s_list[-1]], {"ctx": "1"})
    write_dated_csv(os.path.join(tsind_str, f"TSIND_{start_date.strftime('%Y%m%d')}.csv"), [start_date], {"rsi": "99"})
    # TSBAR: A FILE 15 SESSIONS BEFORE S (SAFE EXIT) AND A FILE 5 SESSIONS BEFORE S (EXIT ON S)
    safe_date = pre_s_list[-15]
    cross_date = pre_s_list[-5]
    safe_cell_str = encode_TSBAR_cell_str(2, 100.25, "TP")
    cross_cell_str = encode_TSBAR_cell_str(10, 100.75, "TP")
    near_cell_str = encode_TSBAR_cell_str(1, 100.10, "SL")
    write_tsbar_csv(os.path.join(tsbar_str, f"TSBAR_{safe_date.strftime('%Y%m%d')}.csv"), safe_date, safe_cell_str, near_cell_str)
    write_tsbar_csv(os.path.join(tsbar_str, f"TSBAR_{cross_date.strftime('%Y%m%d')}.csv"), cross_date, cross_cell_str, near_cell_str)
    write_tsbar_csv(os.path.join(tsbar_str, f"TSBAR_{start_date.strftime('%Y%m%d')}.csv"), start_date, cross_cell_str, near_cell_str)
    # TSDAY: EVERY SESSION, FORWARD COLUMNS FILLED
    tsday_session_list = list(session_date_list)
    write_dated_csv(os.path.join(tsday_str, "TSDAY_data.csv"), tsday_session_list,
                    {"close": "100.5", "fwd_net_return_20d": "0.01", "y_fwd_positive": "1"})
    # FOLDERS THE VIEW MUST NEVER COPY
    os.makedirs(get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_vix_family_staging"), exist_ok=True)
    os.makedirs(get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_spy_1min_backup"), exist_ok=True)
    os.makedirs(get_rel_str(TEMP_QUARANTINE_STR, "store02_workzone", "step00_data_quality_report"), exist_ok=True)
    with open(get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_vix_family_staging", "secret.csv"), "w", encoding="utf-8") as secret_file:
        secret_file.write("secret,1\n")
    with open(get_rel_str(TEMP_QUARANTINE_STR, "store01_rawzone", "ibkr_spy_1min_backup", "ohlcv_data_2023.csv"), "w", encoding="utf-8") as backup_file:
        backup_file.write("timestamp,open\n2026-01-02 14:30:00+00:00,1\n")
    with open(get_rel_str(TEMP_QUARANTINE_STR, "store02_workzone", "step00_data_quality_report", "report.csv"), "w", encoding="utf-8") as step00_file:
        step00_file.write("date,ok\n2024-01-16,1\n")
    return {"session_date_list": session_date_list, "pre_s_list": pre_s_list, "early_list": early_list,
            "start_date": start_date, "june_date": june_date, "last_date": last_date, "later_date": later_date,
            "window_dict": window_dict, "safe_date": safe_date, "cross_date": cross_date,
            "safe_cell_str": safe_cell_str, "cross_cell_str": cross_cell_str, "near_cell_str": near_cell_str,
            "path_year_2023_str": path_year_2023_str, "bytes_year_2023": bytes_year_2023,
            "path_month_202401_str": path_month_202401_str, "bytes_month_202401": bytes_month_202401,
            "path_daily_before_str": path_daily_before_str, "bytes_daily_before": bytes_daily_before,
            "path_daily_s_str": path_daily_s_str, "path_month_202406_str": path_month_202406_str,
            "path_year_2024_str": path_year_2024_str}

# FUNCTION: OPEN THE FIRST-WAVE WINDOW ON THE TEMPORARY REGISTRY
def open_first_window(tree_dict_in):
    """
    Opens the holdout computed from the first-wave sessions.

    Args:
        tree_dict_in (dict): Tree description

    Returns:
        dict: Opened row
    """
    # THE FIRST WAVE DOES NOT INCLUDE THE LATER 2025 SESSION
    first_list = [session_date for session_date in tree_dict_in["session_date_list"] if session_date <= tree_dict_in["last_date"]]
    window_dict = compute_holdout_window_dict(first_list)
    return open_holdout_window_dict(first_list, f"OPEN {window_dict['start']} {window_dict['end']}", file_path_str_in=REGISTRY_PATH_STR)

# FUNCTION: VIEW PATH OF A QUARANTINE FILE
def get_view_path_str(source_path_str_in):
    """
    The same relative path under the development view.

    Args:
        source_path_str_in (str): Quarantine file

    Returns:
        str: View file
    """
    # RELATIVE TO THE QUARANTINE ROOT
    rel_str = os.path.relpath(source_path_str_in, TEMP_QUARANTINE_STR)
    return os.path.join(TEMP_VIEW_STR, rel_str)

# FUNCTION: DATES FOUND IN A VIEW TREE
def get_view_row_date_list(view_root_str_in):
    """
    Session dates of every CSV row under store01-store03 of the view.

    Args:
        view_root_str_in (str): View root

    Returns:
        list[datetime.date]: Dates
    """
    # WALK THE THREE ZONES
    date_list = []
    for zone_str in ("store01_rawzone", "store02_workzone", "store03_goldzone"):
        zone_str_path = os.path.join(view_root_str_in, zone_str)
        if not os.path.isdir(zone_str_path):
            continue
        for walk_root_str, _dir_list, file_list in os.walk(zone_str_path):
            for file_name_str in file_list:
                if not file_name_str.lower().endswith(".csv"):
                    continue
                file_path_str = os.path.join(walk_root_str, file_name_str)
                try:
                    frame_pdf = pd.read_csv(file_path_str)
                except (pd.errors.EmptyDataError, ValueError):
                    continue
                for column_str in ("date", "timestamp", "decision_ts", "entry_ts"):
                    if column_str not in frame_pdf.columns:
                        continue
                    if column_str == "date":
                        date_list.extend(pd.to_datetime(frame_pdf[column_str]).dt.date.tolist())
                    else:
                        stamp_series = pd.to_datetime(frame_pdf[column_str], utc=True).dt.tz_convert(ny_tz)
                        date_list.extend(stamp_series.dt.date.tolist())
                    break
    return date_list

# FUNCTION: TEST FILENAME SPAN PARSING
def test_file_name_span():
    """
    Yearly, monthly and daily tokens become calendar spans; other names have none.

    Returns:
        None
    """
    # THREE GRANULARITIES AND AN UNDATED NAME
    assert get_file_name_date_span_tuple("ohlcv_data_2023.csv") == (pd.Timestamp("2023-01-01").date(), pd.Timestamp("2023-12-31").date())
    assert get_file_name_date_span_tuple("ohlcv_data_202401.csv") == (pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-31").date())
    assert get_file_name_date_span_tuple("ohlcv_data_20240116.csv") == (pd.Timestamp("2024-01-16").date(), pd.Timestamp("2024-01-16").date())
    assert get_file_name_date_span_tuple("TSDAY_data.csv") is None
    passed("file-name date spans (yearly, monthly, daily, undated)")

# FUNCTION: TEST THE START REFUSALS
def test_refresh_refuses_without_roots():
    """
    The refresh refuses when a variable is missing, when both variables name the same folder, and when the
    quarantine has no store01_rawzone.

    Returns:
        None
    """
    # MISSING QUARANTINE
    saved_view_str = os.environ["SO_DATA_PATH"]
    saved_quarantine_str = os.environ["SO_QUARANTINE_PATH"]
    os.environ.pop("SO_QUARANTINE_PATH", None)
    try:
        check_refresh_roots_dict()
        raise AssertionError("an unset SO_QUARANTINE_PATH was accepted")
    except RuntimeError as error:
        assert "SO_QUARANTINE_PATH" in str(error)
    os.environ["SO_QUARANTINE_PATH"] = saved_view_str
    try:
        check_refresh_roots_dict()
        raise AssertionError("the same folder for both variables was accepted")
    except RuntimeError as error:
        assert "different folders" in str(error)
    empty_str = tempfile.mkdtemp(prefix="so_empty_q_")
    os.environ["SO_QUARANTINE_PATH"] = empty_str
    try:
        check_refresh_roots_dict()
        raise AssertionError("a quarantine without store01_rawzone was accepted")
    except RuntimeError as error:
        assert "store01_rawzone" in str(error)
    finally:
        shutil.rmtree(empty_str, ignore_errors=True)
        os.environ["SO_DATA_PATH"] = saved_view_str
        os.environ["SO_QUARANTINE_PATH"] = saved_quarantine_str
    passed("refresh refuses unless both roots are set, distinct, and the quarantine has store01_rawzone")

# FUNCTION: TEST THE FIRST BUILD
def test_first_view_cut_and_redact():
    """
    The first refresh copies nothing on or after S, keeps raw lines byte-identical, redacts TSBAR exits that land
    on S and TSDAY forward columns whose horizon ends on or after S, and writes a VIEW.json that matches the window.

    Returns:
        dict: Tree description (for later tests)
    """
    # BUILD THE TREE AND OPEN THE FIRST WINDOW
    tree_dict = build_quarantine_tree_dict(add_later_bool_in=False)
    open_first_window(tree_dict)
    start_date = tree_dict["window_dict"]["start"]
    assert start_date == tree_dict["start_date"]
    # A MARKER IN STORE04 MUST SURVIVE
    store04_str = os.path.join(TEMP_VIEW_STR, "store04_experiments", "marker.txt")
    os.makedirs(os.path.dirname(store04_str), exist_ok=True)
    with open(store04_str, "w", encoding="utf-8") as marker_file:
        marker_file.write("keep\n")
    result_dict = run_refresh_development_view_dict(run_pipeline_bool_in=False)
    assert result_dict["slid_bool"] is False
    view_path_str = os.path.join(TEMP_VIEW_STR, "VIEW.json")
    assert os.path.isfile(view_path_str)
    with open(view_path_str, encoding="utf-8") as view_file:
        stamp_dict = json.load(view_file)
    window_dict = get_active_holdout_window_dict()
    assert stamp_dict["window_id"] == str(window_dict["window_id"])
    assert stamp_dict["window_start"] == str(pd.Timestamp(window_dict["start"]).date())
    assert stamp_dict["window_end"] == str(pd.Timestamp(window_dict["end"]).date())
    assert stamp_dict["quarantine_last_session"] == str(tree_dict["last_date"])
    manifest_path_str = os.path.join(TEMP_VIEW_STR, "view_manifest.json")
    assert stamp_dict["manifest_sha256"]
    assert os.path.isfile(manifest_path_str)
    # NOTHING ON OR AFTER S IN A FILE NAME OR A ROW
    for walk_root_str, _dir_list, file_list in os.walk(TEMP_VIEW_STR):
        if "store04_experiments" in walk_root_str:
            continue
        for file_name_str in file_list:
            span_tup = get_file_name_date_span_tuple(file_name_str)
            if span_tup is not None:
                assert span_tup[0] < start_date, file_name_str
    row_date_list = get_view_row_date_list(TEMP_VIEW_STR)
    assert row_date_list
    assert max(row_date_list) < start_date
    # KEPT RAW LINES ARE BYTE-IDENTICAL
    assert Path_read_bytes(get_view_path_str(tree_dict["path_year_2023_str"])) == tree_dict["bytes_year_2023"]
    assert Path_read_bytes(get_view_path_str(tree_dict["path_month_202401_str"])) == tree_dict["bytes_month_202401"]
    assert Path_read_bytes(get_view_path_str(tree_dict["path_daily_before_str"])) == tree_dict["bytes_daily_before"]
    assert not os.path.isfile(get_view_path_str(tree_dict["path_daily_s_str"]))
    assert not os.path.isfile(get_view_path_str(tree_dict["path_month_202406_str"]))
    assert not os.path.isfile(get_view_path_str(tree_dict["path_year_2024_str"]))
    # STAGING, BACKUPS AND STEP00 ARE ABSENT; STORE04 IS UNTOUCHED
    assert not os.path.exists(os.path.join(TEMP_VIEW_STR, "store01_rawzone", "ibkr_vix_family_staging"))
    assert not os.path.exists(os.path.join(TEMP_VIEW_STR, "store01_rawzone", "ibkr_spy_1min_backup"))
    assert not os.path.exists(os.path.join(TEMP_VIEW_STR, "store02_workzone", "step00_data_quality_report"))
    with open(store04_str, encoding="utf-8") as marker_file:
        assert marker_file.read() == "keep\n"
    # TSBAR: THE CROSSING CELL IS UNRESOLVED; THE SAFE FILE AND THE NEAR CELL ARE UNCHANGED
    cross_view_str = os.path.join(TEMP_VIEW_STR, "store03_goldzone", "step05_TSBAR_data", f"TSBAR_{tree_dict['cross_date'].strftime('%Y%m%d')}.csv")
    safe_view_str = os.path.join(TEMP_VIEW_STR, "store03_goldzone", "step05_TSBAR_data", f"TSBAR_{tree_dict['safe_date'].strftime('%Y%m%d')}.csv")
    cross_pdf = pd.read_csv(cross_view_str, dtype=str, keep_default_na=False)
    safe_pdf = pd.read_csv(safe_view_str, dtype=str, keep_default_na=False)
    assert cross_pdf.iloc[0]["0.0010"] == UNRESOLVED_TSBAR_CELL_STR
    assert cross_pdf.iloc[0]["0.0020"] == tree_dict["near_cell_str"]
    assert safe_pdf.iloc[0]["0.0010"] == tree_dict["safe_cell_str"]
    assert not os.path.isfile(os.path.join(TEMP_VIEW_STR, "store03_goldzone", "step05_TSBAR_data", f"TSBAR_{start_date.strftime('%Y%m%d')}.csv"))
    # TSDAY: LAST LABEL_HORIZON SESSIONS BEFORE S ARE EMPTY; EARLIER ROWS KEEP THE FILLED LABELS
    tsday_pdf = pd.read_csv(os.path.join(TEMP_VIEW_STR, "store02_workzone", "step06_TSDAY_data", "TSDAY_data.csv"), dtype=str, keep_default_na=False)
    tsday_pdf["date"] = pd.to_datetime(tsday_pdf["date"]).dt.date
    assert tsday_pdf["date"].max() < start_date
    before_list = [session_date for session_date in tree_dict["session_date_list"] if session_date < start_date]
    redact_set = set(before_list[-int(config.LABEL_HORIZON_SESSIONS):])
    for _, row in tsday_pdf.iterrows():
        if row["date"] in redact_set:
            assert str(row["fwd_net_return_20d"]).strip() == ""
            assert str(row["y_fwd_positive"]).strip() == ""
        else:
            assert str(row["fwd_net_return_20d"]).strip() == "0.01"
            assert str(row["y_fwd_positive"]).strip() == "1"
    # A LOG WAS WRITTEN UNDER THE QUARANTINE
    log_folder_str = os.path.join(TEMP_QUARANTINE_STR, "refresh_logs")
    assert os.path.isdir(log_folder_str) and os.listdir(log_folder_str)
    passed("first view (nothing on or after S, byte-identical raw lines, TSBAR/TSDAY redactions, VIEW.json matches)")
    tree_dict["store04_str"] = store04_str
    tree_dict["year_2023_view_str"] = get_view_path_str(tree_dict["path_year_2023_str"])
    return tree_dict

# FUNCTION: READ FILE BYTES
def Path_read_bytes(file_path_str_in):
    """
    Bytes of a file.

    Args:
        file_path_str_in (str): File

    Returns:
        bytes: Contents
    """
    # READ THE WHOLE FILE
    with open(file_path_str_in, "rb") as file_handle:
        return file_handle.read()

# FUNCTION: TEST THAT A SECOND RUN COPIES NOTHING
def test_second_run_copies_nothing(tree_dict_in):
    """
    A second refresh with the same quarantine and the same window copies no source file.

    Args:
        tree_dict_in (dict): Tree from the first build

    Returns:
        None
    """
    # RECORD THE DESTINATION MTIME OF A FILE THAT WAS COPIED
    view_path_str = tree_dict_in["year_2023_view_str"]
    before_mtime_ns = os.stat(view_path_str).st_mtime_ns
    before_stamp_dict = json.loads(open(os.path.join(TEMP_VIEW_STR, "VIEW.json"), encoding="utf-8").read())
    result_dict = run_refresh_development_view_dict(run_pipeline_bool_in=False)
    assert result_dict["slid_bool"] is False
    assert os.stat(view_path_str).st_mtime_ns == before_mtime_ns
    with open(os.path.join(TEMP_VIEW_STR, "view_manifest.json"), encoding="utf-8") as manifest_file:
        manifest_dict = json.load(manifest_file)
    copy_record_dict = next(record_dict for record_dict in manifest_dict["file_list"] if record_dict["relative_path"].endswith("ohlcv_data_2023.csv"))
    assert copy_record_dict["action"] == "copy"
    after_stamp_dict = json.loads(open(os.path.join(TEMP_VIEW_STR, "VIEW.json"), encoding="utf-8").read())
    assert after_stamp_dict["window_id"] == before_stamp_dict["window_id"]
    passed("second run copies nothing")

# FUNCTION: TEST SLIDE, NEW SESSIONS AND FILLED LABELS
def test_slide_moves_sessions_and_fills_labels(tree_dict_in):
    """
    Adding sessions and re-running slides the window, copies the sessions that fell out of the holdout, and fills
    the earlier TSBAR and TSDAY redactions.

    Args:
        tree_dict_in (dict): Tree from the first build

    Returns:
        dict: Updated tree
    """
    # APPEND THE LATER SESSION TO RAW AND TSDAY
    tree_dict = build_quarantine_tree_dict(add_later_bool_in=True)
    later_list = tree_dict["session_date_list"]
    later_window_dict = compute_holdout_window_dict(later_list)
    assert later_window_dict["start"] > tree_dict_in["start_date"]
    result_dict = run_refresh_development_view_dict(run_pipeline_bool_in=False)
    assert result_dict["slid_bool"] is True
    window_dict = get_active_holdout_window_dict()
    assert pd.Timestamp(window_dict["start"]).date() == later_window_dict["start"]
    new_start_date = later_window_dict["start"]
    # SESSIONS THAT WERE IN THE FIRST HOLDOUT AND ARE NOW BEFORE THE NEW START ARE IN THE VIEW
    assert os.path.isfile(get_view_path_str(tree_dict["path_daily_s_str"]))
    assert Path_read_bytes(get_view_path_str(tree_dict["path_daily_s_str"])) == Path_read_bytes(tree_dict["path_daily_s_str"])
    row_date_list = get_view_row_date_list(TEMP_VIEW_STR)
    assert tree_dict["start_date"] in row_date_list
    assert max(row_date_list) < new_start_date
    assert tree_dict["later_date"] not in row_date_list
    # THE CROSSING TSBAR CELL IS FILLED AGAIN (ITS EXIT IS BEFORE THE NEW START)
    cross_view_str = os.path.join(TEMP_VIEW_STR, "store03_goldzone", "step05_TSBAR_data", f"TSBAR_{tree_dict['cross_date'].strftime('%Y%m%d')}.csv")
    cross_pdf = pd.read_csv(cross_view_str, dtype=str, keep_default_na=False)
    assert cross_pdf.iloc[0]["0.0010"] == tree_dict["cross_cell_str"]
    # THE ORIGINAL TSDAY REDACTIONS ARE FILLED
    tsday_pdf = pd.read_csv(os.path.join(TEMP_VIEW_STR, "store02_workzone", "step06_TSDAY_data", "TSDAY_data.csv"), dtype=str, keep_default_na=False)
    tsday_pdf["date"] = pd.to_datetime(tsday_pdf["date"]).dt.date
    first_redact_set = set(tree_dict_in["pre_s_list"][-int(config.LABEL_HORIZON_SESSIONS):])
    for _, row in tsday_pdf.iterrows():
        if row["date"] in first_redact_set:
            assert str(row["fwd_net_return_20d"]).strip() == "0.01"
            assert str(row["y_fwd_positive"]).strip() == "1"
    with open(os.path.join(TEMP_VIEW_STR, "VIEW.json"), encoding="utf-8") as view_file:
        stamp_dict = json.load(view_file)
    assert stamp_dict["window_start"] == str(new_start_date)
    assert stamp_dict["quarantine_last_session"] == str(tree_dict["later_date"])
    # THE REAL REGISTRY WAS NOT THE FILE THAT SLID
    if REAL_WINDOWS_EXISTS_BOOL:
        assert os.path.getsize(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_SIZE_INT
    passed("slide moves sessions into the view and fills the earlier redactions")
    tree_dict["new_start_date"] = new_start_date
    return tree_dict

# FUNCTION: TEST THAT A PLANTED HOLDOUT FILE FAILS THE SCAN
def test_planted_file_fails_scan(tree_dict_in):
    """
    A file dated on or after the active start, planted in the view, makes the scan fail and leaves VIEW.json absent.

    Args:
        tree_dict_in (dict): Tree after the slide

    Returns:
        None
    """
    # PLANT A DAILY FILE DATED ON THE ACTIVE START
    start_date = tree_dict_in["new_start_date"]
    planted_str = os.path.join(TEMP_VIEW_STR, "store01_rawzone", "ibkr_spy_1min", f"ohlcv_data_{start_date.strftime('%Y%m%d')}.csv")
    write_raw_csv_bytes(planted_str, [start_date])
    assert os.path.isfile(os.path.join(TEMP_VIEW_STR, "VIEW.json"))
    try:
        run_refresh_development_view_dict(run_pipeline_bool_in=False)
        raise AssertionError("a planted holdout file was accepted")
    except SystemExit as error:
        assert error.code == 1
    assert not os.path.isfile(os.path.join(TEMP_VIEW_STR, "VIEW.json"))
    assert os.path.isfile(planted_str)
    passed("planted window file fails the scan and leaves VIEW.json absent")

# FUNCTION: TEST THAT --run-pipeline COPIES NOTEBOOKS AND DOES NOT TOUCH THE REPO
def test_run_pipeline_copies_notebooks():
    """
    --run-pipeline writes copies under the quarantine pipeline_runs folder and executes those copies, not the repo
    notebooks.

    Returns:
        None
    """
    # INJECT AN EXECUTOR THAT RECORDS THE PATHS IT WAS GIVEN
    executed_list = []
    repo_mtime_dict = {}
    for notebook_str in ["pipeline/step00_data_quality_check.ipynb", "pipeline/step06_TSDAY_data_collection.ipynb"]:
        repo_path_str = os.path.join(WORKSPACE_PATH_STR, notebook_str.replace("/", os.sep))
        repo_mtime_dict[notebook_str] = os.stat(repo_path_str).st_mtime_ns

    def execute_copy(path_str_in):
        executed_list.append(path_str_in)
        assert "pipeline_runs" in path_str_in.replace("\\", "/")
        assert os.path.abspath(path_str_in).startswith(os.path.abspath(TEMP_QUARANTINE_STR))

    run_refresh_development_view_dict(run_pipeline_bool_in=True, execute_func_in=execute_copy)
    assert len(executed_list) == 7
    assert all("pipeline_runs" in path_str.replace("\\", "/") for path_str in executed_list)
    for notebook_str, mtime_ns in repo_mtime_dict.items():
        repo_path_str = os.path.join(WORKSPACE_PATH_STR, notebook_str.replace("/", os.sep))
        assert os.stat(repo_path_str).st_mtime_ns == mtime_ns
    passed("run-pipeline executes copies under the quarantine and does not modify repo notebooks")

# FUNCTION: LINEAR TSBAR EXIT PLACEMENT (THE PRE-SCALE RULE)
def get_linear_tsbar_exit_on_or_after_bool(cell_str_in, entry_value_in, bar_timestamp_list_in, first_holdout_ts_in):
    """
    The original linear walk over bar_timestamp_list_in. Used only to check that the dict lookup agrees.

    Args:
        cell_str_in (str): Encoded cell
        entry_value_in: entry_ts
        bar_timestamp_list_in (list[pd.Timestamp]): Bars
        first_holdout_ts_in (pd.Timestamp): First holdout bar

    Returns:
        bool: Exit on or after the holdout
    """
    # SAME RULE AS get_tsbar_exit_on_or_after_bool BEFORE THE DICT INDEX
    from refresh_development_view import get_tsbar_cell_tuple
    cell_tup = get_tsbar_cell_tuple(cell_str_in)
    if cell_tup is None:
        return False
    count_int, _price_str, reason_str = cell_tup
    if count_int < 0 or reason_str == config.EXIT_REASON_NA:
        return False
    if first_holdout_ts_in is None or not bar_timestamp_list_in:
        return True
    entry_ts = pd.to_datetime(entry_value_in, utc=True).tz_convert(ny_tz)
    entry_idx = None
    for bar_idx, bar_ts in enumerate(bar_timestamp_list_in):
        if pd.Timestamp(bar_ts) == entry_ts:
            entry_idx = bar_idx
            break
    if entry_idx is None:
        return True
    exit_idx = entry_idx + int(count_int)
    if exit_idx < 0 or exit_idx >= len(bar_timestamp_list_in):
        return True
    return pd.Timestamp(bar_timestamp_list_in[exit_idx]) >= pd.Timestamp(first_holdout_ts_in)

# FUNCTION: TEST THAT THE BAR-INDEX DICT MATCHES THE LINEAR WALK
def test_tsbar_exit_dict_matches_linear_walk():
    """
    Exit placement with the timestamp->position dict gives the same answers as walking the bar list.

    Returns:
        None
    """
    # TWENTY ONE-MINUTE BARS; HOLDOUT STARTS AT BAR 10
    bar_list = [pd.Timestamp("2024-01-16 09:30:00", tz=ny_tz) + pd.Timedelta(minutes=idx) for idx in range(20)]
    position_dict = get_bar_position_dict(bar_list)
    first_holdout_ts = bar_list[10]
    entry_ts = bar_list[0]
    unresolved_str = encode_TSBAR_cell_str(-1, float("nan"), config.EXIT_REASON_NA)
    case_list = [0, 1, 9, 10, 15, 19, 20, 30]
    for count_int in case_list:
        cell_str = encode_TSBAR_cell_str(count_int, 100.0, "TP")
        dict_bool = get_tsbar_exit_on_or_after_bool(cell_str, entry_ts, bar_list, first_holdout_ts, bar_position_dict_in=position_dict)
        linear_bool = get_linear_tsbar_exit_on_or_after_bool(cell_str, entry_ts, bar_list, first_holdout_ts)
        assert dict_bool == linear_bool, (count_int, dict_bool, linear_bool)
    assert get_tsbar_exit_on_or_after_bool(unresolved_str, entry_ts, bar_list, first_holdout_ts, bar_position_dict_in=position_dict) is False
    assert get_linear_tsbar_exit_on_or_after_bool(unresolved_str, entry_ts, bar_list, first_holdout_ts) is False
    missing_entry_str = "2020-01-01 14:30:00+00:00"
    missing_cell_str = encode_TSBAR_cell_str(1, 100.0, "TP")
    assert get_tsbar_exit_on_or_after_bool(missing_cell_str, missing_entry_str, bar_list, first_holdout_ts, bar_position_dict_in=position_dict) is True
    assert get_linear_tsbar_exit_on_or_after_bool(missing_cell_str, missing_entry_str, bar_list, first_holdout_ts) is True
    passed("TSBAR exit dict lookup matches the linear walk")

# FUNCTION: TEST --plan WRITES NOTHING
def test_plan_does_not_write(tree_dict_in):
    """
    --plan prints per-folder counts and bytes and does not change VIEW.json or the registry.

    Args:
        tree_dict_in (dict): Tree after the first build

    Returns:
        None
    """
    # RECORD THE STAMP AND THE REGISTRY BEFORE THE PLAN
    view_path_str = os.path.join(TEMP_VIEW_STR, "VIEW.json")
    before_mtime_ns = os.stat(view_path_str).st_mtime_ns
    before_stamp_str = open(view_path_str, encoding="utf-8").read()
    before_registry_size_int = os.path.getsize(REGISTRY_PATH_STR)
    stdout_buf = io.StringIO()
    with redirect_stdout(stdout_buf):
        result_dict = run_refresh_development_view_dict(run_pipeline_bool_in=False, plan_bool_in=True)
    plan_text_str = stdout_buf.getvalue()
    assert result_dict["plan_bool"] is True
    assert result_dict["slid_bool"] is False
    assert result_dict["view_path_str"] is None
    assert os.stat(view_path_str).st_mtime_ns == before_mtime_ns
    assert open(view_path_str, encoding="utf-8").read() == before_stamp_str
    assert os.path.getsize(REGISTRY_PATH_STR) == before_registry_size_int
    assert "folder " in plan_text_str
    assert "copy" in plan_text_str
    assert "skip" in plan_text_str
    skip_total_int = sum(int(plan_dict["skip_count"]) for plan_dict in result_dict["folder_plan_list"])
    assert skip_total_int >= 1
    spy_action_str = get_source_file_action_str("ohlcv_data_2023.csv", "store01_rawzone/ibkr_spy_1min/ohlcv_data_2023.csv",
                                                tree_dict_in["start_date"], set())
    assert spy_action_str == "copy"
    passed("--plan prints per-folder counts and does not write VIEW.json or the registry")

# FUNCTION: TIMING TREE OF REALISTIC SHAPE
def build_timing_tree_dict(quarantine_root_str_in):
    """
    Writes a quarantine tree shaped like production: 300 per-day ~5 MB step01 files, one yearly raw file of
    100,000 rows, 30 TSBAR files with 390 rows and 6 distance cells, and a TSDAY table of 5,436 rows.

    Args:
        quarantine_root_str_in (str): Quarantine root

    Returns:
        dict: session list, start date, file and byte counts
    """
    # SESSIONS 2022-2024 SO THE HOLDOUT START IS IN 2023
    session_2022_list = get_session_date_list("2022-01-03", "2022-12-30")
    session_2023_list = get_session_date_list("2023-01-03", "2023-12-29")
    session_2024_list = get_session_date_list("2024-01-02", "2024-01-16")
    spy_session_list = session_2022_list + session_2023_list + session_2024_list
    pad_session_list = get_session_date_list("2002-01-02", "2021-12-31")
    tsday_session_list = (pad_session_list + spy_session_list)[-5436:]
    assert len(tsday_session_list) == 5436
    assert tsday_session_list[-1] == spy_session_list[-1]
    window_dict = compute_holdout_window_dict(spy_session_list)
    start_date = window_dict["start"]
    spy_str = get_rel_str(quarantine_root_str_in, "store01_rawzone", "ibkr_spy_1min")
    pa_str = get_rel_str(quarantine_root_str_in, "store02_workzone", "step01_PA_ohlcv_data")
    tsbar_str = get_rel_str(quarantine_root_str_in, "store03_goldzone", "step05_TSBAR_data")
    tsday_str = get_rel_str(quarantine_root_str_in, "store02_workzone", "step06_TSDAY_data")
    os.makedirs(spy_str, exist_ok=True)
    # YEARLY 2022: ABOUT 100,000 UNIQUE BARS
    n_rows_int = 100000
    n_sessions_int = len(session_2022_list)
    bars_per_int = n_rows_int // n_sessions_int
    extra_int = n_rows_int - bars_per_int * n_sessions_int
    line_list = ["timestamp,open,high,low,close,volume"]
    for session_idx, session_date in enumerate(session_2022_list):
        n_int = bars_per_int + (1 if session_idx < extra_int else 0)
        day_str = pd.Timestamp(session_date).strftime("%Y-%m-%d")
        for bar_idx in range(n_int):
            minute_int = 14 * 60 + 30 + bar_idx
            hour_int, minute_only_int = divmod(minute_int, 60)
            line_list.append(f"{day_str} {hour_int:02d}:{minute_only_int:02d}:00+00:00,100.0,101.0,99.0,100.5,1000")
    os.makedirs(spy_str, exist_ok=True)
    with open(os.path.join(spy_str, "ohlcv_data_2022.csv"), "w", encoding="utf-8", newline="\n") as spy_file:
        spy_file.write("\n".join(line_list) + "\n")
    write_raw_csv_bytes(os.path.join(spy_str, "ohlcv_data_2023.csv"), session_2023_list)
    write_raw_csv_bytes(os.path.join(spy_str, "ohlcv_data_2024.csv"), session_2024_list)
    # 300 PER-DAY ~5 MB FILES IN STEP01, DATED WELL BEFORE THE SCAN TAIL
    pa_date_list = get_session_date_list("2021-01-04", "2022-06-30")[:300]
    assert len(pa_date_list) == 300
    fill_bytes = b"2020-01-02,1.0\n"
    header_bytes = b"date,close\n"
    target_int = 5 * 1024 * 1024
    fill_count_int = max(1, (target_int - 80) // len(fill_bytes))
    body_bytes = fill_bytes * fill_count_int
    os.makedirs(pa_str, exist_ok=True)
    for session_date in pa_date_list:
        last_bytes = f"{session_date},100.5\n".encode("utf-8")
        file_path_str = os.path.join(pa_str, f"PA_ohlcv_{session_date.strftime('%Y%m%d')}.csv")
        with open(file_path_str, "wb") as pa_file:
            pa_file.write(header_bytes)
            pa_file.write(body_bytes)
            pa_file.write(last_bytes)
    # 30 TSBAR FILES: 390 ROWS, 6 DISTANCE CELLS
    os.makedirs(tsbar_str, exist_ok=True)
    before_s_list = [session_date for session_date in spy_session_list if session_date < start_date]
    tsbar_date_list = before_s_list[-30:]
    distance_list = ["0.0010", "0.0020", "0.0030", "0.0040", "0.0050", "0.0060"]
    near_cell_str = encode_TSBAR_cell_str(1, 100.10, "SL")
    for session_date in tsbar_date_list:
        stamp_str = get_session_bar_str_list(session_date)[0]
        day_str = str(session_date)
        row_dict_list = []
        for row_idx in range(390):
            row_dict = {"decision_ts": stamp_str, "entry_ts": stamp_str, "entry_price": "100.0",
                        "horizon_complete": "True", "rr_ratio": "1.0", "date": day_str}
            for column_str in distance_list:
                row_dict[column_str] = near_cell_str
            row_dict_list.append(row_dict)
        pd.DataFrame(row_dict_list).to_csv(os.path.join(tsbar_str, f"TSBAR_{session_date.strftime('%Y%m%d')}.csv"), index=False)
    write_dated_csv(os.path.join(tsday_str, "TSDAY_data.csv"), tsday_session_list,
                    {"close": "100.5", "fwd_net_return_20d": "0.01", "y_fwd_positive": "1"})
    for folder_str in (
        get_rel_str(quarantine_root_str_in, "store01_rawzone", "ibkr_vix_family", "vix_1min"),
        get_rel_str(quarantine_root_str_in, "store01_rawzone", "ibkr_vix_family", "vix_daily"),
        get_rel_str(quarantine_root_str_in, "store01_rawzone", "ibkr_vix_family", "vix3m_1min"),
        get_rel_str(quarantine_root_str_in, "store01_rawzone", "ibkr_vix_family", "vix3m_daily"),
        get_rel_str(quarantine_root_str_in, "store02_workzone", "step02_TSIND_data"),
        get_rel_str(quarantine_root_str_in, "store02_workzone", "step03_TSSEG_data"),
        get_rel_str(quarantine_root_str_in, "store02_workzone", "step04_TSCTX_data"),
    ):
        os.makedirs(folder_str, exist_ok=True)
    file_count_int = 0
    byte_count_int = 0
    for walk_root_str, _dir_list, file_list in os.walk(quarantine_root_str_in):
        for file_name_str in file_list:
            file_path_str = os.path.join(walk_root_str, file_name_str)
            file_count_int += 1
            byte_count_int += int(os.path.getsize(file_path_str))
    return {"session_date_list": spy_session_list, "start_date": start_date, "window_dict": window_dict,
            "file_count": file_count_int, "byte_count": byte_count_int, "pa_file_count": 300}

# FUNCTION: TIMING AND PROJECTION ON A REALISTIC-SHAPE TREE
def test_refresh_timing_and_projection():
    """
    Build and scan a tree of realistic shape, print seconds, and project the real 61,405-file / 62 GB tree.

    Returns:
        dict: Timings and projection
    """
    # ISOLATED ROOTS SO THE SMALL-TREE TESTS ARE UNTOUCHED
    timing_view_str = tempfile.mkdtemp(prefix="so_timing_view_")
    timing_quarantine_str = tempfile.mkdtemp(prefix="so_timing_q_")
    saved_view_str = os.environ["SO_DATA_PATH"]
    saved_quarantine_str = os.environ["SO_QUARANTINE_PATH"]
    saved_registry_str = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    try:
        os.environ["SO_DATA_PATH"] = timing_view_str
        os.environ["SO_QUARANTINE_PATH"] = timing_quarantine_str
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = os.path.join(timing_view_str, "holdout_windows.csv")
        tree_dict = build_timing_tree_dict(timing_quarantine_str)
        open_holdout_window_dict(tree_dict["session_date_list"],
                                 f"OPEN {tree_dict['window_dict']['start']} {tree_dict['window_dict']['end']}",
                                 file_path_str_in=paths.HOLDOUT_WINDOWS_FILE_PATH_STR)
        result_dict = run_refresh_development_view_dict(run_pipeline_bool_in=False)
        build_seconds = float(result_dict["build_seconds"])
        scan_seconds = float(result_dict["scan_seconds"])
        n_int = int(tree_dict["file_count"])
        bytes_int = int(tree_dict["byte_count"])
        real_files_int = 61405
        real_bytes_int = 62 * (10 ** 9)
        file_scale_float = real_files_int / max(n_int, 1)
        byte_scale_float = real_bytes_int / max(bytes_int, 1)
        proj_build_files_float = build_seconds * file_scale_float
        proj_build_bytes_float = build_seconds * byte_scale_float
        proj_scan_float = scan_seconds * file_scale_float
        proj_total_float = proj_build_bytes_float + proj_scan_float
        print(
            f"TIMING build={build_seconds:.3f}s scan={scan_seconds:.3f}s "
            f"files={n_int} bytes={bytes_int} pa_files={tree_dict['pa_file_count']}"
        )
        print(
            f"PROJECTION 61405 files / 62 GB: "
            f"build_file_scaled={proj_build_files_float:.1f}s "
            f"build_byte_scaled={proj_build_bytes_float:.1f}s "
            f"scan_file_scaled={proj_scan_float:.1f}s "
            f"total_byte_plus_scan={proj_total_float:.1f}s"
        )
        assert build_seconds >= 0.0
        assert scan_seconds >= 0.0
        assert n_int >= 300
        assert os.path.isfile(os.path.join(timing_view_str, "VIEW.json"))
        passed("timing tree: build and scan seconds plus real-tree projection")
        return {"build_seconds": build_seconds, "scan_seconds": scan_seconds, "file_count": n_int,
                "byte_count": bytes_int, "proj_build_files": proj_build_files_float,
                "proj_build_bytes": proj_build_bytes_float, "proj_scan": proj_scan_float,
                "proj_total": proj_total_float}
    finally:
        os.environ["SO_DATA_PATH"] = saved_view_str
        os.environ["SO_QUARANTINE_PATH"] = saved_quarantine_str
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = saved_registry_str
        shutil.rmtree(timing_view_str, ignore_errors=True)
        shutil.rmtree(timing_quarantine_str, ignore_errors=True)

# RUN THE SUITE
if __name__ == "__main__":
    # RUN EVERY CHECK, THEN REMOVE THE TEMPORARY FOLDERS
    try:
        test_file_name_span()
        test_refresh_refuses_without_roots()
        test_tsbar_exit_dict_matches_linear_walk()
        tree_dict = test_first_view_cut_and_redact()
        test_plan_does_not_write(tree_dict)
        test_second_run_copies_nothing(tree_dict)
        test_run_pipeline_copies_notebooks()
        slid_tree_dict = test_slide_moves_sessions_and_fills_labels(tree_dict)
        test_planted_file_fails_scan(slid_tree_dict)
        test_refresh_timing_and_projection()
        # THE REAL REGISTRY IS UNCHANGED
        assert os.path.isfile(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_EXISTS_BOOL
        if REAL_WINDOWS_EXISTS_BOOL:
            assert os.path.getsize(REAL_WINDOWS_PATH_STR) == REAL_WINDOWS_SIZE_INT
        print("\nAll development-view refresh tests passed ✅")
    finally:
        shutil.rmtree(TEMP_VIEW_STR, ignore_errors=True)
        shutil.rmtree(TEMP_QUARANTINE_STR, ignore_errors=True)
        os.environ.pop("SO_QUARANTINE_PATH", None)
