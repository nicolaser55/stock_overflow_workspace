import numpy as np
import pandas as pd

"""
Total-Return Schedule (R4b, decided 2026-10-29; rules decided by Nicolas 2026-11-08 and 2026-11-09)

Every return the referee compares is a total return: SPY shares earn their dividends and cash earns the 3-month T-bill
rate. The engines read one schedule per session, carried in the price bundle (ohlcv_array_dict):

    dividend_per_share_arr[s]   dollars per share credited at the open of session s to the shares held at the previous
                                close: the SPY distribution whose ex-date is session s (or, if that ex-date has no
                                session in the data, the first session after it)
    cash_growth_arr[s]          interest earned by one dollar of cash from the close of session s-1 to the close of
                                session s, credited at the open of session s: y x calendar days / 365, where y is the
                                investment yield of day s-1's first-release DTB3 rate (0 for the first session)
    total_return_basis_str      "total_return" when the schedule comes from the registered sources, "price_only" for a
                                bundle built without them (synthetic tests): then both arrays are zeros and every
                                result equals the price-return result

Rules:
    - The first release of each value is used (vintage_kind first_seen or rule_based_backfill), never a later revision,
      so a past result does not change when a source is revised (decided 2026-11-09).
    - Discount basis to investment yield for a 91-day bill: y = 365 d / (360 - 91 d), d = DTB3 / 100.
    - A session whose previous day has no value (FRED's ".", or a federal holiday that is an NYSE session) carries the
      last value known.
    - This is accounting, not a decision input: day t's rate is used for the night t -> t+1 although FRED posts it on
      t+1 at 16:30. Designs read the two sources only through the DataContext, with their feature clocks.
"""

# DEFINE THE BASIS LABELS
TOTAL_RETURN_BASIS_STR = "total_return"
PRICE_ONLY_BASIS_STR = "price_only"
# DEFINE THE TERM OF THE 3-MONTH BILL USED BY THE YIELD CONVERSION
BILL_TERM_DAYS_INT = 91
# DEFINE THE ROW KINDS THAT ARE A FIRST RELEASE
FIRST_RELEASE_KIND_SET = {"first_seen", "rule_based_backfill"}


# FUNCTION: DISCOUNT RATE TO INVESTMENT YIELD
def get_investment_yield_arr(discount_pct_in):
    """
    Args:
        discount_pct_in (array-like): DTB3 values in percent (discount basis)

    Returns:
        np.ndarray: Investment yields as decimals (365-day basis)
    """
    # d AS A DECIMAL, THEN THE 91-DAY BOND-EQUIVALENT YIELD
    discount_arr = np.asarray(discount_pct_in, dtype=float) / 100.0
    return 365.0 * discount_arr / (360.0 - BILL_TERM_DAYS_INT * discount_arr)


# FUNCTION: ZERO SCHEDULE (PRICE RETURNS)
def get_zero_schedule_dict(session_count_in):
    """
    Args:
        session_count_in (int): Sessions in the bundle

    Returns:
        dict: dividend_per_share_arr, cash_growth_arr (zeros), total_return_basis_str "price_only"
    """
    # NO DIVIDEND, NO INTEREST
    return {"dividend_per_share_arr": np.zeros(int(session_count_in), dtype=float),
            "cash_growth_arr": np.zeros(int(session_count_in), dtype=float),
            "total_return_basis_str": PRICE_ONLY_BASIS_STR}


# FUNCTION: BUILD THE SCHEDULE FOR A SESSION LIST
def get_total_return_schedule_dict(session_date_list_in, dividend_pdf_in, rate_pdf_in):
    """
    Args:
        session_date_list_in (list): Session dates of the bundle (sorted)
        dividend_pdf_in (pd.DataFrame): so.core.external_data.read_spy_dividends_pdf output (ex_date, amount_usd, vintage_kind)
        rate_pdf_in (pd.DataFrame): so.core.external_data.read_tbill_3m_pdf output (observation_date, value_pct, vintage_kind)

    Returns:
        dict: dividend_per_share_arr, cash_growth_arr, total_return_basis_str "total_return"
    """
    # SESSION DATES AS NUMPY DAYS
    session_day_arr = pd.to_datetime(pd.Series(list(session_date_list_in))).to_numpy(dtype="datetime64[D]")
    session_count = len(session_day_arr)
    schedule_dict = get_zero_schedule_dict(session_count)
    schedule_dict["total_return_basis_str"] = TOTAL_RETURN_BASIS_STR
    if session_count == 0:
        return schedule_dict
    # DIVIDENDS: FIRST RELEASES, EACH ON THE FIRST SESSION ON OR AFTER ITS EX-DATE (ONE THAT FALLS AFTER THE LAST SESSION IS NOT IN THIS SPAN)
    dividend_pdf = dividend_pdf_in[dividend_pdf_in["vintage_kind"].isin(FIRST_RELEASE_KIND_SET)]
    if len(dividend_pdf):
        ex_day_arr = pd.to_datetime(pd.Series(list(dividend_pdf["ex_date"]))).to_numpy(dtype="datetime64[D]")
        position_arr = np.searchsorted(session_day_arr, ex_day_arr, side="left")
        amount_arr = dividend_pdf["amount_usd"].to_numpy(dtype=float)
        inside_bool_arr = (position_arr < session_count) & (ex_day_arr >= session_day_arr[0])
        np.add.at(schedule_dict["dividend_per_share_arr"], position_arr[inside_bool_arr], amount_arr[inside_bool_arr])
    # RATES: FIRST RELEASES WITH A VALUE, BY OBSERVATION DATE
    rate_pdf = rate_pdf_in[rate_pdf_in["vintage_kind"].isin(FIRST_RELEASE_KIND_SET) & rate_pdf_in["value_pct"].notna()]
    rate_pdf = rate_pdf.drop_duplicates("observation_date", keep="first").sort_values("observation_date")
    if session_count > 1:
        observation_day_arr = pd.to_datetime(pd.Series(list(rate_pdf["observation_date"]))).to_numpy(dtype="datetime64[D]")
        # FOR EACH NIGHT s-1 -> s: THE LAST VALUE OBSERVED ON OR BEFORE SESSION s-1 (CARRIES OVER DAYS WITHOUT A VALUE)
        previous_day_arr = session_day_arr[:-1]
        value_position_arr = np.searchsorted(observation_day_arr, previous_day_arr, side="right") - 1
        if (value_position_arr < 0).any():
            raise ValueError("❌ Total-return schedule: no T-bill rate on or before the first session of the span.")
        yield_arr = get_investment_yield_arr(rate_pdf["value_pct"].to_numpy(dtype=float)[value_position_arr])
        day_count_arr = (session_day_arr[1:] - previous_day_arr).astype(int)
        schedule_dict["cash_growth_arr"][1:] = yield_arr * day_count_arr / 365.0
    return schedule_dict


