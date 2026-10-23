# IMPORT THE EXPERIMENT CONFIGURATION AND THE SHARED RULE DESIGN
from experiments.exp07_warning_lights_exit import config as exp_config
from so.features.rule_design import RuleDesign, get_light_count_int

"""
Runner Design: exp07_warning_lights_exit

Invested by default. Five fixed warning lights (config LIGHT_DICT; a missing feature is an off light). Exit at 15:59
when at least k lights are on; buy back when fewer than k - 1 are on. No forced buy-back. Trailing-stop engine
without a stop.
"""

# THE 3 CANDIDATES
CANDIDATE_LIST = [f"k{int(light_k)}" for light_k in exp_config.LIGHT_K_LIST]
_LIGHT_K_DICT = {f"k{int(light_k)}": int(light_k) for light_k in exp_config.LIGHT_K_LIST}

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
# TIES: THE LARGER k (FEWER EXITS)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("light_k", False)]}
CANDIDATE_TIE_VALUE_DICT = {"light_k": dict(_LIGHT_K_DICT)}
DATA_SOURCE_LIST = ["SPY_1MIN", "TSDAY"]
ENGINE_NAME = "trailing_stop"
INITIAL_WEIGHT = 1.0
MAX_CASH_SESSIONS = exp_config.MAX_CASH_SESSIONS


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Candidate name

    Returns:
        Design: Fresh object
    """
    # UNKNOWN NAMES ARE A DESIGN ERROR
    if str(candidate_in) not in _LIGHT_K_DICT:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return Design(str(candidate_in), {"light_k": _LIGHT_K_DICT[str(candidate_in)]})


# CLASS: ONE THRESHOLD k
class Design(RuleDesign):
    """Exit at >= k lights; buy back at < k - 1."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME
    COLUMN_LIST = sorted({feature_str for feature_str, _comparison, _threshold in exp_config.LIGHT_DICT.values()})

    # FUNCTION: AT LEAST k LIGHTS
    def get_exit_bool(self, row_in, view_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView

        Returns:
            bool: Exit signal
        """
        # COUNT TODAY'S LIGHTS
        return get_light_count_int(row_in, exp_config.LIGHT_DICT) >= int(self.candidate_dict["light_k"])

    # FUNCTION: FEWER THAN k - 1 LIGHTS
    def get_reentry_dict(self, row_in, view_in, state_dict_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView
            state_dict_in (dict): Engine snapshot

        Returns:
            dict: reentry_bool
        """
        # COUNT TODAY'S LIGHTS
        return {"reentry_bool": get_light_count_int(row_in, exp_config.LIGHT_DICT) < int(self.candidate_dict["light_k"]) - 1,
                "reentry_reason": "rule"}
