import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp05_vol_scaled_exposure import config as exp_config
from experiments.exp05_vol_scaled_exposure.exposure import get_rule_candidate_list, get_weight_builder_func

"""
Holdout Design: exp05_vol_scaled_exposure_v2

Re-run of protocol 1.0 under the current rules, not new evidence. The weight is min(1, max(floor, target volatility /
current volatility)), with the target fixed for each quarter and a 20-point dead band. No model is trained. A
candidate's period score is the slice of one continuous path.
"""

# THE 4 RULES, IN THE PROTOCOL ORDER
_RULE_LIST = get_rule_candidate_list()

# FUNCTION: THE CANDIDATE NAME
def get_candidate_name_str(candidate_dict_in):
    """
    Names one rule. The floor and the quantile are printed with two decimals.

    Args:
        candidate_dict_in (dict): One element of get_rule_candidate_list

    Returns:
        str: Name
    """
    # RETURN THE NAME
    return f"{float(candidate_dict_in['floor']):.2f}|{float(candidate_dict_in['target_quantile']):.2f}"

# FUNCTION: PARSE A CANDIDATE NAME
def parse_candidate_dict(candidate_str_in):
    """
    Recovers the rule dictionary from its name.

    Args:
        candidate_str_in (str): Name

    Returns:
        dict: The rule
    """
    # MATCH THE NAME
    for candidate_dict in _RULE_LIST:
        if get_candidate_name_str(candidate_dict) == str(candidate_str_in):
            return candidate_dict
    raise ValueError(f"unknown candidate '{candidate_str_in}'.")

# DEFINE HOW CANDIDATE PERIODS ARE FORMED
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
# DEFINE THE 4 CANDIDATES
CANDIDATE_LIST = [get_candidate_name_str(candidate_dict) for candidate_dict in _RULE_LIST]
# DEFINE THE SELECTION RULE (MEAN OF THE LAST 4 QUARTERS; TIES: HIGHER FLOOR, THEN HIGHER QUANTILE)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT,
                  "tie_break": [("floor", False), ("target_quantile", False)]}
# DEFINE THE TIE COLUMNS THE RUNNER ATTACHES
CANDIDATE_TIE_VALUE_DICT = {
    "floor": {get_candidate_name_str(candidate_dict): float(candidate_dict["floor"]) for candidate_dict in _RULE_LIST},
    "target_quantile": {get_candidate_name_str(candidate_dict): float(candidate_dict["target_quantile"]) for candidate_dict in _RULE_LIST},
}
# COPY THE NAME AND THE PROTOCOL VERSION
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
# EVERY INPUT IS READ THROUGH THE POINT-IN-TIME CONTEXT (SPY BARS ONLY)
DATA_SOURCE_LIST = ["SPY_1MIN"]
# CACHES LIVE FOR ONE REPLAY
_cache_dict = {}

# FUNCTION: A CHEAP KEY FOR ONE BAR ARRAY
def get_bar_key_tuple(ohlcv_array_dict_in):
    """
    Identifies a bar array so a later call on the same bars reuses the path.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        tuple: Length, first close, last close, close sum
    """
    # THE CLOSE SUM MOVES WHEN A LATER BAR IS PERTURBED
    close_arr = np.asarray(ohlcv_array_dict_in["close_arr"], dtype=float)
    return (int(len(close_arr)), round(float(close_arr[0]), 8), round(float(close_arr[-1]), 8), round(float(close_arr.sum()), 4))

# FUNCTION: THE DAILY TABLE, CACHED PER BAR ARRAY
def get_cached_daily_pdf(ohlcv_array_dict_in):
    """
    Builds the daily features once per bar array.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.DataFrame: Daily features
    """
    # REUSE THE TABLE WHEN THE BARS HAVE NOT CHANGED
    from so.features.daily_features import get_daily_feature_pdf
    cache_key = (get_bar_key_tuple(ohlcv_array_dict_in), "daily")
    if cache_key not in _cache_dict:
        _cache_dict[cache_key] = get_daily_feature_pdf(ohlcv_array_dict_in)
    return _cache_dict[cache_key]

