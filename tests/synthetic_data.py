import pandas as pd
import numpy as np
# IMPORT MARKET DATETIME FUNCTIONS
from so.core.datetime_utils import ny_tz, get_date_range_market_schedule_pdf

"""
Synthetic Minute Data For Tests

Generates SPY-like regular-hours minute bars on the real NYSE calendar (including half days), so the tests exercise
the same session logic as the real data without needing the IBKR files.
"""

# FUNCTION: GENERATE SYNTHETIC MINUTE OHLCV DATA
def get_synthetic_ohlcv_pdf(date1_str_in, date2_str_in, start_price_in=100.0, minute_vol_in=0.0008, seed_in=0):
    """
    Generates a random-walk minute OHLCV DataFrame (timestamp, open, high, low, close, volume, date) with overnight gaps.

    Args:
        date1_str_in (str): First date
        date2_str_in (str): Last date
        start_price_in (float): First open
        minute_vol_in (float): Standard deviation of minute log returns
        seed_in (int): Random seed

    Returns:
        pd.DataFrame: Minute bars in New York time, prices rounded to cents
    """
    # CREATE THE RANDOM GENERATOR
    rng = np.random.default_rng(seed_in)
    # COLLECT THE MARKET SCHEDULE
    schedule_pdf = get_date_range_market_schedule_pdf(date1_str_in, date2_str_in)
    # LIST TO HOLD THE SESSION DATAFRAMES
    pdf_list = []
    # DEFINE THE CURRENT PRICE
    price = start_price_in
    # ITERATE OVER THE SESSIONS
    for open_ts, close_ts in zip(schedule_pdf.market_open_ts, schedule_pdf.market_close_ts):
        # CREATE THE MINUTE TIMESTAMPS (THE CLOSE IS ALREADY THE LAST BAR)
        ts_index = pd.date_range(open_ts, close_ts, freq="min")
        # APPLY AN OVERNIGHT GAP
        price = price * np.exp(rng.normal(0, 0.004))
        # GENERATE THE MINUTE CLOSES
        close_arr = price * np.exp(np.cumsum(rng.normal(0.0, minute_vol_in, len(ts_index))))
        open_arr = np.concatenate([[price], close_arr[:-1]])
        # GENERATE THE HIGHS AND LOWS AROUND THE BODY
        wick_arr = np.abs(rng.normal(0, minute_vol_in * price, len(ts_index)))
        high_arr = np.maximum(open_arr, close_arr) + wick_arr * rng.random(len(ts_index))
        low_arr = np.minimum(open_arr, close_arr) - wick_arr * rng.random(len(ts_index))
        # APPEND THE SESSION
        pdf_list.append(pd.DataFrame({"timestamp": ts_index, "open": open_arr, "high": high_arr, "low": low_arr, "close": close_arr,
                                      "volume": rng.integers(50_000, 500_000, len(ts_index))}))
        # CARRY THE LAST CLOSE
        price = close_arr[-1]
    # CONCATENATE THE SESSIONS
    ohlcv_pdf = pd.concat(pdf_list, ignore_index=True)
    # ROUND THE PRICES TO CENTS (AND KEEP HIGH/LOW CONSISTENT AFTER ROUNDING)
    ohlcv_pdf[["open", "close"]] = ohlcv_pdf[["open", "close"]].round(2)
    ohlcv_pdf["high"] = np.maximum(ohlcv_pdf["high"].round(2), ohlcv_pdf[["open", "close"]].max(axis=1))
    ohlcv_pdf["low"] = np.minimum(ohlcv_pdf["low"].round(2), ohlcv_pdf[["open", "close"]].min(axis=1))
    # CONVERT THE TIMESTAMP TO NEW YORK TIME AND ADD THE DATE
    ohlcv_pdf["timestamp"] = pd.to_datetime(ohlcv_pdf["timestamp"], utc=True).dt.tz_convert(ny_tz)
    ohlcv_pdf["date"] = ohlcv_pdf["timestamp"].dt.date
    # RETURN DATAFRAME
    return ohlcv_pdf

# FUNCTION: GENERATE SYNTHETIC DAILY INDEX BARS (VIX-LIKE; ONE PER NYSE DATE, MIDNIGHT NEW YORK LABEL)
def get_synthetic_index_daily_pdf(date1_str_in, date2_str_in, start_in, seed_in):
    """
    Generates daily index bars in the format of so.features.vix_features.read_vix_daily_pdf (timestamp, open, high, low,
    close, created_ts, date), a positive random walk.

    Args:
        date1_str_in, date2_str_in (str): Date range
        start_in (float): Level at the start
        seed_in (int): Random seed

    Returns:
        pd.DataFrame: One row per NYSE date
    """
    # COLLECT THE DATES
    date_list = pd.to_datetime(get_date_range_market_schedule_pdf(date1_str_in, date2_str_in)["date"]).dt.date.tolist()
    # GENERATE A POSITIVE RANDOM WALK
    close_arr = np.round(start_in * np.exp(np.cumsum(np.random.default_rng(seed_in).normal(0, 0.05, len(date_list)))), 2)
    # RETURN THE BARS
    return pd.DataFrame({"timestamp": [pd.Timestamp(d).tz_localize(ny_tz) for d in date_list], "open": close_arr, "high": close_arr, "low": close_arr,
                         "close": close_arr, "created_ts": "synthetic", "date": date_list})

# FUNCTION: GENERATE SYNTHETIC 1-MINUTE INDEX BARS (09:31 TO 15 MINUTES AFTER THE CLOSE)
def get_synthetic_index_minute_pdf(date1_str_in, date2_str_in, start_in, seed_in):
    """
    Generates 1-minute index bars in the format of so.features.vix_features.read_vix_1min_pdf, labelled from 09:31 to 15
    minutes after the NYSE close of every session (half days included).

    Args:
        date1_str_in, date2_str_in (str): Date range
        start_in (float): Typical level
        seed_in (int): Random seed

    Returns:
        pd.DataFrame: timestamp (New York), open, high, low, close, created_ts, date
    """
    # CREATE THE GENERATOR AND COLLECT THE SCHEDULE
    rng = np.random.default_rng(seed_in)
    schedule_pdf = get_date_range_market_schedule_pdf(date1_str_in, date2_str_in)
    # LIST TO HOLD THE SESSIONS
    pdf_list = []
    # ITERATE OVER THE SESSIONS
    for open_ts, close_ts in zip(schedule_pdf.market_open_ts, schedule_pdf.market_close_ts):
        # CREATE THE LABELS AND THE CLOSES
        ts_index = pd.date_range(pd.Timestamp(open_ts) + pd.Timedelta(minutes=1), pd.Timestamp(close_ts) + pd.Timedelta(minutes=15), freq="min").tz_convert(ny_tz)
        close_arr = np.round(start_in * np.exp(rng.normal(0, 0.1) + np.cumsum(rng.normal(0, 0.002, len(ts_index)))), 2)
        pdf_list.append(pd.DataFrame({"timestamp": ts_index, "open": close_arr, "high": close_arr, "low": close_arr, "close": close_arr,
                                      "created_ts": "synthetic", "date": ts_index.date}))
    # RETURN THE BARS
    return pd.concat(pdf_list, ignore_index=True)
