import pandas as pd
import json
from json import JSONDecodeError
import time
import os
# IMPORT DATA QUALITY FUNCTIONS
from so.core.data_quality import check_var_type

# DEFINE STORAGE NAME STR
STORAGE_NAME_STR = "Local File Storage"

# FUNCTION: CHECK IF FILE EXISTS
def check_file_exists(file_path_str_in, alert_in=False):
    """
    Checks if a file exists at the specified path
    
    Args:
        file_path_str_in: String path to check for file
        
    Returns:
        Boolean indicating if file exists
    """
    # IF THERE IS NO "/" IN THE STRING (local file save)
    if "/" not in file_path_str_in:
        # RETURN TRUE
        return True
    # CHECK IF THE FILE EXISTS
    file_exists_bool = os.path.isfile(file_path_str_in)
    # IF THE FILE EXISTS
    if alert_in:
        # IF FILE EXISTS
        if file_exists_bool:
            # DISPLAY INFORMATION
            print(f"✅ File:\t'{file_path_str_in}' Found!\t(💾 In {STORAGE_NAME_STR})")
        # IF THE FILE DOES NOT EXIST
        else:
            # DISPLAY INFORMATION
            print(f"⚠️ File:\t'{file_path_str_in}' Not Found!\t(💾 In {STORAGE_NAME_STR})")
    # RETURN TRUE IF FILE EXISTS
    return file_exists_bool

# FUNCTION: DELETE FILE FROM PATH
def delete_file_from_path(file_path_str_in, alert_in=True):
    """
    Deletes a file from the local file system.
    
    Args:
        file_path_str_in (str): The path to the file to delete
    """
    # CHECK IF THE FILE EXISTS
    if check_file_exists(file_path_str_in):
        # DISPLAY INFORMATION
        print(f"✅ File:\t'{file_path_str_in}' Found!\n🗑️ Deleting File...\t(💾 From {STORAGE_NAME_STR})") if alert_in else None
        # DELETE THE FILE FROM THE PATH
        os.remove(file_path_str_in)
    # IF THE FILE DOES NOT EXIST
    else:
        # DISPLAY INFORMATION
        print(f"⚠️ File:\t'{file_path_str_in}' Not Found!\t(💾 In {STORAGE_NAME_STR})") if alert_in else None

# FUNCTION: CHECK THAT A STRING HAS A VALID FILE SPECIFIED
def check_valid_file_path(file_path_str_in, required_extension):
    """
    Validates that a file path contains a file with the required extension.

    Args:
        file_path_str_in (str): The full file path to validate
        required_extension (str): The required file extension (without the dot)

    Returns:
        bool: True if validation passes

    Raises:
        Exception: If file path is missing extension or has wrong extension
        
    Example:
        >>> check_valid_file_path("/path/to/file.csv", "csv")
        True
        >>> check_valid_file_path("/path/to/file.txt", "csv") 
        Exception: ⚠️ File extension '.txt' is not valid...
    """
    # GET THE FILE NAME FROM THE PATH
    filename = os.path.basename(file_path_str_in)
    # CHECK IF FILE HAS AN EXTENSION
    if '.' not in filename:
        # RAISE EXCEPTION
        raise Exception(f"⚠️ File Path '{file_path_str_in}' is not valid. Requires a file with extension '.{required_extension}'")
    # GET AND VALIDATE EXTENSION
    extension = filename.split('.')[-1]
    # IF THE REQUIRED EXTENSION IS NOT THE SAME AS THE FILE EXTENSION
    if extension != required_extension:
        # RAISE EXCEPTION
        raise Exception(f"⚠️ File extension '.{extension}' is not valid. Required extension is '.{required_extension}'")
    # RETURN TRUE
    return True

