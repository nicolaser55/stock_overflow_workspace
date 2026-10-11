import os
import numpy as np
import pandas as pd
# IMPORT PATHS
from so import paths
# IMPORT THE VIX CONSTANTS
from so import vix_config
# IMPORT MARKET DATETIME FUNCTIONS
from so.core.datetime_utils import ny_tz

"""
VIX Data Layer: point-in-time VIX and VIX3M values and features for every SPY session (roadmap 2026-10-09, exp08-exp11)

Data: IBKR VIX and VIX3M index bars in store01_rawzone/ibkr_vix_family/{vix_1min, vix_daily, vix3m_1min, vix3m_daily}/
(daily: one file per calendar year, ohlcv_data_YYYY.csv; 1-minute: one file per session, ohlcv_data_YYYYMMDD.csv;
columns timestamp, open, high, low, close, volume, created_ts, date). Approved by Nicolas on 2026-10-08; read only. The
staging folder (ibkr_vix_family_staging/) and the backup folders are never read.

Loaders:
    - every loader takes a REQUIRED cutoff date (no default) and raises if it is missing or on or after the first day
      of the untouched window (vix_config.UNTOUCHED_START_DATE_STR = 2026-05-14);
    - the 1-minute loader never opens a file whose name date is after the cutoff; the daily loader never opens a year
      file after the cutoff's year, drops the rows after the cutoff immediately after parsing, then asserts that no row
      is dated after the cutoff or on or after 2026-05-14;
    - timestamps are parsed as UTC and converted to New York time (as so.core.raw_data); volume is dropped (not
      meaningful for an index); the "date" column must equal the New York date of the timestamp;
    - the daily timestamp is a LABEL (midnight New York of the date), not a time of trade: the daily close is only
      known at about 16:15, after the SPY decision bar of the same date.

Timing variants (one value per series and SPY session t):
    _prev       PRIMARY. The close of the latest daily bar dated strictly BEFORE t. NaN if that bar is more than
                STALE_MAX_SESSIONS SPY sessions older than the previous SPY session (stale), or if no bar exists.
    _intraday   SECONDARY. The close of the last 1-minute bar of session t whose label is at most
                decision_ts(t) - INTRADAY_MIN_LAG_MINUTES (15:57 or earlier on a full day; 12:57 on a 13:00 half day).
                If session t has no such bar (missing file, the half days left in staging), the _prev value is used
                and the session is counted as a fallback.
    Both are NaN before the first date of the series (VIX 2005-10-03, VIX3M 2009-08-12).

    The bar-label convention of the IBKR index data is UNPROVEN: the 2026-10-06 probe found no lead against SPY (no
    look-ahead detected) and a delay of about one minute. The one-minute lag of _intraday is a safety margin, not a
    proof; the primary results therefore use _prev.

Features of variant v (x_t = VIX value known at the decision of session t under v, m_t = VIX3M value; every feature
uses only values of sessions up to and including t and is NaN when an input is NaN):
    vix_level_v     x_t
    vix_pct250_v    share of the previous 250 values x_(t-250) ... x_(t-1) strictly below x_t (NaN unless all 250 exist)
    vix_chg5_v      log(x_t / x_(t-5))
    vix_fade_v      x_t / max(x_(t-19) ... x_t) - 1   (20 values including today; always <= 0)
    vix_term_v      x_t / m_t   (> 1 = inverted term structure, stress)
    vrp_v           (x_t / 100)^2 - (daily_volatility_t * sqrt(252))^2   (implied minus trailing realized annualized
                    variance; daily_volatility is the trailing 20-session std of so.features.daily_features)
"""

# FUNCTION: CHECK A LOADER CUTOFF
def check_cutoff_date(cutoff_date_str_in, untouched_start_str_in=vix_config.UNTOUCHED_START_DATE_STR):
    """
    Raises unless the cutoff is given and lies strictly before the first day of the untouched window.

    Args:
        cutoff_date_str_in (str): Last date the caller may load (inclusive)
        untouched_start_str_in (str): First day of the untouched window

    Returns:
        datetime.date: The cutoff date
    """
    # RAISE WITHOUT A CUTOFF
    if cutoff_date_str_in is None:
        raise ValueError("❌ A VIX loader needs an explicit cutoff date (no default).")
    # CONVERT THE CUTOFF
    cutoff_date = pd.Timestamp(cutoff_date_str_in).date()
    # RAISE IF THE CUTOFF REACHES THE UNTOUCHED WINDOW
    if cutoff_date >= pd.Timestamp(untouched_start_str_in).date():
        raise ValueError(f"❌ VIX loader cutoff {cutoff_date} is on or after the untouched window start {untouched_start_str_in}.")
    # RETURN THE CUTOFF DATE
    return cutoff_date

