import os
import pandas as pd
from so import paths

"""
External Non-Price Sources (SPY dividends, 3-month T-bill rate)

The files are written by the ingest repository stock_overflow_infra into the quarantine, under the layout of so.paths, and
reach the development view only through Nicolas's refresh. This module reads them; it never imports the ingest. The file
format is the ingest's data contract, version 2 (stock_overflow_infra/docs/DATA_CONTRACT.md):

    store01_rawzone/spy_dividends/spy_dividends.csv
        date, available_ts, ex_date, record_date, pay_date, declared_date, amount_usd, distribution_type, currency,
        vintage_kind, ingest_run_id
    store01_rawzone/fred_dtb3/dtb3.csv
        date, available_ts, observation_date, value_pct, vintage_realtime_start, vintage_kind, ingest_run_id

Rules every reader applies (the same pattern as so.features.vix_features):
    - a direct read is refused inside the holdout runner (designs read through the DataContext);
    - the cutoff date is required; with the holdout guard on it must lie strictly before the replay boundary;
    - the header must equal the contract exactly (another version raises instead of being guessed);
    - date must be the New York date of available_ts (the refresh cuts the view on date, so the two must agree);
    - rows dated after the cutoff are dropped right after parsing; with the guard on, a row on or after the boundary raises.

Both sources are vintage sources: each row carries its own available_ts, and a revision is a later row with the same key.
The registry (so.core.point_in_time) collapses them to the release known at the decision.
"""

# DEFINE THE CONTRACT VERSION THIS MODULE READS
CONTRACT_VERSION_INT = 2
# DEFINE THE FILES AND THEIR COLUMNS (CONTRACT VERSION 2)
SPY_DIVIDENDS_FILE_NAME_STR = "spy_dividends.csv"
SPY_DIVIDENDS_COLUMN_STR_LIST = ["date", "available_ts", "ex_date", "record_date", "pay_date", "declared_date", "amount_usd",
                                 "distribution_type", "currency", "vintage_kind", "ingest_run_id"]
SPY_DIVIDENDS_KEY_STR_LIST = ["ex_date", "distribution_type"]
TBILL_3M_FILE_NAME_STR = "dtb3.csv"
TBILL_3M_COLUMN_STR_LIST = ["date", "available_ts", "observation_date", "value_pct", "vintage_realtime_start", "vintage_kind", "ingest_run_id"]
TBILL_3M_KEY_STR_LIST = ["observation_date"]
# DEFINE THE ROW KINDS THE CONTRACT ALLOWS
VINTAGE_KIND_SET = {"first_seen", "rule_based_backfill", "revision"}
# DEFINE THE NEW YORK TIME ZONE
NY_TZ_STR = "America/New_York"

# FUNCTION: CHECK A LOADER CUTOFF
def check_external_cutoff_date(cutoff_date_str_in, enforce_holdout_bool_in=True):
    """
    Raises unless the cutoff is given. When the holdout guard is on, the cutoff must lie strictly before the replay
    boundary (development: the active window start; inside the holdout evaluation: the day after the window end).

    Args:
        cutoff_date_str_in (str): Last date the caller may load (inclusive)
        enforce_holdout_bool_in (bool): Apply the active holdout. False keeps the caller's cutoff only

    Returns:
        datetime.date: The cutoff date
    """
    # IMPORT THE HOLDOUT BOUNDARY HERE (THE SAME DATE THE VIX LOADERS USE)
    from so.core.holdout import get_replay_boundary_date
    # RAISE WITHOUT A CUTOFF
    if cutoff_date_str_in is None:
        raise ValueError("❌ An external-source loader needs an explicit cutoff date (no default).")
    cutoff_date = pd.Timestamp(cutoff_date_str_in).date()
    # THE CALLER'S CUTOFF IS THE ONLY LIMIT WHEN THE GUARD IS OFF
    if not enforce_holdout_bool_in:
        return cutoff_date
    # RAISE IF THE CUTOFF REACHES THE BOUNDARY
    boundary_date = get_replay_boundary_date(None)
    if cutoff_date >= boundary_date:
        raise ValueError(f"❌ External-source cutoff {cutoff_date} is on or after the holdout boundary {boundary_date}.")
    return cutoff_date

