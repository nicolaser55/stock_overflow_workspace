import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL, SEED)
from so import config
# IMPORT TRADE EXECUTION FUNCTIONS (FEES AND SHARE COUNT)
from so.core.trade_execution import calculate_side_fee, get_affordable_share_count
# IMPORT BACKTEST FUNCTIONS (DAILY EQUITY, FIRST ENTRY BAR, BUY AND HOLD)
from so.core.backtest_simulation import get_daily_equity_pdf, get_session_first_entry_idx, simulate_buy_and_hold_dict
# IMPORT PERFORMANCE METRICS
from so.core.performance_metrics import get_sharpe_ratio, get_max_drawdown
# IMPORT DAILY FEATURE FUNCTIONS (DECISION AND FILL BARS)
from so.features.daily_features import get_session_decision_idx_dict

"""
Exit And Re-entry Simulation (used by exp02 stop_reentry and exp03 ath_exit)

State machine over one evaluation window, one position at a time, whole account invested, compounding:

    INVESTED --(trailing stop hit, intraday)-----------------------> CASH
    INVESTED --(exit signal at the decision bar, trend rule only)---> CASH   (sell at the 15:59 open)
    CASH     --(re-entry rule True at the decision bar)-------------> INVESTED (buy at the 15:59 open)
    CASH     --(MAX_CASH_SESSIONS decisions spent in cash)----------> INVESTED (forced re-entry)

Trailing stop (one bar at a time, vectorized per session):
    stop for bar j = max(previous stop, highest close of the bars entry..j-1 x (1 - k x daily_volatility of the session))
    The stop is active from the bar after the entry bar and never moves down. Fills use the v1 stop-loss rules:
    a bar opening at or below the stop exits at its open (gap), otherwise a low at or below the stop exits at the stop.
    Market exits pay MARKET_EXIT_SLIPPAGE_PER_SHARE; entries pay ENTRY_SLIPPAGE_PER_SHARE; IBKR fees on both sides.

Cash-session counter: it counts the DECISIONS made in cash. A stop hit at or before the decision bar makes that
session's decision the first cash decision (re-entry the same day is allowed, protocol §5).

Window rules: the window starts INVESTED at the first allowed entry of its first session (10:00 open, as buy-and-hold).
No entry is made at the decision of the last session. A position still open at the end is sold at the last close (END).

Re-entry rules are functions f(session_idx, cash_session_count, episode_dict) -> bool. Builders are provided for the
model, fixed delay, random and oracle rules (get_*_reentry_func).
"""

"""
Re-entry Rule Builders
"""

# FUNCTION: GET THE MODEL RE-ENTRY RULE
def get_model_reentry_func(proba_arr_in, threshold_float_in):
    """
    Re-enters when the model probability of the session is at or above the threshold (NaN never re-enters).

    Args:
        proba_arr_in (np.ndarray): P(positive forward return) per session position (NaN where unavailable)
        threshold_float_in (float): Re-entry threshold p*

    Returns:
        function: Re-entry rule
    """
    # RETURN THE RULE
    return lambda session_idx, cash_session_count, episode_dict: bool(proba_arr_in[session_idx] >= threshold_float_in)

# FUNCTION: GET THE FIXED-DELAY RE-ENTRY RULE
def get_fixed_delay_reentry_func(delay_session_count_in):
    """
    Re-enters at the decision of the delay-th session spent in cash (1 = the first cash decision).

    Args:
        delay_session_count_in (int): Number of cash decisions before re-entry

    Returns:
        function: Re-entry rule
    """
    # RETURN THE RULE
    return lambda session_idx, cash_session_count, episode_dict: cash_session_count >= delay_session_count_in

