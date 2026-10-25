import argparse
import datetime
import json
import os
import smtplib
import subprocess
import sys
from email.message import EmailMessage
from pathlib import Path

# ADD THE WORKSPACE TO THE PATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from so.paths import get_named_data_path_str

"""
Run Queue (development runs, one at a time)

    python scripts/run_queue.py add experiments/exp13_e1m1_robustness --note "why this run"
    python scripts/run_queue.py run        # runs every pending job in order, then exits
    python scripts/run_queue.py status     # prints state.json

Files, all under <SO_DATA_PATH>/store04_experiments/:

    queue/pending/<job_id>.json   jobs waiting (job_id starts with the time it was added, so names sort in order)
    queue/done/<job_id>.json      finished jobs with their result (run id, verdict, results-log row, log file)
    queue/failed/<job_id>.json    jobs whose run exited with an error, with the last lines of the log
    queue/logs/<run_id>.log       each run's output
    queue/outbox/<run_id>.txt     an email that could not be sent (no SMTP settings, or the send failed)
    queue/runner.lock             present while a runner works; a second runner refuses to start
    state.json                    machine-readable state: the running job, pending count, the last 20 results

Each job runs scripts/run_development.py in its own process with a fresh run id, so one failure does not stop the
queue and the run's manifest is found at runs/<run_id>/manifest.json. When the manifest's verdict is email-worthy, an
email is sent through the SMTP settings in SO_SMTP_HOST, SO_SMTP_PORT (default 587, STARTTLS), SO_SMTP_USER,
SO_SMTP_PASSWORD and SO_EMAIL_TO; without them the message is written to the outbox. Nothing else sends email.
The queue never runs a holdout evaluation.
"""

# THE NUMBER OF RESULTS KEPT IN state.json
STATE_RECENT_COUNT_INT = 20
# THE NUMBER OF LOG LINES COPIED INTO A FAILED JOB
FAILED_TAIL_LINE_COUNT_INT = 20
# THE WORKSPACE ROOT
WORKSPACE_PATH = Path(__file__).resolve().parents[1]


# FUNCTION: THE QUEUE FOLDERS AND THE STATE FILE
def get_queue_path_dict(experiment_zone_str_in=None):
    """
    Args:
        experiment_zone_str_in (str | None): store04_experiments folder (None = from SO_DATA_PATH)

    Returns:
        dict: root, pending, done, failed, outbox, lock, state, runs (paths as str)
    """
    # EVERYTHING LIVES IN THE EXPERIMENT ZONE
    zone_str = experiment_zone_str_in or get_named_data_path_str("LOCAL_EXPERIMENTZONE_PATH_STR")
    root_str = os.path.join(zone_str, "queue")
    path_dict = {"root": root_str, "pending": os.path.join(root_str, "pending"), "done": os.path.join(root_str, "done"),
                 "failed": os.path.join(root_str, "failed"), "outbox": os.path.join(root_str, "outbox"),
                 "lock": os.path.join(root_str, "runner.lock"), "state": os.path.join(zone_str, "state.json"),
                 "runs": os.path.join(zone_str, "runs")}
    for key_str in ["pending", "done", "failed", "outbox"]:
        os.makedirs(path_dict[key_str], exist_ok=True)
    return path_dict


# FUNCTION: WRITE JSON THROUGH A TEMPORARY FILE
def write_json_atomic(path_str_in, payload_in):
    """
    Args:
        path_str_in (str): Target file
        payload_in (dict): JSON-serializable payload

    Returns:
        None
    """
    # A READER NEVER SEES A HALF-WRITTEN FILE
    temp_path_str = f"{path_str_in}.{os.getpid()}.tmp"
    with open(temp_path_str, "w", encoding="utf-8") as file_obj:
        json.dump(payload_in, file_obj, indent=2, default=str)
    os.replace(temp_path_str, path_str_in)


# FUNCTION: READ A JSON FILE
def read_json(path_str_in):
    """
    Args:
        path_str_in (str): File

    Returns:
        dict: Payload
    """
    # UTF-8 EVERYWHERE
    with open(path_str_in, encoding="utf-8") as file_obj:
        return json.load(file_obj)


