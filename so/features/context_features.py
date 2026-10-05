import pandas as pd
import numpy as np
# IMPORT EXPERIMENT CONFIGURATION
from so import config
# IMPORT MARKET DATETIME FUNCTIONS
from so.core.datetime_utils import get_date_pdf
# IMPORT DATA QUALITY FUNCTIONS
from so.core.data_quality import validate_all_pdf_cols, pdf_is_empty

"""
Timestamp Context (TSCTX) Features

Context that the session-by-session snapshot pipeline (steps 01 / 02 / 03) cannot see because every session starts cold:
time of day, the previous sessions, the overnight gap, volume relative to the usual volume at that minute, and the
distance from the all-time high.

Every value on the row of bar t uses only bars <= t (prior sessions and the current session up to and including bar t).

Columns (one row per minute bar):
    timestamp               bar timestamp (New York timezone)
    minutes_since_open      minutes between the market open and the bar (09:30 bar -> 0)
    minutes_to_close        minutes between the bar and the last bar of the session (last bar -> 0; shorter on half days)
    day_of_week             0 = Monday ... 4 = Friday
    overnight_gap_pct       session open / previous session close - 1
    prev_day_return_pct     previous session close / close of the session before it - 1
    prev_day_range_pct      (previous session high - previous session low) / previous session close
    prev_day_high_dist_pct  close / previous session high - 1
    prev_day_low_dist_pct   close / previous session low - 1
    intraday_return_pct     close / session open - 1
    daily_volatility        standard deviation of the previous CTX_DAILY_VOLATILITY_SESSIONS daily close-to-close returns
    relative_volume         volume / mean volume at the same minute of the day over the previous CTX_RELATIVE_VOLUME_SESSIONS sessions
    ath_drawdown_pct        close / running maximum high since the start of the data - 1 (0 at a new all-time high)
    date                    added by generate_func_data_date_list

Not included yet: VIX (external data source required).
"""

# FUNCTION: ADD THE RUNNING MAXIMUM HIGH COLUMN
def add_cum_max_col(ohlcv_pdf_in):
    """
    Adds the running maximum high since the first row of the data (same definition as the TSSEG cum_max).

    Args:
        ohlcv_pdf_in (pd.DataFrame): Complete minute OHLCV data sorted by timestamp

    Returns:
        pd.DataFrame: Same DataFrame with a cum_max column
    """
    # COLLECT THE CUMULATIVE MAXIMUM HIGH
    ohlcv_pdf_in["cum_max"] = ohlcv_pdf_in["high"].cummax()
    # RETURN THE DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: GET THE SESSION SUMMARY DATAFRAME
