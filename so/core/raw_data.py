import pandas as pd
# IMPORT PATHS
from so import paths
# IMPORT LOCAL FILE MANAGEMENT FUNCTIONS
from so.core.local_file_management import get_path_file_list, read_pdf_from_csv_file_path_list
# IMPORT MARKET DATETIME FUNCTIONS
from so.core.datetime_utils import ny_tz
# IMPORT TRANSFORM OHLCV DATA FUNCTIONS
from so.features.ohlcv_data_utils import format_ohlcv_pdf

"""
Raw Data Loading (the same reading in every notebook)

The raw IBKR files are yearly CSVs in paths.LOCAL_OHLCV_DATA_FILE_PATH_STR. Timestamps are parsed as UTC and converted
to New York time; the session date is taken from the New York timestamp.
"""

# FUNCTION: READ THE RAW MINUTE BARS
def read_raw_ohlcv_pdf(raw_path_str_in=None):
    """
    Reads every raw CSV file of the raw folder into one DataFrame, with New York timestamps and the session date.

    Args:
        raw_path_str_in (str | None): Raw folder (None = paths.LOCAL_OHLCV_DATA_FILE_PATH_STR)

    Returns:
        pd.DataFrame: Raw minute bars (every raw column kept), timestamp in New York time, date
    """
    # COLLECT THE CSV FILES OF THE RAW FOLDER
    raw_path_str = raw_path_str_in or paths.LOCAL_OHLCV_DATA_FILE_PATH_STR
    file_path_list = sorted(file_path for file_path in get_path_file_list(raw_path_str) if file_path.lower().endswith(".csv"))
    # READ THE FILES
    raw_ohlcv_pdf = read_pdf_from_csv_file_path_list(file_path_list)
    # DROP REPEATED COLUMN NAMES (AN EXPORTED COPY CAN CARRY TWO "date" COLUMNS)
    raw_ohlcv_pdf = raw_ohlcv_pdf.loc[:, ~raw_ohlcv_pdf.columns.duplicated()].reset_index(drop=True)
    # CONVERT THE TIMESTAMPS AND ADD THE SESSION DATE
    raw_ohlcv_pdf["timestamp"] = pd.to_datetime(raw_ohlcv_pdf["timestamp"], utc=True).dt.tz_convert(ny_tz)
    raw_ohlcv_pdf["date"] = raw_ohlcv_pdf["timestamp"].dt.date
    # RETURN THE DATAFRAME
    return raw_ohlcv_pdf

# FUNCTION: GET THE COMPLETE (FORMATTED) MINUTE BARS
def get_complete_ohlcv_pdf(raw_path_str_in=None, cutoff_date_str_in=None):
    """
    Reads the raw bars and formats them for the pipeline and the simulators (timestamp, open, high, low, close, volume,
    date), sorted by timestamp. Optionally cuts the data after a date (exploration notebooks).

    Args:
        raw_path_str_in (str | None): Raw folder (None = paths.LOCAL_OHLCV_DATA_FILE_PATH_STR)
        cutoff_date_str_in (str | None): Last session kept (inclusive); None keeps everything

    Returns:
        pd.DataFrame: Complete minute bars
    """
    # READ THE RAW BARS
    raw_ohlcv_pdf = read_raw_ohlcv_pdf(raw_path_str_in)
    # IF A CUTOFF IS GIVEN
    if cutoff_date_str_in is not None:
        # KEEP THE SESSIONS UP TO THE CUTOFF
        raw_ohlcv_pdf = raw_ohlcv_pdf[raw_ohlcv_pdf["date"] <= pd.Timestamp(cutoff_date_str_in).date()]
    # RETURN THE FORMATTED AND SORTED BARS
    return format_ohlcv_pdf(raw_ohlcv_pdf.copy()).sort_values("timestamp").reset_index(drop=True)
