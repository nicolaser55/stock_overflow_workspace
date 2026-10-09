import os
import sys
from pathlib import Path

"""
Notebook Smoke Run On Synthetic Data (agent helper; no real data is read, nothing is written to the data folder)

Usage: venv-main/Scripts/python.exe scripts/smoke_notebook.py <cell source file> [<schedule module> <train years>]

Executes the cells of a notebook source file (scripts/write_notebook.py format) in one namespace, with:
    - so.core.raw_data.get_complete_ohlcv_pdf replaced by a synthetic random walk (tests/synthetic_data.py, 2019-2024);
    - the VIX loaders of so.features.vix_features replaced by synthetic index bars on the same dates (cutoff checked);
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
    # REPLACE THE VIX LOADERS BY SYNTHETIC INDEX BARS (THE CUTOFF CHECK OF THE REAL LOADERS IS KEPT)
    import so.features.vix_features as vix_features
    from synthetic_data import get_synthetic_index_daily_pdf, get_synthetic_index_minute_pdf
    synthetic_date1_str, synthetic_date2_str = str(synthetic_ohlcv_pdf["date"].min()), str(synthetic_ohlcv_pdf["date"].max())
    synthetic_vix_dict = {("vix", "daily"): get_synthetic_index_daily_pdf(synthetic_date1_str, synthetic_date2_str, 18.0, 41),
                          ("vix3m", "daily"): get_synthetic_index_daily_pdf(synthetic_date1_str, synthetic_date2_str, 20.0, 42)}
    synthetic_minute_cache_dict = {}
    def read_synthetic_vix_daily_pdf(series_str_in, cutoff_date_str_in, raw_path_str_in=None):
        cutoff_date = vix_features.check_cutoff_date(cutoff_date_str_in)
        bar_pdf = synthetic_vix_dict[(series_str_in, "daily")]
        return bar_pdf[bar_pdf["date"] <= cutoff_date].reset_index(drop=True)
    def read_synthetic_vix_1min_pdf(series_str_in, cutoff_date_str_in, start_date_str_in=None, raw_path_str_in=None):
        cutoff_date = vix_features.check_cutoff_date(cutoff_date_str_in)
        if series_str_in not in synthetic_minute_cache_dict:
            synthetic_minute_cache_dict[series_str_in] = get_synthetic_index_minute_pdf(synthetic_date1_str, synthetic_date2_str, 18.0 if series_str_in == "vix" else 20.0, 43 if series_str_in == "vix" else 44)
        bar_pdf = synthetic_minute_cache_dict[series_str_in]
        start_date = pd.Timestamp(start_date_str_in).date() if start_date_str_in else bar_pdf["date"].min()
        return bar_pdf[(bar_pdf["date"] <= cutoff_date) & (bar_pdf["date"] >= start_date)].reset_index(drop=True)
    vix_features.read_vix_daily_pdf, vix_features.read_vix_1min_pdf = read_synthetic_vix_daily_pdf, read_synthetic_vix_1min_pdf
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
