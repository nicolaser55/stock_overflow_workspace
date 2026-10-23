import numpy as np
# IMPORT THE EXPERIMENT CONFIGURATION AND THE SHARED RULE DESIGN
from experiments.exp03_ath_exit import config as exp_config
from so.features.rule_design import RuleDesign, get_value_float

"""
Runner Design: exp03_ath_exit ("sell at strength")

Invested by default. Sell at 15:59 when the 15:58 close is within x of the all-time high (ath_drawdown_pct >= -x; a
missing value never exits). Buy back after n cash decisions, or when the 15:58 close is d below the sale fill price.
Forced buy-back after MAX_CASH_SESSIONS cash decisions. Trailing-stop engine without a stop.
"""

# THE 15 CANDIDATES IN A FIXED ORDER: THRESHOLD, THEN THE DELAYS, THEN THE DIPS
_CANDIDATE_DICT_LIST = []
for _ath_within in exp_config.ATH_WITHIN_LIST:
    for _delay in exp_config.BUYBACK_DELAY_LIST:
        _CANDIDATE_DICT_LIST.append({"ath_within": float(_ath_within), "buyback_type": "delay", "buyback_value": float(_delay),
                                     "name": f"{float(_ath_within):.3f}|delay_{int(_delay)}"})
    for _dip in exp_config.BUYBACK_DIP_LIST:
        _CANDIDATE_DICT_LIST.append({"ath_within": float(_ath_within), "buyback_type": "dip", "buyback_value": float(_dip),
                                     "name": f"{float(_ath_within):.3f}|dip_{int(round(_dip * 100))}pct"})
_CANDIDATE_BY_NAME_DICT = {candidate_dict["name"]: candidate_dict for candidate_dict in _CANDIDATE_DICT_LIST}

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
CANDIDATE_LIST = [candidate_dict["name"] for candidate_dict in _CANDIDATE_DICT_LIST]
# TIES: THE TIGHTER THRESHOLD, THEN THE LIST ORDER
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("ath_within", True), ("rule_order", True)]}
CANDIDATE_TIE_VALUE_DICT = {"ath_within": {name: _CANDIDATE_BY_NAME_DICT[name]["ath_within"] for name in CANDIDATE_LIST},
                            "rule_order": {name: idx for idx, name in enumerate(CANDIDATE_LIST)}}
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
    if str(candidate_in) not in _CANDIDATE_BY_NAME_DICT:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return Design(str(candidate_in), _CANDIDATE_BY_NAME_DICT[str(candidate_in)])


# CLASS: ONE THRESHOLD AND ONE BUY-BACK
class Design(RuleDesign):
    """Exit near the ATH; delay or dip buy-back."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME
    COLUMN_LIST = ["ath_drawdown_pct", "decision_close"]

    # FUNCTION: WITHIN x OF THE ALL-TIME HIGH
    def get_exit_bool(self, row_in, view_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView

        Returns:
            bool: Exit signal
        """
        # A MISSING DISTANCE NEVER EXITS
        return get_value_float(row_in, "ath_drawdown_pct", -np.inf) >= -self.candidate_dict["ath_within"]

    # FUNCTION: DELAY OR DIP
    def get_reentry_dict(self, row_in, view_in, state_dict_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView
            state_dict_in (dict): Engine snapshot

        Returns:
            dict: reentry_bool, reentry_reason
        """
        # n CASH DECISIONS, THIS ONE INCLUDED
        if self.candidate_dict["buyback_type"] == "delay":
            return {"reentry_bool": int(state_dict_in["cash_session_count"]) >= int(self.candidate_dict["buyback_value"]),
                    "reentry_reason": "delay"}
        # THE CLOSE d BELOW THE SALE FILL PRICE
        exit_price = state_dict_in.get("last_exit_fill_price")
        close_float = float(row_in.get("decision_close", np.nan))
        reentry_bool = exit_price is not None and np.isfinite(close_float) and close_float <= float(exit_price) * (1.0 - self.candidate_dict["buyback_value"])
        return {"reentry_bool": bool(reentry_bool), "reentry_reason": "dip"}
