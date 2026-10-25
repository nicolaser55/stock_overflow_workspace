import pandas as pd

# FUNCTION: CHECK VARIABLE TYPE
def check_var_type(var_in, var_type_in, alert_in=True):
    """
    Checks if a variable is of a specific type.
    
    Args:
        var_in: Variable to check
        var_type_in: Type to check against
    """
    # IF THE VARIABLE IS NOT OF THE SPECIFIED TYPE
    if not isinstance(var_in, var_type_in):
        # DISPLAY INFORMATION
        print(f"❌ Variable is type mismatch!\nExpected Type:\t{var_type_in}\nFound Type:\t{type(var_in)}") if alert_in else None
        # RETURN FALSE
        return False
    # RETURN TRUE
    return True

# FUNCTION: CHECK EMPTY DATAFRAME
def pdf_is_empty(pdf_in, alert_in=True):
    """
    Checks if a dataframe is empty.
    
    Args:
        pdf_in: DataFrame to check
    """
    # CHECK IF THE VARIABLE IS A DATAFRAME
    if not check_var_type(pdf_in, pd.DataFrame):
        # RETURN TRUE
        return True
    # IF THE DATAFRAME IS EMPTY
    if pdf_in.empty:
        # DISPLAY INFORMATION
        print("❌ DataFrame is empty!") if alert_in else None
        # RETURN FALSE
        return True
    # RETURN TRUE
    return False

# FUNCTION: VALIDATE DATAFRAME COLS
def validate_all_pdf_cols(pdf_in, column_str_list_in, alert_in=True):
    """
    Validates the columns of an OHLCV DataFrame.
    
    Args:
        ohlcv_pdf_in: DataFrame containing OHLCV data with columns:
        column_str_list_in: List of required columns
        
    Returns:
        None
        
    Raises:
        TypeError: If input is not a pandas DataFrame
        ValueError: If DataFrame is empty or does not contain required columns
    """
    # CHECK IF THE DATAFRAME IS EMPTY
    if pdf_is_empty(pdf_in):
        # RETURN FALSE
        return False
    # IF THE OHLCV DATAFRAME DOES NOT CONTAIN THE REQUIRED COLUMNS
    if not all(col in pdf_in.columns for col in column_str_list_in):
        # DISPLAY INFORMATION
        print(f"❌ DataFrame does not contain the required columns!\nExpected Cols:\t{column_str_list_in}\nFound Cols:\t{pdf_in.columns.tolist()}") if alert_in else None
        # RETURN FALSE
        return False
    # IF ALL THE COLUMNS ARE VALID
    return True


