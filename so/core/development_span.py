import pandas as pd
# IMPORT THE SHARED CONFIGURATION
from so import config

"""
Development Span (the bars a development notebook may replay)

The development end is the session an embargo before the active holdout start (so.core.holdout.get_development_end_date).
Prices are loaded only through that session. The holdout start is appended as a date so the embargo index can be
computed; that session's prices are not read. A caller that already holds bars passes them in and nothing is loaded.
"""

# FUNCTION: BARS THROUGH THE DEVELOPMENT END, PLUS THE DATE ANCHOR
def get_development_ohlcv_dict(embargo_sessions_in, ohlcv_pdf_in=None):
    """
    Cuts minute bars at the development end for one embargo. The returned session list used to locate that end
    includes the holdout start as a date and does not include its prices.

    Args:
        embargo_sessions_in (int): Sessions of embargo (at least 1)
        ohlcv_pdf_in (pd.DataFrame | None): Bars already loaded (None reads the raw folder through the guard)

    Returns:
        dict: ohlcv_array_dict, development_end, window_start, anchor_session_list, last_price_date
    """
    # IMPORT THE BOUNDARY AND THE ARRAY BUILDER HERE
    from so.core.holdout import get_active_holdout_window_dict, get_development_end_date, get_date, get_truncated_ohlcv_dict
    from so.core.trade_execution import get_ohlcv_array_dict
    # LOAD THROUGH THE DAY BEFORE THE WINDOW WHEN THE CALLER DID NOT PASS BARS
    if ohlcv_pdf_in is None:
        from so.core.raw_data import get_complete_ohlcv_pdf
        ohlcv_pdf_in = get_complete_ohlcv_pdf()
    # THE WINDOW START IS A DATE. PRICES ON THAT SESSION ARE NOT IN THE GUARDED LOAD
    window_start = get_date(get_active_holdout_window_dict()["start"])
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf_in)
    price_session_list = [get_date(session_date) for session_date in ohlcv_array_dict["session_date_list"]]
    if not price_session_list or price_session_list[-1] >= window_start:
        raise ValueError("development bars must end strictly before the holdout start.")
    # THE ANCHOR LIST IS THE PRICE SESSIONS PLUS THE WINDOW START, SO THE EMBARGO INDEX IS DEFINED
    anchor_session_list = price_session_list + [window_start]
    development_end = get_development_end_date(int(embargo_sessions_in), anchor_session_list)
    # DROP THE EMBARGO SESSIONS THAT SIT BETWEEN THE DEVELOPMENT END AND THE WINDOW
    cut_dict = get_truncated_ohlcv_dict(ohlcv_array_dict, development_end)
    return {"ohlcv_array_dict": cut_dict, "development_end": development_end, "window_start": window_start,
            "anchor_session_list": anchor_session_list, "last_price_date": price_session_list[-1]}

# FUNCTION: DEVELOPMENT VALIDATION PERIODS ON THOSE BARS
def get_development_period_pdf(anchor_session_list_in, ohlcv_array_dict_in, embargo_sessions_in, train_years_in):
    """
    Validation quarters anchored on the development end, made non-overlapping. There is no test window.

    Args:
        anchor_session_list_in (list): Sessions that include the holdout start
        ohlcv_array_dict_in (dict): Bars through the development end
        embargo_sessions_in (int): Embargo
        train_years_in (int): Fold-schedule training length (not a model's rolling window)

    Returns:
        tuple: period_pdf, fold_pdf
    """
    # IMPORT THE SCHEDULE AND THE PERIOD BUILDER HERE
    from so.core.schedule import get_development_fold_pdf
    from so.core.continuous_replay import get_replay_period_pdf
    # BUILD THE QUARTERS, THEN THE NON-OVERLAPPING PERIODS ON THE PRICE SESSIONS
    fold_pdf = get_development_fold_pdf(anchor_session_list_in, int(embargo_sessions_in), [int(train_years_in)],
                                       validation_window_months_in=config.VALIDATION_WINDOW_MONTHS,
                                       step_months_in=config.WALK_FORWARD_STEP_MONTHS)
    period_pdf = get_replay_period_pdf(fold_pdf, ohlcv_array_dict_in["session_date_list"])
    return period_pdf, fold_pdf
