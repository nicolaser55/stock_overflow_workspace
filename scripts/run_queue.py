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
    state.json                    the running job, pending count, heartbeat, the commit of the queue script itself
                                  (queue_commit), the last 20 results

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
Each pass fetches origin once before it validates pending files, so a job can name any pushed commit. The
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
QUEUE_COMMIT_CACHE_STR = None
# THE REF scripts/deploy_runner.ps1 SETS TO THE COMMIT NICOLAS DEPLOYED (THE JUDGE OF NEW JOBS)
DEPLOYED_REF_STR = "refs/deployed"


# CLASS: NO DEPLOYED JUDGE YET (NEW JOBS WAIT)
class NoDeployedJudgeError(ValueError):
    """The judge ref does not resolve: nothing has been deployed with scripts/deploy_runner.ps1."""
# THE KILL-SWITCH FILE NAME INSIDE <SO_DATA_PATH>/control
STOP_FLAG_FOLDER_STR = "control"
STOP_FLAG_FILE_STR = "STOP"


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
        dict: root, pending, running, rejected, done, failed, outbox, logs, lock, state, runs, run_index, stop_flag
        (paths as str; stop_flag is "" when no data root is set)
    """
    # PATHS ONLY: AN AGENT CANNOT CREATE FOLDERS HERE, AND add NEEDS ONLY pending
    zone_str = experiment_zone_str_in or get_named_data_path_str("LOCAL_EXPERIMENTZONE_PATH_STR")
    root_str = os.path.join(zone_str, "queue")
    return {"root": root_str, "pending": os.path.join(root_str, "pending"), "running": os.path.join(root_str, "running"),
            "rejected": os.path.join(root_str, "rejected"), "done": os.path.join(root_str, "done"),
            "failed": os.path.join(root_str, "failed"), "outbox": os.path.join(root_str, "outbox"),
            "logs": os.path.join(root_str, "logs"), "lock": os.path.join(root_str, "runner.lock"),
            "state": os.path.join(zone_str, "state.json"), "runs": os.path.join(zone_str, "runs"),
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
    for key_str in ["pending", "running", "rejected", "done", "failed", "outbox", "logs", "runs"]:
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
    # REPLACE IN ONE STEP SO A READER NEVER SEES HALF A FILE
    temp_path_str = f"{path_str_in}.{os.getpid()}.tmp"
    with open(temp_path_str, "w", encoding="utf-8") as file_obj:
        json.dump(payload_in, file_obj, indent=2, default=str)
    os.replace(temp_path_str, path_str_in)


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
        job_id_str_in (str): A job in failed/
        now_in (datetime.datetime | None): Clock (tests)

    Returns:
        dict: The new job
    """
    # THE FAILED RESULT HOLDS THE RUN ID
    failed_path_str = os.path.join(path_dict_in["failed"], f"{job_id_str_in}.json")
    if not os.path.isfile(failed_path_str):
        raise ValueError(f"no failed job {job_id_str_in}")
    failed_dict = read_json(failed_path_str)
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
    # THE AGENT THAT ADDED THE JOB CANNOT READ rejected/, SO THE REASON ALSO GOES INTO state.json (status SHOWS IT)
    write_state_dict(path_dict_in, None, {"job_id": stem_str, "status": "rejected", "reason": str(reason_str_in)[:300],
                                          "finished_ts": now.isoformat(timespec="seconds")})
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
    # THE MAIN THREAD AND THE HEARTBEAT THREAD BOTH WRITE; THE RECENT LIST IS KEPT ACROSS WRITES
    with STATE_LOCK:
        recent_list = []
        if os.path.isfile(path_dict_in["state"]):
            try:
                recent_list = list(read_json(path_dict_in["state"]).get("recent", []))
            except (ValueError, OSError):
                recent_list = []
        if result_dict_in is not None:
            recent_list = [result_dict_in] + recent_list
        state_dict = {"updated_ts": datetime.datetime.now().isoformat(timespec="seconds"), "running": running_job_in,
                      "pending_count": len(get_pending_job_list(path_dict_in)), "host": socket.gethostname(),
                      "queue_commit": get_queue_commit_str(), "deployed_commit": get_deployed_commit_str(),
                      "stopped": get_stop_flag_bool(path_dict_in),
                      "recent": recent_list[:STATE_RECENT_COUNT_INT]}
        write_json_atomic(path_dict_in["state"], state_dict)
    return state_dict


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
    header_str = (f"run commit {run_commit_str}\njudge commit {job_dict_in['judge_commit']}\n"
                  f"design commit {job_dict_in['commit']}\nworktree {worktree_str}\n")
    try:
        outcome_dict = run_logged_command_dict(command_list, worktree_str, environment_dict, log_path_str_in,
                                               timeout_seconds, header_str)
    finally:
        remove_job_worktree(worktree_str, git_func)
    line_list = Path(log_path_str_in).read_text(encoding="utf-8", errors="replace").splitlines()
    return {"return_code": outcome_dict["return_code"], "log_line_list": line_list,
            "timed_out_bool": outcome_dict["timed_out_bool"], "run_commit": run_commit_str}


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
                 f"Designs tried (the multiple-testing N) {number_dict['design_count'] or 'n/a'}",
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
        return {"return_code": -2, "log_line_list": [message_str], "timed_out_bool": False}
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
    status_str = "done" if ok_bool else ("timeout" if process_dict.get("timed_out_bool") else "failed")
    result_dict = {**job_dict_in, "run_id": run_id_str, "finished_ts": datetime.datetime.now().isoformat(timespec="seconds"),
                   "status": status_str, "return_code": process_dict["return_code"], "log": log_path_str,
                   "results_row": row_list[-1] if row_list else None, "verdict": (manifest_dict or {}).get("verdict"),
                   "run_commit": process_dict.get("run_commit") or job_dict_in.get("run_commit"), "email": None}
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
    # THE JOB IS FILED: THE CLAIM AND ANY LEFTOVER PENDING FILE GO
    for folder_key_str in ["running", "pending"]:
        leftover_str = os.path.join(path_dict_in[folder_key_str], f"{job_dict_in['job_id']}.json")
        if os.path.isfile(leftover_str):
            os.remove(leftover_str)
    write_state_dict(path_dict_in, None, result_dict)
    return result_dict


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
        print(f"{result_dict['status']} {job_in['job_id']} {result_dict['results_row'] or result_dict['log']}", flush=True)
        result_list.append(result_dict)

    try:
        upgrade_run_index_file(path_dict_in)
        # THE KILL SWITCH IS CHECKED BEFORE EVERY JOB; A RECOVERED JOB STAYS IN running/ UNTIL THE FLAG IS GONE
        if not get_stop_flag_bool(path_dict_in):
            for job_dict in recover_running_job_list(path_dict_in):
                run_one_func(job_dict)
        # NEW COMMITS FIRST, SO A PENDING JOB THAT NAMES A JUST-PUSHED COMMIT IS NOT REJECTED AS MISSING
        fetch_origin(git_func_in)
        while True:
            if get_stop_flag_bool(path_dict_in):
                print(f"stop flag set ({path_dict_in['stop_flag']}); no further job is started", flush=True)
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
                run_func_in=None, send_func_in=None, judge_func_in=None, git_func_in=None, prepare_func_in=None):
    """
    The runner account's scheduled task. Each loop runs every pending job (and any job a crash left in running/), or
    writes a heartbeat to state.json.

    Args:
        path_dict_in (dict): Queue paths
        interval_seconds_in (float): Pause between loops
        max_loop_count_in (int | None): Stop after this many loops (tests; None = forever)
        run_func_in, send_func_in (callable | None): Replacements (tests)
        judge_func_in, git_func_in, prepare_func_in (callable | None): Replacements (tests)

    Returns:
        int: Jobs run
    """
    # A JOB THAT FAILS DOES NOT STOP THE WATCH
    job_count_int, loop_count_int = 0, 0
    while max_loop_count_in is None or loop_count_int < int(max_loop_count_in):
        if get_has_work_bool(path_dict_in) and not get_stop_flag_bool(path_dict_in):
            job_count_int += len(run_queue_list(path_dict_in, run_func_in, send_func_in, judge_func_in=judge_func_in,
                                                git_func_in=git_func_in, prepare_func_in=prepare_func_in))
        else:
            make_runner_folder_list(path_dict_in)
            write_state_dict(path_dict_in, None)
        loop_count_int += 1
        if max_loop_count_in is None or loop_count_int < int(max_loop_count_in):
            time.sleep(float(interval_seconds_in))
    return job_count_int


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
    retry_parser.add_argument("job_id", help="Job id in queue/failed/")
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
            print(f"{result_dict['job_id']} {result_dict['status']}: {result_dict['results_row'] or result_dict['log']}")
    elif arg_dict.command == "watch":
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
