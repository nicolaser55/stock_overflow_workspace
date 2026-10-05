import pandas as pd
import numpy as np
from datetime import timedelta
# IMPORT EXPERIMENT CONFIGURATION
from so import config
# IMPORT MARKET DATETIME FUNCTIONS
from so.core.datetime_utils import ny_tz
# IMPORT LOCAL FILE MANAGEMENT FUNCTIONS
from so.core.local_file_management import get_date_range_file_path_list, read_csv_file_from_path
# IMPORT TRADE EXECUTION FUNCTIONS (single source of truth for the exit rules)
from so.core.trade_execution import resolve_entry_trade_dict, get_net_return_arr

"""
Timestamp Barrier (TSBAR) Target Matrix

Step 05 target. Replaces the step12 TS_delta_matrix_sell target of the previous workspace (legacy, paths.LOCAL_LEGACY_TS_DELTA_MATRIX_SELL_DATA_FILE_PATH_STR)
with the rules agreed on 2026-10-01 (see trade_execution.py).

One row per DECISION bar (the feature row). The entry is at the open of the next bar of the same session.
Decisions are allowed from the bar before the first allowed entry (09:59 -> entry at the 10:00 open) to the
second-to-last bar of the session (15:58 -> entry at the 15:59 open). The last bar of a session cannot trigger a buy
at the next session's open.

Row columns:
    decision_ts         timestamp of the feature row (pair it with TSIND/TSSEG/TSCTX rows having the same timestamp)
    entry_ts            timestamp of the entry bar
    entry_price         open of the entry bar (raw, before slippage)
    horizon_complete    True if the data contains the full holding window of the entry
    rr_ratio            stop loss distance / take profit distance
    "<delta>"           one column per delta (e.g. "0.0010"), cell = "exit_bar_count|exit_price|exit_reason"
                        exit_bar_count = bars from the entry bar to the exit bar (-1 if unresolved)
                        exit_price     = raw exit price before slippage (nan if unresolved)
                        exit_reason    = TP / SL / TL / NA
    date                added by generate_func_data_date_list
"""

# FUNCTION: GET THE DELTA COLUMN NAME
def get_delta_col_str(delta_float_in):
    """
    Formats a delta as its TSBAR column name.

    Args:
        delta_float_in (float): Delta (fraction)

    Returns:
        str: Column name with 4 decimals (e.g. 0.001 -> "0.0010")
    """
    # RETURN THE COLUMN NAME
    return f"{delta_float_in:.4f}"

# FUNCTION: ENCODE A TSBAR CELL
def encode_TSBAR_cell_str(exit_bar_count_int_in, exit_price_float_in, exit_reason_str_in):
    """
    Encodes one trade outcome as a compact TSBAR cell string "exit_bar_count|exit_price|exit_reason".

    Args:
        exit_bar_count_int_in (int): Bars from the entry bar to the exit bar (-1 if unresolved)
        exit_price_float_in (float): Raw exit price (NaN if unresolved)
        exit_reason_str_in (str): Exit reason

    Returns:
        str: Encoded cell
    """
    # FORMAT THE EXIT PRICE
    exit_price_str = "nan" if pd.isna(exit_price_float_in) else f"{round(float(exit_price_float_in), 6)}"
    # RETURN THE ENCODED CELL
    return f"{int(exit_bar_count_int_in)}|{exit_price_str}|{exit_reason_str_in}"

# FUNCTION: PARSE A TSBAR DELTA COLUMN
def parse_TSBAR_cell_pdf(cell_series_in):
    """
    Splits a TSBAR delta column into its exit bar count, exit price and exit reason.

    Args:
        cell_series_in (pd.Series): Encoded cells of one delta column

    Returns:
        pd.DataFrame: Columns exit_bar_count (int), exit_price (float), exit_reason (str), same index as the input
    """
    # SPLIT THE CELLS
    split_pdf = cell_series_in.astype(str).str.split("|", expand=True)
    # RETURN THE PARSED DATAFRAME
    return pd.DataFrame({"exit_bar_count": split_pdf[0].astype(int),
                         "exit_price": pd.to_numeric(split_pdf[1], errors="coerce"),
                         "exit_reason": split_pdf[2]}, index=cell_series_in.index)

