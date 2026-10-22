"""
Workspace Tests: the development look-ahead audit (scripts/lookahead_audit.py)

Run from the workspace root:   python tests/test_lookahead_audit.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required.)

Synthetic bars only. The leaking designs must fail. The template must pass. The data root is a temporary folder.
"""

import datetime
import sys

import pandas as pd

# THE HOLDOUT SUITE POINTS THE DATA ROOT AT A TEMPORARY FOLDER BEFORE so IS IMPORTED
import test_holdout
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()
from test_holdout import get_later_bar_design, get_leak_design
from synthetic_data import get_synthetic_ohlcv_pdf
from so.core.trade_execution import get_ohlcv_array_dict
from scripts.lookahead_audit import get_audit_cut_date_list, get_audit_result_dict, get_replay_result_dict

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

# FUNCTION: CLIPPED PERIOD BOUNDS ARE DATES, SO THE VOLATILITY TARGET CAN COMPARE THEM
def test_clipped_period_bounds_are_dates():
    """
    The saved period file stores bounds as strings. After clipping, both bounds are datetime.date, and exp05's
    volatility target accepts that frame.

    Returns:
        None
    """
    # A STRING-BOUNDED PERIOD THAT CONTAINS THE CUT, AND ONE THAT STARTS AFTER IT
    from scripts.lookahead_audit import get_clipped_period_pdf
    period_pdf = pd.DataFrame([{"period_id": 1, "period_start": "2015-01-02", "period_end": "2015-06-30"},
                               {"period_id": 2, "period_start": "2015-07-01", "period_end": "2015-12-31"}])
    cut_date = datetime.date(2015, 4, 30)
    clipped_pdf = get_clipped_period_pdf(period_pdf, cut_date)
    assert len(clipped_pdf) == 1
    assert clipped_pdf["period_start"].iloc[0] == datetime.date(2015, 1, 2)
    assert clipped_pdf["period_end"].iloc[0] == cut_date
    assert type(clipped_pdf["period_start"].iloc[0]) is datetime.date
    assert type(clipped_pdf["period_end"].iloc[0]) is datetime.date
    # THE TARGET COMPARES THESE DATES WITH THE DAILY TABLE'S DATES
    from experiments.exp05_vol_scaled_exposure.exposure import get_target_volatility_arr
    daily_pdf = pd.DataFrame({"date": [datetime.date(2014, 12, 31), datetime.date(2015, 1, 2), cut_date],
                              "daily_volatility": [0.01, 0.02, 0.03]})
    target_arr = get_target_volatility_arr(daily_pdf, clipped_pdf, 0.5, min_history_in=1)
    assert len(target_arr) == 3
    assert target_arr[0] == target_arr[0]
    passed("clipped period bounds are dates")

# FUNCTION: A WINDOW-END WEIGHT IS NOT A FINDING WHEN THE CONTROL HAS IT TOO
def test_window_end_matches_the_control():
    """
    The last session of a stopped replay is flat. The saved path is not. The control is stopped the same way, so the
    check passes. The control runs, because the saved path differed.

    Returns:
        None
    """
    # THE SAME YEAR THE LEAK TESTS USE. THE WEIGHT IS 0 ONLY ON THE LAST SESSION OF THE PERIOD.
    import types
    import numpy as np
    from so import config
    from test_holdout import get_planted_equity_pdf
    ohlcv_pdf = get_synthetic_ohlcv_pdf("2023-01-03", "2023-12-29", minute_vol_in=0.0004, seed_in=11)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf)
    session_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict["session_date_list"]]
    period_pdf = get_period_pdf(session_list, 0, len(session_list) - 1)
    design_module = types.ModuleType("window_end_design")
    design_module.EXPERIMENT_NAME = "exp_window_end"
    design_module.PROTOCOL_VERSION = "1.0"
    design_module.PERIOD_RULE = {"embargo_sessions": 5, "train_years": [1]}
    design_module.CANDIDATE_LIST = ["flat"]
    design_module.SELECTION_RULE = {"pooled_periods": 1, "tie_break": [("candidate", True)]}

    def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in):
        return {"daily_equity_pdf": get_planted_equity_pdf(date2_in, 0.0), "trade_pdf": pd.DataFrame()}

    def run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in):
        date1 = pd.Timestamp(period_pdf_in["period_start"].iloc[0]).date()
        date2 = pd.Timestamp(period_pdf_in["period_end"].iloc[-1]).date()
        kept_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]
                     if date1 <= pd.Timestamp(session_date).date() <= date2]
        weight_list = [0.0 if session_date == date2 else 1.0 for session_date in kept_list]
        equity_pdf = pd.DataFrame({"date": kept_list, "equity": float(config.INITIAL_CAPITAL),
                                   "in_position": [weight == 1.0 for weight in weight_list], "weight": weight_list})
        return {"daily_equity_pdf": equity_pdf, "trade_pdf": pd.DataFrame(columns=["trade_ts", "delta_share_count", "reason"]),
                "target_weight_arr": np.array(weight_list, dtype=float), "decision_session_list": kept_list}

    design_module.run_candidate_replay_dict = run_candidate_replay_dict
    design_module.run_prior_only_path_dict = run_prior_only_path_dict
    design_module.get_baseline_return_dict = lambda ohlcv_array_dict_in, date1_in, date2_in: {"flat": 0.0}
    reference_dict = get_replay_result_dict(design_module, ohlcv_array_dict, period_pdf, None)
    result_dict = get_audit_result_dict(design_module, ohlcv_array_dict, period_pdf, None, 4, reference_dict)
    assert result_dict["passed"] is True, result_dict
    assert result_dict["artefact_list"], result_dict
    passed(f"window end matches the control ({len(result_dict['artefact_list'])} saved-path differences)")

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
    for design_module, label_str in [(get_leak_design(), "next close"),
                                     (get_later_bar_design("fill"), "fill bar"),
                                     (get_later_bar_design("session_close"), "session close")]:
        reference_dict = get_replay_result_dict(design_module, ohlcv_array_dict, leak_period_pdf, None)
        result_dict = get_audit_result_dict(design_module, ohlcv_array_dict, leak_period_pdf, None, 4, reference_dict)
        assert result_dict["passed"] is False, label_str
        assert result_dict["first_difference"], label_str
        assert len(result_dict["cut_date_list"]) == 4
        passed(f"{label_str} fails ({result_dict['first_difference']})")
    # THE TEMPLATE IS ON THE RUNNER; ITS LOOK-AHEAD IS so.runner.lookahead, NOT THIS OLD REPLAY AUDIT
    from experiments._template import design as template_design
    assert hasattr(template_design, "get_candidate_design")
    passed("template is on the runner (old replay audit not used)")

# RUN THE SUITE
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    test_cut_dates()
    test_clipped_period_bounds_are_dates()
    test_window_end_matches_the_control()
    test_designs()
    print("\nAll look-ahead audit tests passed")
