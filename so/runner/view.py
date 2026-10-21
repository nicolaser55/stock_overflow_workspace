import numpy as np
import pandas as pd
# IMPORT THE POINT-IN-TIME CLOCKS, REGISTRY AND STAMPING (THE VIEW DOES NOT HOLD A CONTEXT)
from so.core.point_in_time import (NY_TZ_STR, get_ny_timestamp, get_minute_bar_available_ts, get_source_spec_dict,
                                   add_available_ts_pdf, get_feature_column_pdf, get_spy_frame_pdf,
                                   get_declared_source_name_list)

"""
Decision View (infrastructure step 4a)

The design is shown only what could have been seen at the decision moment. That is structural: the runner keeps its
own buffers, starting empty (NaN / NaT), and copies each session's bars in as time advances, only up to the decision
bar before decide(). The view slices those buffers. One pass of copying in total. A slice's .base is the buffer, whose
tail after the moment is still NaN / NaT.

Declared sources are the same idea: a feed filled in available_ts order (labels in label_known_ts order) up to the
moment. The view does not hold a DataContext or any full frame. get / get_labels / get_new return copies of the
visible rows. get_new is the rows that became available since this design's previous call.

Default decision moment: end of the 15:58 bar (15:59:00); fill at the 15:59 open. Half days use the second-to-last
bar, the same index as so.features.daily_features.get_session_decision_idx_dict. The fill bar is not in the view.
Labels only through get_labels, with label_known_ts strictly before the moment.
"""

# BUFFER KEYS THE VIEW SLICES (LOCKED AFTER EACH COPY)
BAR_BUFFER_KEY_LIST = ["open_arr", "high_arr", "low_arr", "close_arr", "bar_session_idx_arr", "timestamp_arr",
                       "session_start_idx_arr", "session_end_idx_arr", "session_date_arr"]


# FUNCTION: A DATAFRAME THAT DOES NOT SHARE MEMORY WITH ITS SOURCE
def get_detached_pdf(pdf_in):
    """
    Rebuilds the frame from copied numpy columns so a CoW view of a longer frame cannot leak later rows.

    Args:
        pdf_in (pd.DataFrame): Rows to detach

    Returns:
        pd.DataFrame: Independent copy
    """
    # EMPTY KEEPS THE COLUMN NAMES, NOT THE SOURCE BLOCKS
    if pdf_in is None:
        return pd.DataFrame()
    if len(pdf_in) == 0:
        return pd.DataFrame(columns=list(pdf_in.columns))
    return pd.DataFrame({col_str: np.array(pdf_in[col_str].to_numpy()) for col_str in pdf_in.columns})


# FUNCTION: LOCK OR UNLOCK THE BAR BUFFERS
def set_bar_buffer_writeable(buffer_dict_in, writeable_bool_in):
    """
    The runner unlocks to copy, then locks so a design holding .base cannot write the tail.

    Args:
        buffer_dict_in (dict): Bar buffers
        writeable_bool_in (bool): True while copying

    Returns:
        None
    """
    # EACH BUFFER IS ITS OWN ARRAY
    for key_str in BAR_BUFFER_KEY_LIST:
        buffer_dict_in[key_str].flags.writeable = bool(writeable_bool_in)


# FUNCTION: A READ-ONLY NUMPY SLICE THROUGH LAST_IDX INCLUSIVE
def get_readonly_slice_arr(array_in, last_idx_in):
    """
    Prefix of array_in through last_idx_in. A view of the buffer, not a copy, and not writable.

    Args:
        array_in (np.ndarray): Buffer
        last_idx_in (int): Last index kept

    Returns:
        np.ndarray: Read-only prefix
    """
    # SLICE THEN LOCK; .base IS THE BUFFER WHOSE TAIL IS STILL EMPTY
    sliced_arr = array_in[:int(last_idx_in) + 1]
    sliced_arr.flags.writeable = False
    return sliced_arr


