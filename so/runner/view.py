import numpy as np
import pandas as pd
# IMPORT THE POINT-IN-TIME CLOCKS AND THE CONTEXT THE VIEW WRAPS
from so.core.point_in_time import get_ny_timestamp, get_minute_bar_available_ts

"""
Decision View (infrastructure step 4a)

At a decision moment the design receives this view, not the runner's bar arrays. SPY bars are read-only slices
through the decision bar. Feature rows come from DataContext.get with available_ts at or before the moment. Labels
come only from DataContext.get_labels with label_known_ts strictly before the moment. Clocks and registration stay
in so.core.point_in_time; this module does not stamp sources itself.
"""

# FUNCTION: A READ-ONLY NUMPY SLICE THROUGH LAST_IDX INCLUSIVE
def get_readonly_slice_arr(array_in, last_idx_in):
    """
    Prefix of array_in through last_idx_in. A view of the original, not a copy, and not writable.

    Args:
        array_in (np.ndarray): Full array
        last_idx_in (int): Last index kept

    Returns:
        np.ndarray: Read-only prefix
    """
    # SLICE THEN LOCK; THE CALLER STILL SEES THE SAME MEMORY
    sliced_arr = array_in[:int(last_idx_in) + 1]
    sliced_arr.flags.writeable = False
    return sliced_arr