# FUNCTION: LIST FILES IN DIRECTORY
def get_path_file_list(file_path_str_in):
    """
    Gets list of files in directory at specified path
    
    Args:
        file_path_str_in: String path to directory
        
    Returns:
        List of full file paths for all files in directory
    """
    # IF THERE ARE ITEMS IN THE FILE PATH
    if len(list(os.walk(file_path_str_in))) > 0:
        # COLLECT ALL DATA FILE NAMES
        data_file_name_list = next(os.walk(file_path_str_in), (None, None, []))[2]
        # COLLECT AND RETURN DATA FILE NAME LIST
        return [f"{file_path_str_in}{data_file_name}" for data_file_name in data_file_name_list]
    # IF THERE ARE NO ITEMS IN THE FILE PATH
    return []

# FUNCTION: READ CSV AS DATAFRAME FROM PATH
def read_csv_file_from_path(file_path_str_in, alert_in=True):
    """
    Reads CSV file into pandas DataFrame
    
    Args:
        file_path_str_in: String path to CSV file
        alert_in: Boolean to control progress messages
        
    Returns:
        DataFrame containing CSV data or None if file not found
    """
    # CHECK IF THE FILE PATH IS VALID
    check_valid_file_path(file_path_str_in, "csv")
    # ATTEMPT TO READ DATA FILE
    try:
        # READ DATA FILE
        read_pdf = pd.read_csv(file_path_str_in)
        # DISPLAY INFORMATION
        print(f"✅ File:\t'{file_path_str_in}' Found!\t(💾 In {STORAGE_NAME_STR})") if alert_in else None
        # RETURN DATAFRAME
        return read_pdf
    # CATCH EXCEPTION
    except FileNotFoundError:
        # DISPLAY INFORMATION
        print(f"⚠️ File:\t'{file_path_str_in}' Not Found!\t(💾 In {STORAGE_NAME_STR})") if alert_in else None
        # RETURN NONE
        return None

# FUNCTION: SAVE DATAFRAME AS CSV TO PATH
def write_csv_file_to_path(pdf_in, file_path_str_in, access_mode_in="I", alert_in=True):
    """
    Writes pandas DataFrame to CSV file
    
    Args:
        pdf_in: DataFrame to save
        file_path_str_in: String path where to save CSV
        access_mode_in: String indicating write mode ('W'=overwrite, 'A'=append, 'N'=no write)
        alert_in: Boolean to control progress messages
        
    Returns:
        None
    """
    # CHECK IF THE INPUT IS A DATAFRAME
    check_var_type(pdf_in, pd.DataFrame)
    # CHECK IF THE FILE PATH IS VALID
    check_valid_file_path(file_path_str_in, "csv")
    # ASSERT THAT THE ACCESS MODE IS VALID
    assert access_mode_in.upper() in ["W","A","N","I"], f"Access mode '{access_mode_in}' is invalid"
    # IF df_in IS NOT EMPTY
    if (isinstance(pdf_in, pd.DataFrame) == False):
        # DISPLAY INFORMATION
        print("⚠️ Item Provided Is Not A DataFrame") if alert_in else None
        # EXIT FUNCTION
        return None
    # IF pdf_in IS EMPTY
    if (len(pdf_in) == 0):
        # DISPLAY INFORMATION
        print("⚠️ DataFrame Provided Is Empty! Proceeding...") if alert_in else None
        # EXIT FUNCTION
        return None
    # IF access_mode in IS "N"
    if (access_mode_in.upper() == "N"):
        # DISPLAY INFORMATION
        print("⚠️ Not Saving DataFrame") if alert_in else None
        # EXIT FUNCTION
        return None
    # # COLLECT THE FILE PATH
    # directory_path = "/".join(file_path_str_in.split("/")[:-1])
    # # CREATE THE DIRECTORY IF IT DOES NOT EXIST
    # os.makedirs(directory_path, exist_ok=True)
    # CREATE THE DIRECTORY IF IT DOES NOT EXIST
    directory_path = os.path.dirname(file_path_str_in)
    # CREATE THE DIRECTORY IF IT DOES NOT EXIST, BUT ONLY IF directory_path IS NON-EMPTY
    if directory_path not in ["", None]:
        # MAKE A DIRECTORY PATH
        os.makedirs(directory_path, exist_ok=True)
    # ACCESS MODE MEANING
    access_mode_dict = {"W":"Overwrite", "A":"Append", "I":"Ignore"}
    # DISPLAY INFORMATION
    print(f"ℹ️ Saving In {access_mode_dict[access_mode_in.upper()]} Mode.\t(💾 In {STORAGE_NAME_STR})") if alert_in else None
    # READ THE CSV FROM PATH
    existing_pdf = read_csv_file_from_path(file_path_str_in, alert_in=alert_in)
    # CHECK IF DATA FILE EXISTS
    file_exists_bool = isinstance(existing_pdf, pd.DataFrame)
    # DEFINE SAVE DATAFRAME
    save_pdf = pdf_in
    # IF FILE ALREADY EXISTS
    if file_exists_bool:
        # IF THE ACCESS MODE IS I
        if access_mode_in.upper() == "I":
            # DISPLAY INFORMATION
            print(f"\t⚠️ File:\t'{file_path_str_in}' Already Exists! Proceeding...") if alert_in else None
            # RETURN NONE
            return None
        # IF THE ACCESS MODE IS W
        if access_mode_in.upper() == "W":
            # DISPLAY INFORMATION
            print(f"\t♻️ File:\t'{file_path_str_in}' Has Been Overwritten!") if alert_in else None
        # IF THE ACCESS MODE IS A
        elif access_mode_in.upper() == "A":
            # APPEND CURRENT DATAFRAME TO EXISTING DATAFRAME
            save_pdf = pd.concat([existing_pdf, pdf_in], axis=0)
            # DISPLAY INFORMATION
            print(f"\t✅ File:\t'{file_path_str_in}' Has Been Appended To!") if alert_in else None
    # SAVE CSV TO CONTAINER
    save_pdf.to_csv(file_path_str_in, index=False)
    # DISPLAY INFORMATION
    print(f"✅ File:\t'{file_path_str_in}' Has Been Saved!") if alert_in else None

