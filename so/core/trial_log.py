import pandas as pd
import numpy as np
import json
import hashlib
from datetime import datetime
# IMPORT THE SHARED CONFIGURATION
from so import config
# IMPORT PATHS
from so import paths
# IMPORT LOCAL FILE MANAGEMENT FUNCTIONS
from so.core.local_file_management import check_file_exists, read_csv_file_from_path, write_csv_file_to_path

"""
Trial Log (one file shared by every experiment: paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)

Every experiment appends one row per evaluated configuration: each exploration rule, each signal check, each validation
candidate of each fold and each test evaluation. The log is the evidence of how many configurations were tried before a
result was obtained (multiple testing) and of whether a test window had already been seen. Never edit or delete rows.

The trial log of the previous workspace (4,089 entries, 2026-10-03 -> 2026-10-05) is kept as
records/legacy/trial_log_legacy_20261005.csv; those trials still count in the thesis.

Columns:
    trial_id                unique id (logged timestamp + config hash)
    logged_ts               local time of the log entry
    experiment              experiment name (config.EXPERIMENT_NAME of the experiment, e.g. "exp02_stop_reentry")
    protocol_version        PROTOCOL_VERSION of the experiment config
    stage                   "exploration", "signal_check", "validation", "test" or "note"
    fold_id                 walk-forward fold id (NaN if not applicable)
    train_start/train_end   training window (the evaluated training window when the setting names one)
    valid_start/valid_end   validation window
    test_start/test_end     test window
    test_window_touched     True if this entry looked at test results
    config_hash             md5 of so.config + the experiment config (identical hash = identical constants)
    setting_json            selected / evaluated settings
    metric_json             metrics of the entry
    note                    free text
"""

# FUNCTION: GET THE CONSTANT SNAPSHOT OF A CONFIGURATION MODULE
def get_module_constant_dict(module_in):
    """
    Collects every uppercase constant of a module.

    Args:
        module_in (module): Configuration module (so.config or an experiment config)

    Returns:
        dict: Constant name -> value
    """
    # RETURN THE UPPERCASE CONSTANTS
    return {key_str: value for key_str, value in vars(module_in).items() if key_str.isupper()}

# FUNCTION: GET THE CONFIGURATION HASH OF AN EXPERIMENT
def get_config_hash_str(experiment_config_in):
    """
    Hashes the shared configuration (so.config) together with the experiment configuration, so that identical constants
    produce identical hashes and a change to either file changes the hash.

    Args:
        experiment_config_in (module): The experiment's config module (experiments.expNN_<name>.config)

    Returns:
        str: 10-character md5 hash
    """
    # BUILD THE SNAPSHOT
    snapshot_dict = {"shared": get_module_constant_dict(config), "experiment": get_module_constant_dict(experiment_config_in)}
    # SERIALIZE THE SNAPSHOT
    config_json_str = json.dumps(snapshot_dict, sort_keys=True, default=str)
    # RETURN THE HASH
    return hashlib.md5(config_json_str.encode("utf-8")).hexdigest()[:10]

# FUNCTION: CONVERT VALUES TO JSON-SAFE VALUES
def to_json_safe(value_in):
    """
    Converts numpy and pandas values to JSON-serializable Python values.

    Args:
        value_in: Any value

    Returns:
        JSON-serializable value
    """
    # IF THE VALUE IS A DICTIONARY
    if isinstance(value_in, dict):
        # CONVERT EVERY VALUE
        return {str(key): to_json_safe(value) for key, value in value_in.items()}
    # IF THE VALUE IS A LIST OR TUPLE
    if isinstance(value_in, (list, tuple)):
        # CONVERT EVERY ITEM
        return [to_json_safe(value) for value in value_in]
    # IF THE VALUE IS A NUMPY NUMBER
    if isinstance(value_in, np.generic):
        # CONVERT TO A PYTHON NUMBER
        return to_json_safe(value_in.item())
    # IF THE VALUE IS A FLOAT NAN
    if isinstance(value_in, float) and np.isnan(value_in):
        # RETURN NONE
        return None
    # IF THE VALUE IS A DATE OR TIMESTAMP
    if hasattr(value_in, "isoformat"):
        # RETURN THE ISO STRING
        return value_in.isoformat()
    # RETURN THE VALUE
    return value_in

