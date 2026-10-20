import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE SHARED CONFIGURATION AND THE PATHS
from so import config, paths
# IMPORT THE NEW YORK TIME ZONE
from so.core.datetime_utils import ny_tz
# IMPORT THE HOLDOUT HELPERS (LATEST SESSION, SESSION LIST, SLIDE)
from so.core.holdout import get_active_holdout_window_dict, get_latest_session_date, get_raw_session_date_list, slide_holdout_window_dict
# IMPORT THE UNRESOLVED TSBAR CELL FORM
from so.features.barrier_labels import encode_TSBAR_cell_str
import pandas as pd

"""
Development View Refresh (Nicolas only)

Only Nicolas may run this script. Agents must not. It rebuilds the development view at SO_DATA_PATH from the complete
tree at SO_QUARANTINE_PATH: sessions strictly before the active holdout start, with forward-looking TSBAR and TSDAY
labels redacted so a clock on or after that start cannot be read. store04_experiments is never touched. The notebooks
in the repo are never modified. Real data is not read unless Nicolas runs the script with both variables set.
"""

# THE WORKSPACE ROOT (THE HOLDOUT REGISTRY LIVES UNDER records/)
WORKSPACE_PATH_STR = str(Path(__file__).resolve().parents[1])
# THE ONLY REGISTRY FILE THIS SCRIPT MAY COMMIT
REGISTRY_COMMIT_PATH_STR = os.path.normcase(os.path.abspath(os.path.join(WORKSPACE_PATH_STR, "records", "holdout_windows.csv")))
# THE PIPELINE NOTEBOOKS, IN ORDER (STEP 07 IS NOT PART OF THE REFRESH)
PIPELINE_NOTEBOOK_LIST = [
    "pipeline/step00_data_quality_check.ipynb",
    "pipeline/step01_PA_ohlcv_data_collection.ipynb",
    "pipeline/step02_TSIND_data_collection.ipynb",
    "pipeline/step03_TSSEG_data_collection.ipynb",
    "pipeline/step04_TSCTX_data_collection.ipynb",
    "pipeline/step05_TSBAR_data_collection.ipynb",
    "pipeline/step06_TSDAY_data_collection.ipynb",
]
# THE FOLDERS THE RESEARCH CODE READS (NEVER STAGING, BACKUPS, STEP 00, OR STORE04)
VIEW_PATH_NAME_LIST = [
    "LOCAL_OHLCV_DATA_FILE_PATH_STR",
    "LOCAL_VIX_1MIN_DATA_FILE_PATH_STR",
    "LOCAL_VIX_DAILY_DATA_FILE_PATH_STR",
    "LOCAL_VIX3M_1MIN_DATA_FILE_PATH_STR",
    "LOCAL_VIX3M_DAILY_DATA_FILE_PATH_STR",
    "LOCAL_PA_OHLCV_DATA_FILE_PATH_STR",
    "LOCAL_TSIND_DATA_FILE_PATH_STR",
    "LOCAL_TSSEG_DATA_FILE_PATH_STR",
    "LOCAL_TSCTX_DATA_FILE_PATH_STR",
    "LOCAL_TSBAR_DATA_FILE_PATH_STR",
    "LOCAL_TSDAY_DATA_FILE_PATH_STR",
]
# COLUMNS THAT ARE NOT A TSBAR DISTANCE CELL
TSBAR_META_COLUMN_SET = {"decision_ts", "entry_ts", "entry_price", "horizon_complete", "rr_ratio", "date", "timestamp"}
# THE UNRESOLVED DISTANCE CELL point_in_time TREATS AS UNFINISHED
UNRESOLVED_TSBAR_CELL_STR = encode_TSBAR_cell_str(-1, float("nan"), config.EXIT_REASON_NA)

"""
Logging
"""

# FUNCTION: APPEND ONE LINE TO THE LOG AND TO STDOUT
def write_log_line(log_file_in, message_str_in):
    """
    Writes one line to the refresh log and to stdout.

    Args:
        log_file_in: Open text file, or None
        message_str_in (str): Line, without a trailing newline

    Returns:
        None
    """
    # PRINT, THEN COPY TO THE LOG WHEN IT IS OPEN
    print(message_str_in, flush=True)
    if log_file_in is not None:
        log_file_in.write(message_str_in.rstrip("\n") + "\n")
        log_file_in.flush()

"""
Paths And File Names
"""

# FUNCTION: NORMALIZE A FOLDER PATH
def get_normalized_root_str(path_str_in):
    """
    Absolute folder path, forward slashes, one trailing slash, case-normalized on Windows.

    Args:
        path_str_in (str): Folder

    Returns:
        str: Normalized folder
    """
    # ABSOLUTE, FORWARD SLASHES, ONE TRAILING SLASH
    abs_str = os.path.abspath(path_str_in).replace("\\", "/").rstrip("/") + "/"
    return abs_str

# FUNCTION: RELATIVE POSIX PATH OF A FILE INSIDE A ROOT
def get_relative_path_str(path_str_in, root_str_in):
    """
    Path of a file relative to a root, with forward slashes.

    Args:
        path_str_in (str): File
        root_str_in (str): Root folder

    Returns:
        str: Relative path
    """
    # RELATIVE PATH WITH FORWARD SLASHES
    return os.path.relpath(path_str_in, root_str_in).replace("\\", "/")

# FUNCTION: JOIN A ROOT AND A RELATIVE POSIX PATH
def get_joined_path_str(root_str_in, relative_path_str_in):
    """
    Joins a root folder and a relative path that uses forward slashes.

    Args:
        root_str_in (str): Root folder
        relative_path_str_in (str): Relative path

    Returns:
        str: Joined path
    """
    # SPLIT ON FORWARD SLASHES SO WINDOWS JOINS CORRECTLY
    return os.path.join(root_str_in, *relative_path_str_in.split("/"))

# FUNCTION: SHA256 OF A FILE
def get_file_sha256_str(file_path_str_in):
    """
    Hex digest of a file's bytes.

    Args:
        file_path_str_in (str): File

    Returns:
        str: Hex digest
    """
    # HASH IN CHUNKS
    digest = hashlib.sha256()
    with open(file_path_str_in, "rb") as file_handle:
        for chunk_bytes in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk_bytes)
    return digest.hexdigest()

