# IMPORT GENERAL PACKAGES
import pandas as pd
import numpy as np
# IMPORT PLOTLY
import plotly.graph_objects as go
# IMPORT PLOT UTILITY FUNCTIONS
from so.features.plot_ohlcv_utils import fig_add_ohlcv
# IMPORT EXPERIMENT CONFIGURATION (indicator defaults read from here so every step uses the same constants)
from so import config

# FUNCTION: DETECT SUPPORT LEVELS
def detect_support_levels(ohlcv_pdf_in):
    """
    Detects support levels in price data by analyzing local minima.

    This function identifies support zones by looking for clusters of price minima within
    a certain ATR-based range. A support level is formed when multiple minima occur in close
    proximity without the price breaking below the zone.

    Parameters:
    -----------
    ohlcv_pdf_in : pandas.DataFrame
        DataFrame containing OHLCV price data with the following required columns:
        - timestamp: Datetime index
        - minima: Float, local minimum prices (NaN where not a minima)
        - atr: Float, Average True Range values
        - high: Float, high prices

    Returns:
    --------
    dict
        Dictionary containing support level information with structure:
        {
            "active": list of active support level IDs,
            "inactive": list of broken support level IDs,
            "support_levels": {
                level_id: {
                    "minima_ts": timestamp of most recent minima,
                    "start_ts": timestamp where level begins,
                    "end_ts": timestamp where level ends (or current time if active),
                    "p_bot": bottom price of support zone,
                    "p_mid": middle price of support zone,
                    "p_top": top price of support zone,
                    "contact_minima_ts_list": list of timestamps where price touched level,
                    "contact_count": number of times price touched level
                }
            }
        }
    """
    # PRE-DEFINE SUPPORT LEVELS DICTIONARY
    support_levels_info_dict = {"active": [],
                                "inactive": [],
                                "support_levels": {}}
    # COLLECT ALL MINIMAS (AND REVERSE THE DATAFRAME)
    minimas_pdf = ohlcv_pdf_in[ohlcv_pdf_in.minima.notna()][::-1]
    # IF THERE ARE NO MINIMAS
    if minimas_pdf.empty:
        # RETURN EMPTY DICTIONARY
        return support_levels_info_dict
    # COLLECT THE CURRENT TIMESTAMP AND ATR
    current_ts = ohlcv_pdf_in.timestamp.iloc[-1]
    # DEFINE ATR FACTOR
    atr_factor = 0.5
    # DEFINE SUPPORT COUNT
    support_count = 0
    # CREATE A DICTIONARY OF MINIMA TIMESTAMP, PRICE, AND ATR
    minima_ts_p_atr_dict = {timestamp: {"p": minima, "atr": atr} for timestamp, minima, atr in zip(minimas_pdf.timestamp, minimas_pdf.minima, minimas_pdf.atr)}
    # COLLECT A LIST OF MINIMA TIMESTAMP
    minima_ts_list = list(minima_ts_p_atr_dict.keys())
    # ITERATE OVER EACH MINIMA
    for current_minima_ts in minima_ts_list:
        # COLLECT THE CURRENT MINIMA PRICE
        current_minima_p_atr_dict = minima_ts_p_atr_dict[current_minima_ts]
        # COLLECT THE MINIMA PRICE AND ATR
        current_minima_p = current_minima_p_atr_dict["p"]
        current_minima_atr = current_minima_p_atr_dict["atr"]
        # CALCULATE THE BOTTOM AND TOP BUFFER
        minima_atr_bot = current_minima_p - (current_minima_atr * atr_factor)
        minima_atr_top = current_minima_p + (current_minima_atr * atr_factor)
        # FILTER ALL MINIMAS BEFORE CURRENT MINIMA WITHIN THE CURRENT ATR BUFFER (SUPPORT ZONE CANDIDATES)
        area_minimas_pdf = minimas_pdf[(minimas_pdf.timestamp < current_minima_ts) &
                                        (minimas_pdf.minima.between(minima_atr_bot, minima_atr_top))]
        # DEFINE THE SUPPORT START AND END TIMESTAMPS
        support_start_ts, support_end_ts = pd.NaT, current_ts
        # LIST TO HOLD CONTACT MINIMA TIMESTAMPS
        contact_minima_ts_list = []
        # DEFINE ACTIVE BOOLEAN
        active_sup_level = True
        # IF THERE ARE MORE THAN ONE MINIMA WITHIN THE CURRENT ATR BUFFER (EXCLUDE THE FIRST ONE)
        if len(area_minimas_pdf) > 1:
            # COLLECT THE AREA MINIMAS TIMESTAMP LIST (EXCLUDING THE LAST ONE, IN REVERSE ORDER)
            area_minimas_ts_list = area_minimas_pdf.timestamp[::-1]
            # ITERATE OVER THE AREA MINIMAS TIMESTAMP LIST
            for minima_ts in area_minimas_ts_list:
                # FILTER ALL CANDLESTICKS THAT INVALIDATE THE SUPPORT ZONE UP TO THE CURRENT MINIMA TS
                invalid_support_pdf = ohlcv_pdf_in[(ohlcv_pdf_in.high < minima_atr_bot) &
                                                    (ohlcv_pdf_in.timestamp > minima_ts) &
                                                    (ohlcv_pdf_in.timestamp < current_minima_ts)]
                # IF NO CANDLES BREAK THE SUPPORT ZONE (VALID SUPPORT)
                if invalid_support_pdf.empty:
                    # SET THE SUPPORT START TIMESTAMP TO THE MINIMA TIMESTAMP
                    support_start_ts = minima_ts
                    # COLLECT THE CANDLESTICKS THAT BREAK THE SUPPORT ZONE AFTER THE CURRENT MINIMA TS
                    support_end_pdf = ohlcv_pdf_in[(ohlcv_pdf_in.timestamp > current_minima_ts) &
                                                        (ohlcv_pdf_in.high < minima_atr_bot)]
                    # IF THE SUPPORT END DATAFRAME IS NOT EMPTY
                    if not support_end_pdf.empty:
                        # SET THE SUPPORT END TIMESTAMP TO THE LAST VALID SUPPORT END TIMESTAMP
                        support_end_ts = support_end_pdf.timestamp.iloc[0]
                        # SET THE ACTIVE BOOLEAN TO FALSE
                        active_sup_level = False
                    # FILTER ALL THE SUPPORT AREA MINIMAS (IDENTIFY CONTACT MINIMAS)
                    support_area_minimas_pdf = area_minimas_pdf[area_minimas_pdf.timestamp >= support_start_ts]
                    # COLLECT THE TIMESTAMP OF THE SUPPORT AREA MINIMAS
                    support_area_minima_ts_list = support_area_minimas_pdf.timestamp.tolist()
                    # ADD THE SUPPORT AREA MINIMAS + CURRENT MINIMA TO THE CONTACT MINIMA TIMESTAMP LIST
                    contact_minima_ts_list.extend(support_area_minima_ts_list + [current_minima_ts])
                    # REMOVE THE SUPPORT AREA MINIMAS FROM THE MINIMA TIMESTAMP LIST (CONSUMED ALREADY)
                    [minima_ts_list.remove(minima_ts) for minima_ts in support_area_minima_ts_list if minima_ts in minima_ts_list]
                    # BREAK THE LOOP (SUPPORT ZONE IS ALREADY FOUND)
                    break
        # IF THE CONTACT LIST CONTAINS MORE THAN 1 MINIMA
        if len(contact_minima_ts_list) > 1:
            # INCREMENT THE SUPPORT COUNT BY 1
            support_count += 1
            # IF THE SUPPORT LEVEL IS ACTIVE
            if active_sup_level == True:
                # ADD THE SUPPORT LEVEL TO THE ACTIVE LIST
                support_levels_info_dict["active"].append(support_count)
            # IF THE SUPPORT LEVEL IS INACTIVE
            else:
                # ADD THE SUPPORT LEVEL TO THE INACTIVE LIST
                support_levels_info_dict["inactive"].append(support_count)
            # ADD THE SUPPORT LEVEL TO THE SUPPORT LEVELS DICTIONARY
            support_levels_info_dict["support_levels"][support_count] = {
                "minima_ts": current_minima_ts,
                "start_ts": support_start_ts,
                "end_ts": support_end_ts,
                "p_bot": minima_atr_bot,
                "p_mid": current_minima_p,
                "p_top": minima_atr_top,
                "contact_minima_ts_list": contact_minima_ts_list,
                "contact_count": len(contact_minima_ts_list),
            }
    # SORT THE ACTIVE ID LIST FROM SUPPORT LEVELS BY PRICE MIDDLE (IN REVERSE ORDER)
    support_levels_info_dict["active"] = sorted(support_levels_info_dict["active"], key=lambda x: support_levels_info_dict["support_levels"][x]["p_bot"], reverse=True)
    # SORT THE INACTIVE ID LIST FROM SUPPORT LEVELS BY PRICE BOTTOM (IN REVERSE ORDER)
    support_levels_info_dict["inactive"] = sorted(support_levels_info_dict["inactive"], key=lambda x: support_levels_info_dict["support_levels"][x]["p_bot"], reverse=True)
    # RETURN THE SUPPORT LEVELS DICTIONARY
    return support_levels_info_dict

