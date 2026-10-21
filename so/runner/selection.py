import pandas as pd
# IMPORT THE SHARED CONFIGURATION (INITIAL CAPITAL)
from so import config
# IMPORT POOLED SELECTION AND THE PERIOD-SLICE RETURN
from so.core.evaluation import get_pooled_selection_pdf
from so.core.continuous_replay import get_period_return_pdf, get_prior_only_period_candidate_dict
from so.core.reentry_simulation import get_buy_and_hold_result_dict
# IMPORT THE ENGINE-ONLY REPLAY OF RECORDED DECISIONS
from so.runner.engine import FractionalWeightEngine, get_decision_dict
from so.runner.loop import run_engine_decisions_dict, get_design_mode_str, MODE_MINUTE_STR
from so.runner.periods import get_period_date

"""
Candidate Scores And Prior-Only Selection (infrastructure step 4b-1a)

Each candidate is one stream over the whole span. A candidate-period score is the return of that stream over the
period (equity at the period's last session / equity at the last session before the period - 1), minus buy-and-hold
sliced the same way from one buy-and-hold stream over the same span.

Pooled prior-only selection uses so.core.evaluation.get_pooled_selection_pdf with the design's SELECTION_RULE and
tie-break. The choice at period f governs period f+1. Period 0, which has no prior choice, takes CANDIDATE_LIST[0]
(the same first-candidate convention as so.core.holdout.get_governing_selection_pdf).

The prior-only path is one engine pass over the governing candidate's recorded decisions, carrying the position
across switches. decide() is not called again.
"""


# FUNCTION: THE SELECTION RULE FROM A DESIGN MODULE
def get_selection_rule_dict(design_module_in):
    """
    SELECTION_RULE.pooled_periods and SELECTION_RULE.tie_break.

    Args:
        design_module_in (module): Design

    Returns:
        dict: pooled_periods, tie_break
    """
    # BOTH KEYS ARE REQUIRED
    if not hasattr(design_module_in, "SELECTION_RULE"):
        raise ValueError("design module is missing SELECTION_RULE.")
    rule_dict = dict(design_module_in.SELECTION_RULE)
    if "pooled_periods" not in rule_dict or "tie_break" not in rule_dict:
        raise ValueError("SELECTION_RULE needs pooled_periods and tie_break.")
    return {"pooled_periods": int(rule_dict["pooled_periods"]), "tie_break": list(rule_dict["tie_break"])}


# FUNCTION: BUY-AND-HOLD PERIOD RETURNS OF ONE CONTINUOUS PATH
def get_buy_hold_period_return_dict(ohlcv_array_dict_in, period_pdf_in, date1_in, date2_in,
                                    initial_capital_in=config.INITIAL_CAPITAL):
    """
    One buy-and-hold stream over the span, then get_period_return_pdf. This is a slice of a continuous path, not a
    fresh window started at each period.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        date1_in, date2_in: Span bounds (inclusive)
        initial_capital_in (float): Starting capital

    Returns:
        dict: period_id -> total_return
    """
    # THE SAME BUY-AND-HOLD PATH THE 4A WEIGHT-1 LOOP REPRODUCES
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, date1_in, date2_in)
    period_return_pdf = get_period_return_pdf(buy_hold_dict["daily_equity_pdf"], period_pdf_in, initial_capital_in)
    return {int(row["period_id"]): float(row["total_return"]) for _, row in period_return_pdf.iterrows()}


# FUNCTION: SCORE ONE PERIOD OF A CANDIDATE STREAM
def get_stream_period_score_dict(daily_equity_pdf_in, period_row_in, buy_hold_return_in,
                                 initial_capital_in=config.INITIAL_CAPITAL):
    """
    Period return from the stream so far, plus buy-and-hold for the same period.

    Args:
        daily_equity_pdf_in (pd.DataFrame): Equity of the candidate stream through this period
        period_row_in (pd.Series | dict): One period
        buy_hold_return_in (float): Buy-and-hold return of that period
        initial_capital_in (float): Starting capital

    Returns:
        dict: period_id, total_return, buy_hold_total_return, excess_return
    """
    # SLICE WITH THE EXISTING PERIOD-RETURN CODE
    period_pdf = pd.DataFrame([dict(period_row_in)])
    return_pdf = get_period_return_pdf(daily_equity_pdf_in, period_pdf, initial_capital_in)
    if return_pdf.empty:
        raise ValueError("the candidate stream has no equity in this period.")
    total_return = float(return_pdf["total_return"].iloc[0])
    buy_hold_return = float(buy_hold_return_in)
    return {"period_id": int(return_pdf["period_id"].iloc[0]), "total_return": total_return,
            "buy_hold_total_return": buy_hold_return, "excess_return": total_return - buy_hold_return}