# FUNCTION: SIZE AND MTIME OF A SOURCE FILE
def get_source_stamp_dict(file_path_str_in):
    """
    Size and modification time of a source file.

    Args:
        file_path_str_in (str): File

    Returns:
        dict: source_size, source_mtime
    """
    # INTEGER NANOSECONDS SO A SECOND RUN CAN SKIP EXACTLY
    file_stat = os.stat(file_path_str_in)
    return {"source_size": int(file_stat.st_size), "source_mtime": int(file_stat.st_mtime_ns)}

# FUNCTION: THE DATE SPAN STAMPED ON A FILE NAME
def get_file_name_date_span_tuple(file_path_str_in):
    """
    Inclusive calendar span of a trailing YYYY, YYYYMM or YYYYMMDD token. None when the name has no such token.

    Args:
        file_path_str_in (str): File path or name

    Returns:
        tuple[datetime.date, datetime.date] | None: Start and end, or None
    """
    # LAST TOKEN OF THE STEM
    stem_str = os.path.splitext(os.path.basename(file_path_str_in))[0]
    token_str = stem_str.split("_")[-1]
    # DAILY YYYYMMDD
    if len(token_str) == 8 and token_str.isdigit():
        day_date = pd.to_datetime(token_str, format="%Y%m%d").date()
        return (day_date, day_date)
    # MONTHLY YYYYMM
    if len(token_str) == 6 and token_str.isdigit():
        month_start_date = pd.to_datetime(token_str, format="%Y%m").date()
        month_end_date = (pd.Timestamp(month_start_date) + pd.offsets.MonthEnd(0)).date()
        return (month_start_date, month_end_date)
    # YEARLY YYYY
    if len(token_str) == 4 and token_str.isdigit():
        year_int = int(token_str)
        return (pd.Timestamp(f"{year_int}-01-01").date(), pd.Timestamp(f"{year_int}-12-31").date())
    # NO DATE IN THE NAME
    return None

"""
Row Dates And CSV Lines
"""

# FUNCTION: PARSE A FIELD TO A CALENDAR DATE
def get_field_date(value_str_in, column_str_in):
    """
    Calendar date of one CSV field. A date column is the calendar date. A timestamp is converted from UTC (or its
    own offset) to America/New_York.

    Args:
        value_str_in (str): Field
        column_str_in (str): Column name

    Returns:
        datetime.date | None: The date, or None when the field is empty
    """
    # AN EMPTY CELL HAS NO DATE
    text_str = str(value_str_in).strip()
    if text_str == "" or text_str.lower() in {"nan", "nat", "none"}:
        return None
    # THE DATE COLUMN IS THE SESSION, NOT A UTC MIDNIGHT
    if column_str_in == "date":
        return pd.Timestamp(text_str).date()
    # TIMESTAMPS: UTC WHEN NAIVE, OTHERWISE THE STATED OFFSET, THEN NEW YORK
    timestamp = pd.to_datetime(text_str, utc=False)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert(ny_tz).date()

# FUNCTION: THE DATE COLUMN TO USE ON A HEADER
def get_row_date_column_str(column_list_in):
    """
    The column that dates a row. date wins, then timestamp, then decision_ts, then entry_ts.

    Args:
        column_list_in (list[str]): Header names

    Returns:
        str | None: Column name
    """
    # PREFER THE SESSION DATE, THEN A TIMESTAMP
    for column_str in ("date", "timestamp", "decision_ts", "entry_ts"):
        if column_str in column_list_in:
            return column_str
    return None

# FUNCTION: THE DATE OF ONE CSV DATA LINE
def get_csv_line_date(line_str_in, column_list_in, date_column_str_in):
    """
    Session date of one CSV record, or None when it cannot be read.

    Args:
        line_str_in (str): Data line, with or without a newline
        column_list_in (list[str]): Header names
        date_column_str_in (str): Column to parse

    Returns:
        datetime.date | None: The date
    """
    # PARSE ONE RECORD WITH THE DEFAULT DIALECT
    try:
        field_list = next(csv.reader([line_str_in.rstrip("\r\n")]))
    except (csv.Error, StopIteration):
        return None
    # A SHORT LINE HAS NO DATE
    if date_column_str_in not in column_list_in:
        return None
    column_idx = column_list_in.index(date_column_str_in)
    if column_idx >= len(field_list):
        return None
    try:
        return get_field_date(field_list[column_idx], date_column_str_in)
    except (ValueError, TypeError):
        return None

# FUNCTION: HEADER NAMES OF A CSV FILE
def get_csv_header_list(file_bytes_in):
    """
    Header names of a CSV whose first line is the header.

    Args:
        file_bytes_in (bytes): File contents

    Returns:
        list[str]: Column names
    """
    # DECODE THE FIRST LINE
    text_str = file_bytes_in.decode("utf-8")
    first_str = text_str.splitlines()[0] if text_str else ""
    return next(csv.reader([first_str])) if first_str else []

# FUNCTION: WHETHER A PATH IS A TSBAR CACHE
def get_tsbar_path_bool(relative_path_str_in):
    """
    True when the relative path is under the gold-zone TSBAR folder.

    Args:
        relative_path_str_in (str): Relative path

    Returns:
        bool: TSBAR
    """
    # THE GOLD-ZONE STEP 05 FOLDER
    return "step05_TSBAR_data" in relative_path_str_in.replace("\\", "/")

# FUNCTION: WHETHER A PATH IS THE TSDAY TABLE
def get_tsday_path_bool(relative_path_str_in):
    """
    True when the relative path is the step-06 TSDAY table.

    Args:
        relative_path_str_in (str): Relative path

    Returns:
        bool: TSDAY
    """
    # THE WORK-ZONE STEP 06 FOLDER OR THE TABLE NAME
    posix_str = relative_path_str_in.replace("\\", "/")
    return "step06_TSDAY_data" in posix_str or os.path.basename(posix_str) == "TSDAY_data.csv"

"""
Copy, Cut, Redact
"""

