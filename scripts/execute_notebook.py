import sys
from pathlib import Path

"""
Execute a notebook and always save it (Nicolas, 2026-10-12).

Usage: venv-main/Scripts/python.exe scripts/execute_notebook.py <notebook path>

The notebook runs top to bottom on a fresh kernel through nbclient. A cell that fails stops the run. The notebook is
written in a finally block with the outputs of the cells that ran, including the error output. That file is the
evidence of the failed run. This script does not execute the notebook a second time.
"""

# FUNCTION: EXECUTE ONE NOTEBOOK AND ALWAYS WRITE IT BACK
def execute_notebook_bool(notebook_path_str_in, kernel_name_str_in="venv-main", timeout_int_in=None):
    """
    Runs every cell. The write sits in a finally block, so a failed cell is saved with the outputs collected so far.

    Args:
        notebook_path_str_in (str): Notebook path, written in place
        kernel_name_str_in (str): Jupyter kernel name
        timeout_int_in (int | None): Seconds allowed for one cell (None waits)

    Returns:
        bool: True when every cell completed. A failed cell raises after the save.
    """
    # IMPORT THE CLIENT HERE SO A DOCSTRING READ DOES NOT START JUPYTER
    import nbformat
    from nbclient import NotebookClient
    # READ THE WHOLE NOTEBOOK BEFORE ANY CELL RUNS
    notebook_path = Path(notebook_path_str_in)
    notebook = nbformat.read(notebook_path, as_version=4)
    # RUN IN THE NOTEBOOK'S OWN FOLDER
    client = NotebookClient(notebook, timeout=timeout_int_in, kernel_name=kernel_name_str_in,
                            resources={"metadata": {"path": str(notebook_path.parent)}})
    # ONE EXECUTION. A FAILURE IS NOT TRIED AGAIN.
    cell_error = None
    try:
        client.execute()
    except Exception as exc:
        cell_error = exc
    finally:
        # THE FAILED RUN IS SAVED AS SUCH
        with notebook_path.open("w", encoding="utf-8", newline="\n") as notebook_file:
            nbformat.write(notebook, notebook_file)
        print(f"saved {notebook_path}")
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