def get_session_summary_pdf(complete_ohlcv_pdf_in, volatility_session_count_in=config.CTX_DAILY_VOLATILITY_SESSIONS):
    """
    Aggregates the minute data by session and adds the previous-session values used by the context features.

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Complete minute OHLCV data with a date column
        volatility_session_count_in (int): Number of prior daily returns used for daily_volatility

    Returns:
        pd.DataFrame: One row per session date with open, high, low, close, prev_close, prev_high, prev_low,
                      prev_day_return_pct, prev_day_range_pct, daily_volatility
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["date", "open", "high", "low", "close"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(complete_ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")
    # AGGREGATE THE OHLC DATA BY SESSION
    session_pdf = complete_ohlcv_pdf_in.groupby("date").agg(open=("open", "first"),
                                                            high=("high", "max"),
                                                            low=("low", "min"),
                                                            close=("close", "last")
                                                        ).reset_index().sort_values("date").reset_index(drop=True)
    # COLLECT THE PREVIOUS SESSION VALUES
    session_pdf["prev_close"] = session_pdf["close"].shift(1)
    session_pdf["prev_high"] = session_pdf["high"].shift(1)
    session_pdf["prev_low"] = session_pdf["low"].shift(1)
    # CALCULATE THE DAILY CLOSE TO CLOSE RETURN
    daily_return_series = session_pdf["close"] / session_pdf["prev_close"] - 1
    # CALCULATE THE PREVIOUS SESSION RETURN AND RANGE
    session_pdf["prev_day_return_pct"] = daily_return_series.shift(1)
    session_pdf["prev_day_range_pct"] = (session_pdf["prev_high"] - session_pdf["prev_low"]) / session_pdf["prev_close"]
    # CALCULATE THE DAILY VOLATILITY FROM PRIOR SESSIONS ONLY (SHIFTED SO THE CURRENT SESSION IS EXCLUDED)
    session_pdf["daily_volatility"] = daily_return_series.rolling(window=volatility_session_count_in,
                                                                  min_periods=volatility_session_count_in).std().shift(1)
    # RETURN DATAFRAME
    return session_pdf

# FUNCTION: GET THE RELATIVE VOLUME REFERENCE DATAFRAME
def get_relative_volume_reference_pdf(complete_ohlcv_pdf_in, date_market_open_ts_dict_in,
                                      session_count_in=config.CTX_RELATIVE_VOLUME_SESSIONS,
                                      min_session_count_in=config.CTX_RELATIVE_VOLUME_MIN_SESSIONS):
    """
    Calculates, for every session and minute of the day, the mean volume of the same minute over the previous sessions.

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Complete minute OHLCV data with timestamp, date and volume columns
        date_market_open_ts_dict_in (dict): datetime.date -> market open timestamp (barrier_labels.get_date_market_open_ts_dict)
        session_count_in (int): Number of previous sessions in the mean
        min_session_count_in (int): Minimum number of previous sessions with data for the minute

    Returns:
        pd.DataFrame: Columns date, minutes_since_open, reference_volume
    """
    # COPY THE REQUIRED COLUMNS
    volume_pdf = complete_ohlcv_pdf_in[["timestamp", "date", "volume"]].copy()
    # MAP THE MARKET OPEN OF EVERY ROW
    market_open_series = pd.to_datetime(volume_pdf["date"].map(date_market_open_ts_dict_in))
    # CALCULATE THE MINUTES SINCE THE OPEN
    volume_pdf["minutes_since_open"] = ((volume_pdf["timestamp"] - market_open_series).dt.total_seconds() // 60).astype("Int64")
    # PIVOT THE VOLUME (SESSIONS x MINUTES OF THE DAY)
    volume_pivot_pdf = volume_pdf.pivot_table(index="date", columns="minutes_since_open", values="volume", aggfunc="first").sort_index()
    # CALCULATE THE MEAN OF THE PREVIOUS SESSIONS (SHIFTED SO THE CURRENT SESSION IS EXCLUDED)
    reference_pivot_pdf = volume_pivot_pdf.rolling(window=session_count_in, min_periods=min_session_count_in).mean().shift(1)
    # UNPIVOT THE REFERENCE VOLUME
    reference_pdf = reference_pivot_pdf.stack().rename("reference_volume").reset_index()
    # RETURN DATAFRAME
    return reference_pdf

# FUNCTION: GENERATE THE DATE TIMESTAMP CONTEXT (TSCTX) DATAFRAME
def get_date_TSCTX_pdf(complete_ohlcv_pdf_in, session_summary_pdf_in, relative_volume_reference_pdf_in,
                       date_market_schedule_dict_in, date_str_in):
    """
    Generates the context feature rows of one session.

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Complete minute OHLCV data with date and cum_max columns (add_cum_max_col)
        session_summary_pdf_in (pd.DataFrame): Output of get_session_summary_pdf
        relative_volume_reference_pdf_in (pd.DataFrame): Output of get_relative_volume_reference_pdf
        date_market_schedule_dict_in (dict): datetime.date -> (market_open_ts, market_close_ts)
        date_str_in (str): Session date 'YYYY-MM-DD'

    Returns:
        pd.DataFrame: TSCTX rows (empty DataFrame if the session is not in the data)
    """
    # GET THE DATAFRAME FOR THE DATE
    date_ohlcv_pdf = get_date_pdf(complete_ohlcv_pdf_in, date_str_in, alert_in=False)
    # IF THE DATAFRAME IS EMPTY
    if pdf_is_empty(date_ohlcv_pdf, alert_in=False):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # CONVERT THE DATE STRING TO A DATE OBJECT
    date_object = pd.to_datetime(date_str_in).date()
    # IF THE SESSION HAS NO SCHEDULE OR NO SUMMARY
    if date_object not in date_market_schedule_dict_in or date_object not in set(session_summary_pdf_in["date"]):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # COLLECT THE MARKET OPEN AND CLOSE (THE CLOSE IS THE LAST BAR TIMESTAMP)
    market_open_ts, market_close_ts = date_market_schedule_dict_in[date_object]
    # COLLECT THE SESSION SUMMARY ROW
    summary_row = session_summary_pdf_in[session_summary_pdf_in["date"] == date_object].iloc[0]
    # SORT THE SESSION DATA
    date_ohlcv_pdf = date_ohlcv_pdf.sort_values("timestamp").reset_index(drop=True)
    # COLLECT THE SESSION OPEN (OPEN OF THE FIRST BAR, KNOWN FROM THE FIRST BAR ONWARDS)
    session_open = date_ohlcv_pdf["open"].iloc[0]
    # CREATE THE OUTPUT DATAFRAME
    TSCTX_pdf = pd.DataFrame({"timestamp": date_ohlcv_pdf["timestamp"]})
    # CALCULATE THE TIME POSITION FEATURES
    TSCTX_pdf["minutes_since_open"] = ((date_ohlcv_pdf["timestamp"] - market_open_ts).dt.total_seconds() // 60).astype(int)
    TSCTX_pdf["minutes_to_close"] = ((market_close_ts - date_ohlcv_pdf["timestamp"]).dt.total_seconds() // 60).astype(int)
    TSCTX_pdf["day_of_week"] = date_ohlcv_pdf["timestamp"].dt.dayofweek
    # CALCULATE THE PREVIOUS SESSION FEATURES
    TSCTX_pdf["overnight_gap_pct"] = round(session_open / summary_row["prev_close"] - 1, 8)
    TSCTX_pdf["prev_day_return_pct"] = summary_row["prev_day_return_pct"]
    TSCTX_pdf["prev_day_range_pct"] = summary_row["prev_day_range_pct"]
    TSCTX_pdf["prev_day_high_dist_pct"] = date_ohlcv_pdf["close"] / summary_row["prev_high"] - 1
    TSCTX_pdf["prev_day_low_dist_pct"] = date_ohlcv_pdf["close"] / summary_row["prev_low"] - 1
    # CALCULATE THE INTRADAY RETURN
    TSCTX_pdf["intraday_return_pct"] = date_ohlcv_pdf["close"] / session_open - 1
    # ADD THE DAILY VOLATILITY
    TSCTX_pdf["daily_volatility"] = summary_row["daily_volatility"]
    # COLLECT THE REFERENCE VOLUME OF THE SESSION
    date_reference_pdf = relative_volume_reference_pdf_in[relative_volume_reference_pdf_in["date"] == date_object]
    reference_volume_dict = dict(zip(date_reference_pdf["minutes_since_open"].astype(int), date_reference_pdf["reference_volume"]))
    # CALCULATE THE RELATIVE VOLUME
    reference_volume_series = TSCTX_pdf["minutes_since_open"].map(reference_volume_dict).astype(float)
    TSCTX_pdf["relative_volume"] = (date_ohlcv_pdf["volume"] / reference_volume_series.replace(0, np.nan)).to_numpy()
    # CALCULATE THE DISTANCE FROM THE ALL-TIME HIGH
    TSCTX_pdf["ath_drawdown_pct"] = date_ohlcv_pdf["close"] / date_ohlcv_pdf["cum_max"] - 1
    # ROUND THE FLOAT COLUMNS
    float_col_str_list = TSCTX_pdf.select_dtypes(include="float").columns
    TSCTX_pdf[float_col_str_list] = TSCTX_pdf[float_col_str_list].round(8)
    # RETURN DATAFRAME
    return TSCTX_pdf