# FUNCTION: COPY ONLY ROWS STRICTLY BEFORE THE HOLDOUT START
def write_cut_file_bytes(source_path_str_in, dest_path_str_in, start_date_in):
    """
    Writes dest_path_str_in with the source header and every data line whose date is strictly before start_date_in.
    Kept lines are the source bytes, including their original line endings. Returns whether any data line was kept.

    Args:
        source_path_str_in (str): Source CSV
        dest_path_str_in (str): Destination CSV
        start_date_in (datetime.date): First date that must not be copied

    Returns:
        bool: True when at least one data line was kept
    """
    # READ THE SOURCE AS BYTES SO THE KEPT LINES ARE UNCHANGED
    source_bytes = Path(source_path_str_in).read_bytes()
    if source_bytes == b"":
        return False
    line_bytes_list = source_bytes.splitlines(keepends=True)
    header_bytes = line_bytes_list[0]
    header_list = get_csv_header_list(source_bytes)
    date_column_str = get_row_date_column_str(header_list)
    # WITHOUT A DATE COLUMN THE FILE CANNOT BE CUT SAFELY: KEEP NOTHING
    kept_bytes_list = [header_bytes]
    kept_row_bool = False
    if date_column_str is not None:
        for line_bytes in line_bytes_list[1:]:
            line_str = line_bytes.decode("utf-8")
            if line_str.strip() == "":
                continue
            line_date = get_csv_line_date(line_str, header_list, date_column_str)
            if line_date is not None and line_date < start_date_in:
                kept_bytes_list.append(line_bytes)
                kept_row_bool = True
    # WRITE ONLY WHEN A ROW SURVIVES (A HEADER-ONLY YEAR FILE IS NOT A VIEW FILE)
    if not kept_row_bool:
        return False
    os.makedirs(os.path.dirname(dest_path_str_in), exist_ok=True)
    Path(dest_path_str_in).write_bytes(b"".join(kept_bytes_list))
    return True

# FUNCTION: PARSE ONE TSBAR DISTANCE CELL
def get_tsbar_cell_tuple(cell_str_in):
    """
    Exit bar count, price text and reason of one distance cell.

    Args:
        cell_str_in (str): Encoded cell

    Returns:
        tuple | None: (count, price_str, reason_str), or None when the cell is not a distance cell
    """
    # A DISTANCE CELL HAS TWO BARS
    text_str = str(cell_str_in)
    if text_str.count("|") < 2:
        return None
    count_str, price_str, reason_str = text_str.split("|", 2)
    try:
        count_int = int(float(count_str))
    except (TypeError, ValueError):
        return None
    return (count_int, price_str, reason_str)

# FUNCTION: SORTED NEW YORK BAR STARTS OF A SPY FOLDER
def get_spy_bar_timestamp_list(raw_folder_str_in):
    """
    Sorted unique New York start labels of every raw SPY CSV in a folder.

    Args:
        raw_folder_str_in (str): Raw SPY folder

    Returns:
        list[pd.Timestamp]: Bar starts
    """
    # READ EVERY CSV, PARSE TIMESTAMP AS UTC, CONVERT TO NEW YORK
    folder_str = raw_folder_str_in.replace("\\", "/").rstrip("/") + "/"
    if not os.path.isdir(folder_str):
        return []
    timestamp_list = []
    for file_name_str in os.listdir(folder_str):
        if not file_name_str.lower().endswith(".csv"):
            continue
        file_path_str = folder_str + file_name_str
        try:
            stamp_pdf = pd.read_csv(file_path_str, usecols=lambda name_str: name_str == "timestamp")
        except (ValueError, pd.errors.EmptyDataError):
            continue
        if "timestamp" not in stamp_pdf.columns:
            continue
        stamp_series = pd.to_datetime(stamp_pdf["timestamp"], utc=True).dt.tz_convert(ny_tz)
        timestamp_list.extend(stamp_series.tolist())
    # UNIQUE AND SORTED
    return sorted(set(timestamp_list))

# FUNCTION: FIRST BAR START ON OR AFTER A DATE
def get_first_bar_timestamp(bar_timestamp_list_in, start_date_in):
    """
    The first bar whose New York date is on or after start_date_in.

    Args:
        bar_timestamp_list_in (list[pd.Timestamp]): Sorted bar starts
        start_date_in (datetime.date): Date

    Returns:
        pd.Timestamp | None: First bar, or None when none exists
    """
    # THE FIRST BAR OF THE HOLDOUT
    for bar_ts in bar_timestamp_list_in:
        if pd.Timestamp(bar_ts).tz_convert(ny_tz).date() >= start_date_in:
            return pd.Timestamp(bar_ts)
    return None

# FUNCTION: WHETHER A TSBAR EXIT FALLS ON OR AFTER THE FIRST HOLDOUT BAR
def get_tsbar_exit_on_or_after_bool(cell_str_in, entry_value_in, bar_timestamp_list_in, first_holdout_ts_in):
    """
    True when a resolved distance cell's exit bar is on or after first_holdout_ts_in, or cannot be placed on the
    bar index (the exit is after the last loaded bar).

    Args:
        cell_str_in (str): Encoded cell
        entry_value_in: entry_ts field
        bar_timestamp_list_in (list[pd.Timestamp]): Sorted bar starts
        first_holdout_ts_in (pd.Timestamp): First bar of the holdout

    Returns:
        bool: Exit on or after the holdout
    """
    # UNRESOLVED CELLS DO NOT CARRY A CLOCK
    cell_tup = get_tsbar_cell_tuple(cell_str_in)
    if cell_tup is None:
        return False
    count_int, _price_str, reason_str = cell_tup
    if count_int < 0 or reason_str == config.EXIT_REASON_NA:
        return False
    if first_holdout_ts_in is None or not bar_timestamp_list_in:
        return True
    # PLACE THE ENTRY ON THE BAR INDEX AND WALK exit_bar_count BARS
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