# FUNCTION: A COPY OF A BUNDLE WITH ITS SCHEDULE
def get_bundle_with_schedule_dict(ohlcv_array_dict_in, schedule_dict_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Price bundle
        schedule_dict_in (dict): Output of get_total_return_schedule_dict or get_zero_schedule_dict

    Returns:
        dict: The bundle with the three schedule keys set (the price arrays are shared, not copied)
    """
    # ONE VALUE PER SESSION
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    for key_str in ("dividend_per_share_arr", "cash_growth_arr"):
        if len(schedule_dict_in[key_str]) != session_count:
            raise ValueError(f"❌ Total-return schedule: {key_str} has {len(schedule_dict_in[key_str])} values for {session_count} sessions.")
    return {**ohlcv_array_dict_in, **schedule_dict_in}


# FUNCTION: LOAD THE SOURCES AND ATTACH THE SCHEDULE (DEVELOPMENT VIEW, RUNNER OR HOLDOUT EVALUATION)
def get_total_return_bundle_dict(ohlcv_array_dict_in, cutoff_date_str_in, enforce_holdout_bool_in=True, frame_tuple_in=None):
    """
    Args:
        ohlcv_array_dict_in (dict): Price bundle
        cutoff_date_str_in (str): Last date the source loaders may read (the bundle's last session, or the window end)
        enforce_holdout_bool_in (bool): Apply the active holdout boundary to the loaders
        frame_tuple_in (tuple | None): (dividend_pdf, rate_pdf) already loaded (the holdout evaluation passes its own)

    Returns:
        dict: The bundle with a total-return schedule
    """
    # LOAD THROUGH THE REGISTERED LOADERS UNLESS THE FRAMES ARE GIVEN
    if frame_tuple_in is None:
        from so.core.external_data import read_spy_dividends_pdf, read_tbill_3m_pdf
        frame_tuple_in = (read_spy_dividends_pdf(cutoff_date_str_in, enforce_holdout_bool_in=enforce_holdout_bool_in),
                          read_tbill_3m_pdf(cutoff_date_str_in, enforce_holdout_bool_in=enforce_holdout_bool_in))
    dividend_pdf, rate_pdf = frame_tuple_in
    schedule_dict = get_total_return_schedule_dict(ohlcv_array_dict_in["session_date_list"], dividend_pdf, rate_pdf)
    return get_bundle_with_schedule_dict(ohlcv_array_dict_in, schedule_dict)


# FUNCTION: THE OPEN-OF-SESSION CREDIT EVENT
def get_session_open_event_dict(ohlcv_array_dict_in, session_idx_in, session_date_in):
    """
    Args:
        ohlcv_array_dict_in (dict): Bundle (a bundle without a schedule credits nothing)
        session_idx_in (int): Session position in the bundle
        session_date_in: Session date

    Returns:
        dict: session_idx, session_date, dividend_per_share, cash_growth
    """
    # READ THE SCHEDULE (ZERO WHEN THE BUNDLE HAS NONE)
    session_idx = int(session_idx_in)
    dividend_arr = ohlcv_array_dict_in.get("dividend_per_share_arr")
    growth_arr = ohlcv_array_dict_in.get("cash_growth_arr")
    return {"session_idx": session_idx, "session_date": session_date_in,
            "dividend_per_share": float(dividend_arr[session_idx]) if dividend_arr is not None else 0.0,
            "cash_growth": float(growth_arr[session_idx]) if growth_arr is not None else 0.0}