# FUNCTION: GET THE MARKET OPEN TIMESTAMP DICTIONARY
def get_date_market_open_ts_dict(market_schedule_pdf_in):
    """
    Converts a market schedule (datetime_utils.get_date_range_market_schedule_pdf) into a date -> market open dictionary.

    Args:
        market_schedule_pdf_in (pd.DataFrame): Schedule with date and market_open_ts columns

    Returns:
        dict: datetime.date -> market open timestamp (New York timezone)
    """
    # RETURN THE DICTIONARY
    return dict(zip(pd.to_datetime(market_schedule_pdf_in["date"]).dt.date, market_schedule_pdf_in["market_open_ts"]))

# FUNCTION: GET THE DECISION BAR INDEXES OF A SESSION
def get_session_decision_bar_idx_arr(ohlcv_array_dict_in, date_object_in, market_open_ts_in,
                                     start_delay_minutes_in=config.TRADING_START_DELAY_MINUTES):
    """
    Finds the decision bars of a session: bars whose NEXT bar (the entry bar) is in the same session and starts at or after
    the first allowed entry time (market open + start delay).

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        date_object_in (datetime.date): Session date
        market_open_ts_in (pd.Timestamp): Market open of the session (New York timezone)
        start_delay_minutes_in (int): Minutes after the open before the first entry

    Returns:
        np.ndarray: Global bar indexes of the decision bars (empty if the session is not in the data)
    """
    # IF THE SESSION IS NOT IN THE DATA
    if date_object_in not in ohlcv_array_dict_in["date_session_idx_dict"]:
        # RETURN AN EMPTY ARRAY
        return np.array([], dtype=int)
    # COLLECT THE SESSION POSITION AND ITS FIRST AND LAST BAR
    session_idx = ohlcv_array_dict_in["date_session_idx_dict"][date_object_in]
    start_idx = ohlcv_array_dict_in["session_start_idx_arr"][session_idx]
    end_idx = ohlcv_array_dict_in["session_end_idx_arr"][session_idx]
    # CALCULATE THE FIRST ALLOWED ENTRY TIMESTAMP
    first_entry_ts = market_open_ts_in + timedelta(minutes=start_delay_minutes_in)
    # COLLECT THE CANDIDATE DECISION BARS (EVERY BAR EXCEPT THE LAST BAR OF THE SESSION)
    decision_idx_arr = np.arange(start_idx, end_idx)
    # COLLECT THE ENTRY TIMESTAMPS OF THE CANDIDATES
    entry_ts_index = ohlcv_array_dict_in["timestamp_index"][decision_idx_arr + config.DECISION_TO_ENTRY_BAR_OFFSET]
    # RETURN THE DECISION BARS WHOSE ENTRY IS AT OR AFTER THE FIRST ALLOWED ENTRY
    return decision_idx_arr[np.asarray(entry_ts_index >= first_entry_ts)]