# FUNCTION: GET THE TRAINING START OF A FOLD FOR A SETTING
def get_setting_train_start(fold_dict_in, setting_dict_in):
    """
    Returns the training start of the training window named by the setting ("train_window": "10y" / "all", or
    "train_years": 3 / 5 / 10), or the fold's "train_start" when the setting names none.

    Args:
        fold_dict_in (dict): Fold row as a dictionary
        setting_dict_in (dict): Evaluated setting

    Returns:
        datetime.date | None: Training start
    """
    # COLLECT THE NAMED TRAINING WINDOW
    setting_dict = setting_dict_in if isinstance(setting_dict_in, dict) else {}
    # IF THE SETTING NAMES A WINDOW KEY ("10y", "all")
    if setting_dict.get("train_window") is not None:
        # RETURN THE START OF THAT WINDOW
        return fold_dict_in.get(f"train_start_{setting_dict['train_window']}", fold_dict_in.get("train_start"))
    # IF THE SETTING NAMES A NUMBER OF YEARS
    if setting_dict.get("train_years") is not None:
        # RETURN THE START OF THAT WINDOW
        return fold_dict_in.get(f"train_start_{int(setting_dict['train_years'])}y", fold_dict_in.get("train_start"))
    # RETURN THE GENERIC TRAINING START
    return fold_dict_in.get("train_start")

# FUNCTION: LOG A TRIAL
def log_trial_dict(experiment_config_in, stage_str_in, setting_dict_in, metric_dict_in, test_window_touched_bool_in,
                   fold_row_in=None, note_str_in="", file_path_str_in=None, alert_in=False):
    """
    Appends one entry to the shared trial log.

    Args:
        experiment_config_in (module): The experiment's config module (name, protocol version and hash are read from it)
        stage_str_in (str): "exploration", "signal_check", "validation", "test" or "note"
        setting_dict_in (dict): Settings evaluated or selected
        metric_dict_in (dict): Metrics of the entry
        test_window_touched_bool_in (bool): True if test results were looked at
        fold_row_in (pd.Series | dict | None): Walk-forward fold row (windows are copied from it)
        note_str_in (str): Free text
        file_path_str_in (str | None): Trial log CSV path (None = paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)
        alert_in (bool): Display file messages

    Returns:
        dict: The logged row
    """
    # DEFINE THE LOGGED TIMESTAMP AND THE CONFIG HASH
    logged_ts = datetime.now()
    config_hash_str = get_config_hash_str(experiment_config_in)
    # CONVERT THE FOLD ROW TO A DICTIONARY
    fold_dict = dict(fold_row_in) if fold_row_in is not None else {}
    # DEFINE THE TRIAL ROW
    trial_dict = {
        "trial_id": f"{logged_ts.strftime('%Y%m%d%H%M%S%f')}_{config_hash_str}",
        "logged_ts": logged_ts.isoformat(timespec="seconds"),
        "experiment": experiment_config_in.EXPERIMENT_NAME,
        "protocol_version": experiment_config_in.PROTOCOL_VERSION,
        "stage": stage_str_in,
        "fold_id": fold_dict.get("fold_id", np.nan),
        "train_start": get_setting_train_start(fold_dict, setting_dict_in),
        "train_end": fold_dict.get("train_end"),
        "valid_start": fold_dict.get("valid_start"),
        "valid_end": fold_dict.get("valid_end"),
        "test_start": fold_dict.get("test_start"),
        "test_end": fold_dict.get("test_end"),
        "test_window_touched": bool(test_window_touched_bool_in),
        "config_hash": config_hash_str,
        "setting_json": json.dumps(to_json_safe(setting_dict_in), sort_keys=True),
        "metric_json": json.dumps(to_json_safe(metric_dict_in), sort_keys=True),
        "note": note_str_in,
    }
    # APPEND THE ROW TO THE TRIAL LOG
    write_csv_file_to_path(pd.DataFrame([trial_dict]), file_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR, "A", alert_in=alert_in)
    # RETURN THE ROW
    return trial_dict

