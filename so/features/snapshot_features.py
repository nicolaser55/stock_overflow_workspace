import pandas as pd
import numpy as np
# IMPORT EXPERIMENT CONFIGURATION
from so import config
# IMPORT TRANSFORM OHLCV DATA FUNCTIONS
from so.features.ohlcv_data_utils import ohlcv_pdf_to_PA_tf_ohlcv_pdf_list, \
                                get_or_create_date_PA_tf_ohlcv_pdf_list, \
                                add_cs_attribute_cols
# IMPORT OHLCV TOOLS (INDICATORS AND MARKET STRUCTURE)
from so.features.tf_ohlcv_tools import detect_market_structure, \
                            add_SO_cols, \
                            add_MACD_cols, \
                            add_RSI_col, \
                            add_DC_cols, \
                            add_BB_cols
# IMPORT MARKET DATETIME FUNCTIONS
from so.core.datetime_utils import get_date_pdf

"""
Snapshot Features (pipeline steps 01, 02 and 03)

Moved from the collection notebooks of the previous workspace (step00_label_ohlcv_data, step06_TSIND_data_collection,
step08_TSSEG_data_collection) into one module. The LOGIC IS UNCHANGED, so the rows are identical to the previous
TSIND / TSSEG files (existing files can be copied into the new step02 / step03 folders instead of regenerated).

Point-in-time ("snapshot") design: every session is converted into growing snapshots (bars 0..k). The row of minute k
is computed from snapshot k only, so it never uses bars after k. See docs/SO_pipeline_understanding.md for the exact
column definitions and the lagged reads of the forward-shifted smooth price.

Changes compared with the notebooks:
    - complete_ohlcv_pdf, the cumulative maximum dictionary and (optionally) the snapshot list are passed as arguments
      instead of being read from notebook globals;
    - the cumulative maximum is computed in memory (context_features.add_cum_max_col) instead of being saved per year.
"""

"""
Step 00: Price Action (PA) Snapshots
"""

# FUNCTION: GENERATE DATE PRICE ACTION TIMEFRAME OHLCV DATAFRAME
def generate_date_PA_tf_ohlcv_pdf(complete_ohlcv_pdf_in, date_str_in):
    """
    Generates every price-action snapshot of a session and stacks them into one DataFrame (tagged with pdf_id).
    (Previously defined in step00_label_ohlcv_data.ipynb of the previous workspace.)

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Complete minute OHLCV data with a date column
        date_str_in (str): Session date 'YYYY-MM-DD'

    Returns:
        pd.DataFrame: Stacked snapshots without the date column (empty DataFrame if the date is not in the data)
    """
    # COLLECT THE DATE FOR THE DATAFRAME
    date_ohlcv_pdf = get_date_pdf(complete_ohlcv_pdf_in, date_str_in)
    # IF THE DATAFRAME EXISTS
    if isinstance(date_ohlcv_pdf, pd.DataFrame) and len(date_ohlcv_pdf) > 0:
        # CALL FUNCTION TO CONVERT OHLCV DATAFRAME TO TIMEFRAME OHLCV DATAFRAME LIST
        tf_ohlcv_pdf_list = ohlcv_pdf_to_PA_tf_ohlcv_pdf_list(date_ohlcv_pdf, alert_in=False)
        # LIST TO HOLD DATAFRAMES
        labeled_ohlcv_pdf_list = []
        # FOR DATAFRAME IN LIST
        for pdf_idx, tf_ohlcv_pdf in enumerate(tf_ohlcv_pdf_list):
            # ADD A COLUMN TO THE DATAFRAME WITH THE PDF ID
            tf_ohlcv_pdf["pdf_id"] = pdf_idx
            # APPEND THE DATAFRAME TO THE LIST
            labeled_ohlcv_pdf_list.append(tf_ohlcv_pdf)
        # CONCATENATE ALL DATAFRAMES
        return pd.concat(labeled_ohlcv_pdf_list).drop(columns=["date"])
    # RETURN EMPTY DATAFRAME
    return pd.DataFrame()