# FUNCTION: READ SPY THROUGH THE CONTEXT
def read_context_inputs(ohlcv_array_dict_in, data_context_in):
    """
    Reads SPY_1MIN as of the last decision in this bar set.

    Args:
        ohlcv_array_dict_in (dict): Bars
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        None
    """
    # SPY THROUGH THE CONTEXT, AS OF THE LAST DECISION MOMENT
    if data_context_in is None or not data_context_in.has_source_bool("SPY_1MIN") or not len(ohlcv_array_dict_in["session_date_list"]):
        return
    from so.core.point_in_time import get_decision_ts
    from so.features.daily_features import get_session_decision_idx_dict
    decision_idx = int(get_session_decision_idx_dict(ohlcv_array_dict_in)["decision_idx_arr"][-1])
    decision_ts = get_decision_ts(ohlcv_array_dict_in["timestamp_index"][decision_idx])
    data_context_in.set_decision_ts(decision_ts)
    data_context_in.get("SPY_1MIN", decision_ts, columns_in=["timestamp", "close", "available_ts"])
    data_context_in.set_decision_ts(None)

# FUNCTION: REPLAY PERIODS ON THESE BARS
def get_bar_period_pdf(ohlcv_array_dict_in):
    """
    Development periods when the bars end before the window. The runner's periods when the bars reach it.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.DataFrame: Periods
    """
    # IMPORT THE SCHEDULE HERE
    from so.core.holdout import get_active_holdout_window_dict, get_date, get_holdout_period_pdf
    from so.core.development_span import get_development_period_pdf
    cache_key = (get_bar_key_tuple(ohlcv_array_dict_in), "periods")
    if cache_key in _cache_dict:
        return _cache_dict[cache_key]
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    window_dict = get_active_holdout_window_dict()
    window_start = get_date(window_dict["start"])
    if session_date_list[-1] >= window_start:
        period_rule = type("PeriodRule", (), {"PERIOD_RULE": PERIOD_RULE})
        period_pdf = get_holdout_period_pdf(period_rule, session_date_list, window_dict)
    else:
        anchor_list = session_date_list + [window_start]
        period_pdf, _fold_pdf = get_development_period_pdf(anchor_list, ohlcv_array_dict_in, exp_config.EMBARGO_TRADING_DAYS, exp_config.FIXED_TRAIN_WINDOW_YEARS)
    if period_pdf is None or len(period_pdf) == 0:
        raise ValueError("these bars have no replay period.")
    _cache_dict[cache_key] = period_pdf
    return period_pdf

# FUNCTION: THE WEIGHT BOUGHT AT THE OPEN OF A SPAN
def get_initial_weight_float(ohlcv_array_dict_in, date1_in, weight_arr_in):
    """
    The target decided at the session before the span. Missing history buys a full position.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in: Span start
        weight_arr_in (np.ndarray): Target weight per session

    Returns:
        float: Initial weight
    """
    # THE SESSION BEFORE THE SPAN
    first_idx = int(ohlcv_array_dict_in["date_session_idx_dict"][pd.Timestamp(date1_in).date()])
    if first_idx > 0 and np.isfinite(weight_arr_in[first_idx - 1]):
        return float(weight_arr_in[first_idx - 1])
    return 1.0

