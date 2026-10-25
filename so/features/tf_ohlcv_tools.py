# IMPORT GENERAL PACKAGES
import numpy as np
# IMPORT EXPERIMENT CONFIGURATION (indicator defaults read from here so every step uses the same constants)
from so import config


import plotly.express as px
# DEFINE A COLOR LIST
color_list = px.colors.qualitative.Alphabet


# FUNCTION: GET OHLCV MARKET STRUCTURE DICT
def detect_market_structure(ohlcv_pdf_in):
    """
    Analyzes price action to detect market structure by examining the relationships between local minima and maxima.
    
    The function identifies trends by comparing consecutive minima and maxima points to determine if the market is in a 
    bullish or bearish trend. It also detects key structural events like Break of Structure (BOS) and Change of Character (CHOCH).

    Parameters:
    -----------
    ohlcv_pdf_in : pandas.DataFrame
        DataFrame containing OHLCV (Open, High, Low, Close, Volume) data with additional columns for minima and maxima points

    Returns:
    --------
    dict
        Dictionary containing market structure information:
        - current_low: Latest low price
        - current_high: Latest high price 
        - current_minima: Most recent local minimum
        - current_maxima: Most recent local maximum
        - minima_seg: Count of minima points
        - maxima_seg: Count of maxima points
        - low_status: Status of current low ('bearish_BOS', 'bearish_CHOCH', or NaN)
        - high_status: Status of current high ('bullish_BOS', 'bullish_CHOCH', or NaN)
        - minima_trend: Trend direction based on minima ('bullish', 'bearish', or '')
        - maxima_trend: Trend direction based on maxima ('bullish', 'bearish', or '')
        - trend: Overall market trend ('bullish', 'bearish', or '')
    """
    # PRE-DEFINE MARKET STRUCTURE DICTIONARY
    market_structure_dict = {
        "current_low": np.nan,
        "current_high": np.nan,
        "current_minima": np.nan,
        "current_maxima": np.nan,
        "minima_seg": np.nan,
        "maxima_seg": np.nan,
        "low_status": np.nan,
        "high_status": np.nan,
        "minima_trend": "",
        "maxima_trend": "",
        "trend": "",
    }
    # IF THE OHLCV DATAFRAME IS EMPTY
    if ohlcv_pdf_in.empty:
        # RETURN AN EMPTY DICTIONARY
        return market_structure_dict
    # COLLECT THE MINIMA COUNT
    minima_count = ohlcv_pdf_in.minima.count()
    # IF THERE IS MORE THAN 1 MINIMA
    if minima_count > 1:
        # SET THE MINIMA SEGMENT
        market_structure_dict["minima_seg"] = minima_count
        # COLLECT THE MINIMAS AND MAXIMAS
        minimas_pdf = ohlcv_pdf_in[ohlcv_pdf_in.minima.notna()]
        # COLLECT THE PREVIOUS 0 AND 1 MINIMAS
        prev_0_minima = minimas_pdf.iloc[-1].minima
        prev_1_minima = minimas_pdf.iloc[-2].minima
        # SET THE CURRENT MINIMA PRICE
        market_structure_dict["current_minima"] = prev_0_minima
        # CALCULATE THE MINIMA DIFFERENCE
        minima_diff = prev_0_minima - prev_1_minima
        # IF THE PREVIOUS 0 MINIMA IS LESS THAN THE PREVIOUS 1 MINIMA
        if minima_diff < 0:
            # SET THE MINIMA TREND TO BEARISH
            market_structure_dict["minima_trend"] = "bearish"
        # IF THE PREVIOUS 0 MINIMA IS GREATER THAN THE PREVIOUS 1 MINIMA
        elif minima_diff > 0:
            # SET THE MINIMA TREND TO BULLISH
            market_structure_dict["minima_trend"] = "bullish"
        # IF THE MINIMA DIFFERENCE IS 0
        else:
            # COLLECT LIST OF MINIMAS
            minima_list = minimas_pdf.minima.tolist()
            # PRE DEFINE THE MINIMA 0 DIFF
            minima_0_diff = 0
            # ITERATE OVER PREVIOUS MINIMA LIST (EXCLUDING THE CURRENT MINIMA)
            for idx in range(2, minima_count):
                # DEFINE THE PREV 1 AND PREV 2 MINIMAS
                prev1_idx = - idx
                prev2_idx = - idx - 1
                # SELECT THE PREVIOUS MINIMAS
                prev_01_minima = minima_list[prev1_idx]
                prev_02_minima = minima_list[prev2_idx]
                # CALCULATE THE DIFFERENCE 
                minima_0_diff = prev_01_minima - prev_02_minima
                # IF THE MINIMA DIFFERENCE IS NOT 0
                if minima_0_diff != 0:
                    # BREAK THE LOOP
                    break
            # IF THE MINIMA 0 DIFF IS NEGATIVE
            if minima_0_diff < 0:
                # SET THE MINIMA TREND TO BEARISH
                market_structure_dict["minima_trend"] = "bearish"
            # IF THE MINIMA 0 DIFF IS POSITIVE
            elif minima_0_diff > 0:
                # SET THE MINIMA TREND TO BULLISH
                market_structure_dict["minima_trend"] = "bullish"

    # COLLECT THE MAXIMA COUNT
    maxima_count = ohlcv_pdf_in.maxima.count()
    # IF THERE IS MROE THAN 1 MAXIMA
    if maxima_count > 1:
        # SET THE MAXIMA SEGMENT
        market_structure_dict["maxima_seg"] = maxima_count
        # COLLECT THE MAXIMAS AND MINIMAS
        maximas_pdf = ohlcv_pdf_in[ohlcv_pdf_in.maxima.notna()]
        # COLLECT THE PREVIOUS 0 AND 1 MAXIMAS
        prev_0_maxima = maximas_pdf.iloc[-1].maxima
        prev_1_maxima = maximas_pdf.iloc[-2].maxima
        # SET THE CURRENT MAXIMA PRICE
        market_structure_dict["current_maxima"] = prev_0_maxima
        # CALCULATE THE MAXIMA DIFFERENCE
        maxima_diff = prev_0_maxima - prev_1_maxima
        # IF THE PREVIOUS 0 MAXIMA IS GREATER THAN THE PREVIOUS 1 MAXIMA
        if maxima_diff < 0:
            # SET THE MAXIMA TREND TO BEARISH
            market_structure_dict["maxima_trend"] = "bearish"
        # IF THE PREVIOUS 0 MAXIMA IS LESS THAN THE PREVIOUS 1 MAXIMA
        elif maxima_diff > 0:
            # SET THE MAXIMA TREND TO BULLISH
            market_structure_dict["maxima_trend"] = "bullish"
        # IF THE MAXIMA DIFFERENCE IS 0
        else:
            # COLLECT LIST OF MAXIMAS
            maxima_list = maximas_pdf.maxima.tolist()
            # PRE DEFINE THE MAXIMA 0 DIFF
            maxima_0_diff = 0
            # ITERATE OVER PREVIOUS MAXIMA LIST (EXCLUDING THE CURRENT MAXIMA)
            for idx in range(2, maxima_count):
                # DEFINE THE PREV 1 AND PREV 2 MAXIMAS
                prev1_idx = - idx
                prev2_idx = - idx - 1
                # SELECT THE PREVIOUS MAXIMAS
                prev_01_maxima = maxima_list[prev1_idx]
                prev_02_maxima = maxima_list[prev2_idx]
                # CALCULATE THE DIFFERENCE
                maxima_0_diff = prev_01_maxima - prev_02_maxima
                # IF THE MAXIMA DIFFERENCE IS NOT 0
                if maxima_0_diff != 0:
                    # BREAK THE LOOP
                    break
            # IF THE MAXIMA 0 DIFF IS NEGATIVE
            if maxima_0_diff < 0:
                # SET THE MAXIMA TREND TO BEARISH
                market_structure_dict["maxima_trend"] = "bearish"
            # IF THE MAXIMA 0 DIFF IS POSITIVE
            elif maxima_0_diff > 0:
                # SET THE MAXIMA TREND TO BULLISH
                market_structure_dict["maxima_trend"] = "bullish"
    
    # IF THE CURRENT MINIMA AND MAXIMA TRENDS ARE BEARISH (SET TREND TO BEARISH)
    if (market_structure_dict["minima_trend"] == market_structure_dict["maxima_trend"] == "bearish"):
        # SET THE TREND TO BEARISH
        market_structure_dict["trend"] = "bearish"
    # IF THE CURRENT MINIMA AND MAXIMA TRENDS ARE BULLISH (SET TREND TO BULLISH)
    if (market_structure_dict["minima_trend"] == market_structure_dict["maxima_trend"] == "bullish"):
        # SET THE TREND TO BULLISH
        market_structure_dict["trend"] = "bullish"
    # IF THE MINIMA TREND DOES NOT EQUAL THE MAXIMA TREND (SET TREND TO "")
    if (market_structure_dict["minima_trend"] != market_structure_dict["maxima_trend"]):
        # SET THE TREND TO UNDEFINED
        market_structure_dict["trend"] = ""

    # COLLECT THE CURRENT LOW AND HIGH
    current_low = ohlcv_pdf_in.iloc[-1].low
    current_high = ohlcv_pdf_in.iloc[-1].high
    # SET THE CURRENT LOW AND HIGH
    market_structure_dict["current_low"] = current_low
    market_structure_dict["current_high"] = current_high

    # IF THE CURRENT TREND IS BEARISH AND THE NEW TREND IS BULLISH
    if market_structure_dict["trend"] == "bearish":
        # IF THE CURRENT LOW IS LESS THAN THE PREVIOUS MINIMA
        if current_low < prev_0_minima:
            # SET MINIMA STATUS TO BEARISH BOS
            market_structure_dict["low_status"] = "bearish_BOS"
        # IF THE CURRENT HIGH IS GREATER THAN THE PREVIOUS MAXIMA
        if current_high > prev_0_maxima:
            # SET MAXIMA STATUS TO BULLISH CHOCH
            market_structure_dict["high_status"] = "bullish_CHOCH"
    # IF THE CURRENT TREND IS BULLISH AND THE NEW TREND IS BEARISH
    if market_structure_dict["trend"] == "bullish":
        # IF THE CURRENT HIGH IS GREATER THAN THE PREVIOUS MAXIMA
        if current_high > prev_0_maxima:
            # SET MAXIMA STATUS TO BULLISH BOS
            market_structure_dict["high_status"] = "bullish_BOS"
        # IF THE CURRENT LOW IS LESS THAN THE PREVIOUS MINIMA
        if current_low < prev_0_minima:
            # SET MINIMA STATUS TO BEARISH CHOCH
            market_structure_dict["low_status"] = "bearish_CHOCH"
    
    # RETURN MARKET STRUCTURE DICTIONARY
    return market_structure_dict