# FUNCTION: ATTACH TIE COLUMNS FROM THE DESIGN
def add_tie_value_pdf(score_pdf_in, design_module_in):
    """
    Copies CANDIDATE_TIE_VALUE_DICT columns onto the score table when they are missing.

    Args:
        score_pdf_in (pd.DataFrame): fold_id, candidate, excess_return
        design_module_in (module): Design

    Returns:
        pd.DataFrame: Copy with tie columns
    """
    # A DESIGN MAY NAME TIE COLUMNS THE SCORE TABLE DOES NOT CARRY
    score_pdf = score_pdf_in.copy()
    tie_value_dict = getattr(design_module_in, "CANDIDATE_TIE_VALUE_DICT", None) or {}
    for column_str, value_dict in tie_value_dict.items():
        if column_str not in score_pdf.columns:
            score_pdf[column_str] = score_pdf["candidate"].map(value_dict)
    return score_pdf


# FUNCTION: POOLED SELECTION ON CANDIDATE-PERIOD SCORES
def get_runner_selection_pdf(score_pdf_in, design_module_in):
    """
    One selected row per fold (period). Maximizes excess_return with SELECTION_RULE.

    Args:
        score_pdf_in (pd.DataFrame): fold_id, candidate, excess_return (and tie columns)
        design_module_in (module): Design (SELECTION_RULE, optional CANDIDATE_TIE_VALUE_DICT)

    Returns:
        pd.DataFrame: Output of get_pooled_selection_pdf
    """
    # THE EXISTING POOLED SELECTOR, WITH THE DESIGN'S TIE-BREAK
    rule_dict = get_selection_rule_dict(design_module_in)
    score_pdf = add_tie_value_pdf(score_pdf_in, design_module_in)
    return get_pooled_selection_pdf(score_pdf, ["candidate"], "excess_return", int(rule_dict["pooled_periods"]),
                                    list(rule_dict["tie_break"]))


# FUNCTION: THE CANDIDATE IN FORCE FOR EACH PERIOD
def get_governing_candidate_dict(selection_pdf_in, period_pdf_in, candidate_list_in):
    """
    The choice at period f governs period f+1. Period 0 takes candidate_list_in[0].

    Args:
        selection_pdf_in (pd.DataFrame): Output of get_runner_selection_pdf
        period_pdf_in (pd.DataFrame): Periods
        candidate_list_in (list): CANDIDATE_LIST

    Returns:
        dict: period_id -> candidate
    """
    # A SINGLE CANDIDATE GOVERNS EVERY PERIOD
    candidate_list = list(candidate_list_in)
    if len(candidate_list) == 0:
        raise ValueError("CANDIDATE_LIST is empty.")
    if len(candidate_list) == 1:
        return {int(period_id): candidate_list[0] for period_id in period_pdf_in["period_id"]}
    selection_pdf = selection_pdf_in.copy()
    selection_pdf["candidate_idx"] = selection_pdf["candidate"].map({name: idx for idx, name in enumerate(candidate_list)})
    governing_idx_dict = get_prior_only_period_candidate_dict(selection_pdf, period_pdf_in, "candidate_idx")
    governing_dict = {}
    for period_id in period_pdf_in.sort_values("period_id")["period_id"].astype(int):
        candidate_idx = int(governing_idx_dict[period_id]) if period_id in governing_idx_dict else 0
        governing_dict[int(period_id)] = candidate_list[candidate_idx]
    return governing_dict


# FUNCTION: SESSION -> GOVERNING CANDIDATE
def get_session_candidate_dict(session_date_list_in, period_pdf_in, governing_dict_in):
    """
    The candidate in force on each window session. Sessions outside every period are omitted.

    Args:
        session_date_list_in (list): Window session dates
        period_pdf_in (pd.DataFrame): Periods
        governing_dict_in (dict): period_id -> candidate

    Returns:
        dict: session date -> candidate
    """
    # THE LAST COVERING PERIOD WINS IF BOUNDS EVER TOUCH (THEY SHOULD NOT)
    session_candidate_dict = {}
    period_pdf = period_pdf_in.sort_values("period_id")
    for session_date in session_date_list_in:
        session_day = get_period_date(session_date)
        cover_pdf = period_pdf[(period_pdf["period_start"].map(get_period_date) <= session_day)
                               & (period_pdf["period_end"].map(get_period_date) >= session_day)]
        if cover_pdf.empty:
            continue
        period_id = int(cover_pdf["period_id"].iloc[-1])
        if period_id in governing_dict_in:
            session_candidate_dict[session_day] = governing_dict_in[period_id]
    return session_candidate_dict


