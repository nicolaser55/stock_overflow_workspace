import os
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
from so.core.local_file_management import check_file_exists, read_csv_file_from_path
# IMPORT THE LOCKED CSV APPEND (NEW ROWS ONLY; THE EXISTING FILE IS NOT REWRITTEN)
from so.core.csv_append import append_csv_record_pdf

"""
Trial Log (one file shared by every experiment: paths.LOCAL_TRIAL_LOG_FILE_PATH_STR)

Every experiment appends one row per evaluated configuration: each exploration rule, each signal check, each validation
candidate of each fold and each test evaluation. The log is the evidence of how many configurations were tried before a
result was obtained (multiple testing) and of whether a test window had already been seen. Never edit or delete rows.

The records from before the 2026-10-22 reset are kept, read-only, in records/legacy/: the trial log of 2026-10-05 ->
2026-10-22 (trial_log_snapshot_20261022.csv, which contains the 2026-10-05 legacy rows) and the 2026-10-05 audit trials
(audit_trials_20261005.csv). They were restored from git history on 2026-10-25 (audit B5) and count in the
multiple-testing adjustment (so.core.multiple_testing).

From 2026-10-20 a new trial_id includes the process id, so two processes that log in the same microsecond do not
share an id. One row is "{timestamp}_{pid}_{config_hash}". A row written in a batch is
"{timestamp}{row_index:05d}_{pid}_{config_hash}". Rows already in the log keep the earlier id (those two forms
without the process id). They are not rewritten.

A caller may pass a stable trial_id (the runner: run id + candidate + period). When that id is already in the file,
the append is skipped so a resumed run never logs the same trial twice.

Columns:
    trial_id                unique id (timestamp, process id and config hash; older rows have no process id)
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

# THE TRIAL LOG COLUMNS, IN THE ORDER THEY ARE WRITTEN
TRIAL_LOG_COLUMN_LIST = ["trial_id", "logged_ts", "experiment", "protocol_version", "stage", "fold_id", "train_start",
                         "train_end", "valid_start", "valid_end", "test_start", "test_end", "test_window_touched",
                         "config_hash", "setting_json", "metric_json", "note"]

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
                   fold_row_in=None, note_str_in="", file_path_str_in=None, alert_in=False, trial_id_str_in=None):
    """
    Appends one entry to the shared trial log. A stable trial_id_str_in that is already in the file is not written
    again (a resumed run).

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
        trial_id_str_in (str | None): Stable id (None = timestamp, process id and config hash)

    Returns:
        dict: The logged row (appended_bool is True when a new row was written)
    """
    # DEFINE THE LOGGED TIMESTAMP, THE CONFIG HASH AND THE PROCESS ID (THE ID STAYS UNIQUE ACROSS PROCESSES)
    logged_ts = datetime.now()
    config_hash_str = get_config_hash_str(experiment_config_in)
    pid_int = os.getpid()
    # CONVERT THE FOLD ROW TO A DICTIONARY
    fold_dict = dict(fold_row_in) if fold_row_in is not None else {}
    # A STABLE ID WINS; OTHERWISE THE TIMESTAMP FORM
    trial_id_str = str(trial_id_str_in) if trial_id_str_in else f"{logged_ts.strftime('%Y%m%d%H%M%S%f')}_{pid_int}_{config_hash_str}"
    # DEFINE THE TRIAL ROW
    trial_dict = {
        "trial_id": trial_id_str,
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
    # APPEND THE ROW (A STABLE ID THAT IS ALREADY PRESENT IS SKIPPED)
    file_path_str = file_path_str_in or paths.LOCAL_TRIAL_LOG_FILE_PATH_STR
    skip_col_str = "trial_id" if trial_id_str_in else None
    appended_count = append_csv_record_pdf(pd.DataFrame([trial_dict], columns=TRIAL_LOG_COLUMN_LIST), file_path_str,
                                           TRIAL_LOG_COLUMN_LIST, skip_existing_col_str_in=skip_col_str)
    trial_dict["appended_bool"] = int(appended_count) > 0
    # DISPLAY INFORMATION
    print(f"✅ Trial appended to '{file_path_str}'") if alert_in and trial_dict["appended_bool"] else None
    # RETURN THE ROW
    return trial_dict


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


