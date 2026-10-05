import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION (DAILY FEATURE CONSTANTS)
from so import config
# IMPORT TRADE EXECUTION FUNCTIONS
from so.core.trade_execution import get_net_return_arr

"""
Daily Features And Target (pipeline step 06 TSDAY; used by exp02, exp03 and later daily experiments)

One row per session, built directly from the minute bars (ohlcv_array_dict). The row of session i describes the market at
its DECISION BAR (15:58 on a full day, the second-to-last bar on half days); the trade it labels fills at the open of the
next bar (15:59).

Point-in-time rules:
    - values of session i use the bars of session i up to and including the decision bar, and complete PREVIOUS sessions;
    - previous sessions are the sessions present in the data (2007-07-02 is missing, so 2007-06-29 is the previous session
      of 2007-07-03);
    - the label (fwd_net_return_20d, y_fwd_positive) is the ONLY column that looks forward.

Columns:
    session_idx             position of the session in ohlcv_array_dict["session_date_list"]
    date                    session date
    decision_ts             timestamp of the decision bar
    decision_idx, fill_idx  bar indexes of the decision bar and of the fill bar (fill = decision + 1)
    decision_close          close of the decision bar
    fill_open               open of the fill bar (raw, before slippage)
    session_open/high/low/close   OHLC of the complete session (close = last bar; used for features of LATER sessions only)

    Features (same definitions as TSCTX where the name is shared, evaluated at the decision bar):
    prev_day_return_pct     previous session close / close of the session before it - 1
    prev_day_range_pct      (previous session high - previous session low) / previous session close
    intraday_return_pct     decision close / session open - 1
    daily_volatility        std of the previous 20 daily close-to-close returns (also the stop volatility of the session)
    ath_drawdown_pct        decision close / running maximum high since the start of the data (up to the decision bar) - 1
    return_<n>d             decision close / close of the session n sessions earlier - 1  (n = 5, 20, 60, 120, 250)
    ma<n>_dist_pct          decision close / mean close of the previous n sessions - 1  (n = 50, 200)
    volatility_ratio_20_60  daily_volatility / std of the previous 60 daily returns
    high<n>_dist_pct        decision close / highest high of the last n sessions (today up to the decision bar) - 1  (n = 60, 250)
    sessions_since_high60   sessions since the highest high of the last 60 sessions (0 = today)

    Target:
    fwd_net_return_20d      net return of buying at the fill (open + slippage) and selling at the close of session i+20
                            (- slippage), with the per share fees of trade_execution.get_net_return_arr
    y_fwd_positive          1 if fwd_net_return_20d > 0, else 0 (NaN when session i+20 is not in the data yet)
"""

# FUNCTION: GET THE DECISION AND FILL BAR INDEXES OF EVERY SESSION
def get_session_decision_idx_dict(ohlcv_array_dict_in, decision_offset_in=config.DECISION_BAR_OFFSET_FROM_END):
    """
    Returns the decision bar (offset bars before the last bar) and the fill bar (the bar after the decision) of every session.

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        decision_offset_in (int): Bars between the decision bar and the last bar of the session

    Returns:
        dict: {"decision_idx_arr": np.ndarray, "fill_idx_arr": np.ndarray}
    """
    # COLLECT THE SESSION BOUNDS
    start_idx_arr = ohlcv_array_dict_in["session_start_idx_arr"]
    end_idx_arr = ohlcv_array_dict_in["session_end_idx_arr"]
    # CALCULATE THE DECISION BAR (NEVER BEFORE THE FIRST BAR OF THE SESSION)
    decision_idx_arr = np.maximum(end_idx_arr - decision_offset_in, start_idx_arr)
    # CALCULATE THE FILL BAR (NEVER AFTER THE LAST BAR OF THE SESSION)
    fill_idx_arr = np.minimum(decision_idx_arr + 1, end_idx_arr)
    # RETURN THE DICTIONARY
    return {"decision_idx_arr": decision_idx_arr.astype(int), "fill_idx_arr": fill_idx_arr.astype(int)}

