import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION (THE EXTREMA CONFIRMATION LAG)
from so import config

"""
Point-in-Time Data (Nicolas, 2026-10-11)

Every value has an available_ts: the moment it could have been known. A decision at decision_ts may use only rows with
available_ts <= decision_ts. Designs in the holdout runner read data only through DataContext, so the runner's
whole-session cut and its perturbation check cover every registered source. Labels may look forward; a model trained
at time t uses only rows whose label_known_ts is before t.

Timestamp convention, observed on the raw files (not assumed):

    SPY 1-minute, 2005-01-03: 390 bars, first label 09:30, last label 15:59. A regular session is 09:30-16:00, which is
    390 minutes. An end-of-bar label would run 09:31-16:00.
    SPY 1-minute, 2005-11-25 (half day, early close 13:00): 210 bars, first 09:30, last 12:59. 09:30 through 12:59 is
    210 minutes. An end-of-bar label would finish at 13:00.
    So the SPY label is the bar START. The close of the bar labelled 15:58 is knowable at 15:59:00. That is the decision
    moment: so.features.daily_features stores the 15:58 label as decision_ts and fills at the open of the next bar
    (15:59). available_ts of a 1-minute bar is label + 1 minute.

    VIX 1-minute, 2005-10-03: 404 bars, first 09:31, last 16:14. VIX3M 1-minute, 2009-08-12: 389 bars, first 09:31, last
    15:59. The same start-of-bar reading fits a session that begins at 09:31 (docs/VIX_DATA_INVENTORY_2026-10-08.md:
    the label convention is not proven, and the probe saw about a one-minute delay). The later, conservative rule is
    the same one: available_ts = label + 1 minute. A last label of 16:14 is then knowable at 16:15.

    VIX and VIX3M daily: the timestamp is midnight New York of the date (observed 2005-10-03 00:00:00-04:00), a label,
    not a trade time. The inventory states the daily close is known at 16:15 New York. available_ts is that date at
    16:15 America/New_York, which is after the 15:58 decision of the same session.

Derived caches (pipeline steps 02-04 and 06) are feature rows. A row's available_ts is the latest available_ts of the
bars it is computed from. The step-01 snapshot loop only sees bars up to the current bar, and a swing is confirmed
config.PA_EXTREMA_ORDER bars later (add_minima_col needs `order` bars on each side; the snapshot count increases only
once those bars exist). A swing stored on its own bar is therefore knowable only at the end of the confirmation bar.
TSCTX states that the row of bar t uses only bars <= t. TSDAY features are the decision bar of the session; the
forward-return columns on that row are labels and are not served on the feature path. TSDAY_FWD is those same files
as a label: label_known_ts is the end of the session LABEL_HORIZON_SESSIONS later (its close is the exit); unfinished rows (no
horizon session) are dropped; a redacted blank y_fwd stays as a missing label. TSBAR is a label: label_known_ts
is the end of the bar where TP or SL was hit, or the end of the horizon. The files store that bar as exit_bar_count
on each distance cell (minute bars from entry_ts). The row clock is the latest of those bars. An unresolved cell,
or an exit bar that is not in the loaded minute bars, leaves the row unfinished.
"""

# DEFINE THE NEW YORK TIME ZONE USED ON EVERY TIMESTAMP
NY_TZ_STR = "America/New_York"
# DEFINE THE COLUMNS A PERTURBATION MUST NOT REWRITE (ROW IDENTITY)
PROTECTED_COLUMN_SET = {"timestamp", "available_ts", "label_known_ts", "date", "decision_ts"}
# DEFINE HOW LONG A 1-MINUTE BAR TAKES TO BECOME KNOWABLE AFTER ITS START LABEL
MINUTE_BAR_TIMEDELTA = pd.Timedelta(minutes=1)

"""
Direct Reads While The Runner Is Inside A Design
"""

# THE RUNNER SETS THIS AFTER IT HAS LOADED, SO A DESIGN CANNOT OPEN A RAW FILE ITSELF
_DIRECT_READ_BLOCKED_BOOL = False

# FUNCTION: BLOCK OR ALLOW A DIRECT LOADER CALL
def set_direct_read_blocked_bool(blocked_bool_in):
    """
    Sets the runner-scope flag. While it is set, the raw loaders, the VIX loaders and the cache readers raise.

    Args:
        blocked_bool_in (bool): True while a design replay is running

    Returns:
        None
    """
    # STORE THE FLAG FOR THE LOADERS
    global _DIRECT_READ_BLOCKED_BOOL
    _DIRECT_READ_BLOCKED_BOOL = bool(blocked_bool_in)

# FUNCTION: RAISE IF A DESIGN IS READING AROUND THE CONTEXT
def raise_if_direct_read_blocked():
    """
    Raises when the holdout runner has handed data to a design and the design calls a loader itself.

    Args:
        None

    Returns:
        None
    """
    # RAISE ONLY WHILE THE RUNNER HAS BLOCKED DIRECT READS
    if _DIRECT_READ_BLOCKED_BOOL:
        raise ValueError("read data through the DataContext")

"""
Clocks
"""

# FUNCTION: PUT A TIMESTAMP IN NEW YORK TIME
def get_ny_timestamp(timestamp_in):
    """
    Returns a New York timestamp. A naive timestamp is read as New York wall time.

    Args:
        timestamp_in (datetime-like): Timestamp or date

    Returns:
        pd.Timestamp: Timezone-aware New York timestamp
    """
    # PARSE AND ATTACH NEW YORK
    timestamp = pd.Timestamp(timestamp_in)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize(NY_TZ_STR)
    return timestamp.tz_convert(NY_TZ_STR)

# FUNCTION: WHEN A 1-MINUTE BAR CAN BE KNOWN
def get_minute_bar_available_ts(label_ts_in):
    """
    The bar label is the start. The bar can be known when it ends, one minute later.

    Args:
        label_ts_in (datetime-like): Bar-start label

    Returns:
        pd.Timestamp: available_ts
    """
    # THE CLOSE OF THE LABELLED MINUTE
    return get_ny_timestamp(label_ts_in) + MINUTE_BAR_TIMEDELTA

# FUNCTION: WHEN THE DECISION BAR CAN BE KNOWN
def get_decision_ts(decision_bar_label_ts_in):
    """
    The decision moment is the end of the decision bar. On a full day that bar is labelled 15:58, so the moment is
    15:59:00. so.features.daily_features uses that same bar and fills at the open of the next one.

    Args:
        decision_bar_label_ts_in (datetime-like): Start label of the decision bar

    Returns:
        pd.Timestamp: decision_ts
    """
    # THE END OF THE DECISION BAR
    return get_minute_bar_available_ts(decision_bar_label_ts_in)

# FUNCTION: WHEN A VIX-FAMILY DAILY BAR CAN BE KNOWN
def get_vix_daily_available_ts(date_in):
    """
    The daily timestamp is midnight of the date. The close is knowable at 16:15 New York that date.

    Args:
        date_in (datetime-like): Bar date or midnight timestamp

    Returns:
        pd.Timestamp: available_ts at 16:15 America/New_York
    """
    # TAKE THE NEW YORK CALENDAR DATE AND SET 16:15
    day = get_ny_timestamp(date_in)
    return pd.Timestamp(year=day.year, month=day.month, day=day.day, hour=16, minute=15, tz=NY_TZ_STR)

# FUNCTION: WHEN A DERIVED ROW COMPUTED FROM THESE BARS CAN BE KNOWN
def get_derived_available_ts(input_label_ts_list_in):
    """
    The latest available_ts among the input bars. A row computed from bars up to t is knowable when the last of those
    bars ends.

    Args:
        input_label_ts_list_in (list): Bar-start labels the row was computed from

    Returns:
        pd.Timestamp: available_ts
    """
    # THE LATEST BAR END
    return max(get_minute_bar_available_ts(label_ts) for label_ts in input_label_ts_list_in)