# FUNCTION: GENERATE THE DATE TIMESTAMP BARRIER (TSBAR) DATAFRAME
def get_date_TSBAR_pdf(ohlcv_array_dict_in, date_market_open_ts_dict_in, date_str_in,
                       delta_list_in=config.FULL_DELTA_LIST, rr_ratio_float_in=config.RR_RATIO):
    """
    Generates the barrier target rows of one session (one row per decision bar, one column per delta).

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict built on the COMPLETE data
                                    (later sessions are needed to resolve multi-day trades)
        date_market_open_ts_dict_in (dict): Output of get_date_market_open_ts_dict
        date_str_in (str): Session date 'YYYY-MM-DD'
        delta_list_in (list[float]): Take profit distances
        rr_ratio_float_in (float): Stop loss distance / take profit distance

    Returns:
        pd.DataFrame: TSBAR rows (empty DataFrame if the session is not in the data)
    """
    # CONVERT THE DATE STRING TO A DATE OBJECT
    date_object = pd.to_datetime(date_str_in).date()
    # IF THE MARKET OPEN IS UNKNOWN FOR THE DATE
    if date_object not in date_market_open_ts_dict_in:
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # COLLECT THE DECISION BARS OF THE SESSION
    decision_idx_arr = get_session_decision_bar_idx_arr(ohlcv_array_dict_in, date_object, date_market_open_ts_dict_in[date_object])
    # IF THERE ARE NO DECISION BARS
    if len(decision_idx_arr) == 0:
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # DEFINE THE DELTA ARRAY AND COLUMN NAMES
    delta_arr = np.asarray(delta_list_in, dtype=float)
    delta_col_str_list = [get_delta_col_str(delta) for delta in delta_list_in]
    # LIST TO HOLD THE ROWS
    data_dict_list = []
    # ITERATE OVER THE DECISION BARS
    for decision_idx in decision_idx_arr:
        # DEFINE THE ENTRY BAR
        entry_idx = int(decision_idx) + config.DECISION_TO_ENTRY_BAR_OFFSET
        # RESOLVE THE TRADES OF EVERY DELTA
        trade_dict = resolve_entry_trade_dict(ohlcv_array_dict_in, entry_idx, delta_arr, rr_ratio_float_in)
        # DEFINE THE ROW DICTIONARY
        data_dict = {
            "decision_ts": ohlcv_array_dict_in["timestamp_index"][decision_idx],
            "entry_ts": ohlcv_array_dict_in["timestamp_index"][entry_idx],
            "entry_price": trade_dict["entry_price"],
            "horizon_complete": trade_dict["horizon_complete"],
            "rr_ratio": float(rr_ratio_float_in),
        }
        # ITERATE OVER THE DELTAS
        for delta_idx, delta_col_str in enumerate(delta_col_str_list):
            # ENCODE THE CELL
            data_dict[delta_col_str] = encode_TSBAR_cell_str(trade_dict["exit_bar_count_arr"][delta_idx],
                                                             trade_dict["exit_price_arr"][delta_idx],
                                                             trade_dict["exit_reason_arr"][delta_idx])
        # APPEND THE ROW
        data_dict_list.append(data_dict)
    # CONVERT THE LIST TO A DATAFRAME AND RETURN
    return pd.DataFrame(data_dict_list)

# FUNCTION: ADD THE LABEL COLUMNS OF A LIST OF DELTAS
def add_TSBAR_label_cols(TSBAR_pdf_in, delta_list_in, drop_cell_cols_in=False, **cost_kwargs):
    """
    Parses the TSBAR delta cells into numeric label columns.

    For each delta d (column suffix = get_delta_col_str(d)):
        y_tp_<d>            1 if the exit is a take profit, 0 for stop loss or time limit, NaN if unresolved (NA)
        net_return_<d>      net return after costs (trade_execution.get_net_return_arr), NaN if unresolved
        exit_bar_count_<d>  bars from the entry bar to the exit bar (-1 if unresolved)
        exit_reason_<d>     TP / SL / TL / NA

    Args:
        TSBAR_pdf_in (pd.DataFrame): TSBAR rows (must contain entry_price and the delta columns)
        delta_list_in (list[float]): Deltas to parse
        drop_cell_cols_in (bool): Drop the raw encoded delta columns after parsing
        **cost_kwargs: Optional cost overrides passed to trade_execution.get_net_return_arr

    Returns:
        pd.DataFrame: Copy of the input with the label columns
    """
    # COPY THE DATAFRAME
    pdf_out = TSBAR_pdf_in.copy()
    # DICTIONARY TO HOLD THE NEW COLUMNS
    new_col_dict = {}
    # ITERATE OVER THE DELTAS
    for delta in delta_list_in:
        # DEFINE THE DELTA COLUMN
        delta_col_str = get_delta_col_str(delta)
        # PARSE THE CELLS
        cell_pdf = parse_TSBAR_cell_pdf(pdf_out[delta_col_str])
        # DEFINE THE RESOLVED MASK
        resolved_mask = cell_pdf.exit_reason != config.EXIT_REASON_NA
        # ADD THE LABEL COLUMNS
        new_col_dict[f"y_tp_{delta_col_str}"] = np.where(resolved_mask, (cell_pdf.exit_reason == config.EXIT_REASON_TP).astype(float), np.nan)
        new_col_dict[f"net_return_{delta_col_str}"] = np.where(resolved_mask,
                                                               get_net_return_arr(pdf_out["entry_price"].to_numpy(dtype=float),
                                                                                  cell_pdf.exit_price.to_numpy(dtype=float),
                                                                                  cell_pdf.exit_reason.to_numpy(dtype=object),
                                                                                  **cost_kwargs),
                                                               np.nan)
        new_col_dict[f"exit_bar_count_{delta_col_str}"] = cell_pdf.exit_bar_count.to_numpy()
        new_col_dict[f"exit_reason_{delta_col_str}"] = cell_pdf.exit_reason.to_numpy()
    # ADD THE NEW COLUMNS
    pdf_out = pd.concat([pdf_out, pd.DataFrame(new_col_dict, index=pdf_out.index)], axis=1)
    # IF THE RAW CELL COLUMNS MUST BE DROPPED
    if drop_cell_cols_in:
        # DROP EVERY RAW DELTA COLUMN
        pdf_out = pdf_out.drop(columns=[col for col in pdf_out.columns if col in [get_delta_col_str(d) for d in config.FULL_DELTA_LIST]])
    # RETURN DATAFRAME
    return pdf_out

