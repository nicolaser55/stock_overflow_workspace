import pandas as pd
import numpy as np
# IMPORT LOCAL FILE MANAGEMENT
from so.core.local_file_management import check_file_exists, read_csv_file_from_path, write_csv_file_to_path
# IMPORT MARKET DATETIME
from so.core.datetime_utils import ny_tz, get_date_pdf
# IMPORT PATHS
from so import paths
# IMPORT EXPERIMENT CONFIGURATION (function defaults read from here so every step uses the same constants)
from so import config
# IMPORT DATA QUALITY FUNCTIONS
from so.core.data_quality import validate_all_pdf_cols, check_var_type, pdf_is_empty

# FUNCTION: COLLECT DATE OHLCV AGGREGATED INFODATA
def get_date_ohlcv_agg_info_pdf(pdf_in):
    # CHECK IF THE VARIABLE IS A DATAFRAME
    if not check_var_type(pdf_in, pd.DataFrame):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # AGGREGATE TO COUNT BY TIMESTAMP
    return pdf_in.groupby("date").agg(ts_count=("timestamp","count"),
                                        start_ts=("timestamp","first"),
                                        end_ts=("timestamp","last")
                                    ).reset_index()


# FUNCTION: COLLECT DATE OHLCV DATA QUALITY INFORMATION
def get_date_ohlcv_DQ_info_pdf(pdf_in):
    # IMPORT MARKET DATETIME FUNCTION
    from so.core.datetime_utils import get_date_range_market_schedule_pdf
    # AGGREGATE TIMESTAMP INFORMATION BY DATE
    # (FIX 2026-10: previously called get_date_ohlcv_agg_pdf, which has no ts_count column, so the status comparison failed)
    date_agg_ohlcv_pdf = get_date_ohlcv_agg_info_pdf(pdf_in)
    # COLLECT MINIMUM AND MAXIMUM DATES
    start_date = date_agg_ohlcv_pdf.date.min()
    end_date = date_agg_ohlcv_pdf.date.max()
    # COLLECT MARKET SCHEDULE DATAFRAME
    date_market_schedule_data_pdf = get_date_range_market_schedule_pdf(start_date, end_date)
    # CALCULATE THE OPEN MINUTES
    date_market_schedule_data_pdf["minutes_open"] = (date_market_schedule_data_pdf.market_close_ts - date_market_schedule_data_pdf.market_open_ts).apply(lambda x: x.total_seconds() / 60).astype(int) + 1
    # SET THE DATE COLUMN TO STRING
    date_agg_ohlcv_pdf["date"] = date_agg_ohlcv_pdf.date.astype(str)
    date_market_schedule_data_pdf["date"] = date_market_schedule_data_pdf.date.astype(str)
    # MERGE THE DATE TIMESTAMP DATA WITH THE MARKET SCHEDULE DATA
    date_comparison_pdf = date_agg_ohlcv_pdf.merge(date_market_schedule_data_pdf, on="date", how="left")
    # CREATE A COLUMN TO LABEL WHEN THERE IS LESS DATA OR MORE DATA (-1 LESS DATA, 0 NORMAL, 1 MORE DATA)
    date_comparison_pdf["status"] = np.select([date_comparison_pdf.ts_count < date_comparison_pdf.minutes_open,
                                                date_comparison_pdf.ts_count == date_comparison_pdf.minutes_open,
                                                date_comparison_pdf.ts_count > date_comparison_pdf.minutes_open],
                                                [-1,
                                                0,
                                                1])
    # RETURN DATAFRAME
    return date_comparison_pdf

