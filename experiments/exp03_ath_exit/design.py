import numpy as np
import pandas as pd
# IMPORT THE EXPERIMENT CONFIGURATION AND THE RULES
from experiments.exp03_ath_exit import config as exp_config
from experiments.exp03_ath_exit.rules import get_rule_candidate_list, simulate_rule_dict

"""
Holdout Design: exp03_ath_exit_v2

Re-run of protocol 1.0 under the current rules, not new evidence. Sell when the 15:58 close is within a threshold of
the all-time high. Buy back after a fixed number of cash decisions, or after a dip from the sale. No model is trained.
The candidate in force for a quarter is the pooled choice of the previous quarters.
"""

# THE 15 RULES, IN THE PROTOCOL ORDER
_RULE_LIST = get_rule_candidate_list()

# FUNCTION: THE CANDIDATE NAME
def get_candidate_name_str(candidate_dict_in):
    """
    Names one rule. The threshold is printed with three decimals so 0.5%, 1% and 2% stay distinct.

    Args:
        candidate_dict_in (dict): One element of get_rule_candidate_list

    Returns:
        str: Name
    """
    # RETURN THE NAME
    return f"{float(candidate_dict_in['ath_within']):.3f}|{candidate_dict_in['rule']}"

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

# DEFINE HOW CANDIDATE PERIODS ARE FORMED (THE SCHEDULE MATCHES exp02; NO MODEL IS TRAINED)
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FIXED_TRAIN_WINDOW_YEARS]}
# DEFINE THE 15 CANDIDATES
CANDIDATE_LIST = [get_candidate_name_str(candidate_dict) for candidate_dict in _RULE_LIST]
# DEFINE THE SELECTION RULE (MEAN OF THE LAST 4 QUARTERS; TIES: TIGHTER THRESHOLD, THEN RULE ORDER)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT,
                  "tie_break": [("ath_within", True), ("rule_order", True)]}
# DEFINE THE TIE COLUMNS THE RUNNER ATTACHES
CANDIDATE_TIE_VALUE_DICT = {
    "ath_within": {get_candidate_name_str(candidate_dict): float(candidate_dict["ath_within"]) for candidate_dict in _RULE_LIST},
    "rule_order": {get_candidate_name_str(candidate_dict): int(candidate_dict["rule_order"]) for candidate_dict in _RULE_LIST},
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
    Identifies a bar array so a later call on the same bars reuses the daily table.

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

# FUNCTION: ATTACH A 0/1 WEIGHT AND THE TRADES TO A SIMULATION
def attach_path_columns(simulation_dict_in):
    """
    Weight is 1 while the session ends invested and 0 in cash. The simulator's equity is unchanged.

    Args:
        simulation_dict_in (dict): Output of simulate_rule_dict

    Returns:
        dict: The same dict, with weight and trade_pdf
    """
    # COPY THE EQUITY AND MARK THE POSITION
    equity_pdf = simulation_dict_in["daily_equity_pdf"].copy()
    equity_pdf["weight"] = equity_pdf["in_position"].astype(float)
    simulation_dict_in["daily_equity_pdf"] = equity_pdf
    simulation_dict_in["trade_pdf"] = get_trade_pdf(simulation_dict_in["transaction_pdf"])
    return simulation_dict_in

# FUNCTION: REPLAY ONE CANDIDATE OVER ONE PERIOD
def run_candidate_replay_dict(ohlcv_array_dict_in, date1_in, date2_in, candidate_in, data_context_in=None):
    """
    One fresh window, as protocol 1.0 scored a validation quarter: start invested, one rule, state not carried in.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Period bounds
        candidate_in (str): Candidate name
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, metric_dict
    """
    # READ SPY, THEN SIMULATE THE RULE ON A FRESH WINDOW
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    simulation_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf, date1_in, date2_in, parse_candidate_dict(candidate_in))
    return attach_path_columns(simulation_dict)

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

# FUNCTION: A BUY-BACK THAT FOLLOWS THE RULE IN FORCE ON THAT SESSION
def get_switching_reentry_func(decision_close_arr_in, type_arr_in, value_arr_in):
    """
    Delay rules buy back after that many cash decisions. Dip rules buy back when the close is that far under the sale.

    Args:
        decision_close_arr_in (np.ndarray): 15:58 close per session
        type_arr_in (np.ndarray): "delay", "dip", or "" per session
        value_arr_in (np.ndarray): Delay count or dip fraction per session

    Returns:
        function: Re-entry rule
    """
    # THE RULE OF THE SESSION, OR NO BUY-BACK WHEN THE SESSION HAS NO CANDIDATE
    def reentry_func(session_idx, cash_session_count, episode_dict):
        kind_str = type_arr_in[session_idx]
        if kind_str == "delay":
            return int(cash_session_count) >= int(value_arr_in[session_idx])
        if kind_str == "dip":
            return bool(decision_close_arr_in[session_idx] <= episode_dict["exit_fill_price"] * (1.0 - float(value_arr_in[session_idx])))
        return False
    return reentry_func