# FUNCTION: WHEN A SWING CONFIRMED K BARS LATER CAN BE KNOWN
def get_swing_available_ts(swing_label_ts_in, confirm_bar_count_in=config.PA_EXTREMA_ORDER):
    """
    add_minima_col / add_maxima_col mark a swing on its own bar, but the mark uses `order` bars after it
    (config.PA_EXTREMA_ORDER, 3). The snapshot count increases only once those bars exist. The swing is knowable at
    the end of the confirmation bar, not at the end of the swing bar.

    Args:
        swing_label_ts_in (datetime-like): Start label of the swing bar
        confirm_bar_count_in (int): Bars after the swing before it is confirmed

    Returns:
        pd.Timestamp: available_ts of the confirmation bar
    """
    # THE CONFIRMATION BAR'S OWN START, THEN ITS END
    confirmation_label_ts = get_ny_timestamp(swing_label_ts_in) + pd.Timedelta(minutes=int(confirm_bar_count_in))
    return get_minute_bar_available_ts(confirmation_label_ts)

"""
Availability Rules
"""

# FUNCTION: ADD available_ts TO 1-MINUTE BARS
def add_minute_source_available_ts_pdf(bar_pdf_in):
    """
    Copies a 1-minute frame and sets available_ts to one minute after each bar-start label.

    Args:
        bar_pdf_in (pd.DataFrame): Rows with a timestamp column (the bar start)

    Returns:
        pd.DataFrame: Copy with available_ts
    """
    # COPY AND STAMP EACH BAR AT ITS END
    stamped_pdf = bar_pdf_in.copy()
    label_series = pd.to_datetime(stamped_pdf["timestamp"])
    if label_series.dt.tz is None:
        label_series = label_series.dt.tz_localize(NY_TZ_STR)
    else:
        label_series = label_series.dt.tz_convert(NY_TZ_STR)
    stamped_pdf["available_ts"] = label_series + MINUTE_BAR_TIMEDELTA
    return stamped_pdf

# FUNCTION: ADD available_ts TO VIX-FAMILY DAILY BARS
def add_vix_daily_available_ts_pdf(bar_pdf_in):
    """
    Copies a daily frame and sets available_ts to 16:15 New York on the bar date.

    Args:
        bar_pdf_in (pd.DataFrame): Rows with a timestamp or a date column

    Returns:
        pd.DataFrame: Copy with available_ts
    """
    # THE DATE COLUMN WINS; OTHERWISE THE MIDNIGHT TIMESTAMP
    stamped_pdf = bar_pdf_in.copy()
    date_series = stamped_pdf["date"] if "date" in stamped_pdf.columns else stamped_pdf["timestamp"]
    day_series = pd.to_datetime(date_series)
    if getattr(day_series.dt, "tz", None) is not None:
        day_series = day_series.dt.tz_convert(NY_TZ_STR).dt.tz_localize(None)
    clock_series = pd.to_datetime(day_series.dt.strftime("%Y-%m-%d") + " 16:15")
    stamped_pdf["available_ts"] = clock_series.dt.tz_localize(NY_TZ_STR)
    return stamped_pdf

# FUNCTION: ADD available_ts TO A DERIVED CACHE ROW
def add_cache_available_ts_pdf(cache_pdf_in):
    """
    Copies a derived frame. A decision_ts column (TSDAY) is the decision-bar label, so available_ts is the end of that
    bar. A confirm_lag_bars column (a swing stored on its own bar) waits for confirmation. Otherwise the row timestamp
    is the snapshot bar, which is already the latest input bar, and available_ts is the end of that bar.

    Args:
        cache_pdf_in (pd.DataFrame): Derived rows

    Returns:
        pd.DataFrame: Copy with available_ts
    """
    # COPY FIRST
    stamped_pdf = cache_pdf_in.copy()
    # TSDAY: THE DECISION BAR IS THE LATEST BAR THE FEATURES USE
    if "decision_ts" in stamped_pdf.columns:
        stamped_pdf["available_ts"] = [get_decision_ts(label_ts) for label_ts in stamped_pdf["decision_ts"]]
        return stamped_pdf
    # A SWING STORED ON ITS OWN BAR IS KNOWABLE ONLY AFTER CONFIRMATION
    if "confirm_lag_bars" in stamped_pdf.columns:
        stamped_pdf["available_ts"] = [get_swing_available_ts(label_ts, lag) for label_ts, lag in zip(stamped_pdf["timestamp"], stamped_pdf["confirm_lag_bars"])]
        return stamped_pdf
    # THE SNAPSHOT TIMESTAMP IS THE LATEST INPUT BAR
    if "timestamp" not in stamped_pdf.columns:
        raise ValueError("A derived row needs decision_ts or timestamp so its available_ts can be set.")
    stamped_pdf["available_ts"] = [get_minute_bar_available_ts(label_ts) for label_ts in stamped_pdf["timestamp"]]
    return stamped_pdf

# COLUMNS THAT ARE NOT A DISTANCE CELL
_TSBAR_META_COLUMN_SET = {"decision_ts", "entry_ts", "entry_price", "horizon_complete", "rr_ratio", "date", "timestamp",
                          "available_ts", "label_known_ts", "exit_ts"}

# FUNCTION: THE LATEST STORED EXIT, IN BARS FROM THE ENTRY BAR
def get_tsbar_latest_exit_count_arr(label_pdf_in):
    """
    Reads every distance cell ("exit_bar_count|exit_price|exit_reason"). The row's count is the latest exit. Any
    unresolved cell (a missing count, a negative count, or reason NA) marks the whole row unfinished.

    Args:
        label_pdf_in (pd.DataFrame): TSBAR rows as stored

    Returns:
        tuple[np.ndarray, np.ndarray]: Exit-bar counts, and a bool per row that is True when the row is unfinished
    """
    # EVERY DISTANCE CELL ON THE ROW. A SLOWER DISTANCE CAN ONLY DELAY THE CLOCK.
    count_arr, unresolved_arr, found_bool = None, None, False
    for column_str in label_pdf_in.columns:
        if column_str in _TSBAR_META_COLUMN_SET:
            continue
        cell_series = label_pdf_in[column_str]
        sample_str = ""
        for value in cell_series:
            if pd.notna(value) and str(value) != "":
                sample_str = str(value)
                break
        if sample_str.count("|") < 2:
            continue
        split_pdf = cell_series.astype(str).str.split("|", n=2, expand=True)
        count_series = pd.to_numeric(split_pdf[0], errors="coerce")
        reason_series = split_pdf[2].astype(str)
        cell_unresolved_arr = (count_series.isna() | (count_series < 0) | reason_series.eq("NA")).to_numpy(dtype=bool)
        found_bool = True
        if count_arr is None:
            count_arr = count_series.to_numpy(dtype=float)
            unresolved_arr = cell_unresolved_arr
        else:
            count_arr = np.fmax(count_arr, count_series.to_numpy(dtype=float))
            unresolved_arr = unresolved_arr | cell_unresolved_arr
    if not found_bool:
        raise ValueError("TSBAR needs label_known_ts or exit_ts (the bar where TP or SL was hit, or the horizon end).")
    return count_arr, unresolved_arr

# FUNCTION: BAR-START LABELS IN BAR ORDER
def get_bar_label_index(timestamp_index_in):
    """
    The minute-bar start labels, sorted, in America/New_York. exit_bar_count walks this order.

    Args:
        timestamp_index_in (array-like): Bar-start labels

    Returns:
        pd.DatetimeIndex: Sorted bar starts
    """
    # SORT SO A BAR COUNT IS THE NEXT TRADING MINUTE, NOT A FILE ORDER
    label_index = pd.DatetimeIndex(pd.to_datetime(timestamp_index_in, utc=True)).tz_convert(NY_TZ_STR)
    return label_index.sort_values()