# FUNCTION: COLLECT DATA FROM LIST OF PATHS
def read_pdf_from_csv_file_path_list(list_in):
    """
    Reads multiple CSV files and combines them into single DataFrame
    
    Args:
        list_in: List of file paths to CSV files
        
    Returns:
        Combined DataFrame from all CSV files or None if no files
    """
    # CREATE A LIST OF DATAFRAMES FROM PATH LIST
    pdf_list = [pd.read_csv(data_file_path_str) for data_file_path_str in list_in]
    # IF THERE ARE DATAFRMAES IN THE LIST
    if pdf_list:
        # CONCATENATE ALL DATAFRAMES VERTICALLY AND RESET THE INDEX
        return pd.concat(pdf_list, axis=0).reset_index(drop=True)
    # IF THERE ARE NO ITEMS
    print("There are 0 DataFrame items in the list")

# FUNCTION: COLLECT TRANSACTION DATA FROM PATH
def read_csv_files_from_path(file_path_str_in):
    """
    Reads all CSV files in directory into single DataFrame
    
    Args:
        file_path_str_in: String path to directory containing CSV files
        
    Returns:
        Combined DataFrame from all CSV files in directory
    """
    # CHECK IF THE END OF THE FILE PATH IS A SLASH
    if not file_path_str_in.endswith("/"):
        # RAISE AN ERROR
        raise ValueError(f"❌ File path '{file_path_str_in}' is not valid.\nFile path must end with '/'.")
    # COLLECT ALL THE FILES IN THE DIRECTORY
    file_path_str_list = get_path_file_list(file_path_str_in)
    # FILTER OUT NON-CSV FILES
    valid_file_path_str_list = [f for f in file_path_str_list if f.endswith(".csv")]
    # CALL FUNCTION TO COLLECT DATA
    return read_pdf_from_csv_file_path_list(valid_file_path_str_list)

