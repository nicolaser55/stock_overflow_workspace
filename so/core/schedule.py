import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION (WALK-FORWARD CONVENTIONS)
from so import config

"""
Walk-Forward Schedule (shared by every experiment)

    |----- train (L years) -----| embargo |-- validation (3 months) --| embargo |-- test (3 months) --|

The schedule is anchored on the LAST session of the data: the fold with the highest id has the most recent test window,
and earlier folds step back WALK_FORWARD_STEP_MONTHS at a time. When new data arrives, every window shifts.

Each experiment passes its own embargo (at least its label horizon) and its training window candidates (years).
"""


# FUNCTION: GET THE FIRST SESSION AFTER A DATE
def get_first_session_idx_after(session_date_arr_in, date_object_in):
    """
    Finds the position of the first session strictly after a date.

    Args:
        session_date_arr_in (np.ndarray): Sorted session dates (datetime64[D])
        date_object_in (np.datetime64 | datetime.date): Date

    Returns:
        int: Session position (len(session_date_arr_in) if none)
    """
    # RETURN THE POSITION
    return int(np.searchsorted(session_date_arr_in, np.datetime64(date_object_in, "D"), side="right"))


# FUNCTION: GET THE DEVELOPMENT FOLD DATAFRAME
def get_development_fold_pdf(session_date_list_in, embargo_trading_days_in, train_window_years_list_in,
                             validation_window_months_in=config.VALIDATION_WINDOW_MONTHS,
                             step_months_in=config.WALK_FORWARD_STEP_MONTHS,
                             require_all_train_windows_in=config.WALK_FORWARD_REQUIRE_ALL_TRAIN_WINDOWS,
                             max_fold_count_in=None):
    """
    Builds validation windows only, anchored on so.core.holdout.get_development_end_date (the session an embargo
    before the active holdout start). The last validation window ends on that session. There is no test window.

    Args:
        session_date_list_in (list[datetime.date]): Sorted session dates, including the holdout start
        embargo_trading_days_in (int): Sessions skipped between training and validation (at least the label horizon)
        train_window_years_list_in (list[int]): Training window length candidates (years)
        validation_window_months_in (int): Validation window length (calendar months)
        step_months_in (int): Months between consecutive validation windows
        require_all_train_windows_in (bool): Keep a fold only if every training window candidate fits
        max_fold_count_in (int | None): Keep only the most recent folds

    Returns:
        pd.DataFrame: fold_id, valid_start, valid_end, train_end, and for every L: train_start_<L>y, fits_<L>y
    """
    # IMPORT THE DEVELOPMENT END HERE (THE SCHEDULE MODULE MUST NOT IMPORT THE HOLDOUT AT LOAD TIME)
    from so.core.holdout import get_development_end_date
    # ANCHOR THE SCHEDULE ON THE DEVELOPMENT END
    development_end_date = get_development_end_date(embargo_trading_days_in, session_date_list_in)
    # CONVERT THE SESSION DATES TO AN ARRAY
    session_date_arr = np.array(session_date_list_in, dtype="datetime64[D]")
    # DEFINE THE FIRST DATE OF THE DATA AND THE POSITION OF THE DEVELOPMENT END
    first_date = pd.Timestamp(session_date_arr[0])
    development_end_idx = int(np.where(session_date_arr == np.datetime64(development_end_date, "D"))[0][0])
    # LIST TO HOLD THE FOLDS
    fold_dict_list = []
    # DEFINE THE STEP COUNTER
    step_idx = 0
    # LOOP UNTIL THE FOLDS NO LONGER FIT
    while True:
        # CALCULATE THE CALENDAR END OF THIS VALIDATION WINDOW (STEPPING BACK FROM THE DEVELOPMENT END)
        valid_end_date = pd.Timestamp(development_end_date) - pd.DateOffset(months=step_idx * step_months_in)
        valid_start_exclusive_date = valid_end_date - pd.DateOffset(months=validation_window_months_in)
        # SNAP THE VALIDATION WINDOW TO SESSIONS
        valid_start_idx = get_first_session_idx_after(session_date_arr, valid_start_exclusive_date.date())
        valid_end_idx = get_first_session_idx_after(session_date_arr, valid_end_date.date()) - 1
        # STOP WHEN THE WINDOW WOULD PASS THE DEVELOPMENT END OR LEAVE THE DATA
        if valid_end_idx > development_end_idx or valid_end_idx < 0 or valid_start_idx > valid_end_idx:
            break
        # CALCULATE THE TRAINING END (AN EMBARGO BEFORE VALIDATION)
        train_end_idx = valid_start_idx - embargo_trading_days_in - 1
        # STOP WHEN THE TRAINING WINDOW LEAVES THE DATA
        if train_end_idx < 0:
            break
        # DEFINE THE FOLD DICTIONARY (VALIDATION AND TRAINING ONLY)
        fold_dict = {
            "valid_start": session_date_arr[valid_start_idx].astype(object),
            "valid_end": session_date_arr[valid_end_idx].astype(object),
            "train_end": session_date_arr[train_end_idx].astype(object),
        }
        # ITERATE OVER THE TRAINING WINDOW CANDIDATES
        for train_years in train_window_years_list_in:
            # CALCULATE THE CALENDAR START OF THE TRAINING WINDOW
            train_start_exclusive_date = pd.Timestamp(session_date_arr[train_end_idx]) - pd.DateOffset(years=train_years)
            # SNAP TO SESSIONS
            fold_dict[f"train_start_{train_years}y"] = session_date_arr[min(get_first_session_idx_after(session_date_arr, train_start_exclusive_date.date()), train_end_idx)].astype(object)
            # FLAG WHETHER THE FULL TRAINING WINDOW FITS (7 DAYS OF TOLERANCE FOR HOLIDAYS)
            fold_dict[f"fits_{train_years}y"] = bool(train_start_exclusive_date >= first_date - pd.Timedelta(days=7))
        # COLLECT THE FIT FLAGS
        fit_bool_list = [fold_dict[f"fits_{train_years}y"] for train_years in train_window_years_list_in]
        # STOP WHEN THE FOLD DOES NOT FIT
        if (require_all_train_windows_in and not all(fit_bool_list)) or not any(fit_bool_list):
            break
        # APPEND THE FOLD
        fold_dict_list.append(fold_dict)
        # INCREMENT THE STEP COUNTER
        step_idx += 1
        # STOP AT THE MAXIMUM FOLD COUNT
        if max_fold_count_in is not None and len(fold_dict_list) >= max_fold_count_in:
            break
    # CONVERT TO A CHRONOLOGICAL DATAFRAME
    fold_pdf = pd.DataFrame(fold_dict_list[::-1]).reset_index(drop=True)
    # ADD THE FOLD ID
    fold_pdf.insert(0, "fold_id", range(len(fold_pdf)))
    # RETURN DATAFRAME
    return fold_pdf