# FUNCTION: DETECT RESISTANCE LEVELS
def detect_resistance_levels(ohlcv_pdf_in):
    """
    Detects resistance levels in price data by analyzing local maxima.

    This function identifies resistance zones by looking for clusters of price maxima within
    a certain ATR-based range. A resistance level is formed when multiple maxima occur in close
    proximity without the price breaking above the zone.

    Parameters:
    -----------
    ohlcv_pdf_in : pandas.DataFrame
        DataFrame containing OHLCV price data with the following required columns:
        - timestamp: Datetime index
        - maxima: Float, local maximum prices (NaN where not a maxima)
        - atr: Float, Average True Range values
        - low: Float, low prices

    Returns:
    --------
    dict
        Dictionary containing resistance level information with structure:
        {
            "active": list of active resistance level IDs,
            "inactive": list of broken resistance level IDs,
            "resistance_levels": {
                level_id: {
                    "maxima_ts": timestamp of most recent maxima,
                    "start_ts": timestamp where level begins,
                    "end_ts": timestamp where level ends (or current time if active),
                    "p_bot": bottom price of resistance zone,
                    "p_mid": middle price of resistance zone,
                    "p_top": top price of resistance zone,
                    "contact_maxima_ts_list": list of timestamps where price touched level,
                    "contact_count": number of times price touched level
                }
            }
        }
    """
    # PRE-DEFINE RESISTANCE LEVELS DICTIONARY
    resistance_levels_info_dict = {"active": [],
                                    "inactive": [],
                                    "resistance_levels": {}}
    # COLLECT ALL MAXIMAS (AND REVERSE THE DATAFRAME)
    maximas_pdf = ohlcv_pdf_in[ohlcv_pdf_in.maxima.notna()][::-1]
    # IF THERE ARE NO MAXIMAS
    if maximas_pdf.empty:
        # RETURN EMPTY DICTIONARY
        return resistance_levels_info_dict
    # COLLECT THE CURRENT TIMESTAMP AND ATR
    current_ts = ohlcv_pdf_in.timestamp.iloc[-1]
    current_atr = ohlcv_pdf_in.atr.iloc[-1]
    # DEFINE ATR FACTOR
    atr_factor = 0.5
    # DEFINE RESISTANCE COUNT
    resistance_count = 0
    # CREATE A DICTIONARY OF MAXIMA TIMESTAMP, PRICE, AND ATR
    maxima_ts_p_atr_dict = {timestamp: {"p": maxima, "atr": atr} for timestamp, maxima, atr in zip(maximas_pdf.timestamp, maximas_pdf.maxima, maximas_pdf.atr)}
    # COLLECT A LIST OF MAXIMA TIMESTAMP
    maxima_ts_list = list(maxima_ts_p_atr_dict.keys())
    # ITERATE OVER EACH MAXIMA
    for current_maxima_ts in maxima_ts_list:
        # COLLECT THE CURRENT MAXIMA PRICE AND ATR DICTIONARY
        current_maxima_p_atr_dict = maxima_ts_p_atr_dict[current_maxima_ts]
        # COLLECT THE CURRENT MAXIMA PRICE
        current_maxima_p = current_maxima_p_atr_dict["p"]
        current_maxima_atr = current_maxima_p_atr_dict["atr"]
        # CALCULATE THE BOTTOM AND TOP BUFFER
        maxima_atr_bot = current_maxima_p - (current_maxima_atr * atr_factor)
        maxima_atr_top = current_maxima_p + (current_maxima_atr * atr_factor)
        # FILTER ALL MAXIMAS BEFORE CURRENT MAXIMA WITHIN THE CURRENT ATR BUFFER (RESISTANCE ZONE CANDIDATES)
        area_maximas_pdf = maximas_pdf[(maximas_pdf.timestamp < current_maxima_ts) &
                                        (maximas_pdf.maxima.between(maxima_atr_bot, maxima_atr_top))]
        # DEFINE THE RESISTANCE START AND END TIMESTAMPS
        resistance_start_ts, resistance_end_ts = pd.NaT, current_ts
        # LIST TO HOLD CONTACT MAXIMA TIMESTAMPS
        contact_maxima_ts_list = []
        # DEFINE THE ACTIVE BOOLEAN
        active_res_level = True
        # IF THERE ARE MORE THAN ONE MAXIMA WITHIN THE CURRENT ATR BUFFER (EXCLUDE THE FIRST ONE)
        if len(area_maximas_pdf) > 1:
            # COLLECT THE AREA MAXIMAS TIMESTAMP LIST (EXCLUDING THE LAST ONE, IN REVERSE ORDER)
            area_maximas_ts_list = area_maximas_pdf.timestamp[::-1]
            # ITERATE OVER THE AREA MAXIMAS TIMESTAMP LIST
            for maxima_ts in area_maximas_ts_list:
                # FILTER ALL CANDLESTICKS THAT INVALIDATE THE RESISTANCE ZONE UP TO THE CURRENT MAXIMA TS
                invalid_resistance_pdf = ohlcv_pdf_in[(ohlcv_pdf_in.low > maxima_atr_top) &
                                                    (ohlcv_pdf_in.timestamp > maxima_ts) &
                                                    (ohlcv_pdf_in.timestamp < current_maxima_ts)]
                # IF NO CANDLES BREAK THE RESISTANCE ZONE (VALID RESISTANCE)
                if invalid_resistance_pdf.empty:
                    # SET THE RESISTANCE START TIMESTAMP TO THE MAXIMA TIMESTAMP
                    resistance_start_ts = maxima_ts
                    # COLLECT THE CANDLESTICKS THAT BREAK THE RESISTANCE ZONE AFTER THE CURRENT MAXIMA TS
                    resistance_end_pdf = ohlcv_pdf_in[(ohlcv_pdf_in.timestamp > current_maxima_ts) &
                                                        (ohlcv_pdf_in.low > maxima_atr_top)]
                    # IF THE RESISTANCE END DATAFRAME IS NOT EMPTY
                    if not resistance_end_pdf.empty:
                        # SET THE RESISTANCE END TIMESTAMP TO THE LAST VALID RESISTANCE END TIMESTAMP
                        resistance_end_ts = resistance_end_pdf.timestamp.iloc[0]
                        # SET THE ACTIVE BOOLEAN TO FALSE
                        active_res_level = False
                    # FILTER ALL THE RESISTANCE AREA MAXIMAS (IDENTIFY CONTACT MAXIMAS)
                    resistance_area_maximas_pdf = area_maximas_pdf[area_maximas_pdf.timestamp >= resistance_start_ts]
                    # COLLECT THE TIMESTAMP OF THE RESISTANCE AREA MAXIMAS
                    resistance_area_maxima_ts_list = resistance_area_maximas_pdf.timestamp.tolist()
                    # ADD THE RESISTANCE AREA MAXIMAS + CURRENT MAXIMA TO THE CONTACT MAXIMA TIMESTAMP LIST
                    contact_maxima_ts_list.extend(resistance_area_maxima_ts_list + [current_maxima_ts])
                    # REMOVE THE RESISTANCE AREA MAXIMAS FROM THE MAXIMA TIMESTAMP LIST (CONSUMED ALREADY)
                    [maxima_ts_list.remove(maxima_ts) for maxima_ts in resistance_area_maxima_ts_list if maxima_ts in maxima_ts_list]
                    # BREAK THE LOOP (RESISTANCE ZONE IS ALREADY FOUND)
                    break
        # IF THE CONTACT LIST CONTAINS MORE THAN 1 MAXIMA
        if len(contact_maxima_ts_list) > 1:
            # INCREMENT THE RESISTANCE COUNT BY 1
            resistance_count += 1
            # IF THE RESISTANCE LEVEL IS ACTIVE
            if active_res_level == True:
                # ADD THE RESISTANCE LEVEL TO THE ACTIVE LIST
                resistance_levels_info_dict["active"].append(resistance_count)
            # IF THE RESISTANCE LEVEL IS INACTIVE
            else:
                # ADD THE RESISTANCE LEVEL TO THE INACTIVE LIST
                resistance_levels_info_dict["inactive"].append(resistance_count)
            # ADD THE RESISTANCE LEVEL TO THE RESISTANCE LEVELS DICTIONARY
            resistance_levels_info_dict["resistance_levels"][resistance_count] = {
                "maxima_ts": current_maxima_ts,
                "start_ts": resistance_start_ts,
                "end_ts": resistance_end_ts,
                "p_bot": maxima_atr_bot,
                "p_mid": current_maxima_p,
                "p_top": maxima_atr_top,
                "contact_maxima_ts_list": contact_maxima_ts_list,
                "contact_count": len(contact_maxima_ts_list),
            }
    # SORT THE ACTIVE ID LIST FROM RESISTANCE LEVELS BY PRICE MIDDLE (IN REVERSE ORDER)
    resistance_levels_info_dict["active"] = sorted(resistance_levels_info_dict["active"], key=lambda x: resistance_levels_info_dict["resistance_levels"][x]["p_bot"])
    # SORT THE INACTIVE ID LIST FROM RESISTANCE LEVELS BY PRICE BOTTOM (IN REVERSE ORDER)
    resistance_levels_info_dict["inactive"] = sorted(resistance_levels_info_dict["inactive"], key=lambda x: resistance_levels_info_dict["resistance_levels"][x]["p_bot"])
    # RETURN THE RESISTANCE LEVELS DICTIONARY
    return resistance_levels_info_dict