# FUNCTION: label_known_ts FROM THE STORED CELLS AND THE MINUTE BARS
def get_tsbar_cell_label_known_ts_arr(label_pdf_in, timestamp_index_in):
    """
    The end of the latest exit bar. A row is unfinished when any cell is unresolved, the entry bar is missing, or the
    exit bar is outside the loaded minute bars. An unfinished clock is NaT, and a training mask drops that row.

    Args:
        label_pdf_in (pd.DataFrame): TSBAR rows with entry_ts and distance cells
        timestamp_index_in (array-like): SPY minute-bar start labels, in bar order

    Returns:
        list: label_known_ts per row (NaT when unfinished)
    """
    # THE EXIT BAR IS entry_ts PLUS exit_bar_count TRADING MINUTES
    if "entry_ts" not in label_pdf_in.columns:
        raise ValueError("TSBAR cells need entry_ts so the exit bar can be found.")
    count_arr, unresolved_arr = get_tsbar_latest_exit_count_arr(label_pdf_in)
    label_index = get_bar_label_index(timestamp_index_in)
    entry_index = pd.DatetimeIndex(pd.to_datetime(label_pdf_in["entry_ts"], utc=True)).tz_convert(NY_TZ_STR)
    entry_pos_arr = label_index.get_indexer(entry_index)
    row_count = len(label_pdf_in)
    ok_arr = (~unresolved_arr) & (entry_pos_arr >= 0) & np.isfinite(count_arr)
    exit_pos_arr = np.full(row_count, -1, dtype=int)
    if ok_arr.any():
        exit_pos_arr[ok_arr] = entry_pos_arr[ok_arr] + np.rint(count_arr[ok_arr]).astype(int)
    ok_arr = ok_arr & (exit_pos_arr >= 0) & (exit_pos_arr < len(label_index))
    known_list = [pd.NaT] * row_count
    if ok_arr.any():
        exit_label_index = label_index[exit_pos_arr[ok_arr]] + MINUTE_BAR_TIMEDELTA
        for slot_idx, known_ts in zip(np.flatnonzero(ok_arr), exit_label_index):
            known_list[int(slot_idx)] = pd.Timestamp(known_ts)
    return known_list

# FUNCTION: ADD label_known_ts TO BARRIER TARGETS
def add_tsbar_label_known_ts_pdf(label_pdf_in, timestamp_index_in=None):
    """
    Copies a TSBAR frame. label_known_ts is kept when the caller already set it (the hit bar or the horizon end).
    An exit_ts column is the start label of that bar, and the label is knowable at the end of the bar. Stored
    distance cells are placed on timestamp_index_in (the SPY minute bars). The row is knowable at the end of the
    latest exit bar. An unresolved cell leaves the row unfinished.

    Args:
        label_pdf_in (pd.DataFrame): Barrier rows
        timestamp_index_in (array-like | None): Bar-start labels. None loads SPY through the frame's last date.

    Returns:
        pd.DataFrame: Copy with label_known_ts and available_ts
    """
    # COPY AND RESOLVE WHEN THE LABEL COULD HAVE BEEN KNOWN
    stamped_pdf = label_pdf_in.copy()
    if "label_known_ts" in stamped_pdf.columns:
        stamped_pdf["label_known_ts"] = [get_ny_timestamp(label_ts) for label_ts in stamped_pdf["label_known_ts"]]
    elif "exit_ts" in stamped_pdf.columns:
        stamped_pdf["label_known_ts"] = [get_minute_bar_available_ts(label_ts) for label_ts in stamped_pdf["exit_ts"]]
    else:
        # THE FILES HAVE NO CLOCK COLUMN. PLACE THE STORED EXIT BAR ON THE MINUTE INDEX.
        if timestamp_index_in is None:
            if "date" in stamped_pdf.columns:
                end_date = pd.to_datetime(stamped_pdf["date"]).dt.date.max()
            else:
                end_date = pd.to_datetime(stamped_pdf["entry_ts"], utc=True).dt.tz_convert(NY_TZ_STR).dt.date.max()
            spy_pdf = get_registry_frame_pdf("SPY_1MIN", end_date)
            if spy_pdf is None or len(spy_pdf) == 0 or "timestamp" not in spy_pdf.columns:
                raise ValueError("SPY minute bars are required to place a TSBAR exit bar.")
            timestamp_index_in = spy_pdf["timestamp"]
        stamped_pdf["label_known_ts"] = get_tsbar_cell_label_known_ts_arr(stamped_pdf, timestamp_index_in)
    # THE LABEL ROW ITSELF IS KNOWABLE AT THAT SAME MOMENT
    stamped_pdf["available_ts"] = stamped_pdf["label_known_ts"]
    return stamped_pdf

# FUNCTION: ADD label_known_ts TO THE FIXED-HORIZON TSDAY LABEL
def add_tsday_fwd_label_known_ts_pdf(label_pdf_in):
    """
    Copies a TSDAY frame as a label. label_known_ts is the end of the session LABEL_HORIZON_SESSIONS
    later. The last horizon sessions have no clock and are dropped. A redacted blank y_fwd / fwd_ cell becomes a
    missing label; the row stays if it has a clock.

    Args:
        label_pdf_in (pd.DataFrame): TSDAY rows

    Returns:
        pd.DataFrame: Copy with label_known_ts and available_ts, unfinished rows dropped
    """
    # NOTHING TO STAMP
    if label_pdf_in is None or len(label_pdf_in) == 0:
        return pd.DataFrame() if label_pdf_in is None else label_pdf_in.copy()
    stamped_pdf = label_pdf_in.copy()
    # A FRAME THAT ALREADY CARRIES THE CLOCK IS NOT SHIFTED A SECOND TIME
    if "label_known_ts" in stamped_pdf.columns:
        stamped_pdf["label_known_ts"] = [pd.NaT if pd.isna(label_ts) else get_ny_timestamp(label_ts)
                                         for label_ts in stamped_pdf["label_known_ts"]]
        stamped_pdf["available_ts"] = stamped_pdf["label_known_ts"]
        keep_mask = [pd.notna(label_ts) for label_ts in stamped_pdf["label_known_ts"]]
        return stamped_pdf.loc[keep_mask].reset_index(drop=True)
    if "decision_ts" not in stamped_pdf.columns:
        raise ValueError("TSDAY_FWD needs decision_ts so the horizon clock can be placed.")
    # THE CLOCK IS THE DECISION OF SESSION i + HORIZON
    decision_list = [get_decision_ts(label_ts) for label_ts in stamped_pdf["decision_ts"]]
    horizon_int = int(config.LABEL_HORIZON_SESSIONS)
    known_list = [pd.NaT] * len(decision_list)
    for row_idx in range(max(0, len(decision_list) - horizon_int)):
        # THE LABEL SELLS AT THE CLOSE OF SESSION i + HORIZON: KNOWN AT THE END OF ITS LAST BAR, ONE MINUTE AFTER THAT
        # SESSION'S DECISION MOMENT (THE DECISION BAR IS ALWAYS THE SECOND-TO-LAST BAR; AUDIT S10, 2026-10-25)
        known_list[row_idx] = decision_list[row_idx + horizon_int] + MINUTE_BAR_TIMEDELTA
    stamped_pdf["label_known_ts"] = known_list
    stamped_pdf["available_ts"] = known_list
    # A REDACTED BLANK FORWARD COLUMN IS A MISSING LABEL, NOT A ZERO
    label_column_list = [column_str for column_str in stamped_pdf.columns if column_str.startswith("fwd_") or column_str.startswith("y_fwd")]
    for column_str in label_column_list:
        cell_series = stamped_pdf[column_str]
        if cell_series.dtype == object:
            cell_series = cell_series.replace("", np.nan).infer_objects(copy=False)
        stamped_pdf[column_str] = pd.to_numeric(cell_series, errors="coerce")
    # AN UNFINISHED ROW HAS NO CLOCK AND MUST NOT ENTER THE FEED
    keep_mask = [pd.notna(label_ts) for label_ts in stamped_pdf["label_known_ts"]]
    return stamped_pdf.loc[keep_mask].reset_index(drop=True)