# FUNCTION: LIST THE DATE FILES OF A DIRECTORY WITHIN A DATE RANGE
def get_date_range_file_path_list(file_path_str_in, date1_str_in=None, date2_str_in=None):
    """
    Lists the date-stamped CSV files ('{name}_YYYYMMDD.csv') of a directory whose date falls within an inclusive range.

    Args:
        file_path_str_in (str): Directory path ending with '/'
        date1_str_in (str | None): Start date (inclusive); None means no lower bound
        date2_str_in (str | None): End date (inclusive); None means no upper bound

    Returns:
        list[str]: Sorted list of full file paths (sorted by date)
    """
    # COLLECT ALL THE FILES IN THE DIRECTORY
    file_path_str_list = [f for f in get_path_file_list(file_path_str_in) if f.endswith(".csv")]
    # CONVERT THE DATE BOUNDS TO DATE OBJECTS
    date1_object = pd.to_datetime(date1_str_in).date() if date1_str_in is not None else None
    date2_object = pd.to_datetime(date2_str_in).date() if date2_str_in is not None else None
    # LIST TO HOLD THE DATE AND FILE PATH TUPLES
    date_file_path_tup_list = []
    # ITERATE OVER THE FILE PATHS
    for file_path_str in file_path_str_list:
        # COLLECT THE DATE STRING AT THE END OF THE FILE NAME
        date_str = os.path.basename(file_path_str).replace(".csv", "").split("_")[-1]
        # TRY TO CONVERT THE DATE STRING
        try:
            # CONVERT TO A DATE OBJECT
            date_object = pd.to_datetime(date_str, format="%Y%m%d").date()
        # IF THE FILE NAME DOES NOT END WITH A DATE
        except ValueError:
            # SKIP THE FILE
            continue
        # IF THE DATE IS OUTSIDE THE RANGE
        if (date1_object is not None and date_object < date1_object) or (date2_object is not None and date_object > date2_object):
            # SKIP THE FILE
            continue
        # ADD THE DATE AND FILE PATH TO THE LIST
        date_file_path_tup_list.append((date_object, file_path_str))
    # RETURN THE FILE PATHS SORTED BY DATE
    return [file_path_str for _, file_path_str in sorted(date_file_path_tup_list)]

# FUNCTION: READ THE DATE FILES OF A DIRECTORY WITHIN A DATE RANGE
def read_date_range_csv_files_from_path(file_path_str_in, date1_str_in=None, date2_str_in=None):
    """
    Reads the date-stamped CSV files of a directory within an inclusive date range into a single DataFrame.

    Args:
        file_path_str_in (str): Directory path ending with '/'
        date1_str_in (str | None): Start date (inclusive)
        date2_str_in (str | None): End date (inclusive)

    Returns:
        pd.DataFrame: Combined DataFrame (empty DataFrame if no files match)
    """
    # CHECK IF THE END OF THE FILE PATH IS A SLASH
    if not file_path_str_in.endswith("/"):
        # RAISE AN ERROR
        raise ValueError(f"❌ File path '{file_path_str_in}' is not valid.\nFile path must end with '/'.")
    # COLLECT THE FILE PATHS WITHIN THE DATE RANGE
    file_path_str_list = get_date_range_file_path_list(file_path_str_in, date1_str_in, date2_str_in)
    # IF THERE ARE NO FILES
    if not file_path_str_list:
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # CALL FUNCTION TO COLLECT DATA
    return read_pdf_from_csv_file_path_list(file_path_str_list)

