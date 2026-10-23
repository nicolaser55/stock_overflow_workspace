import numpy as np
# IMPORT THE EXPERIMENT CONFIGURATION AND THE SHARED RULE DESIGN
from experiments.exp06_capped_regret_reentry import config as exp_config
from so.features.rule_design import RuleDesign, get_value_float

"""
Runner Design: exp06_capped_regret_reentry

Invested by default. Exit at 15:59 on trend_ma200 (15:58 close below the 200-session average) or ath_1pct (within 1%
of the all-time high). Re-enter on whichever comes first:
    buy-stop   the 15:58 close is at least b above the sale fill price; then exits are ignored for c decisions
    recovery   the close is above the 200-session average after at least one close below it since the exit decision
No forced buy-back. Trailing-stop engine without a stop.
"""

# THE 12 CANDIDATES: EXIT SIGNAL, THEN BUY-STOP, THEN COOLING-OFF
_CANDIDATE_DICT_LIST = [{"exit_signal": exit_str, "exit_order": int(exit_order), "buy_stop": float(buy_stop), "cooling": int(cooling),
                         "name": f"{exit_str}|{float(buy_stop):.2f}|{int(cooling)}"}
                        for exit_str, exit_order in sorted(exp_config.EXIT_SIGNAL_ORDER_DICT.items(), key=lambda item: item[1])
                        for buy_stop in exp_config.BUY_STOP_LIST for cooling in exp_config.COOLING_LIST]
_CANDIDATE_BY_NAME_DICT = {candidate_dict["name"]: candidate_dict for candidate_dict in _CANDIDATE_DICT_LIST}

# THE RUNNER INTERFACE
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
CANDIDATE_LIST = [candidate_dict["name"] for candidate_dict in _CANDIDATE_DICT_LIST]
# TIES: THE LONGER COOLING-OFF, THEN THE SMALLER BUY-STOP, THEN THE TREND EXIT
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT,
                  "tie_break": [("cooling", False), ("buy_stop", True), ("exit_order", True)]}
CANDIDATE_TIE_VALUE_DICT = {key_str: {name: _CANDIDATE_BY_NAME_DICT[name][key_str] for name in CANDIDATE_LIST}
                            for key_str in ("cooling", "buy_stop", "exit_order")}
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


# CLASS: ONE EXIT, ONE BUY-STOP, ONE COOLING-OFF
class Design(RuleDesign):
    """Trend or near-ATH exit; buy-stop or recovery re-entry."""

    DATA_SOURCE_LIST = DATA_SOURCE_LIST
    ENGINE_NAME = ENGINE_NAME
    COLUMN_LIST = ["ma200_dist_pct", "ath_drawdown_pct", "decision_close"]

    # FUNCTION: THE CANDIDATE'S EXIT SIGNAL
    def get_exit_bool(self, row_in, view_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView

        Returns:
            bool: Exit signal (a missing feature never exits)
        """
        # TREND OR NEAR-ATH
        if self.candidate_dict["exit_signal"] == "trend_ma200":
            return get_value_float(row_in, "ma200_dist_pct", 0.0) < 0
        return get_value_float(row_in, "ath_drawdown_pct", -np.inf) >= -float(exp_config.ATH_WITHIN)

    # FUNCTION: BUY-STOP FIRST, THEN RECOVERY
    def get_reentry_dict(self, row_in, view_in, state_dict_in):
        """
        Args:
            row_in (dict): Today's row
            view_in: DecisionView
            state_dict_in (dict): Engine snapshot

        Returns:
            dict: reentry_bool, exit_block_sessions, reentry_reason
        """
        # THE CLOSE AT LEAST b ABOVE THE SALE FILL PRICE
        exit_price = state_dict_in.get("last_exit_fill_price")
        close_float = float(row_in.get("decision_close", np.nan))
        if exit_price is not None and np.isfinite(close_float) and close_float >= float(exit_price) * (1.0 + self.candidate_dict["buy_stop"]):
            return {"reentry_bool": True, "exit_block_sessions": int(self.candidate_dict["cooling"]), "reentry_reason": "buy_stop"}
        # ABOVE THE AVERAGE AFTER AT LEAST ONE CLOSE BELOW IT SINCE THE EXIT DECISION (MISSING = 0)
        since_arr = np.nan_to_num(self.get_since_exit_arr("ma200_dist_pct", state_dict_in), nan=0.0)
        recovery_bool = bool((since_arr < 0).any()) and get_value_float(row_in, "ma200_dist_pct", 0.0) > 0
        return {"reentry_bool": recovery_bool, "exit_block_sessions": 0, "reentry_reason": "recovery"}