# FUNCTION: EMPTY BAR BUFFERS THE SAME SHAPE AS THE RUNNER'S ARRAYS
def get_empty_bar_buffer_dict(ohlcv_array_dict_in):
    """
    NaN / NaT arrays with the same lengths as the full bar arrays. Nothing has been copied yet.

    Args:
        ohlcv_array_dict_in (dict): Runner bar arrays

    Returns:
        dict: Empty buffers and copied_through_idx = -1
    """
    # ONE SLOT PER BAR AND PER SESSION; THE VIEW WILL SLICE THESE
    bar_count = len(ohlcv_array_dict_in["close_arr"])
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    timestamp_arr = np.empty(bar_count, dtype="datetime64[ns]")
    timestamp_arr[:] = np.datetime64("NaT")
    session_date_arr = np.empty(session_count, dtype=object)
    session_date_arr[:] = None
    return {"open_arr": np.full(bar_count, np.nan), "high_arr": np.full(bar_count, np.nan),
            "low_arr": np.full(bar_count, np.nan), "close_arr": np.full(bar_count, np.nan),
            "bar_session_idx_arr": np.full(bar_count, np.nan), "timestamp_arr": timestamp_arr,
            "session_start_idx_arr": np.full(session_count, np.nan), "session_end_idx_arr": np.full(session_count, np.nan),
            "session_date_arr": session_date_arr, "copied_through_idx": -1, "copied_through_session_idx": -1}


# FUNCTION: COPY NEW BARS INTO THE BUFFER THROUGH THE DECISION BAR
def fill_bar_buffer_through_decision(buffer_dict_in, ohlcv_array_dict_in, session_idx_in, decision_idx_in):
    """
    Copies bars (copied_through_idx, decision_idx] from the runner's arrays into the buffer. Already-copied bars are
    not copied again.

    Args:
        buffer_dict_in (dict): Empty-started buffers
        ohlcv_array_dict_in (dict): Full arrays (held by the loop, not the view)
        session_idx_in (int): Session of the decision
        decision_idx_in (int): Decision bar

    Returns:
        None
    """
    # UNLOCK, COPY ONLY THE NEW PREFIX, THEN LOCK SO .base STAYS READ-ONLY
    set_bar_buffer_writeable(buffer_dict_in, True)
    start_idx = int(buffer_dict_in["copied_through_idx"]) + 1
    end_idx = int(decision_idx_in) + 1
    if start_idx < end_idx:
        buffer_dict_in["open_arr"][start_idx:end_idx] = ohlcv_array_dict_in["open_arr"][start_idx:end_idx]
        buffer_dict_in["high_arr"][start_idx:end_idx] = ohlcv_array_dict_in["high_arr"][start_idx:end_idx]
        buffer_dict_in["low_arr"][start_idx:end_idx] = ohlcv_array_dict_in["low_arr"][start_idx:end_idx]
        buffer_dict_in["close_arr"][start_idx:end_idx] = ohlcv_array_dict_in["close_arr"][start_idx:end_idx]
        buffer_dict_in["bar_session_idx_arr"][start_idx:end_idx] = ohlcv_array_dict_in["bar_session_idx_arr"][start_idx:end_idx].astype(float)
        naive_index = ohlcv_array_dict_in["timestamp_index"][start_idx:end_idx]
        if getattr(naive_index, "tz", None) is not None:
            naive_index = naive_index.tz_convert(NY_TZ_STR).tz_localize(None)
        buffer_dict_in["timestamp_arr"][start_idx:end_idx] = np.asarray(naive_index, dtype="datetime64[ns]")
        buffer_dict_in["copied_through_idx"] = int(decision_idx_in)
    # SESSION BOUNDS FOR EVERY SESSION WHOSE BARS ARE NOW IN THE BUFFER
    session_idx = int(session_idx_in)
    first_new_session_idx = int(buffer_dict_in["copied_through_session_idx"]) + 1
    for filled_session_idx in range(first_new_session_idx, session_idx + 1):
        buffer_dict_in["session_start_idx_arr"][filled_session_idx] = float(ohlcv_array_dict_in["session_start_idx_arr"][filled_session_idx])
        buffer_dict_in["session_date_arr"][filled_session_idx] = ohlcv_array_dict_in["session_date_list"][filled_session_idx]
    for prior_session_idx in range(0, session_idx):
        buffer_dict_in["session_end_idx_arr"][prior_session_idx] = float(ohlcv_array_dict_in["session_end_idx_arr"][prior_session_idx])
    buffer_dict_in["session_end_idx_arr"][session_idx] = float(decision_idx_in)
    buffer_dict_in["copied_through_session_idx"] = session_idx
    set_bar_buffer_writeable(buffer_dict_in, False)