# FUNCTION: ADD ONE JOB
def add_job_dict(path_dict_in, design_str_in, note_str_in="", n_jobs_in=None, now_in=None):
    """
    Args:
        path_dict_in (dict): Output of get_queue_path_dict
        design_str_in (str): Experiment folder, relative to the workspace (must contain design.py)
        note_str_in (str): Trial-row note
        n_jobs_in (int | None): Candidate processes
        now_in (datetime.datetime | None): Clock (tests)

    Returns:
        dict: The job
    """
    # REFUSE A FOLDER WITHOUT A DESIGN BEFORE IT REACHES THE QUEUE
    design_str = str(design_str_in).replace("\\", "/").rstrip("/")
    if not (WORKSPACE_PATH / design_str / "design.py").is_file():
        raise ValueError(f"{design_str} has no design.py")
    now = now_in or datetime.datetime.now()
    job_id_str = f"{now.strftime('%Y%m%d%H%M%S%f')}_{Path(design_str).name}"
    job_dict = {"job_id": job_id_str, "design": design_str, "note": str(note_str_in),
                "n_jobs": None if n_jobs_in is None else int(n_jobs_in), "added_ts": now.isoformat(timespec="seconds")}
    write_json_atomic(os.path.join(path_dict_in["pending"], f"{job_id_str}.json"), job_dict)
    return job_dict


# FUNCTION: PENDING JOBS IN ORDER
def get_pending_job_list(path_dict_in):
    """
    Args:
        path_dict_in (dict): Queue paths

    Returns:
        list[dict]: Jobs, oldest first
    """
    # FILE NAMES START WITH THE TIME THE JOB WAS ADDED
    name_list = sorted(name_str for name_str in os.listdir(path_dict_in["pending"]) if name_str.endswith(".json"))
    return [read_json(os.path.join(path_dict_in["pending"], name_str)) for name_str in name_list]


# FUNCTION: WRITE THE MACHINE-READABLE STATE
def write_state_dict(path_dict_in, running_job_in, result_dict_in=None):
    """
    Args:
        path_dict_in (dict): Queue paths
        running_job_in (dict | None): The job being run, or None
        result_dict_in (dict | None): A finished job's result to add to the recent list

    Returns:
        dict: The state written
    """
    # KEEP THE LAST RESULTS, NEWEST FIRST
    recent_list = []
    if os.path.isfile(path_dict_in["state"]):
        recent_list = list(read_json(path_dict_in["state"]).get("recent", []))
    if result_dict_in is not None:
        recent_list = [result_dict_in] + recent_list
    state_dict = {"updated_ts": datetime.datetime.now().isoformat(timespec="seconds"), "running": running_job_in,
                  "pending_count": len(get_pending_job_list(path_dict_in)),
                  "recent": recent_list[:STATE_RECENT_COUNT_INT]}
    write_json_atomic(path_dict_in["state"], state_dict)
    return state_dict


# FUNCTION: RUN ONE DEVELOPMENT RUN IN ITS OWN PROCESS
def run_development_process_dict(job_dict_in, run_id_str_in, log_path_str_in):
    """
    Args:
        job_dict_in (dict): Job
        run_id_str_in (str): Fresh run id
        log_path_str_in (str): Log file

    Returns:
        dict: return_code, log_line_list
    """
    # THE SAME COMMAND AS A MANUAL RUN, OUTPUT TO THE LOG
    command_list = [sys.executable, "-u", str(WORKSPACE_PATH / "scripts" / "run_development.py"), job_dict_in["design"],
                    "--note", job_dict_in.get("note", ""), "--run-id", run_id_str_in]
    if job_dict_in.get("n_jobs"):
        command_list += ["--n-jobs", str(int(job_dict_in["n_jobs"]))]
    environment_dict = dict(os.environ, PYTHONIOENCODING="utf-8")
    with open(log_path_str_in, "w", encoding="utf-8") as log_file:
        return_code_int = subprocess.call(command_list, cwd=str(WORKSPACE_PATH), stdout=log_file,
                                          stderr=subprocess.STDOUT, env=environment_dict)
    line_list = Path(log_path_str_in).read_text(encoding="utf-8", errors="replace").splitlines()
    return {"return_code": int(return_code_int), "log_line_list": line_list}


