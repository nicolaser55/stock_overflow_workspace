"""
Grade Of A Run (roadmap R4, decided by Nicolas on 2026-11-03; design 6.5)

The planner never sees numbers. Each run gets one grade, one main reason (a code and a fixed sentence) and an audit
state. The grade comes from the verdict; the first failing check in this order decides it:

    1  no verdict: crashed, timed out, the judge changed during the run, gave up    Failed: technical problem
    2  look-ahead check failed (the design used future data) or did not run          Failed: technical problem
    3  return check fails even with zero slippage                                     Failed: not better than buy-and-hold
    4  return check fails at the standard slippage, passes with zero slippage        Failed: gain disappears after costs
    5  return passes, consistency fails                                               Failed: inconsistent over time
    6  return and consistency pass; baselines or multiple testing fail               Failed: could be luck (too many attempts)
    7  every check passed                                                             Passed all checks (audit pending)

"Zero slippage" is the cost-sensitivity replay at 0.00 dollars per share on entries and market exits, with buy-and-hold
replayed the same way; broker fees are charged in both (so.runner.run.get_cost_sensitivity_list re-applies the full
return check to that replay). A run without that replay (a holdout run, a test) cannot tell rows 3 and 4 apart and
gets row 3 with the reason "return_below_buy_hold_no_cost_check".

A rejected job is not a run (no run id, no trial rows, not counted): it gets a technical status for the coder, never a
grade. A pass is "audit pending" until Nicolas (later the auditor agent) vetoes it or not; a veto is recorded later
(roadmap R6) and never upgrades a fail.

Every value written for the planner is on a fixed vocabulary: grades, reason codes and reason sentences contain no
digits (tests/test_grades.py checks it), so a grade file can carry no performance number.
"""

# THE SIX GRADES (DESIGN 6.5; FIXED)
GRADE_PASS_STR = "Passed all checks"
GRADE_NOT_BETTER_STR = "Failed: not better than buy-and-hold"
GRADE_COSTS_STR = "Failed: gain disappears after costs"
GRADE_INCONSISTENT_STR = "Failed: inconsistent over time"
GRADE_LUCK_STR = "Failed: could be luck (too many attempts)"
GRADE_TECHNICAL_STR = "Failed: technical problem"
GRADE_LIST = [GRADE_PASS_STR, GRADE_NOT_BETTER_STR, GRADE_COSTS_STR, GRADE_INCONSISTENT_STR, GRADE_LUCK_STR,
              GRADE_TECHNICAL_STR]
# AUDIT STATES OF A GRADE (ONLY A PASS IS EVER AUDITED)
AUDIT_PENDING_STR = "pending"
AUDIT_NOT_APPLICABLE_STR = "not applicable"
# THE REASONS: CODE -> (GRADE, SENTENCE). THE CODE IS WHAT PROGRAMS READ; THE SENTENCE IS FOR THE PLANNER AND THE LOG
REASON_DICT = {
    # TECHNICAL (NO VERDICT)
    "crashed": (GRADE_TECHNICAL_STR, "the run stopped with an error before it had a verdict"),
    "timeout": (GRADE_TECHNICAL_STR, "the run exceeded its time limit"),
    "judge_changed": (GRADE_TECHNICAL_STR, "the judge changed during the run, so the run was not scored"),
    "gave_up": (GRADE_TECHNICAL_STR, "the runner was interrupted too often while this run was running"),
    "no_verdict": (GRADE_TECHNICAL_STR, "the run finished without a verdict"),
    # TECHNICAL (LOOK-AHEAD)
    "look_ahead_failed": (GRADE_TECHNICAL_STR, "the look-ahead check failed: the design used future data"),
    "look_ahead_not_run": (GRADE_TECHNICAL_STR, "the look-ahead check did not run, so the run cannot pass"),
    # NOT BETTER THAN BUY-AND-HOLD
    "return_below_comparable": (GRADE_NOT_BETTER_STR,
                                "the return is below the comparable band of buy-and-hold, even with zero slippage"),
    "return_comparable_without_secondary": (GRADE_NOT_BETTER_STR,
                                            "the return is in the comparable band below buy-and-hold without a better "
                                            "Sharpe ratio or drawdown, even with zero slippage"),
    "return_below_buy_hold_no_cost_check": (GRADE_NOT_BETTER_STR,
                                            "the return check fails and this run has no zero-slippage replay"),
    # COSTS
    "return_passes_only_without_slippage": (GRADE_COSTS_STR,
                                            "the return check passes with zero slippage but fails at the standard "
                                            "slippage (broker fees are charged in both)"),
    # CONSISTENCY
    "too_few_decisive_windows": (GRADE_INCONSISTENT_STR,
                                 "too few rolling windows differ from buy-and-hold to judge consistency"),
    "behind_in_too_many_windows": (GRADE_INCONSISTENT_STR,
                                   "ahead of buy-and-hold in too few of the decisive rolling windows"),
    # LUCK (BASELINES, THEN MULTIPLE TESTING)
    "not_above_constant_exposure": (GRADE_LUCK_STR,
                                    "not above holding the same average exposure without any timing"),
    "not_above_random_timing": (GRADE_LUCK_STR, "not above enough of the random-timing draws"),
    "deflated_sharpe_below_bar": (GRADE_LUCK_STR,
                                  "the deflated Sharpe ratio is below the bar for the number of designs tried"),
    "random_timing_count_above_bar": (GRADE_LUCK_STR,
                                      "random timing does as well too often for the number of designs tried"),
    "multiple_testing_failed": (GRADE_LUCK_STR, "the multiple-testing check failed for the number of designs tried"),
    # PASS
    "all_checks_passed": (GRADE_PASS_STR, "every check passed; the audit is pending"),
}
# THE TECHNICAL REASON OF A QUEUE STATUS THAT HAS NO VERDICT
QUEUE_STATUS_REASON_DICT = {"failed": "crashed", "timeout": "timeout"}