# FUNCTION: GET THE RANDOM RE-ENTRY RULE
def get_random_reentry_func(daily_probability_in, seed_in=config.RANDOM_SEED):
    """
    Re-enters at each cash decision with a fixed probability (mean time in cash about 1 / probability decisions).

    Args:
        daily_probability_in (float): Re-entry probability per cash decision
        seed_in (int): Random seed

    Returns:
        function: Re-entry rule
    """
    # CREATE THE RANDOM GENERATOR
    rng = np.random.default_rng(seed_in)
    # RETURN THE RULE
    return lambda session_idx, cash_session_count, episode_dict: bool(rng.random() < daily_probability_in)

# FUNCTION: GET THE ORACLE RE-ENTRY RULE (UPPER BOUND, USES FUTURE PRICES; MECHANISM CHECK ONLY)
def get_oracle_reentry_func(ohlcv_array_dict_in, window_session_idx_arr_in, max_cash_sessions_in):
    """
    Re-enters at the cash decision whose fill price (15:59 open) is the LOWEST of the decisions allowed before the forced
    re-entry. It looks into the future, so it is only an upper bound of what re-entry timing could add (step 10).

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        window_session_idx_arr_in (np.ndarray): Session positions of the window (the last one never re-enters)
        max_cash_sessions_in (int): Forced re-entry after this many cash decisions

    Returns:
        function: Re-entry rule
    """
    # COLLECT THE FILL BARS
    fill_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict_in)["fill_idx_arr"]
    # DEFINE THE LAST SESSION THAT ALLOWS AN ENTRY
    last_entry_session_idx = int(window_session_idx_arr_in[-1]) - 1
    # DICTIONARY OF THE TARGET SESSION PER EPISODE
    target_dict = {}
    # FUNCTION: THE RULE
    def oracle_func(session_idx, cash_session_count, episode_dict):
        # DEFINE THE EPISODE KEY (FIRST CASH DECISION SESSION)
        episode_key = episode_dict["first_cash_session_idx"]
        # IF THE TARGET IS NOT KNOWN YET
        if episode_key not in target_dict:
            # COLLECT THE CANDIDATE SESSIONS (FIRST CASH DECISION .. FORCED RE-ENTRY, INSIDE THE WINDOW)
            candidate_arr = np.arange(episode_key, min(episode_key + max_cash_sessions_in, last_entry_session_idx + 1))
            # STORE THE SESSION WITH THE LOWEST FILL OPEN
            target_dict[episode_key] = int(candidate_arr[np.argmin(ohlcv_array_dict_in["open_arr"][fill_idx_arr[candidate_arr]])]) if len(candidate_arr) else -1
        # RETURN TRUE ON THE TARGET SESSION
        return session_idx == target_dict[episode_key]
    # RETURN THE RULE
    return oracle_func

"""
Simulator
"""

# FUNCTION: GET THE SESSION POSITIONS OF A DATE WINDOW
def get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in):
    """
    Returns the session positions whose date is within [date1, date2].

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)

    Returns:
        np.ndarray: Session positions (sorted)
    """
    # CONVERT THE BOUNDS
    date1_object, date2_object = pd.to_datetime(date1_in).date(), pd.to_datetime(date2_in).date()
    # RETURN THE POSITIONS
    return np.array([idx for idx, date_object in enumerate(ohlcv_array_dict_in["session_date_list"]) if date1_object <= date_object <= date2_object], dtype=int)

