import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp01_minute_entry import config as exp_config
# IMPORT PATHS
from so import paths
# IMPORT MARKET DATETIME FUNCTIONS
from so.core.datetime_utils import ny_tz
# IMPORT LOCAL FILE MANAGEMENT FUNCTIONS
from so.core.local_file_management import check_file_exists, read_csv_file_from_path, get_date_range_file_path_list
# IMPORT BARRIER LABEL FUNCTIONS
from so.features.barrier_labels import add_TSBAR_label_cols, get_delta_col_str, format_TSBAR_pdf
# IMPORT TRADE EXECUTION FUNCTIONS
from so.core.trade_execution import get_ts_bar_idx_arr

"""
Model Dataset (exp01 step 01; written to store04_experiments/exp01_minute_entry/step01_model_dataset_data/)

Joins, for every decision bar, the feature rows (TSIND step02, TSSEG step03, TSCTX step04) with the barrier targets
(TSBAR step05). The feature row and the target row share the same timestamp: decision_ts (the entry is the next bar).

The saved daily files keep EVERY eligible decision row (no sampling) so that:
    - validation / test simulations can decide at every eligible minute (as a live model would);
    - the training sampling scheme can be changed in the experiment config without regenerating the dataset.
"""

# DEFINE THE STEP FILE NAME PREFIX DICTIONARY
STEP_FILE_PREFIX_DICT = {
    "TSIND": "TSIND_data",
    "TSSEG": "TSSEG_data",
    "TSCTX": "TSCTX_data",
    "TSBAR": "TSBAR_data",
    "MDS": "model_dataset",
}

# DEFINE THE STEP FILE PATH DICTIONARY
STEP_FILE_PATH_DICT = {
    "TSIND": paths.LOCAL_TSIND_DATA_FILE_PATH_STR,
    "TSSEG": paths.LOCAL_TSSEG_DATA_FILE_PATH_STR,
    "TSCTX": paths.LOCAL_TSCTX_DATA_FILE_PATH_STR,
    "TSBAR": paths.LOCAL_TSBAR_DATA_FILE_PATH_STR,
    "MDS": paths.get_experiment_data_path_str(exp_config.EXPERIMENT_NAME, "step01_model_dataset_data"),
}

# FUNCTION: GET THE FILE PATH OF A STEP AT A DATE
def get_step_date_file_path_str(step_str_in, date_str_in):
    """
    Builds the daily file path of a step ('{prefix}_YYYYMMDD.csv').

    Args:
        step_str_in (str): Step key of STEP_FILE_PATH_DICT ("TSIND", "TSSEG", "TSCTX", "TSBAR", "MDS")
        date_str_in (str): Date 'YYYY-MM-DD'

    Returns:
        str: File path
    """
    # DEFINE THE DATE NAME
    date_name_str = pd.to_datetime(date_str_in).strftime("%Y%m%d")
    # RETURN THE FILE PATH
    return f"{STEP_FILE_PATH_DICT[step_str_in]}{STEP_FILE_PREFIX_DICT[step_str_in]}_{date_name_str}.csv"

# FUNCTION: READ THE FILE OF A STEP AT A DATE
def read_step_date_pdf(step_str_in, date_str_in):
    """
    Reads the daily file of a step and converts its timestamp column(s) to New York timezone.

    Args:
        step_str_in (str): Step key of STEP_FILE_PATH_DICT
        date_str_in (str): Date 'YYYY-MM-DD'

    Returns:
        pd.DataFrame: File content (empty DataFrame if the file does not exist)
    """
    # DEFINE THE FILE PATH
    file_path_str = get_step_date_file_path_str(step_str_in, date_str_in)
    # IF THE FILE DOES NOT EXIST
    if not check_file_exists(file_path_str):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # READ THE FILE
    read_pdf = read_csv_file_from_path(file_path_str, alert_in=False)
    # ITERATE OVER THE POSSIBLE TIMESTAMP COLUMNS
    for col_str in ["timestamp", "decision_ts", "entry_ts"]:
        # IF THE COLUMN EXISTS
        if col_str in read_pdf.columns:
            # CONVERT THE COLUMN
            read_pdf[col_str] = pd.to_datetime(read_pdf[col_str], utc=True).dt.tz_convert(ny_tz)
    # RETURN DATAFRAME
    return read_pdf

