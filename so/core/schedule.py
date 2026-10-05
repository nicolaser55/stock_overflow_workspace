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

# FUNCTION: GET THE WALK-FORWARD FOLD DATAFRAME
def get_walk_forward_fold_pdf(session_date_list_in, embargo_trading_days_in, train_window_years_list_in,
                              test_window_months_in=config.TEST_WINDOW_MONTHS,
                              validation_window_months_in=config.VALIDATION_WINDOW_MONTHS,
                              step_months_in=config.WALK_FORWARD_STEP_MONTHS,
                              require_all_train_windows_in=config.WALK_FORWARD_REQUIRE_ALL_TRAIN_WINDOWS,
                              max_fold_count_in=None):
    """
    Builds the walk-forward schedule, anchored on the last session of the data (fold with the highest id = latest
    test window) and stepping back by step_months_in until the training windows no longer fit in the data.

    Args:
        session_date_list_in (list[datetime.date]): Sorted session dates of the data
        test_window_months_in (int): Test window length (calendar months)
        validation_window_months_in (int): Validation window length (calendar months)
        embargo_trading_days_in (int): Sessions skipped between consecutive windows
        train_window_years_list_in (list[int]): Training window length candidates (years)
        step_months_in (int): Months between consecutive test windows
        require_all_train_windows_in (bool): Keep a fold only if every training window candidate fits in the data
        max_fold_count_in (int | None): Keep only the most recent folds (None keeps all)

    Returns:
        pd.DataFrame: One row per fold (chronological): fold_id, test_start, test_end, valid_start, valid_end,
                      refit_end, train_end, and for every L: train_start_<L>y, refit_start_<L>y, fits_<L>y
    """
    # CONVERT THE SESSION DATES TO AN ARRAY
    session_date_arr = np.array(session_date_list_in, dtype="datetime64[D]")
    # DEFINE THE FIRST DATE OF THE DATA
    first_date = pd.Timestamp(session_date_arr[0])
    # LIST TO HOLD THE FOLDS
    fold_dict_list = []
    # DEFINE THE STEP COUNTER
    step_idx = 0
    # LOOP UNTIL THE FOLDS NO LONGER FIT
    while True:
        # CALCULATE THE CALENDAR END AND START OF THE TEST WINDOW
        test_end_date = pd.Timestamp(session_date_arr[-1]) - pd.DateOffset(months=step_idx * step_months_in)
        test_start_exclusive_date = test_end_date - pd.DateOffset(months=test_window_months_in)
        # SNAP THE TEST WINDOW TO SESSIONS
        test_start_idx = get_first_session_idx_after(session_date_arr, test_start_exclusive_date.date())
        test_end_idx = get_first_session_idx_after(session_date_arr, test_end_date.date()) - 1
        # CALCULATE THE VALIDATION WINDOW (ENDING AN EMBARGO BEFORE THE TEST WINDOW)
        valid_end_idx = test_start_idx - embargo_trading_days_in - 1
        # IF THE VALIDATION WINDOW FALLS OUTSIDE THE DATA
        if valid_end_idx < 0:
            # STOP THE LOOP
            break
        valid_start_idx = get_first_session_idx_after(session_date_arr, (pd.Timestamp(session_date_arr[valid_end_idx]) - pd.DateOffset(months=validation_window_months_in)).date())
        # CALCULATE THE TRAINING END (AN EMBARGO BEFORE VALIDATION) AND THE REFIT END (AN EMBARGO BEFORE TEST)
        train_end_idx = valid_start_idx - embargo_trading_days_in - 1
        refit_end_idx = valid_end_idx
        # IF THE TRAINING WINDOW FALLS OUTSIDE THE DATA
        if train_end_idx < 0:
            # STOP THE LOOP
            break
        # DEFINE THE FOLD DICTIONARY
        fold_dict = {
            "test_start": session_date_arr[test_start_idx].astype(object),
            "test_end": session_date_arr[test_end_idx].astype(object),
            "valid_start": session_date_arr[valid_start_idx].astype(object),
            "valid_end": session_date_arr[valid_end_idx].astype(object),
            "train_end": session_date_arr[train_end_idx].astype(object),
            "refit_end": session_date_arr[refit_end_idx].astype(object),
        }
        # ITERATE OVER THE TRAINING WINDOW CANDIDATES
        for train_years in train_window_years_list_in:
            # CALCULATE THE CALENDAR START OF THE TRAINING AND REFIT WINDOWS
            train_start_exclusive_date = pd.Timestamp(session_date_arr[train_end_idx]) - pd.DateOffset(years=train_years)
            refit_start_exclusive_date = pd.Timestamp(session_date_arr[refit_end_idx]) - pd.DateOffset(years=train_years)
            # SNAP TO SESSIONS
            fold_dict[f"train_start_{train_years}y"] = session_date_arr[min(get_first_session_idx_after(session_date_arr, train_start_exclusive_date.date()), train_end_idx)].astype(object)
            fold_dict[f"refit_start_{train_years}y"] = session_date_arr[min(get_first_session_idx_after(session_date_arr, refit_start_exclusive_date.date()), refit_end_idx)].astype(object)
            # FLAG WHETHER THE FULL TRAINING WINDOW FITS IN THE DATA (7 DAYS OF TOLERANCE FOR HOLIDAYS)
            fold_dict[f"fits_{train_years}y"] = bool(train_start_exclusive_date >= first_date - pd.Timedelta(days=7))
        # COLLECT THE FIT FLAGS
        fit_bool_list = [fold_dict[f"fits_{train_years}y"] for train_years in train_window_years_list_in]
        # IF THE FOLD DOES NOT FIT
        if (require_all_train_windows_in and not all(fit_bool_list)) or not any(fit_bool_list):
            # STOP THE LOOP
            break
        # APPEND THE FOLD
        fold_dict_list.append(fold_dict)
        # INCREMENT THE STEP COUNTER
        step_idx += 1
        # IF THE MAXIMUM FOLD COUNT IS REACHED
        if max_fold_count_in is not None and len(fold_dict_list) >= max_fold_count_in:
            # STOP THE LOOP
            break
    # CONVERT TO A CHRONOLOGICAL DATAFRAME
    fold_pdf = pd.DataFrame(fold_dict_list[::-1]).reset_index(drop=True)
    # ADD THE FOLD ID
    fold_pdf.insert(0, "fold_id", range(len(fold_pdf)))
    # RETURN DATAFRAME
    return fold_pdf
