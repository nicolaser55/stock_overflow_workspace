"""
Synthetic trailing-stop design for runner 4b-2a tests.

One candidate. Re-enters when the engine snapshot is in cash. Constant k and volatility. No flatten. Records
engine_state at each decision so a stop-out visibility test can read it.
"""

# ONE CANDIDATE
CANDIDATE_LIST = ["trail"]
# DEVELOPMENT QUARTERS (TESTS INJECT PERIODS)
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
# POOL THE LAST TWO PERIODS
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("candidate", True)]}
# TRIAL LOG CONSTANTS
EXPERIMENT_NAME = "runner_trailing_test"
PROTOCOL_VERSION = "4b-2a"
# SPY BARS ONLY
DATA_SOURCE_LIST = ["SPY_1MIN"]
# ENGINE CONSTANTS
ENGINE_NAME = "trailing_stop"
INITIAL_WEIGHT = 1.0
MAX_CASH_SESSIONS = 20
TRAIL_MULTIPLE = 2.0
VOLATILITY = 0.01


# FUNCTION: A DESIGN THAT RE-ENTERS FROM THE ENGINE SNAPSHOT
class TrailDesign:
    """Re-enters when cash. Records engine_state at each call."""

    # SPY ONLY
    DATA_SOURCE_LIST = ["SPY_1MIN"]

    # FUNCTION: EMPTY LOGS
    def __init__(self, trail_multiple_in=TRAIL_MULTIPLE, volatility_in=VOLATILITY):
        """
        Args:
            trail_multiple_in (float): k
            volatility_in (float): Daily volatility
        """
        # ONE ROW PER DECISION
        self.trail_multiple_float = float(trail_multiple_in)
        self.volatility_float = float(volatility_in)
        self.state_log_list = []
        self.session_date_list = []
        self.raised_bool = False

    # FUNCTION: RE-ENTER WHEN THE SNAPSHOT IS IN CASH
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            dict: target_weight, trail_multiple, volatility
        """
        # THE SNAPSHOT IS A COPY AS OF THIS MOMENT
        state_dict = view_in.get_engine_state_dict()
        self.state_log_list.append(dict(state_dict))
        self.session_date_list.append(view_in.session_date)
        target_weight = 1.0 if not state_dict["in_position"] else float("nan")
        return {"target_weight": target_weight, "flatten_bool": False, "trail_multiple": self.trail_multiple_float,
                "volatility": self.volatility_float, "reentry_reason": "delay"}


# FUNCTION: A DESIGN THAT TRIES TO WRITE THE ENGINE SNAPSHOT
class MutatingTrailDesign(TrailDesign):
    """Same re-entry as TrailDesign. Assigns into view.engine_state to prove it is read-only."""

    # FUNCTION: RE-ENTER AND TRY TO MUTATE THE PROXY
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            dict: target_weight, trail_multiple, volatility
        """
        # THE COPY IS MUTABLE; THE PROXY IS NOT
        state_dict = view_in.get_engine_state_dict()
        self.state_log_list.append(dict(state_dict))
        self.session_date_list.append(view_in.session_date)
        state_dict["in_position"] = not state_dict["in_position"]
        try:
            view_in.engine_state["in_position"] = False
        except TypeError:
            self.raised_bool = True
        target_weight = 1.0 if not self.state_log_list[-1]["in_position"] else float("nan")
        return {"target_weight": target_weight, "flatten_bool": False, "trail_multiple": self.trail_multiple_float,
                "volatility": self.volatility_float, "reentry_reason": "delay"}



# CLASS: A DESIGN WHOSE STOP VOLATILITY CHANGES EVERY SESSION
class VaryingTrailDesign(TrailDesign):
    """Same re-entry as TrailDesign. Volatility cycles 0.004 / 0.008 / 0.012 by session index (known at the moment)."""

    # FUNCTION: RE-ENTER WHEN IN CASH, WITH A SESSION-DEPENDENT STOP
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            dict: target_weight, trail_multiple, volatility
        """
        # THE SESSION INDEX IS PART OF THE MOMENT, NOT THE FUTURE
        state_dict = view_in.get_engine_state_dict()
        self.state_log_list.append(dict(state_dict))
        self.session_date_list.append(view_in.session_date)
        target_weight = 1.0 if not state_dict["in_position"] else float("nan")
        volatility_float = 0.004 * (1 + int(view_in.session_idx) % 3)
        return {"target_weight": target_weight, "flatten_bool": False, "trail_multiple": self.trail_multiple_float,
                "volatility": volatility_float, "reentry_reason": "delay"}

# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Name in CANDIDATE_LIST

    Returns:
        TrailDesign: Fresh object
    """
    # UNKNOWN NAMES ARE A TEST ERROR
    if str(candidate_in) not in CANDIDATE_LIST:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return TrailDesign()
