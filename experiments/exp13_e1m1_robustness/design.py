# IMPORT THE FROZEN RULE'S DESIGN AND THIS EXPERIMENT'S CONFIGURATION
from experiments.exp12_vix_fear_reentry import design as exp12_design
from experiments.exp13_e1m1_robustness import config as exp_config

"""
Holdout Design: exp13_e1m1_robustness_v2

The frozen rule E1M1, one candidate. Re-run under the current rules, not new evidence. The robustness steps of
protocol 1.0 are not repeated. The path is exp12's implementation of E1M1.
"""

# ONE CANDIDATE. SELECTION IS VACUOUS.
CANDIDATE_LIST = ["E1M1"]
SELECTION_RULE = {"pooled_periods": exp12_design.SELECTION_RULE["pooled_periods"], "tie_break": [("tie_order", True)]}
CANDIDATE_TIE_VALUE_DICT = {"tie_order": {"E1M1": int(exp_config.FROZEN_CANDIDATE_DICT["tie_order"])}}
PERIOD_RULE = dict(exp12_design.PERIOD_RULE)
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
DATA_SOURCE_LIST = list(exp12_design.DATA_SOURCE_LIST)

# THE REPLAY IS exp12'S, WHICH ALREADY KNOWS E1M1
get_bar_period_pdf = exp12_design.get_bar_period_pdf
run_candidate_replay_dict = exp12_design.run_candidate_replay_dict
run_prior_only_path_dict = exp12_design.run_prior_only_path_dict
get_development_data_context = exp12_design.get_development_data_context
get_session_candidate_str = exp12_design.get_session_candidate_str

# THE RETURNS THE DEVELOPMENT REPORT PASSES TO THE SUCCESS CRITERIA
BASELINE_COMPARISON_KEY_LIST = ["unmodified_e1", "random_exit_median", "random_reentry_median"]

# FUNCTION: E1M1'S RANDOM FAMILIES AND, WHEN PERIODS ARE PASSED, UNMODIFIED E1
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None, path_dict_in=None, period_pdf_in=None):
    """
    The random families are exp12's, on this path, with exp12's seeds. When period_pdf_in is passed, every period is
    forced to E1none and that path's total return is unmodified_e1. The same function is the development report.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span
        data_context_in (DataContext | None): Point-in-time context
        path_dict_in (dict | None): Prior-only path
        period_pdf_in (pd.DataFrame | None): Periods, required for unmodified E1

    Returns:
        dict: Both random families and, with periods, unmodified E1
    """
    # THE RANDOM FAMILIES. PERIODS ARE NOT PASSED, SO exp12 DOES NOT ADD ITS OWN UNMODIFIED PATH
    import pandas as pd
    return_dict = exp12_design.get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in, data_context_in, path_dict_in)
    # UNMODIFIED E1: EVERY PERIOD IS E1none
    if period_pdf_in is not None:
        selection_pdf = pd.DataFrame({"period_id": period_pdf_in["period_id"].astype(int), "candidate": "E1none", "candidate_idx": 0})
        unmodified_dict = exp12_design.run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf, data_context_in)
        return_dict["unmodified_e1"] = unmodified_dict["metric_dict"]["total_return"]
    return return_dict
