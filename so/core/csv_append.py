import io
import os
import time
from contextlib import contextmanager
import pandas as pd

"""
Locked CSV Append

write_csv_file_to_path in append mode reads the whole file, concatenates the new rows and rewrites the file. Two
processes doing that keep one copy and can crash when the read sees an empty file. This module appends only the new
rows. It never reads the rows already stored and never rewrites them.

An exclusive lock on "<file>.lock" is held for the check and the write (msvcrt on Windows, fcntl elsewhere). The lock
is waited for up to 60 seconds. After that the append raises CsvAppendLockTimeoutError and writes nothing.

While the lock is held:
    - a missing or empty file is started with the header (the column names joined by commas, then a newline);
    - any other file must already have that header exactly, and must already end with a newline;
    - a file that fails either check is left as it is (it is not repaired);
    - the new rows are written in the given column order, in append mode, then flushed and fsynced.
A missing or empty file is started with LF. An existing file's new rows use the line ending of its header line,
CRLF or LF, so the file stays on one ending. The header text compared to the column list does not include that ending.
"""

# THE EXCLUSIVE LOCK IS WAITED FOR THIS LONG, THEN THE APPEND FAILS
CSV_APPEND_LOCK_TIMEOUT_SECONDS = 60
# HOW OFTEN A WAITER RETRIES A BUSY LOCK
CSV_APPEND_LOCK_POLL_SECONDS = 0.05

# THE APPEND LOCK WAS NOT ACQUIRED WITHIN THE WAIT
class CsvAppendLockTimeoutError(TimeoutError):
    """Raised when "<file>.lock" is still held after the wait. The CSV file is not written."""

"""
Lock
"""

# FUNCTION: TAKE THE EXCLUSIVE LOCK, OR RAISE IF ANOTHER PROCESS HOLDS IT
def acquire_exclusive_lock(fd_int_in):
    """
    Locks one byte of a lock file without waiting. A busy lock raises; any other error is raised as itself.

    Args:
        fd_int_in (int): Open file descriptor of the lock file

    Returns:
        None
    """
    # WINDOWS LOCKS A BYTE RANGE; THE FILE MAY BE EMPTY
    if os.name == "nt":
        import msvcrt
        os.lseek(fd_int_in, 0, os.SEEK_SET)
        msvcrt.locking(fd_int_in, msvcrt.LK_NBLCK, 1)
        return
    # OTHER PLATFORMS LOCK THE WHOLE FILE (NON-BLOCKING)
    import fcntl
    fcntl.flock(fd_int_in, fcntl.LOCK_EX | fcntl.LOCK_NB)

# FUNCTION: RELEASE THE EXCLUSIVE LOCK
def release_exclusive_lock(fd_int_in):
    """
    Releases the lock taken by acquire_exclusive_lock.

    Args:
        fd_int_in (int): Open file descriptor of the lock file

    Returns:
        None
    """
    # UNLOCK THE SAME BYTE THAT WAS LOCKED
    if os.name == "nt":
        import msvcrt
        os.lseek(fd_int_in, 0, os.SEEK_SET)
        msvcrt.locking(fd_int_in, msvcrt.LK_UNLCK, 1)
        return
    # UNLOCK THE WHOLE FILE
    import fcntl
    fcntl.flock(fd_int_in, fcntl.LOCK_UN)

# FUNCTION: WHETHER A LOCK ERROR MEANS THE LOCK IS BUSY
def get_lock_contention_bool(error_in):
    """
    True when the error is a busy lock. Other errors (a bad descriptor, a disk failure) are not retried.

    Args:
        error_in (OSError): The error from acquire_exclusive_lock

    Returns:
        bool: The lock is held by someone else
    """
    # WINDOWS REPORTS A BUSY LOCK AS PERMISSION DENIED
    if os.name == "nt":
        return isinstance(error_in, PermissionError)
    # POSIX REPORTS A BUSY NON-BLOCKING LOCK AS BlockingIOError
    return isinstance(error_in, BlockingIOError)

