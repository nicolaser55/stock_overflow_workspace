"""
Workspace Tests: locked CSV append (so.core.csv_append, the trial log and the holdout ledger)

Run from the workspace root:   python tests/test_trial_log_append.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

Synthetic rows only, written under the temporary data root. The real trial log is not opened.
"""

import os
import sys
import csv
import re
import time
import types
import multiprocessing
import pandas as pd

# ADD THE WORKSPACE ROOT AND THE TESTS FOLDER TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
# IMPORT THE APPEND, THE TRIAL LOG AND THE TEMPORARY DATA ROOT
from so import paths
from so.core.csv_append import (append_csv_record_pdf, hold_csv_append_lock, CsvAppendLockTimeoutError,
                               CSV_APPEND_LOCK_TIMEOUT_SECONDS)
from so.core.trial_log import TRIAL_LOG_COLUMN_LIST, log_trial_dict, log_trial_pdf

# PROCESSES ARE SPAWNED SO THE LOCK IS NOT INHERITED (WINDOWS AND LINUX)
MP_CONTEXT = multiprocessing.get_context("spawn")

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

# FUNCTION: A SYNTHETIC EXPERIMENT CONFIG FOR THE TRIAL ID
def get_config_module():
    """
    A module with the two constants log_trial_pdf reads. It is not an experiment.

    Returns:
        module: EXPERIMENT_NAME and PROTOCOL_VERSION
    """
    # THE HASH ONLY NEEDS THE UPPERCASE CONSTANTS
    config_module = types.ModuleType("csv_append_test_config")
    config_module.EXPERIMENT_NAME = "csv_append_test"
    config_module.PROTOCOL_VERSION = "0"
    return config_module

# FUNCTION: ONE CSV PATH INSIDE THE TEMPORARY DATA ROOT
def get_log_path_str(file_name_str_in):
    """
    A path under store04_experiments of the temporary data root.

    Args:
        file_name_str_in (str): File name

    Returns:
        str: CSV path
    """
    # THE FOLDER IS CREATED HERE; THE APPEND CREATES IT AGAIN IF NEEDED
    folder_str = f"{paths.LOCAL_EXPERIMENTZONE_PATH_STR}csv_append_test"
    os.makedirs(folder_str, exist_ok=True)
    return f"{folder_str}/{file_name_str_in}"

# FUNCTION: HOLD THE APPEND LOCK UNTIL THE PARENT SAYS TO RELEASE IT
def hold_lock_worker(file_path_str_in, ready_queue_in, release_queue_in):
    """
    Takes the same exclusive lock the append uses, signals, then waits.

    Args:
        file_path_str_in (str): CSV path
        ready_queue_in (multiprocessing.Queue): Receives True once the lock is held
        release_queue_in (multiprocessing.Queue): Blocks until the parent sends anything

    Returns:
        None
    """
    # THE LOCK IS "<file>.lock", THE SAME FILE THE SECOND WRITER WAITS ON
    with hold_csv_append_lock(file_path_str_in, timeout_seconds_in=30):
        ready_queue_in.put(True)
        release_queue_in.get()

# FUNCTION: APPEND 100 SYNTHETIC TRIAL ROWS
def write_batch_worker(file_path_str_in, row_count_int_in):
    """
    One process of the concurrent append. The path is inside the temporary data root.

    Args:
        file_path_str_in (str): Trial log CSV
        row_count_int_in (int): Rows to append

    Returns:
        None
    """
    # SYNTHETIC SETTINGS; THE PROCESS ID IS WHAT MAKES THE IDS UNIQUE ACROSS PROCESSES
    config_module = get_config_module()
    setting_pdf = pd.DataFrame([{"stop_k": row_idx, "valid_total_return": 0.0} for row_idx in range(row_count_int_in)])
    log_trial_pdf(config_module, "validation", setting_pdf, ["stop_k"], ["valid_total_return"], False, file_path_str_in=file_path_str_in)

# FUNCTION: FOUR PROCESSES APPEND 100 ROWS EACH
def test_concurrent_appends():
    # FOUR WRITERS, ONE LOG, UNDER THE TEMPORARY DATA ROOT
    file_path_str = get_log_path_str("concurrent_trial_log.csv")
    process_list = [MP_CONTEXT.Process(target=write_batch_worker, args=(file_path_str, 100)) for _ in range(4)]
    for process in process_list:
        process.start()
    for process in process_list:
        process.join(120)
        assert process.exitcode == 0, process.exitcode
    # THE FILE PARSES, AND EVERY TRIAL ID IS PRESENT AND UNIQUE
    trial_pdf = pd.read_csv(file_path_str)
    assert len(trial_pdf) == 400 and trial_pdf["trial_id"].nunique() == 400
    assert trial_pdf.columns.tolist() == TRIAL_LOG_COLUMN_LIST
    with open(file_path_str, newline="") as csv_file:
        row_list = list(csv.reader(csv_file))
    assert row_list[0] == TRIAL_LOG_COLUMN_LIST and len(row_list) == 401
    assert all(len(row) == len(TRIAL_LOG_COLUMN_LIST) for row in row_list)
    # THE BATCH ID IS TIMESTAMP, ROW INDEX, PROCESS ID, CONFIG HASH
    id_pattern = re.compile(r"^\d{25}_\d+_[0-9a-f]{10}$")
    assert all(id_pattern.match(trial_id_str) for trial_id_str in trial_pdf["trial_id"].astype(str))
    passed("4 processes x 100 rows (400 rows, 400 unique trial ids, the file parses)")