# FUNCTION: GET THE SESSION TABLE
def get_session_table_pdf(ohlcv_array_dict_in):
    """
    Aggregates the minute bars into one row per session (complete-session OHLC and decision-bar values).

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict

    Returns:
        pd.DataFrame: session_idx, date, decision_ts, decision_idx, fill_idx, decision_close, fill_open,
                      high_to_decision, session_open, session_high, session_low, session_close
    """
    # COLLECT THE ARRAYS
    open_arr, high_arr, low_arr, close_arr = (ohlcv_array_dict_in[key] for key in ["open_arr", "high_arr", "low_arr", "close_arr"])
    start_idx_arr = ohlcv_array_dict_in["session_start_idx_arr"]
    end_idx_arr = ohlcv_array_dict_in["session_end_idx_arr"]
    # COLLECT THE DECISION AND FILL BARS
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    decision_idx_arr, fill_idx_arr = idx_dict["decision_idx_arr"], idx_dict["fill_idx_arr"]
    # CALCULATE THE COMPLETE-SESSION HIGH AND LOW (REDUCE OVER [START, NEXT START))
    session_high_arr = np.maximum.reduceat(high_arr, start_idx_arr)
    session_low_arr = np.minimum.reduceat(low_arr, start_idx_arr)
    # CALCULATE THE HIGH UP TO AND INCLUDING THE DECISION BAR (REDUCE OVER [START, DECISION + 1), EVEN POSITIONS ONLY)
    bound_idx_arr = np.column_stack([start_idx_arr, decision_idx_arr + 1]).ravel()
    bound_idx_arr = bound_idx_arr[bound_idx_arr < len(high_arr)]
    high_to_decision_arr = np.maximum.reduceat(high_arr, bound_idx_arr)[::2][:len(start_idx_arr)]
    # RETURN THE DATAFRAME
    return pd.DataFrame({
        "session_idx": np.arange(len(start_idx_arr)),
        "date": ohlcv_array_dict_in["session_date_list"],
        "decision_ts": ohlcv_array_dict_in["timestamp_index"][decision_idx_arr],
        "decision_idx": decision_idx_arr,
        "fill_idx": fill_idx_arr,
        "decision_close": close_arr[decision_idx_arr],
        "fill_open": open_arr[fill_idx_arr],
        "high_to_decision": high_to_decision_arr,
        "session_open": open_arr[start_idx_arr],
        "session_high": session_high_arr,
        "session_low": session_low_arr,
        "session_close": close_arr[end_idx_arr],
    })

# FUNCTION: GET THE SESSIONS SINCE THE ROLLING HIGH
def get_sessions_since_high_arr(prev_high_arr_in, today_high_arr_in, window_in):
    """
    Counts the sessions since the highest high of the last window_in sessions (today's high up to the decision bar included).

    Args:
        prev_high_arr_in (np.ndarray): Complete-session highs
        today_high_arr_in (np.ndarray): Highs up to the decision bar of every session
        window_in (int): Number of sessions in the window (today included)

    Returns:
        np.ndarray: Sessions since the high (0 = today; NaN when fewer than window_in sessions exist)
    """
    # DEFINE THE OUTPUT
    session_count = len(prev_high_arr_in)
    result_arr = np.full(session_count, np.nan)
    # ITERATE OVER THE SESSIONS WITH A FULL WINDOW
    for session_idx in range(window_in - 1, session_count):
        # BUILD THE WINDOW: PREVIOUS window_in - 1 COMPLETE SESSIONS + TODAY UP TO THE DECISION BAR
        window_arr = np.append(prev_high_arr_in[session_idx - window_in + 1:session_idx], today_high_arr_in[session_idx])
        # FIND THE LAST POSITION OF THE MAXIMUM (MOST RECENT HIGH WINS TIES)
        last_max_pos = len(window_arr) - 1 - int(np.argmax(window_arr[::-1]))
        # STORE THE SESSIONS SINCE THE HIGH
        result_arr[session_idx] = len(window_arr) - 1 - last_max_pos
    # RETURN THE ARRAY
    return result_arr

