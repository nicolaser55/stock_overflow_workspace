import argparse
import datetime
import json
import os
import re
import shutil
import smtplib
import socket
import subprocess
import sys
import threading
import time
import uuid
from email.message import EmailMessage
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# IMPORT THE DATA PATHS AND THE LOCKED CSV APPEND
from so.paths import get_named_data_path_str
from so.core.csv_append import append_csv_record_pdf

"""
Run Queue (development runs, one at a time; the judge from main, the design from the job's commit)

Agents (so_agent) add jobs; only the runner account (so_runner) runs them and writes results (audit S3 / S4,
2026-10-25; trust boundaries, design 2026-10-27). A job names a commit, and the runner builds the code of the run from
two sources: everything except experiments/ comes from the commit Nicolas last deployed (the judge: so/, scripts/,
tests/, the rules; the ref refs/deployed that scripts/deploy_runner.ps1 sets in the runner's clone), and experiments/
comes from the job's commit (the design). A merge to main changes no run until it is deployed (design 4.2, roadmap R2). A job commit that changes anything else is
refused. The run executes that combination in a temporary git worktree, so a result always belongs to known judge code
and known design code, whatever is checked out anywhere.

    python scripts/run_queue.py add experiments/exp13_e1m1_robustness --note "why this run"   # the current commit
    python scripts/run_queue.py add experiments/exp13_e1m1_robustness --commit <sha> --note "..."
    python scripts/run_queue.py retry <job_id>      # queue a failed job again; it resumes the same run id
    python scripts/run_queue.py run                 # runner: run every pending job, then exit
    python scripts/run_queue.py watch               # runner: run jobs as they arrive, forever (the scheduled task)
    python scripts/run_queue.py status              # print state.json
    python scripts/run_queue.py test-email          # runner: send one test email with the runner's SMTP settings

add refuses a clone with uncommitted changes in the design folder, and records the commit; the commit must be pushed
(the runner fetches origin before each job). Files, all under <SO_DATA_PATH>/store04_experiments/:

    queue/pending/<job_id>.json   jobs waiting (the only folder so_agent may write)
    queue/running/<job_id>.json   the job being run, with its run id and judge commit; after a crash or reboot the
                                  runner finds it, resumes the same run id, and gives up after MAX_RESUME_COUNT_INT
    queue/rejected/<job_id>.json  a pending file that failed validation, with the reason (never run, never emailed)
    queue/done/<job_id>.json      finished jobs with their result
    queue/failed/<job_id>.json    jobs whose run failed or timed out, with the last lines of the log
    queue/logs/<run_id>_attempt<n>.log   each attempt's output
    queue/outbox/<run_id>.txt     an email that could not be sent
    queue/runner.lock             the running runner's process id and host; a stale lock (dead process) is replaced
    run_index.csv                 one row per job attempt (append-only; scripts/append_results_log.py turns finished
                                  rows into docs/RESULTS_LOG.md rows)
    visible/state.json            the running job (identifiers only), pending count, heartbeat, the commit of the queue
                                  script (queue_commit), the deployed judge, the kill switch, and the last 20 results
                                  as job id, run id and status only (roadmap R4; the state.json of earlier versions at
                                  the zone root held full results and is removed on the first write)
    visible/grades/<run_id>.json  the grade of a run (so.runner.grade): identifiers, grade, reason, audit; no numbers.
                                  Readable by the planner (group so_grade_readers)
    visible/status/<job_id>.json  the technical status of a job: ran / crashed / timeout / rejected, the look-ahead
                                  status of a run that ran, the error with every number scrubbed, and the fields a retry
                                  needs; no performance numbers. Readable by the coder (group so_status_readers)

Agents read only visible/ (and write queue/pending); everything else here is readable by so_runner and Nicolas only
(roadmap R4, scripts/setup_so_agent.ps1).

A pending file is untrusted input. It must hold exactly the fields of a job (JOB_FIELD_LIST) with safe values
(identifier patterns, a 40-character commit that exists and holds the design, a bounded note); a run id, a judge
commit or a retry marker is accepted only when it matches the runner's own record of the failed job it retries.

A job runs scripts/run_development.py from a worktree at <SO_QUEUE_WORKTREE_ROOT or <workspace>/.worktrees>/<run_id>,
with the Python in SO_QUEUE_PYTHON (default: this interpreter), under a time limit (SO_QUEUE_JOB_TIMEOUT_HOURS,
default 24); a timeout kills the whole process tree. The worktree is a commit made from the judge commit and the
job's experiments/ tree (fixed author and date, so the same pair always gives the same commit); a ref
refs/runs/<run_id> keeps it, and both parents, in the runner's clone. The judge commit is refs/deployed at the time
the job starts (SO_QUEUE_JUDGE_REF overrides the ref) and is pinned for the run, its retries and its crash resumes.
Without a deployed commit no new job starts (the jobs wait in pending/; state.json shows "deployed_commit": "").
Each pass fetches origin once before it validates pending files, so a job can name any pushed commit.
The judge hash (so.runner.judge_identity) is taken from the fresh worktree of the run commit before the child process
starts and again after it ends; a run whose report.json shows another judge hash, or whose worktree's judge changed, is
filed as failed ("judge changed during the run"): design code ran in between (roadmap R3, audit S9). The
child process gets the runner's environment without secrets (get_child_environment_dict). While a job runs, a thread
refreshes the heartbeat in state.json every SO_QUEUE_HEARTBEAT_SECONDS (default 60). An email-worthy verdict and a
failed job send an email (SMTP from SO_SMTP_HOST, SO_SMTP_PORT, SO_SMTP_USER, SO_SMTP_PASSWORD, SO_EMAIL_TO; without
them the message goes to the outbox). The queue never runs a holdout evaluation.

Email (design 2026-10-27, section 9): one email per finished full run, positive or negative (subject: the design and the
verdict label; a run that passes every part has the subject "PASS, audit pending" until an auditor exists), and one per
failed, timed-out or abandoned job. The body holds the run id, verdict, failed parts, look-ahead status, the strategy's
and buy-and-hold total returns, the number of designs tried, the judge hash and the three commits, and the paths of
the report and the log. A rejected job sends nothing.

Kill switch (section 10): a file named STOP in <SO_DATA_PATH>/control (SO_STOP_FLAG_PATH overrides the path). While it
exists the runner starts no job, resumes no interrupted job, and the job that is running finishes; state.json shows
"stopped": true. Nicolas creates and deletes the file (every other account can only read it). A flag that cannot be
read (access denied) counts as set; a flag that does not exist, including a missing control folder, does not.
scripts/reset_records.py reads the same path the other way (2026-11-10): it resets only when the flag is confirmed to
exist.

Windows Update guard (decided by Nicolas on 2026-11-11, after two update restarts during the baseline rerun): Windows 11
Home gives no reliable way to stop update restarts except a pause (Settings > Windows Update > Pause updates, at most 35
days ahead, renewable). add refuses a job, and the runner starts or resumes no job, while the guard is not safe: the
pause ends within UPDATE_PAUSE_MIN_DAYS (3) days (the earliest of the pause end values under
HKLM/SOFTWARE/Microsoft/WindowsUpdate/UX/Settings), no pause is set, a restart is pending (the RebootRequired or
RebootPending key exists), or any of these cannot be read. The job that is running finishes. state.json shows
"update_guard" (safe and the reason); the watch prints the reason and emails once per reason. The guard reads the
registry only on Windows; elsewhere (CI, tests on Linux) it reports "not applicable" and is safe. Tests replace
UPDATE_GUARD_FUNC.
"""

# THE NUMBER OF RECENT RESULTS IN state.json AND OF LOG LINES KEPT FOR A FAILED JOB
STATE_RECENT_COUNT_INT = 20
FAILED_TAIL_LINE_COUNT_INT = 20
# THE WORKSPACE OF THIS SCRIPT (THE RUNNER'S CLONE WHEN THE RUNNER RUNS IT)
WORKSPACE_PATH = Path(__file__).resolve().parents[1]
# THE RUN INDEX COLUMNS
RUN_INDEX_COLUMN_LIST = ["run_id", "attempt", "job_id", "design", "commit", "judge_commit", "run_commit", "note", "status",
                         "return_code",
                         "verdict_label", "email_worthy", "failed_list", "strategy_total_return",
                         "buy_hold_total_return", "look_ahead", "design_count", "judge_hash", "added_by", "added_ts",
                         "finished_ts"]
# THE CODE add REQUIRES TO BE COMMITTED (ONLY THE DESIGN FOLDER: THE JUDGE CODE OF A RUN IS THE DEPLOYED COMMIT)
GUARDED_ADD_FOLDER_LIST = []
# DEFAULT TIME LIMIT OF ONE JOB (exp01 TAKES 11-14 HOURS)
DEFAULT_JOB_TIMEOUT_HOURS = 24.0
# SECONDS BETWEEN TWO LOOKS AT THE PENDING FOLDER IN watch MODE
DEFAULT_WATCH_INTERVAL_SECONDS = 60
# SECONDS BETWEEN TWO HEARTBEATS WHILE A JOB RUNS
DEFAULT_HEARTBEAT_SECONDS = 60.0
# HOW OFTEN A JOB INTERRUPTED BY A CRASH OR REBOOT IS RESUMED BEFORE IT IS FILED AS FAILED
MAX_RESUME_COUNT_INT = 2
# A PENDING FILE THAT STAYS UNREADABLE THIS LONG IS NOT BEING WRITTEN ANY MORE; PENDING FILES ARE SMALL
STALE_PENDING_SECONDS = 600
MAX_PENDING_FILE_BYTES = 65536
# THE FIELDS OF A JOB FILE AND THE PATTERNS OF THEIR VALUES (A PENDING FILE IS WRITTEN BY AN AGENT ACCOUNT)
JOB_FIELD_LIST = ["job_id", "design", "note", "commit", "n_jobs", "added_ts", "added_by", "attempt", "run_id", "retry_of",
                  "judge_commit"]
JOB_ID_PATTERN = re.compile(r"^[0-9]{20}_[0-9a-f]{6}_[A-Za-z0-9_]{1,100}$")
DESIGN_PATTERN = re.compile(r"^experiments/[A-Za-z0-9_]{1,80}$")
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,160}$")
COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
ADDED_TS_PATTERN = re.compile(r"^[0-9T:.\- ]{0,40}$")
ADDED_BY_PATTERN = re.compile(r"^[A-Za-z0-9_.\\ -]{0,64}$")
NOTE_MAX_LENGTH_INT = 500
MAX_N_JOBS_INT = 64
# ENVIRONMENT NAMES THE CHILD PROCESS MUST NOT SEE (PREFIXES, THEN FRAGMENTS; COMPARED IN UPPER CASE)
SECRET_PREFIX_LIST = ["SO_SMTP_", "SO_EMAIL", "SO_HOLDOUT", "GH_", "GITHUB_", "ANTHROPIC_", "OPENAI_", "AWS_", "AZURE_",
                      "SSH_", "GIT_ASKPASS"]
SECRET_FRAGMENT_LIST = ["PASSWORD", "PASSWD", "SECRET", "TOKEN", "API_KEY", "APIKEY", "CREDENTIAL"]
# THE COMMIT THE RUN IS MADE FROM HAS A FIXED IDENTITY AND DATE SO THE SAME PAIR OF COMMITS GIVES THE SAME HASH
COMPOSITE_ENVIRONMENT_DICT = {"GIT_AUTHOR_NAME": "so_queue", "GIT_AUTHOR_EMAIL": "so_queue@localhost",
                              "GIT_COMMITTER_NAME": "so_queue", "GIT_COMMITTER_EMAIL": "so_queue@localhost",
                              "GIT_AUTHOR_DATE": "2000-01-01T00:00:00 +0000", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00 +0000"}
# state.json IS WRITTEN BY THE MAIN THREAD AND THE HEARTBEAT THREAD
STATE_LOCK = threading.Lock()
# HOW OFTEN AND HOW LONG A REPLACE BLOCKED BY A READER (WINDOWS) IS RETRIED
REPLACE_RETRY_COUNT_INT = 50
REPLACE_RETRY_SECONDS = 0.1
QUEUE_COMMIT_CACHE_STR = None
# THE FOLDER AGENTS MAY READ (ROADMAP R4): STATE, GRADES, TECHNICAL STATUS
VISIBLE_FOLDER_STR = "visible"
# THE FIELDS OF A RECENT ENTRY AND OF THE RUNNING JOB IN state.json (IDENTIFIERS ONLY)
STATE_RECENT_KEY_LIST = ["job_id", "run_id", "status"]
STATE_RUNNING_KEY_LIST = ["job_id", "design", "commit", "run_id", "attempt", "added_ts", "started_ts"]
# THE TECHNICAL STATUS NAMES THE CODER SEES (QUEUE STATUS -> STATUS)
TECHNICAL_STATUS_DICT = {"done": "ran", "failed": "crashed", "timeout": "timeout", "rejected": "rejected"}
# LINES OF A FAILED LOG LOOKED AT FOR THE CODER'S ERROR SUMMARY
STATUS_TAIL_LINE_COUNT_INT = 60
# THE REF scripts/deploy_runner.ps1 SETS TO THE COMMIT NICOLAS DEPLOYED (THE JUDGE OF NEW JOBS)
DEPLOYED_REF_STR = "refs/deployed"


# CLASS: NO DEPLOYED JUDGE YET (NEW JOBS WAIT)
class NoDeployedJudgeError(ValueError):
    """The judge ref does not resolve: nothing has been deployed with scripts/deploy_runner.ps1."""
# THE KILL-SWITCH FILE NAME INSIDE <SO_DATA_PATH>/control
STOP_FLAG_FOLDER_STR = "control"
STOP_FLAG_FILE_STR = "STOP"
# THE WINDOWS UPDATE GUARD (2026-11-11): DAYS OF PAUSE LEFT A NEW OR RESUMED JOB NEEDS, AND WHAT IS READ
UPDATE_PAUSE_MIN_DAYS = 3.0
UPDATE_UX_KEY_STR = r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
UPDATE_PAUSE_VALUE_LIST = ["PauseUpdatesExpiryTime", "PauseFeatureUpdatesEndTime", "PauseQualityUpdatesEndTime"]
UPDATE_RESTART_KEY_LIST = [r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
                           r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"]


# CLASS: READS HKEY_LOCAL_MACHINE (WINDOWS ONLY)
class WindowsRegistryReader:
    """get_value raises FileNotFoundError for a missing key or value; has_key is False for a missing key. Any other
    error (access denied) propagates, and the guard treats it as not safe."""

    # FUNCTION: ONE VALUE
    def get_value(self, key_str_in, name_str_in):
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_str_in) as key:
            return winreg.QueryValueEx(key, name_str_in)[0]

    # FUNCTION: WHETHER A KEY EXISTS
    def has_key(self, key_str_in):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_str_in):
                return True
        except FileNotFoundError:
            return False