# FUNCTION: SLICED SPY ARRAYS FROM THE BUFFER
def get_sliced_bar_array_dict(buffer_dict_in, last_bar_idx_in, session_idx_in):
    """
    Price and timestamp slices through last_bar_idx_in. Session bounds cover 0..session_idx_in. The live session ends
    at the decision bar.

    Args:
        buffer_dict_in (dict): Buffers filled through the decision bar
        last_bar_idx_in (int): Decision bar
        session_idx_in (int): Session of that bar

    Returns:
        dict: Sliced bar arrays
    """
    # SLICES; .base IS THE NaN/NaT BUFFER
    last_bar_idx = int(last_bar_idx_in)
    session_idx = int(session_idx_in)
    timestamp_slice_arr = get_readonly_slice_arr(buffer_dict_in["timestamp_arr"], last_bar_idx)
    session_date_list = [buffer_dict_in["session_date_arr"][idx] for idx in range(session_idx + 1)]
    return {
        "timestamp_arr": timestamp_slice_arr,
        "timestamp_index": pd.DatetimeIndex(timestamp_slice_arr, tz=NY_TZ_STR),
        "open_arr": get_readonly_slice_arr(buffer_dict_in["open_arr"], last_bar_idx),
        "high_arr": get_readonly_slice_arr(buffer_dict_in["high_arr"], last_bar_idx),
        "low_arr": get_readonly_slice_arr(buffer_dict_in["low_arr"], last_bar_idx),
        "close_arr": get_readonly_slice_arr(buffer_dict_in["close_arr"], last_bar_idx),
        "bar_session_idx_arr": get_readonly_slice_arr(buffer_dict_in["bar_session_idx_arr"], last_bar_idx),
        "session_date_list": session_date_list,
        "session_start_idx_arr": get_readonly_slice_arr(buffer_dict_in["session_start_idx_arr"], session_idx),
        "session_end_idx_arr": get_readonly_slice_arr(buffer_dict_in["session_end_idx_arr"], session_idx),
        "date_session_idx_dict": {session_date: idx for idx, session_date in enumerate(session_date_list)},
    }


# FUNCTION: A DECLARED SOURCE FILLED IN CLOCK ORDER
class SourceFeed:
    """
    Runner-only. The full stamped frame stays here. The view receives copies of the visible prefix, never this object.
    """

    # FUNCTION: SORT THE STAMPED FRAME AND START WITH NO VISIBLE ROWS
    def __init__(self, source_name_str_in, role_str_in, stamped_pdf_in):
        """
        Args:
            source_name_str_in (str): Registry name
            role_str_in (str): feature or label
            stamped_pdf_in (pd.DataFrame): Already stamped
        """
        # LABELS USE STRICTLY-BEFORE; FEATURES USE AT-OR-BEFORE
        self.source_name_str = source_name_str_in
        self.role_str = str(role_str_in)
        self.clock_col_str = "label_known_ts" if self.role_str == "label" else "available_ts"
        self.strict_before_bool = self.role_str == "label"
        if stamped_pdf_in is None or len(stamped_pdf_in) == 0:
            self.full_pdf = pd.DataFrame()
            self.clock_ns_arr = np.array([], dtype=np.int64)
        else:
            ordered_pdf = stamped_pdf_in.copy()
            ordered_pdf[self.clock_col_str] = [get_ny_timestamp(ts) for ts in ordered_pdf[self.clock_col_str]]
            ordered_pdf = ordered_pdf.sort_values(self.clock_col_str, kind="mergesort").reset_index(drop=True)
            self.full_pdf = ordered_pdf
            self.clock_ns_arr = np.array([ts.value for ts in ordered_pdf[self.clock_col_str]], dtype=np.int64)
        self.next_idx_int = 0
        self.visible_pdf = self.full_pdf.iloc[0:0].copy()
        self.prev_visible_count_int = 0

    # FUNCTION: COPY NEWLY KNOWABLE ROWS INTO THE VISIBLE PREFIX
    def advance_to_ts(self, moment_ts_in):
        """
        Appends rows whose clock is at or before the moment (strictly before for a label).

        Args:
            moment_ts_in (pd.Timestamp): Decision moment

        Returns:
            None
        """
        # SEARCH SORTED CLOCKS; ALREADY-COPIED ROWS ARE SKIPPED
        if len(self.clock_ns_arr) == 0 or self.next_idx_int >= len(self.clock_ns_arr):
            return
        moment_ns = int(get_ny_timestamp(moment_ts_in).value)
        side_str = "left" if self.strict_before_bool else "right"
        end_idx = int(np.searchsorted(self.clock_ns_arr, moment_ns, side=side_str))
        if end_idx > self.next_idx_int:
            extra_pdf = self.full_pdf.iloc[self.next_idx_int:end_idx]
            self.visible_pdf = pd.concat([self.visible_pdf, extra_pdf], ignore_index=True)
            self.next_idx_int = end_idx

    # FUNCTION: MARK THE BOUNDARY FOR get_new AFTER decide()
    def mark_call_boundary(self):
        """
        The next get_new starts after the rows this call already showed.

        Args:
            None

        Returns:
            None
        """
        # THE DESIGN'S PREVIOUS CALL IS THIS ONE ONCE decide RETURNS
        self.prev_visible_count_int = len(self.visible_pdf)


