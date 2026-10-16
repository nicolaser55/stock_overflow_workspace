"""
Workspace Tests: notebook execution keeps a failed run (scripts/execute_notebook.py)

Run from the workspace root:   python tests/test_execute_notebook.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

A synthetic notebook only. No experiment, no trial log, no holdout window.
"""

import os
import sys
import tempfile

# ADD THE SCRIPTS FOLDER SO THE EXECUTOR IMPORTS WITHOUT A PACKAGE
SCRIPT_PATH_STR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPT_PATH_STR)
import nbformat
from execute_notebook import execute_notebook_bool

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints the passing line for one test.

    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"  {name_str_in}")

# FUNCTION: WRITE A TWO-CELL NOTEBOOK AND RETURN ITS PATH
def write_notebook_str(directory_str_in, source_list_in, file_name_str_in):
    """
    Writes an unexecuted notebook.

    Args:
        directory_str_in (str): Folder
        source_list_in (list[str]): One source string per code cell
        file_name_str_in (str): File name

    Returns:
        str: Notebook path
    """
    # BUILD THE CELLS AND THE NOTEBOOK
    cell_list = [nbformat.v4.new_code_cell(source_str) for source_str in source_list_in]
    notebook = nbformat.v4.new_notebook(cells=cell_list, metadata={"kernelspec": {"display_name": "venv-main", "language": "python", "name": "venv-main"}})
    notebook_path_str = os.path.join(directory_str_in, file_name_str_in)
    # WRITE IT BEFORE EXECUTION
    with open(notebook_path_str, "w", encoding="utf-8", newline="\n") as notebook_file:
        nbformat.write(notebook, notebook_file)
    return notebook_path_str

# FUNCTION: THE TEXT A CELL PRINTED
def get_stream_text_str(cell_in):
    """
    Joins the stream outputs of one cell.

    Args:
        cell_in: Notebook cell

    Returns:
        str: Printed text
    """
    # KEEP STREAM OUTPUTS ONLY
    text_list = []
    for output in cell_in.get("outputs", []):
        if output.get("output_type") == "stream":
            text_value = output.get("text", "")
            text_list.append(text_value if isinstance(text_value, str) else "".join(text_value))
    return "".join(text_list)

# FUNCTION: A FAILED SECOND CELL IS STILL ON DISK, WITH THE FIRST CELL'S OUTPUT
def test_failed_run_is_saved():
    """
    Cell 0 prints. Cell 1 raises. The file written by the finally block holds both.

    Returns:
        None
    """
    # A TEMPORARY NOTEBOOK, NOT AN EXPERIMENT
    with tempfile.TemporaryDirectory(prefix="so_nb_fail_") as directory_str:
        notebook_path_str = write_notebook_str(directory_str, ["print('kept-marker')", "raise RuntimeError('synthetic failure')"], "failed.ipynb")
        progress_path_str = os.path.join(directory_str, "progress.log")
        # THE EXECUTOR RAISES AFTER THE SAVE
        raised_bool = False
        try:
            execute_notebook_bool(notebook_path_str, timeout_int_in=120, progress_path_str_in=progress_path_str)
        except Exception as exc:
            raised_bool = True
            assert type(exc).__name__ == "CellExecutionError", type(exc).__name__
        assert raised_bool
        # READ THE FILE FROM DISK, NOT THE OBJECT THE CLIENT HELD
        saved = nbformat.read(notebook_path_str, as_version=4)
        assert saved.cells[0].get("execution_count") == 1
        assert "kept-marker" in get_stream_text_str(saved.cells[0])
        error_list = [output for output in saved.cells[1].get("outputs", []) if output.get("output_type") == "error"]
        assert len(error_list) == 1 and error_list[0].get("ename") == "RuntimeError"
        assert saved.cells[1].get("execution_count") == 2
    # THE CHECK PASSED
    passed("a failed notebook is saved with the earlier output and the error")

# FUNCTION: A NOTEBOOK THAT COMPLETES IS SAVED WITH ITS OUTPUT
def test_completed_run_is_saved():
    """
    One cell that prints. The saved notebook holds that print.

    Returns:
        None
    """
    # A TEMPORARY NOTEBOOK
    with tempfile.TemporaryDirectory(prefix="so_nb_ok_") as directory_str:
        notebook_path_str = write_notebook_str(directory_str, ["print('ok-marker')"], "ok.ipynb")
        progress_path_str = os.path.join(directory_str, "progress.log")
        # THE EXECUTOR RETURNS AFTER THE SAVE
        assert execute_notebook_bool(notebook_path_str, timeout_int_in=120, progress_path_str_in=progress_path_str) is True
        saved = nbformat.read(notebook_path_str, as_version=4)
        assert saved.cells[0].get("execution_count") == 1
        assert "ok-marker" in get_stream_text_str(saved.cells[0])
    # THE CHECK PASSED
    passed("a completed notebook is saved with its output")

# FUNCTION: THE PROGRESS LINE IS ON DISK BEFORE THE CELL RETURNS
def test_progress_line_is_flushed_before_the_cell_returns():
    """
    The cell reads the progress log and finds its own start line. That line was flushed before the cell ran.

    Returns:
        None
    """
    # A CELL THAT READS THE LOG THE EXECUTOR IS WRITING
    with tempfile.TemporaryDirectory(prefix="so_nb_progress_") as directory_str:
        progress_path_str = os.path.join(directory_str, "progress.log")
        source_str = "import os\ntext = open(os.environ['SO_NOTEBOOK_PROGRESS_LOG'], encoding='utf-8').read()\nassert 'cell 0 start' in text\nprint('saw-progress')\n"
        notebook_path_str = write_notebook_str(directory_str, [source_str], "progress.ipynb")
        assert execute_notebook_bool(notebook_path_str, timeout_int_in=120, progress_path_str_in=progress_path_str) is True
        saved = nbformat.read(notebook_path_str, as_version=4)
        assert "saw-progress" in get_stream_text_str(saved.cells[0])
        progress_text_str = open(progress_path_str, encoding="utf-8").read()
        assert "cell 0 start" in progress_text_str and "cell 0 done" in progress_text_str
    # THE CHECK PASSED
    passed("a progress line is flushed before the cell returns")

# RUN THE SUITE
if __name__ == "__main__":
    test_failed_run_is_saved()
    test_completed_run_is_saved()
    test_progress_line_is_flushed_before_the_cell_returns()
    print("\nAll notebook-execution tests passed")