# FUNCTION: LOG MANY TRIALS
def log_trial_pdf(experiment_config_in, stage_str_in, setting_pdf_in, setting_col_str_list_in, metric_col_str_list_in,
                  test_window_touched_bool_in, fold_pdf_in=None, note_str_in="", file_path_str_in=None):
    """
    Appends one entry per row of a result table (e.g. every validation candidate of every fold) in a single write.

    Args:
        experiment_config_in (module): The experiment's config module
        stage_str_in (str): Stage of every entry
        setting_pdf_in (pd.DataFrame): One row per trial (must contain fold_id when fold_pdf_in is given)
        setting_col_str_list_in (list[str]): Columns stored in setting_json
        metric_col_str_list_in (list[str]): Columns stored in metric_json
        test_window_touched_bool_in (bool): True if test results were looked at
        fold_pdf_in (pd.DataFrame | None): Fold schedule (windows are copied by fold_id)
        note_str_in (str): Free text
        file_path_str_in (str | None): Trial log CSV path (None = paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)

    Returns:
        pd.DataFrame: The logged rows
    """
    # DEFINE THE LOGGED TIMESTAMP AND THE CONFIG HASH
    logged_ts = datetime.now()
    config_hash_str = get_config_hash_str(experiment_config_in)
    # INDEX THE FOLDS
    fold_dict_dict = {int(row["fold_id"]): dict(row) for _, row in fold_pdf_in.iterrows()} if fold_pdf_in is not None else {}
    # LIST TO HOLD THE ROWS
    trial_dict_list = []
    # ITERATE OVER THE TRIALS
    for row_idx, (_, setting_row) in enumerate(setting_pdf_in.iterrows()):
        # COLLECT THE SETTING, THE METRICS AND THE FOLD
        setting_dict = {col: setting_row[col] for col in setting_col_str_list_in}
        metric_dict = {col: setting_row[col] for col in metric_col_str_list_in if col in setting_row.index}
        fold_dict = fold_dict_dict.get(int(setting_row["fold_id"]), {}) if "fold_id" in setting_row.index and pd.notna(setting_row["fold_id"]) else {}
        # DEFINE THE TRIAL ROW (THE ROW INDEX MAKES THE ID UNIQUE WITHIN THE WRITE)
        trial_dict_list.append({
            "trial_id": f"{logged_ts.strftime('%Y%m%d%H%M%S%f')}{row_idx:05d}_{config_hash_str}",
            "logged_ts": logged_ts.isoformat(timespec="seconds"),
            "experiment": experiment_config_in.EXPERIMENT_NAME,
            "protocol_version": experiment_config_in.PROTOCOL_VERSION,
            "stage": stage_str_in,
            "fold_id": fold_dict.get("fold_id", np.nan),
            "train_start": get_setting_train_start(fold_dict, setting_dict),
            "train_end": fold_dict.get("train_end"),
            "valid_start": fold_dict.get("valid_start"),
            "valid_end": fold_dict.get("valid_end"),
            "test_start": fold_dict.get("test_start"),
            "test_end": fold_dict.get("test_end"),
            "test_window_touched": bool(test_window_touched_bool_in),
            "config_hash": config_hash_str,
            "setting_json": json.dumps(to_json_safe(setting_dict), sort_keys=True),
            "metric_json": json.dumps(to_json_safe(metric_dict), sort_keys=True),
            "note": note_str_in,
        })
    # CONVERT TO A DATAFRAME
    trial_pdf = pd.DataFrame(trial_dict_list)
    # APPEND THE ROWS TO THE TRIAL LOG
    if not trial_pdf.empty:
        write_csv_file_to_path(trial_pdf, file_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR, "A", alert_in=False)
    # RETURN THE ROWS
    return trial_pdf

