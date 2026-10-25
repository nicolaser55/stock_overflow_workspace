import json
import numpy as np
import pandas as pd

"""
Holdout Baselines (report only)

The development report and the holdout report share one implementation, on the design:
get_baseline_return_dict. A path whose equity already lies inside the requested span is used unchanged, so the
development numbers stay the numbers that were saved. A wider path is restricted to the span first: activity
(exits, cash, weights, decisions) is counted on that span, and the simulators still index full-length signal
arrays by session position. Random families report the median (np.median, the saved estimator), the 5th and 95th
percentiles, the run count, and how many runs the path's return beats.
"""

# SUFFIXES THAT ARE NOT TOTAL RETURNS THE SUCCESS CRITERIA COMPARE
_STAT_SUFFIX_TUPLE = ("_p05", "_p95", "_count", "_beaten_count", "_beats_share", "_weight", "_list")

# FUNCTION: A TIMESTAMP AS A NEW YORK SESSION DATE
def get_session_date(value_in):
    """
    Converts a date or timestamp to a session date. Aware timestamps are converted to America/New_York first.

    Args:
        value_in: Date or timestamp

    Returns:
        datetime.date: The session date
    """
    # CONVERT, THEN DROP THE CLOCK IN NEW YORK WHEN THE STAMP HAS A ZONE
    stamp = pd.Timestamp(value_in)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("America/New_York")
    return stamp.date()


# FUNCTION: MEDIAN, PERCENTILES AND THE COUNTS OF ONE RANDOM FAMILY
def get_random_family_stat_dict(family_str_in, return_list_in, path_return_float_in):
    """
    The median is np.median, which is the estimator the development reports saved. The 5th and 95th percentiles use
    np.percentile. The beaten count is how many runs have a strictly smaller return than the path, which is the
    count behind the share the stopping rules print.

    Args:
        family_str_in (str): Name prefix, without a trailing underscore
        return_list_in (list): One total return per run
        path_return_float_in (float): Path total return on the same span

    Returns:
        dict: median, p05, p95, count, beaten_count
    """
    # THE EMPTY FAMILY HAS NOTHING TO SUMMARISE
    return_arr = np.asarray(list(return_list_in), dtype=float)
    if len(return_arr) == 0:
        return {f"{family_str_in}_median": np.nan, f"{family_str_in}_p05": np.nan, f"{family_str_in}_p95": np.nan,
                f"{family_str_in}_count": 0, f"{family_str_in}_beaten_count": 0}
    # THE SAVED MEDIAN, THE PERCENTILES, AND THE STRICT COUNT
    beaten_count = int(np.sum(return_arr < float(path_return_float_in)))
    return {f"{family_str_in}_median": float(np.median(return_arr)),
            f"{family_str_in}_p05": float(np.percentile(return_arr, 5)),
            f"{family_str_in}_p95": float(np.percentile(return_arr, 95)),
            f"{family_str_in}_count": int(len(return_arr)),
            f"{family_str_in}_beaten_count": beaten_count}


# FUNCTION: JSON OF THE SCALAR BASELINE FIELDS
def get_baseline_json_str(baseline_dict_in):
    """
    The scalar baseline fields as JSON. Lists stay out of the ledger cell. Non-finite floats are null.

    Args:
        baseline_dict_in (dict): Baseline name -> value

    Returns:
        str: JSON object
    """
    # KEEP SCALARS ONLY
    scalar_dict = {}
    for key_str, value in baseline_dict_in.items():
        if isinstance(value, (list, tuple, dict)):
            continue
        if isinstance(value, (bool, np.bool_)):
            scalar_dict[key_str] = bool(value)
        elif isinstance(value, (int, np.integer)):
            scalar_dict[key_str] = int(value)
        elif isinstance(value, (float, np.floating)):
            scalar_dict[key_str] = float(value) if np.isfinite(value) else None
        else:
            scalar_dict[key_str] = value
    return json.dumps(scalar_dict)