# FUNCTION: SIMULATE THE STOP AND RE-ENTRY STRATEGY OVER A WINDOW
def simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, volatility_arr_in, stop_k_in=None,
                               reentry_func_in=None, reentry_reason_str_in="model", exit_signal_arr_in=None,
                               max_cash_sessions_in=None,
                               initial_capital_in=config.INITIAL_CAPITAL,
                               entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                               market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
    """
    Simulates the state machine of the module docstring over one window.

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict (complete data)
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        volatility_arr_in (np.ndarray): daily_volatility per session position (stop distance = k x volatility)
        stop_k_in (float | None): Stop multiplier k (None = no stop)
        reentry_func_in (function | None): Re-entry rule f(session_idx, cash_session_count, episode_dict) (None = never).
            A rule may set episode_dict["exit_block_sessions"] = c before returning True: the exit signal is then
            ignored for the c decisions after the re-entry (cooling-off; absent = 0, the original behaviour).
            A rule may set episode_dict["require_fresh_exit"] = True before returning True: if the exit signal is on
            at the re-entry decision, it is then ignored until it has been off on at least one decision (a new exit
            needs a fresh signal; absent = False, the original behaviour)
        reentry_reason_str_in (str): Label of the rule's re-entries ("model", "delay", "random", "oracle", "rule")
        exit_signal_arr_in (np.ndarray | None): Bool per session position: sell at the decision while invested (trend rule)
        max_cash_sessions_in (int | None): Forced re-entry after this many cash decisions (None = never forced; pass the
            experiment's value explicitly, e.g. exp02 config.MAX_CASH_SESSIONS)
        initial_capital_in (float): Starting cash
        entry_slippage_in (float): Dollars per share added to entries
        market_exit_slippage_in (float): Dollars per share subtracted from exits

    Returns:
        dict: transaction_pdf, episode_pdf, daily_equity_pdf, metric_dict
    """
    # COLLECT THE ARRAYS
    open_arr, low_arr, close_arr = ohlcv_array_dict_in["open_arr"], ohlcv_array_dict_in["low_arr"], ohlcv_array_dict_in["close_arr"]
    timestamp_index = ohlcv_array_dict_in["timestamp_index"]
    start_idx_arr, end_idx_arr = ohlcv_array_dict_in["session_start_idx_arr"], ohlcv_array_dict_in["session_end_idx_arr"]
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    decision_idx_arr, fill_idx_arr = idx_dict["decision_idx_arr"], idx_dict["fill_idx_arr"]
    # COLLECT THE WINDOW SESSIONS
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    # IF THE WINDOW IS EMPTY
    if len(window_session_idx_arr) == 0:
        # RETURN EMPTY RESULTS
        return {"transaction_pdf": pd.DataFrame(), "episode_pdf": pd.DataFrame(), "daily_equity_pdf": pd.DataFrame(), "metric_dict": {}}
    # DEFINE THE STATE
    state_dict = {"cash": float(initial_capital_in), "invested": False, "share_count": 0, "entry_idx": -1, "buy_fill": np.nan,
                  "buy_fee": 0.0, "entry_reason": "", "decision_ts": pd.NaT, "highest_close": -np.inf, "stop": -np.inf,
                  "cash_session_count": 0, "episode": None, "exit_block_until": -1, "fresh_exit_pending": False}
    # LISTS TO HOLD THE TRANSACTIONS AND EPISODES
    transaction_dict_list, episode_dict_list = [], []

    # FUNCTION: BUY AT A BAR OPEN
    def buy(bar_idx, reason_str, decision_ts):
        # CALCULATE THE FILL PRICE AND SHARE COUNT
        fill_price = open_arr[bar_idx] + entry_slippage_in
        share_count = get_affordable_share_count(state_dict["cash"], fill_price)
        # IF NOTHING IS AFFORDABLE
        if share_count <= 0:
            return False
        # PAY THE SHARES AND THE FEE
        buy_fee = calculate_side_fee(share_count, fill_price)
        state_dict["cash"] -= share_count * fill_price + buy_fee
        # UPDATE THE STATE
        state_dict.update({"invested": True, "share_count": share_count, "entry_idx": int(bar_idx), "buy_fill": fill_price,
                           "buy_fee": buy_fee, "entry_reason": reason_str, "decision_ts": decision_ts,
                           "highest_close": close_arr[bar_idx], "stop": -np.inf, "cash_session_count": 0, "fresh_exit_pending": False})
        # CLOSE THE OPEN EPISODE
        if state_dict["episode"] is not None:
            state_dict["episode"].update({"reentry_ts": timestamp_index[bar_idx], "reentry_fill_price": fill_price, "reentry_reason": reason_str})
            episode_dict_list.append(state_dict["episode"])
            state_dict["episode"] = None
        # RETURN TRUE
        return True

    # FUNCTION: SELL AT A PRICE
    def sell(bar_idx, raw_price, reason_str, stop_price=np.nan):
        # CALCULATE THE FILL PRICE AND THE FEE
        fill_price = raw_price - market_exit_slippage_in
        sell_fee = calculate_side_fee(state_dict["share_count"], fill_price)
        # RECEIVE THE CASH
        state_dict["cash"] += state_dict["share_count"] * fill_price - sell_fee
        # RECORD THE TRANSACTION
        net_profit = state_dict["share_count"] * (fill_price - state_dict["buy_fill"]) - state_dict["buy_fee"] - sell_fee
        transaction_dict_list.append({
            "transaction_id": len(transaction_dict_list),
            "decision_ts": state_dict["decision_ts"],
            "entry_reason": state_dict["entry_reason"],
            "buy_ts": timestamp_index[state_dict["entry_idx"]],
            "buy_idx": state_dict["entry_idx"],
            "buy_raw_price": open_arr[state_dict["entry_idx"]],
            "buy_fill_price": round(state_dict["buy_fill"], 6),
            "share_count": state_dict["share_count"],
            "buy_fee": state_dict["buy_fee"],
            "sell_ts": timestamp_index[bar_idx],
            "sell_idx": int(bar_idx),
            "sell_raw_price": round(raw_price, 6),
            "sell_fill_price": round(fill_price, 6),
            "sell_fee": sell_fee,
            "exit_reason": reason_str,
            "SL_price": round(stop_price, 6) if np.isfinite(stop_price) else np.nan,
            "TP_price": np.nan,
            "net_profit": round(net_profit, 6),
            "hold_bar_count": int(bar_idx) - state_dict["entry_idx"],
            "equity_after": round(state_dict["cash"], 6),
        })
        # UPDATE THE STATE
        state_dict.update({"invested": False, "share_count": 0, "entry_idx": -1, "buy_fill": np.nan, "buy_fee": 0.0, "cash_session_count": 0})
        # OPEN AN EPISODE (NOT FOR THE END OF THE WINDOW)
        if reason_str != "END":
            state_dict["episode"] = {"exit_ts": timestamp_index[bar_idx], "exit_reason": reason_str, "exit_fill_price": fill_price,
                                     "first_cash_session_idx": None, "cash_session_count": 0}

    # FUNCTION: CHECK THE TRAILING STOP OVER A RANGE OF BARS
    def check_stop(bar1_idx, bar2_idx, session_idx):
        # IF THE RANGE IS EMPTY
        if bar2_idx < bar1_idx:
            return False
        # COLLECT THE CLOSES OF THE RANGE
        range_close_arr = close_arr[bar1_idx:bar2_idx + 1]
        # IF THERE IS NO STOP (NO MULTIPLIER OR NO VOLATILITY YET)
        volatility = volatility_arr_in[session_idx]
        if stop_k_in is None or not np.isfinite(volatility):
            # UPDATE THE HIGHEST CLOSE AND RETURN
            state_dict["highest_close"] = max(state_dict["highest_close"], range_close_arr.max())
            return False
        # CALCULATE THE HIGHEST CLOSE BEFORE EVERY BAR OF THE RANGE
        highest_before_arr = np.maximum.accumulate(np.concatenate([[state_dict["highest_close"]], range_close_arr]))[:-1]
        # CALCULATE THE STOP OF EVERY BAR (NEVER MOVES DOWN)
        stop_arr = np.maximum(state_dict["stop"], highest_before_arr * (1 - stop_k_in * volatility))
        # FIND THE FIRST BAR WHOSE LOW REACHES THE STOP
        hit_pos_arr = np.flatnonzero(low_arr[bar1_idx:bar2_idx + 1] <= stop_arr)
        # IF THE STOP IS HIT
        if len(hit_pos_arr) > 0:
            # COLLECT THE BAR AND THE STOP
            hit_pos = int(hit_pos_arr[0])
            bar_idx, stop_price = bar1_idx + hit_pos, stop_arr[hit_pos]
            # FILL AT THE OPEN ON A GAP, OTHERWISE AT THE STOP
            raw_price = open_arr[bar_idx] if open_arr[bar_idx] <= stop_price else stop_price
            # SELL
            sell(bar_idx, raw_price, "STOP", stop_price)
            return True
        # UPDATE THE HIGHEST CLOSE AND THE STOP
        state_dict["highest_close"] = max(state_dict["highest_close"], range_close_arr.max())
        state_dict["stop"] = max(state_dict["stop"], stop_arr[-1])
        # RETURN FALSE
        return False

    # ENTER AT THE FIRST ALLOWED BAR OF THE WINDOW (AS BUY-AND-HOLD)
    first_session_idx = int(window_session_idx_arr[0])
    buy(get_session_first_entry_idx(ohlcv_array_dict_in, first_session_idx), "window_start", pd.NaT)
    # ITERATE OVER THE WINDOW SESSIONS
    for session_pos, session_idx in enumerate(window_session_idx_arr):
        # COLLECT THE SESSION BARS
        start_idx, end_idx = int(start_idx_arr[session_idx]), int(end_idx_arr[session_idx])
        decision_idx, fill_idx = int(decision_idx_arr[session_idx]), int(fill_idx_arr[session_idx])
        is_last_session = session_pos == len(window_session_idx_arr) - 1
        # IF INVESTED: CHECK THE STOP UP TO THE DECISION BAR
        if state_dict["invested"]:
            check_stop(max(start_idx, state_dict["entry_idx"] + 1), decision_idx, session_idx)
        # IF A FRESH EXIT SIGNAL IS PENDING AND THE SIGNAL IS OFF: THE NEXT SIGNAL IS FRESH
        if state_dict["fresh_exit_pending"] and state_dict["invested"] and exit_signal_arr_in is not None and not bool(exit_signal_arr_in[session_idx]):
            state_dict["fresh_exit_pending"] = False
        # DECISION WHILE INVESTED: EXIT SIGNAL (TREND RULE ONLY)
        if state_dict["invested"] and exit_signal_arr_in is not None and bool(exit_signal_arr_in[session_idx]) and not is_last_session and int(session_idx) > state_dict["exit_block_until"] \
                and not state_dict["fresh_exit_pending"]:
            sell(fill_idx, open_arr[fill_idx], "SIGNAL")
        # DECISION WHILE IN CASH
        elif not state_dict["invested"] and state_dict["episode"] is not None:
            # COUNT THE CASH DECISION
            state_dict["cash_session_count"] += 1
            state_dict["episode"]["cash_session_count"] = state_dict["cash_session_count"]
            if state_dict["episode"]["first_cash_session_idx"] is None:
                state_dict["episode"]["first_cash_session_idx"] = int(session_idx)
            # IF ENTRIES ARE ALLOWED (NOT THE LAST SESSION)
            if not is_last_session:
                # ASK THE RE-ENTRY RULE
                rule_bool = reentry_func_in is not None and reentry_func_in(int(session_idx), state_dict["cash_session_count"], state_dict["episode"])
                # IF THE RULE SAYS BUY
                if rule_bool:
                    # READ THE COOLING-OFF REQUESTED BY THE RULE (0 IF ABSENT) AND BLOCK THE EXITS AFTER THE RE-ENTRY
                    block_session_count = int(state_dict["episode"].get("exit_block_sessions", 0))
                    fresh_exit_bool = bool(state_dict["episode"].get("require_fresh_exit", False))
                    if buy(fill_idx, reentry_reason_str_in, timestamp_index[decision_idx]):
                        state_dict["exit_block_until"] = int(session_idx) + block_session_count
                        # A FRESH SIGNAL IS NEEDED ONLY IF THE EXIT SIGNAL IS ON AT THE RE-ENTRY DECISION
                        state_dict["fresh_exit_pending"] = fresh_exit_bool and exit_signal_arr_in is not None and bool(exit_signal_arr_in[session_idx])
                # IF THE MAXIMUM TIME IN CASH IS REACHED
                elif max_cash_sessions_in is not None and state_dict["cash_session_count"] >= max_cash_sessions_in:
                    buy(fill_idx, "forced", timestamp_index[decision_idx])
        # IF INVESTED: CHECK THE STOP ON THE BARS AFTER THE DECISION BAR (THE NEW ENTRY BAR ITSELF IS EXCLUDED)
        if state_dict["invested"]:
            check_stop(max(decision_idx + 1, state_dict["entry_idx"] + 1), end_idx, session_idx)
    # CLOSE AN OPEN POSITION AT THE LAST CLOSE OF THE WINDOW
    last_end_idx = int(end_idx_arr[window_session_idx_arr[-1]])
    if state_dict["invested"]:
        sell(last_end_idx, close_arr[last_end_idx], "END")
    # RECORD AN EPISODE STILL OPEN AT THE END (VALUED AS IF RE-ENTERED AT THE LAST CLOSE, NO COST)
    if state_dict["episode"] is not None:
        state_dict["episode"].update({"reentry_ts": timestamp_index[last_end_idx], "reentry_fill_price": close_arr[last_end_idx], "reentry_reason": "window_end"})
        episode_dict_list.append(state_dict["episode"])
    # CONVERT THE RESULTS
    transaction_pdf = pd.DataFrame(transaction_dict_list)
    episode_pdf = pd.DataFrame(episode_dict_list)
    # IF THERE ARE EPISODES
    if not episode_pdf.empty:
        # CALCULATE THE SHARE GAIN OF EVERY EPISODE (SHARES OWNED AFTER / BEFORE - 1, BEFORE FEES; > 0 = BOUGHT BACK LOWER)
        episode_pdf["share_gain_pct"] = episode_pdf["exit_fill_price"] / episode_pdf["reentry_fill_price"] - 1
    # CALCULATE THE DAILY EQUITY
    date1_str, date2_str = str(ohlcv_array_dict_in["session_date_list"][window_session_idx_arr[0]]), str(ohlcv_array_dict_in["session_date_list"][window_session_idx_arr[-1]])
    daily_equity_pdf = get_daily_equity_pdf(transaction_pdf, ohlcv_array_dict_in, date1_str, date2_str, initial_capital_in)
    # CALCULATE THE METRICS
    metric_dict = get_stop_reentry_metric_dict(transaction_pdf, episode_pdf, daily_equity_pdf, initial_capital_in)
    # RETURN THE RESULTS
    return {"transaction_pdf": transaction_pdf, "episode_pdf": episode_pdf, "daily_equity_pdf": daily_equity_pdf, "metric_dict": metric_dict}

