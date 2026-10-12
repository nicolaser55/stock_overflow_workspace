import pandas as pd
# IMPORT THE EXPERIMENT CONFIGURATION
from experiments.exp02_stop_reentry import config as exp_config
# IMPORT THE EVALUATION FUNCTIONS (POOLED SELECTION)
from so.core.evaluation import get_pooled_selection_pdf as get_generic_pooled_selection_pdf

"""
Selection rule of exp02 protocol 1.0, unchanged in version 2.0

Mean excess return over the last 4 quarters. Ties: larger k, higher offset, then the 10-year window before all history.
"""

# FUNCTION: ADD THE POOLED SELECTION SCORE AND PICK ONE CANDIDATE PER FOLD
def get_pooled_selection_pdf(candidate_pdf_in, pooled_quarter_count_in=exp_config.SELECTION_POOLED_QUARTER_COUNT):
    """
    Scores every candidate of fold f by the mean validation excess return of the same candidate over folds
    f - pooled_quarter_count_in + 1 .. f (fewer for the first folds) and selects the best candidate per fold.
    Ties: larger k, higher offset, then the shorter training window ("10Y" before "ALL").

    Args:
        candidate_pdf_in (pd.DataFrame): One row per candidate and fold
        pooled_quarter_count_in (int): Number of validation quarters pooled

    Returns:
        pd.DataFrame: One selected row per fold
    """
    # ADD THE TRAINING WINDOW ORDER (10Y BEFORE ALL; THE OLD NAMES 10y AND all SORT THE SAME WAY)
    order_dict = {window_str: idx for idx, window_str in enumerate(exp_config.TRAIN_WINDOW_CANDIDATE_LIST)}
    order_dict.update({"10y": 0, "all": 1})
    candidate_pdf = candidate_pdf_in.assign(window_order=candidate_pdf_in["train_window"].map(order_dict))
    # SELECT WITH THE GENERIC POOLED RULE
    selection_pdf = get_generic_pooled_selection_pdf(candidate_pdf, ["train_window", "stop_k", "threshold_offset"], "valid_excess_return", pooled_quarter_count_in,
                                                     [("stop_k", False), ("threshold_offset", False), ("window_order", True)])
    # RETURN THE SELECTION
    return selection_pdf.rename(columns={"pooled_score": "pooled_valid_excess_return"}).drop(columns=["window_order"])
