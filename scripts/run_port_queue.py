import csv
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

"""
Queue for the version-2.0 development replays (Nicolas, 2026-10-12).

Runs one step at a time. A finished step is skipped, so the queue can be restarted after an interruption. A step that
failed before it finished is run again on the next start. During one pass, a failure still skips the rest of that
experiment and the queue continues with the next experiment. exp01 is last. A run longer than 24 hours is started
anyway, and the log receives a progress line at least every 30 minutes while that step runs.

Usage, from the workspace root:
    venv-main/Scripts/python.exe -u scripts/run_port_queue.py
"""

# THE WORKSPACE ROOT AND THE LOG FOLDER
_ROOT_PATH = Path(__file__).resolve().parents[1]
_LOG_DIR_PATH = _ROOT_PATH / "logs"
_STATUS_PATH = _LOG_DIR_PATH / "port_queue_status.csv"
_PROGRESS_PATH = _LOG_DIR_PATH / "port_queue_progress.log"
_STATUS_COLUMN_LIST = ["experiment", "step", "status", "start", "end", "log_path"]
# HOW OFTEN A LONG STEP WRITES A PROGRESS LINE
_HEARTBEAT_SECOND_COUNT = 30 * 60

# FUNCTION: THE STEPS, IN ORDER
def get_step_dict_list():
    """
    Development notebooks, then the old-bounds calibration for each rule experiment. exp01 is last and has no
    calibration. exp02 and exp03 are not here: they already ran.

    Returns:
        list[dict]: experiment, step, notebook or calibrate package, experiment_name, heartbeat
    """
    # RULE EXPERIMENTS, THEN THE MINUTE-ENTRY MODEL
    rule_list = ["exp04_trend_exit", "exp05_vol_scaled_exposure", "exp06_capped_regret_reentry",
                 "exp07_warning_lights_exit", "exp12_vix_fear_reentry", "exp13_e1m1_robustness"]
    step_list = []
    for package_str in rule_list:
        step_list.append({"experiment": package_str, "step": "development", "kind": "notebook",
                          "notebook": f"experiments/{package_str}/step01_development.ipynb",
                          "experiment_name": f"{package_str}_v2", "heartbeat": False})
        step_list.append({"experiment": package_str, "step": "calibration", "kind": "calibration",
                          "package": package_str, "experiment_name": f"{package_str}_v2", "heartbeat": False})
    step_list.append({"experiment": "exp01_minute_entry", "step": "development", "kind": "notebook",
                      "notebook": "experiments/exp01_minute_entry/step01_development.ipynb",
                      "experiment_name": "exp01_minute_entry_v2", "heartbeat": True})
    return step_list

# FUNCTION: A NOTEBOOK WHOSE CELLS FINISHED WITHOUT AN ERROR
def get_notebook_finished_bool(notebook_path_in):
    """
    True when every code cell has an execution count and none of its outputs is an error.

    Args:
        notebook_path_in (Path): Notebook

    Returns:
        bool: Finished
    """
    # AN ABSENT OR EMPTY NOTEBOOK HAS NOT RUN
    import json
    if not notebook_path_in.is_file():
        return False
    notebook_dict = json.loads(notebook_path_in.read_text(encoding="utf-8"))
    code_cell_list = [cell_dict for cell_dict in notebook_dict.get("cells", []) if cell_dict.get("cell_type") == "code"]
    if not code_cell_list:
        return False
    for cell_dict in code_cell_list:
        if cell_dict.get("execution_count") is None:
            return False
        for output_dict in cell_dict.get("outputs", []):
            if output_dict.get("output_type") == "error":
                return False
    return True

# FUNCTION: TRIAL ROWS THAT MEAN A STEP ALREADY FINISHED
def get_trial_finished_bool(experiment_name_str_in, step_str_in, trial_pdf_in):
    """
    A development step is finished when it has validation rows. A calibration is finished when it has its note row.

    Args:
        experiment_name_str_in (str): Trial-log experiment name
        step_str_in (str): development or calibration
        trial_pdf_in (pd.DataFrame): Trial log

    Returns:
        bool: Finished
    """
    # EMPTY LOG
    if trial_pdf_in is None or len(trial_pdf_in) == 0 or "experiment" not in trial_pdf_in.columns:
        return False
    experiment_pdf = trial_pdf_in[trial_pdf_in["experiment"] == experiment_name_str_in]
    if step_str_in == "calibration":
        note_pdf = experiment_pdf[experiment_pdf["stage"] == "note"]
        return bool(len(note_pdf) and note_pdf["note"].astype(str).str.contains("old-bounds calibration").any())
    return bool((experiment_pdf["stage"] == "validation").any())

