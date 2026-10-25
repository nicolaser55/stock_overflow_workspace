import numpy as np

"""
Synthetic design for the look-ahead power test (audit B3). Fully invested; holds cash on a session whose latest
visible RUNNER_SPARSE_FEAT value is negative. The feature is -1 on about 8% of sessions, so the decision changes
rarely and only the sign matters: the kind of leak a level-only perturbation cannot see.
"""

CANDIDATE_LIST = ["sparse"]
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("candidate", True)]}
EXPERIMENT_NAME = "runner_sparse_leak_test"
PROTOCOL_VERSION = "audit-b3"
SPARSE_FEAT_STR = "RUNNER_SPARSE_FEAT"
DATA_SOURCE_LIST = ["SPY_1MIN", SPARSE_FEAT_STR]
DEAD_BAND = 0.0
INITIAL_WEIGHT = 1.0


class SparseDesign:
    """Cash when the latest visible feature value is negative."""

    DATA_SOURCE_LIST = ["SPY_1MIN", SPARSE_FEAT_STR]

    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float: Target weight
        """
        feat_pdf = view_in.get(SPARSE_FEAT_STR)
        value_float = float(feat_pdf["value"].iloc[-1]) if len(feat_pdf) else 1.0
        return 0.0 if value_float < 0 else float(np.float64(1.0))


def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Name in CANDIDATE_LIST

    Returns:
        SparseDesign: Fresh object
    """
    if str(candidate_in) not in CANDIDATE_LIST:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return SparseDesign()