# FUNCTION: A UTC TIME FROM A WINDOWS UPDATE PAUSE VALUE ("2026-11-30T13:59:06Z")
def get_update_utc_datetime(value_in):
    """
    Args:
        value_in (str): ISO time with a trailing Z or an offset

    Returns:
        datetime.datetime: Aware UTC time (raises ValueError when it does not parse)
    """
    # FROMISOFORMAT TAKES +00:00, NOT Z (PYTHON 3.10)
    text_str = str(value_in).strip()
    if text_str.endswith("Z"):
        text_str = text_str[:-1] + "+00:00"
    parsed = datetime.datetime.fromisoformat(text_str)
    if parsed.tzinfo is None:
        raise ValueError(f"pause time {value_in!r} has no time zone")
    return parsed.astimezone(datetime.timezone.utc)


# FUNCTION: WHETHER WINDOWS UPDATE LEAVES ROOM FOR A JOB
def get_update_guard_dict(reader_in=None, now_utc_in=None, platform_str_in=None, min_days_in=UPDATE_PAUSE_MIN_DAYS):
    """
    Fails closed: anything that cannot be read is not safe.

    Args:
        reader_in (object | None): get_value(key, name), has_key(key) (None = WindowsRegistryReader on Windows)
        now_utc_in (datetime.datetime | None): Aware UTC clock (tests)
        platform_str_in (str | None): sys.platform replacement (tests)
        min_days_in (float): Days of pause a job needs

    Returns:
        dict: safe_bool, reason_str, pause_end_str (or None), days_left (or None)
    """
    # OFF WINDOWS THERE IS NO WINDOWS UPDATE (CI, LINUX TESTS)
    platform_str = sys.platform if platform_str_in is None else str(platform_str_in)
    if reader_in is None and platform_str != "win32":
        return {"safe_bool": True, "reason_str": "not applicable (not Windows)", "pause_end_str": None, "days_left": None}
    reader = reader_in if reader_in is not None else WindowsRegistryReader()
    now_utc = now_utc_in or datetime.datetime.now(datetime.timezone.utc)
    # A PENDING RESTART FIRST: IT CAN HAPPEN WHATEVER THE PAUSE SAYS
    try:
        for key_str in UPDATE_RESTART_KEY_LIST:
            if reader.has_key(key_str):
                return {"safe_bool": False, "reason_str": f"a Windows restart is pending ({key_str.split(chr(92))[-1]})",
                        "pause_end_str": None, "days_left": None}
    except Exception as error:
        return {"safe_bool": False, "reason_str": f"cannot read the pending-restart flags ({type(error).__name__})",
                "pause_end_str": None, "days_left": None}
    # THE EARLIEST PAUSE END; A MISSING VALUE MEANS NO PAUSE
    end_list = []
    for name_str in UPDATE_PAUSE_VALUE_LIST:
        try:
            end_list.append(get_update_utc_datetime(reader.get_value(UPDATE_UX_KEY_STR, name_str)))
        except FileNotFoundError:
            return {"safe_bool": False, "reason_str": f"Windows Update is not paused ({name_str} not set)",
                    "pause_end_str": None, "days_left": None}
        except Exception as error:
            return {"safe_bool": False, "reason_str": f"cannot read {name_str} ({type(error).__name__})",
                    "pause_end_str": None, "days_left": None}
    pause_end = min(end_list)
    days_left = (pause_end - now_utc).total_seconds() / 86400.0
    pause_end_str = pause_end.isoformat(timespec="seconds")
    if days_left < float(min_days_in):
        return {"safe_bool": False, "pause_end_str": pause_end_str, "days_left": round(days_left, 2),
                "reason_str": f"the Windows Update pause ends {pause_end_str} ({days_left:.1f} days; at least {min_days_in:g} needed)"}
    return {"safe_bool": True, "pause_end_str": pause_end_str, "days_left": round(days_left, 2),
            "reason_str": f"Windows Update paused until {pause_end_str} ({days_left:.1f} days)"}


# THE GUARD THE QUEUE CALLS (TESTS REPLACE IT; NOTHING ELSE DOES)
UPDATE_GUARD_FUNC = get_update_guard_dict


# FUNCTION: THE GUARD, WITH AN UNEXPECTED ERROR COUNTED AS NOT SAFE
def get_checked_update_guard_dict():
    """
    Returns:
        dict: safe_bool, reason_str, pause_end_str, days_left
    """
    # A GUARD THAT CRASHES IS NOT A SAFE GUARD
    try:
        guard_dict = dict(UPDATE_GUARD_FUNC())
        guard_dict["safe_bool"] = bool(guard_dict.get("safe_bool", False))
        guard_dict["reason_str"] = str(guard_dict.get("reason_str", ""))
        return guard_dict
    except Exception as error:
        return {"safe_bool": False, "reason_str": f"the Windows Update guard failed ({type(error).__name__})",
                "pause_end_str": None, "days_left": None}


# FUNCTION: WHERE THE KILL-SWITCH FILE IS
def get_stop_flag_path_str():
    """
    Returns:
        str: SO_STOP_FLAG_PATH, else <SO_DATA_PATH>/control/STOP, else "" (no data root: no kill switch to read)
    """
    # EVERY ACCOUNT CAN READ THE DATA ROOT AND NONE EXCEPT NICOLAS CAN WRITE ITS control FOLDER
    explicit_str = os.environ.get("SO_STOP_FLAG_PATH", "").strip()
    if explicit_str:
        return explicit_str
    data_str = os.environ.get("SO_DATA_PATH", "").strip()
    return os.path.join(data_str, STOP_FLAG_FOLDER_STR, STOP_FLAG_FILE_STR) if data_str else ""


# FUNCTION: WHETHER THE KILL SWITCH IS SET
def get_stop_flag_bool(path_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths

    Returns:
        bool: True when the flag file exists or cannot be checked. A missing file (or a missing control folder) is
        "not set". Any other error (access denied, a file where the folder should be) counts as set, because a kill
        switch that opens when it cannot be read is no kill switch.
    """
    # NO PATH: NOTHING TO READ
    flag_str = path_dict_in.get("stop_flag") or ""
    if not flag_str:
        return False
    try:
        os.stat(flag_str)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


# FUNCTION: THE QUEUE PATHS (NOTHING IS CREATED)
def get_queue_path_dict(experiment_zone_str_in=None):
    """
    Args:
        experiment_zone_str_in (str | None): store04_experiments folder (None = from SO_DATA_PATH)

    Returns:
        dict: root, pending, running, rejected, done, failed, outbox, logs, lock, state, old_state, visible, grades,
        status, runs, run_index, stop_flag (paths as str; stop_flag is "" when no data root is set)
    """
    # PATHS ONLY: AN AGENT CANNOT CREATE FOLDERS HERE, AND add NEEDS ONLY pending
    zone_str = experiment_zone_str_in or get_named_data_path_str("LOCAL_EXPERIMENTZONE_PATH_STR")
    root_str = os.path.join(zone_str, "queue")
    visible_str = os.path.join(zone_str, VISIBLE_FOLDER_STR)
    return {"visible": visible_str, "grades": os.path.join(visible_str, "grades"),
            "status": os.path.join(visible_str, "status"), "old_state": os.path.join(zone_str, "state.json"),
            "root": root_str, "pending": os.path.join(root_str, "pending"), "running": os.path.join(root_str, "running"),
            "rejected": os.path.join(root_str, "rejected"), "done": os.path.join(root_str, "done"),
            "failed": os.path.join(root_str, "failed"), "outbox": os.path.join(root_str, "outbox"),
            "logs": os.path.join(root_str, "logs"), "lock": os.path.join(root_str, "runner.lock"),
            "state": os.path.join(visible_str, "state.json"), "runs": os.path.join(zone_str, "runs"),
            "run_index": os.path.join(zone_str, "run_index.csv"), "stop_flag": get_stop_flag_path_str()}


# FUNCTION: CREATE THE RUNNER'S FOLDERS
def make_runner_folder_list(path_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths

    Returns:
        None
    """
    # THE RUNNER OWNS THESE
    for key_str in ["pending", "running", "rejected", "done", "failed", "outbox", "logs", "runs", "grades", "status"]:
        os.makedirs(path_dict_in[key_str], exist_ok=True)


# FUNCTION: WRITE JSON THROUGH A TEMPORARY FILE
def write_json_atomic(path_str_in, payload_in):
    """
    Args:
        path_str_in (str): Target file
        payload_in (dict): JSON-serializable payload

    Returns:
        None
    """
    # REPLACE IN ONE STEP SO A READER NEVER SEES HALF A FILE; ON WINDOWS A READER THAT HAS THE TARGET OPEN MAKES THE
    # REPLACE FAIL WITH PermissionError FOR A MOMENT, SO IT IS RETRIED (ABOUT 5 SECONDS) BEFORE IT RAISES
    temp_path_str = f"{path_str_in}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(temp_path_str, "w", encoding="utf-8") as file_obj:
        json.dump(payload_in, file_obj, indent=2, default=str)
    for attempt_int in range(REPLACE_RETRY_COUNT_INT):
        try:
            os.replace(temp_path_str, path_str_in)
            return
        except PermissionError:
            if attempt_int == REPLACE_RETRY_COUNT_INT - 1:
                try:
                    os.remove(temp_path_str)
                except OSError:
                    pass
                raise
            time.sleep(REPLACE_RETRY_SECONDS)


# PATTERNS THE SCRUBBER KEEPS (IDENTIFIERS AND CODE LOCATIONS); EVERY OTHER DIGIT IN AN ERROR TEXT BECOMES "#"
FRAME_LINE_PATTERN = re.compile(r'^\s*File "([^"]{1,300})", line (\d{1,7}), in ([A-Za-z_<>][A-Za-z0-9_<>.]{0,120})\s*$')
EXCEPTION_LINE_PATTERN = re.compile(r"^([A-Za-z_][A-Za-z0-9_.]{0,120}(?:Error|Exception|Exit|Interrupt|Warning|Refused|Failure))(?::\s?(.*))?$")
KEPT_TOKEN_PATTERN = re.compile(r"\b(?:(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}|exp[0-9]{2}_[A-Za-z0-9_]+|"
                                r"[0-9]{20}_[0-9a-f]{6}_[A-Za-z0-9_]+)\b")
DIGIT_RUN_PATTERN = re.compile(r"[0-9]+")
SCRUB_TEXT_MAX_LENGTH_INT = 600


# FUNCTION: A PLACEHOLDER WITHOUT DIGITS (INDEX IN LETTERS)
def get_placeholder_str(index_int_in):
    """
    Args:
        index_int_in (int): Index

    Returns:
        str: "\x00" + letters + "\x00" (no digit, so the digit scrub leaves it alone)
    """
    # BASE 26 IN LETTERS
    letter_str, value_int = "", int(index_int_in)
    while True:
        letter_str = chr(ord("a") + value_int % 26) + letter_str
        value_int //= 26
        if value_int == 0:
            break
    return f"\x00{letter_str}\x00"


# FUNCTION: AN ERROR TEXT WITHOUT NUMBERS
def get_scrubbed_text_str(text_in, keep_list_in=None):
    """
    Conservative (roadmap R4): an error message may print values (a DataFrame, an assertion, a formatted return). Every
    run of digits becomes "#", except inside identifiers: the strings in keep_list_in (job id, run id, design path,
    commits), git hashes (7-40 hex characters with a letter), experiment names (expNN_...) and job ids. Control
    characters go and the text is cut.

    Args:
        text_in (str): Text
        keep_list_in (list[str] | None): Identifiers kept as they are

    Returns:
        str: The scrubbed text
    """
    # IDENTIFIERS OUT (LONGEST FIRST), DIGITS SCRUBBED, IDENTIFIERS BACK
    text_str = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]+", " ", str(text_in or ""))
    kept_list = []

    def hold_func(value_str_in):
        kept_list.append(value_str_in)
        return get_placeholder_str(len(kept_list) - 1)
    for keep_str in sorted({str(value) for value in (keep_list_in or []) if value and len(str(value)) >= 4},
                           key=len, reverse=True):
        if keep_str in text_str:
            text_str = text_str.replace(keep_str, hold_func(keep_str))
    text_str = KEPT_TOKEN_PATTERN.sub(lambda match_in: hold_func(match_in.group(0)), text_str)
    text_str = DIGIT_RUN_PATTERN.sub("#", text_str)
    for index_int in range(len(kept_list) - 1, -1, -1):
        text_str = text_str.replace(get_placeholder_str(index_int), kept_list[index_int])
    return text_str[:SCRUB_TEXT_MAX_LENGTH_INT]


# FUNCTION: THE CODER'S ERROR SUMMARY OF A FAILED LOG
def get_error_summary_dict(log_line_list_in, keep_list_in=None):
    """
    Keeps only the traceback frames (file, line, function: code locations, not data) and the last exception line with
    its message scrubbed. Source lines, printed values and every other log line are dropped.

    Args:
        log_line_list_in (list[str]): The log (or its tail)
        keep_list_in (list[str] | None): Identifiers kept by the scrubber

    Returns:
        dict: error_type (str | None), error_text (scrubbed, str), frame_list (list of "file:line in function")
    """
    # THE LAST EXCEPTION LINE, AND THE FRAMES BEFORE IT
    line_list = [str(line_str).rstrip("\r\n") for line_str in list(log_line_list_in or [])[-STATUS_TAIL_LINE_COUNT_INT:]]
    frame_list, error_type, error_text = [], None, ""
    for line_str in line_list:
        frame_match = FRAME_LINE_PATTERN.match(line_str)
        if frame_match:
            file_str = frame_match.group(1).replace("\\", "/")
            for marker_str in ["/experiments/", "/so/", "/scripts/", "/tests/"]:
                if marker_str in file_str:
                    file_str = marker_str.strip("/") + "/" + file_str.split(marker_str, 1)[1]
                    break
            else:
                file_str = file_str.rsplit("/", 1)[-1]
            # THE LINE NUMBER IS A CODE LOCATION AND STAYS; THE PATH AND THE FUNCTION NAME ARE SCRUBBED LIKE TEXT
            frame_list.append(f"{get_scrubbed_text_str(file_str, keep_list_in)}:{frame_match.group(2)} in "
                              f"{get_scrubbed_text_str(frame_match.group(3), keep_list_in)}")
            continue
        exception_match = EXCEPTION_LINE_PATTERN.match(line_str.strip())
        if exception_match:
            error_type = exception_match.group(1)
            error_text = get_scrubbed_text_str(exception_match.group(2) or "", keep_list_in)
    if error_type is None and line_list:
        error_text = get_scrubbed_text_str(line_list[-1], keep_list_in)
    return {"error_type": error_type, "error_text": error_text, "frame_list": frame_list[-12:]}