# FUNCTION: ONE GRADE FROM A REASON CODE
def get_grade_from_reason_dict(reason_code_str_in):
    """
    Args:
        reason_code_str_in (str): A key of REASON_DICT

    Returns:
        dict: grade_str, reason_code_str, reason_str, audit_str
    """
    # AN UNKNOWN CODE IS A PROGRAMMING ERROR, NOT A GRADE
    if reason_code_str_in not in REASON_DICT:
        raise ValueError(f"unknown grade reason {reason_code_str_in!r}")
    grade_str, reason_str = REASON_DICT[reason_code_str_in]
    return {"grade_str": grade_str, "reason_code_str": reason_code_str_in, "reason_str": reason_str,
            "audit_str": AUDIT_PENDING_STR if grade_str == GRADE_PASS_STR else AUDIT_NOT_APPLICABLE_STR}


# FUNCTION: THE ZERO-SLIPPAGE ROW OF THE COST-SENSITIVITY LIST
def get_zero_slippage_row_dict(cost_sensitivity_list_in):
    """
    Args:
        cost_sensitivity_list_in (list[dict] | None): report["cost_sensitivity_list"]

    Returns:
        dict | None: The row at slippage 0.00 that carries the re-applied return check, or None
    """
    # ONLY A ROW WITH THE RETURN CHECK (R4) COUNTS; OLDER ROWS HOLD TOTAL RETURNS ONLY
    for row_dict in list(cost_sensitivity_list_in or []):
        try:
            slippage_float = float(row_dict.get("slippage_per_share"))
        except (TypeError, ValueError, AttributeError):
            continue
        if abs(slippage_float) < 1e-12 and row_dict.get("return_pass_bool") is not None:
            return row_dict
    return None