# FUNCTION: GET THE RAW FOLDER OF A SERIES
def get_vix_folder_path_str(series_str_in, bar_str_in, raw_path_str_in=None):
    """
    Returns the raw folder of a series and bar size (so.paths through vix_config.VIX_FOLDER_KEY_DICT) or an override.

    Args:
        series_str_in (str): "vix" or "vix3m"
        bar_str_in (str): "daily" or "1min"
        raw_path_str_in (str | None): Override folder (tests); None = the raw folder of so.paths

    Returns:
        str: Folder path ending with "/"
    """
    # RETURN THE OVERRIDE OR THE RAW FOLDER
    folder_path_str = raw_path_str_in or getattr(paths, vix_config.VIX_FOLDER_KEY_DICT[(series_str_in, bar_str_in)])
    return folder_path_str.replace("\\", "/").rstrip("/") + "/"

# FUNCTION: LIST THE FILES OF A FOLDER WITH THEIR NAME DATE
def get_vix_file_tuple_list(folder_path_str_in, name_format_str_in):
    """
    Lists the ohlcv_data_<stamp>.csv files of a folder with the stamp parsed (year or date), without opening them.

    Args:
        folder_path_str_in (str): Folder ending with "/"
        name_format_str_in (str): "%Y" (daily year files) or "%Y%m%d" (1-minute session files)

    Returns:
        list[tuple]: Sorted (stamp as pd.Timestamp, file path) tuples
    """
    # LIST TO HOLD THE TUPLES
    file_tuple_list = []
    # ITERATE OVER THE FILE NAMES OF THE FOLDER (NO SUBFOLDER IS ENTERED)
    for file_name_str in sorted(os.listdir(folder_path_str_in)):
        # SKIP ANYTHING THAT IS NOT A FILE OF THE EXPECTED NAME
        if not (file_name_str.startswith(vix_config.VIX_FILE_PREFIX_STR) and file_name_str.endswith(".csv")):
            continue
        # PARSE THE STAMP OF THE NAME
        stamp_str = file_name_str[len(vix_config.VIX_FILE_PREFIX_STR):-len(".csv")]
        stamp_ts = pd.to_datetime(stamp_str, format=name_format_str_in, errors="coerce")
        # SKIP A NAME WITHOUT A VALID STAMP
        if pd.isna(stamp_ts):
            continue
        # ADD THE TUPLE
        file_tuple_list.append((stamp_ts, f"{folder_path_str_in}{file_name_str}"))
    # RETURN THE SORTED TUPLES
    return sorted(file_tuple_list)

# FUNCTION: PARSE THE BARS OF A FILE
def parse_vix_bar_pdf(raw_pdf_in):
    """
    Parses raw index bars: timestamps from UTC to New York time, prices as floats, volume dropped, date parsed.

    Args:
        raw_pdf_in (pd.DataFrame): Raw rows (timestamp, open, high, low, close, volume, created_ts, date)

    Returns:
        pd.DataFrame: timestamp (New York), open, high, low, close, created_ts, date (raw column, datetime.date),
                      ny_date (New York date of the timestamp)
    """
    # COPY AND DROP REPEATED COLUMN NAMES
    bar_pdf = raw_pdf_in.loc[:, ~raw_pdf_in.columns.duplicated()].copy()
    # CONVERT THE TIMESTAMPS (UTC TO NEW YORK)
    bar_pdf["timestamp"] = pd.to_datetime(bar_pdf["timestamp"], utc=True).dt.tz_convert(ny_tz)
    # ADD THE NEW YORK DATE OF THE TIMESTAMP
    bar_pdf["ny_date"] = bar_pdf["timestamp"].dt.date
    # PARSE THE RAW DATE COLUMN
    bar_pdf["date"] = pd.to_datetime(bar_pdf["date"]).dt.date
    # CONVERT THE PRICES
    for col_str in ["open", "high", "low", "close"]:
        bar_pdf[col_str] = bar_pdf[col_str].astype(float)
    # RETURN THE BARS WITHOUT VOLUME
    return bar_pdf[["timestamp", "open", "high", "low", "close", "created_ts", "date", "ny_date"]]