# FUNCTION: GENERATE THE DATE MODEL DATASET DATAFRAME
def get_date_model_dataset_pdf(date_str_in, feature_col_str_list_in=None):
    """
    Joins the feature rows (TSIND, TSSEG, TSCTX) with the barrier target rows (TSBAR) of one session.

    Args:
        date_str_in (str): Session date 'YYYY-MM-DD'
        feature_col_str_list_in (list[str] | None): Feature columns to keep (None keeps every registered feature)

    Returns:
        pd.DataFrame: One row per decision bar: decision_ts, entry_ts, entry_price, horizon_complete, rr_ratio,
                      features, encoded TSBAR delta cells (empty DataFrame if any step file is missing)
    """
    # DEFINE THE FEATURE COLUMNS
    feature_col_str_list = feature_col_str_list_in if feature_col_str_list_in is not None else list(config.FEATURE_REGISTRY_DICT.keys())
    # READ THE TARGET ROWS
    TSBAR_pdf = read_step_date_pdf("TSBAR", date_str_in)
    # IF THE TARGET ROWS ARE MISSING
    if TSBAR_pdf.empty:
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # DROP THE DATE COLUMN (ADDED BACK BY THE GENERATOR)
    dataset_pdf = TSBAR_pdf.drop(columns=["date"], errors="ignore")
    # ITERATE OVER THE FEATURE STEPS
    for step_str in ["TSIND", "TSSEG", "TSCTX"]:
        # READ THE FEATURE ROWS
        step_pdf = read_step_date_pdf(step_str, date_str_in)
        # IF THE FEATURE ROWS ARE MISSING
        if step_pdf.empty:
            # DISPLAY INFORMATION
            print(f"\t⚠️ Missing {step_str} data for '{date_str_in}'")
            # RETURN EMPTY DATAFRAME
            return pd.DataFrame()
        # COLLECT THE FEATURE COLUMNS OF THIS STEP
        step_col_str_list = [col for col in feature_col_str_list
                             if config.FEATURE_REGISTRY_DICT.get(col, {}).get("source") == step_str and col in step_pdf.columns]
        # RENAME THE TIMESTAMP TO THE DECISION TIMESTAMP AND KEEP THE FEATURES
        step_pdf = step_pdf[["timestamp"] + step_col_str_list].rename(columns={"timestamp": "decision_ts"})
        # JOIN THE FEATURES TO THE DECISION ROWS
        dataset_pdf = dataset_pdf.merge(step_pdf, on="decision_ts", how="left")
    # ORDER THE COLUMNS (KEYS, FEATURES, TARGET CELLS)
    key_col_str_list = ["decision_ts", "entry_ts", "entry_price", "horizon_complete", "rr_ratio"]
    delta_col_str_list = [col for col in TSBAR_pdf.columns if col not in key_col_str_list + ["date"]]
    present_feature_col_str_list = [col for col in feature_col_str_list if col in dataset_pdf.columns]
    # RETURN DATAFRAME
    return dataset_pdf[key_col_str_list + present_feature_col_str_list + delta_col_str_list]

# FUNCTION: APPLY THE SAMPLING SCHEME
def apply_sampling_pdf(dataset_pdf_in, sampling_mode_str_in=exp_config.SAMPLING_MODE, sample_every_n_minutes_in=exp_config.SAMPLE_EVERY_N_MINUTES):
    """
    Reduces overlapping training rows.

    Modes:
        "all"       keep every decision row
        "interval"  keep the decisions whose entry is every N minutes after the first allowed entry (10:00, 10:15, ...)
        "event"     keep the decisions on bars where a new swing is confirmed (TSSEG 'seg' changes within the session)

    Args:
        dataset_pdf_in (pd.DataFrame): Model dataset rows (entry_ts required; 'seg' required for "event")
        sampling_mode_str_in (str): Sampling mode
        sample_every_n_minutes_in (int): Minutes between sampled entries ("interval" mode)

    Returns:
        pd.DataFrame: Sampled rows
    """
    # IF THE MODE KEEPS EVERY ROW
    if sampling_mode_str_in == "all":
        # RETURN THE DATAFRAME
        return dataset_pdf_in
    # IF THE MODE IS INTERVAL
    if sampling_mode_str_in == "interval":
        # CALCULATE THE MINUTE OF THE DAY OF EVERY ENTRY
        entry_minute_series = dataset_pdf_in["entry_ts"].dt.hour * 60 + dataset_pdf_in["entry_ts"].dt.minute
        # CALCULATE THE FIRST ALLOWED ENTRY MINUTE OF THE DAY (09:30 OPEN + START DELAY)
        first_entry_minute = 9 * 60 + 30 + config.TRADING_START_DELAY_MINUTES
        # RETURN THE ROWS ON THE INTERVAL GRID
        return dataset_pdf_in[((entry_minute_series - first_entry_minute) % sample_every_n_minutes_in) == 0]
    # IF THE MODE IS EVENT
    if sampling_mode_str_in == "event":
        # COLLECT THE SESSION DATE OF EVERY ROW
        date_series = dataset_pdf_in["decision_ts"].dt.date
        # RETURN THE ROWS WHERE THE SEGMENT COUNTER CHANGED
        return dataset_pdf_in[dataset_pdf_in.groupby(date_series)["seg"].diff().fillna(0) != 0]
    # RAISE AN ERROR
    raise ValueError(f"Unknown sampling mode '{sampling_mode_str_in}'")