# FUNCTION: REDACT TSBAR DISTANCE CELLS WHOSE EXIT IS ON OR AFTER THE HOLDOUT
def write_redact_tsbar_file_bool(source_path_str_in, dest_path_str_in, start_date_in, bar_timestamp_list_in, first_holdout_ts_in):
    """
    Copies a TSBAR CSV, drops rows on or after start_date_in, and replaces distance cells whose exit bar is on or
    after the first holdout bar with the unresolved form.

    Args:
        source_path_str_in (str): Source TSBAR file
        dest_path_str_in (str): Destination
        start_date_in (datetime.date): Holdout start
        bar_timestamp_list_in (list[pd.Timestamp]): Quarantine SPY bars
        first_holdout_ts_in (pd.Timestamp | None): First bar of S

    Returns:
        bool: True when the destination was written
    """
    # READ THE SOURCE ROWS
    source_pdf = pd.read_csv(source_path_str_in, dtype=str, keep_default_na=False)
    if source_pdf.empty:
        return False
    date_column_str = get_row_date_column_str(list(source_pdf.columns))
    keep_idx_list = []
    for row_idx, row in source_pdf.iterrows():
        row_date = get_field_date(row[date_column_str], date_column_str) if date_column_str is not None else None
        if row_date is None or row_date >= start_date_in:
            continue
        keep_idx_list.append(row_idx)
        if "entry_ts" not in source_pdf.columns:
            continue
        for column_str in source_pdf.columns:
            if column_str in TSBAR_META_COLUMN_SET:
                continue
            cell_str = row[column_str]
            if get_tsbar_exit_on_or_after_bool(cell_str, row["entry_ts"], bar_timestamp_list_in, first_holdout_ts_in):
                source_pdf.at[row_idx, column_str] = UNRESOLVED_TSBAR_CELL_STR
    if not keep_idx_list:
        return False
    os.makedirs(os.path.dirname(dest_path_str_in), exist_ok=True)
    source_pdf.loc[keep_idx_list].to_csv(dest_path_str_in, index=False)
    return True

# FUNCTION: EMPTY TSDAY FORWARD COLUMNS WHOSE HORIZON ENDS ON OR AFTER THE HOLDOUT
def write_redact_tsday_file_bool(source_path_str_in, dest_path_str_in, start_date_in, session_date_list_in):
    """
    Copies the TSDAY table, drops rows on or after start_date_in, and empties fwd_* / y_fwd* cells whose horizon
    (LABEL_HORIZON_SESSIONS sessions after the row) ends on or after start_date_in.

    Args:
        source_path_str_in (str): Source TSDAY file
        dest_path_str_in (str): Destination
        start_date_in (datetime.date): Holdout start
        session_date_list_in (list[datetime.date]): Quarantine sessions, sorted

    Returns:
        bool: True when the destination was written
    """
    # READ THE TABLE AS TEXT SO EMPTY CELLS STAY EMPTY
    source_pdf = pd.read_csv(source_path_str_in, dtype=str, keep_default_na=False)
    if source_pdf.empty or "date" not in source_pdf.columns:
        return False
    session_date_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in]
    start_date = pd.Timestamp(start_date_in).date()
    try:
        start_idx = session_date_list.index(start_date)
    except ValueError:
        start_idx = next((idx for idx, session_date in enumerate(session_date_list) if session_date >= start_date), len(session_date_list))
    label_column_list = [column_str for column_str in source_pdf.columns if column_str.startswith("fwd_") or column_str.startswith("y_fwd")]
    keep_idx_list = []
    for row_idx, row in source_pdf.iterrows():
        row_date = get_field_date(row["date"], "date")
        if row_date is None or row_date >= start_date:
            continue
        keep_idx_list.append(row_idx)
        try:
            row_session_idx = session_date_list.index(row_date)
        except ValueError:
            continue
        if row_session_idx + int(config.LABEL_HORIZON_SESSIONS) >= start_idx:
            for column_str in label_column_list:
                source_pdf.at[row_idx, column_str] = ""
    if not keep_idx_list:
        return False
    os.makedirs(os.path.dirname(dest_path_str_in), exist_ok=True)
    source_pdf.loc[keep_idx_list].to_csv(dest_path_str_in, index=False)
    return True

# FUNCTION: READ A PREVIOUS MANIFEST
def read_manifest_list(manifest_path_str_in):
    """
    File records of a previous view_manifest.json. A missing or unreadable file is an empty list.

    Args:
        manifest_path_str_in (str): Manifest path

    Returns:
        list[dict]: Records
    """
    # A MISSING MANIFEST MEANS A FIRST BUILD
    if not os.path.isfile(manifest_path_str_in):
        return []
    try:
        with open(manifest_path_str_in, "r", encoding="utf-8") as manifest_file:
            payload = json.load(manifest_file)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return []
    # A LIST IS THE RECORDS; A DICT MAY WRAP THEM
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return list(payload.get("file_list") or payload.get("files") or [])
    return []

# FUNCTION: THE LAST MAX_HOLD SESSIONS BEFORE THE HOLDOUT START
def get_redact_tsbar_date_set(session_date_list_in, start_date_in):
    """
    Dates of the TSBAR files that must be redacted: the last MAX_HOLD_TRADING_DAYS sessions strictly before start.

    Args:
        session_date_list_in (list[datetime.date]): Sorted sessions
        start_date_in (datetime.date): Holdout start

    Returns:
        set[datetime.date]: Session dates
    """
    # SESSIONS STRICTLY BEFORE S, THEN THE LAST MAX_HOLD OF THOSE
    start_date = pd.Timestamp(start_date_in).date()
    before_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in if pd.Timestamp(session_date).date() < start_date]
    return set(before_list[-int(config.MAX_HOLD_TRADING_DAYS):])

"""
Guards, Pipeline, Slide, Scan
"""

# FUNCTION: REFUSE TO START WITHOUT TWO DISTINCT ROOTS AND A QUARANTINE RAW ZONE
def check_refresh_roots_dict():
    """
    Requires SO_DATA_PATH and SO_QUARANTINE_PATH, distinct folders, and store01_rawzone under the quarantine.

    Returns:
        dict: view_root_str, quarantine_root_str
    """
    # BOTH VARIABLES ARE REQUIRED
    view_raw_str = os.environ.get("SO_DATA_PATH", "").strip()
    quarantine_raw_str = os.environ.get("SO_QUARANTINE_PATH", "").strip()
    if view_raw_str == "":
        raise RuntimeError("SO_DATA_PATH is not set. Set it to the development view folder.")
    if quarantine_raw_str == "":
        raise RuntimeError("SO_QUARANTINE_PATH is not set. Set it to the complete data folder.")
    view_root_str = get_normalized_root_str(view_raw_str)
    quarantine_root_str = get_normalized_root_str(quarantine_raw_str)
    # THE TWO FOLDERS MUST BE DIFFERENT (CASE-NORMALIZED ON WINDOWS)
    if os.path.normcase(os.path.abspath(view_root_str)) == os.path.normcase(os.path.abspath(quarantine_root_str)):
        raise RuntimeError("SO_DATA_PATH and SO_QUARANTINE_PATH must point to different folders.")
    # THE QUARANTINE MUST LOOK LIKE THE DATA TREE
    rawzone_str = os.path.join(os.path.abspath(quarantine_root_str), "store01_rawzone")
    if not os.path.isdir(rawzone_str):
        raise RuntimeError("SO_QUARANTINE_PATH has no store01_rawzone. It is not the complete data tree.")
    return {"view_root_str": view_root_str, "quarantine_root_str": quarantine_root_str}