# FUNCTION: VALIDATE THE EXTREMAS FROM OHLCV PDF LIST
def validate_extremas_ohlcv_pdf_list(ohlcv_pdf_list_in, alert_in=True):
    """
    Checks that a confirmed swing never changes or disappears in later snapshots (the k-th minima / maxima of every
    snapshot must equal the k-th minima / maxima of the first snapshot in which it appeared).
    (Previously defined in step00_label_ohlcv_data.ipynb of the previous workspace.)

    Args:
        ohlcv_pdf_list_in (list[pd.DataFrame]): Snapshots of one session
        alert_in (bool): Display one line per snapshot

    Returns:
        bool: True if every snapshot passes (raises an Exception otherwise)
    """
    # DEFINE MINIMAS AND MAXIMAS DICTIONARIES
    minima_dict, maxima_dict = {}, {}
    # ITERATE OVER THE OHLCV PDF LIST
    for tf_ohlcv_pdf in ohlcv_pdf_list_in:
        # COLLECT THE CURRENT TIMESTAMP
        current_ts = tf_ohlcv_pdf.iloc[-1].timestamp
        # ITERATE OVER THE MINIMA AND MAXIMA COLUMNS
        for col_str, extrema_dict in [("minima", minima_dict), ("maxima", maxima_dict)]:
            # COLLECT ALL EXTREMA ROWS
            extrema_pdf = tf_ohlcv_pdf[tf_ohlcv_pdf[col_str].notna()]
            # ITERATE OVER THE EXTREMA TUPLE LIST
            for idx, ts, extrema in zip(np.arange(len(extrema_pdf)), extrema_pdf.timestamp, extrema_pdf[col_str]):
                # IF THE EXTREMA IDX IS IN THE DICTIONARY
                if idx in extrema_dict:
                    # IF THE PREVIOUS EXTREMA TUPLE IS NOT THE SAME AS THE CURRENT EXTREMA TUPLE
                    if extrema_dict[idx] != (ts, extrema):
                        # RAISE AN ERROR
                        raise Exception(f"Error! ❌ At\t{current_ts}\nCurrent {col_str} {(ts, extrema)} is not equal to the previous {col_str} {extrema_dict[idx]}")
                # IF THE IDX IS NOT IN THE DICTIONARY
                else:
                    # ADD THE TIMESTAMP AND EXTREMA TO THE DICTIONARY
                    extrema_dict[idx] = (ts, extrema)
        # DISPLAY INFORMATION
        print(f"TS:\t{current_ts}\tPrev Minima & Maxima Passed! ✅") if alert_in else None
    # RETURN TRUE
    return True

"""
Step 01: Timestamp Indicator (TSIND) Rows
"""

# FUNCTION: APPLY OHLCV FUNCTIONS AT TIMEFRAME AND RETURN THE TIMESTAMP INDICATOR (TSIND) DICTIONARY
def get_TSIND_dict(ohlcv_pdf_in):
    """
    Computes the indicator row of the LAST bar of a price-action snapshot (43 fields).
    (Previously defined in step06_TSIND_data_collection.ipynb of the previous workspace; logic unchanged.)

    The forward-shifted price-action fields (smooth_price, composite_price, composite_price_slope, trend, segment)
    are read from the second-to-last row because their last row is always NaN. Support / resistance levels and trend
    lines are not included (they are sometimes null).

    Args:
        ohlcv_pdf_in (pd.DataFrame): One price-action snapshot (output of add_PA_cols)

    Returns:
        dict: Indicator values of the last bar
    """
    # COLLECT THE MARKET STRUCTURE
    market_structure_dict = detect_market_structure(ohlcv_pdf_in)
    # APPLY THE OHLCV TOOLS
    mod_ohlcv_pdf = ohlcv_pdf_in.pipe(add_SO_cols).pipe(add_MACD_cols).pipe(add_RSI_col).pipe(add_DC_cols).pipe(add_BB_cols).pipe(add_cs_attribute_cols)
    # COLLECT THE LAST CURRENT ROW
    current_row = mod_ohlcv_pdf.iloc[-1]
    # PRE-DEFINE DERIVED COLUMNS WITH EMPTY VALUES
    smooth_price = np.nan
    composite_price = np.nan
    composite_price_slope = np.nan
    trend = np.nan
    segment = np.nan
    # IF THE DATAFRAME HAS MORE THAN 1 ROW
    if len(ohlcv_pdf_in) > 1:
        # RE-DEFINE THE RELEVANT DERIVED COLUMN VALUES
        smooth_price = mod_ohlcv_pdf.smooth_price.iloc[-2]
        composite_price = mod_ohlcv_pdf.composite_price.iloc[-2]
        composite_price_slope = mod_ohlcv_pdf.composite_price_slope.iloc[-2]
        trend = mod_ohlcv_pdf.trend.iloc[-2]
        segment = mod_ohlcv_pdf.segment.iloc[-2]
    # CALCULATE THE DONCHIAN WIDTH
    dc_width = current_row.dc_top - current_row.dc_bot
    # CALCULATE THE DONCHIAN PCT (WHERE THE CLOSE IS WITHIN THE DONCHIAN CHANNEL)
    dc_pct = (current_row.close - current_row.dc_bot) / (current_row.dc_top - current_row.dc_bot)
    # CREATE A DICTIONARY WITH THE CURRENT ROW VARIABLES
    return {
        "timestamp": current_row.timestamp,
        "open": current_row.open,
        "high": current_row.high,
        "low": current_row.low,
        "close": current_row.close,
        "volume": current_row.volume,
        # AVERAGE PRICE
        "avg_price": current_row.avg_price,
        # DERIVED COLUMNS
        "smooth_price": smooth_price,
        "extremas_pp": current_row.extremas_pp,
        "composite_price": composite_price,
        "composite_price_slope": composite_price_slope,
        "trend": trend,
        "segment": segment,
        # CANDLESTICK FORM ATTRIBUTES
        "atr": round(current_row.atr, 6),
        "color": current_row.color,
        "span": round(current_row.span, 6),
        "body_span": round(current_row.body_span, 6),
        "bot_wick_pct": round(current_row.bot_wick_pct, 6),
        "body_pct": round(current_row.body_pct, 6),
        "top_wick_pct": round(current_row.top_wick_pct, 6),
        # CURRENT ROW INDICATORS
        "stoch_k": round(current_row.stoch_k, 6),
        "stoch_d": round(current_row.stoch_d, 6),
        "macd": round(current_row.macd, 6),
        "signal": round(current_row.signal, 6),
        "histogram": round(current_row.histogram, 6),
        "rsi": round(current_row.rsi, 6),
        # BOLLINGER BANDS VALUES
        "bb_width": round(current_row.bb_width, 6),
        "bb_bot": round(current_row.bb_bot, 6),
        "bb_mid": round(current_row.bb_mid, 6),
        "bb_top": round(current_row.bb_top, 6),
        "bb_pct": round(current_row.bb_pct_b, 6),
        # DONCHIAN CHANNEL VALUES
        "dc_width": round(dc_width, 6),
        "dc_bot": round(current_row.dc_bot, 6),
        "dc_mid": round(current_row.dc_mid, 6),
        "dc_top": round(current_row.dc_top, 6),
        "dc_pct": round(dc_pct, 6),
        # MARKET STRUCTURE
        "current_minima": market_structure_dict["current_minima"],
        "current_maxima": market_structure_dict["current_maxima"],
        "ms_minima_trend": market_structure_dict["minima_trend"],
        "ms_maxima_trend": market_structure_dict["maxima_trend"],
        "ms_low_status": market_structure_dict["low_status"],
        "ms_high_status": market_structure_dict["high_status"],
        "ms_trend": market_structure_dict["trend"],
    }