import plotly.express as px
# DEFINE A COLOR LIST
color_list = px.colors.qualitative.Alphabet

# FUNCTION: CALCULATE PERIOD OF DATAFRAME
def get_ohlcv_period_seconds(ohlcv_pdf_in):
    """
    Calculate the time period between consecutive rows in an OHLCV dataframe.
    
    This function determines the time interval between adjacent timestamps in the input
    dataframe by calculating the difference between the first two timestamps. This is
    useful for determining the timeframe of price data (e.g. 1-minute bars, 5-minute bars).
    
    Parameters:
    -----------
    ohlcv_pdf_in : pandas.DataFrame
        OHLCV dataframe with a timestamp column
        
    Returns:
    --------
    float or np.nan
        The time period in seconds between consecutive rows
        Returns NaN if dataframe has less than 2 rows
    """
    # IF THE DATAFRAME HAS LESS THAN 2 ROWS
    if len(ohlcv_pdf_in) < 2:
        # RETURN NULL
        return np.nan
    # RETURN THE PERIOD OF THE DATAFRAME
    return (ohlcv_pdf_in.timestamp.iloc[1] - ohlcv_pdf_in.timestamp.iloc[0]).total_seconds()

# FUNCTION: CONVERT (TIMESTAMP 1, PRICE 1) A (TIMESTAMP 2, PRICE 2) INTO TO A FUNCTION THAT RETURNS A PRICE GIVEN A TIMESTAMP
def get_ts_to_price_func(timestamp1_in, price1_in, timestamp2_in, price2_in):
    """
    Convert two points (timestamp1, price1) and (timestamp2, price2) into a linear function 
    that returns a price given any timestamp.
    
    This function creates a linear interpolation/extrapolation function based on two known points.
    It's commonly used for trend line analysis where you have two contact points and want to 
    calculate the trend line price at any given timestamp.
    
    Parameters:
    -----------
    timestamp1 : pandas.Timestamp
        First timestamp point
    price1 : float
        Price at the first timestamp
    timestamp2 : pandas.Timestamp
        Second timestamp point
    price2 : float
        Price at the second timestamp
        
    Returns:
    --------
    function
        A lambda function that takes a timestamp and returns the interpolated/extrapolated price
        
    Example:
    --------
    func = get_price_function(ts1, 100, ts2, 200)
    price_at_ts3 = func(ts3)  # Returns interpolated price at ts3
    """
    # CALCULATE THE TIME DIFFERENCE BETWEEN THE TWO TIMESTAMPS (IN SECONDS)
    seconds_duration = timestamp2_in.timestamp() - timestamp1_in.timestamp()
    # CALCULATE THE SLOPE (PRICE CHANGE PER SECOND)
    # slope = rise / run = (price2 - price1) / (time2 - time1)
    slope = (price2_in - price1_in) / seconds_duration
    # CALCULATE THE Y-INTERCEPT USING POINT-SLOPE FORM
    # Using timestamp1 as reference point: y = mx + b, so b = y - mx
    # Since we're using timestamp1 as origin (x=0), y_intercept = price1
    y_intercept = price1_in
    # RETURN A LAMBDA FUNCTION THAT CALCULATES PRICE FOR ANY GIVEN TIMESTAMP
    # Formula: price = slope * (input_timestamp - reference_timestamp) + reference_price
    return lambda x: slope * (x.timestamp() - timestamp1_in.timestamp()) + y_intercept