# FUNCTION: ADD STOCHASTIC OSCILLATOR (SO) TO OHLCV DATAFRAME
def add_SO_cols(ohlcv_pdf_in, k_window=config.STOCH_K_WINDOW, d_window=config.STOCH_D_WINDOW):
    """
    Add Stochastic Oscillator (%K and %D) to an OHLCV DataFrame.
    
    Parameters
    ----------
    ohlcv_pdf_in : pd.DataFrame
        DataFrame with OHLCV data.
    k_window : int, optional
        Lookback period for %K (default=config.STOCH_K_WINDOW, 14).
    d_window : int, optional
        Smoothing period for %D (default=config.STOCH_D_WINDOW, 3).
        
    Returns
    -------
    ohlcv_pdf_in : pd.DataFrame
        Original DataFrame with added columns 'stoch_k' and 'stoch_d'.
    """
    # ROLLING HIGHEST HIGH AND LOWEST LOW
    low_min = ohlcv_pdf_in["low"].rolling(window=k_window, min_periods=1).min()
    high_max = ohlcv_pdf_in["high"].rolling(window=k_window, min_periods=1).max()
    # STOCHASTIC OSCILLATOR %K LINE
    ohlcv_pdf_in["stoch_k"] = 100 * ((ohlcv_pdf_in["close"] - low_min) / (high_max - low_min))
    # STOCHASTIC OSCILLATOR %D LINE (SMA of %K)
    ohlcv_pdf_in["stoch_d"] = ohlcv_pdf_in["stoch_k"].rolling(window=d_window, min_periods=1).mean()
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: ADD MACD COLUMNS
def add_MACD_cols(ohlcv_pdf_in, fast_span_in=config.MACD_FAST_SPAN, slow_span_in=config.MACD_SLOW_SPAN, signal_span_in=config.MACD_SIGNAL_SPAN):
    """
    Adds Moving Average Convergence Divergence (MACD) indicator columns to a price dataframe.
    
    The MACD is calculated using:
    - 12-period EMA minus 26-period EMA for the MACD line
    - 9-period EMA of MACD for the signal line
    - MACD minus signal line for the histogram
    
    Args:
        ohlcv_pdf_in (pd.DataFrame): Input dataframe containing OHLCV price data
        fast_span_in (int): Fast EMA span (default config.MACD_FAST_SPAN, 12)
        slow_span_in (int): Slow EMA span (default config.MACD_SLOW_SPAN, 26)
        signal_span_in (int): Signal EMA span (default config.MACD_SIGNAL_SPAN, 9)
        
    Returns:
        pd.DataFrame: Original dataframe with added MACD columns:
            - 'macd': The MACD line
            - 'signal': The signal line 
            - 'histogram': The MACD histogram
    """
    # CALCULATE MACD
    ohlcv_pdf_in["macd"] = ohlcv_pdf_in["close"].ewm(span=fast_span_in, adjust=False).mean() - ohlcv_pdf_in["close"].ewm(span=slow_span_in, adjust=False).mean()
    # CALCULATE SIGNAL LINE
    ohlcv_pdf_in["signal"] = ohlcv_pdf_in["macd"].ewm(span=signal_span_in, adjust=False).mean()
    # CALCULATE HISTOGRAM
    ohlcv_pdf_in["histogram"] = ohlcv_pdf_in["macd"] - ohlcv_pdf_in["signal"]
    # RETURN DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: ADD RSI COLUMN TO OHLCV DATAFRAME