# FUNCTION: FIND THE TSBAR DATES THAT MUST BE REGENERATED
def get_TSBAR_incomplete_date_list(file_path_str_in, recent_file_count_in=30):
    """
    Finds the TSBAR dates whose holding windows were not complete when they were generated (the data ended first).
    These dates must be regenerated in overwrite mode ("W") after new data is added.

    Only the most recent files are read: a holding window can only be incomplete within the last
    MAX_HOLD_TRADING_DAYS sessions of the data that existed at generation time.

    Args:
        file_path_str_in (str): TSBAR directory path
        recent_file_count_in (int): Number of most recent files to inspect

    Returns:
        list[datetime.date]: Dates with at least one incomplete holding window (sorted)
    """
    # COLLECT THE MOST RECENT FILE PATHS
    file_path_str_list = get_date_range_file_path_list(file_path_str_in)[-recent_file_count_in:]
    # LIST TO HOLD THE INCOMPLETE DATES
    incomplete_date_list = []
    # ITERATE OVER THE FILE PATHS
    for file_path_str in file_path_str_list:
        # READ THE FILE
        read_pdf = read_csv_file_from_path(file_path_str, alert_in=False)
        # IF THE FILE CONTAINS AN INCOMPLETE HOLDING WINDOW
        if isinstance(read_pdf, pd.DataFrame) and (~read_pdf["horizon_complete"].astype(bool)).any():
            # ADD THE DATE TO THE LIST
            incomplete_date_list.append(pd.to_datetime(read_pdf["date"].iloc[0]).date())
    # RETURN THE SORTED LIST
    return sorted(incomplete_date_list)

# FUNCTION: CORRECT THE TIMESTAMP COLUMNS OF A TSBAR DATAFRAME READ FROM CSV
def format_TSBAR_pdf(TSBAR_pdf_in):
    """
    Converts the TSBAR timestamp columns read from CSV to New York timezone timestamps.

    Args:
        TSBAR_pdf_in (pd.DataFrame): TSBAR rows read from CSV

    Returns:
        pd.DataFrame: Same DataFrame with decision_ts and entry_ts as timestamps and date as date objects
    """
    # ITERATE OVER THE TIMESTAMP COLUMNS
    for col_str in ["decision_ts", "entry_ts"]:
        # IF THE COLUMN EXISTS
        if col_str in TSBAR_pdf_in.columns:
            # CONVERT THE COLUMN
            TSBAR_pdf_in[col_str] = pd.to_datetime(TSBAR_pdf_in[col_str], utc=True).dt.tz_convert(ny_tz)
    # IF THE DATE COLUMN EXISTS
    if "date" in TSBAR_pdf_in.columns:
        # CONVERT THE DATE COLUMN
        TSBAR_pdf_in["date"] = pd.to_datetime(TSBAR_pdf_in["date"]).dt.date
    # RETURN DATAFRAME
    return TSBAR_pdf_in