# FUNCTION: REPLAY THE CONTINUOUS PRIOR-ONLY PATH
def run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
    """
    One path from the first period through the last. Each session uses the exit threshold and the buy-back of the
    candidate in force. The position carries across periods.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force per period
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, target_weight_arr, signal_arr, decision_session_list
    """
    # READ SPY AND THE DAILY TABLE
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    date1, date2 = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    ath_arr = daily_pdf["ath_drawdown_pct"].to_numpy(dtype=float)
    close_arr = daily_pdf["decision_close"].to_numpy(dtype=float)
    exit_arr = np.zeros(session_count, dtype=bool)
    type_arr = np.array([""] * session_count, dtype=object)
    value_arr = np.full(session_count, np.nan)
    signal_arr = np.full(session_count, np.nan)
    # WRITE THE GOVERNING RULE ON EACH SESSION
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        candidate_str = get_session_candidate_str(session_date, period_pdf_in, selection_pdf_in)
        if candidate_str is None:
            continue
        candidate_dict = parse_candidate_dict(candidate_str)
        exit_bool = bool(ath_arr[session_idx] >= -float(candidate_dict["ath_within"]))
        exit_arr[session_idx] = exit_bool
        type_arr[session_idx] = candidate_dict["buyback_type"]
        value_arr[session_idx] = float(candidate_dict["buyback_value"])
        signal_arr[session_idx] = 1.0 if exit_bool else 0.0
    # REPLAY ONCE SO THE POSITION CARRIES
    reentry_func = get_switching_reentry_func(close_arr, type_arr, value_arr)
    simulation_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf, date1, date2, _RULE_LIST[0],
                                         exit_signal_arr_in=exit_arr, reentry_func_tuple_in=(reentry_func, "rule"))
    simulation_dict = attach_path_columns(simulation_dict)
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
    simulation_dict["buyback_type_arr"] = type_arr
    simulation_dict["buyback_value_arr"] = value_arr
    simulation_dict["decision_session_list"] = [session_date_list[idx] for idx in path_idx_list]
    return simulation_dict

# THE RETURNS THE DEVELOPMENT REPORT PASSES TO THE SUCCESS CRITERIA (THE TREND RULE IS REPORTED, NOT COMPARED)
BASELINE_COMPARISON_KEY_LIST = ["random_buyback_median", "random_exit_median"]

# FUNCTION: MATCHED RANDOM FAMILIES AND THE TREND RULE OVER A SPAN
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in, data_context_in=None, path_dict_in=None):
    """
    Twenty random buy-backs keep the path's exit signal. Twenty random exits keep the path's buy-back. The trend rule
    does not use the path. When the path never exits, every random run equals the path. Run i uses
    so.config.RANDOM_SEED + i for buy-backs and so.config.RANDOM_SEED + 1000 + i for exits. The same function is the
    development report.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span
        data_context_in (DataContext | None): Point-in-time context
        path_dict_in (dict | None): Prior-only path

    Returns:
        dict: Both random families, their lists, and the trend rule
    """
    # IMPORT THE RANDOM RULES AND THE SPAN CUT HERE
    from so import config
    from so.core.reentry_simulation import get_random_reentry_func, simulate_trend_rule_dict
    from experiments.exp03_ath_exit.rules import get_random_baseline_probability_dict, get_random_exit_signal_arr
    from so.core.baseline_report import get_random_family_stat_dict, get_span_path_dict
    # SPY THROUGH THE CONTEXT, THEN THE PATH ON THIS SPAN
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    path_dict = get_span_path_dict(path_dict_in, ohlcv_array_dict_in, date1_in, date2_in)
    # MATCH THE PROBABILITIES TO THE PATH
    probability_dict = get_random_baseline_probability_dict(path_dict)
    daily_pdf = get_cached_daily_pdf(ohlcv_array_dict_in)
    buyback_list, exit_list = [], []
    never_bool = not np.isfinite(probability_dict["exit_probability"]) or not np.isfinite(probability_dict["buyback_probability"])
    path_return = path_dict["metric_dict"]["total_return"]
    if never_bool:
        buyback_list = [path_return] * exp_config.RANDOM_RUN_COUNT
        exit_list = [path_return] * exp_config.RANDOM_RUN_COUNT
    else:
        reentry_tuple = (get_switching_reentry_func(daily_pdf["decision_close"].to_numpy(dtype=float), path_dict["buyback_type_arr"], path_dict["buyback_value_arr"]), "random")
        for run_idx in range(exp_config.RANDOM_RUN_COUNT):
            buyback_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf, date1_in, date2_in, _RULE_LIST[0],
                                             exit_signal_arr_in=path_dict["exit_signal_arr"],
                                             reentry_func_tuple_in=(get_random_reentry_func(probability_dict["buyback_probability"], config.RANDOM_SEED + run_idx), "random"))
            exit_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf, date1_in, date2_in, _RULE_LIST[0],
                                          exit_signal_arr_in=get_random_exit_signal_arr(len(daily_pdf), probability_dict["exit_probability"], config.RANDOM_SEED + 1000 + run_idx),
                                          reentry_func_tuple_in=reentry_tuple)
            buyback_list.append(buyback_dict["metric_dict"]["total_return"])
            exit_list.append(exit_dict["metric_dict"]["total_return"])
    return_dict = {}
    return_dict.update(get_random_family_stat_dict("random_buyback", buyback_list, path_return))
    return_dict.update(get_random_family_stat_dict("random_exit", exit_list, path_return))
    return_dict["random_buyback_list"] = buyback_list
    return_dict["random_exit_list"] = exit_list
    trend_dict = simulate_trend_rule_dict(ohlcv_array_dict_in, daily_pdf, date1_in, date2_in, "ma200_dist_pct")
    return_dict["trend_ma200"] = trend_dict["metric_dict"]["total_return"]
    return return_dict

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