def add_RSI_col(ohlcv_pdf_in, window_in=config.RSI_WINDOW):
    """
    Add RSI (Relative Strength Index) column to OHLCV dataframe
    
    Parameters:
    ohlcv_pdf_in (pd.DataFrame): Input OHLCV dataframe with 'close' column
    window_in (int): Period for RSI calculation (default: config.RSI_WINDOW, 14)
    
    Returns:
    pd.DataFrame: OHLCV dataframe with added 'rsi' column
    """
    # CALCULATE THE PRICE CHANGE
    delta = ohlcv_pdf_in['close'].diff()
    # SEPARATE GAINS AND LOSSES
    gains = delta.where(delta > 0, 0)
    losses = -delta.where(delta < 0, 0)
    # CALCULATE THE AVERAGE GAINS
    avg_gains = gains.rolling(window=window_in, min_periods=1).mean()
    # CALCULATE THE AVERAGE LOSSES
    avg_losses = losses.rolling(window=window_in, min_periods=1).mean()
    # CALCULATE THE RS (Relative Strength)
    rs = avg_gains / avg_losses
    # CALCULATE THE RSI
    rsi = 100 - (100 / (1 + rs))
    # ADD THE RSI COLUMN TO THE DATAFRAME
    ohlcv_pdf_in["rsi"] = rsi
    # RETURN THE DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: CREATE BOLINGER BANDS