# FUNCTION: GET THE SLOPE OF A TREND LINE
def get_price_slope(start_p_in, end_p_in, period_in):
    # CALCULATE THE SLOPE
    slope = (end_p_in - start_p_in) / period_in
    # RETURN THE SLOPE
    return slope

# FUNCTION: IDENTIFY SUPPORT TREND LINES
def get_support_TL_info_dict(ohlcv_pdf_in, alert_in=False):
    """
    Identify the best support trend line by connecting the latest minima 
    with previous minimas and validating against intermediate points.
    """
    # PRE DEFINE OUTPUT DICTIONARY
    support_TL_info_dict = {"support_exists": False,
                                "ts_p_dict": {},
                                "contact_minimas_tup_list": {},
                                "atr_buffer": np.nan,
                                "period_count": np.nan,
                                "slope": np.nan}
    # IF THE DATAFRAME CONTAINS IS EMPTY
    if len(ohlcv_pdf_in) < 2:
        # RETURN EMPTY DICTIONARY
        return support_TL_info_dict
    # COLLECT ALL THE MINIMAS
    minimas_pdf = ohlcv_pdf_in[ohlcv_pdf_in.minima.notna()]
    # IF THERE IS NO DATA
    if len(minimas_pdf) < 2:
        # RETURN EMPTY DICT
        return support_TL_info_dict
    # SET THE SUPPORT EXISTS TO TRUE
    support_TL_info_dict["support_exists"] = True
    # COLLECT THE CURRENT TIMESTAMP
    current_ts = ohlcv_pdf_in.iloc[-1].timestamp
    # CALCULATE THE PERIOD IN SECONDS
    period_seconds_duration = get_ohlcv_period_seconds(ohlcv_pdf_in)
    # GET CURRENT (LATEST) MINIMA VALUES
    current_minima = minimas_pdf.iloc[-1]
    current_minima_ts = current_minima.timestamp
    current_minima_p = current_minima.minima
    current_minima_atr = current_minima.atr
    # DEFINE THE ATR FACTOR
    atr_factor = 0.2
    # CALCULATE THE ATR BUFFER
    atr_buffer = atr_factor * current_minima_atr
    # SET THE ATR FACTOR
    support_TL_info_dict["atr_buffer"] = atr_buffer
    # EXCLUDE THE CURRENT MINIMA AND REVERSE THE MINIMAS DATAFRAME
    prev_minimas_pdf = minimas_pdf[:-1][::-1]
    # CREATE VISUALIZATION
    fig = go.Figure()
    # ADD CANDLESTICKS
    fig_add_ohlcv(fig, ohlcv_pdf_in, opacity_in=0.25)
    # PLOT CURRENT MINIMA
    fig.add_trace(go.Scatter(
        x=[current_minima_ts],
        y=[current_minima_p],
        mode="markers",
        name="Latest Minima",
        marker=dict(symbol="circle", size=10, color="green")
    ))
    # PLOT PREVIOUS MINIMAS
    fig.add_trace(go.Scatter(
        x=prev_minimas_pdf["timestamp"],
        y=prev_minimas_pdf["minima"],
        mode="markers+lines",
        name="Prev Minimas",
        marker=dict(symbol="circle", size=10, color="blue")
    ))
    # UPDATE PLOT LAYOUT
    fig.update_layout(
        title="Best Fit Support Trend Line",
        xaxis_title="Timestamp",
        yaxis_title="Price",
        template="plotly_dark",
        width=1000,
        height=500,
        xaxis = dict(range=[ohlcv_pdf_in.timestamp.iloc[0], ohlcv_pdf_in.timestamp.iloc[-1]]),
        yaxis = dict(range=[ohlcv_pdf_in.low.min() * 0.999, ohlcv_pdf_in.high.max() * 1.001]),
        xaxis_rangeslider_visible=False,
    )
    # DEFINE DICTIONARY TO HOLD SUPPORT LINES (ts: price)
    sup_lines_dict = {}
    # DICTIONARY TO HOLD CONTACT POINTS (ts: price)
    sup_contact_dict = {}
    # DEFINE FINAL SUPPORT LINE INDEX (DEFAULT TO 0)
    final_sup_line_idx = 0
    # ITERATE OVER PREVIOUS MINIMAS (CREATE ANCHOR POINT FROM CURRENT MINIMA TO PREVIOUS MINIMA)
    for idx in range(len(prev_minimas_pdf)):
        # COLLECT THE PREVIOUS MINIMA ROW
        prev_minima_row = prev_minimas_pdf.iloc[idx]
        # GET PREVIOUS MINIMA, PRICE, AND TIMESTAMP
        prev_minima_p = prev_minima_row.minima
        prev_minima_ts = prev_minima_row.timestamp
        # GENERATE SUPPORT LINE TIMESTAMPS
        ts_range = pd.date_range(start=prev_minima_ts, end=current_ts, freq=f"{int(period_seconds_duration)}s")
        # CALL FUNCTION TO GET TIMESTAMP TO PRICE FUNCTION
        ts_to_price_func = get_ts_to_price_func(prev_minima_ts, prev_minima_p, current_minima_ts, current_minima_p)
        # GENERATE SUPPORT LINE PRICES
        line_dict = {ts: round(ts_to_price_func(ts), 6) for ts in ts_range}
        # CALCULATE THE SUPPORT LINE BOTTOM AND TOP BUFFERED PRICES
        line_bot_dict = {ts: round(line_dict[ts] - atr_buffer, 6) for ts in line_dict}
        line_top_dict = {ts: round(line_dict[ts] + atr_buffer, 6) for ts in line_dict}
        # PLOT SUPPORT LINE PRICES
        fig.add_trace(go.Scatter(
            x=list(line_dict.keys()),
            y=list(line_dict.values()),
            mode="lines",
            line=dict(dash="dash", color=color_list[idx%len(color_list)], width=1),
            legendgroup=f"Support Line {idx}",
            showlegend=True,
            text=f"Support Line {idx}",
            name=f"Support Line {idx}")
        )
        # PLOT SUPPORT LINE PRICES
        fig.add_trace(go.Scatter(
            x=list(line_bot_dict.keys()),
            y=list(line_bot_dict.values()),
            mode="lines",
            line=dict(color=color_list[idx%len(color_list)], width=1),
            legendgroup=f"Support Line {idx}",
            showlegend=False,
            text=f"Support Line {idx}",
            name=f"Support Line {idx}")
        )
        # PLOT SUPPORT LINE PRICES
        fig.add_trace(go.Scatter(
            x=list(line_top_dict.keys()),
            y=list(line_top_dict.values()),
            mode="lines",
            line=dict(color=color_list[idx%len(color_list)], width=1),
            legendgroup=f"Support Line {idx}",
            showlegend=False,
            text=f"Support Line {idx}",
            name=f"Support Line {idx}")
        )
        # ADD THE LINE DICTIONARY TO THE SUPPORT LINES DICTIONARY
        sup_lines_dict[idx] = line_dict
        # VALIDATE SUPPORT LINE AGAINST INTERMEDIATE MINIMAS
        interm_minimas_pdf = prev_minimas_pdf[prev_minimas_pdf.timestamp > prev_minima_ts]
        # CREATE A DICTIONARY TO HOLD CONTACT POINTS
        interm_contact_list = []
        # SUM TO HOLD THE TOTAL DELTA PCT SUM (threshold)
        price_delta_pct_sum = 0
        # ITERATE OVER THE INTERMEDIATE MINIMAS (BETWEEN THE PREVIOUS MINIMA AND THE CURRENT MINIMA)
        for interm_minima_ts, interm_minima_p in zip(interm_minimas_pdf.timestamp, interm_minimas_pdf.minima):
            # GET SUPPORT LINE PRICE, BOTTOM, AND TOP AT THIS TIMESTAMP
            support_line_price = line_dict[interm_minima_ts]
            support_line_bot_price = line_bot_dict[interm_minima_ts]
            support_line_top_price = line_top_dict[interm_minima_ts]
            # IF THE INTERMEDIATE MINIMA IS BETWEEN THE SUPPORT LINE BOTTOM AND TOP PRICES
            if support_line_bot_price <= interm_minima_p <= support_line_top_price:
                # ADD THE INTERMEDIATE MINIMA TO THE SUPPORT CONTACT DICTIONARY
                interm_contact_list.append((interm_minima_ts, interm_minima_p))
            # CALCULATE PRICE DELTA PERCENTAGE (BETWEEN THE INTERMEDIATE MINIMA AND THE BOTTOM OF THE SUPPORT LINE)
            price_delta_pct = (interm_minima_p - support_line_bot_price) / interm_minima_p
            # IF THE PRICE DELTA PERCENTAGE IS NEGATIVE (INTERMEDIATE MINIMA BREAKS BELOW THE SUPPORT LINE)
            if price_delta_pct < 0:
                # ADD THE PRICE DELTA PCT TO THE PRICE DELTA PCT SUM
                price_delta_pct_sum += price_delta_pct
            # DISPLAY INFORMATION
            print(f"Line {idx}: Minima:\t{interm_minima_p:.2f}\tSupport:\t{support_line_price:.2f}\t(Delta:\t{price_delta_pct:.10f})\t(Delta Sum:\t{price_delta_pct_sum:.10f})") if alert_in else None
            # IF MINIMA BREAKS BELOW SUPPORT LINE (WITH TOLERANCE)
            if price_delta_pct_sum <= -0.00005:
                # BREAK THE INNER LOOP
                break
        # IF THE LOOP COMPLETED WITHOUT BREAKING
        else:
            # ADD THE LINE CONTACT DICTIONARY TO THE SUPPORT CONTACT DICTIONARY
            sup_contact_dict[idx] = interm_contact_list
            # CONTINUE THE OUTER LOOP
            continue
        # IF THE INNER LOOP BROKE, SET THE FINAL INDEX AS THE PREVIOUS INDEX (PREVIOUS VALID SUPPORT LINE)
        final_sup_line_idx = idx - 1
        # BREAK THE OUTER LOOP
        break
    # DISPLAY INFORMATION
    print(f"Selected Support Line: {final_sup_line_idx}") if alert_in else None
    # DISPLAY THE FIGURE
    fig.show() if alert_in else None
    # DEFINE THE FINAL SUPPORT LINE DICTIONARY
    ts_p_dict = sup_lines_dict[final_sup_line_idx]
    # DEFINE THE CONTACT MINIMAS TUPLE LIST
    contact_minimas_tup_list = sup_contact_dict[final_sup_line_idx]
    # COLLECT THE SUPPORT LINE START TIMESTAMP
    support_line_start_ts = prev_minimas_pdf.timestamp.iloc[final_sup_line_idx]
    # COLLECT THE SUPPORT LINE START PRICE
    support_line_start_p = ts_p_dict[support_line_start_ts]
    # ADD THE SUPPORT LINE AND CONTACT POINTS TO THE OUTPUT DICTIONARY
    support_TL_info_dict["ts_p_dict"] = ts_p_dict
    # GET THE INDEX OF THE START TIMESTAMP
    sup_start_idx = ohlcv_pdf_in.loc[ohlcv_pdf_in.timestamp == support_line_start_ts].index[0]
    # GET THE INDEX OF THE END TIMESTAMP
    sup_end_idx = ohlcv_pdf_in.loc[ohlcv_pdf_in.timestamp == current_minima_ts].index[0]
    # CALCULATE THE NUMBER OF PERIODS (ADD 1 TO INCLUDE THE CURRENT MAXIMA)
    sup_period_count = (sup_end_idx - sup_start_idx) + 1
    # SET THE PERIOD COUNT
    support_TL_info_dict["period_count"] = sup_period_count
    # ADD THE CONTACT MINIMAS TO THE OUTPUT DICTIONARY
    support_TL_info_dict["contact_minimas_tup_list"] = [(support_line_start_ts, support_line_start_p)] + contact_minimas_tup_list + [(current_minima_ts, current_minima_p)]
    # SET THE SLOPE
    support_TL_info_dict["slope"] = get_price_slope(support_line_start_p, current_minima_p, sup_period_count)
    # COLLECT THE SUPPORT LINE, CONTACT POINTS, AND RETURN THE DICTIONARY
    return support_TL_info_dict