# FUNCTION: APPEND ONE STATUS ROW
def write_status_row(row_dict_in, status_path_in):
    """
    Appends one row to the status file, writing the header when the file is new.

    Args:
        row_dict_in (dict): experiment, step, status, start, end, log_path
        status_path_in (Path): Status CSV

    Returns:
        None
    """
    # CREATE THE FOLDER AND THE HEADER
    status_path_in.parent.mkdir(parents=True, exist_ok=True)
    write_header_bool = not status_path_in.is_file()
    with status_path_in.open("a", newline="", encoding="utf-8") as status_file:
        writer = csv.DictWriter(status_file, fieldnames=_STATUS_COLUMN_LIST)
        if write_header_bool:
            writer.writeheader()
        writer.writerow({column_str: row_dict_in.get(column_str, "") for column_str in _STATUS_COLUMN_LIST})

# FUNCTION: APPEND ONE PROGRESS LINE AND FLUSH IT
def write_progress_line(progress_path_in, message_str_in):
    """
    Appends one line to the progress log and flushes it, so a reader sees it while the step is still running.

    Args:
        progress_path_in (Path): Progress log
        message_str_in (str): Line, without a trailing newline

    Returns:
        None
    """
    # CREATE THE FOLDER, APPEND, AND FLUSH BEFORE THE CALLER CONTINUES
    progress_path_in.parent.mkdir(parents=True, exist_ok=True)
    with progress_path_in.open("a", encoding="utf-8") as progress_file:
        progress_file.write(message_str_in.rstrip("\n") + "\n")
        progress_file.flush()
        os.fsync(progress_file.fileno())

# FUNCTION: A PROGRESS LINE EVERY HALF HOUR WHILE A CHILD RUNS
def start_heartbeat_thread(log_path_in, stop_event_in, progress_path_in):
    """
    Appends a progress line to the step log and to the progress log until stop_event_in is set.

    Args:
        log_path_in (Path): Step log
        stop_event_in (threading.Event): Set when the child exits
        progress_path_in (Path): Separate progress log

    Returns:
        threading.Thread: The heartbeat
    """
    # THE FIRST LINE IS IMMEDIATE SO A LONG SILENCE STILL HAS A CLOCK
    def heartbeat():
        while not stop_event_in.wait(_HEARTBEAT_SECOND_COUNT):
            line_str = f"progress {datetime.now().isoformat(timespec='seconds')} still running"
            with log_path_in.open("a", encoding="utf-8") as log_file:
                log_file.write(line_str + "\n")
                log_file.flush()
            write_progress_line(progress_path_in, line_str)
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    return thread

# FUNCTION: RUN ONE CHILD AND WAIT FOR IT
def run_child_int(argument_list_in, log_path_in, heartbeat_bool_in, progress_path_in=None):
    """
    Runs one Python command. stdout and stderr go to the log. The processes do not overlap. A long step also writes
    the heartbeat to the separate progress log.

    Args:
        argument_list_in (list[str]): Arguments after the interpreter
        log_path_in (Path): Log file
        heartbeat_bool_in (bool): Write a progress line every 30 minutes
        progress_path_in (Path | None): Separate progress log

    Returns:
        int: Exit code
    """
    # ONE PROCESS. THE QUEUE DOES NOT START THE NEXT STEP UNTIL THIS ONE RETURNS.
    log_path_in.parent.mkdir(parents=True, exist_ok=True)
    progress_path = _PROGRESS_PATH if progress_path_in is None else Path(progress_path_in)
    stop_event = threading.Event()
    if heartbeat_bool_in:
        with log_path_in.open("a", encoding="utf-8") as log_file:
            log_file.write("estimated time may exceed 24 hours; running anyway (Nicolas, 2026-10-12)\n")
            log_file.flush()
        start_heartbeat_thread(log_path_in, stop_event, progress_path)
    with log_path_in.open("a", encoding="utf-8") as log_file:
        completed = subprocess.run([sys.executable, "-u", *argument_list_in], cwd=str(_ROOT_PATH), stdout=log_file, stderr=subprocess.STDOUT)
    stop_event.set()
    return int(completed.returncode)

