"""
Synthetic design for runner 4b-1a tests.

Three candidates: two always-invested twins (a tie) and one always-cash. No file I/O. Tests inject periods; PERIOD_RULE
is present so a PERIOD_RULE wiring test can read it.
"""

# THE THREE CANDIDATES (one_a AND one_b ARE A TIE ON EVERY PERIOD)
CANDIDATE_LIST = ["one_a", "one_b", "zero"]
# DEVELOPMENT QUARTERS (USED WHEN A TEST DOES NOT INJECT PERIODS)
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
# POOL THE LAST TWO PERIODS; TIES GO TO THE LOWER tie_order, THEN THE NAME
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("tie_order", True), ("candidate", True)]}
# TIE COLUMN THE RUNNER ATTACHES
CANDIDATE_TIE_VALUE_DICT = {"tie_order": {"one_a": 1, "one_b": 0, "zero": 2}}
# TRIAL LOG CONSTANTS
EXPERIMENT_NAME = "runner_candidate_test"
PROTOCOL_VERSION = "4b-1a"
# SPY BARS ONLY
DATA_SOURCE_LIST = ["SPY_1MIN"]
# ENGINE CONSTANTS
DEAD_BAND = 0.0
INITIAL_WEIGHT = 1.0
# TARGET WEIGHT PER CANDIDATE
WEIGHT_DICT = {"one_a": 1.0, "one_b": 1.0, "zero": 0.0}


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
