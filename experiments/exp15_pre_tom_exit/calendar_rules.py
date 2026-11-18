from datetime import date, timedelta

"""
Scheduled NYSE holiday rules for exp15_pre_tom_exit (no pandas_market_calendars, no so.core.datetime_utils).

A design-calendar session is a weekday that is not a scheduled holiday. Unscheduled closures (listed in config)
are weekdays and are not scheduled holidays, so they stay in the day count. Day T and offsets use this calendar
only. The design never imports market prices here.
"""

# IMPORT THE EXPERIMENT CONSTANTS (ERA DATES AND WINDOW SPECS)
from experiments.exp15_pre_tom_exit import config as exp_config


# FUNCTION: EASTER SUNDAY (ANONYMOUS GREGORIAN ALGORITHM)
def get_easter_sunday_date(year_int_in):
    """
    Gregorian Easter Sunday for the given year (Meeus/Jones/Butcher anonymous algorithm).

    Args:
        year_int_in (int): Calendar year

    Returns:
        date: Easter Sunday
    """
    # ANONYMOUS GREGORIAN EASTER
    year_int = int(year_int_in)
    a_int = year_int % 19
    b_int = year_int // 100
    c_int = year_int % 100
    d_int = b_int // 4
    e_int = b_int % 4
    f_int = (b_int + 8) // 25
    g_int = (b_int - f_int + 1) // 3
    h_int = (19 * a_int + b_int - d_int - g_int + 15) % 30
    i_int = c_int // 4
    k_int = c_int % 4
    l_int = (32 + 2 * e_int + 2 * i_int - h_int - k_int) % 7
    m_int = (a_int + 11 * h_int + 22 * l_int) // 451
    month_int = (h_int + l_int - 7 * m_int + 114) // 31
    day_int = ((h_int + l_int - 7 * m_int + 114) % 31) + 1
    return date(year_int, month_int, day_int)


# FUNCTION: NTH WEEKDAY OF A MONTH
def get_nth_weekday_date(year_int_in, month_int_in, weekday_int_in, n_int_in):
    """
    The n-th weekday in a month (weekday: Monday=0 .. Sunday=6).

    Args:
        year_int_in (int): Year
        month_int_in (int): Month 1-12
        weekday_int_in (int): Target weekday
        n_int_in (int): 1-based occurrence

    Returns:
        date: That day
    """
    # WALK FROM THE FIRST OF THE MONTH
    cursor_date = date(int(year_int_in), int(month_int_in), 1)
    while cursor_date.weekday() != int(weekday_int_in):
        cursor_date += timedelta(days=1)
    return cursor_date + timedelta(weeks=int(n_int_in) - 1)


# FUNCTION: LAST WEEKDAY OF A MONTH
def get_last_weekday_date(year_int_in, month_int_in, weekday_int_in):
    """
    The last weekday in a month (weekday: Monday=0 .. Sunday=6).

    Args:
        year_int_in (int): Year
        month_int_in (int): Month 1-12
        weekday_int_in (int): Target weekday

    Returns:
        date: That day
    """
    # STEP BACK FROM THE NEXT MONTH'S FIRST DAY
    if int(month_int_in) == 12:
        cursor_date = date(int(year_int_in) + 1, 1, 1) - timedelta(days=1)
    else:
        cursor_date = date(int(year_int_in), int(month_int_in) + 1, 1) - timedelta(days=1)
    while cursor_date.weekday() != int(weekday_int_in):
        cursor_date -= timedelta(days=1)
    return cursor_date


# FUNCTION: OBSERVE A FIXED MONTH-DAY WITH WEEKEND RULES
def get_observed_fixed_date(year_int_in, month_int_in, day_int_in, saturday_to_friday_bool_in=True):
    """
    Fixed calendar holiday with weekend observance. Sunday always moves to Monday. Saturday moves to Friday when
    saturday_to_friday_bool_in is True; otherwise Saturday is not observed (NYSE New Year's rule).

    Args:
        year_int_in (int): Year
        month_int_in (int): Month
        day_int_in (int): Day of month
        saturday_to_friday_bool_in (bool): Observe Saturday on Friday

    Returns:
        date | None: Observed holiday, or None when Saturday is not observed
    """
    # THE NOMINAL DATE
    nominal_date = date(int(year_int_in), int(month_int_in), int(day_int_in))
    if nominal_date.weekday() == 6:
        return nominal_date + timedelta(days=1)
    if nominal_date.weekday() == 5:
        if saturday_to_friday_bool_in:
            return nominal_date - timedelta(days=1)
        return None
    return nominal_date