# FUNCTION: COLLECT OHLCV SANITY ISSUES
def get_ohlcv_sanity_issue_pdf(ohlcv_pdf_in):
    """
    Flags rows of an OHLCV DataFrame that break basic candlestick consistency rules.

    Checks performed (a row can fail several checks):
    - high below the open or the close
    - low above the open or the close
    - high below low
    - non-positive prices
    - negative volume
    - missing OHLCV values
    - duplicated timestamps (same timestamp with different values)

    Args:
        ohlcv_pdf_in (pd.DataFrame): DataFrame with timestamp, open, high, low, close, volume columns

    Returns:
        pd.DataFrame: The offending rows with an additional 'issue' column (comma separated issue names).
                      Empty DataFrame if no issues are found.
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["timestamp", "open", "high", "low", "close", "volume"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")
    # DEFINE THE ISSUE MASK DICTIONARY
    issue_mask_dict = {
        "high_below_body": ohlcv_pdf_in.high < ohlcv_pdf_in[["open", "close"]].max(axis=1),
        "low_above_body": ohlcv_pdf_in.low > ohlcv_pdf_in[["open", "close"]].min(axis=1),
        "high_below_low": ohlcv_pdf_in.high < ohlcv_pdf_in.low,
        "non_positive_price": (ohlcv_pdf_in[["open", "high", "low", "close"]] <= 0).any(axis=1),
        "negative_volume": ohlcv_pdf_in.volume < 0,
        "missing_value": ohlcv_pdf_in[required_col_str_list].isna().any(axis=1),
        "duplicated_timestamp": ohlcv_pdf_in.timestamp.duplicated(keep=False),
    }
    # CREATE THE ISSUE DATAFRAME (ONE BOOLEAN COLUMN PER ISSUE)
    issue_pdf = pd.DataFrame(issue_mask_dict, index=ohlcv_pdf_in.index)
    # COLLECT THE ROWS WITH AT LEAST ONE ISSUE
    any_issue_mask = issue_pdf.any(axis=1)
    # IF THERE ARE NO ISSUES
    if not any_issue_mask.any():
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame(columns=required_col_str_list + ["issue"])
    # COLLECT THE OFFENDING ROWS
    issue_rows_pdf = ohlcv_pdf_in.loc[any_issue_mask, required_col_str_list].copy()
    # JOIN THE NAMES OF THE FAILED CHECKS
    issue_rows_pdf["issue"] = issue_pdf.loc[any_issue_mask].apply(lambda row: ",".join(row.index[row.values]), axis=1)
    # RETURN DATAFRAME
    return issue_rows_pdf

# FUNCTION: FORMAT OHLCV DATA PDF
def format_ohlcv_pdf(ohlcv_pdf_in):
    """
    Formats and validates an OHLCV (Open, High, Low, Close, Volume) DataFrame.
    
    Performs the following operations:
    - Validates input is a non-empty pandas DataFrame with required columns
    - Checks for and removes any duplicate rows
    - Converts timestamp to NY timezone
    - Extracts date and year from timestamp
    - Reorders columns and resets index
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV market data with columns:
                      timestamp, open, high, low, close, volume
                      
    Returns:
        DataFrame with formatted timestamps
        
    Raises:
        ValueError: If DataFrame is empty, missing required columns, or contains duplicates
        TypeError: If input is not a pandas DataFrame
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["timestamp", "open", "high", "low", "close", "volume"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # COUNT THE LENGTH OF THE OHLCV DATAFRAME
    row_count = len(ohlcv_pdf_in)
    # DROP DUPLICATES
    ohlcv_pdf = ohlcv_pdf_in.drop_duplicates()
    # IF THE DROP DUPLICATES ROW COUNT IS NOT THE SAME AS THE ORIGINAL ROW COUNT
    if row_count != len(ohlcv_pdf):
        # RAISE AN ERROR
        raise ValueError("There are duplicate rows in the input OHLCV DataFrame")
    # CONVERT TIMESTAMP TO DATETIME WITH NY TIMEZONE
    ohlcv_pdf["timestamp"] = pd.to_datetime(ohlcv_pdf.timestamp, utc=True).dt.tz_convert(ny_tz)
    # RESET INDEX AND RETURN DATAFRAME
    return ohlcv_pdf.reset_index(drop=True)[["timestamp", "open", "high", "low", "close", "volume", "date"]]

# FUNCTION: DYNAMICALLY GENERATE DATAFRAME
def pdf_to_tf_pdf_list(pdf_in):
    """
    Creates a list of progressively larger dataframes from input dataframe
    
    Args:
        pdf_in: DataFrame containing OHLCV data
        
    Returns:
        List of DataFrames, each containing data up to index i
    """
    # IF THE DATAFRAME IS EMPTY
    if pdf_is_empty(pdf_in) == True:
        # DISPLAY INFORMATION
        print(f"❌ The input dataframe is empty!")
        # RETURN EMPTY LIST
        return []
    # RETURN LIST OF DATAFRAMES
    return [pdf_in.iloc[:idx+1] for idx in range(len(pdf_in))]

# FUNCTION: COLLECT CANDLESTICK ATTRIBUTES
def add_cs_attribute_cols(ohlcv_pdf_in):
    """
    Adds candlestick analysis columns to OHLCV DataFrame including:
    - Color (1 for green, -1 for red)
    - Span (total candle length)
    - Body top/bottom
    - Wick spans and percentages
    - Body span and percentage
    - 5-period rolling average span
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV data with columns 'open', 'high', 'low', 'close'
        
    Returns:
        DataFrame with additional candlestick attribute columns
        
    Raises:
        TypeError: If ohlcv_pdf_in is not a pandas DataFrame
        ValueError: If DataFrame is missing required OHLC columns
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["open", "high", "low", "close"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # IDENTIFY IF GREEN OR RED 
    ohlcv_pdf_in["color"] = (ohlcv_pdf_in.close >= ohlcv_pdf_in.open).map({True: 1, False: -1})
    # GET THE LENGTH OF THE CANDLESTICK
    ohlcv_pdf_in["span"] = ohlcv_pdf_in.high - ohlcv_pdf_in.low 
    # GET THE BODY BOTTOM AND TOP OF THE CANDLE STICK
    ohlcv_pdf_in["bot_body"] = ohlcv_pdf_in.apply(lambda pdf: min(pdf.close, pdf.open), axis=1)
    ohlcv_pdf_in["top_body"] = ohlcv_pdf_in.apply(lambda pdf: max(pdf.close, pdf.open), axis=1)
    # CALCULATE THE SIZE OF THE BOTTOM WICK AND THE TOP BICK
    ohlcv_pdf_in["bot_wick_span"] = ohlcv_pdf_in.bot_body - ohlcv_pdf_in.low
    ohlcv_pdf_in["top_wick_span"] = ohlcv_pdf_in.high - ohlcv_pdf_in.top_body 
    # CALCULATE THE SIZE OF THE BODY
    ohlcv_pdf_in["body_span"] = ohlcv_pdf_in.top_body - ohlcv_pdf_in.bot_body
    # CALCULATE THE PERCENTAGES OF THE TOP WICK, BODY, AND BOTTOM WICK
    ohlcv_pdf_in["top_wick_pct"] = (ohlcv_pdf_in.top_wick_span / ohlcv_pdf_in.span).fillna(0)
    ohlcv_pdf_in["body_pct"] = (ohlcv_pdf_in.body_span / ohlcv_pdf_in.span).fillna(0)
    ohlcv_pdf_in["bot_wick_pct"] = (ohlcv_pdf_in.bot_wick_span / ohlcv_pdf_in.span).fillna(0)
    # GET THE ROLLING AVERAGE OF THE LAST 5 CANDLES
    ohlcv_pdf_in["span_rolling_avg5"] = ohlcv_pdf_in.span.shift(1).rolling(window=5).mean()
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: GET THE AVERAGE PRICE FROM HIGH AND LOW
def add_avg_price_col(ohlcv_pdf_in):
    """
    Calculates average price from high and low columns
    
    Args:
        pdf_in: DataFrame containing OHLCV data
        
    Returns:
        DataFrame with new avg_price column
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["high", "low"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # CALCULATE AVERAGE PRICE FROM HIGH AND LOW
    ohlcv_pdf_in["avg_price"] = ((ohlcv_pdf_in["high"] + ohlcv_pdf_in["low"]) / 2).round(6)
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: CALCULATE AVERAGE TRUE RANGE (ATR)
def add_atr_col(ohlcv_pdf_in, period=config.PA_ATR_PERIOD):
    """
    Calculate the Average True Range (ATR) for a given OHLCV dataframe.
    
    Parameters:
    -----------
    ohlcv_pdf_in : pandas.DataFrame
        DataFrame containing OHLC data with columns 'high', 'low', 'close'
    period : int, optional
        The period over which to calculate ATR, default is config.PA_ATR_PERIOD (10)
        
    Returns:
    --------
    pandas.DataFrame
        Original dataframe with an additional 'atr' column
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["high", "low", "close"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # IF THE PERIOD IS NOT A POSITIVE INTEGER
    if not isinstance(period, int) or period < 1:
        # RAISE AN ERROR
        raise ValueError("period must be a positive integer")

    # CALCULATE THE TRUE RANGE
    ohlcv_pdf_in["tr1"] = abs(ohlcv_pdf_in.high - ohlcv_pdf_in.low)
    ohlcv_pdf_in["tr2"] = abs(ohlcv_pdf_in.high - ohlcv_pdf_in.close.shift(1))
    ohlcv_pdf_in["tr3"] = abs(ohlcv_pdf_in.low - ohlcv_pdf_in.close.shift(1))
    ohlcv_pdf_in["true_range"] = ohlcv_pdf_in[["tr1", "tr2", "tr3"]].max(axis=1)
    # CALCULATE THE AVERAGE TRUE RANGE
    ohlcv_pdf_in["atr"] = ohlcv_pdf_in["true_range"].rolling(window=period).mean().round(6)
    # DROP THE INTERMEDIATE COLUMNS AND RETURN THE DATAFRAME
    return ohlcv_pdf_in.drop(columns=["tr1", "tr2", "tr3", "true_range"])

# FUNCTION: TO SMOOTH THE PRICE CURVE
def add_smooth_price_col(ohlcv_pdf_in, column_str_in="avg_price", window_in=config.PA_SMOOTH_WINDOW):
    """
    Calculate a derived price column using a rolling window average with forward shift.
    
    This function creates a smoothed price series by applying a rolling window average
    and then shifting it forward to reduce lag. For the initial rows where the shifted
    values would be NaN, it interpolates between the first price and the first valid
    derived price to maintain continuity.
    
    Parameters:
    -----------
    ohlcv_pdf_in : pandas.DataFrame
        DataFrame containing OHLC data
    column_str_in : str, optional
        Name of the column to derive the price from, default is "avg_price"
    window_in : int, optional
        Rolling window size for the moving average, default is config.PA_SMOOTH_WINDOW (4)
        
    Returns:
    --------
    pandas.DataFrame
        Original dataframe with an additional 'smooth_price' column containing
        the derived smoothed price series
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["avg_price"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")
    
    # DEFINE THE SHIFT INT
    shift_int = window_in - 3
    # DEFINE THE SHIFTED MOVING AVERAGE COLUMN NAME
    ma_col_str = "smooth_price"
    # ADD MOVING AVERAGE COLUMN
    ohlcv_pdf_in[ma_col_str] = ohlcv_pdf_in[column_str_in].rolling(window=window_in).mean().shift(-shift_int)
    # DEFINE THE DATA START INDEX
    d_start_idx = window_in - shift_int - 1
    # IF THE DATAFRAME IS GREATER THAN THE WINDOW IN
    if len(ohlcv_pdf_in) >= window_in:
        # CREATE A LIST OF PRICES FROM START AVERAGE PRICE TO START OF DERIVED PRICE AND ADD TO THE FIRST 2 ROWS
        ohlcv_pdf_in.loc[ohlcv_pdf_in.index[:d_start_idx], ma_col_str] = np.linspace(ohlcv_pdf_in.avg_price.iloc[0], ohlcv_pdf_in[ma_col_str].iloc[d_start_idx], d_start_idx+1)[:-1]
    # ROUND THE DERIVED PRICE COLUMN
    ohlcv_pdf_in[ma_col_str] = ohlcv_pdf_in[ma_col_str].round(6)
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: ADD MINIMA COLUMN
def add_minima_col(ohlcv_pdf_in, col_str_in="low", order_in=config.PA_EXTREMA_ORDER):
    """
    Adds minima column to a DataFrame using vectorized operations
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV data
        order: Order of the moving average window
        
    Returns:    
        DataFrame with minima column
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["low"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # SET THE OUTPUT COLUMN NAME
    col_str_out = f"{col_str_in}_minima" if col_str_in != "low" else "minima"
    # GET THE LOWS  
    lows = ohlcv_pdf_in[col_str_in].values
    # INITIALIZE MINIMA COLUMN
    ohlcv_pdf_in[col_str_out] = np.nan
    
    # VECTORIZED MINIMA DETECTION
    for i in range(order_in, len(lows) - order_in):
        # GET WINDOW AROUND CURRENT POINT
        window = lows[i - order_in : i + order_in + 1]
        # CHECK IF CURRENT POINT IS THE MINIMUM IN THE WINDOW
        if lows[i] == np.min(window):
            # SET THE MINIMA TO THE LOW
            ohlcv_pdf_in.iloc[i, ohlcv_pdf_in.columns.get_loc(col_str_out)] = lows[i]
    
    # REMOVE ADJACENT MINIMA USING VECTORIZED OPERATIONS
    minima_mask = ohlcv_pdf_in[col_str_out].notna()
    # IF THERE ARE MINIMA
    if minima_mask.sum() > 1:
        # GET INDICES WHERE MINIMA EXIST
        minima_indices = np.where(minima_mask)[0]
        # FIND ADJACENT PAIRS (DIFFERENCE OF LESS THAN OR EQUAL TO 2)
        adjacent_pairs = np.where(np.diff(minima_indices) <= 2)[0]
        # REMOVE THE SECOND MINIMA IN EACH ADJACENT PAIR
        if len(adjacent_pairs) > 0:
            # GET INDICES TO REMOVE
            indices_to_remove = minima_indices[adjacent_pairs + 1]
            # SET THE MINIMA TO NA
            ohlcv_pdf_in.iloc[indices_to_remove, ohlcv_pdf_in.columns.get_loc(col_str_out)] = np.nan
    # ADD MINIMA TO THE FIRST ROW OF THE DATAFRAME
    ohlcv_pdf_in.loc[ohlcv_pdf_in.index[0], col_str_out] = ohlcv_pdf_in.loc[ohlcv_pdf_in.index[0], col_str_in]
    # RETURN THE DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: ADD MAXIMA COLUMN
def add_maxima_col(ohlcv_pdf_in, col_str_in="high", order_in=config.PA_EXTREMA_ORDER):
    """
    Adds maxima column to a DataFrame using vectorized operations
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV data
        order: Order of the moving average window
        
    Returns:    
        DataFrame with maxima column
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["high"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # SET THE OUTPUT COLUMN NAME
    col_str_out = f"{col_str_in}_maxima" if col_str_in != "high" else "maxima"
    # GET THE HIGHS  
    highs = ohlcv_pdf_in[col_str_in].values
    # INITIALIZE MAXIMA COLUMN
    ohlcv_pdf_in[col_str_out] = np.nan
    
    # VECTORIZED MAXIMA DETECTION
    for i in range(order_in, len(highs) - order_in):
        # GET WINDOW AROUND CURRENT POINT
        window = highs[i - order_in : i + order_in + 1]
        # CHECK IF CURRENT POINT IS THE MAXIMUM IN THE WINDOW
        if highs[i] == np.max(window):
            # ADD THE MAXIMA TO THE DATAFRAME
            ohlcv_pdf_in.iloc[i, ohlcv_pdf_in.columns.get_loc(col_str_out)] = highs[i]
    
    # REMOVE ADJACENT MAXIMA USING VECTORIZED OPERATIONS
    maxima_mask = ohlcv_pdf_in[col_str_out].notna()
    # IF THERE ARE MAXIMA
    if maxima_mask.sum() > 1:
        # GET INDICES WHERE MAXIMA EXIST
        maxima_indices = np.where(maxima_mask)[0]
        # FIND ADJACENT PAIRS (DIFFERENCE OF LESS THAN OR EQUAL TO 2)
        adjacent_pairs = np.where(np.diff(maxima_indices) <= 2)[0]
        # REMOVE THE SECOND MAXIMA IN EACH ADJACENT PAIR
        if len(adjacent_pairs) > 0:
            # GET INDICES TO REMOVE
            indices_to_remove = maxima_indices[adjacent_pairs + 1]
            # SET THE MAXIMA TO NA
            ohlcv_pdf_in.iloc[indices_to_remove, ohlcv_pdf_in.columns.get_loc(col_str_out)] = np.nan
    # ADD MAXIMA TO THE FIRST ROW OF THE DATAFRAME
    ohlcv_pdf_in.loc[ohlcv_pdf_in.index[0], col_str_out] = ohlcv_pdf_in.loc[ohlcv_pdf_in.index[0], col_str_in]
    # RETURN THE DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: ADD MINIMA AND MAXIMA COLUMNS TO DATAFRAME
def add_extremas_cols(ohlcv_pdf_in, order_in=config.PA_EXTREMA_ORDER):
    """
    Adds minima and maxima columns to a dataframe
    
    Args:
        pdf_in: DataFrame containing price data
        window_in: Window size for minima and maxima (default 4)
        
    Returns:
        DataFrame with minima and maxima columns
    """    
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["high", "low"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # CALL FUNCTION TO GET EXTREMAS AND RETURN DATAFRAME
    return add_maxima_col(add_minima_col(ohlcv_pdf_in, order_in=order_in), order_in=order_in)

# FUNCITON: IDENTIFY PATTERNS WITHIN PHASES 
def add_extremas_pp_col(ohlcv_pdf_in):
    """
    Creates price pattern (pp) column from extrema points and interpolates between them
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV data with extrema columns
        
    Returns:
        DataFrame with new extremas_pp column containing interpolated price patterns
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["minima", "maxima", "avg_price"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # CREATE A PRICE PATTERN COLUMN WHERE AN EXTREMA IS FOUND USING THE AVERAGE PRICE
    ohlcv_pdf_in["extremas_pp"] = np.where((ohlcv_pdf_in.minima.notna() | ohlcv_pdf_in.maxima.notna()), ohlcv_pdf_in.avg_price, np.nan)
    # ADD THE FIRST AVERAGE PRICE TO THE FIRST ROW OF THE PRICE PATTERN COLUMN
    ohlcv_pdf_in.loc[ohlcv_pdf_in.index[0], "extremas_pp"] = ohlcv_pdf_in.iloc[0]["avg_price"]
    # ADD THE LAST AVEAGE PRICE TO THE LAST ROW OF THE PRICE PATTERN COLUMN
    ohlcv_pdf_in.loc[ohlcv_pdf_in.index[-1], "extremas_pp"] = ohlcv_pdf_in.iloc[-1]["avg_price"]
    # INTERPOLATE PRICE PATTERN
    ohlcv_pdf_in["extremas_pp"] = ohlcv_pdf_in["extremas_pp"].interpolate().round(6)
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: ADD COMPOSITE PRICE COLUMN (formerly: der_price, now: composite_price)
def add_composite_price_col(ohlcv_pdf_in, column_str_in="smooth_price", bias_float_in=config.PA_COMPOSITE_BIAS):
    """
    Mixes the smoothed price with the extrema price pattern into the composite price.

    Args:
        ohlcv_pdf_in: DataFrame containing the smooth price and extremas_pp columns
        column_str_in: Smoothed price column to mix (default "smooth_price")
        bias_float_in: Weight of the smoothed price (default config.PA_COMPOSITE_BIAS = 0.4, chosen visually;
                       0.5 and 0.45 were tried before). The remaining weight goes to extremas_pp.

    Returns:
        DataFrame with the composite_price column
    """
    # ADD BIAS (FROM CONFIGURATION)
    bias_float = bias_float_in
    # ANTI BIAS
    anti_bias_float = 1 - bias_float
    # GET THE AVERAGE OF AVG PRICE AND EXTREMAS PP
    ohlcv_pdf_in["composite_price"] = (ohlcv_pdf_in[column_str_in] * bias_float + ohlcv_pdf_in["extremas_pp"] * anti_bias_float).round(6)
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: ADD THE SLOPE COLUMN
def add_slope_col(ohlcv_pdf_in, column_str_in="composite_price"):
    """
    Calculates slope between consecutive points in specified column
    
    Args:
        ohlcv_pdf_in: DataFrame containing price data
        column_str_in: Column to calculate slope for
        
    Returns:
        DataFrame with new slope column
    """
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, [column_str_in]):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {[column_str_in]}")

    # CALCULATE THE SLOPE 
    ohlcv_pdf_in[f"{column_str_in}_slope"] = ohlcv_pdf_in[column_str_in].diff().round(6)
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: IDENTIFY THE TREND
def add_trend_col(ohlcv_pdf_in, column_str_in="composite_price", slope_limit_in=config.PA_TREND_SLOPE_LIMIT):
    """
    Labels price trends as bullish, bearish or consolidation based on slope
    
    Args:
        ohlcv_pdf_in: DataFrame containing price data
        column_str_in: Column to analyze for trend
        slope_limit_in: Threshold for trend classification
        
    Returns:
        DataFrame with new trend column
    """
    # VALIDATE IF THE SLOPE LIMIT IS A POSITIVE NUMBER
    if not isinstance(slope_limit_in, (int, float)) or slope_limit_in <= 0:
        # RAISE AN ERROR
        raise ValueError("slope_limit_in must be a positive number")
    
    # DEFINE THE SLOPE COLUMN
    slope_col_str = f"{column_str_in}_slope"
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, [slope_col_str]):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {[slope_col_str]}")

    # LABEL TRENDS USING SLOPE
    ohlcv_pdf_in["trend"] = np.select([ohlcv_pdf_in[slope_col_str] > slope_limit_in,
                                        ohlcv_pdf_in[slope_col_str].between(-slope_limit_in, slope_limit_in),
                                        ohlcv_pdf_in[slope_col_str] < -slope_limit_in],
                                        [1,
                                        0,
                                        -1],
                                        np.nan)
    # IF THE DATAFRAME HAS MORE THAN 1 ROW
    if len(ohlcv_pdf_in) > 1:
        # SET THE FIRST VALUE IN THE TREND TO THE SECOND VALUE IN THE TREND
        ohlcv_pdf_in.loc[ohlcv_pdf_in.index[0], "trend"] = ohlcv_pdf_in.iloc[1]["trend"]
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: ADD SEGMENT COLUMN
def add_segment_col(ohlcv_pdf_in, column_name_str_in="trend"):
    """
    Adds a segment column to the OHLCV PDF based on the trend column.
    
    Args:
        ohlcv_pdf_in: The OHLCV PDF to add the segment column to.
        column_name_str_in: The name of the column to add the segment to.
    
    Returns:
        The OHLCV PDF with the segment column added.
    """
    # ADD SEGMENT COLUMN TO THE TREND
    ohlcv_pdf_in["segment"] = (ohlcv_pdf_in[column_name_str_in] != ohlcv_pdf_in[column_name_str_in].shift(1)).cumsum()
    # SET THE SEGMENT COLUMN TO NA IF THE TREND IS NA
    ohlcv_pdf_in["segment"] = np.where(ohlcv_pdf_in[column_name_str_in].notna(), ohlcv_pdf_in.segment, np.nan)
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: CONSOLIDATE PRICE ACTION MARKET STRUCTURE CODE
def add_PA_cols(ohlcv_pdf_in):
    """
    Applies Price Action Market Structure (PA) analysis to OHLCV data
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV data
        
    Returns:
        DataFrame with added PA analysis columns
    """
    # DEFINE REQUIRED COLUMNS
    required_col_str_list = ["open", "high", "low", "close", "volume"]
    # VALIDATE THE DATAFRAME COLS
    if not validate_all_pdf_cols(ohlcv_pdf_in, required_col_str_list):
        # RAISE AN ERROR
        raise ValueError(f"DataFrame does not contain the required columns: {required_col_str_list}")

    # USE PANDAS PIPE METHOD TO CHAIN OPERATIONS
    return (ohlcv_pdf_in.pipe(add_avg_price_col)\
                        .pipe(add_atr_col) \
                        .pipe(add_smooth_price_col) \
                        .pipe(add_extremas_cols) \
                        .pipe(add_extremas_pp_col) \
                        .pipe(add_composite_price_col) \
                        .pipe(add_slope_col) \
                        .pipe(add_trend_col) \
                        .pipe(add_segment_col) \
            )

# FUNCTION: CALCULATE PRICE PATTERNS FOR TIMELAPSE DATA
def get_PA_tf_ohlcv_pdf_list(ohlcv_pdf_in, alert_in=True):
    """
    Applies PA analysis to a list of OHLCV dataframes
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV data
        alert_in: Boolean to control progress messages
        
    Returns:
        List of DataFrames with PA analysis applied
    """
    # CALL FUNCTION TO GET LIST OF DATAFRAMES
    tf_ohlcv_pdf_list = pdf_to_tf_pdf_list(ohlcv_pdf_in)
    # LIST TO HOLD DATAFRAMES
    tf_ohlcv_PA_pdf_list = []
    # ITERATE OVER TIMEFRAME OHLCV PDF LIST
    for idx, tf_ohlcv_pdf in enumerate(tf_ohlcv_pdf_list, 1):
        # DISPLAY INFORMATION
        print(f"Processing DataFrame:\t[{idx}/{len(tf_ohlcv_pdf_list)}]") if alert_in else None
        # CALL THE APPLY DERIVATION FUNCTION TO DATAFRAME
        tf_ohlcv_PA_pdf_list.append(add_PA_cols(tf_ohlcv_pdf.copy()))
    # RETURN LIST
    return tf_ohlcv_PA_pdf_list

# FUNCTION: CONVERT OHLCV DATAFRAME TO TIMEFRAME OHLCV DATAFRAME LIST
def ohlcv_pdf_to_PA_tf_ohlcv_pdf_list(ohlcv_pdf_in, alert_in=True):
    """
    Transforms OHLCV data by applying PA analysis and stabilizing extrema points
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV data
        alert_in: Boolean to control progress messages
        
    Returns:
        List of DataFrames with PA analysis and stabilized extrema
    """
    # IF THE DATAFRAME IS EMPTY
    if ohlcv_pdf_in.empty:
        # RETURN EMPTY LIST
        return []
    # CALL FUNCTION TO GET PA OHLCV PDF LIST
    return get_PA_tf_ohlcv_pdf_list(ohlcv_pdf_in, alert_in=False)

# FUNCTION: PROCESS DATE OHLCV DATA
def process_date_PA_tf_ohlcv_pdf_list(complete_ohlcv_pdf_in, date_str_in, alert_in=True):
    """
    Processes OHLCV data for a specific date by applying PA (Price Action) analysis and generating a list
    of time-framed OHLCV DataFrames with PA features.

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Full OHLCV DataFrame containing all dates.
        date_str_in (str): The date string (e.g., 'YYYY-MM-DD') to filter and process.
        alert_in (bool): If True, display processing information.

    Returns:
        list of pd.DataFrame: List of OHLCV DataFrames with PA analysis, one per timeframe for the given date.
    """
    #  GET DATAFRAME FOR DATE
    date_ohlcv_pdf = get_date_pdf(complete_ohlcv_pdf_in, date_str_in)
    # CONVERT OHLCV PDF TO PA TF OHLCV PDF LIST
    return ohlcv_pdf_to_PA_tf_ohlcv_pdf_list(date_ohlcv_pdf, alert_in=alert_in)

def tf_ohlcv_pdf_list_to_full_tf_ohlcv_pdf(ohlcv_pdf_list_in):
    """
    Concatenates a list of OHLCV DataFrames (one per timeframe) into a single DataFrame.
    Each original DataFrame is tagged with a unique 'pdf_id' column for identification.

    Args:
        ohlcv_pdf_list_in (list of pd.DataFrame): List of OHLCV DataFrames to concatenate.

    Returns:
        pd.DataFrame: Concatenated DataFrame with all input DataFrames combined and a 'pdf_id' column.
                      If input list is empty, returns an empty DataFrame.
    """
    # IF THE LIST IS EMPTY
    if not ohlcv_pdf_list_in:
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # LIST TO HOLD DATAFRAMES
    labeled_ohlcv_pdf_list = []
    # FOR DATAFRAME IN LIST
    for pdf_idx, tf_ohlcv_pdf in enumerate(ohlcv_pdf_list_in):
        # ADD A COLUMN TO THE DATAFRAME WITH THE PDF ID
        tf_ohlcv_pdf["pdf_id"] = pdf_idx
        # APPEND THE DATAFRAME TO THE LIST
        labeled_ohlcv_pdf_list.append(tf_ohlcv_pdf)
    # CONCATENATE ALL DATAFRAMES
    return pd.concat(labeled_ohlcv_pdf_list)

def full_tf_ohlcv_pdf_to_tf_ohlcv_pdf_list(full_ohlcv_pdf_in):
    """
    Splits a concatenated OHLCV DataFrame (with a 'pdf_id' column) back into a list of DataFrames,
    one per timeframe. Removes the 'pdf_id' column from each split DataFrame.

    Args:
        full_ohlcv_pdf_in (pd.DataFrame): Concatenated DataFrame containing a 'pdf_id' column.

    Returns:
        list of pd.DataFrame: List of OHLCV DataFrames for each unique pdf_id.
                              Returns an empty list if input DataFrame is empty.
    """
    # IF THE DATAFRAME IS EMPTY
    if full_ohlcv_pdf_in.empty:
        # RETURN EMPTY LIST
        return []
    # SPLIT THE DATAFRAME BY THE PDF ID AND RETURN
    return [pdf.drop(columns=["pdf_id"]) for _, pdf in full_ohlcv_pdf_in.groupby("pdf_id")]

def read_date_tf_ohlcv_pdf_list(data_file_path_str_in, date_str_in, alert_in=True):
    """
    Reads a timeframed and processed OHLCV CSV file for a specific date,
    if it exists, from disk. Returns the loaded and split list of DataFrames.

    Args:
        data_file_path_str_in (str): Directory or base file path to look for the data file.
        date_str_in (str): Date string (e.g., 'YYYY-MM-DD') to load.
        alert_in (bool): If True, print status and errors.

    Returns:
        list of pd.DataFrame: List of OHLCV DataFrames for the requested date.
                              Empty list if file not found or data is empty.
    """
    # CONVERT DATE TO STRING
    date_name_str = pd.to_datetime(date_str_in).strftime("%Y%m%d")
    # DEFINE FILE NAME
    data_file_name = f"ohlcv_data_{date_name_str}.csv"
    # DEFINE DATA FILE PATH
    data_file_path_str = f"{data_file_path_str_in}{data_file_name}"
    # IF THE FILE EXISTS
    if check_file_exists(data_file_path_str):
        # READ DATAFRAME
        full_PA_tf_ohlcv_pdf = read_csv_file_from_path(data_file_path_str, alert_in=alert_in)
        # IF THE FILE IS A DATAFRAME
        if isinstance(full_PA_tf_ohlcv_pdf, pd.DataFrame):
            # CONVERT TIMESTAMP TO DATETIME
            full_PA_tf_ohlcv_pdf.timestamp = pd.to_datetime(full_PA_tf_ohlcv_pdf.timestamp, utc=True).dt.tz_convert(ny_tz)
            # CALL FUNCTION TO CONVERT FULL TF OHLCV PDF TO TF OHLCV PDF LIST
            return full_tf_ohlcv_pdf_to_tf_ohlcv_pdf_list(full_PA_tf_ohlcv_pdf)
    # DISPLAY INFORMATION
    print(f"OHLCV Data For '{date_str_in}' Not Found") if alert_in else None
    # RETURN EMPTY LIST
    return []

def get_or_create_date_PA_tf_ohlcv_pdf_list(ohlcv_pdf_in, date_str_in, alert_in=True):
    """
    Gets the PA-processed (Price Action-derived) list of OHLCV DataFrames for a particular date,
    either by reading a cached CSV file if available, or by generating and saving it if not.

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Complete OHLCV DataFrame containing all dates and times.
        date_str_in (str): Date string (e.g., 'YYYY-MM-DD') to process or read.
        alert_in (bool): If True, display processing messages.

    Returns:
        list of pd.DataFrame: List of PA-labeled OHLCV DataFrames, one per timeframe, for the date.
    """
    # CALL FUNCTION TO READ DATE TF OHLCV PDF LIST
    date_tf_ohlcv_pdf_list = read_date_tf_ohlcv_pdf_list(paths.LOCAL_PA_OHLCV_DATA_FILE_PATH_STR, date_str_in, alert_in=alert_in)
    # IF THE DATAFRAME LIST EXISTS
    if date_tf_ohlcv_pdf_list:
        # RETURN THE DATAFRAME LIST
        return date_tf_ohlcv_pdf_list
    # GENERATE DATE OHLCV DATAFRAME LIST
    date_PA_tf_ohlcv_pdf_list = process_date_PA_tf_ohlcv_pdf_list(ohlcv_pdf_in, date_str_in)
    # CALL FUNCTION TO CONVERT TF OHLCV PDF LIST TO FULL TF OHLCV PDF
    full_PA_tf_ohlcv_pdf = tf_ohlcv_pdf_list_to_full_tf_ohlcv_pdf(date_PA_tf_ohlcv_pdf_list)
    # DEFINE DATE NAME
    date_name_str = pd.to_datetime(date_str_in).strftime('%Y%m%d')
    # DEFINE SAVE DATA FILE PATH
    save_data_file_path_str = f"{paths.LOCAL_PA_OHLCV_DATA_FILE_PATH_STR}ohlcv_data_{date_name_str}.csv"
    # SAVE FULL TF OHLCV PDF TO CSV
    write_csv_file_to_path(full_PA_tf_ohlcv_pdf, save_data_file_path_str, "W", alert_in=alert_in)
    # CALL FUNCTION TO CONVERT FULL TF OHLCV PDF TO TF OHLCV PDF LIST
    return full_tf_ohlcv_pdf_to_tf_ohlcv_pdf_list(full_PA_tf_ohlcv_pdf)