def add_BB_cols(ohlcv_pdf_in, window_in=config.BB_WINDOW, std_multiplier_in=config.BB_STD_MULTIPLIER):
    """
    Adds Bollinger Bands technical indicators to a pandas DataFrame containing OHLCV data.
    
    Bollinger Bands consist of:
    - A middle band (20-day simple moving average)
    - An upper band (2 standard deviations above middle band)
    - A lower band (2 standard deviations below middle band)
    
    The function also calculates:
    - Band width: Distance between upper and lower bands
    - %B: Position of price relative to the bands (0-1 scale)
    
    Args:
        ohlcv_pdf_in (pd.DataFrame): DataFrame with OHLCV data including 'close' column
        window_in (int, optional): Look-back period for calculations. Defaults to config.BB_WINDOW (20).
        std_multiplier_in (float, optional): Band width in standard deviations. Defaults to config.BB_STD_MULTIPLIER (2).
        
    Returns:
        pd.DataFrame: Original DataFrame with added Bollinger Bands columns:
            - bb_mid: Middle band
            - bb_top: Upper band 
            - bb_bot: Lower band
            - bb_width: Band width
            - bb_pct_b: %B indicator
    """
    # CALCULATE ROLLING MEAN (middle band)
    ohlcv_pdf_in["bb_mid"] = ohlcv_pdf_in["close"].rolling(window=window_in).mean()
    # CALCULATE ROLLING STANDARD DEVIATION
    rolling_std = ohlcv_pdf_in["close"].rolling(window=window_in).std()
    # CALCULATE UPPER AND LOWER BANDS (TYPICALLY 2 STANDARD DEVIATIONS)
    ohlcv_pdf_in["bb_top"] = ohlcv_pdf_in["bb_mid"] + (std_multiplier_in * rolling_std)
    ohlcv_pdf_in["bb_bot"] = ohlcv_pdf_in["bb_mid"] - (std_multiplier_in * rolling_std)
    # CALCULATE BAND WIDTH (DISTANCE BETWEEN UPPER AND LOWER BANDS)
    ohlcv_pdf_in["bb_width"] = ohlcv_pdf_in["bb_top"] - ohlcv_pdf_in["bb_bot"]
    # CALCULATE %B (POSITION OF PRICE WITHIN THE BANDS)
    ohlcv_pdf_in["bb_pct_b"] = (ohlcv_pdf_in["close"] - ohlcv_pdf_in["bb_bot"]) / (ohlcv_pdf_in["bb_top"] - ohlcv_pdf_in["bb_bot"])
    # CREATE BOLINGER BANDS
    return ohlcv_pdf_in

