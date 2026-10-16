import numpy as np
import pandas as pd
# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config
from experiments.exp07_warning_lights_exit import config as exp_config
from experiments.exp07_warning_lights_exit.rules import get_rule_builder_func, get_rule_candidate_list

"""
Holdout Design: exp07_warning_lights_exit_v2

Re-run of protocol 1.0 under the current rules, not new evidence. Sell when at least k of five fixed warning lights
are on. Buy back when fewer than k - 1 are on. No model is trained. A candidate's period score is the slice of one
continuous path, which is how protocol 1.0 scored a quarter.
"""

# THE 3 RULES, IN THE PROTOCOL ORDER
_RULE_LIST = get_rule_candidate_list()

# FUNCTION: THE CANDIDATE NAME
def get_candidate_name_str(candidate_dict_in):
    """
    Names one rule by its light count k.

    Args:
        candidate_dict_in (dict): One element of get_rule_candidate_list

    Returns:
        str: Name
    """
    # RETURN THE NAME
    return f"k{int(candidate_dict_in['light_k'])}"

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
# DEFINE THE 3 CANDIDATES
CANDIDATE_LIST = [get_candidate_name_str(candidate_dict) for candidate_dict in _RULE_LIST]
# DEFINE THE SELECTION RULE (MEAN OF THE LAST 4 QUARTERS; TIES: LARGER k)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT, "tie_break": [("light_k", False)]}
# DEFINE THE TIE COLUMNS THE RUNNER ATTACHES
CANDIDATE_TIE_VALUE_DICT = {
    "light_k": {get_candidate_name_str(candidate_dict): int(candidate_dict["light_k"]) for candidate_dict in _RULE_LIST},
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

# FUNCTION: DEVELOPMENT PERIODS ON THESE BARS
def get_bar_period_pdf(ohlcv_array_dict_in):
    """
    The replay periods of these bars. Bars that end before the holdout start use the development schedule. The window
    start is appended as a date only, so its prices are not read. Bars that reach the window use the runner's period
    builder, so a holdout replay slices the same continuous path.

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
        # THE RUNNER'S BARS REACH THE WINDOW. USE THE SAME PERIOD BUILDER THE RUNNER USES.
        period_rule = type("PeriodRule", (), {"PERIOD_RULE": PERIOD_RULE})
        period_pdf = get_holdout_period_pdf(period_rule, session_date_list, window_dict)
    else:
        anchor_list = session_date_list + [window_start]
        period_pdf, _fold_pdf = get_development_period_pdf(anchor_list, ohlcv_array_dict_in, exp_config.EMBARGO_TRADING_DAYS, exp_config.FIXED_TRAIN_WINDOW_YEARS)
    if period_pdf is None or len(period_pdf) == 0:
        raise ValueError("these bars have no replay period.")
    _cache_dict[cache_key] = period_pdf
    return period_pdf

# FUNCTION: ROUND-TRIP ROWS AS THE TRADE TABLE THE RUNNER COUNTS
def get_trade_pdf(transaction_pdf_in):
    """
    One buy row and one sell row per round trip.

    Args:
        transaction_pdf_in (pd.DataFrame): Simulator transactions

    Returns:
        pd.DataFrame: trade_ts, delta_share_count, reason
    """
    # AN EMPTY PATH HAS NO TRADES
    if transaction_pdf_in is None or len(transaction_pdf_in) == 0:
        return pd.DataFrame(columns=["trade_ts", "delta_share_count", "reason"])
    row_dict_list = []
    for _, row in transaction_pdf_in.iterrows():
        row_dict_list.append({"trade_ts": row["buy_ts"], "delta_share_count": float(row["share_count"]), "reason": row["entry_reason"]})
        row_dict_list.append({"trade_ts": row["sell_ts"], "delta_share_count": -float(row["share_count"]), "reason": row["exit_reason"]})
    return pd.DataFrame(row_dict_list)

# FUNCTION: ATTACH A 0/1 WEIGHT AND THE TRADES
def attach_path_columns(simulation_dict_in):
    """
    Weight is 1 while the session ends invested and 0 in cash.

    Args:
        simulation_dict_in (dict): Simulator output

    Returns:
        dict: The same dict, with weight and trade_pdf
    """
    # COPY THE EQUITY AND MARK THE POSITION
    equity_pdf = simulation_dict_in["daily_equity_pdf"].copy()
    equity_pdf["weight"] = equity_pdf["in_position"].astype(float)
    simulation_dict_in["daily_equity_pdf"] = equity_pdf
    simulation_dict_in["trade_pdf"] = get_trade_pdf(simulation_dict_in["transaction_pdf"])
    return simulation_dict_in

# FUNCTION: SIMULATE ONE FIXED RULE OVER A SPAN
def simulate_fixed_rule_dict(ohlcv_array_dict_in, daily_pdf_in, date1_in, date2_in, candidate_dict_in):
    """
    One rule, no stop, no forced buy-back.

    Args:
        ohlcv_array_dict_in (dict): Bars
        daily_pdf_in (pd.DataFrame): Daily features
        date1_in, date2_in: Span
        candidate_dict_in (dict): Rule

    Returns:
        dict: Simulator output
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.reentry_simulation import simulate_stop_reentry_dict
    exit_arr, reentry_func, reason_str = get_rule_builder_func(daily_pdf_in)(candidate_dict_in)
    return simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, np.full(len(daily_pdf_in), np.nan), None, reentry_func, reason_str,
                                      exit_signal_arr_in=exit_arr, max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)

