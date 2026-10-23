import numpy as np
import pandas as pd
# IMPORT THE VIX SETTINGS AND THE VIX HELPERS
from so import vix_config
from so.features.vix_features import get_vix_prev_value_pdf, get_trailing_percentile_arr

"""
Daily Histories Kept Inside A Design (shared by the daily runner designs)

A design is called once per session, in time order, with a view that stops at the decision moment. These helpers keep
the rows the design has received so far, so each call only copies what is new (view.get_new). They never read a file
and never see anything the view does not show.

    DailyHistory   TSDAY rows (one per session): today's row and every earlier row, by column
    VixPrevHistory vix_level_prev, vix_term_prev and vix_pct250_prev per session, from VIX_DAILY and VIX3M_DAILY rows
                   (the previous date's close, at most STALE_MAX_SESSIONS sessions old), the same definitions as
                   so.features.vix_features
"""


# FUNCTION: A DATE-LIKE VALUE TO datetime.date
def get_day(value_in):
    """
    Args:
        value_in: str, date or Timestamp

    Returns:
        datetime.date: Day
    """
    # PANDAS PARSES EVERY STORED FORM
    return pd.Timestamp(value_in).date()


# CLASS: THE TSDAY ROWS SEEN SO FAR
class DailyHistory:
    """
    update(view) appends the TSDAY rows that became available since the previous call and returns today's row as a
    dict (None when today's row is missing). value_arr(column) is the column over every row received, in date order.
    """

    # FUNCTION: EMPTY HISTORY OF THE GIVEN COLUMNS
    def __init__(self, column_list_in, source_str_in="TSDAY"):
        """
        Args:
            column_list_in (list[str]): TSDAY columns to keep (date is always kept)
            source_str_in (str): Registered daily feature source
        """
        # ONE LIST PER COLUMN
        self.source_str = str(source_str_in)
        self.column_list = [column_str for column_str in column_list_in if column_str != "date"]
        self.date_list = []
        self.value_dict = {column_str: [] for column_str in self.column_list}

    # FUNCTION: APPEND THE NEW ROWS; RETURN TODAY'S ROW
    def update(self, view_in):
        """
        Args:
            view_in: DecisionView

        Returns:
            dict | None: column -> float for today's session
        """
        # ONLY THE ROWS SINCE THE PREVIOUS CALL ARE COPIED
        new_pdf = view_in.get_new(self.source_str, columns_in=["date"] + self.column_list)
        if len(new_pdf):
            self.date_list.extend(get_day(day) for day in new_pdf["date"])
            for column_str in self.column_list:
                self.value_dict[column_str].extend(pd.to_numeric(new_pdf[column_str], errors="coerce").astype(float).tolist())
        if not self.date_list or self.date_list[-1] != get_day(view_in.session_date):
            return None
        return {column_str: self.value_dict[column_str][-1] for column_str in self.column_list}

    # FUNCTION: ONE COLUMN AS AN ARRAY
    def value_arr(self, column_str_in):
        """
        Args:
            column_str_in (str): Column

        Returns:
            np.ndarray: Values of every row received, in date order
        """
        # A COPY THE CALLER MAY CHANGE
        return np.asarray(self.value_dict[column_str_in], dtype=float)


