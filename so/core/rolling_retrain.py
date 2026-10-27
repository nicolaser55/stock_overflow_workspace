import pandas as pd

"""
Rolling Retraining (Nicolas, 2026-10-11)

A model-based design is a walk-forward with a rolling training window. On each retraining session the model is fit
on rows that were already knowable that day, then kept until the next retraining. Every session is decided at its
decision bar with the latest fitted model. The path is one continuous series, in development and in the holdout.

The retraining frequency is a pre-registered protocol setting. The default is weekly: the first session of each
calendar week, so a Monday holiday is a Tuesday refit. Changing the frequency after results is a new version. A
protocol may pre-register one comparison of weekly against quarterly, and no other frequency comparison.

Training-window candidates default to 6 months, 2 years and 10 years. "ALL" is an expanding window from the first
session, for a protocol that pre-registers it. A row dated after the retraining day is outside every window: it was
not available that day. The candidate in force for a quarter is chosen from the last
CANDIDATE_SELECTION_POOLED_QUARTERS_DEFAULT completed quarters before that quarter, prior-only, the same rule as
exp02-exp13. A tie takes the longer training window (the more stable choice) unless the protocol names another order.

Labels may look forward from their own row. A model trained on day t learns only from rows whose label_known_ts is
strictly before the decision bar of day t. An unfinished label is dropped and counted as purged. It is never filled
with 0 or any other value. A row that has a label and no label_known_ts raises. When the label source is the
registered TSBAR source, label_known_ts comes from so.core.point_in_time. Otherwise the helpers below compute it:
a barrier label is knowable at the end of the bar where TP or SL was hit, or at the end of the horizon bar if neither
was hit; a fixed-horizon label is knowable at the decision timestamp of the session that many sessions later.

Features are checked with so.core.point_in_time.check_feature_available_ts. This module does not keep a second clock.
"""

# DEFINE THE FREQUENCIES A PROTOCOL MAY PRE-REGISTER
RETRAIN_FREQUENCY_ALLOWED_LIST = ["daily", "weekly", "monthly", "quarterly"]
# DEFINE THE TRAINING WINDOWS THE MASK ACCEPTS (ALL IS EXPANDING)
TRAIN_WINDOW_ALLOWED_LIST = ["6M", "2Y", "3Y", "5Y", "10Y", "ALL"]
# DEFINE THE LENGTH OF EACH NAMED WINDOW IN MONTHS (ALL HAS NO CALENDAR CUT; THE TIE BREAK TREATS IT AS THE LONGEST)
TRAIN_WINDOW_MONTH_DICT = {"6M": 6, "2Y": 24, "3Y": 36, "5Y": 60, "10Y": 120, "ALL": 10 ** 9}

"""
Retraining Sessions
"""

# FUNCTION: CONVERT A VALUE TO A NEW YORK TIMESTAMP
def get_clock_ts(timestamp_in):
    """
    Normalizes a timestamp to America/New_York.

    Args:
        timestamp_in (datetime-like): Timestamp

    Returns:
        pd.Timestamp: New York timestamp
    """
    # THE POINT-IN-TIME CLOCK IS THE ONE CLOCK
    from so.core.point_in_time import get_ny_timestamp
    return get_ny_timestamp(timestamp_in)

# FUNCTION: CONVERT A VALUE TO A SESSION DATE
def get_session_date(value_in):
    """
    Converts a date-like value to datetime.date.

    Args:
        value_in (datetime.date | str | pd.Timestamp): Session

    Returns:
        datetime.date: The session date
    """
    # DATES AND TIMESTAMPS BOTH REDUCE TO THE CALENDAR DAY
    return pd.Timestamp(value_in).date()