# FUNCTION: CHECK THE LOADED BARS
def check_vix_bar_pdf(bar_pdf_in, cutoff_date_in, label_str_in):
    """
    Raises if a loaded row is dated after the cutoff or in the untouched window, or if a "date" differs from the New
    York date of its timestamp.

    Args:
        bar_pdf_in (pd.DataFrame): Parsed bars (date, ny_date)
        cutoff_date_in (datetime.date): Cutoff of the load
        label_str_in (str): Series label for the messages

    Returns:
        None
    """
    # COLLECT THE UNTOUCHED START
    untouched_date = pd.Timestamp(vix_config.UNTOUCHED_START_DATE_STR).date()
    # ASSERT THAT NO ROW IS AFTER THE CUTOFF OR IN THE UNTOUCHED WINDOW
    assert not (bar_pdf_in["ny_date"] > cutoff_date_in).any() and not (bar_pdf_in["date"] > cutoff_date_in).any(), f"❌ {label_str_in}: a row after the cutoff {cutoff_date_in}"
    assert not (bar_pdf_in["ny_date"] >= untouched_date).any() and not (bar_pdf_in["date"] >= untouched_date).any(), f"❌ {label_str_in}: a row in the untouched window"
    # RAISE IF A DATE DIFFERS FROM THE NEW YORK DATE OF ITS TIMESTAMP
    mismatch_count = int((bar_pdf_in["date"] != bar_pdf_in["ny_date"]).sum())
    if mismatch_count:
        raise ValueError(f"❌ {label_str_in}: {mismatch_count} rows whose date differs from the New York date of the timestamp")

# FUNCTION: READ THE DAILY BARS OF A SERIES
def read_vix_daily_pdf(series_str_in, cutoff_date_str_in, raw_path_str_in=None):
    """
    Reads the daily bars of a series up to a required cutoff (inclusive). Year files after the cutoff's year are never
    opened; rows after the cutoff are dropped immediately after parsing.

    Args:
        series_str_in (str): "vix" or "vix3m"
        cutoff_date_str_in (str): Last date kept (required; must be before 2026-05-14)
        raw_path_str_in (str | None): Override folder (tests)

    Returns:
        pd.DataFrame: timestamp (midnight New York, a label), open, high, low, close, created_ts, date; one row per date
    """
    # CHECK THE CUTOFF
    cutoff_date = check_cutoff_date(cutoff_date_str_in)
    # LIST THE YEAR FILES UP TO THE CUTOFF'S YEAR (LATER FILES ARE NEVER OPENED)
    folder_path_str = get_vix_folder_path_str(series_str_in, "daily", raw_path_str_in)
    file_path_list = [file_path_str for stamp_ts, file_path_str in get_vix_file_tuple_list(folder_path_str, "%Y") if stamp_ts.year <= cutoff_date.year]
    # LIST TO HOLD THE YEARS
    pdf_list = []
    # ITERATE OVER THE FILES
    for file_path_str in file_path_list:
        # PARSE THE FILE
        bar_pdf = parse_vix_bar_pdf(pd.read_csv(file_path_str))
        # DROP THE ROWS AFTER THE CUTOFF IMMEDIATELY
        bar_pdf = bar_pdf[(bar_pdf["ny_date"] <= cutoff_date) & (bar_pdf["date"] <= cutoff_date)]
        # ADD THE YEAR
        pdf_list.append(bar_pdf)
    # CONCATENATE AND SORT
    bar_pdf = pd.concat(pdf_list, ignore_index=True).sort_values("timestamp").reset_index(drop=True)
    # CHECK THE ROWS
    check_vix_bar_pdf(bar_pdf, cutoff_date, f"{series_str_in} daily")
    # RAISE IF A DAILY TIMESTAMP IS NOT MIDNIGHT NEW YORK
    if not (bar_pdf["timestamp"] == bar_pdf["timestamp"].dt.normalize()).all():
        raise ValueError(f"❌ {series_str_in} daily: a timestamp that is not midnight New York")
    # RAISE IF A DATE APPEARS TWICE
    if bar_pdf["date"].duplicated().any():
        raise ValueError(f"❌ {series_str_in} daily: repeated dates")
    # RETURN THE BARS
    return bar_pdf.drop(columns="ny_date")