# FUNCTION: IDENTIFY RESISTANCE TREND LINES
def get_resistance_TL_info_dict(ohlcv_pdf_in, alert_in=False):
    """
    Identify the best resistance trend line by connecting the latest maxima 
    with previous maximas and validating against intermediate points.
    """
    # PRE DEFINE OUTPUT DICTIONARY
    resistance_TL_info_dict = {"resistance_exists":False,
                                "ts_p_dict": {},
                                "contact_maximas_tup_list": {},
                                "atr_buffer": np.nan,
                                "period_count": np.nan,
                                "slope": np.nan}
    # IF THE DATAFRAME CONTAINS IS EMPTY
    if ohlcv_pdf_in.empty:
        # RETURN EMPTY DICTIONARY
        return resistance_TL_info_dict
    # COLLECT ALL THE MAXIMAS
    maximas_pdf = ohlcv_pdf_in[ohlcv_pdf_in.maxima.notna()]
    # IF THERE IS NO DATA
    if len(maximas_pdf) < 2:
        # RETURN EMPTY DICT
        return resistance_TL_info_dict
    # SET THE RESISTANCE EXISTS TO TRUE
    resistance_TL_info_dict["resistance_exists"] = True
    # COLLECT THE CURRENT TIMESTAMP
    current_ts = ohlcv_pdf_in.iloc[-1].timestamp
    # CALCULATE THE PERIOD IN SECONDS
    period_seconds_duration = get_ohlcv_period_seconds(ohlcv_pdf_in)
    # GET CURRENT (LATEST) MAXIMA VALUES
    current_maxima = maximas_pdf.iloc[-1]
    current_maxima_p = current_maxima.maxima
    current_maxima_ts = current_maxima.timestamp
    current_maxima_atr = current_maxima.atr
    # DEFINE THE ATR FACTOR
    atr_factor = 0.2
    # CALCULATE THE ATR BUFFER
    atr_buffer = atr_factor * current_maxima_atr
    # SET THE ATR BUFFER
    resistance_TL_info_dict["atr_buffer"] = atr_buffer
    # EXCLUDE THE CURRENT MAXIMA AND REVERSE THE MAXIMAS DATAFRAME
    prev_maximas_pdf = maximas_pdf[:-1][::-1]
    # CREATE VISUALIZATION
    fig = go.Figure()
    # ADD CANDLESTICKS
    fig_add_ohlcv(fig, ohlcv_pdf_in, opacity_in=0.25)
    # PLOT CURRENT MAXIMA
    fig.add_trace(go.Scatter(
        x=[current_maxima_ts],
        y=[current_maxima_p],
        mode="markers",
        name="Latest Maxima",
        marker=dict(symbol="circle", size=10, color="red")
    ))
    # PLOT PREVIOUS MAXIMAS
    fig.add_trace(go.Scatter(
        x=prev_maximas_pdf["timestamp"],
        y=prev_maximas_pdf["maxima"],
        mode="markers+lines",
        name="Prev Maximas",
        marker=dict(symbol="circle", size=10, color="orange")
    ))
    # UPDATE PLOT LAYOUT
    fig.update_layout(
        title="Best Fit Resistance Trend Line",
        xaxis_title="Timestamp",
        yaxis_title="Price",
        template="plotly_dark",
        width=1000,
        height=500,
        xaxis = dict(range=[ohlcv_pdf_in.timestamp.iloc[0], ohlcv_pdf_in.timestamp.iloc[-1]]),
        yaxis = dict(range=[ohlcv_pdf_in.low.min() * 0.999, ohlcv_pdf_in.high.max() * 1.001]),
        xaxis_rangeslider_visible=False,
    )
    # DEFINE DICTIONARY TO HOLD RESISTANCE LINES (ts: price)
    res_lines_dict = {}
    # DICTIONARY TO HOLD CONTACT POINTS (ts: price)
    res_contact_dict = {}
    # DEFINE FINAL RESISTANCE LINE INDEX (DEFAULT TO 0)
    final_res_line_idx = 0
    # ITERATE OVER PREVIOUS MAXIMAS (CREATE ANCHOR POINT FROM CURRENT MAXIMA TO PREVIOUS MAXIMA)
    for idx in range(len(prev_maximas_pdf)):
        # COLLECT THE PREVIOUS MAXIMA ROW
        prev_maxima_row = prev_maximas_pdf.iloc[idx]
        # GET PREVIOUS MAXIMA, PRICE, AND TIMESTAMP
        prev_maxima_p = prev_maxima_row.maxima
        prev_maxima_ts = prev_maxima_row.timestamp
        # GENERATE RESISTANCE LINE TIMESTAMPS
        ts_range = pd.date_range(start=prev_maxima_ts, end=current_ts, freq=f"{int(period_seconds_duration)}s")
        # CALL FUNCTION TO GET TIMESTAMP TO PRICE FUNCTION
        ts_to_price_func = get_ts_to_price_func(prev_maxima_ts, prev_maxima_p, current_maxima_ts, current_maxima_p)
        # GENERATE RESISTANCE LINE PRICES
        line_dict = {ts: ts_to_price_func(ts) for ts in ts_range}
        # CALCULATE THE RESISTANCE LINE BOTTOM AND TOP BUFFERED PRICES
        line_bot_dict = {ts: round(line_dict[ts] - atr_buffer, 6) for ts in line_dict}
        line_top_dict = {ts: round(line_dict[ts] + atr_buffer, 6) for ts in line_dict}
        # PLOT RESISTANCE LINE PRICES
        fig.add_trace(go.Scatter(
            x=list(line_dict.keys()),
            y=list(line_dict.values()),
            mode="lines",
            line=dict(dash="dash", color=color_list[idx%len(color_list)], width=1),
            legendgroup=f"Resistance Line {idx}",
            showlegend=True,
            text=f"Resistance Line {idx}",
            name=f"Resistance Line {idx}")
        )
        # PLOT RESISTANCE LINE PRICES
        fig.add_trace(go.Scatter(
            x=list(line_bot_dict.keys()),
            y=list(line_bot_dict.values()),
            mode="lines",
            line=dict(color=color_list[idx%len(color_list)], width=1),
            legendgroup=f"Resistance Line {idx}",
            showlegend=False,
            text=f"Resistance Line {idx}",
            name=f"Resistance Line {idx}")
        )
        # PLOT RESISTANCE LINE PRICES
        fig.add_trace(go.Scatter(
            x=list(line_top_dict.keys()),
            y=list(line_top_dict.values()),
            mode="lines",
            line=dict(color=color_list[idx%len(color_list)], width=1),
            legendgroup=f"Resistance Line {idx}",
            showlegend=False,
            text=f"Resistance Line {idx}",
            name=f"Resistance Line {idx}")
        )
        # ADD THE LINE DICTIONARY TO THE RESISTANCE LINES DICTIONARY
        res_lines_dict[idx] = line_dict
        # VALIDATE RESISTANCE LINE AGAINST INTERMEDIATE MAXIMAS
        interm_maximas_pdf = prev_maximas_pdf[prev_maximas_pdf.timestamp > prev_maxima_ts]
        # CREATE A DICTIONARY TO HOLD CONTACT POINTS
        interm_contact_list = []
        # SUM TO HOLD THE TOTAL DELTA PCT SUM (threshold)
        price_delta_pct_sum = 0
        # ITERATE OVER THE INTERMEDIATE MAXIMAS (BETWEEN THE PREVIOUS MAXIMA AND THE CURRENT MAXIMA)
        for interm_maxima_ts, interm_maxima_p in zip(interm_maximas_pdf.timestamp, interm_maximas_pdf.maxima):
            # GET RESISTANCE LINE PRICE, BOTTOM, AND TOP AT THIS TIMESTAMP
            resistance_line_price = line_dict[interm_maxima_ts]
            resistance_line_bot_price = line_bot_dict[interm_maxima_ts]
            resistance_line_top_price = line_top_dict[interm_maxima_ts]
            # IF THE INTERMEDIATE MAXIMA IS BETWEEN THE RESISTANCE LINE BOTTOM AND TOP PRICES
            if resistance_line_bot_price <= interm_maxima_p <= resistance_line_top_price:
                # ADD THE INTERMEDIATE MAXIMA TO THE RESISTANCE CONTACT LIST
                interm_contact_list.append((interm_maxima_ts, interm_maxima_p))
            # CALCULATE PRICE DELTA PERCENTAGE (BETWEEN THE INTERMEDIATE MAXIMA AND THE TOP OF THE RESISTANCE LINE)
            price_delta_pct = (interm_maxima_p - resistance_line_top_price) / interm_maxima_p
            # IF THE PRICE DELTA PERCENTAGE IS POSITIVE (INTERMEDIATE MAXIMA BREAKS ABOVE THE RESISTANCE LINE)
            if price_delta_pct > 0:
                # ADD THE PRICE DELTA PCT TO THE PRICE DELTA PCT SUM
                price_delta_pct_sum += price_delta_pct
            # DISPLAY INFORMATION
            print(f"Line {idx}: Maxima:\t{interm_maxima_p:.2f}\tResistance:\t{resistance_line_price:.2f}\t(Delta:\t{price_delta_pct:.10f})\t(Delta Sum:\t{price_delta_pct_sum:.10f})") if alert_in else None
            # IF MAXIMA BREAKS ABOVE RESISTANCE LINE (WITH TOLERANCE)
            if price_delta_pct_sum >= 0.00005:
                # BREAK THE INNER LOOP
                break
        # IF THE LOOP COMPLETED WITHOUT BREAKING
        else:
            # ADD THE LINE CONTACT DICTIONARY TO THE RESISTANCE CONTACT DICTIONARY
            res_contact_dict[idx] = interm_contact_list
            # CONTINUE THE OUTER LOOP
            continue
        # IF THE INNER LOOP BROKE, SET THE FINAL INDEX AS THE PREVIOUS INDEX (PREVIOUS VALID RESISTANCE LINE)
        final_res_line_idx = idx - 1
        # BREAK THE OUTER LOOP
        break
    # DISPLAY INFORMATION
    print(f"Selected Resistance Line: {final_res_line_idx}") if alert_in else None
    # DISPLAY THE FIGURE
    fig.show() if alert_in else None
    # # DEFINE THE FINAL RESISTANCE LINE DICTIONARY
    ts_p_dict = res_lines_dict[final_res_line_idx]
    # DEFINE THE CONTACT MAXIMAS TUPLE LIST
    contact_maximas_tup_list = res_contact_dict[final_res_line_idx]
    # COLLECT THE RESISTANCE LINE START TIMESTAMP
    resistance_line_start_ts = prev_maximas_pdf.timestamp.iloc[final_res_line_idx]
    # COLLECT THE RESISTANCE LINE START PRICE
    resistance_line_start_p = ts_p_dict[resistance_line_start_ts]
    # ADD THE RESISTANCE LINE AND CONTACT POINTS TO THE OUTPUT DICTIONARY
    resistance_TL_info_dict["ts_p_dict"] = ts_p_dict
    # GET THE INDEX OF THE START TIMESTAMP
    res_start_idx = ohlcv_pdf_in.loc[ohlcv_pdf_in.timestamp == resistance_line_start_ts].index[0]
    # GET THE INDEX OF THE END TIMESTAMP
    res_end_idx = ohlcv_pdf_in.loc[ohlcv_pdf_in.timestamp == current_maxima_ts].index[0]
    # CALCULATE THE NUMBER OF PERIODS (ADD 1 TO INCLUDE THE CURRENT MAXIMA)
    res_period_count = (res_end_idx - res_start_idx) + 1
    # SET THE PERIOD COUNT
    resistance_TL_info_dict["period_count"] = res_period_count
    # ADD THE RESISTANCE LINE START MAXIMA TIMESTAMP AND PRICE, AND CURRENT MAXIMA TIMESTAMP AND PRICE TO THE CONTACT MAXIMAS DICTIONARY
    resistance_TL_info_dict["contact_maximas_tup_list"] = [(resistance_line_start_ts, resistance_line_start_p)] + contact_maximas_tup_list + [(current_maxima_ts, current_maxima_p)]
    # SET THE SLOPE
    resistance_TL_info_dict["slope"] = get_price_slope(resistance_line_start_p, current_maxima_p, res_period_count)
    # COLLECT THE RESISTANCE LINE, CONTACT POINTS, AND RETURN THE DICTIONARY
    return resistance_TL_info_dict