# FUNCTION: READ ONE CONTRACT FILE AS TEXT AND CUT IT AT THE CUTOFF
def read_external_text_pdf(folder_path_str_in, file_name_str_in, column_str_list_in, cutoff_date_in, label_str_in, enforce_holdout_bool_in):
    """
    Reads the file with every cell as text, checks the header and the clock columns, and drops rows dated after the
    cutoff right after parsing.

    Args:
        folder_path_str_in (str): Folder ending with "/"
        file_name_str_in (str): File name
        column_str_list_in (list[str]): Contract columns, in order
        cutoff_date_in (datetime.date): Last date kept
        label_str_in (str): Name used in messages
        enforce_holdout_bool_in (bool): Apply the holdout boundary to the rows

    Returns:
        pd.DataFrame: Text cells, plus available_ts (New York) and date (datetime.date) parsed
    """
    # THE FILE MUST EXIST: A DECLARED SOURCE THAT IS NOT IN THE VIEW IS AN ERROR, NOT AN EMPTY FEED
    file_path_str = f"{folder_path_str_in.replace(chr(92), '/').rstrip('/')}/{file_name_str_in}"
    if not os.path.isfile(file_path_str):
        raise FileNotFoundError(f"❌ {label_str_in}: {file_path_str} is missing (not in this data tree yet).")
    text_pdf = pd.read_csv(file_path_str, dtype=str, keep_default_na=False)
    # THE HEADER IS THE CONTRACT; ANOTHER VERSION IS NOT GUESSED
    if list(text_pdf.columns) != column_str_list_in:
        raise ValueError(f"❌ {label_str_in}: the header is not data contract version {CONTRACT_VERSION_INT}: {list(text_pdf.columns)}")
    # PARSE THE CLOCK COLUMNS
    text_pdf["available_ts"] = pd.to_datetime(text_pdf["available_ts"], utc=True).dt.tz_convert(NY_TZ_STR)
    text_pdf["date"] = pd.to_datetime(text_pdf["date"]).dt.date
    # DROP THE ROWS AFTER THE CUTOFF IMMEDIATELY
    text_pdf = text_pdf[text_pdf["date"] <= cutoff_date_in].reset_index(drop=True)
    # THE REFRESH CUTS ON date: IT MUST BE THE NEW YORK DATE OF available_ts
    mismatch_int = int((text_pdf["date"] != text_pdf["available_ts"].dt.date).sum())
    if mismatch_int:
        raise ValueError(f"❌ {label_str_in}: {mismatch_int} rows whose date is not the New York date of available_ts")
    # ONLY THE ROW KINDS OF THE CONTRACT
    if not text_pdf["vintage_kind"].isin(VINTAGE_KIND_SET).all():
        raise ValueError(f"❌ {label_str_in}: a vintage_kind outside {sorted(VINTAGE_KIND_SET)}")
    # WITH THE GUARD ON, NO ROW ON OR AFTER THE BOUNDARY
    if enforce_holdout_bool_in and len(text_pdf):
        from so.core.holdout import get_replay_boundary_date
        boundary_date = get_replay_boundary_date(None)
        assert not (text_pdf["date"] >= boundary_date).any(), f"❌ {label_str_in}: a row on or after the holdout boundary {boundary_date}"
    return text_pdf