# FUNCTION: WALK THE QUEUE
def run_queue(step_dict_list_in=None, trial_pdf_in=None, status_path_in=None, runner_func_in=None, progress_path_in=None):
    """
    Skips a finished step, runs the others one at a time, and continues after a failure. A progress line is flushed
    before the step's child starts.

    Args:
        step_dict_list_in (list[dict] | None): Steps (None = the real queue)
        trial_pdf_in (pd.DataFrame | None): Trial log (None = the shared log)
        status_path_in (Path | None): Status CSV
        runner_func_in (callable | None): Replacement for the child process, used by the test
        progress_path_in (Path | None): Separate progress log (None = logs/port_queue_progress.log)

    Returns:
        list[dict]: Status rows written
    """
    # THE REAL LOG WHEN THE CALLER DOES NOT PASS ONE
    import pandas as pd
    step_list = get_step_dict_list() if step_dict_list_in is None else step_dict_list_in
    status_path = _STATUS_PATH if status_path_in is None else Path(status_path_in)
    progress_path = _PROGRESS_PATH if progress_path_in is None else Path(progress_path_in)
    if trial_pdf_in is None:
        from so.core.trial_log import read_trial_log_pdf
        trial_pdf = read_trial_log_pdf()
    else:
        trial_pdf = trial_pdf_in
    written_list = []
    # A FAILURE IN THIS PASS SKIPS THE REST OF THAT EXPERIMENT. A LATER START RUNS A STEP THAT NEVER FINISHED.
    failed_experiment_set = set()
    for step_dict in step_list:
        # A FAILED STEP SKIPS THE REST OF THAT EXPERIMENT AND CONTINUES WITH THE NEXT ONE
        if step_dict["experiment"] in failed_experiment_set:
            row_dict = {"experiment": step_dict["experiment"], "step": step_dict["step"], "status": "skipped",
                        "start": datetime.now().isoformat(timespec="seconds"), "end": datetime.now().isoformat(timespec="seconds"),
                        "log_path": ""}
            write_status_row(row_dict, status_path)
            written_list.append(row_dict)
            continue
        start_str = datetime.now().isoformat(timespec="seconds")
        stamp_str = datetime.now().strftime("%Y%m%d_%H%M")
        log_path = _LOG_DIR_PATH / f"{step_dict['experiment']}_{step_dict['step']}_{stamp_str}.log"
        notebook_finished_bool = True
        if step_dict["kind"] == "notebook":
            notebook_finished_bool = get_notebook_finished_bool(_ROOT_PATH / step_dict["notebook"])
        trial_finished_bool = get_trial_finished_bool(step_dict["experiment_name"], step_dict["step"], trial_pdf)
        if notebook_finished_bool and trial_finished_bool and step_dict["kind"] == "notebook":
            status_str = "skipped"
        elif step_dict["kind"] == "calibration" and trial_finished_bool:
            status_str = "skipped"
        else:
            status_str = "running"
            write_progress_line(progress_path, f"running {step_dict['experiment']} {step_dict['step']} {start_str}")
            if runner_func_in is None:
                if step_dict["kind"] == "notebook":
                    exit_code = run_child_int(["scripts/execute_notebook.py", step_dict["notebook"]], log_path, step_dict["heartbeat"], progress_path)
                else:
                    exit_code = run_child_int(["scripts/calibrate_port_old_bounds.py", step_dict["package"]], log_path, False, progress_path)
                status_str = "finished" if exit_code == 0 else "failed"
            else:
                try:
                    runner_func_in(step_dict)
                    status_str = "finished"
                except Exception as error:
                    status_str = "failed"
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    with log_path.open("a", encoding="utf-8") as log_file:
                        log_file.write(f"{type(error).__name__}: {error}\n")
        end_str = datetime.now().isoformat(timespec="seconds")
        write_progress_line(progress_path, f"{status_str} {step_dict['experiment']} {step_dict['step']} {end_str}")
        row_dict = {"experiment": step_dict["experiment"], "step": step_dict["step"], "status": status_str,
                    "start": start_str, "end": end_str, "log_path": str(log_path)}
        write_status_row(row_dict, status_path)
        written_list.append(row_dict)
        if status_str == "failed":
            failed_experiment_set.add(step_dict["experiment"])
    return written_list

# RUN THE REAL QUEUE
if __name__ == "__main__":
    run_queue()