# FUNCTION: THE PRIOR-ONLY PATH FROM RECORDED DECISIONS
def run_prior_only_from_decisions_dict(ohlcv_array_dict_in, date1_in, date2_in, session_date_list_in,
                                       candidate_decision_dict_in, governing_dict_in, period_pdf_in,
                                       dead_band_in=0.0, initial_weight_in=1.0,
                                       initial_capital_in=config.INITIAL_CAPITAL,
                                       entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                                       market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                                       engine_in=None, design_module_in=None):
    """
    One engine pass. Each session uses the governing candidate's recorded decision. The position is carried across
    switches. The last session sells at the close. Minute mode stitches every recorded minute of the candidate in
    force that session.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span bounds
        session_date_list_in (list): Window session dates (aligned with each candidate's decision list in daily mode)
        candidate_decision_dict_in (dict): candidate -> list of decision dicts
        governing_dict_in (dict): period_id -> candidate
        period_pdf_in (pd.DataFrame): Periods
        dead_band_in, initial_weight_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in (float): Engine
        engine_in (Engine | None): None uses a fresh FractionalWeightEngine
        design_module_in (module | None): Design (MODE); None is daily

    Returns:
        dict: Engine result plus governing_dict
    """
    # MINUTE DECISIONS ARE MANY PER SESSION; THE ENGINE REPLAY FILLS AT THE NEXT OPEN
    if design_module_in is not None and get_design_mode_str(design_module_in) == MODE_MINUTE_STR:
        from so.runner.minute import run_engine_minute_decisions_dict, SESSION_DATE_KEY_STR
        session_candidate_dict = get_session_candidate_dict(session_date_list_in, period_pdf_in, governing_dict_in)
        decision_dict_list = []
        for session_date in session_date_list_in:
            session_day = get_period_date(session_date)
            candidate = session_candidate_dict.get(session_day)
            if candidate is None:
                continue
            for recorded_dict in candidate_decision_dict_in.get(candidate, []):
                recorded_session = recorded_dict.get(SESSION_DATE_KEY_STR)
                if recorded_session is None:
                    continue
                if get_period_date(recorded_session) != session_day:
                    continue
                decision_dict_list.append(dict(recorded_dict))
        result_dict = run_engine_minute_decisions_dict(ohlcv_array_dict_in, date1_in, date2_in, decision_dict_list,
                                                       engine_in, initial_weight_in, initial_capital_in,
                                                       entry_slippage_in, market_exit_slippage_in)
        result_dict["governing_dict"] = dict(governing_dict_in)
        return result_dict
    # ONE DECISION PER SESSION FROM THE CANDIDATE IN FORCE THAT DAY
    session_candidate_dict = get_session_candidate_dict(session_date_list_in, period_pdf_in, governing_dict_in)
    first_candidate = next(iter(candidate_decision_dict_in.values()))
    if len(first_candidate) != len(session_date_list_in):
        raise ValueError("each candidate's recorded decisions must cover every window session.")
    decision_dict_list = []
    for session_idx, session_date in enumerate(session_date_list_in):
        session_day = get_period_date(session_date)
        candidate = session_candidate_dict.get(session_day)
        if candidate is None:
            decision_dict_list.append(get_decision_dict(None))
            continue
        decision_dict_list.append(get_decision_dict(candidate_decision_dict_in[candidate][session_idx]))
    engine = engine_in if engine_in is not None else FractionalWeightEngine(dead_band_in, initial_capital_in, entry_slippage_in, market_exit_slippage_in)
    result_dict = run_engine_decisions_dict(ohlcv_array_dict_in, date1_in, date2_in, decision_dict_list, engine,
                                            initial_weight_in, dead_band_in, initial_capital_in, entry_slippage_in,
                                            market_exit_slippage_in)
    result_dict["governing_dict"] = dict(governing_dict_in)
    return result_dict