# FUNCTION: FIND NON GENERATED DATES
def get_missing_date_list(file_path_str_in, date1_str_in, date2_str_in, alert_in=True):
    """
    Compares the date-stamped files of a directory with the NYSE schedule and returns the market dates without a file.
    (Same logic as the get_missing_date_list function previously copied into each collection notebook.)

    Args:
        file_path_str_in (str): Directory path ending with '/'
        date1_str_in (str | datetime.date): First date of the expected range
        date2_str_in (str | datetime.date): Last date of the expected range
        alert_in (bool): Display the counts

    Returns:
        list[datetime.date]: Sorted missing dates
    """
    # IMPORT MARKET DATETIME FUNCTION
    from so.core.datetime_utils import get_date_range_market_schedule_pdf
    # COLLECT THE EXISTING DATES FROM THE FILE NAMES
    existing_date_list = [pd.to_datetime(os.path.basename(f).replace(".csv", "").split("_")[-1], format="%Y%m%d").date()
                          for f in get_date_range_file_path_list(file_path_str_in)]
    # CREATE A MARKET SCHEDULE DATE RANGE
    market_schedule_pdf = get_date_range_market_schedule_pdf(str(date1_str_in), str(date2_str_in))
    # COLLECT THE EXPECTED DATE LIST FROM THE MARKET SCHEDULE
    expected_date_list = pd.to_datetime(market_schedule_pdf["date"]).dt.date.tolist() if not market_schedule_pdf.empty else []
    # COLLECT THE MISSING DATE LIST
    missing_date_list = sorted(set(expected_date_list) - set(existing_date_list))
    # IF ALERT IS TRUE
    if alert_in:
        # DISPLAY INFORMATION
        print(f"Expected Date Count:\t{len(expected_date_list):,}")
        print(f"Existing Date Count:\t{len(existing_date_list):,}")
        print(f"Missing Date Count:\t{len(missing_date_list):,}")
    # RETURN MISSING DATES
    return missing_date_list

# FUNCTION: READ JSON AS DICTIONARY FROM PATH
def read_json_file_from_path(file_path_str_in, alert_in=True):
    """
    Reads JSON file into dictionary
    
    Args:
        file_path_str_in: String path to JSON file
        alert_in: Boolean to control progress messages
        
    Returns:
        Dictionary containing JSON data or None if file not found/corrupted
    """
    # CHECK IF THE FILE PATH IS VALID
    check_valid_file_path(file_path_str_in, "json")
    # ATTEMPT TO READ DATA FILE
    try:
        # OPEN AND READ THE JSON FILE
        with open(file_path_str_in, "r") as json_file:
            # LOAD THE JSON DATA DICTIONARY
            data_dict = json.load(json_file)
            # DISPLAY INFORMATION
            print(f"✅ File:\t'{file_path_str_in}' Found!\t(💾 In {STORAGE_NAME_STR})") if alert_in else None
            # RETURN DATAFRAME
            return data_dict
    # CATCH JSON DECODE ERROR
    except JSONDecodeError:
        # DISPLAY INFORMATION
        print(f"⚠️ File:\t'{file_path_str_in}' Corrupted!\t(💾 In {STORAGE_NAME_STR})") if alert_in else None
        # RETURN NONE
        return None
    # CATCH FILE NOT FOUND EXCEPTION
    except FileNotFoundError:
        # DISPLAY INFORMATION
        print(f"⚠️ File:\t'{file_path_str_in}' Not Found!\t(💾 In {STORAGE_NAME_STR})") if alert_in else None
        # RETURN NONE
        return None