# FUNCTION: READ THE MODEL DATASET WITHIN A DATE RANGE
def read_model_dataset_pdf(date1_str_in, date2_str_in, delta_list_in=exp_config.MODEL_DELTA_LIST,
                           sampling_mode_str_in="all", sample_every_n_minutes_in=exp_config.SAMPLE_EVERY_N_MINUTES,
                           alert_in=True):
    """
    Reads the daily model dataset files of a date range, samples each file and parses the labels of the requested deltas.
    Sampling is applied file by file to keep memory low.

    Args:
        date1_str_in (str): Start date (inclusive)
        date2_str_in (str): End date (inclusive)
        delta_list_in (list[float]): Deltas whose label columns are parsed (other raw delta cells are dropped)
        sampling_mode_str_in (str): Sampling mode (see apply_sampling_pdf); use "all" for validation and test windows
        sample_every_n_minutes_in (int): Interval for the "interval" mode
        alert_in (bool): Display progress

    Returns:
        pd.DataFrame: Dataset rows with label columns (y_tp_<d>, net_return_<d>, exit_bar_count_<d>, exit_reason_<d>)
    """
    # COLLECT THE FILE PATHS OF THE DATE RANGE
    file_path_str_list = get_date_range_file_path_list(STEP_FILE_PATH_DICT["MDS"], date1_str_in, date2_str_in)
    # DISPLAY INFORMATION
    print(f"Reading {len(file_path_str_list):,} model dataset files ({date1_str_in} -> {date2_str_in}, sampling: '{sampling_mode_str_in}')") if alert_in else None
    # LIST TO HOLD THE DATAFRAMES
    pdf_list = []
    # ITERATE OVER THE FILE PATHS
    for file_path_str in file_path_str_list:
        # READ THE FILE
        read_pdf = pd.read_csv(file_path_str)
        # CONVERT THE TIMESTAMPS
        read_pdf = format_TSBAR_pdf(read_pdf)
        # APPLY THE SAMPLING SCHEME
        read_pdf = apply_sampling_pdf(read_pdf, sampling_mode_str_in, sample_every_n_minutes_in)
        # PARSE THE LABELS AND DROP THE RAW CELLS
        read_pdf = add_TSBAR_label_cols(read_pdf, delta_list_in, drop_cell_cols_in=True)
        # APPEND THE DATAFRAME
        pdf_list.append(read_pdf)
    # IF THERE ARE NO DATAFRAMES
    if not pdf_list:
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # CONCATENATE AND RETURN THE DATAFRAME
    return pd.concat(pdf_list, ignore_index=True)

# FUNCTION: GET THE MODEL FEATURE COLUMNS
def get_model_feature_col_str_list(dataset_pdf_in, scale_type_str_list_in=exp_config.MODEL_FEATURE_SCALE_TYPE_LIST):
    """
    Returns the registered features of the allowed scale types that exist in the dataset.

    Args:
        dataset_pdf_in (pd.DataFrame): Model dataset rows
        scale_type_str_list_in (list[str]): Allowed scale types (exp_config.MODEL_FEATURE_SCALE_TYPE_LIST)

    Returns:
        list[str]: Feature column names
    """
    # RETURN THE FEATURE COLUMNS
    return [col for col in config.get_feature_col_str_list(scale_type_str_list_in) if col in dataset_pdf_in.columns]