# FUNCTION: READ THE 1-MINUTE BARS OF A SERIES
def read_vix_1min_pdf(series_str_in, cutoff_date_str_in, start_date_str_in=None, raw_path_str_in=None):
    """
    Reads the 1-minute bars of a series up to a required cutoff (inclusive). A file whose name date is after the
    cutoff is never opened.

    Args:
        series_str_in (str): "vix" or "vix3m"
        cutoff_date_str_in (str): Last session kept (required; must be before 2026-05-14)
        start_date_str_in (str | None): First session read (None = from the first file)
        raw_path_str_in (str | None): Override folder (tests)

    Returns:
        pd.DataFrame: timestamp (New York), open, high, low, close, created_ts, date; sorted by timestamp
    """
    # CHECK THE CUTOFF
    cutoff_date = check_cutoff_date(cutoff_date_str_in)
    # COLLECT THE START
    start_date = pd.Timestamp(start_date_str_in).date() if start_date_str_in is not None else None
    # LIST THE SESSION FILES UP TO THE CUTOFF (LATER FILES ARE NEVER OPENED)
    folder_path_str = get_vix_folder_path_str(series_str_in, "1min", raw_path_str_in)
    file_tuple_list = [(stamp_ts.date(), file_path_str) for stamp_ts, file_path_str in get_vix_file_tuple_list(folder_path_str, "%Y%m%d")
                       if stamp_ts.date() <= cutoff_date and (start_date is None or stamp_ts.date() >= start_date)]
    # READ THE FILES (THE NAME DATE IS KEPT TO CHECK THE ROWS)
    pdf_list = [pd.read_csv(file_path_str).assign(file_date=file_date) for file_date, file_path_str in file_tuple_list]
    # CONCATENATE AND PARSE
    raw_pdf = pd.concat(pdf_list, ignore_index=True)
    file_date_arr = raw_pdf["file_date"].to_numpy()
    bar_pdf = parse_vix_bar_pdf(raw_pdf.drop(columns="file_date"))
    # RAISE IF A ROW BELONGS TO ANOTHER DATE THAN ITS FILE
    if (bar_pdf["ny_date"].to_numpy() != file_date_arr).any():
        raise ValueError(f"❌ {series_str_in} 1-minute: rows whose New York date differs from their file's date")
    # CHECK THE ROWS
    check_vix_bar_pdf(bar_pdf, cutoff_date, f"{series_str_in} 1-minute")
    # RETURN THE SORTED BARS
    return bar_pdf.drop(columns="ny_date").sort_values("timestamp").reset_index(drop=True)

# FUNCTION: GET THE PREVIOUS DAILY CLOSE OF EVERY SPY SESSION
def get_vix_prev_value_pdf(session_date_list_in, vix_daily_pdf_in, series_start_date_str_in, stale_max_in=vix_config.STALE_MAX_SESSIONS):
    """
    Returns, for every SPY session t, the close of the latest daily bar dated strictly before t, and its status.

    Args:
        session_date_list_in (list): SPY session dates in order (datetime.date)
        vix_daily_pdf_in (pd.DataFrame): Daily bars of the series (date, close)
        series_start_date_str_in (str): First date of the series (sessions on or before it have no previous bar)
        stale_max_in (int): Largest accepted lag in SPY sessions between the bar's date and the previous SPY session

    Returns:
        pd.DataFrame: value, bar_date, lag_sessions, status ("ok", "stale", "missing", "before_start")
    """
    # CONVERT THE DATES
    session_date_arr = pd.to_datetime(pd.Series(session_date_list_in)).to_numpy(dtype="datetime64[D]")
    daily_pdf = vix_daily_pdf_in.sort_values("date")
    bar_date_arr = pd.to_datetime(daily_pdf["date"]).to_numpy(dtype="datetime64[D]")
    close_arr = daily_pdf["close"].to_numpy(dtype=float)
    # FIND THE LATEST BAR DATED STRICTLY BEFORE EACH SESSION
    bar_pos_arr = np.searchsorted(bar_date_arr, session_date_arr, side="left") - 1
    found_bool_arr = bar_pos_arr >= 0
    safe_pos_arr = np.where(found_bool_arr, bar_pos_arr, 0)
    # FIND THE LATEST SPY SESSION ON OR BEFORE THE BAR'S DATE
    spy_pos_arr = np.searchsorted(session_date_arr, bar_date_arr[safe_pos_arr], side="right") - 1
    # CALCULATE THE LAG BETWEEN THE BAR'S SESSION AND THE PREVIOUS SPY SESSION
    lag_arr = (np.arange(len(session_date_arr)) - 1) - spy_pos_arr
    # CLASSIFY THE SESSIONS
    before_start_bool_arr = session_date_arr <= np.datetime64(pd.Timestamp(series_start_date_str_in).date(), "D")
    stale_bool_arr = found_bool_arr & (lag_arr > stale_max_in)
    status_arr = np.where(before_start_bool_arr, "before_start", np.where(~found_bool_arr, "missing", np.where(stale_bool_arr, "stale", "ok")))
    # RETURN THE VALUES (NaN UNLESS "ok")
    return pd.DataFrame({
        "value": np.where(status_arr == "ok", close_arr[safe_pos_arr], np.nan),
        "bar_date": np.where(found_bool_arr, bar_date_arr[safe_pos_arr], np.datetime64("NaT")),
        "lag_sessions": np.where(found_bool_arr, lag_arr, -1),
        "status": status_arr,
    })