# FUNCTION: SAVE DICTIONARY AS JSON TO PATH
def write_json_file_to_path(data_dict_in, file_path_str_in, access_mode_in="I", alert_in=True):
    """
    Writes dictionary to JSON file
    
    Args:
        data_dict_in: Dictionary to save
        file_path_str_in: String path where to save JSON
        access_mode_in: String indicating write mode ('W'=overwrite, 'A'=append, 'N'=no write)
        alert_in: Boolean to control progress messages
        
    Returns:
        None
    """
    # CHECK IF THE INPUT IS A DICTIONARY
    check_var_type(data_dict_in, dict)
    # CHECK IF THE FILE PATH IS VALID
    check_valid_file_path(file_path_str_in, "json")
    # CONVERT ACCESS MODE TO UPPER CASE
    access_mode = access_mode_in.upper()
    # ASSERT THAT THE ACCESS MODE IS VALID
    assert access_mode in ["W", "A", "N", "I"], f"Access mode '{access_mode_in}' is invalid"
    # CHECK IF INPUT IS A NON-EMPTY DICTIONARY
    if not isinstance(data_dict_in, dict) or not data_dict_in:
        # DISPLAY INFORMATION
        print("⚠️ Invalid input: Must be a non-empty dictionary.") if alert_in else None
        # RETURN NONE
        return None
    # HANDLE 'N' ACCESS MODE
    if access_mode == "N":
        # DISPLAY INFORMATION
        print("⚠️ Not saving dictionary.") if alert_in else None
        # RETURN NONE
        return None
    # # COLLECT THE FILE PATH
    # directory_path = "/".join(file_path_str_in.split("/")[:-1])
    # # CREATE THE DIRECTORY IF IT DOES NOT EXIST
    # os.makedirs(directory_path, exist_ok=True)
    # CREATE THE DIRECTORY IF IT DOES NOT EXIST
    directory_path = os.path.dirname(file_path_str_in)
    # CREATE THE DIRECTORY IF IT DOES NOT EXIST, BUT ONLY IF directory_path IS NON-EMPTY
    if directory_path not in ["", None]:
        # MAKE A DIRECTORY PATH
        os.makedirs(directory_path, exist_ok=True)
    # ACCESS MODE MEANING
    access_mode_dict = {"W": "Overwrite", "A": "Append", "I":"Ignore"}
    # DISPLAY INFORMATION
    print(f"ℹ️ Saving In {access_mode_dict[access_mode]} Mode.\t(💾 In {STORAGE_NAME_STR})") if alert_in else None
    # READ JSON FROM PATH
    existing_data = read_json_file_from_path(file_path_str_in, alert_in=alert_in)
    # CHECK IF DATA FILE EXISTS
    file_exists = isinstance(existing_data, dict)
    # DEFINE THE SAVE DATA DICTIONARY
    save_dict = data_dict_in
    # IF FILE EXISTS BOOLEAN
    if file_exists:
        # IF THE ACCESS MODE IS I
        if access_mode.upper() == "I":
            # DISPLAY INFORMATION
            print(f"\t⚠️ File:\t'{file_path_str_in}' Already Exists! Proceeding...") if alert_in else None
            # RETURN NONE
            return None
        # IF THE ACCESS MODE IS W
        if access_mode.upper() == "W":
            # DISPLAY INFORMATION
            print(f"\t♻️ File:\t'{file_path_str_in}' Has Been Overwritten!") if alert_in else None
        # IF THE ACCESS MODE IS A
        elif access_mode.upper() == "A":
            # APPEND THE DICTIONARY
            save_dict = {**existing_data, **data_dict_in}
            # DISPLAY INFORMATION
            print(f"\t✅ File:\t'{file_path_str_in}' Has Been Appended To!") if alert_in else None
    # WRITE JSON TO FILE
    with open(file_path_str_in, "w") as json_file:
        # DUMP THE DATA
        json.dump(save_dict, json_file, indent=4)
    # DISPLAY INFORMATION
    print(f"✅ File:\t'{file_path_str_in}' Has Been Saved!")