# CLASS: VIX _prev FEATURES OF EVERY SESSION SEEN SO FAR
class VixPrevHistory:
    """
    update(view) returns today's vix_level_prev, vix_term_prev and vix_pct250_prev. The first call computes every
    earlier session of the view (the stream may start years after the data), later calls one session each.
    """

    # FUNCTION: EMPTY STATE
    def __init__(self, stale_max_in=vix_config.STALE_MAX_SESSIONS, pct_window_in=vix_config.PCT_WINDOW_SESSIONS):
        """
        Args:
            stale_max_in (int): Largest accepted lag (sessions) of the previous close
            pct_window_in (int): Previous values of the percentile
        """
        # RAW DAILY ROWS AND ONE VALUE PER SESSION
        self.stale_max_int = int(stale_max_in)
        self.pct_window_int = int(pct_window_in)
        self.daily_dict = {"vix": {"date": [], "close": []}, "vix3m": {"date": [], "close": []}}
        self.session_list = []
        self.level_list = []
        self.term_list = []

    # FUNCTION: APPEND NEW DAILY ROWS OF ONE SERIES
    def _receive(self, view_in, source_str_in, series_str_in):
        """
        Args:
            view_in: DecisionView
            source_str_in (str): VIX_DAILY or VIX3M_DAILY
            series_str_in (str): vix or vix3m

        Returns:
            None
        """
        # ROWS WITH available_ts AT OR BEFORE THE MOMENT (THE PREVIOUS DATE'S CLOSE, KNOWN AT 16:15 THAT DATE)
        new_pdf = view_in.get_new(source_str_in, columns_in=["date", "close"])
        if len(new_pdf):
            self.daily_dict[series_str_in]["date"].extend(get_day(day) for day in new_pdf["date"])
            self.daily_dict[series_str_in]["close"].extend(pd.to_numeric(new_pdf["close"], errors="coerce").astype(float).tolist())

    # FUNCTION: _prev VALUES OF SOME SESSIONS
    def _prev_value_arr(self, session_list_in, series_str_in):
        """
        Args:
            session_list_in (list): Session dates (a tail long enough for the staleness count)
            series_str_in (str): vix or vix3m

        Returns:
            np.ndarray: Value per session (NaN unless ok)
        """
        # THE SHARED DEFINITION ON THE ROWS RECEIVED SO FAR
        daily_pdf = pd.DataFrame(self.daily_dict[series_str_in])
        if daily_pdf.empty:
            return np.full(len(session_list_in), np.nan)
        prev_pdf = get_vix_prev_value_pdf(list(session_list_in), daily_pdf, vix_config.SERIES_START_DATE_DICT[series_str_in],
                                          self.stale_max_int)
        return prev_pdf["value"].to_numpy(dtype=float)

    # FUNCTION: TODAY'S THREE FEATURES
    def update(self, view_in):
        """
        Args:
            view_in: DecisionView

        Returns:
            dict: vix_level_prev, vix_term_prev, vix_pct250_prev (NaN when unknown)
        """
        # NEW DAILY ROWS, THEN THE SESSIONS NOT YET COMPUTED
        self._receive(view_in, "VIX_DAILY", "vix")
        self._receive(view_in, "VIX3M_DAILY", "vix3m")
        bar_session_list = [get_day(day) for day in view_in.get_bar_array_dict()["session_date_list"]]
        new_count = len(bar_session_list) - len(self.session_list)
        if new_count > 0:
            tail_start = max(0, len(self.session_list) - (self.stale_max_int + 2))
            tail_list = bar_session_list[tail_start:]
            level_arr = self._prev_value_arr(tail_list, "vix")[-new_count:]
            vix3m_arr = self._prev_value_arr(tail_list, "vix3m")[-new_count:]
            with np.errstate(invalid="ignore", divide="ignore"):
                term_arr = level_arr / vix3m_arr
            self.session_list.extend(bar_session_list[-new_count:])
            self.level_list.extend(level_arr.tolist())
            self.term_list.extend(term_arr.tolist())
        level_float = float(self.level_list[-1]) if self.level_list else np.nan
        term_float = float(self.term_list[-1]) if self.term_list else np.nan
        window_arr = np.asarray(self.level_list[-(self.pct_window_int + 1):], dtype=float)
        pct_float = float(get_trailing_percentile_arr(window_arr, self.pct_window_int)[-1]) if len(window_arr) == self.pct_window_int + 1 else np.nan
        return {"vix_level_prev": level_float, "vix_term_prev": term_float, "vix_pct250_prev": pct_float}

    # FUNCTION: THE LEVEL HISTORY FROM A SESSION ON
    def level_since_arr(self, session_date_in):
        """
        Args:
            session_date_in: First session kept

        Returns:
            np.ndarray: vix_level_prev of the sessions on or after it, through today
        """
        # THE SESSIONS ARE IN ORDER
        start_day = get_day(session_date_in)
        start_idx = int(np.searchsorted(np.asarray(self.session_list, dtype=object), start_day, side="left")) if self.session_list else 0
        return np.asarray(self.level_list[start_idx:], dtype=float)

    # FUNCTION: THE TERM HISTORY FROM A SESSION ON
    def term_since_arr(self, session_date_in):
        """
        Args:
            session_date_in: First session kept

        Returns:
            np.ndarray: vix_term_prev of the sessions on or after it, through today
        """
        # THE SESSIONS ARE IN ORDER
        start_day = get_day(session_date_in)
        start_idx = int(np.searchsorted(np.asarray(self.session_list, dtype=object), start_day, side="left")) if self.session_list else 0
        return np.asarray(self.term_list[start_idx:], dtype=float)