# FUNCTION: KEEP A VINTAGE available_ts THAT THE ROW ALREADY CARRIES
def keep_vintage_available_ts_pdf(vintage_pdf_in):
    """
    A revised series stores each revision as its own row. The row's available_ts is when that revision was released.

    Args:
        vintage_pdf_in (pd.DataFrame): Rows that already have available_ts

    Returns:
        pd.DataFrame: Copy
    """
    # REFUSE A VINTAGE ROW WITH NO RELEASE TIME
    if "available_ts" not in vintage_pdf_in.columns:
        raise ValueError("A vintage row needs its own available_ts.")
    # NORMALIZE THE RELEASE TIME TO NEW YORK
    stamped_pdf = vintage_pdf_in.copy()
    stamped_pdf["available_ts"] = [get_ny_timestamp(label_ts) for label_ts in stamped_pdf["available_ts"]]
    return stamped_pdf

"""
Registry
"""

# EACH SOURCE: LOADER, CLOCK, AVAILABILITY, REVISION POLICY, ROLE, HOLDOUT HANDLING
SOURCE_SPEC_DICT = {
    "SPY_1MIN": {"loader": "so.core.raw_data.get_complete_ohlcv_pdf", "time_zone": NY_TZ_STR, "timestamp_convention": "bar_start",
                 "availability_func": add_minute_source_available_ts_pdf, "revision_policy": "not revised",
                 "revision_reason": "IBKR minute bars are stored as received. Bad ticks were corrected once, before research, and the files are not a revision vintage.",
                 "role": "feature", "holdout": "development boundary; runner window end"},
    "VIX_1MIN": {"loader": "so.features.vix_features.read_vix_1min_pdf", "time_zone": NY_TZ_STR, "timestamp_convention": "bar_start",
                 "availability_func": add_minute_source_available_ts_pdf, "revision_policy": "not revised",
                 "revision_reason": "IBKR index minute bars are add-only as first stored. The project does not keep a revision vintage.",
                 "role": "feature", "holdout": "development boundary; runner window end"},
    "VIX_DAILY": {"loader": "so.features.vix_features.read_vix_daily_pdf", "time_zone": NY_TZ_STR, "timestamp_convention": "midnight date label",
                  "availability_func": add_vix_daily_available_ts_pdf, "revision_policy": "not revised",
                  "revision_reason": "The daily file is the stored IBKR print. No vintage of earlier prints is kept.",
                  "role": "feature", "holdout": "development boundary; runner window end"},
    "VIX3M_1MIN": {"loader": "so.features.vix_features.read_vix_1min_pdf", "time_zone": NY_TZ_STR, "timestamp_convention": "bar_start",
                   "availability_func": add_minute_source_available_ts_pdf, "revision_policy": "not revised",
                   "revision_reason": "Same as VIX_1MIN: add-only, first stored print, no vintage.",
                   "role": "feature", "holdout": "development boundary; runner window end"},
    "VIX3M_DAILY": {"loader": "so.features.vix_features.read_vix_daily_pdf", "time_zone": NY_TZ_STR, "timestamp_convention": "midnight date label",
                    "availability_func": add_vix_daily_available_ts_pdf, "revision_policy": "not revised",
                    "revision_reason": "Same as VIX_DAILY: the stored print, no vintage.",
                    "role": "feature", "holdout": "development boundary; runner window end"},
    "TSIND": {"loader": "so.core.local_file_management.read_date_range_csv_files_from_path", "time_zone": NY_TZ_STR,
              "timestamp_convention": "snapshot bar start; extrema confirmed PA_EXTREMA_ORDER bars later",
              "availability_func": add_cache_available_ts_pdf, "revision_policy": "not revised",
              "revision_reason": "The cache is recomputed from the bars. A regeneration replaces it; it is not a vintage store.",
              "role": "feature", "holdout": "development boundary; runner window end"},
    "TSSEG": {"loader": "so.core.local_file_management.read_date_range_csv_files_from_path", "time_zone": NY_TZ_STR,
              "timestamp_convention": "snapshot bar start; a swing is on the row only after confirmation",
              "availability_func": add_cache_available_ts_pdf, "revision_policy": "not revised",
              "revision_reason": "The cache is recomputed from the bars. A regeneration replaces it; it is not a vintage store.",
              "role": "feature", "holdout": "development boundary; runner window end"},
    "TSCTX": {"loader": "so.core.local_file_management.read_date_range_csv_files_from_path", "time_zone": NY_TZ_STR,
              "timestamp_convention": "bar start; the row of bar t uses only bars <= t",
              "availability_func": add_cache_available_ts_pdf, "revision_policy": "not revised",
              "revision_reason": "The cache is recomputed from the bars. A regeneration replaces it; it is not a vintage store.",
              "role": "feature", "holdout": "development boundary; runner window end"},
    "TSDAY": {"loader": "so.core.local_file_management.read_csv_files_from_path", "time_zone": NY_TZ_STR,
              "timestamp_convention": "decision bar start (daily_features decision_ts)",
              "availability_func": add_cache_available_ts_pdf, "revision_policy": "not revised",
              "revision_reason": "The daily table is recomputed from the bars. Forward-return columns are labels and are not served here.",
              "role": "feature", "holdout": "development boundary; runner window end"},
    "TSDAY_FWD": {"loader": "so.core.local_file_management.read_csv_files_from_path", "time_zone": NY_TZ_STR,
                  "timestamp_convention": "label_known_ts is the end of session i + LABEL_HORIZON_SESSIONS (its close is the label's exit)",
                  "availability_func": add_tsday_fwd_label_known_ts_pdf, "revision_policy": "not revised",
                  "revision_reason": "The 20-session sign is a function of the bars. It is not a revised print.",
                  "role": "label", "holdout": "development boundary; runner window end"},
    "TSBAR": {"loader": "so.core.local_file_management.read_date_range_csv_files_from_path", "time_zone": NY_TZ_STR,
              "timestamp_convention": "label_known_ts is the hit bar or the horizon end",
              "availability_func": add_tsbar_label_known_ts_pdf, "revision_policy": "not revised",
              "revision_reason": "The barrier label is a function of the bars and the rule. It is not a revised print.",
              "role": "label", "holdout": "development boundary; runner window end"},
}

# FUNCTION: REGISTER A SOURCE
def register_source_dict(source_name_str_in, spec_dict_in):
    """
    Adds a source. A design cannot read a name that is not registered.

    Args:
        source_name_str_in (str): Source name
        spec_dict_in (dict): Registry fields (availability_func, revision_policy, role, and the rest)

    Returns:
        None
    """
    # REFUSE A SECOND REGISTRATION OF THE SAME NAME
    if source_name_str_in in SOURCE_SPEC_DICT:
        raise ValueError(f"{source_name_str_in} is already registered.")
    # STORE THE SPEC
    SOURCE_SPEC_DICT[source_name_str_in] = spec_dict_in

# FUNCTION: DROP A SOURCE THAT A TEST REGISTERED
def unregister_source(source_name_str_in):
    """
    Removes a source a test added. The built-in sources stay.

    Args:
        source_name_str_in (str): Source name

    Returns:
        None
    """
    # KEEP THE BUILT-IN SOURCES
    if source_name_str_in not in SOURCE_SPEC_DICT or source_name_str_in in ("SPY_1MIN", "VIX_1MIN", "VIX_DAILY", "VIX3M_1MIN", "VIX3M_DAILY", "TSIND", "TSSEG", "TSCTX", "TSDAY", "TSDAY_FWD", "TSBAR"):
        raise ValueError(f"{source_name_str_in} is not a test source.")
    # DROP THE TEST SOURCE
    del SOURCE_SPEC_DICT[source_name_str_in]

# FUNCTION: FETCH A REGISTRY ENTRY
def get_source_spec_dict(source_name_str_in):
    """
    Returns the registry entry. An unknown name raises.

    Args:
        source_name_str_in (str): Source name

    Returns:
        dict: Registry entry
    """
    # RAISE WHEN THE SOURCE WAS NEVER REGISTERED
    if source_name_str_in not in SOURCE_SPEC_DICT:
        raise ValueError(f"Unregistered source {source_name_str_in}.")
    # RETURN THE ENTRY
    return SOURCE_SPEC_DICT[source_name_str_in]

