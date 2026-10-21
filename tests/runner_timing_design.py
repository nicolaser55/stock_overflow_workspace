"""
Synthetic four-candidate design for timing the 4b-1c look-ahead check.

Constant weights. No file I/O. Tests inject periods.
"""

# FOUR CANDIDATES (CONSTANT WEIGHTS)
CANDIDATE_LIST = ["w0", "w25", "w50", "w100"]
# DEVELOPMENT QUARTERS (THE TIMING RUN INJECTS PERIODS)
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
# POOL THE LAST TWO PERIODS
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("candidate", True)]}
# TRIAL LOG CONSTANTS
EXPERIMENT_NAME = "runner_lookahead_timing"
PROTOCOL_VERSION = "4b-1c"
# SPY BARS ONLY
DATA_SOURCE_LIST = ["SPY_1MIN"]
# ENGINE CONSTANTS
DEAD_BAND = 0.0
INITIAL_WEIGHT = 1.0
# TARGET WEIGHT PER CANDIDATE
WEIGHT_DICT = {"w0": 0.0, "w25": 0.25, "w50": 0.5, "w100": 1.0}


# FUNCTION: A DESIGN THAT RETURNS A CONSTANT WEIGHT
class WeightDesign:
    """One target weight at every decision."""

    # SPY ONLY
    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: STORE THE WEIGHT
    def __init__(self, weight_in):
        """
        Args:
            weight_in (float): Target weight
        """
        # THE CANDIDATE'S RULE
        self.weight_float = float(weight_in)

    # FUNCTION: THE CONSTANT WEIGHT
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): Unused besides existing

        Returns:
            float: Target weight
        """
        # THE VIEW MUST EXIST
        assert view_in.decision_bar_idx >= 0
        return self.weight_float


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Name in CANDIDATE_LIST

    Returns:
        WeightDesign: Fresh object
    """
    # UNKNOWN NAMES ARE A TEST ERROR
    if str(candidate_in) not in WEIGHT_DICT:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return WeightDesign(WEIGHT_DICT[str(candidate_in)])