# FUNCTION: HOLD THE EXCLUSIVE LOCK OF A CSV APPEND
@contextmanager
def hold_csv_append_lock(file_path_str_in, timeout_seconds_in=CSV_APPEND_LOCK_TIMEOUT_SECONDS):
    """
    Holds an exclusive lock on "<file>.lock" until the block ends. Waits up to timeout_seconds_in, then raises
    CsvAppendLockTimeoutError. The lock file is left in place so a waiter is not handed a new, unlocked file.

    Args:
        file_path_str_in (str): CSV path (the lock is this path plus ".lock")
        timeout_seconds_in (float): Seconds to wait for the lock

    Returns:
        None
    """
    # THE LOCK SITS BESIDE THE CSV, AND THE FOLDER MUST EXIST BEFORE THE LOCK FILE CAN
    lock_path_str = f"{file_path_str_in}.lock"
    directory_str = os.path.dirname(lock_path_str)
    if directory_str not in ["", None]:
        os.makedirs(directory_str, exist_ok=True)
    # WAIT UNTIL THIS MOMENT, THEN FAIL WITH A CLEAR ERROR
    deadline_float = time.monotonic() + float(timeout_seconds_in)
    fd_int = os.open(lock_path_str, os.O_RDWR | os.O_CREAT, 0o666)
    acquired_bool = False
    try:
        # RETRY A BUSY LOCK; ANY OTHER ERROR PROPAGATES AND WRITES NOTHING
        while True:
            try:
                acquire_exclusive_lock(fd_int)
                acquired_bool = True
                break
            except OSError as error:
                if not get_lock_contention_bool(error):
                    raise
                remaining_float = deadline_float - time.monotonic()
                if remaining_float <= 0:
                    raise CsvAppendLockTimeoutError(
                        f"Timed out after {timeout_seconds_in} seconds waiting for the exclusive lock '{lock_path_str}'.") from None
                time.sleep(min(CSV_APPEND_LOCK_POLL_SECONDS, remaining_float))
        # THE CALLER WRITES THE CSV WHILE THIS LOCK IS HELD
        yield
    finally:
        # RELEASE THE LOCK ONLY IF THIS PROCESS TOOK IT, THEN CLOSE THE DESCRIPTOR
        if acquired_bool:
            release_exclusive_lock(fd_int)
        os.close(fd_int)

"""
Append
"""

# FUNCTION: REJECT A COLUMN NAME THAT CANNOT BE A BARE CSV HEADER
def check_csv_column_list(column_str_list_in):
    """
    The header is the column names joined by commas, with no quoting. A comma, quote or line break in a name would
    make that header ambiguous, so it is refused before any file is touched.

    Args:
        column_str_list_in (list[str]): Expected columns, in write order

    Returns:
        None
    """
    # AN APPEND NEEDS A COLUMN LIST
    if len(column_str_list_in) == 0:
        raise ValueError("CSV append needs a column list. The file was not changed.")
    # EACH NAME MUST BE SAFE TO JOIN WITH COMMAS
    for column_str in column_str_list_in:
        if any(character_str in column_str for character_str in [",", "\"", "\n", "\r"]):
            raise ValueError(f"CSV column '{column_str}' contains a comma, quote or line break. The file was not changed.")

# FUNCTION: SERIALIZE THE NEW ROWS ONLY
def get_csv_row_bytes(pdf_in, column_str_list_in, line_ending_bytes_in):
    """
    The new rows in the given column order, with no header. Each row ends with line_ending_bytes_in (CRLF or LF).

    Args:
        pdf_in (pd.DataFrame): Rows to append
        column_str_list_in (list[str]): Columns, in write order
        line_ending_bytes_in (bytes): b"\\r\\n" or b"\\n"

    Returns:
        bytes: The CSV rows
    """
    # PANDAS QUOTES FIELDS THAT CONTAIN COMMAS; THE RECORD SEPARATOR IS THE FILE'S OWN ENDING
    buffer = io.StringIO(newline="")
    pdf_in.to_csv(buffer, columns=list(column_str_list_in), index=False, header=False, lineterminator=line_ending_bytes_in.decode("ascii"))
    return buffer.getvalue().encode("utf-8")

# FUNCTION: THE HEADER TEXT OF THE FIRST LINE, WITHOUT ITS LINE ENDING
def get_csv_header_str(first_line_bytes_in):
    """
    Drops one trailing line feed and one trailing carriage return. The rest of the line is compared exactly.

    Args:
        first_line_bytes_in (bytes): The first line, including its line ending

    Returns:
        str: Header text
    """
    # DROP THE LINE ENDING ONLY (CRLF OR LF); DO NOT TRIM ANY OTHER CHARACTER
    header_bytes = first_line_bytes_in
    if header_bytes.endswith(b"\n"):
        header_bytes = header_bytes[:-1]
    if header_bytes.endswith(b"\r"):
        header_bytes = header_bytes[:-1]
    return header_bytes.decode("utf-8")

