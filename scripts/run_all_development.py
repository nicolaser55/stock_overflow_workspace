import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

"""
Run Several Development Runs One After Another

    python scripts/run_all_development.py experiments/exp03_ath_exit experiments/exp04_trend_exit ...
    python scripts/run_all_development.py --all

Each experiment runs scripts/run_development.py in its own Python process (so one failure does not stop the others),
with its output in logs/<experiment>_development.log. At the end one summary line per experiment is printed: the
results-log row on success, or the last line of the error. --all runs every experiments/exp* folder that has a design
with get_candidate_design, in name order.
"""

# THE WORKSPACE ROOT
WORKSPACE_PATH = Path(__file__).resolve().parents[1]


# FUNCTION: EVERY EXPERIMENT FOLDER ON THE RUNNER
def get_all_design_folder_list():
    """
    Returns:
        list[str]: experiments/exp* folders whose design.py defines get_candidate_design
    """
    # A TEXT CHECK IS ENOUGH TO PICK THE FOLDERS
    folder_list = []
    for folder in sorted((WORKSPACE_PATH / "experiments").glob("exp*")):
        design_path = folder / "design.py"
        if design_path.is_file() and "def get_candidate_design" in design_path.read_text(encoding="utf-8"):
            folder_list.append(str(folder.relative_to(WORKSPACE_PATH)))
    return folder_list


# FUNCTION: ONE DEVELOPMENT RUN IN ITS OWN PROCESS
def run_one_dict(folder_str_in, note_str_in, n_jobs_in):
    """
    Args:
        folder_str_in (str): Experiment folder
        note_str_in (str): Trial-row note
        n_jobs_in (int | None): Candidate processes

    Returns:
        dict: folder, ok, seconds, summary
    """
    # OUTPUT TO A LOG FILE, UTF-8
    log_folder = WORKSPACE_PATH / "logs"
    log_folder.mkdir(exist_ok=True)
    log_path = log_folder / f"{Path(folder_str_in).name}_development.log"
    command_list = [sys.executable, "-u", str(WORKSPACE_PATH / "scripts" / "run_development.py"), folder_str_in, "--note", note_str_in]
    if n_jobs_in:
        command_list += ["--n-jobs", str(int(n_jobs_in))]
    environment_dict = dict(os.environ, PYTHONIOENCODING="utf-8")
    start_time = time.perf_counter()
    with open(log_path, "w", encoding="utf-8") as log_file:
        return_code = subprocess.call(command_list, cwd=str(WORKSPACE_PATH), stdout=log_file, stderr=subprocess.STDOUT, env=environment_dict)
    seconds = time.perf_counter() - start_time
    line_list = [line for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if return_code == 0:
        row_list = [line for line in line_list if line.startswith("results_row ")]
        summary_str = row_list[-1][len("results_row "):] if row_list else (line_list[-1] if line_list else "")
    else:
        summary_str = f"FAILED (exit {return_code}): {line_list[-1] if line_list else ''}  [log {log_path.name}]"
    return {"folder": folder_str_in, "ok": return_code == 0, "seconds": seconds, "summary": summary_str}


# PARSE THE COMMAND
if __name__ == "__main__":
    # ARGUMENTS
    parser = argparse.ArgumentParser(description="Run several experiments on the development view, one after another.")
    parser.add_argument("design", nargs="*", help="Experiment folders")
    parser.add_argument("--all", action="store_true", help="Every experiments/exp* folder on the runner")
    parser.add_argument("--note", default="", help="Trial-row note")
    parser.add_argument("--n-jobs", type=int, default=None, help="Candidate processes per run")
    arg_dict = parser.parse_args()
    folder_list = get_all_design_folder_list() if arg_dict.all else list(arg_dict.design)
    if not folder_list:
        raise SystemExit("no experiment folder given")
    # ONE AT A TIME, PROGRESS ON THE CONSOLE
    result_list = []
    for folder_str in folder_list:
        print(f"start {folder_str} {time.strftime('%H:%M:%S')}", flush=True)
        result_dict = run_one_dict(folder_str, arg_dict.note, arg_dict.n_jobs)
        print(f"done  {folder_str} {'ok' if result_dict['ok'] else 'FAILED'} {result_dict['seconds'] / 60:.1f} min", flush=True)
        result_list.append(result_dict)
    # THE BLOCK TO PASTE BACK
    print("\n===== development runs =====")
    for result_dict in result_list:
        print(f"{Path(result_dict['folder']).name} ({result_dict['seconds'] / 60:.1f} min): {result_dict['summary']}")