# FUNCTION: STAMP available_ts (AND label_known_ts FOR LABELS)
def add_available_ts_pdf(source_name_str_in, pdf_in):
    """
    Returns a copy of pdf_in with available_ts. A label source also carries label_known_ts.

    Args:
        source_name_str_in (str): Registered source
        pdf_in (pd.DataFrame): Rows of that source

    Returns:
        pd.DataFrame: Copy with the clock columns
    """
    # DISPATCH ON THE REGISTERED RULE
    spec_dict = get_source_spec_dict(source_name_str_in)
    if spec_dict["revision_policy"] == "vintage":
        return keep_vintage_available_ts_pdf(pdf_in)
    return spec_dict["availability_func"](pdf_in)

# FUNCTION: DROP ROWS THE HOLDOUT GUARD FORBIDS
def get_holdout_visible_pdf(stamped_pdf_in, mode_str_in, as_of_limit_ts_in):
    """
    Development mode drops rows whose available_ts falls on or after the active window start. Runner mode keeps the
    window and drops rows after as_of_limit_ts (the window end). No registered window leaves the rows unchanged.

    Args:
        stamped_pdf_in (pd.DataFrame): Rows with available_ts
        mode_str_in (str): "development" or "runner"
        as_of_limit_ts_in (datetime-like | None): Runner window end

    Returns:
        pd.DataFrame: Rows the guard allows
    """
    # READ THE REGISTRY WITHOUT REQUIRING A WINDOW
    from so.core.holdout import get_active_holdout_window_dict, get_date
    window_dict = get_active_holdout_window_dict(missing_ok_bool_in=True)
    # THE RUNNER STOPS AT THE WINDOW END IT WAS GIVEN
    if mode_str_in == "runner":
        if as_of_limit_ts_in is None:
            return stamped_pdf_in
        limit_ts = get_ny_timestamp(as_of_limit_ts_in)
        return stamped_pdf_in[stamped_pdf_in["available_ts"] <= limit_ts].copy()
    # DEVELOPMENT STOPS AT THE WINDOW START WHEN A WINDOW IS OPEN
    if window_dict is None:
        return stamped_pdf_in
    start_date = get_date(window_dict["start"])
    visible_mask = [get_ny_timestamp(ts).date() < start_date for ts in stamped_pdf_in["available_ts"]]
    return stamped_pdf_in.loc[visible_mask].copy()

# FUNCTION: KEEP THE REVISION THAT WAS KNOWN AT as_of
def get_vintage_as_of_pdf(stamped_pdf_in, key_list_in):
    """
    For each key, the row with the latest available_ts still inside the caller's filter.

    Args:
        stamped_pdf_in (pd.DataFrame): Rows already cut at as_of
        key_list_in (list): Columns that identify the observation

    Returns:
        pd.DataFrame: One row per key
    """
    # NO KEYS MEANS EVERY VISIBLE ROW STAYS
    if not key_list_in:
        return stamped_pdf_in
    # THE LAST RELEASE AT OR BEFORE as_of
    ordered_pdf = stamped_pdf_in.sort_values("available_ts")
    return ordered_pdf.groupby(list(key_list_in), as_index=False, dropna=False).tail(1).reset_index(drop=True)

# FUNCTION: ROWS KNOWABLE AT as_of
def get_as_of_pdf(source_name_str_in, as_of_ts_in, columns_in=None, pdf_in=None, mode_str_in="development", as_of_limit_ts_in=None):
    """
    Rows with available_ts <= as_of_ts. Development mode also applies the holdout boundary. pdf_in is the frame already
    in memory (the runner and the tests). Without it there is nothing to read: designs do not load files here.

    Args:
        source_name_str_in (str): Registered source
        as_of_ts_in (datetime-like): Decision or query time
        columns_in (list | None): Columns to keep
        pdf_in (pd.DataFrame | None): Rows already loaded
        mode_str_in (str): "development" or "runner"
        as_of_limit_ts_in (datetime-like | None): Runner window end

    Returns:
        pd.DataFrame: Visible rows
    """
    # AN UNREGISTERED NAME RAISES INSIDE THE STAMP
    if pdf_in is None:
        raise ValueError(f"{source_name_str_in} is not loaded. Read data through the DataContext.")
    # STAMP, CUT AT as_of, THEN APPLY THE GUARD
    stamped_pdf = add_available_ts_pdf(source_name_str_in, pdf_in)
    as_of_ts = get_ny_timestamp(as_of_ts_in)
    known_pdf = stamped_pdf[stamped_pdf["available_ts"] <= as_of_ts].copy()
    visible_pdf = get_holdout_visible_pdf(known_pdf, mode_str_in, as_of_limit_ts_in)
    # A VINTAGE COLLAPSES TO THE RELEASE KNOWN AT as_of
    spec_dict = get_source_spec_dict(source_name_str_in)
    if spec_dict["revision_policy"] == "vintage":
        visible_pdf = get_vintage_as_of_pdf(visible_pdf, spec_dict.get("vintage_key_list", []))
    # COLUMN SUBSET
    if columns_in is not None:
        visible_pdf = visible_pdf[list(columns_in)].copy()
    return visible_pdf.reset_index(drop=True)

# FUNCTION: REFUSE A FEATURE THAT WAS NOT KNOWABLE AT THE DECISION
def check_feature_available_ts(feature_pdf_in, decision_ts_series_in):
    """
    Every feature row must carry available_ts, the latest clock of its inputs, and that clock must be <= the decision.

    Args:
        feature_pdf_in (pd.DataFrame): Feature rows, one per decision
        decision_ts_series_in (Series-like): decision_ts aligned with the rows

    Returns:
        None
    """
    # THE CLOCK COLUMN IS REQUIRED
    if "available_ts" not in feature_pdf_in.columns:
        raise ValueError("feature rows have no available_ts.")
    # COMPARE EACH ROW WITH ITS OWN DECISION
    available_list = [get_ny_timestamp(ts) for ts in feature_pdf_in["available_ts"]]
    decision_list = [get_ny_timestamp(ts) for ts in decision_ts_series_in]
    if len(available_list) != len(decision_list):
        raise ValueError("available_ts and decision_ts have different lengths.")
    late_list = [available_ts > decision_ts for available_ts, decision_ts in zip(available_list, decision_list)]
    if any(late_list):
        raise ValueError("feature available_ts is later than its decision_ts.")

"""
Perturbation Of Feature Values
"""

