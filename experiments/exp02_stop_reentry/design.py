# IMPORT THE SHARED CONFIGURATION AND THE EXPERIMENT CONFIGURATION
from so import config as so_config
from experiments.exp02_stop_reentry import config as exp_config
from experiments.exp02_stop_reentry.model import (fit_reentry_model_dict, predict_reentry_proba_arr, get_candidate_name_str,
                                                  parse_candidate_dict, get_session_threshold_reentry_func)
import numpy as np
import pandas as pd

"""
Holdout Design: exp02_stop_reentry_v2

Re-run of protocol 1.0 under the current rules, not new evidence. Invested by default. A volatility trailing stop
exits. A logistic model of the 20-session forward return buys back when its probability clears the refit's training
base rate plus the candidate's offset. The model is refit weekly on the original windows (10 years, and all history).
An unfinished label is dropped. The candidate in force for a quarter is the pooled choice of the previous quarters.
"""

# DEFINE HOW CANDIDATE PERIODS ARE FORMED
PERIOD_RULE = {"embargo_sessions": exp_config.EMBARGO_TRADING_DAYS, "train_years": [exp_config.FOLD_TRAIN_WINDOW_YEARS]}
# DEFINE THE 18 CANDIDATES IN THE PROTOCOL ORDER (WINDOW, THEN k, THEN OFFSET)
CANDIDATE_LIST = [get_candidate_name_str(window_str, stop_k, offset)
                  for window_str in exp_config.TRAIN_WINDOW_CANDIDATE_LIST
                  for stop_k in exp_config.STOP_K_LIST
                  for offset in exp_config.REENTRY_THRESHOLD_OFFSET_LIST]
# DEFINE THE SELECTION RULE (MEAN OF THE LAST 4 QUARTERS; TIES: LARGER k, HIGHER OFFSET, THEN THE SHORTER WINDOW)
SELECTION_RULE = {"pooled_periods": exp_config.SELECTION_POOLED_QUARTER_COUNT,
                  "tie_break": [("stop_k", False), ("threshold_offset", False), ("train_window_months", True)]}
# DEFINE THE TIE COLUMNS THE RUNNER ATTACHES
CANDIDATE_TIE_VALUE_DICT = {
    "stop_k": {name_str: parse_candidate_dict(name_str)["stop_k"] for name_str in CANDIDATE_LIST},
    "threshold_offset": {name_str: parse_candidate_dict(name_str)["threshold_offset"] for name_str in CANDIDATE_LIST},
    "train_window_months": {name_str: int(exp_config.TRAIN_WINDOW_TIE_DICT[parse_candidate_dict(name_str)["train_window"]]) for name_str in CANDIDATE_LIST},
}
# COPY THE NAME AND THE PROTOCOL VERSION
EXPERIMENT_NAME = exp_config.EXPERIMENT_NAME
PROTOCOL_VERSION = exp_config.PROTOCOL_VERSION
# EVERY INPUT IS READ THROUGH THE POINT-IN-TIME CONTEXT (SPY BARS ONLY)
DATA_SOURCE_LIST = ["SPY_1MIN"]
# THE RETRAINING SETTINGS THE LEDGER ROW COPIES
RETRAIN_FREQUENCY_STR = exp_config.RETRAIN_FREQUENCY_STR
TRAIN_WINDOW_CANDIDATE_LIST = list(exp_config.TRAIN_WINDOW_CANDIDATE_LIST)
MIN_TRAIN_ROW_COUNT = exp_config.MIN_TRAIN_ROW_COUNT
FEATURE_COL_LIST = list(so_config.DAILY_FEATURE_COL_STR_LIST)
LABEL_COL_STR = exp_config.LABEL_COL_STR
# CACHES LIVE FOR ONE REPLAY. THE RUNNER GIVES EVERY REPLAY A FRESH MODULE.
_cache_dict = {}

# FUNCTION: A CHEAP KEY FOR ONE BAR ARRAY
def get_bar_key_tuple(ohlcv_array_dict_in):
    """
    Identifies a bar array so a later call on the same bars reuses the fit.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        tuple: Length, first close, last close, close sum
    """
    # THE CLOSE SUM MOVES WHEN A LATER BAR IS PERTURBED
    close_arr = np.asarray(ohlcv_array_dict_in["close_arr"], dtype=float)
    return (int(len(close_arr)), round(float(close_arr[0]), 8), round(float(close_arr[-1]), 8), round(float(close_arr.sum()), 4))