# FUNCTION: SIMULATE ONE WEIGHT ARRAY OVER A SPAN
def simulate_weight_span_dict(ohlcv_array_dict_in, date1_in, date2_in, weight_arr_in):
    """
    Fractional exposure with the protocol dead band. The initial weight is the previous session's target.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span
        weight_arr_in (np.ndarray): Target weight per session

    Returns:
        dict: Simulator output
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.fractional_exposure import simulate_fractional_exposure_dict
    initial_weight = get_initial_weight_float(ohlcv_array_dict_in, date1_in, weight_arr_in)
    return simulate_fractional_exposure_dict(ohlcv_array_dict_in, date1_in, date2_in, weight_arr_in, exp_config.DEAD_BAND, initial_weight)

# FUNCTION: A DAILY EQUITY WHOSE TOTAL RETURN EQUALS A CONTINUOUS SLICE
def get_rebased_slice_pdf(daily_equity_pdf_in, date1_in, date2_in, period_return_float_in):
    """
    Keeps the slice's weights and sets the equity so the runner's last/initial formula equals the slice return.

    Args:
        daily_equity_pdf_in (pd.DataFrame): Continuous daily equity
        date1_in, date2_in: Period bounds
        period_return_float_in (float): Continuous period return

    Returns:
        pd.DataFrame: Daily equity of the period
    """
    # KEEP THE SLICE AND SET THE LAST EQUITY TO THE CONTINUOUS PERIOD RETURN
    start_date, end_date = pd.Timestamp(date1_in).date(), pd.Timestamp(date2_in).date()
    equity_pdf = daily_equity_pdf_in.copy()
    equity_pdf["date"] = [pd.Timestamp(day).date() for day in equity_pdf["date"]]
    slice_pdf = equity_pdf[(equity_pdf["date"] >= start_date) & (equity_pdf["date"] <= end_date)].copy().reset_index(drop=True)
    slice_pdf["equity"] = float(config.INITIAL_CAPITAL)
    slice_pdf.loc[slice_pdf.index[-1], "equity"] = float(config.INITIAL_CAPITAL) * (1.0 + float(period_return_float_in))
    return slice_pdf

# FUNCTION: ONE CONTINUOUS PATH OF ONE CANDIDATE, CACHED
def get_continuous_candidate_dict(ohlcv_array_dict_in, candidate_str_in):
    """
    Replays one candidate from the first period through the last.

    Args:
        ohlcv_array_dict_in (dict): Bars
        candidate_str_in (str): Candidate name

    Returns:
        dict: simulation, period_pdf, period_return_pdf, weight_arr
    """
    # REUSE THE PATH
    from so.core.continuous_replay import get_period_return_pdf
    cache_key = (get_bar_key_tuple(ohlcv_array_dict_in), "path", str(candidate_str_in))
    if cache_key in _cache_dict:
        return _cache_dict[cache_key]
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    period_pdf = get_bar_period_pdf(ohlcv_array_dict_in)
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    weight_arr = get_weight_builder_func(daily_pdf, period_pdf)(parse_candidate_dict(candidate_str_in))
    simulation_dict = simulate_weight_span_dict(ohlcv_array_dict_in, date1, date2, weight_arr)
    result_dict = {"simulation_dict": simulation_dict, "period_pdf": period_pdf, "weight_arr": weight_arr,
                   "period_return_pdf": get_period_return_pdf(simulation_dict["daily_equity_pdf"], period_pdf)}
    _cache_dict[cache_key] = result_dict
    return result_dict

# FUNCTION: REPLAY ONE CANDIDATE OVER ONE PERIOD
def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
    """
    The period return of one continuous path when the dates are a replay period. Any other span is simulated on its own.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Period bounds
        candidate_in (str): Candidate name
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, metric_dict
    """
    # READ SPY
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    start_date, end_date = pd.Timestamp(date1_in).date(), pd.Timestamp(date2_in).date()
    try:
        continuous_dict = get_continuous_candidate_dict(ohlcv_array_dict_in, str(candidate_in))
    except ValueError:
        continuous_dict = None
    if continuous_dict is not None:
        period_pdf = continuous_dict["period_pdf"]
        match_pdf = period_pdf[(period_pdf["period_start"].map(lambda value: pd.Timestamp(value).date()) == start_date)
                               & (period_pdf["period_end"].map(lambda value: pd.Timestamp(value).date()) == end_date)]
        if len(match_pdf) == 1:
            period_id = int(match_pdf["period_id"].iloc[0])
            period_return = float(continuous_dict["period_return_pdf"].loc[continuous_dict["period_return_pdf"]["period_id"] == period_id, "total_return"].iloc[0])
            slice_pdf = get_rebased_slice_pdf(continuous_dict["simulation_dict"]["daily_equity_pdf"], start_date, end_date, period_return)
            return {"daily_equity_pdf": slice_pdf, "trade_pdf": continuous_dict["simulation_dict"]["trade_pdf"],
                    "metric_dict": {"total_return": period_return}}
    # A SPAN THAT IS NOT A REPLAY PERIOD IS SIMULATED ON ITS OWN
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    one_period_pdf = pd.DataFrame({"period_id": [0], "period_start": [start_date], "period_end": [end_date]})
    weight_arr = get_weight_builder_func(daily_pdf, one_period_pdf)(parse_candidate_dict(candidate_in))
    return simulate_weight_span_dict(ohlcv_array_dict_in, start_date, end_date, weight_arr)

# FUNCTION: THE CANDIDATE IN FORCE ON ONE SESSION
def get_session_candidate_str(session_date_in, period_pdf_in, selection_pdf_in):
    """
    The governing candidate of the period that contains the session.

    Args:
        session_date_in (datetime.date): Session
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force

    Returns:
        str | None: Candidate
    """
    # THE PERIOD THAT COVERS THE SESSION
    session_day = pd.Timestamp(session_date_in).date()
    cover_pdf = period_pdf_in[(period_pdf_in["period_start"].map(lambda value: pd.Timestamp(value).date()) <= session_day)
                              & (period_pdf_in["period_end"].map(lambda value: pd.Timestamp(value).date()) >= session_day)]
    if cover_pdf.empty:
        return None
    period_id = int(cover_pdf["period_id"].iloc[-1])
    return selection_pdf_in.loc[selection_pdf_in["period_id"] == period_id, "candidate"].iloc[0]

# FUNCTION: REPLAY THE CONTINUOUS PRIOR-ONLY PATH
def run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
    """
    One path. Each session uses the floor and the quantile in force. The position carries across periods.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force per period
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, target_weight_arr, signal_arr, decision_session_list, target_decision_arr
    """
    # READ SPY AND BUILD THE SWITCHING WEIGHTS
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    date1, date2 = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    weight_cache_dict = {}
    weight_arr = np.full(len(daily_pdf), np.nan)
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        candidate_str = get_session_candidate_str(session_date, period_pdf_in, selection_pdf_in)
        if candidate_str is None:
            continue
        if candidate_str not in weight_cache_dict:
            weight_cache_dict[candidate_str] = get_weight_builder_func(daily_pdf, period_pdf_in)(parse_candidate_dict(candidate_str))
        weight_arr[session_idx] = float(weight_cache_dict[candidate_str][session_idx])
    # THE SESSION BEFORE THE SPAN USES THE FIRST PERIOD'S TARGET, AS PROTOCOL 1.0 DID
    first_idx = int(ohlcv_array_dict_in["date_session_idx_dict"][pd.Timestamp(date1).date()])
    if first_idx > 0 and np.isfinite(weight_arr[first_idx]):
        weight_arr[first_idx - 1] = weight_arr[first_idx]
    simulation_dict = simulate_weight_span_dict(ohlcv_array_dict_in, date1, date2, weight_arr)
    # THE ARRAYS THE LOOK-AHEAD CHECK COMPARES, ON THE PATH SESSIONS ONLY
    start_date, end_date = pd.Timestamp(date1).date(), pd.Timestamp(date2).date()
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    path_idx_list = [idx for idx, session_date in enumerate(session_date_list) if start_date <= session_date <= end_date]
    executed_arr = simulation_dict["daily_equity_pdf"]["weight"].to_numpy(dtype=float)
    if len(executed_arr) != len(path_idx_list):
        raise ValueError("the path equity and the path sessions have different lengths.")
    simulation_dict["target_weight_arr"] = executed_arr
    simulation_dict["signal_arr"] = weight_arr[path_idx_list]
    simulation_dict["target_decision_arr"] = weight_arr
    simulation_dict["decision_session_list"] = [session_date_list[idx] for idx in path_idx_list]
    return simulation_dict

# FUNCTION: MATCHED BASELINES NEED THE PATH
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in):
    """
    The constant exposure and the random shifts are matched to the prior-only path in the development report.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span

    Returns:
        dict: Empty
    """
    # THE RUNNER'S HOOK HAS NO PATH
    return {}

# FUNCTION: LOAD DECLARED SOURCES FOR A DEVELOPMENT REPLAY
def get_development_data_context(session_date_list_in):
    """
    Loads DATA_SOURCE_LIST through the development end and returns a development DataContext.

    Args:
        session_date_list_in (list): Session dates that include the window start

    Returns:
        DataContext: Development context
    """
    # THE DEVELOPMENT END IS BEFORE THE WINDOW
    from so.core.holdout import get_development_end_date
    from so.core.point_in_time import DataContext, load_source_frame_dict
    end_date = get_development_end_date(int(PERIOD_RULE["embargo_sessions"]), session_date_list_in)
    frame_dict = load_source_frame_dict(list(DATA_SOURCE_LIST), end_date)
    return DataContext("development", frame_dict_in=frame_dict, declared_name_list_in=list(DATA_SOURCE_LIST))