# FUNCTION: STAMPED FEEDS FOR EVERY DECLARED SOURCE
def get_source_feed_dict(design_in, ohlcv_array_dict_in, data_context_in):
    """
    One SourceFeed per declared name. SPY_1MIN comes from the bar arrays when the context has no frame.

    Args:
        design_in (object): Design (DATA_SOURCE_LIST)
        ohlcv_array_dict_in (dict): Bars
        data_context_in (DataContext | None): Loaded frames

    Returns:
        dict: source name -> SourceFeed
    """
    # DECLARED NAMES; MISSING MEANS SPY ONLY
    if data_context_in is not None and data_context_in.declared_name_list is not None:
        declared_name_list = list(data_context_in.declared_name_list)
    else:
        declared_name_list = get_declared_source_name_list(design_in)
    frame_dict = {} if data_context_in is None else dict(data_context_in.frame_dict)
    feed_dict = {}
    for source_name_str in declared_name_list:
        spec_dict = get_source_spec_dict(source_name_str)
        if source_name_str not in frame_dict:
            if source_name_str != "SPY_1MIN":
                raise ValueError(f"{source_name_str} is not loaded. Read data through the DataContext.")
            frame_pdf = get_spy_frame_pdf(ohlcv_array_dict_in)
        else:
            frame_pdf = add_available_ts_pdf(source_name_str, frame_dict[source_name_str])
        if spec_dict["role"] == "feature":
            frame_pdf = get_feature_column_pdf(source_name_str, frame_pdf, None)
        feed_dict[source_name_str] = SourceFeed(source_name_str, spec_dict["role"], frame_pdf)
    return feed_dict


