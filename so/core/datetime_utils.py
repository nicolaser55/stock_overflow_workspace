import pandas as pd
import tzlocal
import pytz
from datetime import timedelta
from datetime import time as datetime_time
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

# FUNCTION: CONVERT TIMESTAMP TO NEW YORK TIMESTAMP
def convert_to_ny_ts(timestamp_in):
    """
    Converts a timestamp to New York timezone.
    
    Args:
        timestamp_in: Input timestamp that can be a string, datetime object or pandas Timestamp
        
    Returns:
        pandas.Timestamp: Timestamp converted to New York timezone
    """
    # IF THE TIMESTAMP IS NOT A TIMESTAMP OBJECT
    if isinstance(timestamp_in, pd.Timestamp) == False:
        # CONVERT TIMESTAMP TO NEW YORK TIMESTAMP
        timestamp_in = pd.to_datetime(timestamp_in)
        # IF THE TIMESTAMP DOES NOT EXIST
        if timestamp_in.tz is None:
            # CONVERT THE TIMESTAMP TO THE NEW YORK TIMEZONE
            timestamp_in = timestamp_in.tz_localize(ny_tz)
         # IF THE TIMEZONE EXISTS BUT IT IS NOT NEW YORK TIMEZONE
        elif timestamp_in.tz != ny_tz:
            # CONVERT THE TIMESTAMP TO THE NEW YORK TIMEZONE
            timestamp_in = timestamp_in.tz_convert(ny_tz)
    # IF THE TIMESTAMP IS A TIMESTAMP OBJECT
    else:
        # IF THE TIMEZONE IS NONE
        if timestamp_in.tz is None:
            # CONVERT THE TIMESTAMP TO THE NEW YORK TIMEZONE
            timestamp_in = timestamp_in.tz_localize(ny_tz).tz_convert(ny_tz)
        # IF THE TIMEZONE EXISTS BUT IT IS NOT NEW YORK TIMEZONE
        elif timestamp_in.tz != ny_tz:
            # CONVERT THE TIMESTAMP TO THE NEW YORK TIMEZONE
            timestamp_in = timestamp_in.tz_convert(ny_tz)
    # RETURN THE NEW YORK TIMESTAMP
    return pd.to_datetime(timestamp_in)

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

# FUNCTION: GET DATAFRAME FOR DATE RANGE
def get_date_range_pdf(pdf_in, date1_str_in, date2_str_in):
    """
    Extracts data for a date range from a complete dataset
    
    Args:
        pdf_in: Complete DataFrame containing the data
        date1_str_in: Start date string to filter data from
        date2_str_in: End date string to filter data to
        
    Returns:
        DataFrame containing only data between specified dates with date and year columns dropped
    """
    # INPUT VALIDATION: CHECK IF PDF_IN IS A PANDAS DATAFRAME
    if not isinstance(pdf_in, pd.DataFrame):
        # RAISE AN ERROR
        raise TypeError("pdf_in must be a pandas DataFrame")
    # INPUT VALIDATION: CHECK IF DATE1_STR_IN AND DATE2_STR_IN ARE STRINGS
    if not isinstance(date1_str_in, str) or not isinstance(date2_str_in, str):
        # RAISE AN ERROR
        raise TypeError("Date inputs must be strings")
    # INPUT VALIDATION: CHECK IF PDF_IN CONTAINS THE REQUIRED COLUMNS
    if "date" not in pdf_in.columns:
        # RAISE AN ERROR
        raise ValueError("DataFrame must contain 'date' columns")
    # CONVERT DATE TO DATE OBJECT
    try:
        # CONVERT DATE1_STR_IN TO DATE OBJECT
        date1_object = pd.to_datetime(date1_str_in).date()
        # CONVERT DATE2_STR_IN TO DATE OBJECT
        date2_object = pd.to_datetime(date2_str_in).date()
    # IF THE DATE IS NOT CONVERTED
    except:
        # RAISE AN ERROR
        raise ValueError("Invalid date string format")
    # IF THE END DATE IS BEFORE THE START DATE
    if date2_object < date1_object:
        # RAISE AN ERROR
        raise ValueError("End date must be after start date")
    # GET THE DATAFRAME FOR THE SPECIFIC DATE AND RETURN
    date_range_pdf = pdf_in[pdf_in.date.between(date1_object, date2_object)].copy()
    # IF THE DATAFRAME IS EMPTY, RETURN AN EMPTY DATAFRAME
    if date_range_pdf.empty:
        # DISPLAY INFORMATION
        print(f"❌ No data found for the specified date range: {date1_str_in} to {date2_str_in}")
        # RETURN AN EMPTY DATAFRAME
        return pd.DataFrame(columns=pdf_in.columns)
    # RETURN THE DATAFRAME
    return date_range_pdf

# FUNCTION: SELECT DATAFRAME AT TIMESTAMP
def find_pdf_ts_idx(pdf_list_in, arg_in):
    # INPUT VALIDATION: CHECK IF PDF_LIST_IN IS PROVIDED AND NOT EMPTY
    if not pdf_list_in:
        # RAISE AN ERROR
        raise ValueError("pdf_list_in cannot be empty or None")
    # INPUT VALIDATION: CHECK IF ARG_IN IS PROVIDED
    if arg_in is None:
        # RAISE AN ERROR
        raise ValueError("arg_in cannot be None")
    # IF THE ARGUMENT IS AN INTEGER
    if isinstance(arg_in, int):
        # INPUT VALIDATION: CHECK IF INDEX IS WITHIN BOUNDS
        if arg_in < 0 or arg_in >= len(pdf_list_in):
            # RAISE AN ERROR
            raise IndexError(f"Index {arg_in} is out of bounds for list of length {len(pdf_list_in)}")
        # COLLECT THE LAST TIMESTAMP OF EACH DATAFRAME
        idx_ts_tup_list = {idx: pdf for idx, pdf in enumerate(pdf_list_in)}
        # RETURN THE DATAFRAME
        return idx_ts_tup_list[arg_in].copy()
    # INPUT VALIDATION: CHECK IF ARG_IN IS A STRING OR TIMESTAMP-LIKE OBJECT
    if not isinstance(arg_in, (str, pd.Timestamp)):
        # RAISE AN ERROR
        raise TypeError(f"arg_in must be an integer, string, or pandas Timestamp, got {type(arg_in)}")
    # TRY TO CONVERT TIMESTAMP TO NEW YORK TIMESTAMP
    try:
        # CALL FUNCTION TO CONVERT TIMESTAMP TO NEW YORK TIMESTAMP 
        selected_ts = convert_to_ny_ts(arg_in)
    # IF THE TIMESTAMP IS NOT CONVERTED
    except Exception as e:
        # RAISE AN ERROR
        raise ValueError(f"Failed to convert timestamp: {e}")
    # CREATE TIMESTMAP DATAFRAME DICTIONARY
    ts_pdf_dict = {pdf.iloc[-1]["timestamp"]: pdf for pdf in pdf_list_in}
    # INPUT VALIDATION: CHECK IF TIMESTAMP EXISTS IN THE DATA
    if selected_ts not in ts_pdf_dict:
        # COLLECT THE AVAILABLE TIMESTAMPS
        available_timestamps = sorted(ts_pdf_dict.keys())
        # RAISE AN ERROR
        raise KeyError(f"Timestamp {selected_ts} not found in data. Available timestamps range from {available_timestamps[0]} to {available_timestamps[-1]}")
    # RETURN THE DATAFRAME
    return ts_pdf_dict[selected_ts].copy()

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