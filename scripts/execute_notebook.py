import os
import sys
import threading
from datetime import datetime
from pathlib import Path

"""
Execute a notebook and always save it (Nicolas, 2026-10-12).

Usage: venv-main/Scripts/python.exe scripts/execute_notebook.py <notebook path>

The notebook runs top to bottom on a fresh kernel through nbclient. A cell that fails stops the run. The notebook is
written in a finally block with the outputs of the cells that ran, including the error output. That file is the
evidence of the failed run. This script does not execute the notebook a second time. A separate progress log is
flushed as each cell starts and ends. That log is not an input to the notebook.
"""

# THE WORKSPACE ROOT, AND HOW OFTEN A LONG CELL WRITES A PROGRESS LINE
_ROOT_PATH = Path(__file__).resolve().parents[1]
_HEARTBEAT_SECOND_COUNT = 30 * 60

# FUNCTION: APPEND ONE PROGRESS LINE AND FLUSH IT
def write_progress_line(progress_path_in, message_str_in):
    """
    Appends one line to the progress log and flushes it, so a reader sees it before the cell returns.

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

# FUNCTION: THE DEFAULT PROGRESS LOG FOR ONE NOTEBOOK
def get_progress_path(notebook_path_in):
    """
    The progress log in logs/, named from the notebook. It is not written beside the notebook.

    Args:
        notebook_path_in (Path): Notebook

    Returns:
        Path: Progress log
    """
    # ONE FILE PER NOTEBOOK STEM
    return _ROOT_PATH / "logs" / f"{notebook_path_in.stem}.progress.log"

# FUNCTION: EXECUTE ONE NOTEBOOK AND ALWAYS WRITE IT BACK
def execute_notebook_bool(notebook_path_str_in, kernel_name_str_in="venv-main", timeout_int_in=None, progress_path_str_in=None):
    """
    Runs every cell. The write sits in a finally block, so a failed cell is saved with the outputs collected so far.
    The progress log receives a line before each cell runs. The notebook source and the kernel are unchanged.

    Args:
        notebook_path_str_in (str): Notebook path, written in place
        kernel_name_str_in (str): Jupyter kernel name
        timeout_int_in (int | None): Seconds allowed for one cell (None waits)
        progress_path_str_in (str | None): Progress log (None = logs/<notebook stem>.progress.log)

    Returns:
        bool: True when every cell completed. A failed cell raises after the save.
    """
    # IMPORT THE CLIENT HERE SO A DOCSTRING READ DOES NOT START JUPYTER
    import nbformat
    from nbclient import NotebookClient
    # READ THE WHOLE NOTEBOOK BEFORE ANY CELL RUNS
    notebook_path = Path(notebook_path_str_in)
    notebook = nbformat.read(notebook_path, as_version=4)
    progress_path = Path(progress_path_str_in) if progress_path_str_in else get_progress_path(notebook_path)
    # THE KERNEL CAN READ THE PATH. NO NOTEBOOK IN THIS PROJECT READS IT.
    previous_progress_str = os.environ.get("SO_NOTEBOOK_PROGRESS_LOG")
    os.environ["SO_NOTEBOOK_PROGRESS_LOG"] = str(progress_path)
    write_progress_line(progress_path, f"start {notebook_path.name} {datetime.now().isoformat(timespec='seconds')}")

    # A LINE BEFORE THE CELL RUNS, AND A LINE WHEN IT RETURNS. execute() CALLS THE ASYNC METHOD.
    class ProgressNotebookClient(NotebookClient):
        async def async_execute_cell(self, cell, cell_index, execution_count=None, store_history=True):
            write_progress_line(progress_path, f"cell {cell_index} start")
            try:
                return await super().async_execute_cell(cell, cell_index, execution_count=execution_count, store_history=store_history)
            finally:
                write_progress_line(progress_path, f"cell {cell_index} done")

    # RUN IN THE NOTEBOOK'S OWN FOLDER
    client = ProgressNotebookClient(notebook, timeout=timeout_int_in, kernel_name=kernel_name_str_in,
                                    resources={"metadata": {"path": str(notebook_path.parent)}})
    # A LONG CELL STILL WRITES A LINE WHILE IT RUNS
    stop_event = threading.Event()

    def heartbeat():
        while not stop_event.wait(_HEARTBEAT_SECOND_COUNT):
            write_progress_line(progress_path, f"progress {datetime.now().isoformat(timespec='seconds')} still running")

    threading.Thread(target=heartbeat, daemon=True).start()
    # ONE EXECUTION. A FAILURE IS NOT TRIED AGAIN.
    cell_error = None
    try:
        try:
            client.execute()
        except Exception as exc:
            cell_error = exc
        finally:
            # THE FAILED RUN IS SAVED AS SUCH
            with notebook_path.open("w", encoding="utf-8", newline="\n") as notebook_file:
                nbformat.write(notebook, notebook_file)
            print(f"saved {notebook_path}")
    finally:
        stop_event.set()
        if previous_progress_str is None:
            os.environ.pop("SO_NOTEBOOK_PROGRESS_LOG", None)
        else:
            os.environ["SO_NOTEBOOK_PROGRESS_LOG"] = previous_progress_str
    # THE SAVE HAS ALREADY HAPPENED
    if cell_error is not None:
        raise cell_error
    return True

# IF RUN AS A SCRIPT
if __name__ == "__main__":
    # REQUIRE THE NOTEBOOK PATH
    if len(sys.argv) != 2:
        print("usage: python scripts/execute_notebook.py <notebook path>")
        raise SystemExit(2)
    # EXECUTE, THEN REPORT A FAILURE THAT WAS ALREADY WRITTEN
    try:
        execute_notebook_bool(sys.argv[1])
    except Exception as exc:
        print(f"notebook execution failed after the notebook was saved: {exc}", file=sys.stderr)
        raise SystemExit(1)
