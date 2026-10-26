import argparse
import datetime
import json
import os
import shutil
import smtplib
import socket
import subprocess
import sys
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
Run Queue (development runs, one at a time, at the commit each job names)

Agents (so_agent) add jobs; only the runner account (so_runner) runs them and writes results (audit S3 / S4,
2026-10-25). Every job names a commit, and the runner executes that commit in a temporary git worktree, so a result
always belongs to known code, whatever is checked out anywhere.

    python scripts/run_queue.py add experiments/exp13_e1m1_robustness --note "why this run"   # the current commit
    python scripts/run_queue.py add experiments/exp13_e1m1_robustness --commit <sha> --note "..."
    python scripts/run_queue.py retry <job_id>      # queue a failed job again; it resumes the same run id
    python scripts/run_queue.py run                 # runner: run every pending job, then exit
    python scripts/run_queue.py watch               # runner: run jobs as they arrive, forever (the scheduled task)
    python scripts/run_queue.py status              # print state.json

add refuses a clone with uncommitted changes in so/ or the design folder, and records the commit; the commit must be
pushed (the runner fetches origin before each job). Files, all under <SO_DATA_PATH>/store04_experiments/:

    queue/pending/<job_id>.json   jobs waiting (the only folder so_agent may write)
    queue/done/<job_id>.json      finished jobs with their result
    queue/failed/<job_id>.json    jobs whose run failed or timed out, with the last lines of the log
    queue/logs/<run_id>_attempt<n>.log   each attempt's output
    queue/outbox/<run_id>.txt     an email that could not be sent
    queue/runner.lock             the running runner's process id and host; a stale lock (dead process) is replaced
    run_index.csv                 one row per job attempt (append-only; scripts/append_results_log.py turns finished
                                  rows into docs/RESULTS_LOG.md rows)
    state.json                    the running job, pending count, heartbeat, the last 20 results

A job runs scripts/run_development.py from a worktree at <SO_QUEUE_WORKTREE_ROOT or <workspace>/.worktrees>/<run_id>,
with the Python in SO_QUEUE_PYTHON (default: this interpreter), under a time limit (SO_QUEUE_JOB_TIMEOUT_HOURS,
default 24); a timeout kills the whole process tree. The worktree is removed afterwards. An email-worthy verdict and a
failed job send an email (SMTP from SO_SMTP_HOST, SO_SMTP_PORT, SO_SMTP_USER, SO_SMTP_PASSWORD, SO_EMAIL_TO; without
them the message goes to the outbox). The queue never runs a holdout evaluation.
"""

# THE NUMBER OF RECENT RESULTS IN state.json AND OF LOG LINES KEPT FOR A FAILED JOB
STATE_RECENT_COUNT_INT = 20
FAILED_TAIL_LINE_COUNT_INT = 20
# THE WORKSPACE OF THIS SCRIPT (THE RUNNER'S CLONE WHEN THE RUNNER RUNS IT)
WORKSPACE_PATH = Path(__file__).resolve().parents[1]
# THE RUN INDEX COLUMNS
RUN_INDEX_COLUMN_LIST = ["run_id", "attempt", "job_id", "design", "commit", "note", "status", "return_code",
                         "verdict_label", "email_worthy", "failed_list", "strategy_total_return",
                         "buy_hold_total_return", "look_ahead", "design_count", "added_by", "added_ts", "finished_ts"]
# THE CODE add REQUIRES TO BE COMMITTED (WITH THE DESIGN FOLDER)
GUARDED_ADD_FOLDER_LIST = ["so"]
# DEFAULT TIME LIMIT OF ONE JOB (exp01 TAKES 11-14 HOURS)
DEFAULT_JOB_TIMEOUT_HOURS = 24.0
# SECONDS BETWEEN TWO LOOKS AT THE PENDING FOLDER IN watch MODE
DEFAULT_WATCH_INTERVAL_SECONDS = 60


# FUNCTION: THE QUEUE PATHS (NOTHING IS CREATED)
def get_queue_path_dict(experiment_zone_str_in=None):
    """
    Args:
        experiment_zone_str_in (str | None): store04_experiments folder (None = from SO_DATA_PATH)

    Returns:
        dict: root, pending, done, failed, outbox, logs, lock, state, runs, run_index (paths as str)
    """
    # PATHS ONLY: AN AGENT CANNOT CREATE FOLDERS HERE, AND add NEEDS ONLY pending
    zone_str = experiment_zone_str_in or get_named_data_path_str("LOCAL_EXPERIMENTZONE_PATH_STR")
    root_str = os.path.join(zone_str, "queue")
    return {"root": root_str, "pending": os.path.join(root_str, "pending"), "done": os.path.join(root_str, "done"),
            "failed": os.path.join(root_str, "failed"), "outbox": os.path.join(root_str, "outbox"),
            "logs": os.path.join(root_str, "logs"), "lock": os.path.join(root_str, "runner.lock"),
            "state": os.path.join(zone_str, "state.json"), "runs": os.path.join(zone_str, "runs"),
            "run_index": os.path.join(zone_str, "run_index.csv")}


# FUNCTION: CREATE THE RUNNER'S FOLDERS
def make_runner_folder_list(path_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths

    Returns:
        None
    """
    # THE RUNNER OWNS THESE
    for key_str in ["pending", "done", "failed", "outbox", "logs", "runs"]:
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
def run_git_str(arg_list_in, cwd_in=WORKSPACE_PATH):
    """
    Args:
        arg_list_in (list[str]): git arguments
        cwd_in (Path | str): Folder

    Returns:
        str: stdout
    """
    # RAISES ON A NON-ZERO EXIT
    return subprocess.check_output(["git"] + list(arg_list_in), cwd=str(cwd_in), text=True, encoding="utf-8",
                                   stderr=subprocess.STDOUT)


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
                "attempt": attempt_int, "run_id": failed_dict.get("run_id"), "retry_of": job_id_str_in}
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
    # THE RECENT LIST IS KEPT ACROSS WRITES
    recent_list = []
    if os.path.isfile(path_dict_in["state"]):
        recent_list = list(read_json(path_dict_in["state"]).get("recent", []))
    if result_dict_in is not None:
        recent_list = [result_dict_in] + recent_list
    state_dict = {"updated_ts": datetime.datetime.now().isoformat(timespec="seconds"), "running": running_job_in,
                  "pending_count": len(get_pending_job_list(path_dict_in)), "host": socket.gethostname(),
                  "recent": recent_list[:STATE_RECENT_COUNT_INT]}
    write_json_atomic(path_dict_in["state"], state_dict)
    return state_dict


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


