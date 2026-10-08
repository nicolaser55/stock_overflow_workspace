import os
import sys
from pathlib import Path

"""
Synthetic exp01 Step 01 Files For The Step 04 Smoke Run (agent helper; writes only to logs/smoke/)

Builds, for every session of the smoke run's synthetic random walk (scripts/smoke_notebook.py, same seed), one model
dataset file with the real TSBAR cells of the 21 distances (barrier simulation on the synthetic bars) and random values
for the 33 model features. The smoke run checks that the notebook code runs end to end; its numbers mean nothing.
"""

# DEFINE THE WORKSPACE AND THE OUTPUT FOLDER
WORKSPACE_PATH = Path(__file__).resolve().parents[1]
OUTPUT_PATH = WORKSPACE_PATH / "logs" / "smoke" / "exp01_minute_entry" / "step01_model_dataset_data"

# IF RUN AS A SCRIPT
if __name__ == "__main__":
    # ADD THE WORKSPACE AND THE TESTS FOLDER TO THE PATH
    sys.path.insert(0, str(WORKSPACE_PATH))
    sys.path.insert(0, str(WORKSPACE_PATH / "tests"))
    import numpy as np
    from so import config
    from so.core.datetime_utils import get_date_range_market_schedule_pdf
    from so.core.trade_execution import get_ohlcv_array_dict
    from so.features.barrier_labels import get_date_TSBAR_pdf, get_date_market_open_ts_dict
    from experiments.exp01_minute_entry import config as exp_config
    from synthetic_data import get_synthetic_ohlcv_pdf
    # BUILD THE SAME SYNTHETIC BARS AS THE SMOKE RUN
    start_str, end_str = os.environ.get("SMOKE_START_DATE_STR", "2019-01-02"), os.environ.get("SMOKE_END_DATE_STR", "2024-06-28")
    ohlcv_pdf = get_synthetic_ohlcv_pdf(start_str, end_str, minute_vol_in=0.0006, seed_in=7)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    date_market_open_ts_dict = get_date_market_open_ts_dict(get_date_range_market_schedule_pdf(start_str, end_str))
    # DEFINE THE MODEL FEATURES
    feature_list = config.get_feature_col_str_list(exp_config.MODEL_FEATURE_SCALE_TYPE_LIST)
    rng = np.random.default_rng(0)
    OUTPUT_PATH.mkdir(parents=True, exist_ok=True)
    # ITERATE OVER THE SESSIONS
    for date_object in ohlcv_array_dict["session_date_list"]:
        # BUILD THE TARGET CELLS OF THE SESSION
        dataset_pdf = get_date_TSBAR_pdf(ohlcv_array_dict, date_market_open_ts_dict, str(date_object), exp_config.MODEL_DELTA_LIST)
        if dataset_pdf.empty:
            continue
        dataset_pdf = dataset_pdf.drop(columns=["date"], errors="ignore")
        # ADD RANDOM FEATURES (VALID LEVELS FOR THE CATEGORICALS)
        for feature_str in feature_list:
            level_list = config.CATEGORY_LEVEL_DICT.get(feature_str)
            dataset_pdf[feature_str] = rng.choice(level_list, size=len(dataset_pdf)) if level_list is not None else rng.random(len(dataset_pdf))
        # WRITE THE FILE
        dataset_pdf.to_csv(OUTPUT_PATH / f"model_dataset_{date_object.strftime('%Y%m%d')}.csv", index=False)
    print(f"ok {len(ohlcv_array_dict['session_date_list'])} sessions -> {OUTPUT_PATH}")
