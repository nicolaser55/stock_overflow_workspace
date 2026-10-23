"""
Synthetic design for tests/test_experiments.py: records VixPrevHistory's three values at every decision.
"""
# IMPORT THE SHARED VIX HISTORY
from so.features.view_history import VixPrevHistory

# ONE CANDIDATE, SPY AND THE TWO VIX DAILY SOURCES
CANDIDATE_LIST = ["vix"]
DATA_SOURCE_LIST = ["SPY_1MIN", "VIX_DAILY", "VIX3M_DAILY"]
ENGINE_NAME = "fractional"
EXPERIMENT_NAME = "runner_vix_history_test"
PROTOCOL_VERSION = "test"


# CLASS: KEEP WEIGHT 1 AND LOG THE VIX VALUES
class VixLogDesign:
    """decide(view) returns 1 and appends (session, level, term, pct250)."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST

    # FUNCTION: EMPTY LOG
    def __init__(self):
        # THE HISTORY UNDER TEST
        self.history = VixPrevHistory()
        self.log_list = []

    # FUNCTION: LOG TODAY'S VALUES
    def decide(self, view_in):
        """
        Args:
            view_in: DecisionView

        Returns:
            float: 1
        """
        # ONE ROW PER DECISION
        value_dict = self.history.update(view_in)
        self.log_list.append({"session": view_in.session_date, **value_dict})
        return 1.0


# FUNCTION: A FRESH DESIGN
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): "vix"

    Returns:
        VixLogDesign: Fresh object
    """
    # ONE CANDIDATE
    return VixLogDesign()