# FUNCTION: THE FIRST SESSION OF EACH CALENDAR BLOCK, PLUS THE FIRST SESSION OF THE SPAN
def get_retrain_session_list(session_date_list_in, start_date_in, end_date_in, frequency_str_in):
    """
    The sessions on which a refit happens. weekly is the first session of each ISO week (Monday-start; a Monday
    holiday makes Tuesday the first session). monthly is the first session of each calendar month. quarterly is the
    first session of each calendar quarter. daily is every session. The first session of the span is always a refit.

    Args:
        session_date_list_in (list): Session dates, in any order
        start_date_in, end_date_in: Inclusive span
        frequency_str_in (str): "daily", "weekly", "monthly" or "quarterly"

    Returns:
        list[datetime.date]: Retraining sessions, chronological, no duplicates
    """
    # REFUSE A FREQUENCY THE PROTOCOL MAY NOT NAME
    if frequency_str_in not in RETRAIN_FREQUENCY_ALLOWED_LIST:
        raise ValueError(f"retraining frequency '{frequency_str_in}' is not one of {RETRAIN_FREQUENCY_ALLOWED_LIST}.")
    # KEEP THE SESSIONS INSIDE THE SPAN
    start_date, end_date = get_session_date(start_date_in), get_session_date(end_date_in)
    session_date_list = sorted({get_session_date(session_date) for session_date in session_date_list_in if start_date <= get_session_date(session_date) <= end_date})
    if not session_date_list:
        return []
    # DAILY REFITS ON EVERY SESSION
    if frequency_str_in == "daily":
        return session_date_list
    # THE BLOCK KEY OF A SESSION
    def get_block_key(session_date):
        # A WEEK IS THE ISO WEEK (MONDAY START)
        if frequency_str_in == "weekly":
            iso = session_date.isocalendar()
            return (iso[0], iso[1])
        # A MONTH IS THE CALENDAR MONTH
        if frequency_str_in == "monthly":
            return (session_date.year, session_date.month)
        # A QUARTER IS JANUARY, APRIL, JULY, OCTOBER
        return (session_date.year, (session_date.month - 1) // 3)
    # THE FIRST SESSION OF EACH BLOCK
    first_dict = {}
    for session_date in session_date_list:
        first_dict.setdefault(get_block_key(session_date), session_date)
    # THE FIRST SESSION OF THE SPAN IS A REFIT EVEN MID-BLOCK
    retrain_set = set(first_dict.values())
    retrain_set.add(session_date_list[0])
    return sorted(retrain_set)

"""
Label Clocks
"""


"""
Training Mask
"""

# FUNCTION: THE FIRST DAY OF A TRAINING WINDOW
def get_train_window_start_ts(retrain_decision_ts_in, train_window_str_in):
    """
    Midnight New York on (retrain day - the window). ALL has no calendar start (None): every row date is inside it.

    Args:
        retrain_decision_ts_in (datetime-like): Decision bar of the retraining session
        train_window_str_in (str): "6M", "2Y", "10Y" or "ALL"

    Returns:
        pd.Timestamp | None: Window start, or None for ALL
    """
    # REFUSE AN UNKNOWN WINDOW
    if train_window_str_in not in TRAIN_WINDOW_ALLOWED_LIST:
        raise ValueError(f"training window '{train_window_str_in}' is not one of {TRAIN_WINDOW_ALLOWED_LIST}.")
    # ALL STARTS AT THE FIRST SESSION THE CALLER PASSED
    if train_window_str_in == "ALL":
        return None
    # 6 MONTHS, OR A WHOLE NUMBER OF YEARS, MEASURED BACK FROM THE RETRAIN DAY
    day_ts = get_clock_ts(retrain_decision_ts_in).normalize()
    if train_window_str_in == "6M":
        return day_ts - pd.DateOffset(months=6)
    year_dict = {"2Y": 2, "3Y": 3, "5Y": 5, "10Y": 10}
    return day_ts - pd.DateOffset(years=year_dict[train_window_str_in])


"""
One Rolling Fit
"""


"""
Candidate Selection
"""


"""
Reference Fit (deterministic given the seed; used by the parallel check)
"""