# FUNCTION: GET OHLCV SEGMENT AGG DATAFRAME FOR DATE RANGE
def generate_func_data_date_range(func_in, date1_str_in, date2_str_in, file_path_str_in, file_name_str_in, access_mode_in, reverse_in=False):
    # ASSERT THAT THE ACCESS MODE IS VALID
    assert access_mode_in.upper() in ["W", "I", "N"], f"Access mode '{access_mode_in}' is invalid"
    # IMPORT GET DATE RANGE MARKET SCHEDULE PDF FUNCTION
    from so.core.datetime_utils import get_date_range_market_schedule_pdf
    # CALL FUNCTION TO GET NYSE SCHEDULE FOR DATE RANGE
    nyse_schedule_pdf = get_date_range_market_schedule_pdf(date1_str_in, date2_str_in)
    # IF THE NYSE SCHEDULE IS EMPTY
    if nyse_schedule_pdf.empty:
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # COLLECT LIST OF OPEN MARKET DATES
    date_list, date_count = nyse_schedule_pdf.date.tolist(), len(nyse_schedule_pdf)
    # IF THE REVERSE IN IS TRUE
    if reverse_in:
        # REVERSE THE DATE LIST
        date_list.reverse()
    # CREATE A LIST TO HOLD DATA
    data_list = []
    # ITERATE OVER THE DATE RANGE
    for idx, date_object in enumerate(date_list, 1):
        # CREATE A DATE STRING
        date_name_str, date_file_name_str = date_object.strftime("%Y-%m-%d"), date_object.strftime("%Y%m%d")
        # DISPLAY INFORMATION
        print(f"\nDate:\t{date_name_str}\t[{idx}/{date_count}]")
        
        # DEFINE THE FILE NAME
        file_name_str = f"{file_name_str_in}_{date_file_name_str}.csv"
        # COMBINE FILE NAME WITH FILE PATH
        save_file_path_str = file_path_str_in + file_name_str
        # PRE-DEFINE THE FILE VALID
        valid_data_file_bool = False
        # PRE-DEFINE SECONDS DURATION
        seconds_duration = 0
        # IF THE FILE EXISTS
        if check_file_exists(save_file_path_str):
            # READ THE EXISTING DATA FILE
            read_pdf = read_csv_file_from_path(save_file_path_str, alert_in=False)
            # BOOLEAN TO CHECK IF THE FILE CONTAINS DATA
            valid_data_file_bool = isinstance(read_pdf, pd.DataFrame) and len(read_pdf) > 0
        # IF A VALID DATA FILE EXISTS AND THE ACCESS MODE IS "I" (ignore)
        if (valid_data_file_bool) and (access_mode_in.upper() == "I"):
            # DISPLAY INFORMATION
            print(f"⚠️ File '{file_name_str}' already exists!\nProceeding...")
        # IF THE FILE DOES NOT EXIST OR THE ACCESS MODE IS "W" (write)
        else:
            # DISPLAY INFORMATION
            print(f"\t⏳ Processing date...")
            # START THE TIMER
            start_time = time.time()
            # EXECUTE THE ALGORITHM FOR THE CURRENT DATE
            date_data_pdf = func_in(date_name_str)
            # GET THE ELAPSED TIME
            seconds_duration = time.time() - start_time
            # DISPLAY INFORMATION
            print(f"\t✅ Date:\t'{date_name_str}' Processed In {seconds_duration:.2f} seconds ({seconds_duration / 60:.2f} minutes)")
            # IF THE OHLCV SEGMENT AGG DATAFRAME IS NOT EMPTY
            if not date_data_pdf.empty:
                # ADD THE DATE TO THE DATAFRAME
                date_data_pdf["date"] = date_object
                # SAVE DATAFRAME TO CSV
                write_csv_file_to_path(date_data_pdf, save_file_path_str, access_mode_in)
            # IF THE OHLCV SEGMENT AGG DATAFRAME IS EMPTY
            else:
                # DISPLAY INFORMATION
                print(f"\t⚠️ No Data For Date:\t'{date_name_str}'")
            # GET THE ELAPSED TIME
            seconds_duration = time.time() - start_time
            # ADD THE DATAFRAME TO THE LIST
            data_list.append((date_object, seconds_duration))
    # CONVERT THE LIST TO A DATAFRAME AND RETURN
    return pd.DataFrame(data_list, columns=["date", "seconds_duration"])