# FUNCTION: THE GRADE OF A FINISHED RUN FROM ITS VERDICT
def get_run_grade_dict(verdict_dict_in, cost_sensitivity_list_in=None):
    """
    Args:
        verdict_dict_in (dict): Output of so.runner.verdict.get_runner_verdict_dict (or a report.json payload: the
            same part dicts)
        cost_sensitivity_list_in (list[dict] | None): The report's cost_sensitivity_list (None = no replay)

    Returns:
        dict: grade_str, reason_code_str, reason_str, audit_str
    """
    # 2: LOOK-AHEAD FIRST (A LEAK MAKES EVERY OTHER NUMBER MEANINGLESS)
    look_ahead_dict = verdict_dict_in.get("look_ahead_dict") or {}
    status_str = str(look_ahead_dict.get("status_str", ""))
    if status_str == "fail":
        return get_grade_from_reason_dict("look_ahead_failed")
    if not bool(look_ahead_dict.get("pass_bool")):
        return get_grade_from_reason_dict("look_ahead_not_run")
    # 3 AND 4: THE RETURN CHECK, THEN THE SAME CHECK WITH ZERO SLIPPAGE
    return_dict = verdict_dict_in.get("return_dict") or {}
    if not bool(return_dict.get("pass_bool")):
        zero_row_dict = get_zero_slippage_row_dict(cost_sensitivity_list_in)
        if zero_row_dict is None:
            return get_grade_from_reason_dict("return_below_buy_hold_no_cost_check")
        if bool(zero_row_dict.get("return_pass_bool")):
            return get_grade_from_reason_dict("return_passes_only_without_slippage")
        if str(zero_row_dict.get("return_reason_str", "")) == "comparable_without_secondary":
            return get_grade_from_reason_dict("return_comparable_without_secondary")
        return get_grade_from_reason_dict("return_below_comparable")
    # 5: CONSISTENCY
    consistency_dict = verdict_dict_in.get("consistency_dict") or {}
    if not bool(consistency_dict.get("pass_bool")):
        if consistency_dict.get("enough_decisive_bool") is False:
            return get_grade_from_reason_dict("too_few_decisive_windows")
        return get_grade_from_reason_dict("behind_in_too_many_windows")
    # 6: BASELINES, THEN MULTIPLE TESTING
    baseline_dict = verdict_dict_in.get("baseline_dict") or {}
    if not bool(baseline_dict.get("pass_bool")):
        if not bool(baseline_dict.get("constant_pass_bool")):
            return get_grade_from_reason_dict("not_above_constant_exposure")
        return get_grade_from_reason_dict("not_above_random_timing")
    multiple_dict = verdict_dict_in.get("multiple_testing_dict") or {}
    if not bool(multiple_dict.get("pass_bool")):
        if multiple_dict.get("dsr_pass_bool") is False:
            return get_grade_from_reason_dict("deflated_sharpe_below_bar")
        if multiple_dict.get("random_pass_bool") is False:
            return get_grade_from_reason_dict("random_timing_count_above_bar")
        return get_grade_from_reason_dict("multiple_testing_failed")
    # 7: EVERY CHECK PASSED (THE FAILED LIST MUST AGREE; A DISAGREEMENT IS NEVER A PASS)
    if list(verdict_dict_in.get("failed_list") or []):
        return get_grade_from_reason_dict("no_verdict")
    return get_grade_from_reason_dict("all_checks_passed")


# FUNCTION: THE GRADE OF A QUEUE RESULT (A FINISHED RUN, OR ONE WITHOUT A VERDICT)
def get_queue_grade_dict(status_str_in, manifest_verdict_dict_in=None, judge_problem_str_in="", gave_up_bool_in=False):
    """
    The queue has the manifest, not the verdict parts: the run wrote its grade into the manifest's verdict. Without a
    verdict, or with a problem the queue found itself, the grade is technical.

    Args:
        status_str_in (str): done, failed or timeout
        manifest_verdict_dict_in (dict | None): manifest["verdict"] (grade, grade_reason_code)
        judge_problem_str_in (str): The queue's judge check ("" = none)
        gave_up_bool_in (bool): The runner gave up after repeated interruptions

    Returns:
        dict: grade_str, reason_code_str, reason_str, audit_str
    """
    # THE QUEUE'S OWN FINDINGS FIRST
    if gave_up_bool_in:
        return get_grade_from_reason_dict("gave_up")
    if judge_problem_str_in:
        return get_grade_from_reason_dict("judge_changed")
    if status_str_in != "done":
        return get_grade_from_reason_dict(QUEUE_STATUS_REASON_DICT.get(status_str_in, "crashed"))
    # A FINISHED RUN: THE CODE THE RUN RECORDED, CHECKED AGAINST THE VOCABULARY
    verdict_dict = dict(manifest_verdict_dict_in or {})
    reason_code_str = str(verdict_dict.get("grade_reason_code") or "")
    if reason_code_str not in REASON_DICT or REASON_DICT[reason_code_str][0] != verdict_dict.get("grade"):
        return get_grade_from_reason_dict("no_verdict")
    if REASON_DICT[reason_code_str][0] == GRADE_PASS_STR and not bool(verdict_dict.get("email_worthy")):
        return get_grade_from_reason_dict("no_verdict")
    return get_grade_from_reason_dict(reason_code_str)