# FUNCTION: READ THE TRIAL LOG
def read_trial_log_pdf(file_path_str_in=None, expand_metrics_bool_in=False):
    """
    Reads the trial log.

    Args:
        file_path_str_in (str | None): Trial log CSV path (None = paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)
        expand_metrics_bool_in (bool): Expand metric_json into columns

    Returns:
        pd.DataFrame: Trial log (empty DataFrame if it does not exist)
    """
    # DEFINE THE PATH
    file_path_str = file_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR
    # IF THE TRIAL LOG DOES NOT EXIST
    if not check_file_exists(file_path_str):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # READ THE TRIAL LOG
    trial_log_pdf = read_csv_file_from_path(file_path_str, alert_in=False)
    # IF THE METRICS MUST BE EXPANDED
    if expand_metrics_bool_in and not trial_log_pdf.empty:
        # EXPAND THE METRIC JSON
        metric_pdf = pd.json_normalize(trial_log_pdf["metric_json"].apply(json.loads)).add_prefix("metric_")
        # JOIN THE METRICS
        trial_log_pdf = pd.concat([trial_log_pdf.reset_index(drop=True), metric_pdf], axis=1)
    # RETURN DATAFRAME
    return trial_log_pdf

# FUNCTION: SUMMARIZE THE TRIAL LOG
def get_trial_count_pdf(trial_log_pdf_in):
    """
    Counts the trials per experiment and stage (the multiple-testing record shown at the end of every notebook).

    Args:
        trial_log_pdf_in (pd.DataFrame): Output of read_trial_log_pdf

    Returns:
        pd.DataFrame: experiment, stage, trial_count, config_count, test_touched_count, first_logged_ts, last_logged_ts
    """
    # IF THE LOG IS EMPTY
    if trial_log_pdf_in is None or trial_log_pdf_in.empty:
        # RETURN AN EMPTY DATAFRAME
        return pd.DataFrame()
    # RETURN THE COUNTS
    return trial_log_pdf_in.groupby(["experiment", "stage"]).agg(trial_count=("trial_id", "count"),
                                                                 config_count=("config_hash", "nunique"),
                                                                 test_touched_count=("test_window_touched", "sum"),
                                                                 first_logged_ts=("logged_ts", "min"),
                                                                 last_logged_ts=("logged_ts", "max")).reset_index()

# FUNCTION: WARN ABOUT EARLIER ENTRIES OF THE SAME EXPERIMENT STAGE
def print_previous_trial_warning(experiment_config_in, stage_str_in, file_path_str_in=None):
    """
    Prints how many entries the trial log already holds for this experiment and stage (any configuration), so that a
    rerun is a deliberate decision: every rerun adds trials (the duplicated v2 run of 2026-10-04 is the reason).

    Args:
        experiment_config_in (module): The experiment's config module
        stage_str_in (str): Stage about to be run ("exploration", "signal_check", "validation", "test")
        file_path_str_in (str | None): Trial log CSV path (None = paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)

    Returns:
        int: Number of earlier entries of the experiment and stage
    """
    # READ THE TRIAL LOG
    trial_log_pdf = read_trial_log_pdf(file_path_str_in)
    # COUNT THE EARLIER ENTRIES
    if trial_log_pdf.empty:
        previous_count = 0
    else:
        previous_pdf = trial_log_pdf[(trial_log_pdf["experiment"] == experiment_config_in.EXPERIMENT_NAME) & (trial_log_pdf["stage"] == stage_str_in)]
        previous_count = int(len(previous_pdf))
    # DISPLAY THE WARNING
    if previous_count > 0:
        last_ts_str = previous_pdf["logged_ts"].max()
        hash_list = sorted(previous_pdf["config_hash"].unique().tolist())
        print(f"⚠️ The trial log already holds {previous_count} '{stage_str_in}' entries of {experiment_config_in.EXPERIMENT_NAME} "
              f"(last {last_ts_str}, config hash(es) {hash_list}; current hash {get_config_hash_str(experiment_config_in)}). Running this notebook again ADDS trials.")
    else:
        print(f"ℹ️ No earlier '{stage_str_in}' entry of {experiment_config_in.EXPERIMENT_NAME} in the trial log (config hash {get_config_hash_str(experiment_config_in)}).")
    # RETURN THE COUNT
    return previous_count