# FUNCTION: REPLACE FEATURE VALUES THAT WERE NOT YET KNOWABLE
def get_perturbed_feature_pdf(feature_pdf_in, decision_ts_in, seed_int_in, source_name_str_in):
    """
    Copies the frame. Every value with available_ts after the cut session's decision is replaced: each column's late
    values are permuted among the late rows (seeded; a value moves to another row), and numeric columns are then
    multiplied by 1.25. A row read one step early therefore shows another row's value, so a sign or a rank changes,
    not only the level (audit B3, 2026-10-25). High and low stay consistent with open and close when those columns
    exist. Row timestamps and the row count stay.

    Args:
        feature_pdf_in (pd.DataFrame): Feature rows with available_ts
        decision_ts_in (datetime-like): End of the cut session's decision bar
        seed_int_in (int): Seed (the cut date YYYYMMDD)
        source_name_str_in (str): Source name, mixed into the seed

    Returns:
        pd.DataFrame: Perturbed copy
    """
    # COPY SO THE ORIGINAL FRAME IS UNCHANGED
    perturbed_pdf = feature_pdf_in.copy()
    if "available_ts" not in perturbed_pdf.columns or len(perturbed_pdf) == 0:
        return perturbed_pdf
    # ROWS THAT WERE NOT KNOWABLE AT THE DECISION
    decision_ts = get_ny_timestamp(decision_ts_in)
    late_mask = perturbed_pdf["available_ts"].map(get_ny_timestamp) > decision_ts
    if not bool(late_mask.any()):
        return perturbed_pdf
    # ONE STREAM PER SOURCE AND CUT
    seed_int = int(seed_int_in) + (sum(source_name_str_in.encode("utf-8")) % 10000)
    rng = np.random.default_rng(seed_int)
    late_idx = perturbed_pdf.index[late_mask]
    late_count = len(late_idx)
    # A DERANGEMENT-LIKE ORDER: A ROTATED PERMUTATION SO NO LATE ROW KEEPS ITS OWN VALUE WHEN THERE ARE TWO OR MORE
    order_arr = rng.permutation(late_count)
    if late_count >= 2:
        order_arr = np.roll(order_arr, 1)[np.argsort(order_arr)]
    # REWRITE EACH VALUE COLUMN
    for column_str in perturbed_pdf.columns:
        if column_str in PROTECTED_COLUMN_SET:
            continue
        column_series = perturbed_pdf[column_str]
        late_value_arr = column_series.loc[late_idx].to_numpy().copy()[order_arr]
        if pd.api.types.is_bool_dtype(column_series) or not pd.api.types.is_numeric_dtype(column_series):
            perturbed_pdf.loc[late_idx, column_str] = late_value_arr
            continue
        # AN INTEGER COLUMN (VOLUME, COUNTS) BECOMES FLOAT FIRST: PANDAS DID THIS SILENTLY BEFORE AND WARNS NOW
        if pd.api.types.is_integer_dtype(column_series):
            perturbed_pdf[column_str] = column_series.astype(float)
        perturbed_pdf.loc[late_idx, column_str] = late_value_arr.astype(float) * 1.25
    # KEEP A BAR'S HIGH AND LOW CONSISTENT WITH ITS OPEN AND CLOSE
    if {"open", "high", "low", "close"}.issubset(perturbed_pdf.columns):
        open_arr = perturbed_pdf.loc[late_idx, "open"].to_numpy(dtype=float)
        close_arr = perturbed_pdf.loc[late_idx, "close"].to_numpy(dtype=float)
        high_arr = perturbed_pdf.loc[late_idx, "high"].to_numpy(dtype=float)
        low_arr = perturbed_pdf.loc[late_idx, "low"].to_numpy(dtype=float)
        perturbed_pdf.loc[late_idx, "high"] = np.maximum(high_arr, np.maximum(open_arr, close_arr))
        perturbed_pdf.loc[late_idx, "low"] = np.minimum(low_arr, np.minimum(open_arr, close_arr))
    return perturbed_pdf

# FUNCTION: BUILD THE SPY_1MIN FRAME FROM THE RUNNER'S BAR ARRAYS
def get_spy_frame_pdf(ohlcv_array_dict_in):
    """
    The runner keeps the SPY arrays. This frame is the same bars, registered as SPY_1MIN.

    Args:
        ohlcv_array_dict_in (dict): Bar arrays (timestamp_index, open_arr, high_arr, low_arr, close_arr)

    Returns:
        pd.DataFrame: SPY_1MIN rows with available_ts
    """
    # ONE ROW PER BAR, THEN THE 1-MINUTE RULE
    bar_pdf = pd.DataFrame({"timestamp": ohlcv_array_dict_in["timestamp_index"], "open": ohlcv_array_dict_in["open_arr"],
                            "high": ohlcv_array_dict_in["high_arr"], "low": ohlcv_array_dict_in["low_arr"],
                            "close": ohlcv_array_dict_in["close_arr"]})
    return add_available_ts_pdf("SPY_1MIN", bar_pdf)

# FUNCTION: DECISION MOMENT AND SESSION-END MOMENT OF A CUT
def get_cut_clock_dict(ohlcv_array_dict_in, cut_date_in):
    """
    decision_ts is the end of the cut session's decision bar. session_end_ts is the end of its last bar.

    Args:
        ohlcv_array_dict_in (dict): Bar arrays
        cut_date_in (datetime.date): Cut session

    Returns:
        dict: decision_ts, session_end_ts
    """
    # IMPORT THE DECISION INDEX HERE SO THIS MODULE DOES NOT IMPORT IT AT LOAD
    from so.features.daily_features import get_session_decision_idx_dict
    # FIND THE CUT SESSION
    session_day_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    cut_day = pd.Timestamp(cut_date_in).date()
    last_idx = max(idx for idx, session_day in enumerate(session_day_list) if session_day <= cut_day)
    decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][last_idx])
    end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][last_idx])
    # BOTH CLOCKS ARE BAR ENDS
    return {"decision_ts": get_minute_bar_available_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx]),
            "session_end_ts": get_minute_bar_available_ts(ohlcv_array_dict_in["timestamp_index"][end_idx])}

"""
The One Door
"""