# FUNCTION: GET THE DAILY FEATURE AND TARGET DATAFRAME
def get_daily_feature_pdf(ohlcv_array_dict_in, label_horizon_in=config.LABEL_HORIZON_SESSIONS):
    """
    Builds the daily feature rows and the forward target of every session (see the module docstring).

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict (complete data)
        label_horizon_in (int): Forward horizon of the label (sessions)

    Returns:
        pd.DataFrame: One row per session
    """
    # GET THE SESSION TABLE
    daily_pdf = get_session_table_pdf(ohlcv_array_dict_in)
    # COLLECT THE SERIES
    close_series = daily_pdf["session_close"]
    decision_close_series = daily_pdf["decision_close"]
    # CALCULATE THE DAILY CLOSE-TO-CLOSE RETURNS OF COMPLETE SESSIONS
    daily_return_series = close_series / close_series.shift(1) - 1
    # CALCULATE THE PREVIOUS SESSION FEATURES
    daily_pdf["prev_day_return_pct"] = daily_return_series.shift(1)
    daily_pdf["prev_day_range_pct"] = (daily_pdf["session_high"].shift(1) - daily_pdf["session_low"].shift(1)) / close_series.shift(1)
    # CALCULATE THE INTRADAY RETURN AT THE DECISION BAR
    daily_pdf["intraday_return_pct"] = decision_close_series / daily_pdf["session_open"] - 1
    # CALCULATE THE DAILY VOLATILITY FROM PRIOR SESSIONS ONLY (SAME DEFINITION AS TSCTX)
    daily_pdf["daily_volatility"] = daily_return_series.rolling(config.DAILY_VOLATILITY_SESSIONS, min_periods=config.DAILY_VOLATILITY_SESSIONS).std().shift(1)
    long_volatility_series = daily_return_series.rolling(config.LONG_VOLATILITY_SESSIONS, min_periods=config.LONG_VOLATILITY_SESSIONS).std().shift(1)
    daily_pdf["volatility_ratio_20_60"] = daily_pdf["daily_volatility"] / long_volatility_series
    # CALCULATE THE DISTANCE FROM THE ALL-TIME HIGH (RUNNING MAX OF PREVIOUS SESSIONS AND TODAY UP TO THE DECISION BAR)
    previous_max_high_series = daily_pdf["session_high"].cummax().shift(1)
    ath_series = np.fmax(previous_max_high_series.to_numpy(), daily_pdf["high_to_decision"].to_numpy())
    daily_pdf["ath_drawdown_pct"] = decision_close_series / ath_series - 1
    # CALCULATE THE PAST RETURNS (DECISION CLOSE vs COMPLETE CLOSE n SESSIONS EARLIER)
    for session_count in config.PAST_RETURN_SESSION_LIST:
        daily_pdf[f"return_{session_count}d"] = decision_close_series / close_series.shift(session_count) - 1
    # CALCULATE THE MOVING AVERAGE DISTANCES (MEAN OF THE PREVIOUS n COMPLETE CLOSES)
    for session_count in config.MOVING_AVERAGE_SESSION_LIST:
        moving_average_series = close_series.rolling(session_count, min_periods=session_count).mean().shift(1)
        daily_pdf[f"ma{session_count}_dist_pct"] = decision_close_series / moving_average_series - 1
    # CALCULATE THE ROLLING HIGH DISTANCES (PREVIOUS n-1 COMPLETE SESSIONS + TODAY UP TO THE DECISION BAR)
    for session_count in config.ROLLING_HIGH_SESSION_LIST:
        previous_high_series = daily_pdf["session_high"].rolling(session_count - 1, min_periods=session_count - 1).max().shift(1)
        rolling_high_arr = np.where(previous_high_series.isna(), np.nan, np.fmax(previous_high_series.to_numpy(), daily_pdf["high_to_decision"].to_numpy()))
        daily_pdf[f"high{session_count}_dist_pct"] = decision_close_series / rolling_high_arr - 1
    # CALCULATE THE SESSIONS SINCE THE 60-SESSION HIGH
    daily_pdf["sessions_since_high60"] = get_sessions_since_high_arr(daily_pdf["session_high"].to_numpy(), daily_pdf["high_to_decision"].to_numpy(), 60)
    # CALCULATE THE FORWARD TARGET (BUY AT THE FILL OPEN, SELL AT THE CLOSE OF SESSION i + HORIZON, MARKET ORDER COSTS)
    exit_close_arr = close_series.shift(-label_horizon_in).to_numpy()
    daily_pdf["fwd_net_return_20d"] = get_net_return_arr(daily_pdf["fill_open"].to_numpy(), exit_close_arr,
                                                         np.full(len(daily_pdf), config.EXIT_REASON_TL, dtype=object))
    daily_pdf["y_fwd_positive"] = np.where(np.isnan(daily_pdf["fwd_net_return_20d"]), np.nan, (daily_pdf["fwd_net_return_20d"] > 0).astype(float))
    # ROUND THE FLOAT COLUMNS
    float_col_str_list = [col for col in daily_pdf.select_dtypes(include="float").columns if col not in ["y_fwd_positive", "sessions_since_high60"]]
    daily_pdf[float_col_str_list] = daily_pdf[float_col_str_list].round(10)
    # RETURN THE DATAFRAME
    return daily_pdf

# FUNCTION: GET THE TRAINING ROWS OF A DATE WINDOW
def get_daily_train_pdf(daily_pdf_in, date1_in, date2_in, feature_col_str_list_in=config.DAILY_FEATURE_COL_STR_LIST):
    """
    Returns the rows of a date window that have a resolved label and every feature (rows with missing values are dropped).

    Args:
        daily_pdf_in (pd.DataFrame): Output of get_daily_feature_pdf
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        feature_col_str_list_in (list[str]): Model features

    Returns:
        pd.DataFrame: Usable training rows
    """
    # CONVERT THE BOUNDS
    date1_object, date2_object = pd.to_datetime(date1_in).date(), pd.to_datetime(date2_in).date()
    # SELECT THE WINDOW
    window_pdf = daily_pdf_in[(daily_pdf_in["date"] >= date1_object) & (daily_pdf_in["date"] <= date2_object)]
    # RETURN THE COMPLETE ROWS
    return window_pdf.dropna(subset=list(feature_col_str_list_in) + ["y_fwd_positive"])