# FUNCTION: GENERATE SUPPORT AND RESISTANCE TREND LINES
def add_TL_cols(ohlcv_pdf_in):
    """
    Add support and resistance trend line columns to the OHLCV dataframe.
    
    This function takes an OHLCV dataframe and adds columns for:
    - Support line bottom, middle, and top (with ATR buffer)
    - Resistance line bottom, middle, and top (with ATR buffer)
    
    The trend lines are generated using the get_support_TL_info_dict() and 
    get_resistance_TL_info_dict() functions which identify the best support and
    resistance trend lines based on price extrema.
    
    Parameters
    ----------
    ohlcv_pdf_in : pandas.DataFrame
        Input OHLCV dataframe with columns: timestamp, open, high, low, close, volume
        
    Returns
    -------
    pandas.DataFrame
        OHLCV dataframe with added trend line columns:
        - sup_bot: Support line bottom (support - ATR buffer)
        - support: Support line middle 
        - sup_top: Support line top (support + ATR buffer)
        - res_bot: Resistance line bottom (resistance - ATR buffer)
        - resistance: Resistance line middle
        - res_top: Resistance line top (resistance + ATR buffer)
    """
    # GENERATE SUPPORT AND RESISTANCE TREND LINES
    support_TL_info_dict = get_support_TL_info_dict(ohlcv_pdf_in, alert_in=False)
    resistance_line_info_dict = get_resistance_TL_info_dict(ohlcv_pdf_in, alert_in=False)
    # EXTRACT SUPPORT LINE DATA
    support_line_dict = support_TL_info_dict["ts_p_dict"]
    sup_atr_buffer = support_TL_info_dict["atr_buffer"]
    # EXTRACT RESISTANCE LINE DATA
    resistance_line_dict = resistance_line_info_dict["ts_p_dict"]
    res_atr_buffer = resistance_line_info_dict["atr_buffer"]
    
    # CREATE ALL MAPPING DICTIONARIES AT ONCE
    mappings_dict = {
        "sup_bot": {ts: price - sup_atr_buffer for ts, price in support_line_dict.items()},
        "support": support_line_dict,
        "sup_top": {ts: price + sup_atr_buffer for ts, price in support_line_dict.items()},
        "res_bot": {ts: price - res_atr_buffer for ts, price in resistance_line_dict.items()},
        "resistance": resistance_line_dict,
        "res_top": {ts: price + res_atr_buffer for ts, price in resistance_line_dict.items()}
    }
    # APPLY ALL MAPPINGS TO THE DATAFRAME IN ONE VECTORIZED OPERATION
    timestamp_series = ohlcv_pdf_in['timestamp']
    # ITERATE OVER THE MAPPING DICTIONARIES
    for col_name, mapping_dict in mappings_dict.items():
        # APPLY THE MAPPING TO THE DATAFRAME
        ohlcv_pdf_in[col_name] = timestamp_series.map(mapping_dict)
    # RETURN THE DATAFRAME
    return ohlcv_pdf_in

# FUNCTION: CONVERT SLOPE TO ANGLE
def slope_to_angle(slope):
    """
    Converts a slope (m) into an angle in degrees.
    
    Parameters:
    slope (float): The slope of a line (rise/run).
    
    Returns:
    float: The angle in degrees.
    """
    # CONVERT SLOPE TO ANGLE IN RADIANS
    angle_rad = np.arctan(slope)
    # CONVERT ANGLE IN RADIANS TO DEGREES
    angle_deg = np.degrees(angle_rad)
    # RETURN ANGLE IN DEGREES
    return angle_deg

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
    