# FUNCTION: DELETE THE DEVELOPMENT VIEW STAMP
def delete_view_stamp(view_root_str_in):
    """
    Removes VIEW.json so a half-built view cannot be used.

    Args:
        view_root_str_in (str): Development view root

    Returns:
        None
    """
    # DELETE THE STAMP WHEN IT EXISTS
    view_path_str = os.path.join(os.path.abspath(view_root_str_in), "VIEW.json")
    if os.path.isfile(view_path_str):
        os.remove(view_path_str)

# FUNCTION: COPY AND RUN THE PIPELINE NOTEBOOKS ON THE QUARANTINE
def run_pipeline_notebooks(quarantine_root_str_in, run_ts_str_in, execute_func_in=None, log_file_in=None):
    """
    Copies pipeline/step00..step06 to <quarantine>/pipeline_runs/<timestamp>/ and executes those copies with
    SO_DATA_PATH set to the quarantine. The notebooks in the repo are not opened for writing.

    Args:
        quarantine_root_str_in (str): Quarantine root
        run_ts_str_in (str): Run timestamp used as the folder name
        execute_func_in (callable | None): Injected executor (None = scripts/execute_notebook.py)
        log_file_in: Refresh log

    Returns:
        str: Folder of the copies
    """
    # THE COPIES LIVE UNDER THE QUARANTINE, NEVER IN THE REPO
    run_folder_str = os.path.join(os.path.abspath(quarantine_root_str_in), "pipeline_runs", run_ts_str_in)
    os.makedirs(run_folder_str, exist_ok=True)
    python_str = sys.executable
    execute_script_str = os.path.join(WORKSPACE_PATH_STR, "scripts", "execute_notebook.py")
    for notebook_str in PIPELINE_NOTEBOOK_LIST:
        source_str = os.path.join(WORKSPACE_PATH_STR, notebook_str.replace("/", os.sep))
        dest_str = os.path.join(run_folder_str, os.path.basename(source_str))
        shutil.copy2(source_str, dest_str)
        write_log_line(log_file_in, f"pipeline copy {notebook_str} -> {dest_str}")
        if execute_func_in is not None:
            execute_func_in(dest_str)
            continue
        # THE CHILD SEES THE QUARANTINE AS SO_DATA_PATH; THE PARENT KEEPS THE VIEW
        child_env_dict = {**os.environ, "SO_DATA_PATH": os.path.abspath(quarantine_root_str_in)}
        write_log_line(log_file_in, f"pipeline execute {dest_str}")
        subprocess.run([python_str, execute_script_str, dest_str], env=child_env_dict, check=True)
    return run_folder_str

# FUNCTION: COMMIT A SLID HOLDOUT REGISTRY
def commit_slid_holdout_window_bool(registry_path_str_in, start_date_in, end_date_in, log_file_in=None):
    """
    Commits only records/holdout_windows.csv when that is the file that was written. Does not push.

    Args:
        registry_path_str_in (str): Registry that was written
        start_date_in, end_date_in: New window bounds
        log_file_in: Refresh log

    Returns:
        bool: True when a commit was made
    """
    # NEVER COMMIT A TEMPORARY REGISTRY A TEST POINTED AT
    written_str = os.path.normcase(os.path.abspath(registry_path_str_in))
    if written_str != REGISTRY_COMMIT_PATH_STR:
        write_log_line(log_file_in, "holdout registry is not records/holdout_windows.csv; not committing")
        return False
    # COMMIT ONLY THAT FILE, DO NOT PUSH
    message_str = f"slide holdout window to {pd.Timestamp(start_date_in).date()} -> {pd.Timestamp(end_date_in).date()}"
    subprocess.run(["git", "commit", "-m", message_str, "--", "records/holdout_windows.csv"], cwd=WORKSPACE_PATH_STR, check=True)
    write_log_line(log_file_in, f"git commit -- records/holdout_windows.csv ({message_str})")
    return True