# FUNCTION: READ THE SPY DIVIDENDS
def read_spy_dividends_pdf(cutoff_date_str_in, raw_path_str_in=None, enforce_holdout_bool_in=True):
    """
    SPY distributions through a required cutoff (inclusive, on date = the New York date of available_ts).

    Args:
        cutoff_date_str_in (str): Last date kept (required; before the holdout boundary when the guard is on)
        raw_path_str_in (str | None): Override folder (tests); None = so.paths.LOCAL_SPY_DIVIDENDS_PATH_STR
        enforce_holdout_bool_in (bool): Apply the active holdout (False = the caller's cutoff only)

    Returns:
        pd.DataFrame: date, available_ts, ex_date, record_date, pay_date (datetime.date; declared_date may be NaT),
                      amount_usd (float), distribution_type, currency, vintage_kind, ingest_run_id; sorted by ex_date, available_ts
    """
    # A DESIGN INSIDE THE HOLDOUT RUNNER READS THROUGH THE DATA CONTEXT
    from so.core.point_in_time import raise_if_direct_read_blocked
    raise_if_direct_read_blocked()
    cutoff_date = check_external_cutoff_date(cutoff_date_str_in, enforce_holdout_bool_in)
    folder_path_str = raw_path_str_in or paths.LOCAL_SPY_DIVIDENDS_PATH_STR
    dividend_pdf = read_external_text_pdf(folder_path_str, SPY_DIVIDENDS_FILE_NAME_STR, SPY_DIVIDENDS_COLUMN_STR_LIST, cutoff_date,
                                          "SPY dividends", enforce_holdout_bool_in)
    # TYPES: DATES AND THE AMOUNT (declared_date IS EMPTY WHEN NO SOURCE GIVES IT)
    for column_str in ("ex_date", "record_date", "pay_date"):
        dividend_pdf[column_str] = pd.to_datetime(dividend_pdf[column_str]).dt.date
    dividend_pdf["declared_date"] = pd.to_datetime(dividend_pdf["declared_date"].replace("", None)).dt.date
    dividend_pdf["amount_usd"] = pd.to_numeric(dividend_pdf["amount_usd"], errors="raise").astype(float)
    # ONE ROW PER (EX-DATE, TYPE, RELEASE)
    if dividend_pdf.duplicated(SPY_DIVIDENDS_KEY_STR_LIST + ["available_ts"]).any():
        raise ValueError("❌ SPY dividends: two rows with the same ex_date, distribution_type and available_ts")
    return dividend_pdf.sort_values(["ex_date", "available_ts"]).reset_index(drop=True)

# FUNCTION: READ THE 3-MONTH T-BILL RATE (FRED DTB3, DISCOUNT BASIS, PERCENT)
def read_tbill_3m_pdf(cutoff_date_str_in, raw_path_str_in=None, enforce_holdout_bool_in=True):
    """
    DTB3 first releases and revisions through a required cutoff (inclusive, on date = the New York date of available_ts).

    Args:
        cutoff_date_str_in (str): Last date kept (required; before the holdout boundary when the guard is on)
        raw_path_str_in (str | None): Override folder (tests); None = so.paths.LOCAL_TBILL_3M_PATH_STR
        enforce_holdout_bool_in (bool): Apply the active holdout (False = the caller's cutoff only)

    Returns:
        pd.DataFrame: date, available_ts, observation_date, value_pct (float; NaN where FRED published "."),
                      vintage_realtime_start (datetime.date), vintage_kind, ingest_run_id; sorted by observation_date, available_ts
    """
    # A DESIGN INSIDE THE HOLDOUT RUNNER READS THROUGH THE DATA CONTEXT
    from so.core.point_in_time import raise_if_direct_read_blocked
    raise_if_direct_read_blocked()
    cutoff_date = check_external_cutoff_date(cutoff_date_str_in, enforce_holdout_bool_in)
    folder_path_str = raw_path_str_in or paths.LOCAL_TBILL_3M_PATH_STR
    rate_pdf = read_external_text_pdf(folder_path_str, TBILL_3M_FILE_NAME_STR, TBILL_3M_COLUMN_STR_LIST, cutoff_date,
                                      "3-month T-bill", enforce_holdout_bool_in)
    # TYPES: "." IS FRED'S "NO VALUE THAT DAY" AND BECOMES NaN; ANY OTHER TEXT MUST BE A NUMBER
    value_text_series = rate_pdf["value_pct"].where(rate_pdf["value_pct"] != ".")
    rate_pdf["value_pct"] = pd.to_numeric(value_text_series, errors="raise").astype(float)
    rate_pdf["observation_date"] = pd.to_datetime(rate_pdf["observation_date"]).dt.date
    rate_pdf["vintage_realtime_start"] = pd.to_datetime(rate_pdf["vintage_realtime_start"]).dt.date
    # A RELEASE MAY NOT PRECEDE THE DAY IT DESCRIBES
    if (rate_pdf["date"] <= rate_pdf["observation_date"]).any():
        raise ValueError("❌ 3-month T-bill: a row available on or before the date it describes")
    # ONE ROW PER (OBSERVATION, RELEASE)
    if rate_pdf.duplicated(TBILL_3M_KEY_STR_LIST + ["available_ts"]).any():
        raise ValueError("❌ 3-month T-bill: two rows with the same observation_date and available_ts")
    return rate_pdf.sort_values(["observation_date", "available_ts"]).reset_index(drop=True)