# FUNCTION: GENERATE THE DATE TIMESTAMP INDICATOR (TSIND) DATAFRAME
def get_date_TSIND_pdf(complete_ohlcv_pdf_in, date_str_in, PA_tf_ohlcv_pdf_list_in=None):
    """
    Generates the TSIND rows of one session (one row per minute, each from its own snapshot).

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Complete minute OHLCV data with a date column
        date_str_in (str): Session date 'YYYY-MM-DD'
        PA_tf_ohlcv_pdf_list_in (list | None): Snapshots of the session; None reads (or creates) the step01 cache

    Returns:
        pd.DataFrame: TSIND rows
    """
    # CALL FUNCTION TO PROCESS DATE OHLCV DATA (READ OR CREATE THE STEP01 SNAPSHOTS)
    PA_tf_ohlcv_pdf_list = PA_tf_ohlcv_pdf_list_in if PA_tf_ohlcv_pdf_list_in is not None else get_or_create_date_PA_tf_ohlcv_pdf_list(complete_ohlcv_pdf_in, date_str_in, alert_in=True)
    # CONVERT THE LIST OF TSIND DICTIONARIES TO A DATAFRAME AND RETURN
    return pd.DataFrame([get_TSIND_dict(PA_tf_ohlcv_pdf.copy()) for PA_tf_ohlcv_pdf in PA_tf_ohlcv_pdf_list])

"""
Step 02: Timestamp Segment (TSSEG) Rows
"""