# FUNCTION: WRITE A NEW JOB FILE IN ONE CREATE
def write_job_file(path_str_in, payload_in):
    """
    so_agent may create files in queue/pending but not rename or delete them (a rename needs delete access), so a job
    is written directly with an exclusive create. A reader that finds it half written skips it until the next look.

    Args:
        path_str_in (str): New job file
        payload_in (dict): Job

    Returns:
        None
    """
    # "x" REFUSES AN EXISTING NAME
    with open(path_str_in, "x", encoding="utf-8") as file_obj:
        json.dump(payload_in, file_obj, indent=2, default=str)


# FUNCTION: READ A JSON FILE
def read_json(path_str_in):
    """
    Args:
        path_str_in (str): File

    Returns:
        dict: Payload
    """
    # UTF-8
    with open(path_str_in, encoding="utf-8") as file_obj:
        return json.load(file_obj)


# FUNCTION: RUN GIT IN A FOLDER
def run_git_str(arg_list_in, cwd_in=WORKSPACE_PATH, input_str_in=None, environment_dict_in=None):
    """
    Args:
        arg_list_in (list[str]): git arguments
        cwd_in (Path | str): Folder
        input_str_in (str | None): Standard input
        environment_dict_in (dict | None): Variables added to this process's environment

    Returns:
        str: stdout
    """
    # RAISES ON A NON-ZERO EXIT
    environment_dict = dict(os.environ, **environment_dict_in) if environment_dict_in else None
    return subprocess.check_output(["git"] + list(arg_list_in), cwd=str(cwd_in), text=True, encoding="utf-8",
                                   stderr=subprocess.STDOUT, input=input_str_in, env=environment_dict)


# FUNCTION: THE COMMIT A NEW JOB RUNS
def get_add_commit_str(design_str_in, commit_str_in=None, git_func_in=None):
    """
    An explicit commit wins. Otherwise HEAD, after refusing uncommitted changes in so/ or the design folder.

    Args:
        design_str_in (str): Experiment folder (repo-relative)
        commit_str_in (str | None): Commit named by the caller
        git_func_in (callable | None): (args list) -> stdout (tests)

    Returns:
        str: Full commit hash
    """
    # THE CODE THE RUN USES MUST BE COMMITTED
    git_func = git_func_in or run_git_str
    if commit_str_in:
        return git_func(["rev-parse", "--verify", f"{commit_str_in}^{{commit}}"]).strip()
    status_str = git_func(["status", "--porcelain", "--"] + GUARDED_ADD_FOLDER_LIST + [design_str_in])
    if status_str.strip():
        raise ValueError(f"uncommitted changes in the code this run uses; commit and push first:\n{status_str.strip()}")
    return git_func(["rev-parse", "HEAD"]).strip()


# FUNCTION: WHO ADDED A JOB
def get_user_str():
    """
    Returns:
        str: The account name
    """
    # WINDOWS, THEN POSIX
    return os.environ.get("USERNAME") or os.environ.get("USER") or ""


# FUNCTION: THE FIELDS OF A JOB WITH SAFE VALUES (NO GIT, NO FILES)
def get_clean_job_dict(raw_in, file_stem_str_in=None):
    """
    A job file is written by an agent account, so every value is checked before anything is built from it: the
    identifiers are short patterns (they become folder and file names), the commit is a full hash, the note is bounded
    text. Unknown fields are refused rather than ignored.

    Args:
        raw_in (object): The parsed job file
        file_stem_str_in (str | None): The file name without .json (must equal job_id)

    Returns:
        dict: The job with all fields of JOB_FIELD_LIST present (None where absent)
    """
    # A JSON OBJECT WITH KNOWN FIELDS ONLY
    if not isinstance(raw_in, dict):
        raise ValueError("the job file is not a JSON object")
    unknown_list = sorted(set(raw_in) - set(JOB_FIELD_LIST))
    if unknown_list:
        raise ValueError(f"unknown field(s): {', '.join(str(name_str)[:40] for name_str in unknown_list)}")
    job_dict = {name_str: raw_in.get(name_str) for name_str in JOB_FIELD_LIST}
    # IDENTIFIERS
    for name_str, pattern in [("job_id", JOB_ID_PATTERN), ("design", DESIGN_PATTERN), ("commit", COMMIT_PATTERN)]:
        if not isinstance(job_dict[name_str], str) or not pattern.match(job_dict[name_str]):
            raise ValueError(f"{name_str} is missing or not in the allowed form")
    if file_stem_str_in is not None and job_dict["job_id"] != file_stem_str_in:
        raise ValueError("job_id differs from the file name")
    for name_str, pattern in [("run_id", RUN_ID_PATTERN), ("retry_of", JOB_ID_PATTERN), ("judge_commit", COMMIT_PATTERN)]:
        if job_dict[name_str] is not None and (not isinstance(job_dict[name_str], str) or not pattern.match(job_dict[name_str])):
            raise ValueError(f"{name_str} is not in the allowed form")
    # THE NOTE BECOMES A COMMAND ARGUMENT AND A RESULTS-LOG CELL
    note_str = job_dict["note"] if job_dict["note"] is not None else ""
    if not isinstance(note_str, str):
        raise ValueError("note is not text")
    note_str = re.sub(r"[\x00-\x1f\x7f]+", " ", note_str).strip()
    if len(note_str) > NOTE_MAX_LENGTH_INT:
        raise ValueError(f"note is longer than {NOTE_MAX_LENGTH_INT} characters")
    job_dict["note"] = note_str
    # NUMBERS
    n_jobs = job_dict["n_jobs"]
    if n_jobs is not None and (isinstance(n_jobs, bool) or not isinstance(n_jobs, int) or not 1 <= n_jobs <= MAX_N_JOBS_INT):
        raise ValueError(f"n_jobs must be an integer from 1 to {MAX_N_JOBS_INT}")
    attempt = 1 if job_dict["attempt"] is None else job_dict["attempt"]
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 99:
        raise ValueError("attempt must be an integer from 1 to 99")
    job_dict["attempt"] = attempt
    # WHO AND WHEN (DISPLAY ONLY)
    for name_str, pattern in [("added_ts", ADDED_TS_PATTERN), ("added_by", ADDED_BY_PATTERN)]:
        value = job_dict[name_str] if job_dict[name_str] is not None else ""
        if not isinstance(value, str) or not pattern.match(value):
            raise ValueError(f"{name_str} is not in the allowed form")
        job_dict[name_str] = value
    return job_dict


# FUNCTION: A RETRY JOB MUST MATCH THE RUNNER'S RECORD OF THE FAILED JOB
def check_retry_job_dict(path_dict_in, job_dict_in):
    """
    A run id, a judge commit or a retry marker in a pending file is accepted only when failed/<retry_of>.json (written
    by the runner) names the same run id, design and commit. The judge commit is then the failed job's, so a retry
    runs under the judge of the first attempt, and an agent cannot pick a judge commit or a run folder by writing it.

    Args:
        path_dict_in (dict): Queue paths
        job_dict_in (dict): Output of get_clean_job_dict

    Returns:
        dict: The job with attempt and judge_commit taken from the failed record
    """
    # NOT A RETRY: NONE OF THE THREE FIELDS MAY BE SET
    job_dict = dict(job_dict_in)
    if job_dict["retry_of"] is None:
        if job_dict["run_id"] is not None or job_dict["judge_commit"] is not None:
            raise ValueError("run_id or judge_commit without retry_of")
        return job_dict
    if job_dict["run_id"] is None:
        raise ValueError("retry_of without run_id")
    failed_path_str = os.path.join(path_dict_in["failed"], f"{job_dict['retry_of']}.json")
    if not os.path.isfile(failed_path_str):
        raise ValueError(f"retry_of {job_dict['retry_of']} is not a failed job")
    failed_dict = read_json(failed_path_str)
    for name_str in ["run_id", "design", "commit"]:
        if failed_dict.get(name_str) != job_dict[name_str]:
            raise ValueError(f"{name_str} differs from the failed job {job_dict['retry_of']}")
    if job_dict["judge_commit"] is not None and job_dict["judge_commit"] != failed_dict.get("judge_commit"):
        raise ValueError("judge_commit differs from the failed job")
    job_dict["judge_commit"] = failed_dict.get("judge_commit")
    job_dict["attempt"] = int(failed_dict.get("attempt") or 1) + 1
    return job_dict


# FUNCTION: THE COMMIT EXISTS AND HOLDS THE DESIGN
def check_job_commit_exists(job_dict_in, git_func_in=None):
    """
    Args:
        job_dict_in (dict): Output of get_clean_job_dict
        git_func_in (callable | None): Injected git (tests)

    Returns:
        None
    """
    # THE COMMIT, THEN design.py INSIDE IT
    git_func = git_func_in or run_git_str
    try:
        git_func(["cat-file", "-e", f"{job_dict_in['commit']}^{{commit}}"])
        git_func(["cat-file", "-e", f"{job_dict_in['commit']}:{job_dict_in['design']}/design.py"])
    except subprocess.CalledProcessError:
        raise ValueError(f"commit {job_dict_in['commit']} does not exist in the runner's clone or has no "
                         f"{job_dict_in['design']}/design.py; push it to origin first")