# FUNCTION: SEND ONE EMAIL, OR WRITE IT TO THE OUTBOX
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
    # SETTINGS FROM THE ENVIRONMENT ONLY
    host_str = os.environ.get("SO_SMTP_HOST", "").strip()
    to_str = os.environ.get("SO_EMAIL_TO", "").strip()
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
        dict: The job's result (also written to done/ or failed/)
    """
    # A FRESH RUN ID AND LOG FOR THIS JOB
    now = now_in or datetime.datetime.now()
    run_id_str = f"{Path(job_dict_in['design']).name}_{now.strftime('%Y%m%d%H%M%S%f')}"
    log_folder = Path(path_dict_in["root"]) / "logs"
    log_folder.mkdir(parents=True, exist_ok=True)
    log_path_str = str(log_folder / f"{run_id_str}.log")
    write_state_dict(path_dict_in, {**job_dict_in, "run_id": run_id_str, "started_ts": now.isoformat(timespec="seconds")})
    process_dict = (run_func_in or run_development_process_dict)(job_dict_in, run_id_str, log_path_str)
    # READ THE MANIFEST; A RUN WITHOUT ONE DID NOT FINISH
    manifest_path_str = os.path.join(path_dict_in["runs"], run_id_str, "manifest.json")
    manifest_dict = read_json(manifest_path_str) if os.path.isfile(manifest_path_str) else None
    row_list = [line_str[len("results_row "):] for line_str in process_dict["log_line_list"] if line_str.startswith("results_row ")]
    ok_bool = process_dict["return_code"] == 0 and manifest_dict is not None
    result_dict = {**job_dict_in, "run_id": run_id_str, "finished_ts": datetime.datetime.now().isoformat(timespec="seconds"),
                   "status": "done" if ok_bool else "failed", "return_code": process_dict["return_code"],
                   "log": log_path_str, "results_row": row_list[-1] if row_list else None,
                   "verdict": (manifest_dict or {}).get("verdict"), "email": None}
    if not ok_bool:
        result_dict["log_tail"] = process_dict["log_line_list"][-FAILED_TAIL_LINE_COUNT_INT:]
    # EMAIL ONLY WHEN THE MANIFEST SAYS EMAIL-WORTHY
    if ok_bool and bool((manifest_dict.get("verdict") or {}).get("email_worthy")):
        subject_str = f"Stock Overflow: {Path(job_dict_in['design']).name} is email-worthy"
        body_str = (f"Run {run_id_str}\nDesign {job_dict_in['design']}\nNote {job_dict_in.get('note', '')}\n"
                    f"Results row {result_dict['results_row']}\nReport {os.path.join(path_dict_in['runs'], run_id_str, 'report.md')}\n"
                    f"Manifest verdict {json.dumps(manifest_dict.get('verdict'))}\n")
        result_dict["email"] = (send_func_in or send_email_dict)(path_dict_in, run_id_str, subject_str, body_str)
    # FILE THE JOB, THEN REMOVE IT FROM PENDING
    target_folder_str = path_dict_in["done"] if ok_bool else path_dict_in["failed"]
    write_json_atomic(os.path.join(target_folder_str, f"{job_dict_in['job_id']}.json"), result_dict)
    pending_path_str = os.path.join(path_dict_in["pending"], f"{job_dict_in['job_id']}.json")
    if os.path.isfile(pending_path_str):
        os.remove(pending_path_str)
    write_state_dict(path_dict_in, None, result_dict)
    return result_dict


# FUNCTION: RUN EVERY PENDING JOB UNDER ONE LOCK
def run_queue_list(path_dict_in, run_func_in=None, send_func_in=None):
    """
    Jobs added while the runner works are picked up before it exits.

    Args:
        path_dict_in (dict): Queue paths
        run_func_in, send_func_in (callable | None): Replacements (tests)

    Returns:
        list[dict]: Results in run order
    """
    # ONE RUNNER AT A TIME
    try:
        lock_fd = os.open(path_dict_in["lock"], os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise SystemExit(f"another queue runner holds {path_dict_in['lock']} (delete it only if no runner is running)")
    os.write(lock_fd, str(os.getpid()).encode("ascii"))
    os.close(lock_fd)
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


# PARSE THE COMMAND
if __name__ == "__main__":
    # ARGUMENTS
    parser = argparse.ArgumentParser(description="Development run queue (one run at a time).")
    sub_parser = parser.add_subparsers(dest="command", required=True)
    add_parser = sub_parser.add_parser("add", help="Add one job")
    add_parser.add_argument("design", help="Experiment folder")
    add_parser.add_argument("--note", default="", help="Trial-row note")
    add_parser.add_argument("--n-jobs", type=int, default=None, help="Candidate processes")
    sub_parser.add_parser("run", help="Run every pending job, then exit")
    sub_parser.add_parser("status", help="Print state.json")
    arg_dict = parser.parse_args()
    path_dict = get_queue_path_dict()
    if arg_dict.command == "add":
        print(json.dumps(add_job_dict(path_dict, arg_dict.design, arg_dict.note, arg_dict.n_jobs), indent=2))
    elif arg_dict.command == "run":
        result_list = run_queue_list(path_dict)
        print(f"\n===== queue: {len(result_list)} job(s) =====")
        for result_dict in result_list:
            print(f"{result_dict['job_id']} {result_dict['status']}: {result_dict['results_row'] or result_dict['log']}")
    else:
        state_dict = write_state_dict(path_dict, None) if not os.path.isfile(path_dict["state"]) else read_json(path_dict["state"])
        print(json.dumps(state_dict, indent=2))
