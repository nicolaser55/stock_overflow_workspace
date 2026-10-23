# IMPORT THE EXPERIMENT CONFIGURATION AND exp12'S DESIGN
from experiments.exp13_e1m1_robustness import config as exp_config
from experiments.exp12_vix_fear_reentry import design as exp12_design

"""
Runner Design: exp13_e1m1_robustness

exp12's rule E1M1 alone: one candidate, so no selection. The rule, its sources and its engine are exp12's.
"""

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
CANDIDATE_LIST = [exp_config.FROZEN_CANDIDATE_STR]
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("candidate", True)]}
DATA_SOURCE_LIST = list(exp12_design.DATA_SOURCE_LIST)
ENGINE_NAME = exp12_design.ENGINE_NAME
INITIAL_WEIGHT = exp12_design.INITIAL_WEIGHT
MAX_CASH_SESSIONS = exp12_design.MAX_CASH_SESSIONS


# FUNCTION: A FRESH DESIGN OBJECT FOR THE ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): "E1M1"

    Returns:
        exp12 Design: Fresh object
    """
    # ONLY THE FROZEN RULE
    if str(candidate_in) != exp_config.FROZEN_CANDIDATE_STR:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return exp12_design.get_candidate_design(exp_config.FROZEN_CANDIDATE_STR)