# FUNCTION: GET THE LAST 1-MINUTE CLOSE BEFORE EVERY DECISION
def get_vix_intraday_value_pdf(session_date_list_in, decision_ts_list_in, vix_1min_pdf_in, prev_value_arr_in, series_start_date_str_in,
                               lag_minutes_in=vix_config.INTRADAY_MIN_LAG_MINUTES):
    """
    Returns, for every SPY session t, the close of the last 1-minute bar of date t labelled at most decision_ts(t) -
    lag minutes; the previous daily close when the session has no such bar (fallback).

    Args:
        session_date_list_in (list): SPY session dates in order (datetime.date)
        decision_ts_list_in (list): Decision bar timestamps of the sessions (New York)
        vix_1min_pdf_in (pd.DataFrame): 1-minute bars of the series (timestamp, close, date)
        prev_value_arr_in (np.ndarray): _prev values of the sessions (used by the fallback)
        series_start_date_str_in (str): First date of the series (sessions before it are NaN, "before_start")
        lag_minutes_in (int): Minimum lag of the bar label before the decision bar (minutes)

    Returns:
        pd.DataFrame: value, bar_ts, source ("bar", "fallback", "before_start")
    """
    # BUILD THE SESSION KEYS (UTC NANOSECONDS OF THE LAST ALLOWED LABEL, DAY NUMBER)
    allowed_ts_index = pd.DatetimeIndex(decision_ts_list_in).tz_convert("UTC") - pd.Timedelta(minutes=lag_minutes_in)
    session_pdf = pd.DataFrame({"row": np.arange(len(session_date_list_in)), "allowed_ts": allowed_ts_index,
                                "day": pd.to_datetime(pd.Series(session_date_list_in)).to_numpy(dtype="datetime64[D]").astype(np.int64)})
    # BUILD THE BAR KEYS
    bar_pdf = pd.DataFrame({"bar_ts": pd.DatetimeIndex(vix_1min_pdf_in["timestamp"]).tz_convert("UTC"),
                            "day": pd.to_datetime(vix_1min_pdf_in["date"]).to_numpy(dtype="datetime64[D]").astype(np.int64),
                            "bar_close": vix_1min_pdf_in["close"].to_numpy(dtype=float)})
    # FIND THE LAST BAR OF THE SAME DATE LABELLED AT MOST THE ALLOWED TIME
    merged_pdf = pd.merge_asof(session_pdf.sort_values("allowed_ts"), bar_pdf.sort_values("bar_ts"), left_on="allowed_ts", right_on="bar_ts",
                               by="day", direction="backward").sort_values("row").reset_index(drop=True)
    # CLASSIFY THE SESSIONS
    before_start_bool_arr = pd.to_datetime(pd.Series(session_date_list_in)).dt.date.to_numpy() < pd.Timestamp(series_start_date_str_in).date()
    found_bool_arr = merged_pdf["bar_close"].notna().to_numpy()
    source_arr = np.where(before_start_bool_arr, "before_start", np.where(found_bool_arr, "bar", "fallback"))
    # COLLECT THE VALUES
    value_arr = np.where(source_arr == "bar", merged_pdf["bar_close"].to_numpy(), np.where(source_arr == "fallback", prev_value_arr_in, np.nan))
    # RETURN THE DATAFRAME (BAR LABEL IN NEW YORK TIME)
    return pd.DataFrame({"value": value_arr, "bar_ts": pd.DatetimeIndex(merged_pdf["bar_ts"]).tz_convert(ny_tz).where(source_arr == "bar"), "source": source_arr})