# FUNCTION: ONE LABELLED ROW PER SESSION
def get_labelled_row_pdf(ohlcv_array_dict_in):
    """
    Daily features, the 20-session label, and the clocks the rolling fit requires.

    Args:
        ohlcv_array_dict_in (dict): Bars

    Returns:
        pd.DataFrame: Rows for run_rolling_retrain_dict
    """
    # IMPORT THE CLOCKS AND THE DAILY FEATURES HERE
    from so import config
    from so.core.point_in_time import get_decision_ts
    from so.core.rolling_retrain import get_fixed_horizon_label_known_ts_arr
    from so.features.daily_features import get_daily_feature_pdf
    # THE DAILY TABLE, THEN THE DECISION MOMENT IN PLACE OF THE BAR-START LABEL
    daily_pdf = get_daily_feature_pdf(ohlcv_array_dict_in, config.LABEL_HORIZON_SESSIONS).copy()
    decision_list = [get_decision_ts(bar_ts) for bar_ts in daily_pdf["decision_ts"]]
    daily_pdf["decision_ts"] = decision_list
    daily_pdf["row_ts"] = decision_list
    daily_pdf["available_ts"] = decision_list
    daily_pdf["session"] = [pd.Timestamp(day).date() for day in daily_pdf["date"]]
    daily_pdf["label_known_ts"] = get_fixed_horizon_label_known_ts_arr(decision_list, config.LABEL_HORIZON_SESSIONS)
    return daily_pdf

# FUNCTION: DECISION SESSIONS LATE ENOUGH THAT THE FIRST REFIT MEETS THE MINIMUM
def get_decision_session_list(row_pdf_in):
    """
    Sessions from the feature warmup onward. The first of them is always a refit.

    Args:
        row_pdf_in (pd.DataFrame): Labelled rows

    Returns:
        list: Session dates
    """
    # THE 250-SESSION RETURN IS THE LONGEST FEATURE; THE LABEL THEN NEEDS THE HORIZON, THEN THE MINIMUM
    from so import config
    start_idx = int(max(config.PAST_RETURN_SESSION_LIST) + config.LABEL_HORIZON_SESSIONS + exp_config.MIN_TRAIN_ROW_COUNT)
    if start_idx >= len(row_pdf_in):
        raise ValueError(f"the series has {len(row_pdf_in)} sessions, shorter than the warmup {start_idx}.")
    # KEEP SESSIONS WHOSE FEATURES ARE FINITE
    finite_arr = row_pdf_in[FEATURE_COL_LIST].apply(pd.to_numeric, errors="coerce").notna().all(axis=1).to_numpy()
    return [session_date for session_date, finite_bool in zip(row_pdf_in["session"].iloc[start_idx:], finite_arr[start_idx:]) if finite_bool]

# FUNCTION: FIT ONE TRAINING WINDOW, REUSING A PREVIOUS FIT OF THE SAME BARS
def get_window_retrain_dict(ohlcv_array_dict_in, train_window_str_in):
    """
    Weekly rolling logistic regression for one training window.

    Args:
        ohlcv_array_dict_in (dict): Bars
        train_window_str_in (str): "10Y" or "ALL"

    Returns:
        dict: prediction_pdf, refit_log_pdf, row_pdf
    """
    # IMPORT THE WALKER HERE
    from so.core.rolling_retrain import run_rolling_retrain_dict
    # REUSE THE FIT WHEN THE BARS HAVE NOT CHANGED
    cache_key = (get_bar_key_tuple(ohlcv_array_dict_in), str(train_window_str_in))
    if cache_key in _cache_dict:
        return _cache_dict[cache_key]
    # BUILD THE ROWS ONCE PER BAR ARRAY
    row_key = (get_bar_key_tuple(ohlcv_array_dict_in), "rows")
    if row_key not in _cache_dict:
        _cache_dict[row_key] = get_labelled_row_pdf(ohlcv_array_dict_in)
    row_pdf = _cache_dict[row_key]
    # WALK THE DECISIONS
    decision_list = get_decision_session_list(row_pdf)
    result_dict = run_rolling_retrain_dict(row_pdf, FEATURE_COL_LIST, LABEL_COL_STR, fit_reentry_model_dict,
                                           predict_reentry_proba_arr, decision_list, train_window_str_in,
                                           RETRAIN_FREQUENCY_STR, int(exp_config.MODEL_SEED), int(MIN_TRAIN_ROW_COUNT), True)
    result_dict = {**result_dict, "row_pdf": row_pdf}
    _cache_dict[cache_key] = result_dict
    print(f"\trefit {train_window_str_in}: {len(result_dict['refit_log_pdf'])} models, {len(result_dict['prediction_pdf'])} decisions")
    return result_dict

# FUNCTION: READ SPY THROUGH THE CONTEXT SO THE ACCESS LOG RECORDS IT
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