# FUNCTION: THE POINT-IN-TIME CONTEXT
class DataContext:
    """
    The only door a design uses. mode "development" stops at the holdout start. mode "runner" stops at as_of_limit_ts.
    """

    # FUNCTION: STORE THE FRAMES THE RUNNER ALREADY LOADED
    def __init__(self, mode_str_in, as_of_limit_ts_in=None, frame_dict_in=None, access_sink_list_in=None, declared_name_list_in=None):
        """
        Args:
            mode_str_in (str): "development" or "runner"
            as_of_limit_ts_in (datetime-like | None): Runner window end
            frame_dict_in (dict | None): source name -> frame already loaded
            access_sink_list_in (list | None): Shared access log
            declared_name_list_in (list | None): Sources the design named in DATA_SOURCE_LIST (None = not checked)
        """
        # KEEP THE MODE, THE LIMIT AND THE FRAMES
        self.mode_str = mode_str_in
        self.as_of_limit_ts = as_of_limit_ts_in
        self.frame_dict = {} if frame_dict_in is None else frame_dict_in
        self.access_sink_list = [] if access_sink_list_in is None else access_sink_list_in
        self.declared_name_list = None if declared_name_list_in is None else list(declared_name_list_in)


    # FUNCTION: THE SOURCES A DESIGN HAS READ
    def get_access_name_list(self):
        """
        Source names read through get or get_labels, first-seen order, no duplicates.

        Args:
            None

        Returns:
            list[str]: Source names
        """
        # THE SHARED SINK
        return list(self.access_sink_list)

    # FUNCTION: REFUSE A READ THE DESIGN DID NOT DECLARE
    def _refuse_undeclared_source(self, source_name_str_in):
        """
        When the runner set DATA_SOURCE_LIST, a read of any other source is recorded and then refused. No row is returned.

        Args:
            source_name_str_in (str): Source name

        Returns:
            None
        """
        # NO LIST MEANS THE CALLER IS NOT THE RUNNER
        if self.declared_name_list is None or source_name_str_in in self.declared_name_list:
            return
        # THE ACCESS LOG SHOWS THE READ, THEN THE READ STOPS
        self._record_access(source_name_str_in)
        raise ValueError(f"undeclared source {source_name_str_in}")

    # FUNCTION: RECORD ONE READ
    def _record_access(self, source_name_str_in):
        """
        Appends the source the first time it is read.

        Args:
            source_name_str_in (str): Source name

        Returns:
            None
        """
        # FIRST SEEN ONLY
        if source_name_str_in not in self.access_sink_list:
            self.access_sink_list.append(source_name_str_in)

    # FUNCTION: THE LOADED FRAME, STAMPED
    def _get_stamped_pdf(self, source_name_str_in):
        """
        The loaded rows with available_ts. A missing frame raises. An unknown name raises.

        Args:
            source_name_str_in (str): Source name

        Returns:
            pd.DataFrame: Stamped rows
        """
        # REGISTRATION FIRST, THEN THE LOADED FRAME
        get_source_spec_dict(source_name_str_in)
        if source_name_str_in not in self.frame_dict:
            raise ValueError(f"{source_name_str_in} is not loaded. Read data through the DataContext.")
        return add_available_ts_pdf(source_name_str_in, self.frame_dict[source_name_str_in])

    # FUNCTION: FEATURE ROWS KNOWABLE AT as_of
    def get(self, source_name_str_in, as_of_ts_in, columns_in=None):
        """
        Feature rows with available_ts <= as_of_ts. A label source raises.

        Args:
            source_name_str_in (str): Registered feature source
            as_of_ts_in (datetime-like): Query time
            columns_in (list | None): Columns to keep

        Returns:
            pd.DataFrame: Visible feature rows
        """
        # LABELS HAVE THEIR OWN DOOR
        spec_dict = get_source_spec_dict(source_name_str_in)
        if spec_dict["role"] == "label":
            raise ValueError(f"{source_name_str_in} is a label. Read it through get_labels.")
        as_of_ts = get_ny_timestamp(as_of_ts_in)
        # A SOURCE THE DESIGN DID NOT DECLARE IS REFUSED BEFORE ANY ROW IS RETURNED
        self._refuse_undeclared_source(source_name_str_in)
        # STAMP AND DROP ANY LABEL COLUMNS ON A FEATURE SOURCE
        stamped_pdf = get_feature_column_pdf(source_name_str_in, self._get_stamped_pdf(source_name_str_in), columns_in)
        # RECORD THE READ AND CUT AT as_of
        self._record_access(source_name_str_in)
        return get_as_of_pdf(source_name_str_in, as_of_ts, columns_in, pdf_in=stamped_pdf, mode_str_in=self.mode_str, as_of_limit_ts_in=self.as_of_limit_ts)

    # FUNCTION: LABEL ROWS WHOSE OUTCOME WAS KNOWN BEFORE THE CUTOFF
    def get_labels(self, source_name_str_in, known_before_ts_in, columns_in=None):
        """
        Label rows with label_known_ts strictly before known_before_ts. A feature source raises.

        Args:
            source_name_str_in (str): Registered label source
            known_before_ts_in (datetime-like): Train cutoff
            columns_in (list | None): Columns to keep

        Returns:
            pd.DataFrame: Labels known before the cutoff
        """
        # FEATURES DO NOT COME THROUGH THIS DOOR
        spec_dict = get_source_spec_dict(source_name_str_in)
        if spec_dict["role"] != "label":
            raise ValueError(f"{source_name_str_in} is a feature. Read it through get.")
        # A SOURCE THE DESIGN DID NOT DECLARE IS REFUSED BEFORE ANY ROW IS RETURNED
        self._refuse_undeclared_source(source_name_str_in)
        # STRICTLY BEFORE THE TRAINING MOMENT
        stamped_pdf = self._get_stamped_pdf(source_name_str_in)
        cutoff_ts = get_ny_timestamp(known_before_ts_in)
        known_pdf = stamped_pdf[stamped_pdf["label_known_ts"].map(get_ny_timestamp) < cutoff_ts].copy()
        visible_pdf = get_holdout_visible_pdf(known_pdf, self.mode_str, self.as_of_limit_ts)
        self._record_access(source_name_str_in)
        if columns_in is not None:
            visible_pdf = visible_pdf[list(columns_in)].copy()
        return visible_pdf.reset_index(drop=True)

    # FUNCTION: A CONTEXT WHOSE SOURCES STOP AT THE END OF THE CUT SESSION
    def get_truncated_context(self, session_end_ts_in, spy_array_dict_in):
        """
        Every loaded source keeps rows with available_ts <= the cut session's last bar end. SPY comes from the
        already-truncated arrays so its indexes stay the runner's indexes.

        Args:
            session_end_ts_in (datetime-like): End of the cut session's last bar
            spy_array_dict_in (dict): Truncated SPY arrays

        Returns:
            DataContext: Child context sharing the access log
        """
        # CUT EVERY NON-SPY FRAME AT THE SESSION END
        session_end_ts = get_ny_timestamp(session_end_ts_in)
        child_dict = {}
        for source_name_str, frame_pdf in self.frame_dict.items():
            if source_name_str == "SPY_1MIN":
                continue
            stamped_pdf = add_available_ts_pdf(source_name_str, frame_pdf)
            available_series = pd.to_datetime(stamped_pdf["available_ts"])
            if available_series.dt.tz is None:
                available_series = available_series.dt.tz_localize(NY_TZ_STR)
            else:
                available_series = available_series.dt.tz_convert(NY_TZ_STR)
            child_dict[source_name_str] = stamped_pdf.loc[available_series <= session_end_ts].copy()
        # SPY IS THE RUNNER'S TRUNCATED ARRAYS
        child_dict["SPY_1MIN"] = get_spy_frame_pdf(spy_array_dict_in)
        return DataContext(self.mode_str, self.as_of_limit_ts, child_dict, self.access_sink_list, self.declared_name_list)


# TSDAY COLUMNS COMPUTED FROM BARS AFTER THE DECISION BAR (NOT SERVED ON THE FEATURE PATH; THEY STAY ON TSDAY_FWD ROWS,
# WHICH ARE ONLY SERVED 20 SESSIONS LATER)
TSDAY_AFTER_DECISION_COLUMN_LIST = ["fill_open", "session_high", "session_low", "session_close"]

# FUNCTION: DROP TSDAY COLUMNS THAT LOOK FORWARD
def get_feature_column_pdf(source_name_str_in, feature_pdf_in, columns_in):
    """
    TSDAY rows also carry the forward return. Those columns are labels and are removed on the feature path.

    Args:
        source_name_str_in (str): Source name
        feature_pdf_in (pd.DataFrame): Feature rows
        columns_in (list | None): Requested columns

    Returns:
        pd.DataFrame: Feature columns only
    """
    # ONLY TSDAY MIXES A LABEL ONTO THE FEATURE ROW
    if source_name_str_in != "TSDAY":
        return feature_pdf_in
    label_column_list = [column_str for column_str in feature_pdf_in.columns if column_str.startswith("fwd_") or column_str.startswith("y_fwd")]
    # COLUMNS OF THE SAME ROW THAT ARE ONLY KNOWN AFTER THE DECISION BAR (THE 15:59 FILL OPEN, THE COMPLETE SESSION)
    late_column_list = [column_str for column_str in TSDAY_AFTER_DECISION_COLUMN_LIST if column_str in feature_pdf_in.columns]
    if columns_in is not None and any(column_str in label_column_list + late_column_list for column_str in columns_in):
        raise ValueError("TSDAY forward-return and after-decision columns are not served through get.")
    return feature_pdf_in.drop(columns=label_column_list + late_column_list)

# FUNCTION: BUILD THE RUNNER'S CONTEXT FROM ARRAYS AND ANY EXTRA FRAMES
def get_runner_context(ohlcv_array_dict_in, source_frame_dict_in=None, as_of_limit_ts_in=None, declared_name_list_in=None):
    """
    SPY_1MIN from the bar arrays, plus any other frames the caller already loaded. Nothing is read from disk here.

    Args:
        ohlcv_array_dict_in (dict): SPY bar arrays
        source_frame_dict_in (dict | None): Other source name -> frame
        as_of_limit_ts_in (datetime-like | None): Window end (last bar end)
        declared_name_list_in (list | None): DATA_SOURCE_LIST (None = not checked)

    Returns:
        DataContext: Runner context
    """
    # SPY FROM THE ARRAYS THE RUNNER ALREADY HOLDS
    frame_dict = {"SPY_1MIN": get_spy_frame_pdf(ohlcv_array_dict_in)}
    if source_frame_dict_in:
        for source_name_str, frame_pdf in source_frame_dict_in.items():
            get_source_spec_dict(source_name_str)
            frame_dict[source_name_str] = frame_pdf
    return DataContext("runner", as_of_limit_ts_in, frame_dict, [], declared_name_list_in)

