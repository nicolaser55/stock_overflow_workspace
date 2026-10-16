"""
Workspace Tests: the development look-ahead audit (scripts/lookahead_audit.py)

Run from the workspace root:   python tests/test_lookahead_audit.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

Synthetic bars only. The leaking designs must fail. The template must pass. The real trial log is not written.
"""

import os
import sys

import pandas as pd

# THE HOLDOUT SUITE POINTS THE DATA ROOT AT A TEMPORARY FOLDER BEFORE so IS IMPORTED
import test_holdout
from test_holdout import get_later_bar_design, get_leak_design
from synthetic_data import get_synthetic_ohlcv_pdf
from so.core.trade_execution import get_ohlcv_array_dict
from scripts.lookahead_audit import get_audit_cut_date_list, get_audit_result_dict, get_replay_result_dict

# THE REAL TRIAL LOG, MEASURED SO THIS SUITE CAN SHOW IT WAS NOT APPENDED
REAL_TRIAL_LOG_PATH_STR = "C:/Users/nico/Desktop/stock_overflow_data/store04_experiments/trial_log.csv"
REAL_TRIAL_LOG_SIZE_INT = os.path.getsize(REAL_TRIAL_LOG_PATH_STR)

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints a passing check.

    Args:
        name_str_in (str): What was checked

    Returns:
        None
    """
    # PRINT THE CHECK
    print(f"✅ {name_str_in}", flush=True)

# FUNCTION: ONE PERIOD COVERING A SPAN OF THE SYNTHETIC SESSIONS
def get_period_pdf(session_date_list_in, start_idx_in, end_idx_in):
    """
    One period. The audit clips it at each cut.

    Args:
        session_date_list_in (list): Sessions
        start_idx_in (int): First session of the period
        end_idx_in (int): Last session of the period

    Returns:
        pd.DataFrame: period_id, period_start, period_end, fold_id
    """
    # ONE PERIOD THE PATH CAN DECIDE ON
    return pd.DataFrame([{"period_id": 1, "fold_id": 1,
                          "period_start": session_date_list_in[start_idx_in],
                          "period_end": session_date_list_in[end_idx_in]}])

# FUNCTION: THE CUT DATES ARE MONTH-ENDS AFTER THE FIRST DECISION AND A QUARTER BEFORE THE END
def test_cut_dates():
    """
    Four month-ends, spread over the span. None falls on or before the first decision. The last is at least one
    quarter before the development end.

    Returns:
        None
    """
    # A LONG SESSION LIST, WITH THE FIRST DECISION IN FEBRUARY
    session_list = [day.date() for day in pd.bdate_range("2015-02-02", "2025-07-31")]
    first_date, end_date = session_list[0], session_list[-1]
    cut_list = get_audit_cut_date_list(session_list, first_date, end_date, 4)
    latest_date = (pd.Timestamp(end_date) - pd.DateOffset(months=3)).date()
    assert len(cut_list) == 4
    assert cut_list == sorted(cut_list)
    assert all(cut_date > first_date for cut_date in cut_list)
    assert cut_list[-1] <= latest_date
    # EACH CUT IS THE LAST SESSION OF ITS MONTH IN THIS LIST
    for cut_date in cut_list:
        month_list = [day for day in session_list if day.year == cut_date.year and day.month == cut_date.month and day <= latest_date]
        assert cut_date == max(month_list)
    # A MONTH-END EQUAL TO THE FIRST DECISION IS NOT A CUT
    month_end_date = max(day for day in session_list if day.year == first_date.year and day.month == first_date.month)
    cut_on_first_list = get_audit_cut_date_list(session_list, month_end_date, end_date, 4)
    assert all(cut_date > month_end_date for cut_date in cut_on_first_list)
    passed(f"four month-end cuts ({cut_list[0]} … {cut_list[-1]})")

# FUNCTION: LEAKING DESIGNS FAIL AND THE TEMPLATE PASSES
def test_designs():
    """
    The next-close leak, the fill bar and the session close fail. The template passes. No trial-log row is written.

    Returns:
        None
    """
    # ONE YEAR OF SYNTHETIC BARS. FOUR MONTH-ENDS FIT AFTER THE FIRST SESSION AND BEFORE THE LAST QUARTER.
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2023-01-03", "2023-12-29", minute_vol_in=0.0004, seed_in=11)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
    leak_period_pdf = get_period_pdf(session_list, 0, len(session_list) - 1)
    # THE TEMPLATE'S FIRST PREDICTION IS AFTER THE WARMUP, SO THE PERIOD STARTS LATER
    template_period_pdf = get_period_pdf(session_list, 60, len(session_list) - 1)
    for design_module, label_str in [(get_leak_design(), "next close"),
                                     (get_later_bar_design("fill"), "fill bar"),
                                     (get_later_bar_design("session_close"), "session close")]:
        reference_dict = get_replay_result_dict(design_module, ohlcv_array_dict, leak_period_pdf, None)
        result_dict = get_audit_result_dict(design_module, ohlcv_array_dict, leak_period_pdf, None, 4, reference_dict)
        assert result_dict["passed"] is False, label_str
        assert result_dict["first_difference"], label_str
        assert len(result_dict["cut_date_list"]) == 4
        passed(f"{label_str} fails ({result_dict['first_difference']})")
    from experiments._template import design as template_design
    template_reference_dict = get_replay_result_dict(template_design, ohlcv_array_dict, template_period_pdf, None)
    template_result_dict = get_audit_result_dict(template_design, ohlcv_array_dict, template_period_pdf, None, 4, template_reference_dict)
    assert template_result_dict["passed"] is True, template_result_dict["first_difference"]
    assert template_result_dict["first_difference"] == ""
    assert len(template_result_dict["cut_date_list"]) == 4
    assert os.path.getsize(REAL_TRIAL_LOG_PATH_STR) == REAL_TRIAL_LOG_SIZE_INT
    passed(f"template passes ({', '.join(template_result_dict['cut_date_list'])})")

# RUN THE SUITE
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    test_cut_dates()
    test_designs()
    assert os.path.getsize(REAL_TRIAL_LOG_PATH_STR) == REAL_TRIAL_LOG_SIZE_INT
    print("\nAll look-ahead audit tests passed")
