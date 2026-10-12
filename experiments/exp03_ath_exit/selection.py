import pandas as pd
# IMPORT THE EXPERIMENT CONFIGURATION
from experiments.exp03_ath_exit import config as exp_config
# IMPORT THE GENERIC POOLED SELECTION
from so.core.evaluation import get_pooled_selection_pdf as get_generic_pooled_selection_pdf

"""
Selection: exp03_ath_exit_v2

Mean excess over the last 4 quarters. Ties: the tighter ATH threshold, then the rule order. This is the protocol 1.0
rule, kept so a synthetic table still selects the same way.
"""

# FUNCTION: ADD THE POOLED SELECTION SCORE AND PICK ONE RULE PER FOLD
def get_pooled_selection_pdf(candidate_pdf_in, pooled_quarter_count_in=exp_config.SELECTION_POOLED_QUARTER_COUNT):
    """
    Scores every rule of fold f by its mean validation excess return over the last pooled quarters and selects the
    best rule per fold. Ties: the tighter ATH threshold, then the rule order.

    Args:
        candidate_pdf_in (pd.DataFrame): Candidate rows (ath_within, rule, rule_order, valid_excess_return, fold_id)
        pooled_quarter_count_in (int): Number of validation quarters pooled

    Returns:
        pd.DataFrame: One selected row per fold
    """
    # SELECT WITH THE GENERIC POOLED RULE
    selection_pdf = get_generic_pooled_selection_pdf(candidate_pdf_in, ["ath_within", "rule"], "valid_excess_return", pooled_quarter_count_in,
                                                     [("ath_within", True), ("rule_order", True)])
    # RETURN THE SELECTION
    return selection_pdf.rename(columns={"pooled_score": "pooled_valid_excess_return"})
