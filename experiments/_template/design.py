# IMPORT THE EXPERIMENT CONFIGURATION
from experiments._template import config as exp_config
import numpy as np
import pandas as pd

"""
Holdout Design (template, fractional-exposure family)

The holdout result is the design's frozen prior-only path from its development start, continued without interruption
through the holdout window: same code, same decision bar (15:58) and fill (15:59), same costs, dead band and cash
rules, same candidate periods and selection rule, selection history and position carried over from development. Only
the holdout sessions are reported. Every decision uses only information available at its decision bar.

This template is a constant full exposure, so the interface is visible. A real design imports its own experiment code
and replaces the constants and the three functions. An exit-family design implements run_prior_only_path_dict by
calling so.core.replay_walk_forward.run_prior_only_replay_dict (rule switching, carried state) instead of the
fractional simulator.
"""

# DEFINE HOW CANDIDATE PERIODS ARE FORMED (DEVELOPMENT QUARTERS, EXTENDED THROUGH THE HOLDOUT BY THE RUNNER)
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
# DEFINE THE CANDIDATES AND THE SELECTION RULE (MEAN EXCESS RETURN OVER THE LAST N PERIODS, THEN THIS TIE ORDER)
CANDIDATE_LIST = ["constant"]
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("candidate", True)]}
# DEFINE THE DEAD BAND (0 HERE; A DESIGN THAT USES 20 POINTS KEEPS 0.20 AND THE RUNNER DOES NOT CHANGE IT)
DEAD_BAND = 0.0
# DEFINE THE TARGET WEIGHT OF EACH CANDIDATE
WEIGHT_DICT = {"constant": 1.0}
# COPY THE NAME AND THE PROTOCOL VERSION (THE TRIAL LOG AND THE DESIGN HASH READ THEM)
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION

# FUNCTION: BUILD THE TARGET WEIGHT OF EVERY SESSION
def get_target_weight_arr(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in):
    """
    The candidate in force in each period, written on that period's sessions. Other sessions stay NaN (keep).

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods (period_id, period_start, period_end)
        selection_pdf_in (pd.DataFrame): Candidate in force (period_id, candidate)

    Returns:
        np.ndarray: Target weight per session position
    """
    # START FROM "KEEP" AND FILL EACH PERIOD WITH ITS CANDIDATE
    target_arr = np.full(len(ohlcv_array_dict_in["session_date_list"]), np.nan)
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    for period_row in period_pdf_in.itertuples(index=False):
        candidate = selection_pdf_in.loc[selection_pdf_in["period_id"] == period_row.period_id, "candidate"].iloc[0]
        weight_float = float(WEIGHT_DICT[candidate])
        for session_idx, session_date in enumerate(session_date_list):
            if pd.Timestamp(period_row.period_start).date() <= session_date <= pd.Timestamp(period_row.period_end).date():
                target_arr[session_idx] = weight_float
    return target_arr

# FUNCTION: REPLAY ONE CANDIDATE OVER ONE PERIOD
def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in):
    """
    The same replay the experiment uses in development, for one candidate and one period. This template holds a
    constant weight. The returned daily equity starts at the initial capital (a fresh window).

    An ML design refits inside this function, and inside run_prior_only_path_dict, using only bars before the decision
    bar. Example: on each session, fit on the trailing 6 months of sessions strictly before that session (daily, so
    every_sessions = 1), never on the decision bar and never on a later bar. The fit sees the prior close and earlier
    bars; the decision at 15:58 is filled at 15:59 of the same session.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Period bounds
        candidate_in (str): Candidate name

    Returns:
        dict: daily_equity_pdf, trade_pdf, metric_dict (the fractional-exposure replay)
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.fractional_exposure import simulate_fractional_exposure_dict
    # HOLD THE CANDIDATE'S WEIGHT ON EVERY SESSION AND REPLAY THE PERIOD
    target_arr = np.full(len(ohlcv_array_dict_in["session_date_list"]), float(WEIGHT_DICT[candidate_in]))
    return simulate_fractional_exposure_dict(ohlcv_array_dict_in, date1_in, date2_in, target_arr, DEAD_BAND, float(WEIGHT_DICT[candidate_in]))

# FUNCTION: REPLAY THE CONTINUOUS PRIOR-ONLY PATH
def run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in):
    """
    One fractional-exposure replay from the first period through the last, with the candidate in force switching as
    selection_pdf_in says. The position and the cash carry across the holdout start. An exit-family design calls
    so.core.replay_walk_forward.run_prior_only_replay_dict here instead.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force per period

    Returns:
        dict: daily_equity_pdf, trade_pdf, target_weight_arr, decision_session_list
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.fractional_exposure import simulate_fractional_exposure_dict
    # BUILD THE TARGETS AND REPLAY ONCE SO THE POSITION CARRIES ACROSS PERIODS
    target_arr = get_target_weight_arr(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in)
    date1 = period_pdf_in["period_start"].iloc[0]
    date2 = period_pdf_in["period_end"].iloc[-1]
    finite_idx_arr = np.flatnonzero(np.isfinite(target_arr))
    initial_weight_float = float(target_arr[finite_idx_arr[0]])
    simulation_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, date1, date2, target_arr, DEAD_BAND, initial_weight_float)
    # ATTACH THE TARGETS THE TRUNCATION TEST COMPARES (ONE PER SESSION OF THE PATH)
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    path_idx_list = [idx for idx, session_date in enumerate(session_date_list) if pd.Timestamp(date1).date() <= session_date <= pd.Timestamp(date2).date()]
    simulation_dict["target_weight_arr"] = target_arr[path_idx_list]
    simulation_dict["decision_session_list"] = [session_date_list[idx] for idx in path_idx_list]
    return simulation_dict

# FUNCTION: GET THE UNINFORMED BASELINES OVER A SPAN
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in):
    """
    Constant exposure at the mean candidate weight, over the span the caller names. The runner names the holdout only.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span (the holdout start and end when the runner calls this)

    Returns:
        dict: baseline name -> total return
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.fractional_exposure import simulate_fractional_exposure_dict
    # HOLD THE MEAN WEIGHT FOR THE WHOLE SPAN
    weight_float = float(np.mean(list(WEIGHT_DICT.values())))
    target_arr = np.full(len(ohlcv_array_dict_in["session_date_list"]), weight_float)
    simulation_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, date1_in, date2_in, target_arr, 0.0, weight_float)
    return {"constant_exposure": simulation_dict["metric_dict"]["total_return"]}