# FUNCTION: GET OHLCV SEGMENT AGG DATAFRAME FOR DATE RANGE
def generate_func_data_date_list(func_in, date_list_in, file_path_str_in, file_name_str_in, access_mode_in, reverse_in=False):
    # ASSERT THAT THE ACCESS MODE IS VALID
    assert access_mode_in.upper() in ["W", "I", "N"], f"Access mode '{access_mode_in}' is invalid"
    # IF THE NYSE SCHEDULE IS EMPTY
    if not date_list_in:
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # IMPORT GET DATE MARKET SCHEDULE PDF FUNCTION
    from so.core.datetime_utils import get_date_market_schedule_pdf
    # COLLECT LIST OF OPEN MARKET DATES
    date_list, date_count = [pd.to_datetime(date_str) for date_str in date_list_in], len(date_list_in)
    # IF THE REVERSE IN IS TRUE
    if reverse_in:
        # REVERSE THE DATE LIST
        date_list.reverse()
    # CREATE A LIST TO HOLD DATA
    data_list = []
    # ITERATE OVER THE DATE RANGE
    for idx, date_object in enumerate(date_list, 1):
        # CREATE A DATE STRING
        date_name_str, date_file_name_str = date_object.strftime("%Y-%m-%d"), date_object.strftime("%Y%m%d")
        # DISPLAY INFORMATION
        print(f"\nDate:\t{date_name_str}\t[{idx}/{date_count}]")
        # GET THE DATE MARKET SCHEDULE PDF
        date_market_schedule_pdf = get_date_market_schedule_pdf(date_name_str)
        # IF THE DATE MARKET SCHEDULE PDF IS EMPTY
        if date_market_schedule_pdf.empty:
            # DISPLAY INFORMATION
            print(f"\t⚠️ No Market Schedule For Date:\t'{date_name_str}'")
            # CONTINUE TO THE NEXT DATE
            continue
        # DEFINE THE FILE NAME
        file_name_str = f"{file_name_str_in}_{date_file_name_str}.csv"
        # COMBINE FILE NAME WITH FILE PATH
        save_file_path_str = file_path_str_in + file_name_str
        # PRE-DEFINE THE FILE VALID
        valid_data_file_bool = False
        # PRE-DEFINE SECONDS DURATION
        seconds_duration = 0
        # IF THE FILE EXISTS
        if check_file_exists(save_file_path_str):
            # READ THE EXISTING DATA FILE
            read_pdf = read_csv_file_from_path(save_file_path_str, alert_in=False)
            # BOOLEAN TO CHECK IF THE FILE CONTAINS DATA
            valid_data_file_bool = isinstance(read_pdf, pd.DataFrame) and len(read_pdf) > 0
        # IF A VALID DATA FILE EXISTS AND THE ACCESS MODE IS "I" (ignore)
        if (valid_data_file_bool) and (access_mode_in.upper() == "I"):
            # DISPLAY INFORMATION
            print(f"⚠️ File '{file_name_str}' already exists!\nProceeding...")
        # IF THE FILE DOES NOT EXIST OR THE ACCESS MODE IS "W" (write)
        else:
            # DISPLAY INFORMATION
            print(f"\t⏳ Processing date...")
            # START THE TIMER
            start_time = time.time()
            # EXECUTE THE ALGORITHM FOR THE CURRENT DATE
            date_data_pdf = func_in(date_name_str)
            # GET THE ELAPSED TIME
            seconds_duration = time.time() - start_time
            # DISPLAY INFORMATION
            print(f"\t✅ Date:\t'{date_name_str}' Processed In {seconds_duration:.2f} seconds ({seconds_duration / 60:.2f} minutes)")
            # IF THE OHLCV SEGMENT AGG DATAFRAME IS NOT EMPTY
            if not date_data_pdf.empty:
                # ADD THE DATE TO THE DATAFRAME
                date_data_pdf["date"] = date_object
                # SAVE DATAFRAME TO CSV
                write_csv_file_to_path(date_data_pdf, save_file_path_str, access_mode_in)
            # IF THE OHLCV SEGMENT AGG DATAFRAME IS EMPTY
            else:
                # DISPLAY INFORMATION
                print(f"\t⚠️ No Data For Date:\t'{date_name_str}'")
        # ADD THE DATAFRAME TO THE LIST
        data_list.append((date_object, seconds_duration))
    # CONVERT THE LIST TO A DATAFRAME AND RETURN
    return pd.DataFrame(data_list, columns=["date", "seconds_duration"])