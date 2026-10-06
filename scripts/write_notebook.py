import sys
import json
from pathlib import Path

"""
Notebook Writer (agent helper)

Usage: venv-main/Scripts/python.exe scripts/write_notebook.py <cell source file> <notebook path>
The cell source file holds the code cells in order, separated by lines that are exactly "# %%". The notebook is written
without outputs, with the venv-main kernel (the same metadata as the existing notebooks); it is then executed top to
bottom with nbconvert (workflow.mdc), so the saved outputs are the evidence.
"""

# DEFINE THE NOTEBOOK METADATA (AS THE EXISTING NOTEBOOKS)
NOTEBOOK_METADATA_DICT = {"kernelspec": {"display_name": "Python 3.12 (venv-main)", "language": "python", "name": "venv-main"},
                          "language_info": {"name": "python", "version": "3.12.0"}}

# FUNCTION: WRITE A NOTEBOOK FROM A CELL SOURCE FILE
def write_notebook_int(source_path_str_in, notebook_path_str_in):
    """
    Splits the source file into code cells and writes an unexecuted notebook.

    Args:
        source_path_str_in (str): Cell source file ("# %%" separators)
        notebook_path_str_in (str): Notebook path to write

    Returns:
        int: Number of cells written
    """
    # READ THE SOURCE AND SPLIT IT INTO CELLS
    source_str = Path(source_path_str_in).read_text(encoding="utf-8").replace("\r\n", "\n")
    cell_str_list = [cell_str.strip("\n") for cell_str in source_str.split("\n# %%\n")]
    cell_str_list = [cell_str for cell_str in cell_str_list if cell_str.strip()]
    # BUILD THE CELLS
    cell_dict_list = [{"cell_type": "code", "execution_count": None, "id": f"cell{cell_idx:02d}", "metadata": {}, "outputs": [],
                       "source": [line + "\n" for line in cell_str.split("\n")[:-1]] + [cell_str.split("\n")[-1]]} for cell_idx, cell_str in enumerate(cell_str_list)]
    # WRITE THE NOTEBOOK
    notebook_dict = {"cells": cell_dict_list, "metadata": NOTEBOOK_METADATA_DICT, "nbformat": 4, "nbformat_minor": 5}
    Path(notebook_path_str_in).write_text(json.dumps(notebook_dict, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    # RETURN THE CELL COUNT
    return len(cell_dict_list)

# IF RUN AS A SCRIPT
if __name__ == "__main__":
    # WRITE THE NOTEBOOK
    print(f"{write_notebook_int(sys.argv[1], sys.argv[2])} cells written to {sys.argv[2]}")