# FUNCTION: ENCODE THE FEATURE COLUMNS FOR A MODEL
def encode_feature_pdf(dataset_pdf_in, feature_col_str_list_in):
    """
    Converts the feature columns to model inputs: categorical features become pandas categoricals with the fixed
    levels of config.CATEGORY_LEVEL_DICT (identical codes in every fold), every other feature becomes float with
    infinite values replaced by NaN (LightGBM handles NaN natively).

    Args:
        dataset_pdf_in (pd.DataFrame): Model dataset rows
        feature_col_str_list_in (list[str]): Feature columns

    Returns:
        pd.DataFrame: Encoded feature matrix (same index as the input)
    """
    # DICTIONARY TO HOLD THE ENCODED COLUMNS
    encoded_col_dict = {}
    # ITERATE OVER THE FEATURE COLUMNS
    for col_str in feature_col_str_list_in:
        # IF THE FEATURE IS CATEGORICAL
        if config.FEATURE_REGISTRY_DICT[col_str]["scale_type"] == "categorical":
            # ENCODE WITH THE FIXED CATEGORY LEVELS
            encoded_col_dict[col_str] = pd.Categorical(dataset_pdf_in[col_str], categories=config.CATEGORY_LEVEL_DICT[col_str])
        # IF THE FEATURE IS NUMERIC
        else:
            # CONVERT TO FLOAT AND REPLACE INFINITE VALUES
            encoded_col_dict[col_str] = pd.to_numeric(dataset_pdf_in[col_str], errors="coerce").replace([np.inf, -np.inf], np.nan)
    # RETURN THE ENCODED DATAFRAME
    return pd.DataFrame(encoded_col_dict, index=dataset_pdf_in.index)

# FUNCTION: CALCULATE THE AVERAGE UNIQUENESS SAMPLE WEIGHTS
def get_uniqueness_weight_arr(dataset_pdf_in, delta_float_in, ohlcv_array_dict_in):
    """
    Calculates the average uniqueness of each labeled row (Lopez de Prado): for every bar of the row's trade
    (entry bar to exit bar), 1 / number of rows whose trades are open on that bar, averaged over the trade.
    Rows whose trades overlap many others get smaller weights. Weights are normalized to a mean of 1.

    Args:
        dataset_pdf_in (pd.DataFrame): Labeled dataset rows (entry_ts and exit_bar_count_<d> required)
        delta_float_in (float): Delta whose trade lifespans are used
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict

    Returns:
        np.ndarray: Sample weights (NaN for unresolved rows)
    """
    # DEFINE THE EXIT BAR COUNT COLUMN
    exit_bar_count_arr = dataset_pdf_in[f"exit_bar_count_{get_delta_col_str(delta_float_in)}"].to_numpy(dtype=int)
    # COLLECT THE ENTRY BAR INDEXES
    entry_idx_arr = get_ts_bar_idx_arr(ohlcv_array_dict_in, dataset_pdf_in["entry_ts"])
    # DEFINE THE VALID ROWS (RESOLVED AND FOUND IN THE DATA)
    valid_mask = (exit_bar_count_arr >= 0) & (entry_idx_arr >= 0)
    # PRE-DEFINE THE WEIGHTS
    weight_arr = np.full(len(dataset_pdf_in), np.nan)
    # IF THERE ARE NO VALID ROWS
    if not valid_mask.any():
        # RETURN THE WEIGHTS
        return weight_arr
    # COLLECT THE START AND END BAR OF EVERY VALID TRADE
    start_arr = entry_idx_arr[valid_mask]
    end_arr = start_arr + exit_bar_count_arr[valid_mask]
    # SHIFT THE BAR INDEXES TO START AT 0
    offset = start_arr.min()
    start_arr, end_arr = start_arr - offset, end_arr - offset
    # COUNT THE NUMBER OF OPEN TRADES ON EVERY BAR (DIFFERENCE ARRAY)
    concurrency_arr = np.zeros(end_arr.max() + 2)
    np.add.at(concurrency_arr, start_arr, 1)
    np.add.at(concurrency_arr, end_arr + 1, -1)
    concurrency_arr = np.cumsum(concurrency_arr)[:-1]
    # CALCULATE THE CUMULATIVE SUM OF 1 / CONCURRENCY
    inverse_cumsum_arr = np.concatenate([[0.0], np.cumsum(np.where(concurrency_arr > 0, 1.0 / np.maximum(concurrency_arr, 1), 0.0))])
    # CALCULATE THE AVERAGE UNIQUENESS OF EVERY TRADE
    uniqueness_arr = (inverse_cumsum_arr[end_arr + 1] - inverse_cumsum_arr[start_arr]) / (end_arr - start_arr + 1)
    # NORMALIZE THE WEIGHTS TO A MEAN OF 1
    weight_arr[valid_mask] = uniqueness_arr / uniqueness_arr.mean()
    # RETURN THE WEIGHTS
    return weight_arr
