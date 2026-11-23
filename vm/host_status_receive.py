#!/usr/bin/python3 -IS
# so-host-status (vm/host_status_receive.py, 2026-11-23): receives the host's Windows Update facts on so-vm.
#
# Installed root-owned at /usr/local/lib/so/so-host-status. It is the forced command of the account so_host
# (vm/ssh/98-so-host.conf): nicodesktop's scheduled task "SO VM status" (stock_overflow_infra, vm_status/) runs
# "ssh so_host@<so-vm>" every 5 minutes and sends one JSON object on standard input. Whatever command the client asks
# for is ignored (sshd keeps it in SSH_ORIGINAL_COMMAND; this script never reads it). Design section 4 of
# claude/DESIGN_2026-11-18_linux_vm.md, decided 2026-11-23: the judge's update guard on Linux (scripts/run_queue.py)
# reads the file this writes and fails closed when it is missing, malformed or older than 15 minutes.
#
# It accepts exactly this object (at most 4096 bytes, ASCII), nothing more and nothing less:
#   {"schema": "so-host-status/1",
#    "host": "nicodesktop",
#    "written_utc": "2026-11-23T06:00:00Z",
#    "restart_pending": {"<each key of RESTART_KEY_LIST>": true | false},
#    "pause": {"<each value of PAUSE_VALUE_LIST>": "<the registry string>" | null},
#    "errors": ["<what the host could not read>", ...]}
# null means the value is not set (no pause). The registry strings are passed on unparsed; the judge parses them with
# the same function as on Windows. The two lists must equal UPDATE_RESTART_KEY_LIST and UPDATE_PAUSE_VALUE_LIST in
# scripts/run_queue.py (a test in the judge PR compares them).
#
# It adds "received_utc" (this VM's clock: the judge measures the age with it, so a wrong host clock cannot make old
# facts look new) and replaces <target>/host_status.json atomically (a new file, fsync, rename). Prints "ok
# <received_utc>" and exits 0, or "refused: <reason>" and exits 1 (refusals also go to the journal). It reads no other
# file and touches nothing else.
#
#   sudo runuser -u so_host -- /usr/local/lib/so/so-host-status --target-dir <folder> < sample.json   (tests only)
import json
import os
import re
import sys
import syslog
import datetime

TARGET_DIR_STR = "/srv/so/data/control/host_status"
FILE_NAME_STR = "host_status.json"
MAX_BYTES_INT = 4096
SCHEMA_STR = "so-host-status/1"
RESTART_KEY_LIST = [r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"]
PAUSE_VALUE_LIST = ["PauseUpdatesExpiryTime", "PauseFeatureUpdatesEndTime", "PauseQualityUpdatesEndTime"]
TOP_KEY_SET = {"schema", "host", "written_utc", "restart_pending", "pause", "errors"}
HOST_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,62}")
UTC_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
# The registry's pause strings ("2026-11-30T13:59:06Z"); a time zone is required, as on Windows
PAUSE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,7})?(Z|[+-]\d{2}:\d{2})")
MAX_ERROR_COUNT_INT = 10
MAX_ERROR_CHARS_INT = 200


def get_checked_dict(raw_bytes):
    """The validated object, or raises ValueError with the reason."""
    if len(raw_bytes) > MAX_BYTES_INT:
        raise ValueError(f"more than {MAX_BYTES_INT} bytes")
    try:
        text_str = raw_bytes.decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("not ASCII") from None
    try:
        obj = json.loads(text_str)
    except json.JSONDecodeError as error:
        raise ValueError(f"not JSON ({error.msg})") from None
    if not isinstance(obj, dict) or set(obj) != TOP_KEY_SET:
        raise ValueError(f"the keys must be exactly {sorted(TOP_KEY_SET)}")
    if obj["schema"] != SCHEMA_STR:
        raise ValueError(f"schema must be {SCHEMA_STR}")
    if not isinstance(obj["host"], str) or not HOST_PATTERN.fullmatch(obj["host"]):
        raise ValueError("bad host")
    if not isinstance(obj["written_utc"], str) or not UTC_PATTERN.fullmatch(obj["written_utc"]):
        raise ValueError("written_utc must be YYYY-MM-DDTHH:MM:SSZ")
    restart_dict = obj["restart_pending"]
    if not isinstance(restart_dict, dict) or set(restart_dict) != set(RESTART_KEY_LIST):
        raise ValueError("restart_pending must name exactly the two restart keys")
    if not all(isinstance(value, bool) for value in restart_dict.values()):
        raise ValueError("restart_pending values must be true or false")
    pause_dict = obj["pause"]
    if not isinstance(pause_dict, dict) or set(pause_dict) != set(PAUSE_VALUE_LIST):
        raise ValueError("pause must name exactly the three pause values")
    for name_str, value in pause_dict.items():
        if value is not None and not (isinstance(value, str) and PAUSE_PATTERN.fullmatch(value)):
            raise ValueError(f"pause {name_str} must be null or a time with a zone")
    error_list = obj["errors"]
    if not isinstance(error_list, list) or len(error_list) > MAX_ERROR_COUNT_INT:
        raise ValueError(f"errors must be a list of at most {MAX_ERROR_COUNT_INT}")
    for error_str in error_list:
        if not isinstance(error_str, str) or not error_str or len(error_str) > MAX_ERROR_CHARS_INT or not error_str.isprintable():
            raise ValueError(f"each error must be printable text of 1 to {MAX_ERROR_CHARS_INT} characters")
    return obj


def write_atomic(target_dir_str, content_bytes):
    """A new file in the folder (mode 0640, the folder's default ACL), fsync, rename over the old one, fsync the folder."""
    tmp_str = os.path.join(target_dir_str, f".{FILE_NAME_STR}.{os.getpid()}.tmp")
    fd_int = os.open(tmp_str, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o640)
    try:
        with os.fdopen(fd_int, "wb") as tmp_file:
            tmp_file.write(content_bytes)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_str, os.path.join(target_dir_str, FILE_NAME_STR))
    except BaseException:
        try:
            os.unlink(tmp_str)
        except OSError:
            pass
        raise
    dir_fd_int = os.open(target_dir_str, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(dir_fd_int)
    finally:
        os.close(dir_fd_int)


def refuse(reason_str):
    syslog.openlog("so-host-status", 0, syslog.LOG_AUTH)
    syslog.syslog(syslog.LOG_WARNING, f"refused: {reason_str}")
    print(f"refused: {reason_str}")
    return 1


def main(argv_list):
    target_dir_str = TARGET_DIR_STR
    if argv_list[:1] == ["--target-dir"] and len(argv_list) == 2:
        target_dir_str = argv_list[1]
    elif argv_list:
        return refuse("no arguments are taken (only --target-dir <folder>, for tests)")
    raw_bytes = sys.stdin.buffer.read(MAX_BYTES_INT + 1)
    if len(raw_bytes) > MAX_BYTES_INT:
        return refuse(f"more than {MAX_BYTES_INT} bytes")
    try:
        obj = get_checked_dict(raw_bytes.strip())
    except ValueError as error:
        return refuse(str(error))
    received_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out_dict = dict(obj)
    out_dict["received_utc"] = received_str
    content_bytes = (json.dumps(out_dict, sort_keys=True, indent=1) + "\n").encode("ascii")
    try:
        write_atomic(target_dir_str, content_bytes)
    except OSError as error:
        return refuse(f"cannot write {FILE_NAME_STR} ({type(error).__name__})")
    print(f"ok {received_str}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