# FUNCTION: THE POINT-IN-TIME VIEW AT ONE DECISION
class DecisionView:
    """
    Bars, features and labels knowable at decision_ts. No DataContext, no full frame.
    """

    # FUNCTION: STORE THE SLICES AND THE VISIBLE COPIES
    def __init__(self, decision_ts_in, decision_bar_idx_in, session_idx_in, session_date_in, bar_array_dict_in,
                 visible_pdf_dict_in, new_pdf_dict_in, role_dict_in):
        """
        Args:
            decision_ts_in (datetime-like): End of the decision bar
            decision_bar_idx_in (int): Last bar of the slice
            session_idx_in (int): Session of that bar
            session_date_in (datetime.date): Session date
            bar_array_dict_in (dict): Sliced bar arrays
            visible_pdf_dict_in (dict): source -> copy of rows knowable now
            new_pdf_dict_in (dict): source -> copy of rows new since the previous call
            role_dict_in (dict): source -> feature or label
        """
        # COPIES AND SLICES ONLY
        self.decision_ts = get_ny_timestamp(decision_ts_in)
        self.decision_bar_idx = int(decision_bar_idx_in)
        self.session_idx = int(session_idx_in)
        self.session_date = session_date_in
        self._bar_array_dict = bar_array_dict_in
        self._visible_pdf_dict = visible_pdf_dict_in
        self._new_pdf_dict = new_pdf_dict_in
        self._role_dict = role_dict_in

    # FUNCTION: THE SLICED SPY ARRAYS
    def get_bar_array_dict(self):
        """
        SPY bars through the decision bar. Price arrays are read-only slices of the runner's NaN-tailed buffer.

        Args:
            None

        Returns:
            dict: Sliced bar arrays
        """
        # THE SLICE WAS BUILT ONCE FOR THIS MOMENT
        return self._bar_array_dict

    # FUNCTION: REFUSE A CLOCK AFTER THE MOMENT
    def _raise_if_after_decision(self, query_ts_in, door_str_in):
        """
        Raises when the design asks for a time after the decision currently being made.

        Args:
            query_ts_in (datetime-like): Requested as_of or label cutoff
            door_str_in (str): source or label

        Returns:
            pd.Timestamp: Query time in New York
        """
        # COMPARE IN NEW YORK
        query_ts = get_ny_timestamp(query_ts_in)
        if query_ts > self.decision_ts:
            raise ValueError(f"{door_str_in} cutoff is later than the decision currently being made.")
        return query_ts

    # FUNCTION: REFUSE AN UNDECLARED NAME
    def _get_visible_pdf(self, source_name_str_in, role_str_in):
        """
        The snapshot for a declared source of the expected role.

        Args:
            source_name_str_in (str): Source name
            role_str_in (str | None): Required role, or None for get_new

        Returns:
            pd.DataFrame: Visible copy
        """
        # UNDECLARED NAMES DO NOT EXIST ON THE VIEW
        if source_name_str_in not in self._visible_pdf_dict:
            raise ValueError(f"undeclared source {source_name_str_in}")
        if role_str_in is not None and self._role_dict[source_name_str_in] != role_str_in:
            door_str = "get_labels" if role_str_in == "feature" else "get"
            raise ValueError(f"{source_name_str_in} is a {self._role_dict[source_name_str_in]}. Read it through {door_str}.")
        return self._visible_pdf_dict[source_name_str_in]

    # FUNCTION: FEATURE ROWS KNOWABLE AT as_of (DEFAULT: THE MOMENT)
    def get(self, source_name_str_in, as_of_ts_in=None, columns_in=None):
        """
        Feature rows with available_ts <= as_of_ts. A copy. as_of after the decision raises. A label source raises.

        Args:
            source_name_str_in (str): Registered feature source
            as_of_ts_in (datetime-like | None): Query time (None = decision_ts)
            columns_in (list | None): Columns to keep

        Returns:
            pd.DataFrame: Visible feature rows
        """
        # THE SNAPSHOT ALREADY STOPS AT THE MOMENT; AN EARLIER as_of FILTERS IT
        as_of_ts = self.decision_ts if as_of_ts_in is None else self._raise_if_after_decision(as_of_ts_in, "source")
        visible_pdf = self._get_visible_pdf(source_name_str_in, "feature")
        if len(visible_pdf) and as_of_ts < self.decision_ts:
            clock_series = pd.to_datetime(visible_pdf["available_ts"], utc=True).dt.tz_convert(NY_TZ_STR)
            visible_pdf = visible_pdf.loc[clock_series.map(get_ny_timestamp) <= as_of_ts]
        if columns_in is not None:
            visible_pdf = visible_pdf[list(columns_in)]
        return get_detached_pdf(visible_pdf)

    # FUNCTION: LABELS KNOWN STRICTLY BEFORE THE CUTOFF (DEFAULT: THE MOMENT)
    def get_labels(self, source_name_str_in, known_before_ts_in=None, columns_in=None):
        """
        Label rows with label_known_ts strictly before known_before_ts. A copy. A cutoff after the decision raises.

        Args:
            source_name_str_in (str): Registered label source
            known_before_ts_in (datetime-like | None): Train cutoff (None = decision_ts)
            columns_in (list | None): Columns to keep

        Returns:
            pd.DataFrame: Labels known before the cutoff
        """
        # THE SNAPSHOT ALREADY USED STRICTLY-BEFORE THE MOMENT
        cutoff_ts = self.decision_ts if known_before_ts_in is None else self._raise_if_after_decision(known_before_ts_in, "label")
        visible_pdf = self._get_visible_pdf(source_name_str_in, "label")
        if len(visible_pdf) and cutoff_ts < self.decision_ts:
            clock_series = pd.to_datetime(visible_pdf["label_known_ts"], utc=True).dt.tz_convert(NY_TZ_STR)
            visible_pdf = visible_pdf.loc[clock_series.map(get_ny_timestamp) < cutoff_ts]
        if columns_in is not None:
            visible_pdf = visible_pdf[list(columns_in)]
        return get_detached_pdf(visible_pdf)

    # FUNCTION: ROWS THAT BECAME AVAILABLE SINCE THE PREVIOUS CALL
    def get_new(self, source_name_str_in, columns_in=None):
        """
        A copy of the rows appended to this source since the design's previous decide() call. The first call returns
        every row visible at that moment. Works for a feature or a label.

        Args:
            source_name_str_in (str): Declared source
            columns_in (list | None): Columns to keep

        Returns:
            pd.DataFrame: New rows
        """
        # UNDECLARED NAMES DO NOT EXIST
        if source_name_str_in not in self._new_pdf_dict:
            raise ValueError(f"undeclared source {source_name_str_in}")
        new_pdf = self._new_pdf_dict[source_name_str_in]
        if columns_in is not None:
            new_pdf = new_pdf[list(columns_in)]
        return get_detached_pdf(new_pdf)