"""
Metrics And Benchmarks
"""

# FUNCTION: GET THE METRICS OF A STOP AND RE-ENTRY SIMULATION
def get_stop_reentry_metric_dict(transaction_pdf_in, episode_pdf_in, daily_equity_pdf_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Calculates the protocol v2 metrics of one simulation.

    Args:
        transaction_pdf_in (pd.DataFrame): Transactions of the simulation
        episode_pdf_in (pd.DataFrame): Out-of-market episodes of the simulation
        daily_equity_pdf_in (pd.DataFrame): Daily equity (date, equity, in_position)
        initial_capital_in (float): Starting cash

    Returns:
        dict: total_return, sharpe_ratio, max_drawdown, final_equity, trade_count, stop_count, signal_exit_count,
              rule_reentry_count, forced_reentry_count, cash_session_pct, mean_cash_sessions, mean_share_gain_pct,
              positive_episode_pct
    """
    # COLLECT THE FINAL EQUITY
    final_equity = float(daily_equity_pdf_in["equity"].iloc[-1]) if not daily_equity_pdf_in.empty else float(initial_capital_in)
    # COLLECT THE EPISODES THAT ENDED WITH A RE-ENTRY
    has_episodes = episode_pdf_in is not None and not episode_pdf_in.empty
    closed_episode_pdf = episode_pdf_in[episode_pdf_in["reentry_reason"] != "window_end"] if has_episodes else pd.DataFrame()
    # COLLECT THE EXIT AND ENTRY REASONS
    exit_reason_series = transaction_pdf_in["exit_reason"] if not transaction_pdf_in.empty else pd.Series(dtype=object)
    entry_reason_series = transaction_pdf_in["entry_reason"] if not transaction_pdf_in.empty else pd.Series(dtype=object)
    # RETURN THE METRICS (THE LAST SESSION IS EXCLUDED FROM THE CASH SHARE: EVERY POSITION IS CLOSED AT ITS CLOSE)
    return {
        "total_return": round(final_equity / initial_capital_in - 1, 8),
        "sharpe_ratio": get_sharpe_ratio(daily_equity_pdf_in, initial_capital_in),
        "max_drawdown": get_max_drawdown(daily_equity_pdf_in, initial_capital_in),
        "final_equity": round(final_equity, 6),
        "trade_count": int(len(transaction_pdf_in)),
        "stop_count": int((exit_reason_series == "STOP").sum()),
        "signal_exit_count": int((exit_reason_series == "SIGNAL").sum()),
        "rule_reentry_count": int((~entry_reason_series.isin(["window_start", "forced"])).sum()),
        "forced_reentry_count": int((entry_reason_series == "forced").sum()),
        "cash_session_pct": float((~daily_equity_pdf_in["in_position"].iloc[:-1].astype(bool)).mean()) if len(daily_equity_pdf_in) > 1 else 0.0,
        "mean_cash_sessions": float(closed_episode_pdf["cash_session_count"].mean()) if len(closed_episode_pdf) else np.nan,
        "mean_share_gain_pct": float(episode_pdf_in["share_gain_pct"].mean()) if has_episodes else np.nan,
        "positive_episode_pct": float((episode_pdf_in["share_gain_pct"] > 0).mean()) if has_episodes else np.nan,
    }

# FUNCTION: GET THE BUY AND HOLD METRICS OF A WINDOW
def get_buy_and_hold_result_dict(ohlcv_array_dict_in, date1_in, date2_in, initial_capital_in=config.INITIAL_CAPITAL,
                                 entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                                 market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
    """
    Simulates buy-and-hold over the window (10:00 open of the first session -> last close) with the same costs.

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        initial_capital_in (float): Starting cash
        entry_slippage_in, market_exit_slippage_in (float): Slippage per share

    Returns:
        dict: daily_equity_pdf, metric_dict (total_return, sharpe_ratio, max_drawdown, final_equity)
    """
    # SIMULATE BUY AND HOLD
    buy_hold_dict = simulate_buy_and_hold_dict(ohlcv_array_dict_in, str(date1_in), str(date2_in), initial_capital_in, entry_slippage_in, market_exit_slippage_in)
    daily_equity_pdf = buy_hold_dict["daily_equity_pdf"]
    final_equity = float(daily_equity_pdf["equity"].iloc[-1])
    # RETURN THE RESULTS
    return {"daily_equity_pdf": daily_equity_pdf,
            "metric_dict": {"total_return": round(final_equity / initial_capital_in - 1, 8),
                            "sharpe_ratio": get_sharpe_ratio(daily_equity_pdf, initial_capital_in),
                            "max_drawdown": get_max_drawdown(daily_equity_pdf, initial_capital_in),
                            "final_equity": round(final_equity, 6)}}

# FUNCTION: SIMULATE THE TEXTBOOK TREND RULE (200-SESSION MOVING AVERAGE, NO STOP)
def simulate_trend_rule_dict(ohlcv_array_dict_in, daily_pdf_in, date1_in, date2_in, ma_col_str_in="ma200_dist_pct", **simulation_kwargs):
    """
    Invested while the decision close is above the moving average, in cash while it is below (decisions at 15:58, fills at
    the 15:59 open). Starts invested like every other strategy. No stop and no forced re-entry.

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        daily_pdf_in (pd.DataFrame): Output of daily_features.get_daily_feature_pdf (indexed by session position)
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        ma_col_str_in (str): Moving average distance column
        **simulation_kwargs: Cost overrides for simulate_stop_reentry_dict

    Returns:
        dict: Output of simulate_stop_reentry_dict
    """
    # COLLECT THE MOVING AVERAGE DISTANCE (NaN = NO SIGNAL EITHER WAY)
    ma_dist_arr = daily_pdf_in[ma_col_str_in].to_numpy(dtype=float)
    above_arr, below_arr = np.nan_to_num(ma_dist_arr, nan=0.0) > 0, np.nan_to_num(ma_dist_arr, nan=0.0) < 0
    # RETURN THE SIMULATION
    return simulate_stop_reentry_dict(ohlcv_array_dict_in, date1_in, date2_in, np.full(len(ma_dist_arr), np.nan), stop_k_in=None,
                                      reentry_func_in=lambda session_idx, cash_session_count, episode_dict: bool(above_arr[session_idx]),
                                      reentry_reason_str_in="rule", exit_signal_arr_in=below_arr, max_cash_sessions_in=None, **simulation_kwargs)

"""
Mechanism Diagnostics
"""

# FUNCTION: GET THE PRICE PATH AFTER EVERY EXIT (SHARE GAIN IF RE-ENTERED AT THE n-TH CASH DECISION)
def get_post_exit_path_pdf(ohlcv_array_dict_in, episode_pdf_in, max_cash_sessions_in,
                           entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE):
    """
    For every exit, calculates the share gain that re-entering at the n-th cash decision WOULD have produced, for
    n = 1 .. max_cash_sessions_in (whatever the episode actually did). Averaged over exits, the curve shows whether prices
    keep falling after a stop (waiting pays, information has something to find) or rebound (re-entering fast is best).

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        episode_pdf_in (pd.DataFrame): episode_pdf of a simulation (exit_fill_price, first_cash_session_idx)
        max_cash_sessions_in (int): Longest delay considered
        entry_slippage_in (float): Dollars per share added to the hypothetical re-entry

    Returns:
        pd.DataFrame: episode_id, exit_ts, cash_decision_count (n), reentry_fill_price, share_gain_pct, log_share_gain

    Average log_share_gain, not share_gain_pct: the mean of S / R - 1 is biased upwards by the randomness of R alone
    (Jensen's inequality: even on a driftless random walk it grows with n), the mean of log(S / R) is not.
    """
    # COLLECT THE FILL BARS AND THE SESSION COUNT
    fill_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict_in)["fill_idx_arr"]
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    # LIST TO HOLD THE ROWS
    row_dict_list = []
    # ITERATE OVER THE EPISODES WITH A FIRST CASH DECISION
    for episode_id, episode_row in episode_pdf_in.dropna(subset=["first_cash_session_idx"]).iterrows():
        # ITERATE OVER THE DELAYS
        for cash_decision_count in range(1, max_cash_sessions_in + 1):
            # COLLECT THE SESSION OF THE n-TH CASH DECISION
            session_idx = int(episode_row["first_cash_session_idx"]) + cash_decision_count - 1
            # STOP AT THE END OF THE DATA
            if session_idx >= session_count:
                break
            # CALCULATE THE HYPOTHETICAL RE-ENTRY
            reentry_fill_price = ohlcv_array_dict_in["open_arr"][fill_idx_arr[session_idx]] + entry_slippage_in
            row_dict_list.append({"episode_id": episode_id, "exit_ts": episode_row["exit_ts"], "cash_decision_count": cash_decision_count,
                                  "reentry_fill_price": reentry_fill_price, "share_gain_pct": episode_row["exit_fill_price"] / reentry_fill_price - 1,
                                  "log_share_gain": float(np.log(episode_row["exit_fill_price"] / reentry_fill_price))})
    # RETURN THE DATAFRAME
    return pd.DataFrame(row_dict_list)