# FUNCTION: SCAN THE FINISHED VIEW FOR HOLDOUT LEAKS
def get_view_scan_finding_list(view_root_str_in, start_date_in, session_date_list_in):
    """
    Findings in store01-store03 of the view: a file name dated on or after S, a row dated on or after S, a TSBAR
    exit whose clock is on or after S, or a TSDAY forward value whose horizon ends on or after S.

    Args:
        view_root_str_in (str): Development view root
        start_date_in (datetime.date): Holdout start
        session_date_list_in (list[datetime.date]): Quarantine sessions (for the TSDAY horizon)

    Returns:
        list[str]: Findings (empty when the view is clean)
    """
    # WALK ONLY THE THREE DATA ZONES OF THE VIEW
    start_date = pd.Timestamp(start_date_in).date()
    view_root_str = os.path.abspath(view_root_str_in)
    finding_list = []
    spy_folder_str = os.path.join(view_root_str, "store01_rawzone", "ibkr_spy_1min")
    bar_timestamp_list = get_spy_bar_timestamp_list(spy_folder_str) if os.path.isdir(spy_folder_str) else []
    first_holdout_ts = get_first_bar_timestamp(bar_timestamp_list, start_date)
    if first_holdout_ts is None:
        first_holdout_ts = pd.Timestamp(start_date, tz=ny_tz)
    session_date_list = [pd.Timestamp(session_date).date() for session_date in session_date_list_in]
    try:
        start_idx = session_date_list.index(start_date)
    except ValueError:
        start_idx = next((idx for idx, session_date in enumerate(session_date_list) if session_date >= start_date), len(session_date_list))
    for zone_str in ("store01_rawzone", "store02_workzone", "store03_goldzone"):
        zone_root_str = os.path.join(view_root_str, zone_str)
        if not os.path.isdir(zone_root_str):
            continue
        for walk_root_str, _dir_list, file_list in os.walk(zone_root_str):
            for file_name_str in file_list:
                file_path_str = os.path.join(walk_root_str, file_name_str)
                relative_path_str = get_relative_path_str(file_path_str, view_root_str)
                name_span_tup = get_file_name_date_span_tuple(file_name_str)
                if name_span_tup is not None and name_span_tup[0] >= start_date:
                    finding_list.append(f"file name dated on or after {start_date}: {relative_path_str}")
                    continue
                if not file_name_str.lower().endswith(".csv"):
                    continue
                try:
                    file_bytes = Path(file_path_str).read_bytes()
                except OSError:
                    finding_list.append(f"unreadable: {relative_path_str}")
                    continue
                if file_bytes == b"":
                    continue
                header_list = get_csv_header_list(file_bytes)
                date_column_str = get_row_date_column_str(header_list)
                line_str_list = file_bytes.decode("utf-8").splitlines()
                tsbar_bool = get_tsbar_path_bool(relative_path_str)
                tsday_bool = get_tsday_path_bool(relative_path_str)
                label_column_list = [column_str for column_str in header_list if column_str.startswith("fwd_") or column_str.startswith("y_fwd")]
                for line_str in line_str_list[1:]:
                    if line_str.strip() == "":
                        continue
                    row_date = get_csv_line_date(line_str, header_list, date_column_str) if date_column_str else None
                    if row_date is not None and row_date >= start_date:
                        finding_list.append(f"row dated {row_date} on or after {start_date}: {relative_path_str}")
                        continue
                    try:
                        field_list = next(csv.reader([line_str]))
                    except (csv.Error, StopIteration):
                        continue
                    field_dict = {column_str: field_list[idx] if idx < len(field_list) else "" for idx, column_str in enumerate(header_list)}
                    if tsbar_bool and "entry_ts" in field_dict:
                        for column_str, cell_str in field_dict.items():
                            if column_str in TSBAR_META_COLUMN_SET:
                                continue
                            if get_tsbar_exit_on_or_after_bool(cell_str, field_dict["entry_ts"], bar_timestamp_list, first_holdout_ts):
                                finding_list.append(f"TSBAR exit on or after {start_date}: {relative_path_str} {column_str}")
                    if tsday_bool and row_date is not None:
                        try:
                            row_session_idx = session_date_list.index(row_date)
                        except ValueError:
                            continue
                        if row_session_idx + int(config.LABEL_HORIZON_SESSIONS) >= start_idx:
                            for column_str in label_column_list:
                                value_str = str(field_dict.get(column_str, "")).strip()
                                if value_str != "" and value_str.lower() not in {"nan", "none"}:
                                    finding_list.append(f"TSDAY forward value whose horizon ends on or after {start_date}: {relative_path_str} {column_str}")
    return finding_list

# FUNCTION: BUILD ONE MANIFEST RECORD
def get_manifest_record_dict(relative_path_str_in, source_path_str_in, dest_path_str_in, action_str_in):
    """
    One view_manifest.json record.

    Args:
        relative_path_str_in (str): Path relative to the view root
        source_path_str_in (str | None): Source file (None for a remove)
        dest_path_str_in (str | None): Written file (None for a remove)
        action_str_in (str): copy, cut, redact or remove

    Returns:
        dict: Manifest record
    """
    # A REMOVE HAS NO WRITTEN FILE TO HASH
    stamp_dict = get_source_stamp_dict(source_path_str_in) if source_path_str_in and os.path.isfile(source_path_str_in) else {"source_size": 0, "source_mtime": 0}
    sha_str = get_file_sha256_str(dest_path_str_in) if dest_path_str_in and os.path.isfile(dest_path_str_in) else ""
    return {"relative_path": relative_path_str_in, "source_size": stamp_dict["source_size"],
            "source_mtime": stamp_dict["source_mtime"], "sha256": sha_str, "action": action_str_in}

# FUNCTION: WHETHER A PREVIOUS RECORD CAN BE REUSED
def get_skip_copy_bool(previous_dict_in, stamp_dict_in, action_str_in, start_date_in, previous_start_date_in, dest_path_str_in):
    """
    True when the destination already matches this source and the same action still applies.

    Args:
        previous_dict_in (dict | None): Previous manifest row
        stamp_dict_in (dict): Current source size and mtime
        action_str_in (str): Action that would be taken
        start_date_in (datetime.date): Current holdout start
        previous_start_date_in (datetime.date | None): Holdout start of the previous build
        dest_path_str_in (str): Destination file

    Returns:
        bool: Skip
    """
    # NOTHING TO REUSE
    if previous_dict_in is None or not os.path.isfile(dest_path_str_in):
        return False
    if int(previous_dict_in.get("source_size", -1)) != int(stamp_dict_in["source_size"]):
        return False
    if int(previous_dict_in.get("source_mtime", -1)) != int(stamp_dict_in["source_mtime"]):
        return False
    if str(previous_dict_in.get("action", "")) != action_str_in:
        return False
    # A SLIDE CHANGES CUTS AND REDACTIONS EVEN WHEN THE SOURCE FILE DID NOT
    if action_str_in != "copy" and (previous_start_date_in is None or pd.Timestamp(previous_start_date_in).date() != pd.Timestamp(start_date_in).date()):
        return False
    return True