# FUNCTION: PROBABILITY, THRESHOLD AND BASE RATE ALIGNED TO EVERY SESSION
def get_aligned_prediction_dict(ohlcv_array_dict_in, train_window_str_in, offset_float_in):
    """
    Full-length arrays. Sessions without a model are NaN, and a NaN threshold never re-enters.

    Args:
        ohlcv_array_dict_in (dict): Bars
        train_window_str_in (str): Training window
        offset_float_in (float): Added to the refit's training base rate

    Returns:
        dict: proba_arr, threshold_arr, volatility_arr, result_dict
    """
    # FIT THE WINDOW AND MAP EACH SESSION
    result_dict = get_window_retrain_dict(ohlcv_array_dict_in, train_window_str_in)
    prediction_pdf, refit_pdf = result_dict["prediction_pdf"], result_dict["refit_log_pdf"]
    balance_dict = {int(model_id): float(balance) for model_id, balance in zip(refit_pdf["model_id"], refit_pdf["label_balance"])}
    pred_dict = {pd.Timestamp(session_date).date(): (float(prediction), int(model_id))
                 for session_date, prediction, model_id in zip(prediction_pdf["session"], prediction_pdf["prediction"], prediction_pdf["model_id"])}
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    proba_arr, threshold_arr = np.full(session_count, np.nan), np.full(session_count, np.nan)
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        session_day = pd.Timestamp(session_date).date()
        if session_day not in pred_dict:
            continue
        proba_float, model_id = pred_dict[session_day]
        proba_arr[session_idx] = proba_float
        threshold_arr[session_idx] = balance_dict[model_id] + float(offset_float_in)
    # VOLATILITY IS THE SAME COLUMN THE STOP USED IN PROTOCOL 1.0
    volatility_arr = result_dict["row_pdf"]["daily_volatility"].to_numpy(dtype=float)
    return {"proba_arr": proba_arr, "threshold_arr": threshold_arr, "volatility_arr": volatility_arr, "result_dict": result_dict}

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
        simulation_dict_in (dict): Output of simulate_stop_reentry_dict

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
    One fresh window, as protocol 1.0 scored a validation quarter: start invested, one stop k, the weekly model of
    that candidate. The fit uses only rows whose label was knowable before each retraining decision.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Period bounds
        candidate_in (str): Candidate name
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, metric_dict
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.reentry_simulation import simulate_stop_reentry_dict
    # READ SPY, THEN THE CACHED MODEL OF THIS WINDOW
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    candidate_dict = parse_candidate_dict(candidate_in)
    aligned_dict = get_aligned_prediction_dict(ohlcv_array_dict_in, candidate_dict["train_window"], candidate_dict["threshold_offset"])
    reentry_func = get_session_threshold_reentry_func(aligned_dict["proba_arr"], aligned_dict["threshold_arr"])
    simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, aligned_dict["volatility_arr"],
                                                 candidate_dict["stop_k"], reentry_func, "model", max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
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

