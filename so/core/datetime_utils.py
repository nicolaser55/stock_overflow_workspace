import pandas as pd
import tzlocal
import pytz
from datetime import timedelta
import importlib.util

# FUNCTION: CHECK IF THE PACKAGE IS INSTALLED
def check_package_installed(package_name_str_in):
    # CHECK IF THE PACKAGE IS INSTALLED
    if importlib.util.find_spec(package_name_str_in) is not None:
        # RETURN TRUE
        return True
    # RETURN FALSE
    return False

# PRE-DEFINE THE NYSE CALENDAR
nyse_calendar = None
# DEFINE PACKAGE NAME
package_name_str = "pandas_market_calendars"
# IF THE PACKAGE IS INSTALLED, IMPORT IT
if check_package_installed(package_name_str):
    # IMPORT THE PACKAGE
    import pandas_market_calendars as mcal
    # COLLECT THE NYSE CALENDAR
    nyse_calendar = mcal.get_calendar("NYSE")
# ELSE RAISE AN ERROR
else:
    # RAISE AN ERROR
    print(f"⚠️ Package '{package_name_str}' is not installed")

# GET THE LOCAL TIMEZONE NAME
local_tz_name = tzlocal.get_localzone_name()
# COLLECT LOCAL TIMEZONE OBJECT
local_tz = pytz.timezone(local_tz_name)
# GET THE NEW YORK TIMEZONE
ny_tz = pytz.timezone("America/New_York")


# FUNCTION: GET DATAFRAME FOR A SPECIFIC DATE
def get_date_pdf(pdf_in, date_str_in, alert_in=True):
    """
    Extracts data for a specific date from a complete dataset
    
    Args:
        pdf_in: Complete DataFrame containing data
        date_str_in: Date string to filter data for
        alert_in: Whether to alert if the date is not found
    Returns:
        DataFrame containing only data for specified date
    """
    # INPUT VALIDATION: CHECK IF PDF_IN IS A PANDAS DATAFRAME
    if not isinstance(pdf_in, pd.DataFrame):
        # RAISE AN ERROR
        raise TypeError("pdf_in must be a pandas DataFrame")
    # INPUT VALIDATION: CHECK IF DATE_STR_IN IS A STRING
    if not isinstance(date_str_in, str):
        # RAISE AN ERROR
        raise TypeError("date_str_in must be a string")
    # INPUT VALIDATION: CHECK IF ALERT_IN IS A BOOLEAN
    if not isinstance(alert_in, bool):
        # RAISE AN ERROR
        raise TypeError("alert_in must be a boolean")
    # INPUT VALIDATION: CHECK IF PDF_IN CONTAINS THE REQUIRED COLUMNS
    if "date" not in pdf_in.columns:
        # RAISE AN ERROR
        raise ValueError("DataFrame must contain 'date' columns")
    # CONVERT DATE TO DATE OBJECT
    try:
        date_object = pd.to_datetime(date_str_in).date()
    # IF THE DATE IS NOT CONVERTED
    except:
        # RAISE AN ERROR
        raise ValueError("Invalid date string format")
    # GET THE DATAFRAME FOR THE SPECIFIC DATE
    date_pdf = pdf_in[pd.to_datetime(pdf_in.date).dt.date == date_object].copy()
    # IF THE DATAFRAME IS EMPTY, RETURN AN EMPTY DATAFRAME
    if date_pdf.empty:
        # IF THE DATE IS NOT FOUND AND ALERT IS TRUE, ALERT THE USER
        print(f"❌ Date:\t'{date_str_in}' not found in dataframe") if alert_in else None
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame(columns=pdf_in.columns)
    # IF THE DATE IS FOUND, RETURN THE DATAFRAME
    return date_pdf


# FUNCTION: GET NYSE STOCK EXCHANGE SCHEDULE FOR SPECIFIC DATE
def get_date_market_schedule_pdf(date_str_in):
    """
    Gets the NYSE market schedule for a specific date.
    
    Args:
        date_str_in (str): Date string in format 'YYYY-MM-DD'
        
    Returns:
        pandas.DataFrame: DataFrame containing market open and close times for the specified date
    """
    # IF THE NYSE CALENDAR IS NOT DEFINED
    if not nyse_calendar:
        # RAISE AN ERROR
        print("❌ NYSE calendar is not defined")
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # COLLECT THE NEXT OPEN DATE SCHEDULE
    schedule_pdf = nyse_calendar.schedule(start_date=date_str_in, end_date=date_str_in)
    # IF THE NYSE SCHEDULE IS EMPTY
    if schedule_pdf.empty:
        # DISPLAY INFORMATION
        print(f"❌ No market schedule found for date: {date_str_in}")
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # CONVERT THE MARKET OPEN TO NEW YORK DATETIME
    schedule_pdf["market_open"] = schedule_pdf.market_open.dt.tz_convert(ny_tz)
    # CONVERT THE MARKET CLOSE TO NEW YORK DATETIME (SUBTRACT 1 MINUTE FROM THE MARKET CLOSE)
    schedule_pdf["market_close"] = schedule_pdf.market_close.dt.tz_convert(ny_tz) - timedelta(minutes=1)
    # RETURN DATAFRAME
    return schedule_pdf.reset_index(names="date").rename(columns={"market_open": "market_open_ts", "market_close": "market_close_ts"})

# FUNCTION: GET NYSE STOCK EXCHANGE SCHEDULE FOR DATE RANGE
def get_date_range_market_schedule_pdf(date1_str_in, date2_str_in):
    """
    Gets the NYSE market schedule for a date range.
    
    Args:
        date1_str_in (str): Start date string in format 'YYYY-MM-DD'
        date2_str_in (str): End date string in format 'YYYY-MM-DD'
        
    Returns:
        pandas.DataFrame: DataFrame containing market open and close times for the specified date range
    """
    # IF THE NYSE CALENDAR IS NOT DEFINED
    if not nyse_calendar:
        # RAISE AN ERROR
        print("❌ NYSE calendar is not defined")
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # COLLECT THE NEXT OPEN DATE SCHEDULE
    schedule_pdf = nyse_calendar.schedule(start_date=date1_str_in, end_date=date2_str_in)
    # IF THE NYSE SCHEDULE IS EMPTY
    if schedule_pdf.empty:
        # DISPLAY INFORMATION
        print(f"❌ No market schedule found for date range: {date1_str_in} to {date2_str_in}")
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # CONVERT THE MARKET OPEN TO NEW YORK DATETIME
    schedule_pdf["market_open"] = schedule_pdf.market_open.dt.tz_convert(ny_tz)
    # CONVERT THE MARKET CLOSE TO NEW YORK DATETIME (SUBTRACT 1 MINUTE FROM THE MARKET CLOSE)
    schedule_pdf["market_close"] = schedule_pdf.market_close.dt.tz_convert(ny_tz) - timedelta(minutes=1)
    # RETURN DATAFRAME
    return schedule_pdf.reset_index(names="date").rename(columns={"market_open": "market_open_ts", "market_close": "market_close_ts"})