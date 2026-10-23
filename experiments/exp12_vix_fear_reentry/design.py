import numpy as np
# IMPORT THE EXPERIMENT CONFIGURATION, THE SHARED RULE DESIGN AND THE VIX HISTORY
from experiments.exp12_vix_fear_reentry import config as exp_config
from so.features.rule_design import RuleDesign, get_value_float, get_light_count_int
from so.features.view_history import VixPrevHistory

"""
Runner Design: exp12_vix_fear_reentry

Two exits, each with three VIX modifications (6 candidates). Invested by default; trailing-stop engine without a stop;
no forced buy-back.
    E1  exit when the 15:58 close is below the 200-session average; original re-entry when it is back above
    E2  exit when at least 4 of exp07's 5 lights are on; original re-entry when fewer than 3 are on
    M1  also re-enter when vix_level_prev <= 0.85 x its maximum from the exit decision through today
    M2  also re-enter when vix_term_prev < 1 after it was >= 1 on some decision since the exit decision
    M3  ignore the exit while vix_term_prev >= 1 or vix_pct250_prev >= 0.9 (a missing value does not suppress)
After an M1 or M2 re-entry a new exit needs a fresh signal (off at least once). VIX values are the previous date's
close (VIX_DAILY, VIX3M_DAILY), at most 3 sessions old.
"""

# THE 6 CANDIDATES: E1M1, E1M2, E1M3, E2M1, E2M2, E2M3
CANDIDATE_LIST = [f"{exit_str}{modification_str}" for exit_str in exp_config.EXIT_RULE_STR_LIST for modification_str in exp_config.MODIFICATION_STR_LIST]

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("tie_order", True)]}
CANDIDATE_TIE_VALUE_DICT = {"tie_order": {name: int(exp_config.TIE_ORDER_DICT[name]) for name in CANDIDATE_LIST}}
DATA_SOURCE_LIST = ["SPY_1MIN", "TSDAY", "VIX_DAILY", "VIX3M_DAILY"]
ENGINE_NAME = "trailing_stop"
INITIAL_WEIGHT = 1.0
MAX_CASH_SESSIONS = exp_config.MAX_CASH_SESSIONS


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Candidate name, e.g. "E1M1"

    Returns:
        Design: Fresh object
    """
    # UNKNOWN NAMES ARE A DESIGN ERROR
    if str(candidate_in) not in CANDIDATE_LIST:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return Design(str(candidate_in), {"exit_rule": str(candidate_in)[:2], "modification": str(candidate_in)[2:]})


# CLASS: ONE EXIT AND ONE MODIFICATION
class Design(RuleDesign):
    """E1 / E2 with M1 / M2 / M3."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME
    COLUMN_LIST = sorted({exp_config.E1_MA_DIST_COL_STR} | {feature_str for feature_str, _comparison, _threshold in exp_config.E2_LIGHT_DICT.values()})

    # FUNCTION: ADD THE VIX HISTORY
    def __init__(self, candidate_str_in, candidate_dict_in):
        """
        Args:
            candidate_str_in (str): Candidate name
            candidate_dict_in (dict): exit_rule, modification
        """
        # THE RULE STATE AND THE VIX STATE
        super().__init__(candidate_str_in, candidate_dict_in)
        self.vix_history = VixPrevHistory()
        self.vix_dict = {"vix_level_prev": np.nan, "vix_term_prev": np.nan, "vix_pct250_prev": np.nan}

    # FUNCTION: TODAY'S VIX FEATURES (EVERY DECISION, SO THE HISTORY IS COMPLETE)
    def update_extra(self, view_in):
        """
        Args:
            view_in: DecisionView

        Returns:
            None
        """
        # THE PREVIOUS DATE'S CLOSES
        self.vix_dict = self.vix_history.update(view_in)

    # FUNCTION: THE BASE EXIT AND ITS ORIGINAL RE-ENTRY
    def get_base_tuple(self, row_in):
        """
        Args:
            row_in (dict): Today's row

        Returns:
            tuple: (exit_bool, original_reentry_bool)
        """
        # E1 ON THE AVERAGE; E2 ON THE LIGHTS
        if self.candidate_dict["exit_rule"] == "E1":
            dist_float = get_value_float(row_in, exp_config.E1_MA_DIST_COL_STR, 0.0)
            return dist_float < 0, dist_float > 0
        light_count = get_light_count_int(row_in, exp_config.E2_LIGHT_DICT)
        return light_count >= int(exp_config.E2_LIGHT_K), light_count < int(exp_config.E2_LIGHT_K) - 1

    # FUNCTION: THE EXIT, SUPPRESSED UNDER M3
    def get_exit_bool(self, row_in, view_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView

        Returns:
            bool: Exit signal
        """
        # M3 IGNORES THE EXIT IN FEAR (NaN COMPARISONS ARE FALSE)
        exit_bool = self.get_base_tuple(row_in)[0]
        if self.candidate_dict["modification"] == "M3":
            term_float, pct_float = self.vix_dict["vix_term_prev"], self.vix_dict["vix_pct250_prev"]
            suppress_bool = (np.isfinite(term_float) and term_float >= exp_config.M3_TERM_THRESHOLD) or \
                            (np.isfinite(pct_float) and pct_float >= exp_config.M3_PCT250_THRESHOLD)
            exit_bool = exit_bool and not suppress_bool
        return bool(exit_bool)

    # FUNCTION: ORIGINAL RE-ENTRY, THEN M1 / M2
    def get_reentry_dict(self, row_in, view_in, state_dict_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView
            state_dict_in (dict): Engine snapshot

        Returns:
            dict: reentry_bool, require_fresh_exit, reentry_reason
        """
        # THE BASE RULE FIRST
        if self.get_base_tuple(row_in)[1]:
            return {"reentry_bool": True, "reentry_reason": "original"}
        modification_str = self.candidate_dict["modification"]
        exit_session = state_dict_in["last_exit_session"]
        if modification_str == "M1":
            level_arr = self.vix_history.level_since_arr(exit_session)
            level_now = float(self.vix_dict["vix_level_prev"])
            finite_arr = level_arr[np.isfinite(level_arr)]
            if np.isfinite(level_now) and len(finite_arr) and level_now <= exp_config.M1_FADE_RATIO * float(finite_arr.max()):
                return {"reentry_bool": True, "require_fresh_exit": True, "reentry_reason": "M1"}
        if modification_str == "M2":
            term_arr = self.vix_history.term_since_arr(exit_session)
            term_now = float(self.vix_dict["vix_term_prev"])
            with np.errstate(invalid="ignore"):
                seen_bool = bool((term_arr >= exp_config.M2_TERM_THRESHOLD).any())
            if np.isfinite(term_now) and term_now < exp_config.M2_TERM_THRESHOLD and seen_bool:
                return {"reentry_bool": True, "require_fresh_exit": True, "reentry_reason": "M2"}
        return {"reentry_bool": False}