# FUNCTION: ONE CONTINUOUS PATH OF ONE CANDIDATE, CACHED
def get_continuous_candidate_dict(ohlcv_array_dict_in, candidate_str_in):
    """
    Replays one candidate from the first development period through the last. Later period calls reuse it.

    Args:
        ohlcv_array_dict_in (dict): Bars through the development end
        candidate_str_in (str): Candidate name

    Returns:
        dict: simulation, period_pdf, period_return_pdf
    """
    # REUSE THE PATH
    cache_key = (get_bar_key_tuple(ohlcv_array_dict_in), "path", str(candidate_str_in))
    if cache_key in _cache_dict:
        return _cache_dict[cache_key]
    from so.core.continuous_replay import get_period_return_pdf
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    period_pdf = get_bar_period_pdf(ohlcv_array_dict_in)
    date1, date2 = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    simulation_dict = attach_path_columns(simulate_fixed_rule_dict(ohlcv_array_dict_in, daily_pdf, date1, date2, parse_candidate_dict(candidate_str_in)))
    period_return_pdf = get_period_return_pdf(simulation_dict["daily_equity_pdf"], period_pdf)
    result_dict = {"simulation_dict": simulation_dict, "period_pdf": period_pdf, "period_return_pdf": period_return_pdf}
    _cache_dict[cache_key] = result_dict
    return result_dict

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
    slice_pdf["weight"] = slice_pdf["in_position"].astype(float)
    return slice_pdf

# FUNCTION: REPLAY ONE CANDIDATE OVER ONE PERIOD
def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
    """
    The period return of one continuous path when the dates are a development period. Any other span is a fresh window.

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
    # A SPAN THAT IS NOT A DEVELOPMENT PERIOD (A TEST WINDOW) IS A FRESH SIMULATION
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    return attach_path_columns(simulate_fixed_rule_dict(ohlcv_array_dict_in, daily_pdf, date1_in, date2_in, parse_candidate_dict(candidate_in)))

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
    One path from the first period through the last. Each session uses the light count k in force.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force per period
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, target_weight_arr, signal_arr, decision_session_list
    """
    # READ SPY AND BUILD THE SWITCHING SIGNALS
    from so.core.reentry_simulation import simulate_stop_reentry_dict
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    date1, date2 = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    session_count = len(daily_pdf)
    exit_arr = np.zeros(session_count, dtype=bool)
    reentry_arr = np.zeros(session_count, dtype=bool)
    signal_arr = np.full(session_count, np.nan)
    # ONE SIGNAL PAIR PER DISTINCT RULE, THEN THE GOVERNING RULE ON EACH SESSION
    builder_func = get_rule_builder_func(daily_pdf)
    signal_cache_dict = {}
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        candidate_str = get_session_candidate_str(session_date, period_pdf_in, selection_pdf_in)
        if candidate_str is None:
            continue
        if candidate_str not in signal_cache_dict:
            exit_signal_arr, reentry_func, _reason_str = builder_func(parse_candidate_dict(candidate_str))
            signal_cache_dict[candidate_str] = (exit_signal_arr, reentry_func)
        exit_bool = bool(signal_cache_dict[candidate_str][0][session_idx])
        exit_arr[session_idx] = exit_bool
        reentry_arr[session_idx] = bool(signal_cache_dict[candidate_str][1](session_idx, 0, {}))
        signal_arr[session_idx] = 1.0 if exit_bool else 0.0
    reentry_func = lambda session_idx, cash_session_count, episode_dict: bool(reentry_arr[session_idx])
    simulation_dict = attach_path_columns(simulate_stop_reentry_dict(ohlcv_array_dict_in, date1, date2, np.full(session_count, np.nan), None,
                                                                    reentry_func, "rule", exit_signal_arr_in=exit_arr, max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS))
    # THE ARRAYS THE LOOK-AHEAD CHECK COMPARES, ON THE PATH SESSIONS ONLY
    start_date, end_date = pd.Timestamp(date1).date(), pd.Timestamp(date2).date()
    session_date_list = [pd.Timestamp(session_date).date() for session_date in ohlcv_array_dict_in["session_date_list"]]
    path_idx_list = [idx for idx, session_date in enumerate(session_date_list) if start_date <= session_date <= end_date]
    weight_arr = simulation_dict["daily_equity_pdf"]["weight"].to_numpy(dtype=float)
    if len(weight_arr) != len(path_idx_list):
        raise ValueError("the path equity and the path sessions have different lengths.")
    simulation_dict["target_weight_arr"] = weight_arr
    simulation_dict["signal_arr"] = signal_arr[path_idx_list]
    simulation_dict["exit_signal_arr"] = exit_arr
    simulation_dict["reentry_signal_arr"] = reentry_arr
    simulation_dict["decision_session_list"] = [session_date_list[idx] for idx in path_idx_list]
    return simulation_dict