# FUNCTION: A PENDING FILE, CHECKED COMPLETELY
def get_validated_job_dict(path_dict_in, raw_in, file_stem_str_in, git_func_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        raw_in (object): The parsed pending file
        file_stem_str_in (str): File name without .json
        git_func_in (callable | None): Injected git (tests)

    Returns:
        dict: The job to claim (ValueError with the reason when it must be rejected)
    """
    # FIELDS, THEN THE RETRY RECORD, THEN GIT
    job_dict = check_retry_job_dict(path_dict_in, get_clean_job_dict(raw_in, file_stem_str_in))
    check_job_commit_exists(job_dict, git_func_in)
    return job_dict


# FUNCTION: THE ENVIRONMENT OF THE CHILD PROCESS, WITHOUT SECRETS
def get_child_environment_dict(environment_dict_in=None):
    """
    The design runs in a child process of the runner. It does not need SMTP settings, tokens or keys, and design code
    must not be able to read them from os.environ.

    Args:
        environment_dict_in (dict | None): The environment (None = this process's)

    Returns:
        dict: A copy without the secret names
    """
    # PREFIXES, THEN FRAGMENTS (WINDOWS NAMES ARE CASE-INSENSITIVE)
    source_dict = os.environ if environment_dict_in is None else environment_dict_in
    child_dict = {}
    for name_str, value_str in source_dict.items():
        upper_str = name_str.upper()
        if any(upper_str.startswith(prefix_str) for prefix_str in SECRET_PREFIX_LIST):
            continue
        if any(fragment_str in upper_str for fragment_str in SECRET_FRAGMENT_LIST):
            continue
        child_dict[name_str] = value_str
    return child_dict


# FUNCTION: ADD ONE JOB
def add_job_dict(path_dict_in, design_str_in, note_str_in="", n_jobs_in=None, now_in=None, commit_str_in=None,
                 git_func_in=None):
    """
    Args:
        path_dict_in (dict): Output of get_queue_path_dict
        design_str_in (str): Experiment folder, relative to the workspace (must contain design.py)
        note_str_in (str): Trial-row note
        n_jobs_in (int | None): Candidate processes
        now_in (datetime.datetime | None): Clock (tests)
        commit_str_in (str | None): Commit to run (None = HEAD of this clone, which must be clean)
        git_func_in (callable | None): Injected git (tests)

    Returns:
        dict: The job
    """
    # THE FOLDER MUST BE A DESIGN; THE COMMIT IS FIXED NOW
    design_str = str(design_str_in).replace("\\", "/").rstrip("/")
    if not (WORKSPACE_PATH / design_str / "design.py").is_file():
        raise ValueError(f"{design_str} has no design.py")
    commit_str = get_add_commit_str(design_str, commit_str_in, git_func_in)
    # THE WINDOWS UPDATE GUARD: A JOB ADDED NOW SHOULD NOT MEET AN UPDATE RESTART (2026-11-11)
    guard_dict = get_checked_update_guard_dict()
    if not guard_dict["safe_bool"]:
        raise ValueError(f"not adding the job: {guard_dict['reason_str']}. Renew the pause (Settings > Windows Update > "
                         f"Pause updates > Pick a date) or restart first, then add again.")
    now = now_in or datetime.datetime.now()
    # A SHORT RANDOM PART: WINDOWS CLOCKS TICK ABOUT EVERY 15 MS, SO TWO JOBS ADDED TOGETHER SHARE A TIMESTAMP
    job_id_str = f"{now.strftime('%Y%m%d%H%M%S%f')}_{uuid.uuid4().hex[:6]}_{Path(design_str).name}"
    job_dict = {"job_id": job_id_str, "design": design_str, "note": str(note_str_in), "commit": commit_str,
                "n_jobs": None if n_jobs_in is None else int(n_jobs_in), "added_ts": now.isoformat(timespec="seconds"),
                "added_by": get_user_str(), "attempt": 1}
    # THE RUNNER APPLIES THE SAME CHECKS TO THE FILE; FAIL HERE, WHERE THE CALLER SEES THE REASON
    get_clean_job_dict(job_dict, job_id_str)
    write_job_file(os.path.join(path_dict_in["pending"], f"{job_id_str}.json"), job_dict)
    return job_dict


# FUNCTION: QUEUE A FAILED JOB AGAIN UNDER ITS RUN ID
def add_retry_job_dict(path_dict_in, job_id_str_in, now_in=None):
    """
    The new pending job keeps the failed job's design, commit, note and run id, so run_development resumes from the
    run's checkpoints and the trial log gets no second row for a period already scored.

    Args:
        path_dict_in (dict): Queue paths
        job_id_str_in (str): A crashed or timed-out job (visible/status/<job_id>.json, else queue/failed/)
        now_in (datetime.datetime | None): Clock (tests)

    Returns:
        dict: The new job
    """
    # THE TECHNICAL STATUS HOLDS WHAT A RETRY NEEDS (AGENTS CANNOT READ failed/ SINCE R4); NICOLAS MAY STILL USE failed/.
    # THE RUNNER CHECKS THE RETRY AGAINST failed/ EITHER WAY (check_retry_job_dict)
    status_path_str = os.path.join(path_dict_in["status"], f"{get_safe_name_str(job_id_str_in)}.json")
    failed_path_str = os.path.join(path_dict_in["failed"], f"{job_id_str_in}.json")
    failed_dict = None
    try:
        status_dict = read_json(status_path_str)
        if status_dict.get("retry_possible") and status_dict.get("job_id") == job_id_str_in:
            failed_dict = status_dict
    except (OSError, ValueError, AttributeError):
        failed_dict = None
    if failed_dict is None:
        try:
            failed_dict = read_json(failed_path_str)
        except (OSError, ValueError):
            raise ValueError(f"no failed job {job_id_str_in} (its status does not allow a retry, or it does not exist)")
    now = now_in or datetime.datetime.now()
    attempt_int = int(failed_dict.get("attempt") or 1) + 1
    job_id_str = f"{now.strftime('%Y%m%d%H%M%S%f')}_{uuid.uuid4().hex[:6]}_{Path(failed_dict['design']).name}_retry{attempt_int}"
    job_dict = {"job_id": job_id_str, "design": failed_dict["design"], "note": failed_dict.get("note", ""),
                "commit": failed_dict.get("commit"), "n_jobs": failed_dict.get("n_jobs"),
                "added_ts": now.isoformat(timespec="seconds"), "added_by": get_user_str(),
                "attempt": attempt_int, "run_id": failed_dict.get("run_id"), "retry_of": job_id_str_in,
                "judge_commit": failed_dict.get("judge_commit")}
    get_clean_job_dict(job_dict, job_id_str)
    write_job_file(os.path.join(path_dict_in["pending"], f"{job_id_str}.json"), job_dict)
    return job_dict


# FUNCTION: PENDING JOBS, OLDEST FIRST
def get_pending_job_list(path_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths

    Returns:
        list[dict]: Jobs, oldest first
    """
    # FILE NAMES START WITH THE TIME THE JOB WAS ADDED
    if not os.path.isdir(path_dict_in["pending"]):
        return []
    name_list = sorted(name_str for name_str in os.listdir(path_dict_in["pending"]) if name_str.endswith(".json"))
    job_list = []
    for name_str in name_list:
        try:
            job_list.append(read_json(os.path.join(path_dict_in["pending"], name_str)))
        except (ValueError, OSError):
            continue
    return job_list


# FUNCTION: FILE A PENDING FILE AS REJECTED
def reject_pending_file(path_dict_in, name_str_in, raw_in, reason_str_in, now_in=None, source_key_str_in="pending"):
    """
    The file is never run. It is copied into rejected/ with the reason and removed from pending/. Nothing is emailed:
    an agent that writes bad files in a loop must not be able to flood the inbox (the daily digest lists them).

    Args:
        path_dict_in (dict): Queue paths
        name_str_in (str): File name in pending/ (the name is not trusted; only its basename is used)
        raw_in (object): What was read (parsed JSON, or text when it could not be parsed)
        reason_str_in (str): Why
        now_in (datetime.datetime | None): Clock (tests)
        source_key_str_in (str): Folder key the file is removed from ("pending", or "running" for a claimed job)

    Returns:
        str: The rejected file
    """
    # A NAME THAT CANNOT ESCAPE THE FOLDER; A TEXT IS CUT
    now = now_in or datetime.datetime.now()
    safe_name_str = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(name_str_in))[:120]
    stem_str = safe_name_str[:-5] if safe_name_str.endswith(".json") else safe_name_str
    os.makedirs(path_dict_in["rejected"], exist_ok=True)
    target_str = os.path.join(path_dict_in["rejected"], f"{stem_str}.json")
    if os.path.exists(target_str):
        target_str = os.path.join(path_dict_in["rejected"], f"{stem_str}_{uuid.uuid4().hex[:6]}.json")
    job_value = raw_in[:2000] if isinstance(raw_in, str) else raw_in
    write_json_atomic(target_str, {"rejected_ts": now.isoformat(timespec="seconds"), "reason": str(reason_str_in)[:500],
                                   "file": safe_name_str, "job": job_value})
    source_str = os.path.join(path_dict_in[source_key_str_in], os.path.basename(name_str_in))
    if os.path.isfile(source_str):
        os.remove(source_str)
    # THE AGENT THAT ADDED THE JOB CANNOT READ rejected/: THE SCRUBBED REASON GOES INTO ITS STATUS FILE (ROADMAP R4)
    status_job_dict = dict(raw_in) if isinstance(raw_in, dict) else {}
    status_job_dict["job_id"] = stem_str
    write_status_dict(path_dict_in, status_job_dict, "rejected", now, reason_str_in=str(reason_str_in)[:500])
    write_state_dict(path_dict_in, None, {"job_id": stem_str, "status": "rejected"})
    return target_str


# FUNCTION: THE OLDEST PENDING JOB THAT PASSES EVERY CHECK
def get_next_job_dict(path_dict_in, git_func_in=None, now_in=None):
    """
    Walks pending/ oldest first. A file that is too large, is not JSON, or fails a check is moved to rejected/ with the
    reason. A file that is not parsable yet is left alone for STALE_PENDING_SECONDS, because the agent may still be
    writing it (write_job_file is a single create, but the reader can be quicker).

    Args:
        path_dict_in (dict): Queue paths
        git_func_in (callable | None): Injected git (tests)
        now_in (datetime.datetime | None): Clock (tests)

    Returns:
        dict | None: The job, or None when nothing valid is pending
    """
    # FILE NAMES START WITH THE TIME THE JOB WAS ADDED
    now = now_in or datetime.datetime.now()
    if not os.path.isdir(path_dict_in["pending"]):
        return None
    for name_str in sorted(os.listdir(path_dict_in["pending"])):
        file_str = os.path.join(path_dict_in["pending"], name_str)
        if not name_str.endswith(".json") or not os.path.isfile(file_str):
            continue
        try:
            if os.path.getsize(file_str) > MAX_PENDING_FILE_BYTES:
                reject_pending_file(path_dict_in, name_str, "(file larger than the limit)", "file is too large", now)
                continue
            text_str = Path(file_str).read_text(encoding="utf-8")
            raw = json.loads(text_str)
        except (ValueError, OSError) as error:
            try:
                age_seconds = time.time() - os.path.getmtime(file_str)
            except OSError:
                continue
            if age_seconds > STALE_PENDING_SECONDS:
                reject_pending_file(path_dict_in, name_str, "(unreadable)", f"not valid JSON: {type(error).__name__}", now)
            continue
        try:
            return get_validated_job_dict(path_dict_in, raw, name_str[:-5], git_func_in)
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            reject_pending_file(path_dict_in, name_str, raw, str(error), now)
    return None


# FUNCTION: THE COMMIT OF THE CODE THIS QUEUE PROCESS RUNS (ONCE PER PROCESS)
def get_queue_commit_str():
    """
    Returns:
        str: git HEAD of the folder holding this script, or "" when git cannot say. state.json shows it next to the
        deployed commit; deploy_runner.ps1 moves both together.
    """
    # CACHED: THE CODE OF A RUNNING PROCESS DOES NOT CHANGE
    global QUEUE_COMMIT_CACHE_STR
    if QUEUE_COMMIT_CACHE_STR is None:
        try:
            QUEUE_COMMIT_CACHE_STR = run_git_str(["rev-parse", "HEAD"]).strip()
        except (OSError, subprocess.CalledProcessError):
            QUEUE_COMMIT_CACHE_STR = ""
    return QUEUE_COMMIT_CACHE_STR


# FUNCTION: WRITE state.json
def write_state_dict(path_dict_in, running_job_in, result_dict_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        running_job_in (dict | None): The job being run, or None
        result_dict_in (dict | None): A finished job's result to add to the recent list

    Returns:
        dict: The state written (updated_ts is the runner's heartbeat)
    """
    # THE MAIN THREAD AND THE HEARTBEAT THREAD BOTH WRITE; THE RECENT LIST IS KEPT ACROSS WRITES, TRIMMED TO
    # IDENTIFIERS AND STATUS (ROADMAP R4: AGENTS READ THIS FILE). AN OLD ENTRY WITH MORE FIELDS IS CUT, NOT MERGED
    with STATE_LOCK:
        recent_list = []
        if os.path.isfile(path_dict_in["state"]):
            try:
                recent_list = list(read_json(path_dict_in["state"]).get("recent", []))
            except (ValueError, OSError, AttributeError):
                recent_list = []
        if result_dict_in is not None:
            recent_list = [result_dict_in] + recent_list
        recent_list = [get_state_entry_dict(entry) for entry in recent_list if isinstance(entry, dict)]
        state_dict = {"updated_ts": datetime.datetime.now().isoformat(timespec="seconds"),
                      "running": get_state_entry_dict(running_job_in, STATE_RUNNING_KEY_LIST) if running_job_in else None,
                      "pending_count": len(get_pending_job_list(path_dict_in)), "host": socket.gethostname(),
                      "queue_commit": get_queue_commit_str(), "deployed_commit": get_deployed_commit_str(),
                      "stopped": get_stop_flag_bool(path_dict_in),
                      "update_guard": {key_str: value for key_str, value in get_checked_update_guard_dict().items()
                                       if key_str in ("safe_bool", "reason_str")},
                      "recent": recent_list[:STATE_RECENT_COUNT_INT]}
        os.makedirs(os.path.dirname(path_dict_in["state"]), exist_ok=True)
        write_json_atomic(path_dict_in["state"], state_dict)
        # THE state.json OF EARLIER VERSIONS (ZONE ROOT, FULL RESULTS) GOES
        old_state_str = path_dict_in.get("old_state") or ""
        if old_state_str and os.path.abspath(old_state_str) != os.path.abspath(path_dict_in["state"]) and os.path.isfile(old_state_str):
            try:
                os.remove(old_state_str)
            except OSError as error:
                print(f"warning: could not remove the old {old_state_str} ({type(error).__name__})", flush=True)
    return state_dict


# FUNCTION: ONE state.json ENTRY WITH ALLOWED FIELDS ONLY
def get_state_entry_dict(entry_dict_in, key_list_in=None):
    """
    Args:
        entry_dict_in (dict): A job, a result, or an earlier entry
        key_list_in (list[str] | None): Allowed keys (None = STATE_RECENT_KEY_LIST)

    Returns:
        dict: Only the allowed keys, as strings (or None); status mapped to the technical status names
    """
    # IDENTIFIERS ONLY; A QUEUE STATUS BECOMES THE CODER'S STATUS NAME (done -> ran)
    key_list = list(key_list_in or STATE_RECENT_KEY_LIST)
    entry_dict = {}
    for key_str in key_list:
        value = entry_dict_in.get(key_str)
        if key_str == "status" and value is not None:
            value = TECHNICAL_STATUS_DICT.get(str(value), str(value) if str(value) in TECHNICAL_STATUS_DICT.values() else "unknown")
        entry_dict[key_str] = None if value is None else (int(value) if key_str == "attempt" and str(value).isdigit() else str(value))
    return entry_dict


# FUNCTION: A FILE NAME FROM AN IDENTIFIER (NOTHING CAN ESCAPE THE FOLDER)
def get_safe_name_str(value_in):
    """
    Args:
        value_in (str): Job id or run id

    Returns:
        str: Letters, digits, "_", "-" and "." only, at most 160 characters
    """
    # THE IDENTIFIERS ARE PATTERN-CHECKED ALREADY; THIS IS A SECOND FENCE
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(value_in))[:160] or "unnamed"


# FUNCTION: THE TECHNICAL STATUS OF A JOB (WHAT THE CODER SEES)
def write_status_dict(path_dict_in, job_dict_in, status_str_in, now_in=None, error_dict_in=None, look_ahead_str_in=None,
                      reason_str_in=None):
    """
    visible/status/<job_id>.json (roadmap R4): ran / crashed / timeout / rejected; for a run that ran, its look-ahead
    status only (a failed look-ahead check is a code bug the coder must fix; it says nothing about performance); for a
    crash, the error type, the scrubbed message and the code locations; for a rejection, the scrubbed reason. It also
    holds the identifiers a retry needs. Nothing about the grade, the verdict or any number the run produced.

    Args:
        path_dict_in (dict): Queue paths
        job_dict_in (dict): The job (or the raw pending content of a rejected file)
        status_str_in (str): done, failed, timeout or rejected (queue names)
        now_in (datetime.datetime | None): Clock (tests)
        error_dict_in (dict | None): Output of get_error_summary_dict (crashes)
        look_ahead_str_in (str | None): pass / fail / pending (runs that ran)
        reason_str_in (str | None): Why it was rejected, or the queue's own finding (judge changed, gave up)

    Returns:
        str: The file written
    """
    # IDENTIFIERS ARE KEPT BY THE SCRUBBER; EVERYTHING ELSE LOSES ITS DIGITS
    now = now_in or datetime.datetime.now()
    job_dict = job_dict_in if isinstance(job_dict_in, dict) else {}
    keep_list = [job_dict.get(name_str) for name_str in ["job_id", "run_id", "design", "commit", "judge_commit", "retry_of"]
                 if isinstance(job_dict.get(name_str), str)]
    job_id_str = str(job_dict.get("job_id") or "unknown")
    status_str = TECHNICAL_STATUS_DICT.get(status_str_in, "crashed")

    def get_identifier_value(name_str_in, pattern_in):
        value = job_dict.get(name_str_in)
        return value if isinstance(value, str) and pattern_in.match(value) else None
    attempt_value = job_dict.get("attempt")
    status_dict = {"job_id": job_id_str if JOB_ID_PATTERN.match(job_id_str) else get_safe_name_str(job_id_str),
                   "status": status_str, "finished_ts": now.isoformat(timespec="seconds"),
                   "run_id": get_identifier_value("run_id", RUN_ID_PATTERN),
                   "design": get_identifier_value("design", DESIGN_PATTERN),
                   "commit": get_identifier_value("commit", COMMIT_PATTERN),
                   "judge_commit": get_identifier_value("judge_commit", COMMIT_PATTERN),
                   "attempt": int(attempt_value) if isinstance(attempt_value, int) and not isinstance(attempt_value, bool) else None,
                   "look_ahead": look_ahead_str_in if status_str == "ran" and look_ahead_str_in in ("pass", "fail", "pending") else None,
                   "look_ahead_failed": bool(status_str == "ran" and look_ahead_str_in == "fail"),
                   "reason": get_scrubbed_text_str(reason_str_in, keep_list) if reason_str_in else None,
                   "error_type": None, "error_text": None, "error_frame_list": [],
                   "retry_possible": bool(status_str in ("crashed", "timeout") and job_dict.get("run_id")),
                   # THE JOB'S OWN NOTE (WRITTEN BY WHOEVER QUEUED IT) AND n_jobs: A RETRY COPIES THEM
                   "note": str(job_dict.get("note") or "")[:NOTE_MAX_LENGTH_INT] if status_str != "rejected" else None,
                   "n_jobs": job_dict.get("n_jobs") if isinstance(job_dict.get("n_jobs"), int) else None}
    if error_dict_in:
        status_dict.update({"error_type": error_dict_in.get("error_type"), "error_text": error_dict_in.get("error_text"),
                            "error_frame_list": list(error_dict_in.get("frame_list") or [])})
    os.makedirs(path_dict_in["status"], exist_ok=True)
    status_path_str = os.path.join(path_dict_in["status"], f"{get_safe_name_str(status_dict['job_id'])}.json")
    write_json_atomic(status_path_str, status_dict)
    return status_path_str


# FUNCTION: THE GRADE OF A RUN (WHAT THE PLANNER SEES)
def write_grade_dict(path_dict_in, result_dict_in, grade_dict_in):
    """
    visible/grades/<run_id>.json (roadmap R4): identifiers, the grade, its reason and the audit state; no numbers. A
    retry of the same run rewrites it (attempt shows which).

    Args:
        path_dict_in (dict): Queue paths
        result_dict_in (dict): The job's result
        grade_dict_in (dict): Output of so.runner.grade.get_queue_grade_dict

    Returns:
        str: The file written
    """
    # ONLY PATTERN-CHECKED IDENTIFIERS AND THE FIXED VOCABULARY
    def get_identifier_value(name_str_in, pattern_in):
        value = result_dict_in.get(name_str_in)
        return value if isinstance(value, str) and pattern_in.match(value) else None
    grade_record_dict = {"run_id": get_identifier_value("run_id", RUN_ID_PATTERN),
                         "job_id": get_identifier_value("job_id", JOB_ID_PATTERN),
                         "design": get_identifier_value("design", DESIGN_PATTERN),
                         "design_commit": get_identifier_value("commit", COMMIT_PATTERN),
                         "judge_commit": get_identifier_value("judge_commit", COMMIT_PATTERN),
                         "attempt": int(result_dict_in.get("attempt") or 1),
                         "finished_ts": str(result_dict_in.get("finished_ts") or ""),
                         "grade": grade_dict_in["grade_str"], "reason_code": grade_dict_in["reason_code_str"],
                         "reason": grade_dict_in["reason_str"], "audit": grade_dict_in["audit_str"]}
    os.makedirs(path_dict_in["grades"], exist_ok=True)
    grade_path_str = os.path.join(path_dict_in["grades"], f"{get_safe_name_str(grade_record_dict['run_id'] or result_dict_in.get('run_id'))}.json")
    write_json_atomic(grade_path_str, grade_record_dict)
    return grade_path_str


# CLASS: A HEARTBEAT WHILE A JOB RUNS
class Heartbeat:
    """
    Refreshes state.json (updated_ts) every interval while the with-block runs, so a watcher can tell a long job from
    a dead runner. The thread is a daemon and is stopped when the block ends.
    """

    def __init__(self, path_dict_in, running_job_in, interval_seconds_in=None):
        self.path_dict = path_dict_in
        self.running_job = running_job_in
        self.interval_seconds = float(interval_seconds_in if interval_seconds_in is not None
                                      else os.environ.get("SO_QUEUE_HEARTBEAT_SECONDS", DEFAULT_HEARTBEAT_SECONDS))
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.beat, daemon=True)

    def beat(self):
        while not self.stop_event.wait(self.interval_seconds):
            try:
                write_state_dict(self.path_dict, self.running_job)
            except Exception as error:
                print(f"warning: heartbeat failed ({type(error).__name__}: {error})", flush=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args_in):
        self.stop_event.set()
        self.thread.join(timeout=10)
        return False


# FUNCTION: WHETHER A PROCESS IS ALIVE
def get_pid_alive_bool(pid_int_in):
    """
    Windows: OpenProcess and GetExitCodeProcess (os.kill would terminate the process there). Elsewhere: signal 0.

    Args:
        pid_int_in (int): Process id

    Returns:
        bool: True when the process exists
    """
    # NO PROCESS HAS ID 0 OR BELOW
    pid_int = int(pid_int_in)
    if pid_int <= 0:
        return False
    if os.name == "nt":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid_int)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid_int, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# FUNCTION: TAKE THE RUNNER LOCK (A STALE LOCK IS REPLACED)
def acquire_runner_lock(path_dict_in, pid_alive_func_in=None):
    """
    The lock holds {pid, host, started_ts}. An existing lock from this host whose process is gone is stale and is
    replaced; any other existing lock refuses the start.

    Args:
        path_dict_in (dict): Queue paths
        pid_alive_func_in (callable | None): pid -> bool (tests)

    Returns:
        None
    """
    # CREATE EXCLUSIVELY; ON A CONFLICT, LOOK AT THE HOLDER ONCE
    pid_alive_func = pid_alive_func_in or get_pid_alive_bool
    payload_bytes = json.dumps({"pid": os.getpid(), "host": socket.gethostname(),
                                "started_ts": datetime.datetime.now().isoformat(timespec="seconds")}).encode("utf-8")
    for _attempt_int in range(2):
        try:
            lock_fd = os.open(path_dict_in["lock"], os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                holder_dict = read_json(path_dict_in["lock"])
            except (ValueError, OSError):
                holder_dict = {}
            if not isinstance(holder_dict, dict):
                holder_dict = {}
            same_host_bool = holder_dict.get("host") == socket.gethostname()
            if same_host_bool and not pid_alive_func(int(holder_dict.get("pid") or 0)):
                os.remove(path_dict_in["lock"])
                continue
            raise SystemExit(f"another queue runner holds {path_dict_in['lock']} ({holder_dict or 'unreadable'})")
        os.write(lock_fd, payload_bytes)
        os.close(lock_fd)
        return
    raise SystemExit(f"could not take {path_dict_in['lock']}")


# FUNCTION: THE JUDGE COMMIT OF A NEW JOB
def get_judge_commit_str(git_func_in=None):
    """
    The commit Nicolas deployed: refs/deployed in the runner's clone, set by scripts/deploy_runner.ps1
    (SO_QUEUE_JUDGE_REF overrides the ref). It is a local ref, so a merge to main (and a fetch) never changes it.
    Everything except experiments/ in a run comes from this commit. It is resolved when the job starts and pinned in
    the job's running record, so the run, its retries and its crash resumes use the same judge.

    Args:
        git_func_in (callable | None): Injected git (tests)

    Returns:
        str: Full commit hash (NoDeployedJudgeError when the ref does not resolve)
    """
    # RESOLVE THE LOCAL REF; NO FETCH
    git_func = git_func_in or run_git_str
    ref_str = os.environ.get("SO_QUEUE_JUDGE_REF", "").strip() or DEPLOYED_REF_STR
    try:
        commit_str = git_func(["rev-parse", "--verify", "--quiet", f"{ref_str}^{{commit}}"]).strip()
    except subprocess.CalledProcessError:
        commit_str = ""
    if not COMMIT_PATTERN.match(commit_str):
        raise NoDeployedJudgeError(f"no deployed judge: {ref_str} does not resolve; deploy with scripts/deploy_runner.ps1 "
                                   f"(as so_runner) before jobs can start")
    return commit_str


# FUNCTION: THE DEPLOYED COMMIT FOR state.json
def get_deployed_commit_str(git_func_in=None):
    """
    Args:
        git_func_in (callable | None): Injected git (tests)

    Returns:
        str: The judge commit new jobs would get, or "" when nothing is deployed
    """
    # THE SAME RESOLUTION AS A CLAIM
    try:
        return get_judge_commit_str(git_func_in)
    except (ValueError, OSError):
        return ""


# FUNCTION: FETCH origin (A FAILURE IS A WARNING: LOCAL OBJECTS ARE USED)
def fetch_origin(git_func_in=None):
    """
    Args:
        git_func_in (callable | None): Injected git (tests)

    Returns:
        bool: True when the fetch worked
    """
    # PENDING JOBS NAME PUSHED COMMITS; THE RUNNER'S CLONE MUST HAVE THEM BEFORE VALIDATION
    git_func = git_func_in or run_git_str
    try:
        git_func(["fetch", "--quiet", "origin"])
        return True
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"warning: git fetch origin failed ({(getattr(error, 'output', '') or '').strip() or error}); "
              f"using local objects", flush=True)
        return False


# FUNCTION: THE COMMIT A RUN EXECUTES: THE JUDGE'S TREE WITH THE JOB'S experiments/ TREE
def make_composite_commit_str(judge_commit_str_in, design_commit_str_in, git_func_in=None):
    """
    Everything outside experiments/ is the judge commit's. experiments/ is the design commit's. The new commit has
    both as parents (so one ref keeps both alive), a fixed author and date (the same pair always gives the same hash,
    which a resumed run needs), and is checked out clean, so the run's own clean-tree check passes.

    A design commit that changes anything outside experiments/ (compared with where it branched from the judge), or
    holds a symlink or a submodule under experiments/, or has no experiments/ at all, is refused.

    Args:
        judge_commit_str_in (str): Judge commit
        design_commit_str_in (str): Job commit
        git_func_in (callable | None): Injected git; it must accept input_str_in and environment_dict_in

    Returns:
        str: The new commit's hash
    """
    # ONLY experiments/ MAY DIFFER FROM THE JUDGE
    git_func = git_func_in or run_git_str
    try:
        changed_list = git_func(["diff", "--name-only", "-z", f"{judge_commit_str_in}...{design_commit_str_in}"]).split("\0")
    except subprocess.CalledProcessError as error:
        raise ValueError(f"the job commit cannot be compared with the judge commit ({(error.output or '').strip()[:200]})")
    outside_list = sorted(path_str for path_str in changed_list if path_str.strip() and not path_str.startswith("experiments/"))
    if outside_list:
        raise ValueError("the job commit changes files outside experiments/ compared with the deployed judge "
                         f"{judge_commit_str_in[:8]} (core changes need a pull request; main commits that are not deployed "
                         "yet need scripts/deploy_runner.ps1 first): " + ", ".join(outside_list[:10])
                         + (" ..." if len(outside_list) > 10 else ""))
    # THE DESIGN SIDE: A TREE WITHOUT LINKS
    try:
        experiments_tree_str = git_func(["rev-parse", "--verify", f"{design_commit_str_in}:experiments"]).strip()
    except subprocess.CalledProcessError:
        raise ValueError("the job commit has no experiments/ folder")
    for line_str in git_func(["ls-tree", "-r", "-z", design_commit_str_in, "--", "experiments"]).split("\0"):
        if line_str.split(" ", 1)[0] in ("120000", "160000"):
            raise ValueError(f"experiments/ holds a symbolic link or a submodule: {line_str.split(chr(9), 1)[-1][:200]}")
    # THE JUDGE'S ROOT TREE WITH THE experiments ENTRY REPLACED
    # NUL-SEPARATED, NOT NEWLINE-SEPARATED: A TEXT-MODE PIPE ON WINDOWS TURNS "\n" INTO "\r\n" AND GIT WOULD READ
    # THE CARRIAGE RETURN AS PART OF EVERY ENTRY NAME
    entry_list = [line_str for line_str in git_func(["ls-tree", "-z", judge_commit_str_in]).split("\0")
                  if line_str.strip() and line_str.split("\t", 1)[-1] != "experiments"]
    entry_list.append(f"040000 tree {experiments_tree_str}\texperiments")
    tree_str = git_func(["mktree", "-z"], input_str_in="\0".join(entry_list) + "\0").strip()
    parent_list = [judge_commit_str_in] if judge_commit_str_in == design_commit_str_in else [judge_commit_str_in, design_commit_str_in]
    argument_list = ["commit-tree", tree_str]
    for parent_str in parent_list:
        argument_list += ["-p", parent_str]
    argument_list += ["-m", f"queue run commit\n\njudge {judge_commit_str_in}\ndesign {design_commit_str_in}"]
    return git_func(argument_list, environment_dict_in=COMPOSITE_ENVIRONMENT_DICT).strip()


# FUNCTION: A WORKTREE AT THE JOB'S COMMIT
def make_job_worktree_str(commit_str_in, run_id_str_in, git_func_in=None):
    """
    Fetches origin, checks that the commit exists, and adds a detached worktree. A leftover worktree of the same run
    id is removed first.

    Args:
        commit_str_in (str): Commit
        run_id_str_in (str): Run id (the folder name)
        git_func_in (callable | None): Injected git (tests)

    Returns:
        str: Worktree folder
    """
    # OUTSIDE THE DATA ROOT: DESIGN CODE MAY NOT OPEN FILES UNDER SO_DATA_PATH, AND IT IMPORTS FROM HERE
    git_func = git_func_in or run_git_str
    root_str = os.environ.get("SO_QUEUE_WORKTREE_ROOT", "").strip() or str(WORKSPACE_PATH / ".worktrees")
    worktree_str = os.path.join(root_str, run_id_str_in)
    try:
        git_func(["fetch", "--quiet", "origin"])
    except subprocess.CalledProcessError as error:
        print(f"warning: git fetch origin failed ({(error.output or '').strip() or error}); using local objects")
    try:
        git_func(["cat-file", "-e", f"{commit_str_in}^{{commit}}"])
    except subprocess.CalledProcessError:
        raise ValueError(f"commit {commit_str_in} is not in the runner's clone; push it to origin first")
    if os.path.isdir(worktree_str):
        remove_job_worktree(worktree_str, git_func)
    os.makedirs(root_str, exist_ok=True)
    git_func(["worktree", "add", "--detach", "--force", worktree_str, commit_str_in])
    return worktree_str


# FUNCTION: REMOVE A JOB WORKTREE
def remove_job_worktree(worktree_str_in, git_func_in=None):
    """
    Args:
        worktree_str_in (str): Worktree folder
        git_func_in (callable | None): Injected git (tests)

    Returns:
        None
    """
    # GIT FIRST, THEN THE FOLDER IF ANYTHING IS LEFT (__pycache__)
    git_func = git_func_in or run_git_str
    try:
        git_func(["worktree", "remove", "--force", worktree_str_in])
    except subprocess.CalledProcessError:
        pass
    shutil.rmtree(worktree_str_in, ignore_errors=True)
    try:
        git_func(["worktree", "prune"])
    except subprocess.CalledProcessError:
        pass


# FUNCTION: KILL A PROCESS AND ITS CHILDREN
def kill_process_tree(process_in):
    """
    Args:
        process_in (subprocess.Popen): The run

    Returns:
        None
    """
    # WINDOWS: taskkill /T; ELSEWHERE: THE PROCESS GROUP
    if os.name == "nt":
        subprocess.call(["taskkill", "/PID", str(process_in.pid), "/T", "/F"], stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL)
    else:
        import signal
        try:
            os.killpg(os.getpgid(process_in.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process_in.kill()
    process_in.wait()


# FUNCTION: RUN A COMMAND UNDER A TIME LIMIT, OUTPUT TO A LOG
def run_logged_command_dict(command_list_in, cwd_str_in, environment_dict_in, log_path_str_in, timeout_seconds_in,
                            header_str_in=""):
    """
    Args:
        command_list_in (list[str]): Command
        cwd_str_in (str): Working folder
        environment_dict_in (dict): Environment
        log_path_str_in (str): Log file (overwritten)
        timeout_seconds_in (float): Time limit
        header_str_in (str): Lines written before the output

    Returns:
        dict: return_code, timed_out_bool
    """
    # A NEW PROCESS GROUP SO A TIMEOUT KILLS EVERY CANDIDATE PROCESS TOO
    popen_kwarg_dict = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                        else {"start_new_session": True})
    with open(log_path_str_in, "w", encoding="utf-8") as log_file:
        log_file.write(header_str_in)
        log_file.flush()
        process = subprocess.Popen(command_list_in, cwd=cwd_str_in, stdout=log_file, stderr=subprocess.STDOUT,
                                   env=environment_dict_in, **popen_kwarg_dict)
        try:
            return {"return_code": int(process.wait(timeout=float(timeout_seconds_in))), "timed_out_bool": False}
        except subprocess.TimeoutExpired:
            kill_process_tree(process)
            log_file.write(f"\nTIMEOUT after {float(timeout_seconds_in) / 3600.0:.2f} hours; the process tree was killed\n")
            return {"return_code": -9, "timed_out_bool": True}


# FUNCTION: THE COMMIT OF A CLAIMED JOB'S RUN, KEPT BY A REF
def prepare_run_commit_str(job_dict_in, git_func_in=None):
    """
    Args:
        job_dict_in (dict): Claimed job (run_id, commit, judge_commit)
        git_func_in (callable | None): Injected git (tests)

    Returns:
        str: The run commit (ValueError when the job commit is refused); refs/runs/<run_id> points at it
    """
    # REFUSED HERE, BEFORE ANY PROCESS STARTS: THE JOB IS REJECTED, NOT FAILED
    git_func = git_func_in or run_git_str
    run_commit_str = make_composite_commit_str(job_dict_in["judge_commit"], job_dict_in["commit"], git_func)
    git_func(["update-ref", f"refs/runs/{job_dict_in['run_id']}", run_commit_str])
    return run_commit_str


# FUNCTION: RUN ONE DEVELOPMENT RUN: THE JUDGE FROM MAIN, THE DESIGN FROM THE JOB'S COMMIT
def run_development_process_dict(job_dict_in, run_id_str_in, log_path_str_in, git_func_in=None):
    """
    Args:
        job_dict_in (dict): Claimed job (design, commit, judge_commit, run_commit, note, n_jobs)
        run_id_str_in (str): Run id
        log_path_str_in (str): Log file
        git_func_in (callable | None): Injected git (tests)

    Returns:
        dict: return_code, log_line_list, timed_out_bool, run_commit
    """
    # THE WORKTREE AT THE RUN COMMIT; THE RUNNER'S PYTHON; A TIME LIMIT
    git_func = git_func_in or run_git_str
    if not job_dict_in.get("run_commit") or not job_dict_in.get("judge_commit"):
        raise ValueError("the job has no run commit or judge commit; it was not prepared by the runner")
    run_commit_str = job_dict_in["run_commit"]
    worktree_str = make_job_worktree_str(run_commit_str, run_id_str_in, git_func)
    timeout_seconds = float(os.environ.get("SO_QUEUE_JOB_TIMEOUT_HOURS", DEFAULT_JOB_TIMEOUT_HOURS)) * 3600.0
    python_str = os.environ.get("SO_QUEUE_PYTHON", "").strip() or sys.executable
    command_list = [python_str, "-u", os.path.join(worktree_str, "scripts", "run_development.py"), job_dict_in["design"],
                    "--note", job_dict_in.get("note", ""), "--run-id", run_id_str_in]
    if job_dict_in.get("n_jobs"):
        command_list += ["--n-jobs", str(int(job_dict_in["n_jobs"]))]
    environment_dict = dict(get_child_environment_dict(), PYTHONIOENCODING="utf-8", PYTHONPATH=worktree_str)
    # THE JUDGE BEFORE ANY DESIGN CODE RUNS: THE FRESH CHECKOUT OF THE RUN COMMIT, BEFORE THE CHILD STARTS
    from so.runner.judge_identity import get_judge_hash_dict
    judge_before_str = get_judge_hash_dict(worktree_str)["judge_hash"]
    header_str = (f"run commit {run_commit_str}\njudge commit {job_dict_in['judge_commit']}\n"
                  f"design commit {job_dict_in['commit']}\nworktree {worktree_str}\njudge hash before {judge_before_str}\n")
    judge_after_str = ""
    try:
        outcome_dict = run_logged_command_dict(command_list, worktree_str, environment_dict, log_path_str_in,
                                               timeout_seconds, header_str)
        # THE JUDGE AFTER THE RUN, FROM THE WORKTREE THE DESIGN CODE RAN IN
        try:
            judge_after_str = get_judge_hash_dict(worktree_str)["judge_hash"]
        except OSError as error:
            judge_after_str = f"unreadable ({type(error).__name__})"
    finally:
        remove_job_worktree(worktree_str, git_func)
    line_list = Path(log_path_str_in).read_text(encoding="utf-8", errors="replace").splitlines()
    return {"return_code": outcome_dict["return_code"], "log_line_list": line_list,
            "timed_out_bool": outcome_dict["timed_out_bool"], "run_commit": run_commit_str,
            "judge_hash_before": judge_before_str, "judge_hash_after": judge_after_str}


# FUNCTION: SEND AN EMAIL, OR WRITE IT TO THE OUTBOX
def send_email_dict(path_dict_in, run_id_str_in, subject_str_in, body_str_in, smtp_factory_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        run_id_str_in (str): Run id (outbox file name)
        subject_str_in (str): Subject
        body_str_in (str): Body
        smtp_factory_in (callable | None): smtplib.SMTP replacement (tests)

    Returns:
        dict: sent_bool, detail
    """
    # NO SETTINGS: THE OUTBOX
    host_str = os.environ.get("SO_SMTP_HOST", "").strip()
    to_str = os.environ.get("SO_EMAIL_TO", "").strip()
    os.makedirs(path_dict_in["outbox"], exist_ok=True)
    outbox_path_str = os.path.join(path_dict_in["outbox"], f"{run_id_str_in}.txt")
    if not host_str or not to_str:
        Path(outbox_path_str).write_text(f"Subject: {subject_str_in}\n\n{body_str_in}\n", encoding="utf-8")
        return {"sent_bool": False, "detail": f"no SMTP settings; written to {outbox_path_str}"}
    message = EmailMessage()
    message["Subject"] = subject_str_in
    message["From"] = os.environ.get("SO_SMTP_USER", to_str)
    message["To"] = to_str
    message.set_content(body_str_in)
    try:
        smtp_factory = smtp_factory_in or smtplib.SMTP
        with smtp_factory(host_str, int(os.environ.get("SO_SMTP_PORT", "587")), timeout=60) as smtp:
            smtp.starttls()
            if os.environ.get("SO_SMTP_USER"):
                smtp.login(os.environ["SO_SMTP_USER"], os.environ.get("SO_SMTP_PASSWORD", ""))
            smtp.send_message(message)
        return {"sent_bool": True, "detail": f"sent to {to_str}"}
    except Exception as error:
        Path(outbox_path_str).write_text(f"Subject: {subject_str_in}\n\n{body_str_in}\n", encoding="utf-8")
        return {"sent_bool": False, "detail": f"send failed ({type(error).__name__}: {error}); written to {outbox_path_str}"}


# FUNCTION: THE NUMBERS OF A FINISHED RUN FOR THE INDEX
def get_report_number_dict(path_dict_in, run_id_str_in):
    """
    Args:
        path_dict_in (dict): Queue paths
        run_id_str_in (str): Run id

    Returns:
        dict: strategy_total_return, buy_hold_total_return, design_count, judge_hash (empty strings when absent)
    """
    # report.json HOLDS EVERY NUMBER BEHIND THE VERDICT
    report_path_str = os.path.join(path_dict_in["runs"], run_id_str_in, "report.json")
    if not os.path.isfile(report_path_str):
        return {"strategy_total_return": "", "buy_hold_total_return": "", "design_count": "", "judge_hash": ""}
    report_dict = read_json(report_path_str)
    return_dict = report_dict.get("return_dict") or {}
    return {"strategy_total_return": return_dict.get("strategy_total_return", ""),
            "buy_hold_total_return": return_dict.get("buy_hold_total_return", ""),
            "design_count": (report_dict.get("multiple_testing_dict") or {}).get("design_count", ""),
            "judge_hash": report_dict.get("judge_hash_str", "")}


# FUNCTION: APPEND ONE ROW TO run_index.csv
def append_run_index_row(path_dict_in, result_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths
        result_dict_in (dict): A job's result

    Returns:
        int: Rows appended
    """
    # ONE ROW PER JOB ATTEMPT, UNDER THE CSV LOCK
    import pandas as pd
    verdict_dict = result_dict_in.get("verdict") or {}
    row_dict = {"run_id": result_dict_in["run_id"], "attempt": int(result_dict_in.get("attempt") or 1),
                "job_id": result_dict_in["job_id"], "design": result_dict_in["design"],
                "commit": result_dict_in.get("commit") or "", "judge_commit": result_dict_in.get("judge_commit") or "",
                "run_commit": result_dict_in.get("run_commit") or "", "note": result_dict_in.get("note", ""),
                "status": result_dict_in["status"], "return_code": result_dict_in.get("return_code", ""),
                "verdict_label": verdict_dict.get("label", ""), "email_worthy": verdict_dict.get("email_worthy", ""),
                "failed_list": ";".join(verdict_dict.get("failed_list") or []),
                "look_ahead": verdict_dict.get("look_ahead", ""), "added_by": result_dict_in.get("added_by", ""),
                "added_ts": result_dict_in.get("added_ts", ""), "finished_ts": result_dict_in.get("finished_ts", ""),
                **get_report_number_dict(path_dict_in, result_dict_in["run_id"])}
    return append_csv_record_pdf(pd.DataFrame([row_dict]), path_dict_in["run_index"], RUN_INDEX_COLUMN_LIST)


# FUNCTION: A NUMBER AS A PERCENT FOR THE EMAIL
def get_percent_str(value_in):
    """
    Args:
        value_in (object): A fraction, or "" / None when the report has none

    Returns:
        str: "+12.34%", or "n/a"
    """
    # THE INDEX HOLDS EMPTY STRINGS WHEN A NUMBER IS MISSING
    try:
        return f"{float(value_in):+.2%}"
    except (TypeError, ValueError):
        return "n/a"


# FUNCTION: THE TRIAL LOG'S SHARE OF N FOR THE EMAIL ("" WHEN THE REPORT HAS NONE)
def get_trial_log_count_email_str(path_dict_in, run_id_str_in):
    """
    Args:
        path_dict_in (dict): Queue paths
        run_id_str_in (str): Run id

    Returns:
        str: " (pilot included; ... in the trial log)" or ""
    """
    # report.json HOLDS IT; N HAS COUNTED THE PILOT DESIGNS SINCE 2026-11-10
    try:
        report_dict = read_json(os.path.join(path_dict_in["runs"], run_id_str_in, "report.json"))
    except (OSError, ValueError):
        return ""
    multiple_dict = report_dict.get("multiple_testing_dict") or {}
    if multiple_dict.get("design_count_scope_str") != "pilot_included":
        return ""
    return f" (pilot included; {multiple_dict.get('current_design_count', 'n/a')} in the trial log)"


# FUNCTION: THE EMAIL OF A FINISHED RUN (ONE PER FULL RUN, POSITIVE OR NEGATIVE)
def get_finished_run_email_tuple(path_dict_in, result_dict_in, manifest_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths
        result_dict_in (dict): The job's result (run_id, design, commit, judge_commit, run_commit, note, results_row, log)
        manifest_dict_in (dict): The run's manifest (verdict)

    Returns:
        tuple[str, str]: Subject and body
    """
    # THE VERDICT COMES FROM THE MANIFEST, THE NUMBERS FROM report.json
    verdict_dict = manifest_dict_in.get("verdict") or {}
    number_dict = get_report_number_dict(path_dict_in, result_dict_in["run_id"])
    design_name_str = Path(result_dict_in["design"]).name
    label_str = re.sub(r"[\x00-\x1f\x7f]+", " ", str(verdict_dict.get("label", ""))).strip()[:80]
    passed_bool = bool(verdict_dict.get("email_worthy"))
    subject_str = (f"Stock Overflow: PASS, audit pending - {design_name_str}" if passed_bool
                   else f"Stock Overflow: {design_name_str} - {label_str or 'finished'}")
    failed_list = verdict_dict.get("failed_list") or []
    line_list = [f"Run {result_dict_in['run_id']}", f"Design {result_dict_in['design']}",
                 f"Note {result_dict_in.get('note', '')}", f"Verdict {label_str}",
                 f"Failed parts {', '.join(failed_list) if failed_list else 'none'}",
                 f"Look-ahead check {verdict_dict.get('look_ahead', '')}",
                 f"Total return {get_percent_str(number_dict['strategy_total_return'])} vs buy-and-hold "
                 f"{get_percent_str(number_dict['buy_hold_total_return'])}",
                 f"Grade (what the planner sees) {verdict_dict.get('grade') or 'n/a'} "
                 f"({verdict_dict.get('grade_reason_code') or 'no reason code'})",
                 f"Designs tried (the multiple-testing N) {number_dict['design_count'] or 'n/a'}"
                 f"{get_trial_log_count_email_str(path_dict_in, result_dict_in['run_id'])}",
                 f"Judge hash {str(number_dict['judge_hash'])[:16] or 'n/a'}",
                 f"Commits: design {result_dict_in.get('commit')}, judge {result_dict_in.get('judge_commit')}, "
                 f"run {result_dict_in.get('run_commit')}",
                 f"Report {os.path.join(path_dict_in['runs'], result_dict_in['run_id'], 'report.md')}",
                 f"Log {result_dict_in.get('log')}", f"Results row {result_dict_in.get('results_row')}"]
    if passed_bool:
        line_list += ["", "This run passed every part of the verdict. No auditor exists yet, so nothing vetoed it. "
                          "Treat it as a candidate: the design is evaluated on data the system has not seen "
                          "(docs/AGENTIC_DESIGN.md, section 11). The language is 'not rejected', not 'proven'."]
    return subject_str, "\n".join(line_list) + "\n"


# FUNCTION: TAKE A JOB OUT OF pending/ INTO running/
def claim_job_dict(path_dict_in, job_dict_in, judge_func_in=None, now_in=None):
    """
    The claim fixes the run id and the judge commit, and writes them to running/ before the pending file goes, so a
    crash at any point leaves the job in one place or both, never none.

    Args:
        path_dict_in (dict): Queue paths
        job_dict_in (dict): A validated job
        judge_func_in (callable | None): () -> judge commit hash (tests)
        now_in (datetime.datetime | None): Clock (tests)

    Returns:
        dict: The claimed job (run_id, judge_commit, claimed_ts, resume_count)
    """
    # A RETRY KEEPS ITS RUN ID AND ITS JUDGE; A NEW JOB GETS A RUN ID AND THE CURRENT JUDGE
    now = now_in or datetime.datetime.now()
    judge_commit_str = job_dict_in.get("judge_commit") or (judge_func_in or get_judge_commit_str)()
    run_id_str = job_dict_in.get("run_id") or f"{Path(job_dict_in['design']).name}_{now.strftime('%Y%m%d%H%M%S%f')}"
    claimed_dict = {**job_dict_in, "run_id": run_id_str, "judge_commit": judge_commit_str,
                    "claimed_ts": now.isoformat(timespec="seconds"), "resume_count": 0}
    os.makedirs(path_dict_in["running"], exist_ok=True)
    write_json_atomic(os.path.join(path_dict_in["running"], f"{claimed_dict['job_id']}.json"), claimed_dict)
    pending_str = os.path.join(path_dict_in["pending"], f"{claimed_dict['job_id']}.json")
    if os.path.isfile(pending_str):
        os.remove(pending_str)
    return claimed_dict


# FUNCTION: JOBS A CRASH OR A REBOOT LEFT IN running/
def recover_running_job_list(path_dict_in, now_in=None):
    """
    Called with the runner lock held, so a file in running/ belongs to a runner that is gone. The job keeps its run id
    and its judge commit; the attempt number and the resume count go up. The caller runs these first.

    Args:
        path_dict_in (dict): Queue paths
        now_in (datetime.datetime | None): Clock (tests)

    Returns:
        list[dict]: Jobs to run again, oldest first
    """
    # A FILE THAT FAILS THE CHECKS IS REJECTED, NOT RUN
    now = now_in or datetime.datetime.now()
    job_list = []
    if not os.path.isdir(path_dict_in["running"]):
        return job_list
    for name_str in sorted(os.listdir(path_dict_in["running"])):
        file_str = os.path.join(path_dict_in["running"], name_str)
        if not name_str.endswith(".json") or not os.path.isfile(file_str):
            continue
        try:
            raw_dict = read_json(file_str)
            job_dict = get_clean_job_dict({key_str: raw_dict.get(key_str) for key_str in JOB_FIELD_LIST}, name_str[:-5])
            if job_dict["run_id"] is None or job_dict["judge_commit"] is None:
                raise ValueError("the claim has no run id or judge commit")
        except (ValueError, OSError, AttributeError) as error:
            os.makedirs(path_dict_in["rejected"], exist_ok=True)
            write_json_atomic(os.path.join(path_dict_in["rejected"], f"claim_{re.sub(r'[^A-Za-z0-9_.-]', '_', name_str)[:100]}"),
                              {"rejected_ts": now.isoformat(timespec="seconds"), "reason": f"unusable claim: {error}"})
            os.remove(file_str)
            write_status_dict(path_dict_in, {"job_id": name_str[:-5]}, "rejected", now, reason_str_in=f"unusable claim: {error}")
            continue
        job_dict["resume_count"] = int(raw_dict.get("resume_count") or 0) + 1
        job_dict["attempt"] = job_dict["attempt"] + 1
        job_dict["claimed_ts"] = now.isoformat(timespec="seconds")
        write_json_atomic(file_str, job_dict)
        pending_str = os.path.join(path_dict_in["pending"], name_str)
        if os.path.isfile(pending_str):
            os.remove(pending_str)
        job_list.append(job_dict)
    return job_list


# FUNCTION: A RUN FUNCTION THAT GIVES UP ON A JOB INTERRUPTED TOO OFTEN
def get_give_up_run_func(resume_count_int_in):
    """
    Args:
        resume_count_int_in (int): How often the job was interrupted

    Returns:
        callable: (job, run_id, log path) -> a failed process result, so the usual filing, index row and email follow
    """
    # NO PROCESS IS STARTED
    def run_func(job_dict_in, run_id_str_in, log_path_str_in):
        message_str = f"gave up: the runner was interrupted {resume_count_int_in} times while this job ran"
        Path(log_path_str_in).write_text(message_str + "\n", encoding="utf-8")
        return {"return_code": -2, "log_line_list": [message_str], "timed_out_bool": False, "gave_up_bool": True}
    return run_func


# FUNCTION: BRING run_index.csv TO THE CURRENT COLUMNS
def upgrade_run_index_file(path_dict_in):
    """
    The append refuses a file whose header differs from RUN_INDEX_COLUMN_LIST, so a column added to the list would
    stop every append to an index written before. When the stored header only lacks columns of the list (or has them in
    another order), the file is rewritten with the current header, the new columns empty, after a copy of the old file
    named run_index.csv.before_<timestamp>. Any other difference is left alone (the append then refuses and says so).

    Args:
        path_dict_in (dict): Queue paths

    Returns:
        bool: True when the file was rewritten
    """
    # NOTHING TO DO FOR A MISSING, EMPTY OR CURRENT FILE
    import pandas as pd
    index_str = path_dict_in["run_index"]
    if not os.path.isfile(index_str) or os.path.getsize(index_str) == 0:
        return False
    with open(index_str, encoding="utf-8", newline="") as file_obj:
        header_str = file_obj.readline().rstrip("\r\n")
    if header_str.split(",") == RUN_INDEX_COLUMN_LIST:
        return False
    if not set(header_str.split(",")) <= set(RUN_INDEX_COLUMN_LIST):
        print(f"warning: {index_str} has columns that are not in the current list; left unchanged")
        return False
    # COPY, THEN REWRITE THROUGH A TEMPORARY FILE
    index_pdf = pd.read_csv(index_str, dtype=str, keep_default_na=False)
    shutil.copy2(index_str, f"{index_str}.before_{datetime.datetime.now():%Y%m%d%H%M%S}")
    temp_str = f"{index_str}.{os.getpid()}.tmp"
    index_pdf.reindex(columns=RUN_INDEX_COLUMN_LIST, fill_value="").to_csv(temp_str, index=False, encoding="utf-8", lineterminator="\n")
    os.replace(temp_str, index_str)
    return True


# FUNCTION: WHAT IS WRONG WITH THE JUDGE OF A FINISHED RUN ("" WHEN NOTHING)
def get_judge_problem_str(process_dict_in, report_judge_hash_str_in):
    """
    Args:
        process_dict_in (dict): The run function's result (judge_hash_before / judge_hash_after when measured)
        report_judge_hash_str_in (str): judge_hash_str of report.json ("" when there is no report)

    Returns:
        str: A reason when the judge changed during the run, else ""
    """
    # NOT MEASURED (TEST FAKES, A RUN THAT NEVER STARTED): NOTHING TO COMPARE
    before_str = str(process_dict_in.get("judge_hash_before") or "")
    if not before_str:
        return ""
    after_str = str(process_dict_in.get("judge_hash_after") or "")
    if after_str and after_str != before_str:
        return f"judge changed during the run: worktree judge {after_str[:16]} != run commit judge {before_str[:16]}"
    if report_judge_hash_str_in and str(report_judge_hash_str_in) != before_str:
        return (f"judge changed during the run: report judge {str(report_judge_hash_str_in)[:16]} != run commit judge "
                f"{before_str[:16]}")
    return ""


# FUNCTION: RUN ONE JOB AND FILE ITS RESULT
def run_job_dict(path_dict_in, job_dict_in, run_func_in=None, send_func_in=None, now_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        job_dict_in (dict): Job
        run_func_in (callable | None): (job, run_id, log path) -> {return_code, log_line_list} (tests)
        send_func_in (callable | None): (paths, run_id, subject, body) -> {sent_bool, detail} (tests)
        now_in (datetime.datetime | None): Clock (tests)

    Returns:
        dict: The job's result (also written to done/ or failed/, run_index.csv and state.json)
    """
    # A RETRY KEEPS ITS RUN ID; A NEW JOB GETS ONE
    now = now_in or datetime.datetime.now()
    run_id_str = job_dict_in.get("run_id") or f"{Path(job_dict_in['design']).name}_{now.strftime('%Y%m%d%H%M%S%f')}"
    os.makedirs(path_dict_in["logs"], exist_ok=True)
    log_path_str = os.path.join(path_dict_in["logs"], f"{run_id_str}_attempt{int(job_dict_in.get('attempt') or 1)}.log")
    running_dict = {**job_dict_in, "run_id": run_id_str, "started_ts": now.isoformat(timespec="seconds")}
    write_state_dict(path_dict_in, running_dict)
    try:
        with Heartbeat(path_dict_in, running_dict):
            process_dict = (run_func_in or run_development_process_dict)({**job_dict_in, "run_id": run_id_str}, run_id_str, log_path_str)
    except Exception as error:
        Path(log_path_str).write_text(f"{type(error).__name__}: {error}\n", encoding="utf-8")
        process_dict = {"return_code": -1, "log_line_list": [f"{type(error).__name__}: {error}"], "timed_out_bool": False}
    manifest_path_str = os.path.join(path_dict_in["runs"], run_id_str, "manifest.json")
    manifest_dict = read_json(manifest_path_str) if os.path.isfile(manifest_path_str) else None
    row_list = [line_str[len("results_row "):] for line_str in process_dict["log_line_list"] if line_str.startswith("results_row ")]
    ok_bool = process_dict["return_code"] == 0 and manifest_dict is not None
    # THE JUDGE MUST BE THE SAME BEFORE THE RUN, IN THE REPORT AND AFTER THE RUN (ONLY WHEN THE PROCESS MEASURED IT)
    judge_problem_str = get_judge_problem_str(process_dict, get_report_number_dict(path_dict_in, run_id_str)["judge_hash"]
                                              if ok_bool else "")
    if judge_problem_str:
        ok_bool = False
        process_dict = {**process_dict, "log_line_list": list(process_dict["log_line_list"]) + [judge_problem_str]}
        with open(log_path_str, "a", encoding="utf-8") as log_file:
            log_file.write(f"\n{judge_problem_str}\n")
    status_str = "done" if ok_bool else ("timeout" if process_dict.get("timed_out_bool") else "failed")
    result_dict = {**job_dict_in, "run_id": run_id_str, "finished_ts": datetime.datetime.now().isoformat(timespec="seconds"),
                   "status": status_str, "return_code": process_dict["return_code"], "log": log_path_str,
                   "results_row": row_list[-1] if row_list else None, "verdict": (manifest_dict or {}).get("verdict"),
                   "run_commit": process_dict.get("run_commit") or job_dict_in.get("run_commit"), "email": None,
                   "judge_hash_before": process_dict.get("judge_hash_before"),
                   "judge_hash_after": process_dict.get("judge_hash_after"), "judge_problem": judge_problem_str or None}
    send_func = send_func_in or send_email_dict
    if not ok_bool:
        result_dict["log_tail"] = process_dict["log_line_list"][-FAILED_TAIL_LINE_COUNT_INT:]
        subject_str = f"Stock Overflow: {Path(job_dict_in['design']).name} run {status_str}"
        body_str = (f"Run {run_id_str}\nJob {job_dict_in['job_id']}\nCommit {job_dict_in.get('commit')}\n"
                    f"Log {log_path_str}\n\nLast lines:\n" + "\n".join(result_dict["log_tail"]) +
                    f"\n\nRetry: python scripts/run_queue.py retry {job_dict_in['job_id']}\n")
        result_dict["email"] = send_func(path_dict_in, run_id_str, subject_str, body_str)
    else:
        subject_str, body_str = get_finished_run_email_tuple(path_dict_in, result_dict, manifest_dict)
        result_dict["email"] = send_func(path_dict_in, run_id_str, subject_str, body_str)
    target_folder_str = path_dict_in["done"] if ok_bool else path_dict_in["failed"]
    os.makedirs(target_folder_str, exist_ok=True)
    write_json_atomic(os.path.join(target_folder_str, f"{job_dict_in['job_id']}.json"), result_dict)
    append_run_index_row(path_dict_in, result_dict)
    # WHAT AGENTS SEE (ROADMAP R4): THE GRADE (PLANNER) AND THE TECHNICAL STATUS (CODER), BOTH WITHOUT NUMBERS
    write_agent_view_dict(path_dict_in, result_dict, process_dict)
    # THE JOB IS FILED: THE CLAIM AND ANY LEFTOVER PENDING FILE GO
    for folder_key_str in ["running", "pending"]:
        leftover_str = os.path.join(path_dict_in[folder_key_str], f"{job_dict_in['job_id']}.json")
        if os.path.isfile(leftover_str):
            os.remove(leftover_str)
    write_state_dict(path_dict_in, None, result_dict)
    return result_dict


# FUNCTION: THE GRADE AND THE TECHNICAL STATUS OF A FILED JOB
def write_agent_view_dict(path_dict_in, result_dict_in, process_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths
        result_dict_in (dict): The job's result (as filed in done/ or failed/)
        process_dict_in (dict): The run function's result (log lines, gave_up_bool)

    Returns:
        dict: grade_path_str, status_path_str, grade_dict
    """
    # THE GRADE MODULE IS IMPORTED HERE: so.runner PULLS IN THE RUNNER'S PACKAGES, WHICH add AND status DO NOT NEED
    from so.runner.grade import get_queue_grade_dict
    status_str = result_dict_in["status"]
    verdict_dict = result_dict_in.get("verdict") or {}
    grade_dict = get_queue_grade_dict(status_str, verdict_dict, result_dict_in.get("judge_problem") or "",
                                      bool(process_dict_in.get("gave_up_bool")))
    grade_path_str = write_grade_dict(path_dict_in, result_dict_in, grade_dict)
    keep_list = [result_dict_in.get(name_str) for name_str in ["job_id", "run_id", "design", "commit", "judge_commit", "run_commit"]]
    if status_str == "done":
        status_path_str = write_status_dict(path_dict_in, result_dict_in, "done",
                                            look_ahead_str_in=str(verdict_dict.get("look_ahead") or "pending"))
    elif result_dict_in.get("judge_problem"):
        status_path_str = write_status_dict(path_dict_in, result_dict_in, status_str,
                                            reason_str_in="the judge changed during the run; the run was not scored")
    elif process_dict_in.get("gave_up_bool"):
        status_path_str = write_status_dict(path_dict_in, result_dict_in, status_str,
                                            reason_str_in="the runner was interrupted too often while this job ran")
    else:
        status_path_str = write_status_dict(path_dict_in, result_dict_in, status_str,
                                            error_dict_in=get_error_summary_dict(process_dict_in.get("log_line_list"), keep_list),
                                            reason_str_in="time limit exceeded" if status_str == "timeout" else None)
    return {"grade_path_str": grade_path_str, "status_path_str": status_path_str, "grade_dict": grade_dict}


# FUNCTION: WHETHER THE QUEUE HAS ANYTHING TO DO
def get_has_work_bool(path_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths

    Returns:
        bool: True when pending/ or running/ holds a file
    """
    # A FILE IN running/ IS A JOB A CRASH LEFT BEHIND
    for key_str in ["pending", "running"]:
        if os.path.isdir(path_dict_in[key_str]) and any(name_str.endswith(".json") for name_str in os.listdir(path_dict_in[key_str])):
            return True
    return False


# FUNCTION: RUN EVERY PENDING JOB UNDER THE LOCK
def run_queue_list(path_dict_in, run_func_in=None, send_func_in=None, pid_alive_func_in=None, judge_func_in=None,
                   git_func_in=None, prepare_func_in=None):
    """
    Jobs interrupted by a crash or reboot are resumed first (same run id, same judge commit). Then the oldest valid
    pending job is claimed, its run commit is made, and it runs. Jobs added while the runner works are picked up
    before it exits. A job whose commit is refused is rejected, not failed, and nothing is emailed.

    Args:
        path_dict_in (dict): Queue paths
        run_func_in, send_func_in (callable | None): Replacements (tests)
        pid_alive_func_in (callable | None): Replacement for the stale-lock check (tests)
        judge_func_in (callable | None): () -> judge commit (tests)
        git_func_in (callable | None): Injected git for the validation (tests)
        prepare_func_in (callable | None): job -> run commit (tests)

    Returns:
        list[dict]: Results in run order
    """
    # THE RUNNER'S FOLDERS, THE LOCK, THE INDEX COLUMNS, THEN THE JOBS
    make_runner_folder_list(path_dict_in)
    acquire_runner_lock(path_dict_in, pid_alive_func_in)
    result_list = []
    prepare_func = prepare_func_in or (lambda job_in: prepare_run_commit_str(job_in, git_func_in))

    def run_one_func(job_in):
        # THE RUN COMMIT FIRST: A REFUSED COMMIT IS A REJECTED JOB
        try:
            job_in = {**job_in, "run_commit": prepare_func(job_in)}
        except (ValueError, OSError, subprocess.SubprocessError) as error:
            reject_pending_file(path_dict_in, f"{job_in['job_id']}.json", job_in, str(error), source_key_str_in="running")
            print(f"rejected {job_in['job_id']}: {error}", flush=True)
            return
        resume_count_int = int(job_in.get("resume_count") or 0)
        give_up_bool = resume_count_int > MAX_RESUME_COUNT_INT
        print(f"start {job_in['job_id']} {datetime.datetime.now():%H:%M:%S}" + (f" (resumed, interruption {resume_count_int})" if resume_count_int else ""), flush=True)
        result_dict = run_job_dict(path_dict_in, job_in, get_give_up_run_func(resume_count_int) if give_up_bool else run_func_in, send_func_in)
        # NO RESULTS ROW ON THE CONSOLE (IT HOLDS RETURNS); THE GRADE FILE AND THE EMAIL CARRY THE OUTCOME
        print(f"{result_dict['status']} {job_in['job_id']} run {result_dict['run_id']}", flush=True)
        result_list.append(result_dict)

    try:
        upgrade_run_index_file(path_dict_in)
        # THE KILL SWITCH AND THE WINDOWS UPDATE GUARD ARE CHECKED BEFORE EVERY JOB; A RECOVERED JOB STAYS IN running/
        # UNTIL BOTH ALLOW IT
        guard_dict = get_checked_update_guard_dict()
        if not get_stop_flag_bool(path_dict_in) and guard_dict["safe_bool"]:
            for job_dict in recover_running_job_list(path_dict_in):
                run_one_func(job_dict)
        # NEW COMMITS FIRST, SO A PENDING JOB THAT NAMES A JUST-PUSHED COMMIT IS NOT REJECTED AS MISSING
        fetch_origin(git_func_in)
        while True:
            if get_stop_flag_bool(path_dict_in):
                print(f"stop flag set ({path_dict_in['stop_flag']}); no further job is started", flush=True)
                break
            guard_dict = get_checked_update_guard_dict()
            if not guard_dict["safe_bool"]:
                print(f"Windows Update guard: {guard_dict['reason_str']}; no further job is started", flush=True)
                break
            # THE JUDGE OF THE NEXT JOB: THE DEPLOYED COMMIT NOW (A DEPLOY BETWEEN JOBS APPLIES TO THE NEXT ONE)
            try:
                judge_commit_str = (judge_func_in or get_judge_commit_str)()
            except NoDeployedJudgeError as error:
                print(f"{error}; pending jobs wait", flush=True)
                break
            job_dict = get_next_job_dict(path_dict_in, git_func_in)
            if job_dict is None:
                break
            run_one_func(claim_job_dict(path_dict_in, job_dict, lambda: judge_commit_str))
    finally:
        write_state_dict(path_dict_in, None)
        os.remove(path_dict_in["lock"])
    return result_list


# FUNCTION: RUN JOBS AS THEY ARRIVE
def watch_queue(path_dict_in, interval_seconds_in=DEFAULT_WATCH_INTERVAL_SECONDS, max_loop_count_in=None,
                run_func_in=None, send_func_in=None, judge_func_in=None, git_func_in=None, prepare_func_in=None,
                guard_send_func_in=None):
    """
    The runner account's scheduled task. Each loop runs every pending job (and any job a crash left in running/), or
    writes a heartbeat to state.json. While the Windows Update guard is not safe and jobs wait, it prints the reason and
    emails once per reason (guard_send_func_in replaces send_email_dict in tests).

    Args:
        path_dict_in (dict): Queue paths
        interval_seconds_in (float): Pause between loops
        max_loop_count_in (int | None): Stop after this many loops (tests; None = forever)
        run_func_in, send_func_in (callable | None): Replacements (tests)
        judge_func_in, git_func_in, prepare_func_in (callable | None): Replacements (tests)
        guard_send_func_in (callable | None): (path_dict, name, subject, body) -> dict (tests)

    Returns:
        int: Jobs run
    """
    # A JOB THAT FAILS DOES NOT STOP THE WATCH
    job_count_int, loop_count_int = 0, 0
    guard_reason_sent_str = None
    while max_loop_count_in is None or loop_count_int < int(max_loop_count_in):
        # ONE FAILED LOOP (A LOCKED FILE, A GIT ERROR) IS LOGGED AND THE WATCH GOES ON; A SECOND RUNNER STILL EXITS
        try:
            has_work_bool = get_has_work_bool(path_dict_in)
            guard_dict = get_checked_update_guard_dict()
            if has_work_bool and not get_stop_flag_bool(path_dict_in) and not guard_dict["safe_bool"]:
                # JOBS WAIT FOR THE WINDOWS UPDATE GUARD: SAY WHY ONCE PER REASON (THE DAYS LEFT ARE NOT PART OF IT)
                reason_key_str = re.sub(r"\(\d+(\.\d+)? days.*\)$", "", guard_dict["reason_str"])
                if reason_key_str != guard_reason_sent_str:
                    print(f"Windows Update guard: {guard_dict['reason_str']}; jobs wait", flush=True)
                    stamp_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                    (guard_send_func_in or send_email_dict)(
                        path_dict_in, f"update_guard_{stamp_str}", "Stock Overflow: jobs wait (Windows Update guard)",
                        f"The runner on {socket.gethostname()} starts no job: {guard_dict['reason_str']}.\n"
                        "Renew the pause (Settings > Windows Update > Pause updates > Pick a date), or install the updates "
                        "and restart with STOP set, then pause again. The jobs start by themselves once the guard is safe.\n")
                    guard_reason_sent_str = reason_key_str
                make_runner_folder_list(path_dict_in)
                write_state_dict(path_dict_in, None)
            elif has_work_bool and not get_stop_flag_bool(path_dict_in):
                guard_reason_sent_str = None
                job_count_int += len(run_queue_list(path_dict_in, run_func_in, send_func_in, judge_func_in=judge_func_in,
                                                    git_func_in=git_func_in, prepare_func_in=prepare_func_in))
            else:
                make_runner_folder_list(path_dict_in)
                write_state_dict(path_dict_in, None)
        except Exception as error:
            print(f"warning: watch loop failed ({type(error).__name__}: {error}); retrying after the pause", flush=True)
        loop_count_int += 1
        if max_loop_count_in is None or loop_count_int < int(max_loop_count_in):
            time.sleep(float(interval_seconds_in))
    return job_count_int


# THE WATCH'S OWN LOG (ROADMAP R7, DECIDED 2026-11-05): queue/logs/runner_watch.log, ROTATED TO .1 PAST 5 MB
WATCH_LOG_FILE_STR = "runner_watch.log"
WATCH_LOG_MAX_BYTES = 5 * 1024 * 1024


# CLASS: A STREAM THAT ALSO WRITES TIME-STAMPED LINES TO THE WATCH LOG
class WatchLogTee:
    """
    Wraps stdout or stderr. Every complete line goes to the original stream unchanged and to the log with a time
    stamp. Past max_bytes_in the log is renamed to .1 (one old copy kept) and a new log starts. A log that cannot be
    written never stops the watch: the line still reaches the original stream.
    """

    # FUNCTION: OPEN THE LOG
    def __init__(self, stream_in, log_path_str_in, max_bytes_in=WATCH_LOG_MAX_BYTES, lock_in=None):
        self.stream = stream_in
        self.log_path_str = str(log_path_str_in)
        self.max_bytes = int(max_bytes_in)
        self.lock = lock_in or threading.Lock()
        self.pending_str = ""

    # FUNCTION: WRITE TEXT (THE LOG GETS WHOLE LINES)
    def write(self, text_in):
        text_str = str(text_in)
        if self.stream is not None:
            try:
                self.stream.write(text_str)
            except (OSError, ValueError):
                pass
        with self.lock:
            self.pending_str += text_str
            if "\n" not in self.pending_str:
                return len(text_str)
            line_list = self.pending_str.split("\n")
            self.pending_str = line_list.pop()
            self.write_log_line_list(line_list)
        return len(text_str)

    # FUNCTION: APPEND STAMPED LINES, ROTATING FIRST WHEN THE LOG IS FULL
    def write_log_line_list(self, line_list_in):
        stamp_str = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            if os.path.isfile(self.log_path_str) and os.path.getsize(self.log_path_str) >= self.max_bytes:
                os.replace(self.log_path_str, self.log_path_str + ".1")
            with open(self.log_path_str, "a", encoding="utf-8") as log_file:
                log_file.write("".join(f"{stamp_str} {line_str}\n" for line_str in line_list_in))
        except OSError:
            pass

    # FUNCTION: FLUSH THE ORIGINAL STREAM
    def flush(self):
        if self.stream is not None:
            try:
                self.stream.flush()
            except (OSError, ValueError):
                pass


# FUNCTION: SEND THE WATCH'S STDOUT AND STDERR TO THE WATCH LOG AS WELL
def start_watch_log(path_dict_in, max_bytes_in=WATCH_LOG_MAX_BYTES):
    """
    Args:
        path_dict_in (dict): Queue paths (the log goes in logs/)
        max_bytes_in (int): Rotation size

    Returns:
        str: Log path
    """
    # ONE LOCK FOR BOTH STREAMS SO LINES DO NOT INTERLEAVE
    os.makedirs(path_dict_in["logs"], exist_ok=True)
    log_path_str = os.path.join(path_dict_in["logs"], WATCH_LOG_FILE_STR)
    lock = threading.Lock()
    sys.stdout = WatchLogTee(sys.stdout, log_path_str, max_bytes_in, lock)
    sys.stderr = WatchLogTee(sys.stderr, log_path_str, max_bytes_in, lock)
    print(f"watch started: pid {os.getpid()}", flush=True)
    return log_path_str


# PARSE THE COMMAND
if __name__ == "__main__":
    # THE COMMANDS
    parser = argparse.ArgumentParser(description="Development run queue (one run at a time, at the job's commit).")
    sub_parser = parser.add_subparsers(dest="command", required=True)
    add_parser = sub_parser.add_parser("add", help="Add one job at the current (or a named) commit")
    add_parser.add_argument("design", help="Experiment folder")
    add_parser.add_argument("--note", default="", help="Trial-row note")
    add_parser.add_argument("--n-jobs", type=int, default=None, help="Candidate processes")
    add_parser.add_argument("--commit", default=None, help="Commit to run (default: this clone's HEAD, which must be clean)")
    retry_parser = sub_parser.add_parser("retry", help="Queue a failed job again under the same run id")
    retry_parser.add_argument("job_id", help="Job id of a crashed or timed-out job (visible/status/)")
    sub_parser.add_parser("run", help="Run every pending job, then exit (runner account)")
    watch_parser = sub_parser.add_parser("watch", help="Run jobs as they arrive (runner account)")
    watch_parser.add_argument("--interval", type=float, default=DEFAULT_WATCH_INTERVAL_SECONDS, help="Seconds between looks")
    sub_parser.add_parser("status", help="Print state.json")
    sub_parser.add_parser("test-email", help="Send one test email with this account's SMTP settings (runner account)")
    arg_dict = parser.parse_args()
    path_dict = get_queue_path_dict()
    if arg_dict.command == "add":
        print(json.dumps(add_job_dict(path_dict, arg_dict.design, arg_dict.note, arg_dict.n_jobs,
                                      commit_str_in=arg_dict.commit), indent=2))
    elif arg_dict.command == "retry":
        print(json.dumps(add_retry_job_dict(path_dict, arg_dict.job_id), indent=2))
    elif arg_dict.command == "run":
        result_list = run_queue_list(path_dict)
        print(f"\n===== queue: {len(result_list)} job(s) =====")
        for result_dict in result_list:
            print(f"{result_dict['job_id']} {result_dict['status']}: run {result_dict['run_id']}")
    elif arg_dict.command == "watch":
        start_watch_log(path_dict)
        watch_queue(path_dict, arg_dict.interval)
    elif arg_dict.command == "test-email":
        make_runner_folder_list(path_dict)
        stamp_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        print(json.dumps(send_email_dict(path_dict, f"test_email_{stamp_str}", "Stock Overflow: test email",
                                         f"The queue on {socket.gethostname()} can send email. Sent {stamp_str}.\n"), indent=2))
    else:
        if os.path.isfile(path_dict["state"]):
            print(json.dumps(read_json(path_dict["state"]), indent=2))
        else:
            print(json.dumps({"running": None, "pending_count": len(get_pending_job_list(path_dict)), "recent": []}, indent=2))
