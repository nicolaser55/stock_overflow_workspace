import json
import os
import sys
import numpy as np
import pandas as pd

"""
Workspace Tests: holdout report baselines

The family statistics and the span cut. No market data, no trial row.
"""

# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()

# IMPORT THE SHARED TOLERANCE AND THE BASELINE HELPERS
from so import config
from so.core.baseline_report import get_baseline_json_str, get_comparison_baseline_dict, get_random_family_stat_dict, get_span_path_dict


# FUNCTION: PRINT A PASSED TEST
def passed(message_str_in):
    """
    Prints a passed test and flushes, so a redirected log shows the line as it happens.

    Args:
        message_str_in (str): Message

    Returns:
        None
    """
    # PRINT THE MESSAGE
    print(f"✅ {message_str_in}", flush=True)

# FUNCTION: TEST THE FAMILY STATISTICS AND THE SPAN CUT
def test_family_and_span():
    """
    The median is np.median. Percentiles, counts and lists are not returns the success criteria compare.
    A path already inside the span is returned unchanged.

    Returns:
        None
    """
    # THE SAVED MEDIAN, THE PERCENTILES, AND THE STRICT COUNT
    return_list = [0.1, 0.2, 0.3, 0.4]
    stat_dict = get_random_family_stat_dict("random_exit", return_list, 0.25)
    assert stat_dict["random_exit_median"] == float(np.median(return_list))
    assert stat_dict["random_exit_p05"] == float(np.percentile(return_list, 5))
    assert stat_dict["random_exit_p95"] == float(np.percentile(return_list, 95))
    assert stat_dict["random_exit_count"] == 4 and stat_dict["random_exit_beaten_count"] == 2
    # ONLY THE NAMED RETURN IS COMPARED, AND A LIST DOES NOT ENTER THE LEDGER JSON
    comparison_dict = get_comparison_baseline_dict({**stat_dict, "random_exit_list": return_list}, ["random_exit_median"])
    assert list(comparison_dict) == ["random_exit_median"]
    stored_dict = json.loads(get_baseline_json_str({**stat_dict, "random_exit_list": return_list, "missing": np.nan}))
    assert "random_exit_list" not in stored_dict and stored_dict["missing"] is None and stored_dict["random_exit_count"] == 4
    # A PATH WHOSE EQUITY IS ALREADY THE SPAN IS THE SAME OBJECT
    equity_pdf = pd.DataFrame({"date": ["2015-01-02", "2015-01-05"], "equity": [100.0, 101.0], "in_position": [True, True]})
    path_dict = {"daily_equity_pdf": equity_pdf, "metric_dict": {"total_return": 0.01}}
    assert get_span_path_dict(path_dict, None, "2015-01-02", "2015-01-05") is path_dict
    passed("family statistics and an exact span")

# RUN THE SUITE
if __name__ == "__main__":
    # A REDIRECTED WINDOWS LOG IS NOT CP1252
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    # THE FAMILY STATISTICS AND THE SPAN CUT
    test_family_and_span()
    print("\nAll holdout-baseline tests passed ✅", flush=True)