# FUNCTION: ADD DONCHIAN CHANNELS TO OHLCV DATAFRAME
def add_DC_cols(ohlcv_pdf_in, window_in=config.DC_WINDOW):
    """
    Add Donchian Channel columns to an OHLCV DataFrame.
    
    The Donchian Channel consists of three lines:
    - Upper band (dc_top): The highest high over the lookback period
    - Lower band (dc_bot): The lowest low over the lookback period  
    - Middle line (dc_mid): The average of upper and lower bands
    
    Args:
        ohlcv_pdf_in (pd.DataFrame): DataFrame containing OHLCV data with 'high' and 'low' columns
        window_in (int): Lookback period for calculating the channels (default: config.DC_WINDOW, 20)
        
    Returns:
        pd.DataFrame: Original DataFrame with added Donchian Channel columns ('dc_top', 'dc_bot', 'dc_mid')
    """
    # ADD DONCHIAN CHANNELS TO OHLCV DATAFRAME
    ohlcv_pdf_in["dc_top"] = ohlcv_pdf_in["high"].rolling(window=window_in).max()
    ohlcv_pdf_in["dc_bot"] = ohlcv_pdf_in["low"].rolling(window=window_in).min()
    # ADD THE AVERAGE OF THE DONCHIAN CHANNELS
    ohlcv_pdf_in["dc_mid"] = (ohlcv_pdf_in["dc_top"] + ohlcv_pdf_in["dc_bot"]) / 2
    # RETURN OHLCV DATAFRAME
    return ohlcv_pdf_in
    