# FUNCTION: REPLAY THE CONTINUOUS PRIOR-ONLY PATH
def run_prior_only_path_dict(ohlcv_array_dict_in, period_pdf_in, selection_pdf_in, data_context_in=None):
    """
    One path from the first period through the last. Each session uses the stop k, the offset and the latest weekly
    model of the candidate in force. The position carries across periods.

    Args:
        ohlcv_array_dict_in (dict): Bars
        period_pdf_in (pd.DataFrame): Periods
        selection_pdf_in (pd.DataFrame): Candidate in force per period
        data_context_in (DataContext | None): Point-in-time context

    Returns:
        dict: daily_equity_pdf, trade_pdf, target_weight_arr, signal_arr, decision_session_list, refit_log_pdf
    """
    # IMPORT THE SIMULATOR HERE
    from so.core.reentry_simulation import simulate_stop_reentry_dict
    # READ SPY AND FIT EACH WINDOW ONCE
    read_context_inputs(ohlcv_array_dict_in, data_context_in)
    window_dict = {window_str: get_window_retrain_dict(ohlcv_array_dict_in, window_str) for window_str in TRAIN_WINDOW_CANDIDATE_LIST}
    # THE SPAN OF THE PATH
    date1, date2 = period_pdf_in["period_start"].iloc[0], period_pdf_in["period_end"].iloc[-1]
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    proba_arr, threshold_arr = np.full(session_count, np.nan), np.full(session_count, np.nan)
    stop_k_arr, signal_arr = np.full(session_count, np.nan), np.full(session_count, np.nan)
    used_id_dict = {window_str: set() for window_str in TRAIN_WINDOW_CANDIDATE_LIST}
    # PREDICTION AND BASE-RATE LOOKUP PER WINDOW
    lookup_dict = {}
    for window_str, result_dict in window_dict.items():
        balance_dict = {int(model_id): float(balance) for model_id, balance in zip(result_dict["refit_log_pdf"]["model_id"], result_dict["refit_log_pdf"]["label_balance"])}
        pred_dict = {pd.Timestamp(session_date).date(): (float(prediction), int(model_id))
                     for session_date, prediction, model_id in zip(result_dict["prediction_pdf"]["session"], result_dict["prediction_pdf"]["prediction"], result_dict["prediction_pdf"]["model_id"])}
        lookup_dict[window_str] = (pred_dict, balance_dict)
    volatility_arr = window_dict[TRAIN_WINDOW_CANDIDATE_LIST[0]]["row_pdf"]["daily_volatility"].to_numpy(dtype=float)
    # WRITE THE GOVERNING CANDIDATE ON EACH SESSION
    for session_idx, session_date in enumerate(ohlcv_array_dict_in["session_date_list"]):
        candidate_str = get_session_candidate_str(session_date, period_pdf_in, selection_pdf_in)
        if candidate_str is None:
            continue
        candidate_dict = parse_candidate_dict(candidate_str)
        session_day = pd.Timestamp(session_date).date()
        pred_dict, balance_dict = lookup_dict[candidate_dict["train_window"]]
        stop_k_arr[session_idx] = candidate_dict["stop_k"]
        if session_day not in pred_dict:
            continue
        proba_float, model_id = pred_dict[session_day]
        proba_arr[session_idx] = proba_float
        threshold_arr[session_idx] = balance_dict[model_id] + candidate_dict["threshold_offset"]
        signal_arr[session_idx] = proba_float
        used_id_dict[candidate_dict["train_window"]].add(model_id)
    # REPLAY ONCE SO THE POSITION CARRIES ACROSS PERIODS
    reentry_func = get_session_threshold_reentry_func(proba_arr, threshold_arr)
    simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1, date2, volatility_arr, stop_k_arr, reentry_func, "model",
                                                 max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
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
    simulation_dict["stop_k_arr"] = stop_k_arr[path_idx_list]
    simulation_dict["full_stop_k_arr"] = stop_k_arr
    simulation_dict["decision_session_list"] = [session_date_list[idx] for idx in path_idx_list]
    # THE MODELS THE PATH ACTUALLY USED
    refit_list = []
    for window_str, id_set in used_id_dict.items():
        refit_pdf = window_dict[window_str]["refit_log_pdf"]
        kept_pdf = refit_pdf[refit_pdf["model_id"].isin(id_set)].copy()
        kept_pdf["candidate"] = window_str
        refit_list.append(kept_pdf)
    simulation_dict["refit_log_pdf"] = pd.concat(refit_list, ignore_index=True) if refit_list else pd.DataFrame()
    return simulation_dict

# FUNCTION: FIXED-DELAY AND TREND BASELINES OVER A SPAN
def get_baseline_return_dict(ohlcv_array_dict_in, date1_in, date2_in):
    """
    The uninformed baselines named in protocol 1.0, over the span the caller names. Fixed-delay uses each pre-registered
    stop k (the grid, not a k chosen on this span). The trend rule uses the 200-session average. Random re-entry is
    matched to a path and is computed in the development report, where that path exists.

    Args:
        ohlcv_array_dict_in (dict): Bars
        date1_in, date2_in: Span

    Returns:
        dict: baseline name -> total return
    """
    # IMPORT THE SIMULATORS HERE
    from so.core.reentry_simulation import simulate_stop_reentry_dict, simulate_trend_rule_dict, get_fixed_delay_reentry_func
    from so.features.daily_features import get_daily_feature_pdf
    # ONE VOLATILITY COLUMN AND THE DAILY TABLE
    row_key = (get_bar_key_tuple(ohlcv_array_dict_in), "rows")
    row_pdf = _cache_dict[row_key] if row_key in _cache_dict else get_labelled_row_pdf(ohlcv_array_dict_in)
    volatility_arr = row_pdf["daily_volatility"].to_numpy(dtype=float)
    return_dict = {}
    for stop_k in exp_config.STOP_K_LIST:
        for delay_int in exp_config.FIXED_DELAY_SESSION_LIST:
            simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, volatility_arr, float(stop_k),
                                                         get_fixed_delay_reentry_func(int(delay_int)), "delay", max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
            return_dict[f"fixed_delay_k{int(stop_k)}_{int(delay_int)}"] = simulation_dict["metric_dict"]["total_return"]
    # THE 200-SESSION RULE, NO STOP AND NO FORCED RE-ENTRY
    daily_pdf = get_daily_feature_pdf(ohlcv_array_dict_in)
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