# FUNCTION: GENERATE DATE TIMESTAMP SEGMENT (TSSEG) DATAFRAME
def get_date_TSSEG_pdf(complete_ohlcv_pdf_in, ts_cum_max_dict_in, date_str_in, PA_tf_ohlcv_pdf_list_in=None):
    """
    Generates the TSSEG rows of one session: an anchor moves to the latest swing each time a new swing is confirmed,
    and every row measures the distance (price and bars) from that anchor.
    (Previously defined in step08_TSSEG_data_collection.ipynb of the previous workspace; logic unchanged.)

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Complete minute OHLCV data with a date column
        ts_cum_max_dict_in (dict): Timestamp -> running maximum high since the start of the data
        date_str_in (str): Session date 'YYYY-MM-DD'
        PA_tf_ohlcv_pdf_list_in (list | None): Snapshots of the session; None reads (or creates) the step01 cache

    Returns:
        pd.DataFrame: TSSEG rows
    """
    # CALL FUNCTION TO PROCESS DATE OHLCV DATA (READ OR CREATE THE STEP01 SNAPSHOTS)
    PA_tf_ohlcv_pdf_list = PA_tf_ohlcv_pdf_list_in if PA_tf_ohlcv_pdf_list_in is not None else get_or_create_date_PA_tf_ohlcv_pdf_list(complete_ohlcv_pdf_in, date_str_in, alert_in=True)
    # DEFINE MINIMA AND MAXIMA COUNTER
    minima_dict, maxima_dict = {"idx": np.nan, "count": 0}, {"idx": np.nan, "count": 0}
    # DEFINE SEGMENT
    segment_dict = {"idx": 0, "price": np.nan, "count": 0}
    # CREATE A LIST TO HOLD CURRENT ROW INFORMATION
    data_dict_list = []
    # ITERATE OVER DATAFRAME LIST
    for PA_tf_ohlcv_pdf in PA_tf_ohlcv_pdf_list:
        # RESET INDEX OF DATAFRAME (POSITION WITHIN THE SESSION)
        PA_tf_ohlcv_pdf = PA_tf_ohlcv_pdf.reset_index(drop=True)
        # COLLECT THE CURRENT ROW
        current_row = PA_tf_ohlcv_pdf.iloc[-1]
        # COLLECT THE CURRENT ROW INFORMATION
        current_idx = current_row.name
        current_ts = current_row.timestamp
        current_price = current_row.avg_price
        # COLLECT THE CURRENT MINIMA AND MAXIMA COUNT
        minima_count, maxima_count = PA_tf_ohlcv_pdf.minima.count(), PA_tf_ohlcv_pdf.maxima.count()
        # DEFINE DATA DICT
        data_dict = {
            "timestamp": current_ts,
            "open": current_row.open,
            "high": current_row.high,
            "low": current_row.low,
            "close": current_row.close,
            "volume": current_row.volume,
            "avg_price": current_price,
            "cum_max": ts_cum_max_dict_in[current_ts]
        }
        # DEFINE NEW MINIMA AND NEW MAXIMA BOOL
        new_minima_bool, new_maxima_bool = False, False
        # IF THE MINIMA COUNT IS GREATER THAN THE PREVIOUS MINIMA COUNT
        if (minima_count > minima_dict["count"]):
            # SET THE NEW MINIMA BOOL TO TRUE AND THE MINIMA COUNTER TO THE CURRENT MINIMA COUNT
            new_minima_bool = True
            # SET THE MINIMA DICT VALUES
            minima_dict["idx"] = PA_tf_ohlcv_pdf.minima.last_valid_index()
            minima_dict["count"] = minima_count
        # IF THE MAXIMA COUNT IS GREATER THAN THE PREVIOUS MAXIMA COUNT
        if (maxima_count > maxima_dict["count"]):
            # SET THE NEW MAXIMA BOOL TO TRUE AND THE MAXIMA COUNTER TO THE CURRENT MAXIMA COUNT
            new_maxima_bool = True
            # SET THE MAXIMA DICT VALUES
            maxima_dict["idx"] = PA_tf_ohlcv_pdf.maxima.last_valid_index()
            maxima_dict["count"] = maxima_count
        # IF A NEW MINIMA OR NEW MAXIMA IS FOUND
        if (new_minima_bool or new_maxima_bool):
            # COLLECT THE LATEST EXTREMA BETWEEN MINIMA AND MAXIMA
            latest_extrema_idx = max(minima_dict["idx"], maxima_dict["idx"])
            # SET THE SEGMENT INDEX AND PRICE
            segment_dict["idx"] = latest_extrema_idx
            segment_dict["price"] = PA_tf_ohlcv_pdf.loc[latest_extrema_idx].avg_price
            # INCREMENT THE SEGMENT COUNTER
            segment_dict["count"] += 1
        # ADD THE MINIMA AND MAXIMA COUNT TO THE DATA DICT
        data_dict["minima_count"] = minima_count
        data_dict["maxima_count"] = maxima_count
        # SET THE PREVIOUS SEGMENT DELTA IN THE DATA DICT
        data_dict["prev_seg_delta"] = current_price - segment_dict["price"]
        # CALCULATE THE PREVIOUS SEGMENT DELTA AS A PERCENTAGE OF THE LAST SEGMENT'S AVERAGE PRICE
        data_dict["prev_seg_delta_pct"] = np.round(data_dict["prev_seg_delta"] / segment_dict["price"], 6)
        # CALCULATE THE CANDLESTICKS INTO THE SEGMENT
        data_dict["seg_cs_count"] = current_idx - segment_dict["idx"]
        # ADD SEGMENT TO THE DATA DICT
        data_dict["seg"] = segment_dict["count"]
        # APPEND THE DATA DICT TO THE LIST
        data_dict_list.append(data_dict)
    # CONVERT THE LIST TO A DATAFRAME
    return pd.DataFrame(data_dict_list)
