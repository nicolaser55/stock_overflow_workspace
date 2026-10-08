import os
import sys
from pathlib import Path

"""
Notebook Smoke Run On Synthetic Data (agent helper; no real data is read, nothing is written to the data folder)

Usage: venv-main/Scripts/python.exe scripts/smoke_notebook.py <cell source file> [<schedule module> <train years>]

Executes the cells of a notebook source file (scripts/write_notebook.py format) in one namespace, with:
    - so.core.raw_data.get_complete_ohlcv_pdf replaced by a synthetic random walk (tests/synthetic_data.py, 2019-2024);
    - the trial log and the experiment output folder redirected to logs/smoke/ (a scratch folder of the workspace);
    - optionally, <schedule module>.get_schedule_tuple wrapped with a shorter fixed window (synthetic data is short).
It checks that the notebook code runs end to end before the real run; its numbers mean nothing.
"""

# DEFINE THE WORKSPACE AND THE SCRATCH FOLDER
WORKSPACE_PATH = Path(__file__).resolve().parents[1]
SMOKE_PATH = WORKSPACE_PATH / "logs" / "smoke"

# IF RUN AS A SCRIPT
if __name__ == "__main__":
    # ADD THE WORKSPACE AND THE TESTS FOLDER TO THE PATH
    sys.path.insert(0, str(WORKSPACE_PATH))
    sys.path.insert(0, str(WORKSPACE_PATH / "tests"))
    sys.stdout.reconfigure(encoding="utf-8")
    # REDIRECT THE TRIAL LOG AND THE EXPERIMENT FOLDER
    from so import paths
    SMOKE_PATH.mkdir(parents=True, exist_ok=True)
    paths.LOCAL_TRIAL_LOG_FILE_PATH_STR = str(SMOKE_PATH / "trial_log_smoke.csv").replace("\\", "/")
    paths.LOCAL_EXPERIMENTZONE_PATH_STR = str(SMOKE_PATH).replace("\\", "/") + "/"
    # REPLACE THE RAW DATA READER BY SYNTHETIC DATA (THE CUTOFF IS HONOURED)
    import pandas as pd
    import so.core.raw_data as raw_data
    from synthetic_data import get_synthetic_ohlcv_pdf
    synthetic_ohlcv_pdf = get_synthetic_ohlcv_pdf(os.environ.get("SMOKE_START_DATE_STR", "2019-01-02"), os.environ.get("SMOKE_END_DATE_STR", "2024-06-28"), minute_vol_in=0.0006, seed_in=7)
    raw_data.get_complete_ohlcv_pdf = lambda raw_path_str_in=None, cutoff_date_str_in=None: synthetic_ohlcv_pdf[
        synthetic_ohlcv_pdf["date"] <= (pd.Timestamp(cutoff_date_str_in).date() if cutoff_date_str_in else synthetic_ohlcv_pdf["date"].max())].reset_index(drop=True)
    # OPTIONALLY SHORTEN THE FIXED WINDOW OF THE SCHEDULE
    if len(sys.argv) > 3:
        import importlib
        schedule_module = importlib.import_module(sys.argv[2])
        original_func, train_years = schedule_module.get_schedule_tuple, int(sys.argv[3])
        schedule_module.get_schedule_tuple = lambda session_date_list_in, train_years_in=None, max_fold_count_in=None: original_func(session_date_list_in, train_years, max_fold_count_in)
    # EXECUTE THE CELLS IN ONE NAMESPACE
    source_str = Path(sys.argv[1]).read_text(encoding="utf-8").replace("\r\n", "\n")
    namespace_dict = {"display": lambda *args, **kwargs: print(*[getattr(arg, "to_string", lambda: arg)() for arg in args]), "__name__": "__smoke__"}
    import plotly.graph_objects as go
    go.Figure.show = lambda self, *args, **kwargs: None
    for cell_idx, cell_str in enumerate(cell for cell in source_str.split("\n# %%\n") if cell.strip()):
        print(f"\n===== smoke cell {cell_idx} =====", flush=True)
        exec(compile(cell_str, f"<cell {cell_idx}>", "exec"), namespace_dict)
    print("\nSMOKE RUN COMPLETED")