# FUNCTION: AN APPEND DOES NOT REWRITE THE BYTES ALREADY IN THE FILE
def test_append_keeps_the_byte_prefix():
    # ONE ROW, THEN ANOTHER, ON A SYNTHETIC LOG
    file_path_str = get_log_path_str("prefix_trial_log.csv")
    config_module = get_config_module()
    log_trial_dict(config_module, "note", {"item": 1}, {"value": 0.1}, False, file_path_str_in=file_path_str)
    before_bytes = open(file_path_str, "rb").read()
    log_trial_dict(config_module, "note", {"item": 2}, {"value": 0.2}, False, file_path_str_in=file_path_str)
    after_bytes = open(file_path_str, "rb").read()
    # THE EARLIER BYTES ARE AN EXACT PREFIX
    assert after_bytes[:len(before_bytes)] == before_bytes and len(after_bytes) > len(before_bytes)
    # A SINGLE-ROW ID CARRIES THE PROCESS ID BETWEEN THE TIMESTAMP AND THE HASH
    id_pattern = re.compile(r"^\d{20}_\d+_[0-9a-f]{10}$")
    assert all(id_pattern.match(trial_id_str) for trial_id_str in pd.read_csv(file_path_str)["trial_id"].astype(str))
    passed("the bytes before an append are an exact prefix of the bytes after it")

# FUNCTION: A WRONG HEADER IS REFUSED AND THE FILE IS LEFT AS IT WAS
def test_header_mismatch_is_refused():
    # A COMPLETE FILE WHOSE HEADER IS NOT THE EXPECTED COLUMN LIST
    file_path_str = get_log_path_str("header_mismatch.csv")
    original_bytes = b"other,columns\n1,2\n"
    with open(file_path_str, "wb") as csv_file:
        csv_file.write(original_bytes)
    row_pdf = pd.DataFrame([{"alpha": "one", "beta": "two"}])
    # THE APPEND RAISES AND DOES NOT REPAIR THE HEADER
    try:
        append_csv_record_pdf(row_pdf, file_path_str, ["alpha", "beta"])
        refused_bool = False
    except ValueError as error:
        refused_bool = True
        assert "header" in str(error).lower() and "not changed" in str(error).lower()
    assert refused_bool and open(file_path_str, "rb").read() == original_bytes
    passed("a header mismatch is refused and the file is unchanged")

# FUNCTION: A FILE WITH NO FINAL NEWLINE IS REFUSED AND LEFT AS IT WAS
def test_missing_newline_is_refused():
    # THE HEADER MATCHES; THE FILE STILL HAS NO FINAL NEWLINE, SO IT MUST NOT BE REPAIRED
    column_str_list = ["alpha", "beta"]
    file_path_str = get_log_path_str("missing_newline.csv")
    original_bytes = (",".join(column_str_list) + "\none,two").encode("utf-8")
    assert not original_bytes.endswith(b"\n")
    with open(file_path_str, "wb") as csv_file:
        csv_file.write(original_bytes)
    row_pdf = pd.DataFrame([{"alpha": "one", "beta": "two"}])
    # THE APPEND RAISES AND DOES NOT ADD THE MISSING NEWLINE
    try:
        append_csv_record_pdf(row_pdf, file_path_str, column_str_list)
        refused_bool = False
    except ValueError as error:
        refused_bool = True
        assert "newline" in str(error).lower() and "not repaired" in str(error).lower()
    assert refused_bool and open(file_path_str, "rb").read() == original_bytes
    passed("a file without a final newline is refused and the file is unchanged")

# FUNCTION: A HELD LOCK MAKES THE NEXT WRITER WAIT, THEN TIME OUT
def test_held_lock_times_out():
    # THE PRODUCTION WAIT IS 60 SECONDS; THIS CHECK USES A SHORTER WAIT ON THE SAME LOCK
    assert CSV_APPEND_LOCK_TIMEOUT_SECONDS == 60
    file_path_str = get_log_path_str("held_lock.csv")
    row_pdf = pd.DataFrame([{"alpha": "one", "beta": "two"}])
    append_csv_record_pdf(row_pdf, file_path_str, ["alpha", "beta"])
    before_bytes = open(file_path_str, "rb").read()
    # A SECOND PROCESS HOLDS "<file>.lock" FOR THE WHOLE WAIT
    ready_queue = MP_CONTEXT.Queue()
    release_queue = MP_CONTEXT.Queue()
    process = MP_CONTEXT.Process(target=hold_lock_worker, args=(file_path_str, ready_queue, release_queue))
    process.start()
    timeout_float = 1.0
    try:
        assert ready_queue.get(timeout=30) is True
        start_float = time.monotonic()
        try:
            append_csv_record_pdf(row_pdf, file_path_str, ["alpha", "beta"], timeout_seconds_in=timeout_float)
            refused_bool = False
            error_str = ""
        except CsvAppendLockTimeoutError as error:
            refused_bool = True
            error_str = str(error)
        elapsed_float = time.monotonic() - start_float
    finally:
        # RELEASE THE HOLDER EVEN IF THE ASSERTION ABOVE FAILS
        release_queue.put(True)
        process.join(30)
    # THE WAITER WAITED, THEN RAISED, AND THE CSV WAS NOT WRITTEN
    assert process.exitcode == 0
    assert refused_bool and "exclusive lock" in error_str and f"{file_path_str}.lock" in error_str
    assert elapsed_float >= timeout_float * 0.8
    assert open(file_path_str, "rb").read() == before_bytes
    passed("a held lock makes a second writer wait, then time out with the clear error")

# RUN THE SUITE
if __name__ == "__main__":
    # CONCURRENT APPEND, THEN THE BYTE PREFIX, THE TWO REFUSALS AND THE LOCK TIMEOUT
    test_concurrent_appends()
    test_append_keeps_the_byte_prefix()
    test_header_mismatch_is_refused()
    test_missing_newline_is_refused()
    test_held_lock_times_out()
    print("\nAll trial-log append tests passed ✅")