# FUNCTION: SNAPSHOTS THE VIEW MAY HOLD (COPIES, NOT THE FEED)
def get_view_source_snapshot_tuple(feed_dict_in):
    """
    Copies of the visible prefix and of the rows new since the previous call.

    Args:
        feed_dict_in (dict): source name -> SourceFeed

    Returns:
        tuple[dict, dict, dict]: visible copies, new copies, roles
    """
    # THE VIEW NEVER RECEIVES THE FEED OBJECT
    visible_pdf_dict, new_pdf_dict, role_dict = {}, {}, {}
    for source_name_str, feed in feed_dict_in.items():
        visible_pdf_dict[source_name_str] = get_detached_pdf(feed.visible_pdf)
        new_pdf_dict[source_name_str] = get_detached_pdf(feed.visible_pdf.iloc[feed.prev_visible_count_int:])
        role_dict[source_name_str] = feed.role_str
    return visible_pdf_dict, new_pdf_dict, role_dict


# FUNCTION: BUILD THE VIEW AT ONE DECISION BAR FROM THE BUFFERS
def get_decision_view(buffer_dict_in, session_idx_in, decision_idx_in, feed_dict_in):
    """
    Slices the bar buffer through the decision bar and snapshots the source feeds.

    Args:
        buffer_dict_in (dict): Bar buffers
        session_idx_in (int): Session of the decision
        decision_idx_in (int): Decision bar index
        feed_dict_in (dict): Source feeds already advanced to this moment

    Returns:
        DecisionView: View that stops at that moment
    """
    # THE MOMENT IS THE END OF THE DECISION BAR
    decision_idx = int(decision_idx_in)
    session_idx = int(session_idx_in)
    decision_ts = get_minute_bar_available_ts(pd.Timestamp(buffer_dict_in["timestamp_arr"][decision_idx]))
    bar_array_dict = get_sliced_bar_array_dict(buffer_dict_in, decision_idx, session_idx)
    visible_pdf_dict, new_pdf_dict, role_dict = get_view_source_snapshot_tuple(feed_dict_in)
    return DecisionView(decision_ts, decision_idx, session_idx, buffer_dict_in["session_date_arr"][session_idx],
                        bar_array_dict, visible_pdf_dict, new_pdf_dict, role_dict)