# FUNCTION: GET THE VIX TABLE OF THE SPY SESSIONS
def get_vix_table_pdf(daily_pdf_in, daily_bar_pdf_dict_in, minute_bar_pdf_dict_in=None, start_date_dict_in=vix_config.SERIES_START_DATE_DICT,
                      stale_max_in=vix_config.STALE_MAX_SESSIONS, lag_minutes_in=vix_config.INTRADAY_MIN_LAG_MINUTES):
    """
    Builds one row per SPY session with the _prev (and, if 1-minute bars are given, _intraday) value of each series.

    Args:
        daily_pdf_in (pd.DataFrame): so.features.daily_features.get_daily_feature_pdf output (session_idx, date, decision_ts)
        daily_bar_pdf_dict_in (dict): {series: daily bars}
        minute_bar_pdf_dict_in (dict | None): {series: 1-minute bars}; None = no _intraday columns
        start_date_dict_in (dict): {series: first date of the series}
        stale_max_in (int): Staleness limit of the previous daily close (SPY sessions)
        lag_minutes_in (int): Minimum lag of an intraday bar label before the decision bar (minutes)

    Returns:
        pd.DataFrame: session_idx, date, decision_ts, and per series s: s_prev, s_prev_date, s_prev_lag, s_prev_status
                      [, s_intraday, s_intraday_ts, s_intraday_source]
    """
    # START FROM THE SESSION KEYS
    table_pdf = daily_pdf_in[["session_idx", "date", "decision_ts"]].reset_index(drop=True).copy()
    session_date_list = table_pdf["date"].tolist()
    # ITERATE OVER THE SERIES
    for series_str, daily_bar_pdf in daily_bar_pdf_dict_in.items():
        # ADD THE PREVIOUS DAILY CLOSE
        prev_pdf = get_vix_prev_value_pdf(session_date_list, daily_bar_pdf, start_date_dict_in[series_str], stale_max_in)
        table_pdf[f"{series_str}_prev"] = prev_pdf["value"].to_numpy()
        table_pdf[f"{series_str}_prev_date"] = prev_pdf["bar_date"].to_numpy()
        table_pdf[f"{series_str}_prev_lag"] = prev_pdf["lag_sessions"].to_numpy()
        table_pdf[f"{series_str}_prev_status"] = prev_pdf["status"].to_numpy()
        # IF 1-MINUTE BARS ARE GIVEN FOR THE SERIES
        if minute_bar_pdf_dict_in is not None and series_str in minute_bar_pdf_dict_in:
            # ADD THE LAST 1-MINUTE CLOSE BEFORE THE DECISION
            intraday_pdf = get_vix_intraday_value_pdf(session_date_list, table_pdf["decision_ts"].tolist(), minute_bar_pdf_dict_in[series_str],
                                                      prev_pdf["value"].to_numpy(), start_date_dict_in[series_str], lag_minutes_in)
            table_pdf[f"{series_str}_intraday"] = intraday_pdf["value"].to_numpy()
            table_pdf[f"{series_str}_intraday_ts"] = intraday_pdf["bar_ts"].array
            table_pdf[f"{series_str}_intraday_source"] = intraday_pdf["source"].to_numpy()
    # RETURN THE TABLE
    return table_pdf

# FUNCTION: GET THE VIX FEATURE COLUMNS OF A VARIANT
def get_vix_feature_col_list(variant_str_in):
    """
    Returns the six VIX feature column names of a timing variant.

    Args:
        variant_str_in (str): "prev" or "intraday"

    Returns:
        list[str]: [vix_level_v, vix_pct250_v, vix_chg5_v, vix_fade_v, vix_term_v, vrp_v]
    """
    # RETURN THE NAMES
    return [f"{base_str}_{variant_str_in}" for base_str in vix_config.VIX_FEATURE_BASE_STR_LIST]

# FUNCTION: GET THE SHARE OF THE PREVIOUS VALUES BELOW TODAY
def get_trailing_percentile_arr(value_arr_in, window_in):
    """
    Returns, for every row t, the share of x_(t-window) ... x_(t-1) strictly below x_t (NaN unless all exist).

    Args:
        value_arr_in (np.ndarray): Values in session order
        window_in (int): Number of previous values

    Returns:
        np.ndarray: Shares in [0, 1] or NaN
    """
    # PREPARE THE OUTPUT
    value_arr = np.asarray(value_arr_in, dtype=float)
    result_arr = np.full(len(value_arr), np.nan)
    # IF THERE ARE NOT ENOUGH ROWS
    if len(value_arr) <= window_in:
        return result_arr
    # BUILD THE WINDOWS OF THE PREVIOUS VALUES (WINDOW i ENDS AT ROW i + window - 1; ITS "TODAY" IS ROW i + window)
    window_arr = np.lib.stride_tricks.sliding_window_view(value_arr[:-1], window_in)
    today_arr = value_arr[window_in:]
    # KEEP THE ROWS WHERE EVERY VALUE EXISTS
    valid_bool_arr = ~np.isnan(window_arr).any(axis=1) & ~np.isnan(today_arr)
    # CALCULATE THE SHARES
    result_arr[window_in:] = np.where(valid_bool_arr, (window_arr < today_arr[:, None]).mean(axis=1), np.nan)
    # RETURN THE SHARES
    return result_arr