# FUNCTION: REFUSE A FILE WHOSE HEADER OR FINAL NEWLINE IS WRONG
def check_csv_append_target(file_path_str_in, column_str_list_in):
    """
    Reads the last byte and the header line of an existing non-empty file. Does not read the data rows. A missing
    newline or a header that is not the expected column list raises, and the caller must not write. The line ending
    of the new rows is the ending of that header line.

    Args:
        file_path_str_in (str): CSV path
        column_str_list_in (list[str]): Expected columns, in order

    Returns:
        tuple[bool, bytes]: Write the header, and the line ending for the new rows (LF when the file is new)
    """
    # A MISSING OR EMPTY FILE IS STARTED WITH AN LF HEADER
    if (not os.path.isfile(file_path_str_in)) or os.path.getsize(file_path_str_in) == 0:
        return True, b"\n"
    # THE LAST BYTE FIRST, SO A FILE WITH NO NEWLINE IS NOT READ THROUGH
    with open(file_path_str_in, "rb") as csv_file:
        csv_file.seek(-1, os.SEEK_END)
        last_byte = csv_file.read(1)
        if last_byte != b"\n":
            raise ValueError(f"CSV file '{file_path_str_in}' does not end with a newline. The file was not changed and was not repaired.")
        # THE HEADER IS THE FIRST LINE ONLY; ITS ENDING IS THE ENDING OF THE NEW ROWS
        csv_file.seek(0)
        first_line_bytes = csv_file.readline()
    # CRLF WHEN THE HEADER LINE ENDS WITH CR LF; OTHERWISE LF
    line_ending_bytes = b"\r\n" if first_line_bytes.endswith(b"\r\n") else b"\n"
    # THE HEADER MUST BE THE COLUMN NAMES JOINED BY COMMAS
    expected_header_str = ",".join(column_str_list_in)
    header_str = get_csv_header_str(first_line_bytes)
    if header_str != expected_header_str:
        raise ValueError(f"CSV header of '{file_path_str_in}' does not match the expected columns. "
                         f"Expected '{expected_header_str}'. Found '{header_str}'. The file was not changed.")
    return False, line_ending_bytes

# FUNCTION: WRITE THE NEW BYTES, THEN FLUSH AND FSYNC
def write_csv_payload_bytes(file_path_str_in, payload_bytes_in):
    """
    Appends payload bytes. Does not read the file and does not rewrite bytes already there.

    Args:
        file_path_str_in (str): CSV path
        payload_bytes_in (bytes): Header and rows, or rows only

    Returns:
        None
    """
    # UNBUFFERED APPEND: A SHORT WRITE IS RETRIED, THEN THE BYTES ARE FORCED TO DISK
    with open(file_path_str_in, "ab", buffering=0) as csv_file:
        view = memoryview(payload_bytes_in)
        while len(view) > 0:
            written_int = csv_file.write(view)
            # A ZERO-LENGTH WRITE WOULD SPIN; IT IS A FAILURE, NOT A SHORT WRITE
            if written_int == 0:
                raise OSError(f"Could not write CSV rows to '{file_path_str_in}'.")
            view = view[written_int:]
        csv_file.flush()
        os.fsync(csv_file.fileno())

# FUNCTION: APPEND CSV ROWS UNDER THE EXCLUSIVE LOCK
def append_csv_record_pdf(pdf_in, file_path_str_in, column_str_list_in, timeout_seconds_in=CSV_APPEND_LOCK_TIMEOUT_SECONDS):
    """
    Appends the rows of a DataFrame in column_str_list_in order. An empty frame writes nothing and does not create
    the file. The lock, the header check and the newline check are hold_csv_append_lock and check_csv_append_target.

    Args:
        pdf_in (pd.DataFrame): Rows to append (extra columns are not written)
        file_path_str_in (str): CSV path
        column_str_list_in (list[str]): Expected columns, in write order
        timeout_seconds_in (float): Seconds to wait for "<file>.lock"

    Returns:
        None
    """
    # THE INPUT IS A TABLE, AND THE HEADER NAMES ARE SAFE TO JOIN
    if not isinstance(pdf_in, pd.DataFrame):
        raise ValueError("CSV append expects a DataFrame. The file was not changed.")
    check_csv_column_list(column_str_list_in)
    # A MISSING COLUMN WOULD BE WRITTEN BLANK; REFUSE IT INSTEAD
    missing_str_list = [column_str for column_str in column_str_list_in if column_str not in pdf_in.columns]
    if len(missing_str_list) > 0:
        raise ValueError(f"CSV append is missing columns {missing_str_list}. The file was not changed.")
    # NOTHING TO APPEND
    if len(pdf_in) == 0:
        return None
    # A NEW FILE'S HEADER USES LF; AN EXISTING FILE KEEPS THE ENDING OF ITS HEADER LINE
    header_bytes = (",".join(column_str_list_in) + "\n").encode("utf-8")
    # CHECK AND WRITE WHILE NO OTHER APPENDER HOLDS THE LOCK
    with hold_csv_append_lock(file_path_str_in, timeout_seconds_in=timeout_seconds_in):
        write_header_bool, line_ending_bytes = check_csv_append_target(file_path_str_in, column_str_list_in)
        row_bytes = get_csv_row_bytes(pdf_in, column_str_list_in, line_ending_bytes)
        payload_bytes = header_bytes + row_bytes if write_header_bool else row_bytes
        write_csv_payload_bytes(file_path_str_in, payload_bytes)
    return None
