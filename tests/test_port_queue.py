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

# IMPORT THE QUEUE AND THE CALIBRATION ROW READER
from scripts.run_port_queue import get_notebook_finished_bool, run_queue
from scripts.calibrate_port_old_bounds import get_replay_return_float

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
    A finished step is skipped, a failure continues with the next experiment, and a second pass retries a step that
    did not finish. A finished step is not run again.

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
        # A DEVELOPMENT THAT FAILED BEFORE IT FINISHED IS RUN AGAIN. ITS CALIBRATION STAYS SKIPPED FOR THIS PASS.
        assert [row["status"] for row in second_list] == ["skipped", "skipped", "failed", "skipped", "skipped"]
        assert call_list == [("beta", "development")]
        status_pdf = pd.read_csv(status_path)
        assert list(status_pdf.columns) == ["experiment", "step", "status", "start", "end", "log_path"]
        assert (status_pdf["status"] == "finished").sum() == 1
    passed("queue (skip finished steps, continue after a failure, retry a step that did not finish)")

# FUNCTION: TEST THAT AN itertuples ROW CAN BE REPLAYED
def test_calibration_namedtuple_row():
    """
    The calibration loop passes DataFrame.itertuples rows. Those rows have no string index. A quarter that is not a
    development period is left unmatched and the replay is not called.

    Returns:
        None
    """
    # ONE ARCHIVED QUARTER, THE SAME OBJECT THE CALIBRATION LOOP BUILDS
    from so import config
    from so.core.holdout import get_equity_total_return_float
    archived_pdf = pd.DataFrame([{"fold_id": 1, "valid_start": "2015-01-02", "valid_end": "2015-03-31", "candidate": "c1"}])
    row = next(archived_pdf.itertuples(index=False))
    called_list = []
    class Design:
        def get_bar_period_pdf(self, ohlcv_array_dict_in):
            return pd.DataFrame([{"period_start": "2015-01-02", "period_end": "2015-03-31"}])
        def run_candidate_replay_dict(self, ohlcv_array_dict_in, date1_in, date2_in, candidate_str_in, data_context_in):
            called_list.append(candidate_str_in)
            equity_pdf = pd.DataFrame({"equity": [float(config.INITIAL_CAPITAL), float(config.INITIAL_CAPITAL) * 1.1]})
            return {"daily_equity_pdf": equity_pdf}
    # THE NAMED TUPLE USED TO RAISE TypeError: tuple indices must be integers or slices, not str
    replay_float = get_replay_return_float(Design(), {}, None, row)
    expected_float = get_equity_total_return_float(pd.DataFrame({"equity": [float(config.INITIAL_CAPITAL), float(config.INITIAL_CAPITAL) * 1.1]}))
    assert called_list == ["c1"]
    assert replay_float == expected_float
    # A QUARTER THAT IS NOT A DEVELOPMENT PERIOD DOES NOT CALL THE REPLAY
    class EmptyDesign:
        def get_bar_period_pdf(self, ohlcv_array_dict_in):
            return pd.DataFrame([{"period_start": "2016-01-04", "period_end": "2016-03-31"}])
        def run_candidate_replay_dict(self, ohlcv_array_dict_in, date1_in, date2_in, candidate_str_in, data_context_in):
            raise AssertionError("an unmatched quarter was replayed")
    assert pd.isna(get_replay_return_float(EmptyDesign(), {}, None, row))
    passed("calibration (an itertuples row replays; an unmatched quarter does not)")

# FUNCTION: TEST THAT A FINISHED DEVELOPMENT STAYS SKIPPED AND A FAILED CALIBRATION RUNS AGAIN
def test_retry_unfinished_calibration():
    """
    A development step with a finished notebook and validation rows is skipped. A calibration without its note row
    runs, including when an earlier status file says that calibration failed.

    Returns:
        None
    """
    # THE STATUS FILE FROM THE FAILED QUEUE, AND VALIDATION ROWS WITH NO CALIBRATION NOTE
    with tempfile.TemporaryDirectory() as temp_dir_str:
        root_path = Path(temp_dir_str)
        finished_path = root_path / "finished.ipynb"
        write_notebook(finished_path, True)
        status_path = root_path / "status.csv"
        status_pdf = pd.DataFrame([
            {"experiment": "alpha", "step": "development", "status": "finished", "start": "t0", "end": "t1", "log_path": "dev.log"},
            {"experiment": "alpha", "step": "calibration", "status": "failed", "start": "t1", "end": "t2", "log_path": "cal.log"},
        ])
        status_pdf.to_csv(status_path, index=False)
        trial_pdf = pd.DataFrame({"experiment": ["alpha_v2"], "stage": ["validation"], "note": ["re-run under new rules"]})
        call_list = []
        def runner(step_dict):
            call_list.append(step_dict["step"])
        step_list = [
            {"experiment": "alpha", "step": "development", "kind": "notebook", "notebook": str(finished_path),
             "experiment_name": "alpha_v2", "heartbeat": False},
            {"experiment": "alpha", "step": "calibration", "kind": "calibration", "package": "alpha",
             "experiment_name": "alpha_v2", "heartbeat": False},
        ]
        from scripts import run_port_queue
        original_root = run_port_queue._ROOT_PATH
        run_port_queue._ROOT_PATH = Path("")
        try:
            written_list = run_queue(step_list, trial_pdf, status_path, runner)
        finally:
            run_port_queue._ROOT_PATH = original_root
        assert [(row["step"], row["status"]) for row in written_list] == [("development", "skipped"), ("calibration", "finished")]
        assert call_list == ["calibration"]
    passed("queue (a finished development stays skipped; a calibration without a note row runs again)")

# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    test_queue()
    test_calibration_namedtuple_row()
    test_retry_unfinished_calibration()
    print("\nAll port-queue tests passed")
