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
from scripts.calibrate_port_old_bounds import get_kept_fold_id_set, get_replayed_return_pdf, publish_calibration_dict

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

# A DEVELOPMENT-PERIOD TABLE THE REAL DESIGNS WOULD USE. THE CALIBRATION MUST NOT REPLAY THESE DATES.
_DEVELOPMENT_PERIOD_PDF = pd.DataFrame([{"period_id": 0, "period_start": "2020-01-02", "period_end": "2020-03-31"}])
# CALLS MADE WHILE THE OLD PERIODS ARE INSTALLED
_REPLAY_CALL_LIST = []
_cache_dict = {}

# FUNCTION: THE PERIOD TABLE A DEVELOPMENT RUN WOULD BUILD
def get_bar_period_pdf(ohlcv_array_dict_in):
    """
    Development periods. The calibration replaces this for the duration of a replay.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.DataFrame: Development periods
    """
    # RETURN THE DEVELOPMENT BOUNDS
    return _DEVELOPMENT_PERIOD_PDF.copy()

# FUNCTION: RECORD THE BOUNDS AND THE PERIOD TABLE THE REPLAY ACTUALLY SAW
def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
    """
    Records one replay. The dates and the installed period table are what the calibration passed.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Bounds
        candidate_in (str): Candidate
        data_context_in: Point-in-time context

    Returns:
        dict: A finite equity curve
    """
    # THE LOOKUP IS THE MODULE GLOBAL, WHICH IS WHAT A DESIGN MODULE DOES
    period_pdf = get_bar_period_pdf(ohlcv_array_dict_in)
    _REPLAY_CALL_LIST.append((str(pd.Timestamp(date1_in).date()), str(pd.Timestamp(date2_in).date()), candidate_in,
                               str(pd.Timestamp(period_pdf["period_start"].iloc[0]).date())))
    from so import config
    equity_pdf = pd.DataFrame({"equity": [float(config.INITIAL_CAPITAL), float(config.INITIAL_CAPITAL) * 1.1]})
    return {"daily_equity_pdf": equity_pdf}

# FUNCTION: TEST THAT THE REPLAY USES THE OLD BOUNDS
def test_replay_uses_old_bounds():
    """
    A quarter that is not a development period is still replayed, on its own start and end. The tail period is not
    requested. The development period table is restored afterwards.

    Returns:
        None
    """
    # ONE SCORED QUARTER AND A TAIL. THE DEVELOPMENT TABLE HAS DIFFERENT DATES.
    import sys
    from so import config
    from so.core.holdout import get_equity_total_return_float
    _REPLAY_CALL_LIST.clear()
    period_pdf = pd.DataFrame([
        {"period_id": 7, "period_start": "2015-04-17", "period_end": "2015-07-16"},
        {"period_id": -1, "period_start": "2015-07-17", "period_end": "2015-10-14"},
    ])
    module = sys.modules[__name__]
    replay_pdf = get_replayed_return_pdf(module, {}, None, period_pdf, ["c1"])
    expected_float = get_equity_total_return_float(pd.DataFrame({"equity": [float(config.INITIAL_CAPITAL), float(config.INITIAL_CAPITAL) * 1.1]}))
    assert _REPLAY_CALL_LIST == [("2015-04-17", "2015-07-16", "c1", "2015-04-17")]
    assert list(replay_pdf["replay_return"]) == [expected_float]
    assert str(pd.Timestamp(get_bar_period_pdf({})["period_start"].iloc[0]).date()) == "2020-01-02"
    passed("calibration (replay uses the old quarter bounds, not the development periods)")

# FUNCTION: TEST THAT A QUARTER ENDING ON THE DEVELOPMENT END IS DROPPED
def test_quarter_on_development_end_is_dropped():
    """
    A quarter that ends on the development end is not a kept fold. A quarter that ends the day before is kept.

    Returns:
        None
    """
    # TWO FOLDS, ONE ON THE BOUNDARY
    import datetime
    date_pdf = pd.DataFrame([
        {"fold_id": 1, "valid_end": "2015-07-16"},
        {"fold_id": 2, "valid_end": datetime.date(2025, 7, 17)},
    ])
    assert get_kept_fold_id_set(date_pdf, datetime.date(2025, 7, 17)) == {1}
    passed("calibration (a quarter ending on the development end is dropped before a replay)")

# FUNCTION: TEST THAT AN EMPTY COMPARISON AND A NAN DO NOT PUBLISH
def test_calibration_refuses_empty_and_nan():
    """
    Zero compared rows, and a nan return, raise before the summary writer and before the note. A complete comparison
    calls both once.

    Returns:
        None
    """
    # STUBS STAND IN FOR THE SUMMARY FILE AND THE TRIAL LOG
    call_list = []
    def log_func(*args, **kwargs):
        call_list.append(("log", kwargs.get("note_str_in")))
    def write_func(summary_dict_in):
        call_list.append(("write", summary_dict_in))
    empty_pdf = pd.DataFrame(columns=["replay_return", "valid_total_return"])
    try:
        publish_calibration_dict(empty_pdf, {"compared_rows": 0}, None, log_func, write_func)
        raise AssertionError("an empty comparison was published")
    except RuntimeError as error:
        assert "0 rows" in str(error)
    nan_pdf = pd.DataFrame({"replay_return": [float("nan")], "valid_total_return": [0.01]})
    try:
        publish_calibration_dict(nan_pdf, {"compared_rows": 1}, None, log_func, write_func)
        raise AssertionError("a nan comparison was published")
    except RuntimeError as error:
        assert "nan" in str(error)
    assert call_list == []
    finite_pdf = pd.DataFrame({"replay_return": [0.01, 0.02], "valid_total_return": [0.01, 0.02]})
    publish_calibration_dict(finite_pdf, {"compared_rows": 2}, None, log_func, write_func)
    assert call_list == [("write", {"compared_rows": 2}), ("log", "old-bounds calibration; diagnostic; informs no decision")]
    passed("calibration (0 rows and nan publish nothing; a complete comparison writes the note)")

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
    test_replay_uses_old_bounds()
    test_quarter_on_development_end_is_dropped()
    test_calibration_refuses_empty_and_nan()
    test_retry_unfinished_calibration()
    print("\nAll port-queue tests passed")