# FUNCTION: BUILD THE DEVELOPMENT VIEW
def build_development_view_list(view_root_str_in, quarantine_root_str_in, start_date_in, session_date_list_in, log_file_in=None):
    """
    Copies, cuts, redacts and removes files under the research folders so the view stops before start_date_in.

    Args:
        view_root_str_in (str): Development view root
        quarantine_root_str_in (str): Quarantine root
        start_date_in (datetime.date): Active window start
        session_date_list_in (list[datetime.date]): Quarantine sessions
        log_file_in: Refresh log

    Returns:
        list[dict]: New manifest records
    """
    # PREVIOUS MANIFEST (FOR SKIP AND FOR REMOVE)
    start_date = pd.Timestamp(start_date_in).date()
    view_root_str = os.path.abspath(view_root_str_in)
    quarantine_root_str = os.path.abspath(quarantine_root_str_in)
    manifest_path_str = os.path.join(view_root_str, "view_manifest.json")
    previous_list = read_manifest_list(manifest_path_str)
    previous_dict = {str(record_dict.get("relative_path", "")): record_dict for record_dict in previous_list}
    previous_start_date = None
    if os.path.isfile(manifest_path_str):
        try:
            with open(manifest_path_str, "r", encoding="utf-8") as manifest_file:
                previous_payload = json.load(manifest_file)
            if isinstance(previous_payload, dict) and previous_payload.get("window_start"):
                previous_start_date = pd.Timestamp(previous_payload["window_start"]).date()
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            previous_start_date = None
    spy_source_str = paths.get_quarantine_named_path_str("LOCAL_OHLCV_DATA_FILE_PATH_STR")
    bar_timestamp_list = get_spy_bar_timestamp_list(spy_source_str)
    first_holdout_ts = get_first_bar_timestamp(bar_timestamp_list, start_date)
    tsbar_date_set = get_redact_tsbar_date_set(session_date_list_in, start_date)
    wanted_set = set()
    record_list = []
    copy_count = 0
    skip_count = 0
    # EACH RESEARCH FOLDER, FILES ONLY
    for name_str in VIEW_PATH_NAME_LIST:
        source_folder_str = paths.get_quarantine_named_path_str(name_str)
        dest_folder_str = paths.get_named_data_path_str(name_str)
        if not os.path.isdir(source_folder_str):
            continue
        for file_name_str in os.listdir(source_folder_str):
            source_path_str = os.path.join(source_folder_str, file_name_str)
            if not os.path.isfile(source_path_str):
                continue
            relative_path_str = get_relative_path_str(source_path_str, quarantine_root_str)
            dest_path_str = get_joined_path_str(view_root_str, relative_path_str)
            name_span_tup = get_file_name_date_span_tuple(file_name_str)
            tsbar_bool = get_tsbar_path_bool(relative_path_str)
            tsday_bool = get_tsday_path_bool(relative_path_str)
            file_date = name_span_tup[0] if name_span_tup is not None and name_span_tup[0] == name_span_tup[1] else None
            # A FILE DATED ON OR AFTER S IS NOT COPIED
            if name_span_tup is not None and name_span_tup[0] >= start_date:
                continue
            if tsbar_bool and file_date is not None and file_date in tsbar_date_set:
                action_str = "redact"
            elif tsday_bool:
                action_str = "redact"
            elif name_span_tup is None or name_span_tup[0] < start_date <= name_span_tup[1]:
                action_str = "cut"
            else:
                action_str = "copy"
            stamp_dict = get_source_stamp_dict(source_path_str)
            previous_record_dict = previous_dict.get(relative_path_str)
            if get_skip_copy_bool(previous_record_dict, stamp_dict, action_str, start_date, previous_start_date, dest_path_str):
                record_list.append(dict(previous_record_dict))
                wanted_set.add(relative_path_str)
                skip_count += 1
                continue
            written_bool = False
            if action_str == "copy":
                os.makedirs(os.path.dirname(dest_path_str), exist_ok=True)
                shutil.copy2(source_path_str, dest_path_str)
                written_bool = True
                copy_count += 1
            elif action_str == "cut":
                written_bool = write_cut_file_bytes(source_path_str, dest_path_str, start_date)
            elif tsday_bool:
                written_bool = write_redact_tsday_file_bool(source_path_str, dest_path_str, start_date, session_date_list_in)
            else:
                written_bool = write_redact_tsbar_file_bool(source_path_str, dest_path_str, start_date, bar_timestamp_list, first_holdout_ts)
            if not written_bool:
                continue
            wanted_set.add(relative_path_str)
            record_list.append(get_manifest_record_dict(relative_path_str, source_path_str, dest_path_str, action_str))
    # REMOVE FILES THE PREVIOUS MANIFEST PUT IN THE VIEW THAT DO NOT BELONG NOW (STORE01-STORE03 ONLY)
    for relative_path_str, previous_record_dict in previous_dict.items():
        if relative_path_str in wanted_set:
            continue
        if str(previous_record_dict.get("action", "")) == "remove":
            continue
        posix_str = relative_path_str.replace("\\", "/")
        if not (posix_str.startswith("store01_rawzone/") or posix_str.startswith("store02_workzone/") or posix_str.startswith("store03_goldzone/")):
            continue
        dest_path_str = get_joined_path_str(view_root_str, relative_path_str)
        if os.path.isfile(dest_path_str):
            os.remove(dest_path_str)
            write_log_line(log_file_in, f"remove {relative_path_str}")
        record_list.append({"relative_path": relative_path_str, "source_size": 0, "source_mtime": 0, "sha256": "", "action": "remove"})
    write_log_line(log_file_in, f"view files written {len(wanted_set)} (copied {copy_count}, skipped {skip_count})")
    return record_list

# FUNCTION: WRITE THE MANIFEST
def write_manifest_file(view_root_str_in, start_date_in, record_list_in):
    """
    Writes view_manifest.json (window_start plus the file records).

    Args:
        view_root_str_in (str): View root
        start_date_in (datetime.date): Holdout start
        record_list_in (list[dict]): File records

    Returns:
        str: Manifest path
    """
    # WINDOW START IS STORED SO THE NEXT RUN CAN SKIP CUTS AND REDACTIONS
    manifest_path_str = os.path.join(os.path.abspath(view_root_str_in), "view_manifest.json")
    payload_dict = {"window_start": str(pd.Timestamp(start_date_in).date()), "file_list": list(record_list_in)}
    with open(manifest_path_str, "w", encoding="utf-8", newline="\n") as manifest_file:
        json.dump(payload_dict, manifest_file, indent=2)
        manifest_file.write("\n")
    return manifest_path_str

