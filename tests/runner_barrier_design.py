"""
Synthetic barrier design for runner 4b-2a tests.

One candidate. Buys with a fixed delta when the engine snapshot is flat. Records engine_state at each decision.
"""

# ONE CANDIDATE
CANDIDATE_LIST = ["barrier"]
# DEVELOPMENT QUARTERS (TESTS INJECT PERIODS)
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
# POOL THE LAST TWO PERIODS
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("candidate", True)]}
# TRIAL LOG CONSTANTS
EXPERIMENT_NAME = "runner_barrier_test"
PROTOCOL_VERSION = "4b-2a"
# SPY BARS ONLY
DATA_SOURCE_LIST = ["SPY_1MIN"]
# ENGINE CONSTANTS
ENGINE_NAME = "barrier"
INITIAL_WEIGHT = 0.0
DELTA = 0.01


# FUNCTION: A DESIGN THAT BUYS WHEN FLAT
class BarrierDesign:
    """Buys with DELTA when the snapshot is not in a position."""

    # SPY ONLY
    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: EMPTY LOGS
    def __init__(self):
        """
        Args:
            None
        """
        # ONE ROW PER DECISION
        self.state_log_list = []
        self.session_date_list = []

    # FUNCTION: BUY WHEN FLAT
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            dict: target_weight and delta, or a keep
        """
        # THE SNAPSHOT IS A COPY AS OF THIS MOMENT
        state_dict = view_in.get_engine_state_dict()
        self.state_log_list.append(dict(state_dict))
        self.session_date_list.append(view_in.session_date)
        if state_dict["in_position"]:
            return {"target_weight": 0.0}
        return {"target_weight": 1.0, "delta": DELTA}


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Name in CANDIDATE_LIST

    Returns:
        BarrierDesign: Fresh object
    """
    # UNKNOWN NAMES ARE A TEST ERROR
    if str(candidate_in) not in CANDIDATE_LIST:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return BarrierDesign()