# FUNCTION: RUN ONE DEVELOPMENT RUN AT THE JOB'S COMMIT
def run_development_process_dict(job_dict_in, run_id_str_in, log_path_str_in):
    """
    Args:
        job_dict_in (dict): Job (design, commit, note, n_jobs)
        run_id_str_in (str): Run id
        log_path_str_in (str): Log file

    Returns:
        dict: return_code, log_line_list, timed_out_bool
    """
    # A WORKTREE AT THE COMMIT, THE RUNNER'S PYTHON, A TIME LIMIT
    if not job_dict_in.get("commit"):
        raise ValueError("the job names no commit; add it again with scripts/run_queue.py add")
    worktree_str = make_job_worktree_str(job_dict_in["commit"], run_id_str_in)
    timeout_seconds = float(os.environ.get("SO_QUEUE_JOB_TIMEOUT_HOURS", DEFAULT_JOB_TIMEOUT_HOURS)) * 3600.0
    python_str = os.environ.get("SO_QUEUE_PYTHON", "").strip() or sys.executable
    command_list = [python_str, "-u", os.path.join(worktree_str, "scripts", "run_development.py"), job_dict_in["design"],
                    "--note", job_dict_in.get("note", ""), "--run-id", run_id_str_in]
    if job_dict_in.get("n_jobs"):
        command_list += ["--n-jobs", str(int(job_dict_in["n_jobs"]))]
    environment_dict = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONPATH=worktree_str)
    try:
        outcome_dict = run_logged_command_dict(command_list, worktree_str, environment_dict, log_path_str_in,
                                               timeout_seconds, f"commit {job_dict_in['commit']}\nworktree {worktree_str}\n")
    finally:
        remove_job_worktree(worktree_str)
    line_list = Path(log_path_str_in).read_text(encoding="utf-8", errors="replace").splitlines()
    return {"return_code": outcome_dict["return_code"], "log_line_list": line_list,
            "timed_out_bool": outcome_dict["timed_out_bool"]}


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
        dict: strategy_total_return, buy_hold_total_return, design_count (empty strings when absent)
    """
    # report.json HOLDS EVERY NUMBER BEHIND THE VERDICT
    report_path_str = os.path.join(path_dict_in["runs"], run_id_str_in, "report.json")
    if not os.path.isfile(report_path_str):
        return {"strategy_total_return": "", "buy_hold_total_return": "", "design_count": ""}
    report_dict = read_json(report_path_str)
    return_dict = report_dict.get("return_dict") or {}
    return {"strategy_total_return": return_dict.get("strategy_total_return", ""),
            "buy_hold_total_return": return_dict.get("buy_hold_total_return", ""),
            "design_count": (report_dict.get("multiple_testing_dict") or {}).get("design_count", "")}


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
                "commit": result_dict_in.get("commit") or "", "note": result_dict_in.get("note", ""),
                "status": result_dict_in["status"], "return_code": result_dict_in.get("return_code", ""),
                "verdict_label": verdict_dict.get("label", ""), "email_worthy": verdict_dict.get("email_worthy", ""),
                "failed_list": ";".join(verdict_dict.get("failed_list") or []),
                "look_ahead": verdict_dict.get("look_ahead", ""), "added_by": result_dict_in.get("added_by", ""),
                "added_ts": result_dict_in.get("added_ts", ""), "finished_ts": result_dict_in.get("finished_ts", ""),
                **get_report_number_dict(path_dict_in, result_dict_in["run_id"])}
    return append_csv_record_pdf(pd.DataFrame([row_dict]), path_dict_in["run_index"], RUN_INDEX_COLUMN_LIST)


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
    write_state_dict(path_dict_in, {**job_dict_in, "run_id": run_id_str, "started_ts": now.isoformat(timespec="seconds")})
    try:
        process_dict = (run_func_in or run_development_process_dict)(job_dict_in, run_id_str, log_path_str)
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
                   "email": None}
    send_func = send_func_in or send_email_dict
    if not ok_bool:
        result_dict["log_tail"] = process_dict["log_line_list"][-FAILED_TAIL_LINE_COUNT_INT:]
        subject_str = f"Stock Overflow: {Path(job_dict_in['design']).name} run {status_str}"
        body_str = (f"Run {run_id_str}\nJob {job_dict_in['job_id']}\nCommit {job_dict_in.get('commit')}\n"
                    f"Log {log_path_str}\n\nLast lines:\n" + "\n".join(result_dict["log_tail"]) +
                    f"\n\nRetry: python scripts/run_queue.py retry {job_dict_in['job_id']}\n")
        result_dict["email"] = send_func(path_dict_in, run_id_str, subject_str, body_str)
    elif bool((manifest_dict.get("verdict") or {}).get("email_worthy")):
        subject_str = f"Stock Overflow: {Path(job_dict_in['design']).name} is email-worthy"
        body_str = (f"Run {run_id_str}\nDesign {job_dict_in['design']}\nCommit {job_dict_in.get('commit')}\n"
                    f"Note {job_dict_in.get('note', '')}\nResults row {result_dict['results_row']}\n"
                    f"Report {os.path.join(path_dict_in['runs'], run_id_str, 'report.md')}\n"
                    f"Manifest verdict {json.dumps(manifest_dict.get('verdict'))}\n")
        result_dict["email"] = send_func(path_dict_in, run_id_str, subject_str, body_str)
    target_folder_str = path_dict_in["done"] if ok_bool else path_dict_in["failed"]
    os.makedirs(target_folder_str, exist_ok=True)
    write_json_atomic(os.path.join(target_folder_str, f"{job_dict_in['job_id']}.json"), result_dict)
    append_run_index_row(path_dict_in, result_dict)
    pending_path_str = os.path.join(path_dict_in["pending"], f"{job_dict_in['job_id']}.json")
    if os.path.isfile(pending_path_str):
        os.remove(pending_path_str)
    write_state_dict(path_dict_in, None, result_dict)
    return result_dict


# FUNCTION: RUN EVERY PENDING JOB UNDER THE LOCK
def run_queue_list(path_dict_in, run_func_in=None, send_func_in=None, pid_alive_func_in=None):
    """
    Jobs added while the runner works are picked up before it exits.

    Args:
        path_dict_in (dict): Queue paths
        run_func_in, send_func_in (callable | None): Replacements (tests)
        pid_alive_func_in (callable | None): Replacement for the stale-lock check (tests)

    Returns:
        list[dict]: Results in run order
    """
    # THE RUNNER'S FOLDERS, THE LOCK, THEN THE JOBS
    make_runner_folder_list(path_dict_in)
    acquire_runner_lock(path_dict_in, pid_alive_func_in)
    result_list = []
    try:
        while True:
            pending_list = get_pending_job_list(path_dict_in)
            if not pending_list:
                break
            job_dict = pending_list[0]
            print(f"start {job_dict['job_id']} {datetime.datetime.now():%H:%M:%S}", flush=True)
            result_dict = run_job_dict(path_dict_in, job_dict, run_func_in, send_func_in)
            print(f"{result_dict['status']} {job_dict['job_id']} {result_dict['results_row'] or result_dict['log']}", flush=True)
            result_list.append(result_dict)
    finally:
        write_state_dict(path_dict_in, None)
        os.remove(path_dict_in["lock"])
    return result_list


# FUNCTION: RUN JOBS AS THEY ARRIVE
def watch_queue(path_dict_in, interval_seconds_in=DEFAULT_WATCH_INTERVAL_SECONDS, max_loop_count_in=None,
                run_func_in=None, send_func_in=None):
    """
    The runner account's scheduled task. Each loop runs every pending job, or writes a heartbeat to state.json.

    Args:
        path_dict_in (dict): Queue paths
        interval_seconds_in (float): Pause between loops
        max_loop_count_in (int | None): Stop after this many loops (tests; None = forever)
        run_func_in, send_func_in (callable | None): Replacements (tests)

    Returns:
        int: Jobs run
    """
    # A JOB THAT FAILS DOES NOT STOP THE WATCH
    job_count_int, loop_count_int = 0, 0
    while max_loop_count_in is None or loop_count_int < int(max_loop_count_in):
        if get_pending_job_list(path_dict_in):
            job_count_int += len(run_queue_list(path_dict_in, run_func_in, send_func_in))
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
    else:
        if os.path.isfile(path_dict["state"]):
            print(json.dumps(read_json(path_dict["state"]), indent=2))
        else:
            print(json.dumps({"running": None, "pending_count": len(get_pending_job_list(path_dict)), "recent": []}, indent=2))