# THE RETURNS THE DEVELOPMENT REPORT PASSES TO THE SUCCESS CRITERIA
BASELINE_COMPARISON_KEY_LIST = ["random_exit_median", "random_reentry_median"]

# FUNCTION: MATCHED RANDOM EXITS AND RANDOM RE-ENTRIES OVER A SPAN
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None, path_dict_in=None):
    """
    Twenty random exits keep the path's re-entry. Twenty random re-entries keep the path's exit signal. When the path
    never exits, every random run equals the path. Exit run i uses so.config.RANDOM_SEED + RANDOM_EXIT_SEED_OFFSET + i.
    Re-entry run i uses so.config.RANDOM_SEED + i. The same function is the development report.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span
        data_context_in (DataContext | None): Point-in-time context
        path_dict_in (dict | None): Prior-only path

    Returns:
        dict: Both random families and their lists
    """
    # IMPORT THE RANDOM RULES AND THE SPAN CUT HERE
    from so.core.reentry_simulation import simulate_stop_reentry_dict, get_random_reentry_func
    from experiments.exp03_ath_exit.rules import get_random_baseline_probability_dict, get_random_exit_signal_arr
    from so.core.baseline_report import get_random_family_stat_dict, get_span_path_dict
    # SPY THROUGH THE CONTEXT, THEN THE PATH ON THIS SPAN
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    path_dict = get_span_path_dict(path_dict_in, ohlcv_array_dict_in, date1_in, date2_in)
    probability_dict = get_random_baseline_probability_dict(path_dict)
    path_return = path_dict["metric_dict"]["total_return"]
    session_count = len(path_dict["exit_signal_arr"])
    never_bool = not np.isfinite(probability_dict["exit_probability"]) or not np.isfinite(probability_dict["buyback_probability"])
    exit_list, reentry_list = [], []
    if never_bool:
        exit_list = [path_return] * exp_config.RANDOM_RUN_COUNT
        reentry_list = [path_return] * exp_config.RANDOM_RUN_COUNT
    else:
        reentry_func = lambda session_idx, cash_session_count, episode_dict: bool(path_dict["reentry_signal_arr"][session_idx])
        for run_idx in range(exp_config.RANDOM_RUN_COUNT):
            exit_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, np.full(session_count, np.nan), None, reentry_func, "random",
                                                  exit_signal_arr_in=get_random_exit_signal_arr(session_count, probability_dict["exit_probability"], config.RANDOM_SEED + exp_config.RANDOM_EXIT_SEED_OFFSET + run_idx),
                                                  max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
            reentry_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, np.full(session_count, np.nan), None,
                                                     get_random_reentry_func(probability_dict["buyback_probability"], config.RANDOM_SEED + run_idx), "random",
                                                     exit_signal_arr_in=path_dict["exit_signal_arr"], max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
            exit_list.append(exit_dict["metric_dict"]["total_return"])
            reentry_list.append(reentry_dict["metric_dict"]["total_return"])
    return {**get_random_family_stat_dict("random_exit", exit_list, path_return),
            **get_random_family_stat_dict("random_reentry", reentry_list, path_return),
            "random_exit_list": exit_list, "random_reentry_list": reentry_list}

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