# FUNCTION: SPY ARRAYS CUT AT THE DECISION BAR
def get_sliced_bar_array_dict(ohlcv_array_dict_in, last_bar_idx_in, session_idx_in):
    """
    Price and timestamp arrays sliced through last_bar_idx_in. Session bounds cover sessions 0..session_idx_in, and
    the live session ends at the decision bar so its session_end_idx does not point past the slice.

    Args:
        ohlcv_array_dict_in (dict): Runner bar arrays
        last_bar_idx_in (int): Decision bar (last bar in the view)
        session_idx_in (int): Session of that bar

    Returns:
        dict: Sliced bar arrays
    """
    # PRICE AND SESSION-OF-BAR ARRAYS ARE VIEWS
    last_bar_idx = int(last_bar_idx_in)
    session_idx = int(session_idx_in)
    sliced_dict = {
        "timestamp_index": ohlcv_array_dict_in["timestamp_index"][:last_bar_idx + 1],
        "open_arr": get_readonly_slice_arr(ohlcv_array_dict_in["open_arr"], last_bar_idx),
        "high_arr": get_readonly_slice_arr(ohlcv_array_dict_in["high_arr"], last_bar_idx),
        "low_arr": get_readonly_slice_arr(ohlcv_array_dict_in["low_arr"], last_bar_idx),
        "close_arr": get_readonly_slice_arr(ohlcv_array_dict_in["close_arr"], last_bar_idx),
        "bar_session_idx_arr": get_readonly_slice_arr(ohlcv_array_dict_in["bar_session_idx_arr"], last_bar_idx),
        "session_date_list": list(ohlcv_array_dict_in["session_date_list"][:session_idx + 1]),
        "session_start_idx_arr": get_readonly_slice_arr(ohlcv_array_dict_in["session_start_idx_arr"], session_idx),
        "date_session_idx_dict": {session_date: idx for idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"][:session_idx + 1])},
    }
    # THE LIVE SESSION ENDS AT THE DECISION BAR (A SHORT COPY; A SLICE WOULD POINT AT THE SESSION CLOSE)
    end_arr = np.array(ohlcv_array_dict_in["session_end_idx_arr"][:session_idx + 1], copy=True)
    end_arr[-1] = last_bar_idx
    end_arr.flags.writeable = False
    sliced_dict["session_end_idx_arr"] = end_arr
    return sliced_dict


# FUNCTION: THE POINT-IN-TIME VIEW AT ONE DECISION
class DecisionView:
    """
    Bars, features and labels knowable at decision_ts. The design never receives the runner's full arrays.
    """

    # FUNCTION: STORE THE CUT AND THE CONTEXT
    def __init__(self, decision_ts_in, decision_bar_idx_in, session_idx_in, session_date_in, bar_array_dict_in, data_context_in):
        """
        Args:
            decision_ts_in (datetime-like): End of the decision bar
            decision_bar_idx_in (int): Decision bar in the runner's arrays (and last bar of the slice)
            session_idx_in (int): Session of that bar
            session_date_in (datetime.date): Session date
            bar_array_dict_in (dict): Sliced bar arrays
            data_context_in (DataContext): Context with decision_ts already armed
        """
        # KEEP THE MOMENT, THE SLICE AND THE CONTEXT (THE CONTEXT IS NOT A PUBLIC ATTRIBUTE)
        self.decision_ts = get_ny_timestamp(decision_ts_in)
        self.decision_bar_idx = int(decision_bar_idx_in)
        self.session_idx = int(session_idx_in)
        self.session_date = session_date_in
        self._bar_array_dict = bar_array_dict_in
        self._data_context = data_context_in

    # FUNCTION: THE SLICED SPY ARRAYS
    def get_bar_array_dict(self):
        """
        SPY bars through the decision bar. Price arrays are read-only slices of the runner's arrays.

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
            door_str_in (str): "source" or "label"

        Returns:
            pd.Timestamp: Query time in New York
        """
        # COMPARE IN NEW YORK
        query_ts = get_ny_timestamp(query_ts_in)
        if query_ts > self.decision_ts:
            raise ValueError(f"{door_str_in} cutoff is later than the decision currently being made.")
        return query_ts

    # FUNCTION: FEATURE ROWS KNOWABLE AT as_of (DEFAULT: THE MOMENT)
    def get(self, source_name_str_in, as_of_ts_in=None, columns_in=None):
        """
        Feature rows with available_ts <= as_of_ts. as_of after the decision raises. A label source raises inside
        DataContext.get.

        Args:
            source_name_str_in (str): Registered feature source
            as_of_ts_in (datetime-like | None): Query time (None = decision_ts)
            columns_in (list | None): Columns to keep

        Returns:
            pd.DataFrame: Visible feature rows
        """
        # DEFAULT TO THE ARMED MOMENT; A LATER CLOCK IS A LEAK
        as_of_ts = self.decision_ts if as_of_ts_in is None else self._raise_if_after_decision(as_of_ts_in, "source")
        return self._data_context.get(source_name_str_in, as_of_ts, columns_in)

    # FUNCTION: LABELS KNOWN STRICTLY BEFORE THE CUTOFF (DEFAULT: THE MOMENT)
    def get_labels(self, source_name_str_in, known_before_ts_in=None, columns_in=None):
        """
        Label rows with label_known_ts strictly before known_before_ts. A cutoff after the decision raises. A feature
        source raises inside DataContext.get_labels.

        Args:
            source_name_str_in (str): Registered label source
            known_before_ts_in (datetime-like | None): Train cutoff (None = decision_ts)
            columns_in (list | None): Columns to keep

        Returns:
            pd.DataFrame: Labels known before the cutoff
        """
        # DATA CONTEXT DOES NOT CHECK THE ARMED DECISION ON THIS DOOR, SO THE VIEW DOES
        cutoff_ts = self.decision_ts if known_before_ts_in is None else self._raise_if_after_decision(known_before_ts_in, "label")
        return self._data_context.get_labels(source_name_str_in, cutoff_ts, columns_in)


# FUNCTION: BUILD THE VIEW AT ONE DECISION BAR
def get_decision_view(ohlcv_array_dict_in, session_idx_in, data_context_in, decision_idx_in):
    """
    Slices the bars through the decision bar, arms the context at the bar's end, and returns the view.

    Args:
        ohlcv_array_dict_in (dict): Runner bar arrays
        session_idx_in (int): Session of the decision
        data_context_in (DataContext): Shared context
        decision_idx_in (int): Decision bar index

    Returns:
        DecisionView: View that stops at that moment
    """
    # THE MOMENT IS THE END OF THE DECISION BAR
    decision_idx = int(decision_idx_in)
    session_idx = int(session_idx_in)
    decision_ts = get_minute_bar_available_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])
    bar_array_dict = get_sliced_bar_array_dict(ohlcv_array_dict_in, decision_idx, session_idx)
    data_context_in.set_decision_ts(decision_ts)
    return DecisionView(decision_ts, decision_idx, session_idx, ohlcv_array_dict_in["session_date_list"][session_idx],
                        bar_array_dict, data_context_in)
