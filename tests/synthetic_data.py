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