# FUNCTION: WRITE THE DEVELOPMENT VIEW STAMP
def write_view_stamp_file(view_root_str_in, window_dict_in, built_ts_str_in, last_session_date_in, manifest_sha_str_in):
    """
    Writes VIEW.json after a clean scan.

    Args:
        view_root_str_in (str): View root
        window_dict_in (dict): Active window
        built_ts_str_in (str): Build timestamp
        last_session_date_in (datetime.date): Quarantine last session
        manifest_sha_str_in (str): sha256 of view_manifest.json

    Returns:
        str: VIEW.json path
    """
    # THE STAMP THE LOADERS CHECK
    view_path_str = os.path.join(os.path.abspath(view_root_str_in), "VIEW.json")
    stamp_dict = {
        "window_id": str(window_dict_in["window_id"]),
        "window_start": str(pd.Timestamp(window_dict_in["start"]).date()),
        "window_end": str(pd.Timestamp(window_dict_in["end"]).date()),
        "built_ts": built_ts_str_in,
        "quarantine_last_session": str(pd.Timestamp(last_session_date_in).date()),
        "manifest_sha256": manifest_sha_str_in,
    }
    with open(view_path_str, "w", encoding="utf-8", newline="\n") as view_file:
        json.dump(stamp_dict, view_file, indent=2)
        view_file.write("\n")
    return view_path_str

# FUNCTION: RUN THE DEVELOPMENT VIEW REFRESH
def run_refresh_development_view_dict(run_pipeline_bool_in=False, execute_func_in=None):
    """
    Rebuilds the development view. Nicolas only. Both SO_DATA_PATH and SO_QUARANTINE_PATH must be set.

    Args:
        run_pipeline_bool_in (bool): Execute pipeline steps 00-06 on copies under the quarantine
        execute_func_in (callable | None): Injected notebook executor for tests

    Returns:
        dict: window_dict, last_session_date, slid_bool, finding_list, view_path_str
    """
    # PRINT WHO MAY RUN THE SCRIPT
    print("Only Nicolas may run scripts/refresh_development_view.py. Agents must not.")
    # REFUSE TO START WITHOUT TWO DISTINCT ROOTS
    root_dict = check_refresh_roots_dict()
    view_root_str = root_dict["view_root_str"]
    quarantine_root_str = root_dict["quarantine_root_str"]
    run_ts_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_folder_str = os.path.join(os.path.abspath(quarantine_root_str), "refresh_logs")
    os.makedirs(log_folder_str, exist_ok=True)
    log_path_str = os.path.join(log_folder_str, f"{run_ts_str}.log")
    with open(log_path_str, "w", encoding="utf-8", newline="\n") as log_file:
        write_log_line(log_file, f"refresh {run_ts_str}")
        write_log_line(log_file, f"SO_DATA_PATH={view_root_str}")
        write_log_line(log_file, f"SO_QUARANTINE_PATH={quarantine_root_str}")
        # DELETE THE STAMP FIRST SO A HALF-BUILT VIEW CAN NEVER BE USED
        delete_view_stamp(view_root_str)
        write_log_line(log_file, "deleted VIEW.json")
        # OPTIONAL PIPELINE ON COPIES, WITH SO_DATA_PATH POINTED AT THE QUARANTINE IN THE CHILD
        if run_pipeline_bool_in:
            run_pipeline_notebooks(quarantine_root_str, run_ts_str, execute_func_in=execute_func_in, log_file_in=log_file)
        # LATEST QUARANTINE SESSION: RAW SPY MUST EQUAL STEP06
        raw_path_str = paths.get_quarantine_named_path_str("LOCAL_OHLCV_DATA_FILE_PATH_STR")
        tsday_path_str = paths.get_quarantine_named_path_str("LOCAL_TSDAY_DATA_FILE_PATH_STR") + "TSDAY_data.csv"
        last_session_date = get_latest_session_date(raw_path_str, tsday_path_str)
        session_date_list = get_raw_session_date_list(raw_path_str)
        write_log_line(log_file, f"quarantine last session {last_session_date}")
        # SLIDE THE REGISTERED WINDOW TO THE LATEST TWELVE MONTHS
        before_dict = get_active_holdout_window_dict()
        reason_str = f"new data through {last_session_date}"
        after_dict = slide_holdout_window_dict(session_date_list, reason_str)
        slid_bool = str(after_dict["window_id"]) != str(before_dict["window_id"])
        if slid_bool:
            write_log_line(log_file, f"slid holdout {before_dict['window_id']} -> {after_dict['window_id']}")
            commit_slid_holdout_window_bool(paths.HOLDOUT_WINDOWS_FILE_PATH_STR, after_dict["start"], after_dict["end"], log_file)
        else:
            write_log_line(log_file, f"holdout unchanged {after_dict['window_id']}")
        window_dict = get_active_holdout_window_dict()
        start_date = pd.Timestamp(window_dict["start"]).date()
        # BUILD THE VIEW, THEN SCAN IT
        record_list = build_development_view_list(view_root_str, quarantine_root_str, start_date, session_date_list, log_file)
        manifest_path_str = write_manifest_file(view_root_str, start_date, record_list)
        finding_list = get_view_scan_finding_list(view_root_str, start_date, session_date_list)
        if finding_list:
            for finding_str in finding_list:
                write_log_line(log_file, f"FINDING {finding_str}")
            write_log_line(log_file, "VIEW.json absent (scan failed)")
            raise SystemExit(1)
        built_ts_str = datetime.now().isoformat(timespec="seconds")
        view_path_str = write_view_stamp_file(view_root_str, window_dict, built_ts_str, last_session_date, get_file_sha256_str(manifest_path_str))
        write_log_line(log_file, f"wrote {view_path_str}")
    return {"window_dict": window_dict, "last_session_date": last_session_date, "slid_bool": slid_bool,
            "finding_list": finding_list, "view_path_str": view_path_str, "log_path_str": log_path_str}

# IF RUN AS A SCRIPT
if __name__ == "__main__":
    # PARSE THE OPTIONAL PIPELINE FLAG
    parser = argparse.ArgumentParser(description="Rebuild the development view from the quarantine (Nicolas only).")
    parser.add_argument("--run-pipeline", action="store_true", help="Execute pipeline steps 00-06 on copies under the quarantine")
    arg_dict = parser.parse_args()
    try:
        run_refresh_development_view_dict(run_pipeline_bool_in=arg_dict.run_pipeline)
    except SystemExit:
        raise
    except Exception as error:
        print(error, file=sys.stderr)
        raise SystemExit(1)
