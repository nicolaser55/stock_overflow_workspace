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
run_candidate_replay_dict = exp12_design.run_candidate_replay_dict
run_prior_only_path_dict = exp12_design.run_prior_only_path_dict
get_development_data_context = exp12_design.get_development_data_context
get_session_candidate_str = exp12_design.get_session_candidate_str

# FUNCTION: PATH-MATCHED BASELINES LIVE IN THE REPORT
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in):
    """
    The unmodified E1 path and the random families are computed in the report.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span

    Returns:
        dict: Empty
    """
    # THE BASELINES NEED THE PATH
    return {}