# FUNCTION: SCHEDULED NYSE HOLIDAYS IN ONE YEAR
def get_scheduled_holiday_set(year_int_in):
    """
    Every scheduled NYSE full-day holiday date in the year (observed dates).

    Args:
        year_int_in (int): Year

    Returns:
        set[date]: Holiday dates
    """
    # BUILD THE SET FROM THE PUBLISHED RULES
    year_int = int(year_int_in)
    holiday_set = set()
    new_year_date = get_observed_fixed_date(year_int, 1, 1, saturday_to_friday_bool_in=False)
    if new_year_date is not None:
        holiday_set.add(new_year_date)
    # NEW YEAR ON A SATURDAY OF YEAR+1 IS NOT OBSERVED ON DEC 31 OF YEAR (NYSE RULE)
    holiday_set.add(get_nth_weekday_date(year_int, 1, 0, 3))
    holiday_set.add(get_nth_weekday_date(year_int, 2, 0, 3))
    holiday_set.add(get_easter_sunday_date(year_int) - timedelta(days=2))
    holiday_set.add(get_last_weekday_date(year_int, 5, 0))
    if year_int >= int(exp_config.JUNETEENTH_FIRST_YEAR_INT):
        juneteenth_date = get_observed_fixed_date(year_int, 6, 19, saturday_to_friday_bool_in=True)
        if juneteenth_date is not None:
            holiday_set.add(juneteenth_date)
    july4_date = get_observed_fixed_date(year_int, 7, 4, saturday_to_friday_bool_in=True)
    if july4_date is not None:
        holiday_set.add(july4_date)
    holiday_set.add(get_nth_weekday_date(year_int, 9, 0, 1))
    holiday_set.add(get_nth_weekday_date(year_int, 11, 3, 4))
    christmas_date = get_observed_fixed_date(year_int, 12, 25, saturday_to_friday_bool_in=True)
    if christmas_date is not None:
        holiday_set.add(christmas_date)
    return holiday_set


# FUNCTION: WHETHER A DATE IS A SCHEDULED HOLIDAY
def is_scheduled_holiday_bool(day_in):
    """
    Args:
        day_in (date): Calendar day

    Returns:
        bool: True when the day is a scheduled NYSE full-day holiday
    """
    # COMPARE TO THE YEAR'S SET
    day = day_in if isinstance(day_in, date) else date(day_in.year, day_in.month, day_in.day)
    return day in get_scheduled_holiday_set(day.year)


# FUNCTION: WHETHER A DATE IS A DESIGN-CALENDAR SESSION
def is_design_session_bool(day_in):
    """
    A design session is a Monday-Friday that is not a scheduled holiday. Unscheduled closures remain sessions.

    Args:
        day_in (date): Calendar day

    Returns:
        bool: True when the day counts in the design's trading-day list
    """
    # WEEKDAY AND NOT A SCHEDULED HOLIDAY
    day = day_in if isinstance(day_in, date) else date(day_in.year, day_in.month, day_in.day)
    return day.weekday() < 5 and not is_scheduled_holiday_bool(day)


# FUNCTION: NEXT DESIGN-CALENDAR SESSION STRICTLY AFTER A DAY
def get_next_design_session_date(day_in):
    """
    Args:
        day_in (date): Starting day (not included)

    Returns:
        date: Next design-calendar session
    """
    # STEP FORWARD ONE CALENDAR DAY AT A TIME
    cursor_date = (day_in if isinstance(day_in, date) else date(day_in.year, day_in.month, day_in.day)) + timedelta(days=1)
    while not is_design_session_bool(cursor_date):
        cursor_date += timedelta(days=1)
    return cursor_date


# FUNCTION: PREVIOUS DESIGN-CALENDAR SESSION STRICTLY BEFORE A DAY
def get_prev_design_session_date(day_in):
    """
    Args:
        day_in (date): Starting day (not included)

    Returns:
        date: Previous design-calendar session
    """
    # STEP BACKWARD
    cursor_date = (day_in if isinstance(day_in, date) else date(day_in.year, day_in.month, day_in.day)) - timedelta(days=1)
    while not is_design_session_bool(cursor_date):
        cursor_date -= timedelta(days=1)
    return cursor_date


