import pandas as pd
import numpy as np

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

# FUNCTION: GET A DATA DESCRIPTION DATAFRAME
def get_data_description_pdf(pdf_in):
    # CHECK IF THE VARIABLE IS A DATAFRAME
    if pdf_is_empty(pdf_in):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # GET THE DESCRIBE STATISTICS FOR EACH COLUMN
    desc_pdf = pdf_in.describe()
    # TRANSPOSE THE DATAFRAME SO COLUMNS BECOME ROWS
    desc_pdf = desc_pdf.transpose()
    # SORT THE INDEX
    desc_pdf = desc_pdf.sort_index()
    # RETURN THE DESCRIBED DATAFRAME
    return desc_pdf.reset_index(names="columns")

# FUNCTION: LABEL COLUMN WITH BINS
def add_precision_bin_col(pdf_in, col_str_in, precision_in=6):
    # CALL FUNCTION TO VALIDATE ALL COLUMN IN DATAFRAME
    if not validate_all_pdf_cols(pdf_in, [col_str_in]):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # COPY THE DATAFRAME
    pdf_out = pdf_in.copy().reset_index(drop=True)
    # DEFINE THE PRECISION INTEGER
    precision_int = int("1" + "0" * precision_in)
    # CREATE THE NEW COLUMN
    pdf_out[f"{col_str_in}_bin"] = np.select([pdf_out[col_str_in] < 0,
                                                pdf_out[col_str_in] == 0,
                                                pdf_out[col_str_in] > 0
                                                ],
                                                [pdf_out[col_str_in].apply(lambda x: np.ceil(x*precision_int)/precision_int),
                                                0,
                                                pdf_out[col_str_in].apply(lambda x: np.floor(x*precision_int)/precision_int),
                                                ],
                                                np.nan
                                            )
    # RETURN THE DATAFRAME
    return pdf_out

# FUNCTION: GET THE PRECISION BIN OF A FLOAT
def get_precision_bin(float_in, precision_in=6):
    # DEFINE THE PRECISION INTEGER
    precision_int = int("1" + "0" * precision_in)
    # RETURN THE PRECISION BIN
    return np.select([float_in < 0,
                      float_in == 0,
                      float_in > 0
                      ],    
                      [np.ceil(float_in*precision_int)/precision_int,
                       0,
                       np.floor(float_in*precision_int)/precision_int],
                       np.nan)

# FUNCTION: GET COLUMN HISTOGRAM
def get_col_histogram_pdf(pdf_in, col_str_in):
    # CALL FUNCTION TO VALIDATE ALL COLUMN IN DATAFRAME
    if not validate_all_pdf_cols(pdf_in, [col_str_in]):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # RETURN COLUMN HISTOGRAM DATAFRAME
    return pdf_in[col_str_in].value_counts().reset_index().sort_values(by=col_str_in).reset_index(drop=True)

# FUNCTION: GET DIFFERENCE BETWEEN DATAFRAME 1 AND DATAFRAME 2
def get_pdf1_pdf2_diff(pdf1_in, pdf2_in):
    # CHECK IF THE VARIABLE IS A DATAFRAME
    if not check_var_type(pdf1_in, pd.DataFrame) or not check_var_type(pdf2_in, pd.DataFrame):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # RETURN DATAFRA,E DIFFERENCE
    return pd.concat([pdf1_in, pdf2_in]).drop_duplicates(keep=False)

# FUNCTION: RETURN INDEX AND COLUMN PAIRS WHERE VALUES DIFFER
def get_pdf1_pdf2_diff_list(pdf1_in, pdf2_in):
    """
    Compares pdf1_in and pdf2_in and returns a list of tuples (index, column)
    for exact locations (by index, column) where their values do not match.
    """
    # CHECK IF THE VARIABLE IS A DATAFRAME
    if not check_var_type(pdf1_in, pd.DataFrame) or not check_var_type(pdf2_in, pd.DataFrame):
        # RETURN EMPTY DATAFRAME
        return pd.DataFrame()
    # ENSURE BOTH DATAFRAMES HAVE THE SAME COLUMNS IN THE SAME ORDER
    if not pdf1_in.columns.tolist() == pdf2_in.columns.tolist():
        # RAISE VALUE ERROR
        raise ValueError("DataFrames must have the same columns to compare.")
    # CREATE LIST TO HOLD DIFFERENCES
    diff_list = []
    # ITERATE OVER RANGE IN DATAFRAME 1
    for idx in range(len(pdf1_in)):
        # ITERATE OVER COLUMNS
        for col in pdf1_in.columns:
            # COLLECT VALUE 1 AND VALUE 2
            v1 = pdf1_in.iloc[idx][col]
            v2 = pdf2_in.iloc[idx][col]
            # CHECK IF VALUES ARE EQUAL
            if v1 != v2:
                # ADD INDEX AND COLUMN TO LIST
                diff_list.append((idx, col))
                # RETURN THE LIST
                return diff_list
    # RETURN LIST OF DIFFERENCES
    return diff_list

# FUNCTION: REMOVE NULL ROWS FROM FEATURE LIST
def remove_null_rows_pdf(pdf_in, feature_str_list_in, alert_in=True):
    # COLLECT ALL ROWS WHERE ANY FEATURE VALUE IS NULL (invalid rows)
    invalid_data_pdf = pdf_in[pdf_in[feature_str_list_in].isna().any(axis=1)]
    # COLLECT AN INDEX LIST OF THE INVALID DATA AS WELL AS THE COUNT OF INVALID ROWS
    invalid_data_idx_list = invalid_data_pdf.index.tolist()
    # EXCLUDE THE INVALID DATA FROM THE SIGNAL MODEL DATAFRAME
    pdf_out = pdf_in.drop(invalid_data_idx_list).reset_index(drop=True).copy() if any(idx in invalid_data_idx_list for idx in pdf_in.index) else pdf_in
    # COLLECT NEW DATAFRAME ROW COUNT
    new_row_count = len(pdf_out)
    # IF ALERT IS TRUE, DISPLAY INFORMATION
    if alert_in:
        # DISPLAY INFORMATION
        print(f"Invalid Data Count:\t{len(invalid_data_idx_list)}")
        print(f"Removed {len(invalid_data_idx_list)} rows with invalid data")
        print(f"Previous Count:\t\t{len(pdf_in)}")
        print(f"Current Count:\t\t{new_row_count}")
    # RETURN DATAFRAME
    return pdf_out