# FUNCTION: GET THE VIX FEATURES OF A VARIANT
def get_vix_feature_pdf(vix_table_pdf_in, daily_volatility_arr_in, variant_str_in, pct_window_in=vix_config.PCT_WINDOW_SESSIONS,
                        chg_sessions_in=vix_config.CHG_SESSIONS, fade_window_in=vix_config.FADE_WINDOW_SESSIONS,
                        annualization_in=vix_config.ANNUALIZATION_SESSIONS):
    """
    Computes the six VIX features of a timing variant for every row of the VIX table (rows in session order).

    Args:
        vix_table_pdf_in (pd.DataFrame): get_vix_table_pdf output (vix_<v>, vix3m_<v>)
        daily_volatility_arr_in (np.ndarray): Trailing daily volatility of the same rows (daily_features)
        variant_str_in (str): "prev" or "intraday"
        pct_window_in (int): Previous values of the percentile
        chg_sessions_in (int): Sessions of the log change
        fade_window_in (int): Values of the running maximum (including today)
        annualization_in (int): Sessions per year of the realized variance

    Returns:
        pd.DataFrame: The six feature columns of the variant (same index as the table)
    """
    # COLLECT THE VALUES
    x_series = vix_table_pdf_in[f"vix_{variant_str_in}"].astype(float)
    m_series = vix_table_pdf_in[f"vix3m_{variant_str_in}"].astype(float)
    level_col, pct_col, chg_col, fade_col, term_col, vrp_col = get_vix_feature_col_list(variant_str_in)
    # BUILD THE FEATURES
    feature_pdf = pd.DataFrame(index=vix_table_pdf_in.index)
    feature_pdf[level_col] = x_series
    feature_pdf[pct_col] = get_trailing_percentile_arr(x_series.to_numpy(), pct_window_in)
    feature_pdf[chg_col] = np.log(x_series / x_series.shift(chg_sessions_in))
    feature_pdf[fade_col] = x_series / x_series.rolling(fade_window_in, min_periods=fade_window_in).max() - 1
    feature_pdf[term_col] = x_series / m_series
    feature_pdf[vrp_col] = (x_series / 100) ** 2 - (np.asarray(daily_volatility_arr_in, dtype=float) * np.sqrt(annualization_in)) ** 2
    # RETURN THE FEATURES
    return feature_pdf

# FUNCTION: GET THE COVERAGE OF THE VIX TABLE PER YEAR
def get_vix_coverage_pdf(vix_table_pdf_in):
    """
    Counts per calendar year and series: sessions, _prev status (ok, of which lagged by 1+ sessions; stale; missing;
    before_start) and, if present, the _intraday sources (bar, fallback).

    Args:
        vix_table_pdf_in (pd.DataFrame): get_vix_table_pdf output

    Returns:
        pd.DataFrame: One row per (series, year)
    """
    # COLLECT THE YEAR OF EVERY SESSION
    year_arr = pd.to_datetime(vix_table_pdf_in["date"]).dt.year.to_numpy()
    # LIST TO HOLD THE ROWS
    row_list = []
    # ITERATE OVER THE SERIES PRESENT IN THE TABLE
    for series_str in [s for s in vix_config.VIX_SERIES_STR_LIST if f"{s}_prev_status" in vix_table_pdf_in.columns]:
        # ITERATE OVER THE YEARS
        for year_int in sorted(set(year_arr)):
            # SELECT THE YEAR
            year_pdf = vix_table_pdf_in[year_arr == year_int]
            status_arr = year_pdf[f"{series_str}_prev_status"].to_numpy()
            # BUILD THE ROW
            row_dict = {"series": series_str, "year": int(year_int), "session_count": len(year_pdf),
                        "prev_ok": int((status_arr == "ok").sum()),
                        "prev_ok_lagged": int(((status_arr == "ok") & (year_pdf[f"{series_str}_prev_lag"].to_numpy() > 0)).sum()),
                        "prev_stale": int((status_arr == "stale").sum()), "prev_missing": int((status_arr == "missing").sum()),
                        "prev_before_start": int((status_arr == "before_start").sum())}
            # IF THE INTRADAY SOURCES ARE PRESENT
            if f"{series_str}_intraday_source" in year_pdf.columns:
                source_arr = year_pdf[f"{series_str}_intraday_source"].to_numpy()
                row_dict["intraday_bar"] = int((source_arr == "bar").sum())
                row_dict["intraday_fallback"] = int((source_arr == "fallback").sum())
            # ADD THE ROW
            row_list.append(row_dict)
    # RETURN THE COUNTS
    return pd.DataFrame(row_list)