# FUNCTION: THE SOURCES A DESIGN DECLARED
def get_declared_source_name_list(design_module_in):
    """
    DATA_SOURCE_LIST when the design defines it. Otherwise ROW_SOURCE_LIST plus LABEL_SOURCE_LIST (minute mode),
    with SPY_1MIN prepended if missing. A design without any of those is treated as ["SPY_1MIN"].

    Args:
        design_module_in (module): Design

    Returns:
        list[str]: Registry names
    """
    # AN EXPLICIT DATA_SOURCE_LIST IS KEPT, INCLUDING AN EMPTY ONE
    if hasattr(design_module_in, "DATA_SOURCE_LIST"):
        return [str(source_name_str) for source_name_str in design_module_in.DATA_SOURCE_LIST]
    # MINUTE MODE MAY NAME ROW AND LABEL SOURCES INSTEAD
    name_list = []
    if hasattr(design_module_in, "ROW_SOURCE_LIST"):
        name_list.extend(str(source_name_str) for source_name_str in design_module_in.ROW_SOURCE_LIST)
    if hasattr(design_module_in, "LABEL_SOURCE_LIST"):
        name_list.extend(str(source_name_str) for source_name_str in design_module_in.LABEL_SOURCE_LIST)
    if not name_list:
        return ["SPY_1MIN"]
    if "SPY_1MIN" not in name_list:
        name_list = ["SPY_1MIN"] + name_list
    seen_set = set()
    unique_list = []
    for name_str in name_list:
        if name_str in seen_set:
            continue
        seen_set.add(name_str)
        unique_list.append(name_str)
    return unique_list

# FUNCTION: DROP ROWS DATED AFTER THE END
def get_frame_through_end_date_pdf(frame_pdf_in, end_date_in):
    """
    Keeps rows whose session date is on or before end_date_in. A row with no date or timestamp is kept.

    Args:
        frame_pdf_in (pd.DataFrame): Loaded rows
        end_date_in (datetime.date): Last date kept

    Returns:
        pd.DataFrame: Rows through the end date
    """
    # NOTHING TO CUT
    if frame_pdf_in is None or len(frame_pdf_in) == 0:
        return frame_pdf_in
    end_date = pd.Timestamp(end_date_in).date()
    # THE DATE COLUMN IS THE SESSION; OTHERWISE THE TIMESTAMP'S NEW YORK DATE
    if "date" in frame_pdf_in.columns:
        day_series = pd.to_datetime(frame_pdf_in["date"])
    elif "timestamp" in frame_pdf_in.columns:
        day_series = pd.to_datetime(frame_pdf_in["timestamp"])
    else:
        return frame_pdf_in
    if getattr(day_series.dt, "tz", None) is not None:
        day_series = day_series.dt.tz_convert(NY_TZ_STR)
    return frame_pdf_in.loc[day_series.dt.date <= end_date].reset_index(drop=True)

# FUNCTION: CALL ONE REGISTRY LOADER UP TO AN END DATE
def get_registry_frame_pdf(source_name_str_in, end_date_in):
    """
    Reads one built-in source through its registry loader. The cutoff is end_date_in. The holdout guard stays on.

    Args:
        source_name_str_in (str): Registered source
        end_date_in (datetime.date): Last session kept

    Returns:
        pd.DataFrame: Loader rows
    """
    # THE CUTOFF STRING THE LOADERS ALREADY ACCEPT
    end_str = str(pd.Timestamp(end_date_in).date())
    if source_name_str_in == "SPY_1MIN":
        from so.core.raw_data import get_complete_ohlcv_pdf
        return get_complete_ohlcv_pdf(cutoff_date_str_in=end_str, enforce_holdout_bool_in=True)
    if source_name_str_in in ("VIX_DAILY", "VIX3M_DAILY", "VIX_1MIN", "VIX3M_1MIN"):
        series_str = "vix3m" if source_name_str_in.startswith("VIX3M") else "vix"
        if source_name_str_in.endswith("DAILY"):
            from so.features.vix_features import read_vix_daily_pdf
            return read_vix_daily_pdf(series_str, end_str, enforce_holdout_bool_in=True)
        from so.features.vix_features import read_vix_1min_pdf
        return read_vix_1min_pdf(series_str, end_str, enforce_holdout_bool_in=True)
    # CACHE FOLDERS (DATE-STAMPED FILES, EXCEPT THE DAILY TABLE)
    from so import paths
    from so.core.local_file_management import read_csv_files_from_path, read_date_range_csv_files_from_path
    folder_dict = {"TSIND": paths.LOCAL_TSIND_DATA_FILE_PATH_STR, "TSSEG": paths.LOCAL_TSSEG_DATA_FILE_PATH_STR,
                   "TSCTX": paths.LOCAL_TSCTX_DATA_FILE_PATH_STR, "TSBAR": paths.LOCAL_TSBAR_DATA_FILE_PATH_STR}
    if source_name_str_in in folder_dict:
        return read_date_range_csv_files_from_path(folder_dict[source_name_str_in], None, end_str, enforce_holdout_bool_in=True)
    if source_name_str_in in ("TSDAY", "TSDAY_FWD"):
        return read_csv_files_from_path(paths.LOCAL_TSDAY_DATA_FILE_PATH_STR, enforce_holdout_bool_in=True)
    raise ValueError(f"{source_name_str_in} is registered but has no disk loader.")

# FUNCTION: STAMP DECLARED SOURCES THROUGH AN END DATE
def get_stamped_source_frame_dict(source_name_list_in, end_date_in):
    """
    Loads each declared source through its registry loader and stamps available_ts (and label_known_ts for a label).
    Rows after end_date_in are dropped. This function does not set the runner flag and does not decide whether the
    end date is allowed. The development loader and the evaluation loader own those checks.

    Args:
        source_name_list_in (list[str]): Registry names
        end_date_in (datetime.date | str): Last session kept

    Returns:
        dict: source name -> stamped frame
    """
    # THE CALLER HAS ALREADY DECIDED THAT THIS END DATE MAY BE READ
    end_date = pd.Timestamp(end_date_in).date()
    frame_dict = {}
    for source_name_str in source_name_list_in:
        # AN UNREGISTERED NAME RAISES BEFORE ANY FILE IS USED FOR THAT NAME
        get_source_spec_dict(source_name_str)
        loaded_pdf = get_frame_through_end_date_pdf(get_registry_frame_pdf(source_name_str, end_date), end_date)
        if source_name_str == "TSBAR" and len(loaded_pdf):
            # PLACE THE STORED EXIT BARS ON THE SPY MINUTES ALREADY LOADED FOR THIS CONTEXT
            spy_pdf = frame_dict.get("SPY_1MIN")
            timestamp_index = spy_pdf["timestamp"] if spy_pdf is not None and len(spy_pdf) and "timestamp" in spy_pdf.columns else None
            frame_dict[source_name_str] = add_tsbar_label_known_ts_pdf(loaded_pdf, timestamp_index_in=timestamp_index)
        else:
            frame_dict[source_name_str] = add_available_ts_pdf(source_name_str, loaded_pdf) if len(loaded_pdf) else loaded_pdf
    # RETURN THE STAMPED FRAMES
    return frame_dict

# FUNCTION: LOAD DECLARED SOURCES THROUGH A DEVELOPMENT END DATE
def load_source_frame_dict(source_name_list_in, end_date_in):
    """
    Loads each declared source through its registry loader and stamps available_ts (and label_known_ts for a label).
    Rows after end_date_in are dropped. The development view stamp is checked first. An end date on or after the
    active window start raises. This function does not set the runner flag. The direct-read block stays off, because
    this load happens before a replay starts.

    Args:
        source_name_list_in (list[str]): Registry names
        end_date_in (datetime.date | str): Last session kept

    Returns:
        dict: source name -> stamped frame
    """
    # THE HOLDOUT MODULE OWNS THE VIEW STAMP AND THE WINDOW START
    import so.core.holdout as holdout_module
    # REFUSE A MISSING OR STALE DEVELOPMENT VIEW BEFORE ANY SOURCE IS OPENED
    holdout_module.check_development_view()
    end_date = pd.Timestamp(end_date_in).date()
    window_dict = holdout_module.get_active_holdout_window_dict()
    # A DEVELOPMENT LOAD STOPS BEFORE THE WINDOW. THE WINDOW ITSELF IS NOT READ HERE
    if end_date >= holdout_module.get_date(window_dict["start"]):
        raise ValueError(f"❌ {end_date} is on or after the holdout start {window_dict['start']}.")
    # STAMP THE FRAMES. THE RUNNER FLAG IS LEFT AS THE CALLER SET IT
    return get_stamped_source_frame_dict(source_name_list_in, end_date)
