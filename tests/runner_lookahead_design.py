"""
Synthetic design for runner 4b-1c look-ahead tests.

One candidate. decide() packs the last sliced close, the last visible feature row, and the last visible label row
into target_weight. The file does not import banned modules and does not read .base.
"""

# ONE CANDIDATE WHOSE DECISION MOVES WHEN THE VIEW LEAKS
CANDIDATE_LIST = ["read"]
# DEVELOPMENT QUARTERS (TESTS INJECT PERIODS)
PERIOD_RULE = {"embargo_sessions": 1, "train_years": [1]}
# POOL THE LAST TWO PERIODS
SELECTION_RULE = {"pooled_periods": 2, "tie_break": [("candidate", True)]}
# TRIAL LOG CONSTANTS
EXPERIMENT_NAME = "runner_lookahead_test"
PROTOCOL_VERSION = "4b-1c"
# FEATURE AND LABEL NAMES THE TEST REGISTERS
LOOKAHEAD_FEAT_STR = "RUNNER_LOOKAHEAD_FEAT"
LOOKAHEAD_LABEL_STR = "RUNNER_LOOKAHEAD_LABEL"
# DECLARED SOURCES
DATA_SOURCE_LIST = ["SPY_1MIN", LOOKAHEAD_FEAT_STR, LOOKAHEAD_LABEL_STR]
# ENGINE CONSTANTS
DEAD_BAND = 0.0
INITIAL_WEIGHT = 1.0


# FUNCTION: PACK THE THREE READINGS INTO A WEIGHT IN [0, 1]
def get_packed_weight_float(close_float_in, feat_float_in, label_float_in):
    """
    A change in any reading moves the weight by more than NUMERIC_TOLERANCE.

    Args:
        close_float_in, feat_float_in, label_float_in (float): Last visible values

    Returns:
        float: Target weight
    """
    # CLOSE IS O(100), FEAT IS O(1000), LABEL IS O(1e6)
    packed_float = 0.5 + (float(close_float_in) - 100.0) / 1000.0 + float(feat_float_in) / 1.0e6 + float(label_float_in) / 1.0e9
    if packed_float < 0.0:
        return 0.0
    if packed_float > 1.0:
        return 1.0
    return float(packed_float)


# FUNCTION: A DESIGN THAT READS BARS, FEATURES AND LABELS
class ViewReadDesign:
    """Packs the last sliced close, feature value and label value."""

    # THE THREE SOURCES
    DATA_SOURCE_LIST = ["SPY_1MIN", LOOKAHEAD_FEAT_STR, LOOKAHEAD_LABEL_STR]

    # FUNCTION: DECIDE FROM THE VIEW
    def decide(self, view_in):
        """
        Args:
            view_in (DecisionView): View at this moment

        Returns:
            float: Packed target weight
        """
        # THE SLICE'S LAST CLOSE IS THE DECISION BAR UNLESS THE RUNNER FILLED PAST IT
        close_arr = view_in.get_bar_array_dict()["close_arr"]
        close_float = float(close_arr[-1])
        feat_pdf = view_in.get(LOOKAHEAD_FEAT_STR)
        feat_float = float(feat_pdf["value"].iloc[-1]) if len(feat_pdf) else 0.0
        label_pdf = view_in.get_labels(LOOKAHEAD_LABEL_STR)
        label_float = float(label_pdf["value"].iloc[-1]) if len(label_pdf) else 0.0
        return get_packed_weight_float(close_float, feat_float, label_float)


# FUNCTION: A FRESH DESIGN OBJECT FOR ONE CANDIDATE
def get_candidate_design(candidate_in):
    """
    Args:
        candidate_in (str): Name in CANDIDATE_LIST

    Returns:
        ViewReadDesign: Fresh object
    """
    # UNKNOWN NAMES ARE A TEST ERROR
    if str(candidate_in) not in CANDIDATE_LIST:
        raise ValueError(f"unknown candidate {candidate_in!r}")
    return ViewReadDesign()
