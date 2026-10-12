import json
import os
import sys
import tempfile
import pandas as pd
from pathlib import Path

"""
Workspace Tests: the port queue

The queue is exercised on synthetic notebooks and a synthetic trial table. It does not run an experiment and it does
not read the shared trial log.
"""

# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)

# IMPORT THE QUEUE
from scripts.run_port_queue import get_notebook_finished_bool, run_queue

# FUNCTION: PRINT A PASSED TEST
def passed(message_str_in):
    """
    Prints a passed test.

    Args:
        message_str_in (str): Message

    Returns:
        None
    """
    # PRINT THE MESSAGE
    print(f"✅ {message_str_in}")

# FUNCTION: A ONE-CELL NOTEBOOK
def write_notebook(path_in, finished_bool_in):
    """
    Writes a notebook that is finished or not.

    Args:
        path_in (Path): Destination
        finished_bool_in (bool): Saved outputs without an error

    Returns:
        None
    """
    # ONE CODE CELL
    cell_dict = {"cell_type": "code", "execution_count": 1 if finished_bool_in else None, "metadata": {}, "outputs": [], "source": ["print(1)\n"]}
    if finished_bool_in:
        cell_dict["outputs"] = [{"output_type": "stream", "name": "stdout", "text": ["1\n"]}]
    path_in.parent.mkdir(parents=True, exist_ok=True)
    path_in.write_text(json.dumps({"cells": [cell_dict], "metadata": {}, "nbformat": 4, "nbformat_minor": 5}), encoding="utf-8")

# FUNCTION: TEST SKIP, FAILURE AND NO REPEAT
def test_queue():
    """
    A finished step is skipped, a failure continues with the next experiment, and a second pass does not run a
    finished step again.

    Returns:
        None
    """
    # SYNTHETIC NOTEBOOKS AND A SYNTHETIC TRIAL TABLE
    with tempfile.TemporaryDirectory() as temp_dir_str:
        root_path = Path(temp_dir_str)
        finished_path = root_path / "finished.ipynb"
        pending_path = root_path / "pending.ipynb"
        later_path = root_path / "later.ipynb"
        write_notebook(finished_path, True)
        write_notebook(pending_path, False)
        write_notebook(later_path, False)
        assert get_notebook_finished_bool(finished_path) and not get_notebook_finished_bool(pending_path)
        trial_pdf = pd.DataFrame({"experiment": ["alpha_v2", "alpha_v2"], "stage": ["validation", "note"],
                                   "note": ["re-run under new rules", "old-bounds calibration; diagnostic; informs no decision"]})
        call_list = []
        def runner(step_dict):
            call_list.append((step_dict["experiment"], step_dict["step"]))
            if step_dict["experiment"] == "beta":
                raise RuntimeError("synthetic failure")
        step_list = [
            {"experiment": "alpha", "step": "development", "kind": "notebook", "notebook": str(finished_path), "experiment_name": "alpha_v2", "heartbeat": False},
            {"experiment": "alpha", "step": "calibration", "kind": "calibration", "package": "alpha", "experiment_name": "alpha_v2", "heartbeat": False},
            {"experiment": "beta", "step": "development", "kind": "notebook", "notebook": str(pending_path), "experiment_name": "beta_v2", "heartbeat": False},
            {"experiment": "beta", "step": "calibration", "kind": "calibration", "package": "beta", "experiment_name": "beta_v2", "heartbeat": False},
            {"experiment": "gamma", "step": "development", "kind": "notebook", "notebook": str(later_path), "experiment_name": "gamma_v2", "heartbeat": False},
        ]
        # THE QUEUE JOINS THE NOTEBOOK PATH TO THE WORKSPACE ROOT. POINT THE NOTEBOOKS AT ABSOLUTE PATHS BY USING A ROOT-RELATIVE TRICK:
        # get_notebook_finished_bool joins _ROOT_PATH / notebook. PASS PATHS THAT ARE ALREADY ABSOLUTE AND PATCH THE JOIN.
        status_path = root_path / "status.csv"
        from scripts import run_port_queue
        original_root = run_port_queue._ROOT_PATH
        run_port_queue._ROOT_PATH = Path("")
        try:
            written_list = run_queue(step_list, trial_pdf, status_path, runner)
        finally:
            run_port_queue._ROOT_PATH = original_root
        status_list = [(row["experiment"], row["step"], row["status"]) for row in written_list]
        assert status_list == [("alpha", "development", "skipped"), ("alpha", "calibration", "skipped"),
                               ("beta", "development", "failed"), ("beta", "calibration", "skipped"),
                               ("gamma", "development", "finished")], status_list
        assert call_list == [("beta", "development"), ("gamma", "development")]
        # THE SECOND PASS SEES GAMMA'S VALIDATION ROWS AND ITS SAVED NOTEBOOK, SO IT DOES NOT RUN GAMMA AGAIN
        write_notebook(later_path, True)
        trial_pdf = pd.concat([trial_pdf, pd.DataFrame({"experiment": ["gamma_v2"], "stage": ["validation"], "note": ["re-run under new rules"]})], ignore_index=True)
        call_list.clear()
        run_port_queue._ROOT_PATH = Path("")
        try:
            second_list = run_queue(step_list, trial_pdf, status_path, runner)
        finally:
            run_port_queue._ROOT_PATH = original_root
        assert [row["status"] for row in second_list] == ["skipped", "skipped", "skipped", "skipped", "skipped"]
        assert call_list == []
        status_pdf = pd.read_csv(status_path)
        assert list(status_pdf.columns) == ["experiment", "step", "status", "start", "end", "log_path"]
        assert (status_pdf["status"] == "finished").sum() == 1
    passed("queue (skip finished steps, continue after a failure, never run a finished step twice)")

# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    test_queue()
    print("\nAll port-queue tests passed")