# FUNCTION: LOAD THE VIX DATA AND BUILD THE FEATURES OF THE SPY SESSIONS
def get_vix_daily_feature_dict(daily_pdf_in, cutoff_date_str_in, variant_str_list_in=vix_config.VARIANT_STR_LIST, raw_path_dict_in=None):
    """
    Loads the VIX and VIX3M bars up to the cutoff (the same cutoff as the SPY data of the caller) and returns the VIX
    table, the features of every requested variant joined to the session keys, and the coverage counts.

    Args:
        daily_pdf_in (pd.DataFrame): Daily SPY table (session_idx, date, decision_ts, daily_volatility)
        cutoff_date_str_in (str): Cutoff of every VIX load (required; must be before 2026-05-14 and not before the last SPY session)
        variant_str_list_in (list[str]): Variants to build ("intraday" loads the 1-minute bars)
        raw_path_dict_in (dict | None): {(series, bar): folder} overrides (tests)

    Returns:
        dict: {"vix_table_pdf", "feature_pdf" (session_idx, date + the feature columns), "coverage_pdf", "last_date_dict"}
    """
    # CHECK THE CUTOFF AND THE SPY TABLE
    cutoff_date = check_cutoff_date(cutoff_date_str_in)
    assert max(daily_pdf_in["date"]) <= cutoff_date, "❌ The SPY table runs past the VIX cutoff"
    # COLLECT THE OVERRIDES
    raw_path_dict = raw_path_dict_in or {}
    # LOAD THE DAILY BARS
    daily_bar_pdf_dict = {s: read_vix_daily_pdf(s, cutoff_date_str_in, raw_path_dict.get((s, "daily"))) for s in vix_config.VIX_SERIES_STR_LIST}
    # LOAD THE 1-MINUTE BARS IF THE INTRADAY VARIANT IS REQUESTED
    minute_bar_pdf_dict = None
    if "intraday" in variant_str_list_in:
        minute_bar_pdf_dict = {s: read_vix_1min_pdf(s, cutoff_date_str_in, str(min(daily_pdf_in["date"])), raw_path_dict.get((s, "1min"))) for s in vix_config.VIX_SERIES_STR_LIST}
    # BUILD THE TABLE
    vix_table_pdf = get_vix_table_pdf(daily_pdf_in, daily_bar_pdf_dict, minute_bar_pdf_dict)
    # BUILD THE FEATURES OF EVERY VARIANT
    feature_pdf = vix_table_pdf[["session_idx", "date"]].copy()
    for variant_str in variant_str_list_in:
        feature_pdf = pd.concat([feature_pdf, get_vix_feature_pdf(vix_table_pdf, daily_pdf_in["daily_volatility"].to_numpy(), variant_str)], axis=1)
    # COLLECT THE LAST DATE LOADED OF EVERY SERIES AND BAR SIZE
    last_date_dict = {f"{s}_daily": max(daily_bar_pdf_dict[s]["date"]) for s in daily_bar_pdf_dict}
    if minute_bar_pdf_dict is not None:
        last_date_dict.update({f"{s}_1min": max(minute_bar_pdf_dict[s]["date"]) for s in minute_bar_pdf_dict})
    # RETURN THE DICTIONARY
    return {"vix_table_pdf": vix_table_pdf, "feature_pdf": feature_pdf, "coverage_pdf": get_vix_coverage_pdf(vix_table_pdf),
            "last_date_dict": last_date_dict, "daily_bar_pdf_dict": daily_bar_pdf_dict, "minute_bar_pdf_dict": minute_bar_pdf_dict}