# FUNCTION: DESIGN-CALENDAR SESSIONS IN A MONTH
def get_month_design_session_list(year_int_in, month_int_in):
    """
    Args:
        year_int_in (int): Year
        month_int_in (int): Month 1-12

    Returns:
        list[date]: Design sessions in chronological order
    """
    # EVERY DAY OF THE MONTH THAT COUNTS
    year_int = int(year_int_in)
    month_int = int(month_int_in)
    if month_int == 12:
        end_date = date(year_int + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(year_int, month_int + 1, 1) - timedelta(days=1)
    cursor_date = date(year_int, month_int, 1)
    session_list = []
    while cursor_date <= end_date:
        if is_design_session_bool(cursor_date):
            session_list.append(cursor_date)
        cursor_date += timedelta(days=1)
    return session_list


# FUNCTION: DAY T OF A MONTH
def get_month_t_date(year_int_in, month_int_in):
    """
    Last design-calendar session of the month.

    Args:
        year_int_in (int): Year
        month_int_in (int): Month

    Returns:
        date: Day T
    """
    # THE LAST ENTRY OF THE MONTH LIST
    session_list = get_month_design_session_list(year_int_in, month_int_in)
    if not session_list:
        raise ValueError(f"no design sessions in {year_int_in}-{month_int_in:02d}")
    return session_list[-1]


# FUNCTION: SESSION AT OFFSET N FROM T
def get_offset_from_t_date(t_date_in, offset_int_in):
    """
    Trading-day offset from T on the design calendar. offset 0 is T; negative is before T.

    Args:
        t_date_in (date): Day T
        offset_int_in (int): Offset

    Returns:
        date: The session at that offset
    """
    # WALK THE DESIGN CALENDAR
    offset_int = int(offset_int_in)
    cursor_date = t_date_in if isinstance(t_date_in, date) else date(t_date_in.year, t_date_in.month, t_date_in.day)
    if offset_int == 0:
        return cursor_date
    step_int = 1 if offset_int > 0 else -1
    remaining_int = abs(offset_int)
    while remaining_int > 0:
        cursor_date = cursor_date + timedelta(days=step_int)
        if is_design_session_bool(cursor_date):
            remaining_int -= 1
    return cursor_date


# FUNCTION: SETTLEMENT ERA NAME ON DAY T
def get_settlement_era_str(t_date_in):
    """
    Era in force on the month's day T (SEC compliance dates in config).

    Args:
        t_date_in (date): Day T

    Returns:
        str: "t3", "t2" or "t1"
    """
    # COMPARE TO THE ERA BOUNDARIES
    t_date = t_date_in if isinstance(t_date_in, date) else date(t_date_in.year, t_date_in.month, t_date_in.day)
    if t_date < exp_config.SETTLEMENT_T2_START_DATE:
        return "t3"
    if t_date < exp_config.SETTLEMENT_T1_START_DATE:
        return "t2"
    return "t1"


# FUNCTION: INCLUSIVE OFFSET PAIR FOR ONE CANDIDATE AND ERA
def get_window_offset_tuple(candidate_str_in, era_str_in):
    """
    Args:
        candidate_str_in (str): Candidate name
        era_str_in (str): Era key

    Returns:
        tuple[int, int]: (start_offset, end_offset) inclusive, both <= -2 for this grid
    """
    # LOOK UP THE BASE WIDTH, THEN APPLY THE SHIFT RULE
    candidate_str = str(candidate_str_in)
    if candidate_str not in exp_config.CANDIDATE_WINDOW_DICT:
        raise ValueError(f"unknown candidate {candidate_str!r}")
    start_int, end_int = exp_config.CANDIDATE_WINDOW_DICT[candidate_str]
    settlement_str = exp_config.CANDIDATE_SETTLEMENT_DICT[candidate_str]
    if settlement_str == "fixed":
        return int(start_int), int(end_int)
    if settlement_str != "shift":
        raise ValueError(f"unknown settlement mode {settlement_str!r}")
    shift_int = int(exp_config.SETTLEMENT_SHIFT_DICT[str(era_str_in)])
    return int(start_int) + shift_int, int(end_int) + shift_int


# FUNCTION: CASH-WINDOW DATES FOR ONE MONTH AND CANDIDATE
def get_cash_window_date_set(year_int_in, month_int_in, candidate_str_in):
    """
    Design-calendar dates in the candidate's cash window for that month. Era is taken from that month's T.

    Args:
        year_int_in (int): Year
        month_int_in (int): Month
        candidate_str_in (str): Candidate name

    Returns:
        set[date]: Inclusive cash-window sessions
    """
    # OFFSETS FROM THIS MONTH'S T
    t_date = get_month_t_date(year_int_in, month_int_in)
    era_str = get_settlement_era_str(t_date)
    start_int, end_int = get_window_offset_tuple(candidate_str_in, era_str)
    return {get_offset_from_t_date(t_date, offset_int) for offset_int in range(start_int, end_int + 1)}


# FUNCTION: WHETHER THE NEXT DESIGN SESSION AFTER A DECISION DAY IS IN A CASH WINDOW
def is_next_session_in_cash_window_bool(decision_day_in, candidate_str_in):
    """
    weight(s)=0 when the next design-calendar session after the decision day lies in that session's month window.

    Args:
        decision_day_in (date): Decision session date
        candidate_str_in (str): Candidate name

    Returns:
        bool: True when the next design session is a cash-window day
    """
    # NEXT DESIGN DAY, THEN THAT MONTH'S WINDOW
    decision_day = decision_day_in if isinstance(decision_day_in, date) else date(
        decision_day_in.year, decision_day_in.month, decision_day_in.day)
    next_day = get_next_design_session_date(decision_day)
    window_set = get_cash_window_date_set(next_day.year, next_day.month, candidate_str_in)
    return next_day in window_set
