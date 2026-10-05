import pandas as pd
import numpy as np
# IMPORT EXPERIMENT CONFIGURATION
from so import config

"""
Trade Execution Rules

This module is the single source of truth for HOW a trade is executed. Both the barrier target matrix
(barrier_labels.py) and the backtest simulator (backtest_simulation.py) call these functions, so the label
of a timestamp and the simulated trade from the same timestamp always follow identical rules.

Agreed rules (2026-10-01):
    1. The feature row of bar t is the decision. The entry is at the OPEN of bar t+1 (same session).
    2. Stop loss (SL) and take profit (TP) are computed from the entry open and become active on the bar AFTER the entry bar.
    3. If a bar OPENS beyond a level (overnight gap or a move during the previous bar), the exit is at that bar's open.
    4. Otherwise an SL is hit when low <= SL (fill at SL) and a TP is hit when high >= TP + TP_THROUGH_TICKS * PRICE_TICK
       (fill at TP; a touch is not enough for a limit order). If both are hit on the same bar, SL wins.
    5. Maximum holding period: MAX_HOLD_TRADING_DAYS trading days (entry day = day 1). Time limit exit at the close of the
       last bar of the last day.
    6. Costs: + ENTRY_SLIPPAGE_PER_SHARE on entry, - MARKET_EXIT_SLIPPAGE_PER_SHARE on SL / time limit exits,
       - LIMIT_EXIT_SLIPPAGE_PER_SHARE on TP exits, IBKR fixed fees per side.
"""

"""
Market Data Arrays
"""

# FUNCTION: GET THE OHLCV ARRAY DICTIONARY
def get_ohlcv_array_dict(complete_ohlcv_pdf_in):
    """
    Converts the complete minute OHLCV DataFrame into numpy arrays and session lookups used for fast trade resolution.

    Trading days are the sessions PRESENT IN THE DATA (a session missing from the data, e.g. 2007-07-02, is not counted).

    Args:
        complete_ohlcv_pdf_in (pd.DataFrame): Minute OHLCV data with timestamp (New York timezone), open, high, low, close columns

    Returns:
        dict: {
            "timestamp_index": pd.DatetimeIndex of every bar,
            "open_arr", "high_arr", "low_arr", "close_arr": np.ndarray of prices,
            "bar_session_idx_arr": session position of every bar,
            "session_date_list": sorted list of session dates (datetime.date),
            "session_start_idx_arr", "session_end_idx_arr": first and last bar index of every session,
            "date_session_idx_dict": session date -> session position
        }
    """
    # SORT THE DATAFRAME BY TIMESTAMP
    ohlcv_pdf = complete_ohlcv_pdf_in.sort_values("timestamp").reset_index(drop=True)
    # COLLECT THE TIMESTAMP INDEX
    timestamp_index = pd.DatetimeIndex(ohlcv_pdf["timestamp"])
    # COLLECT THE SESSION DATE OF EVERY BAR
    bar_date_arr = np.array(timestamp_index.date)
    # COLLECT THE UNIQUE SESSION DATES AND THE SESSION POSITION OF EVERY BAR
    session_date_arr, bar_session_idx_arr = np.unique(bar_date_arr, return_inverse=True)
    # COLLECT THE FIRST AND LAST BAR INDEX OF EVERY SESSION
    session_start_idx_arr = np.searchsorted(bar_session_idx_arr, np.arange(len(session_date_arr)), side="left")
    session_end_idx_arr = np.searchsorted(bar_session_idx_arr, np.arange(len(session_date_arr)), side="right") - 1
    # RETURN THE DICTIONARY
    return {
        "timestamp_index": timestamp_index,
        "open_arr": ohlcv_pdf["open"].to_numpy(dtype=float),
        "high_arr": ohlcv_pdf["high"].to_numpy(dtype=float),
        "low_arr": ohlcv_pdf["low"].to_numpy(dtype=float),
        "close_arr": ohlcv_pdf["close"].to_numpy(dtype=float),
        "bar_session_idx_arr": bar_session_idx_arr,
        "session_date_list": list(session_date_arr),
        "session_start_idx_arr": session_start_idx_arr,
        "session_end_idx_arr": session_end_idx_arr,
        "date_session_idx_dict": {date_object: idx for idx, date_object in enumerate(session_date_arr)},
    }

# FUNCTION: GET THE BAR INDEX OF A LIST OF TIMESTAMPS
def get_ts_bar_idx_arr(ohlcv_array_dict_in, ts_list_in):
    """
    Finds the bar index of each timestamp (-1 when the timestamp is not in the data).

    Args:
        ohlcv_array_dict_in (dict): Output of get_ohlcv_array_dict
        ts_list_in (list | pd.Series | pd.DatetimeIndex): Timestamps (New York timezone)

    Returns:
        np.ndarray: Bar indexes (int)
    """
    # RETURN THE BAR INDEXES
    return ohlcv_array_dict_in["timestamp_index"].get_indexer(pd.DatetimeIndex(ts_list_in))

# FUNCTION: GET THE HOLDING WINDOW OF AN ENTRY
def get_horizon_window_dict(ohlcv_array_dict_in, entry_idx_in, max_hold_trading_days_in=config.MAX_HOLD_TRADING_DAYS):
    """
    Computes the bars on which the SL and TP of an entry are active.

    The SL/TP become active on the bar after the entry bar and stay active until the last bar of the
    MAX_HOLD_TRADING_DAYS-th session (the entry session is day 1).

    Args:
        ohlcv_array_dict_in (dict): Output of get_ohlcv_array_dict
        entry_idx_in (int): Bar index of the entry bar (filled at its open)
        max_hold_trading_days_in (int): Maximum holding period in trading days

    Returns:
        dict: {
            "active_start_idx": first bar where SL/TP are active (entry_idx + 1),
            "horizon_end_idx": last bar of the holding window (or the last bar of the data),
            "horizon_complete": True if the data contains the full holding window
        }
    """
    # COLLECT THE ENTRY SESSION POSITION
    entry_session_idx = ohlcv_array_dict_in["bar_session_idx_arr"][entry_idx_in]
    # CALCULATE THE LAST SESSION OF THE HOLDING WINDOW
    end_session_idx = entry_session_idx + max_hold_trading_days_in - 1
    # COLLECT THE SESSION COUNT
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    # IF THE DATA CONTAINS THE FULL HOLDING WINDOW
    if end_session_idx < session_count:
        # SET THE HORIZON END TO THE LAST BAR OF THE LAST HOLDING SESSION
        horizon_end_idx, horizon_complete = int(ohlcv_array_dict_in["session_end_idx_arr"][end_session_idx]), True
    # IF THE DATA ENDS BEFORE THE HOLDING WINDOW ENDS
    else:
        # SET THE HORIZON END TO THE LAST BAR OF THE DATA
        horizon_end_idx, horizon_complete = len(ohlcv_array_dict_in["close_arr"]) - 1, False
    # RETURN THE DICTIONARY
    return {"active_start_idx": int(entry_idx_in) + 1,
            "horizon_end_idx": horizon_end_idx,
            "horizon_complete": horizon_complete}

"""
Barrier Prices And Exit Resolution
"""

# FUNCTION: GET THE STOP LOSS AND TAKE PROFIT PRICES
def get_barrier_price_dict(entry_price_float_in, delta_arr_in, rr_ratio_float_in=config.RR_RATIO, decimals_int_in=config.SLTP_PRICE_DECIMALS):
    """
    Calculates the stop loss and take profit prices for one or many deltas.

    TP = entry * (1 + delta), SL = entry * (1 - delta * rr_ratio), both rounded to decimals_int_in.

    Args:
        entry_price_float_in (float): Entry price (the open of the entry bar, before slippage)
        delta_arr_in (float | array-like): Take profit distance(s) as a fraction of the entry price
        rr_ratio_float_in (float): Stop loss distance / take profit distance
        decimals_int_in (int): Rounding decimals

    Returns:
        dict: {"stop_loss_arr": np.ndarray, "take_profit_arr": np.ndarray}
    """
    # CONVERT THE DELTA INPUT TO AN ARRAY
    delta_arr = np.atleast_1d(np.asarray(delta_arr_in, dtype=float))
    # CALCULATE THE TAKE PROFIT AND STOP LOSS PRICES
    take_profit_arr = np.round(entry_price_float_in * (1 + delta_arr), decimals_int_in)
    stop_loss_arr = np.round(entry_price_float_in * (1 - delta_arr * rr_ratio_float_in), decimals_int_in)
    # RETURN THE DICTIONARY
    return {"stop_loss_arr": stop_loss_arr, "take_profit_arr": take_profit_arr}

# FUNCTION: RESOLVE THE EXIT OF ONE OR MANY BARRIER PAIRS ON AN ACTIVE WINDOW
def resolve_barrier_exit_dict(open_arr_in, high_arr_in, low_arr_in, close_arr_in,
                              stop_loss_arr_in, take_profit_arr_in, horizon_complete_bool_in,
                              tp_through_float_in=config.TP_THROUGH_TICKS * config.PRICE_TICK):
    """
    Finds the first exit of each (SL, TP) pair on the bars where the barriers are active.

    The input arrays must contain ONLY the active window (first element = first bar where SL/TP are active,
    last element = last bar of the holding window). Exit rules, per bar, in order:
        1. bar opens at or below SL                     -> "SL" at the bar's open
        2. bar opens at or above TP + tp_through        -> "TP" at the bar's open
        3. low <= SL                                    -> "SL" at SL (SL wins if TP is also hit on the bar)
        4. high >= TP + tp_through                      -> "TP" at TP
    If no barrier is hit:
        - horizon complete   -> "TL" (time limit) at the close of the last bar
        - horizon incomplete -> "NA" (unresolved, the data ends first), price NaN

    Args:
        open_arr_in, high_arr_in, low_arr_in, close_arr_in (np.ndarray): Active window prices
        stop_loss_arr_in (np.ndarray): Stop loss prices (one per barrier pair)
        take_profit_arr_in (np.ndarray): Take profit prices (one per barrier pair)
        horizon_complete_bool_in (bool): True if the active window reaches the end of the holding period
        tp_through_float_in (float): Distance the price must trade beyond TP for the limit order to fill

    Returns:
        dict: {
            "exit_offset_arr": bar offset within the active window (-1 if unresolved),
            "exit_price_arr": raw exit price before slippage (NaN if unresolved),
            "exit_reason_arr": "TP" / "SL" / "TL" / "NA"
        }
    """
    # CONVERT THE BARRIERS TO ARRAYS
    stop_loss_arr = np.atleast_1d(np.asarray(stop_loss_arr_in, dtype=float))
    take_profit_arr = np.atleast_1d(np.asarray(take_profit_arr_in, dtype=float))
    # CALCULATE THE TAKE PROFIT TRIGGER (ROUNDED TO AVOID FLOATING POINT ERRORS)
    tp_trigger_arr = np.round(take_profit_arr + tp_through_float_in, 6)
    # COLLECT THE NUMBER OF BARRIER PAIRS AND ACTIVE BARS
    pair_count, bar_count = len(stop_loss_arr), len(open_arr_in)
    # PRE-DEFINE THE OUTPUT ARRAYS (UNRESOLVED BY DEFAULT)
    exit_offset_arr = np.full(pair_count, -1, dtype=int)
    exit_price_arr = np.full(pair_count, np.nan)
    exit_reason_arr = np.full(pair_count, config.EXIT_REASON_NA, dtype=object)
    # IF THERE ARE ACTIVE BARS
    if bar_count > 0:
        # FLAG THE BARS WHERE EACH BARRIER IS HIT (pair_count x bar_count)
        sl_hit_arr = low_arr_in[None, :] <= stop_loss_arr[:, None]
        tp_hit_arr = high_arr_in[None, :] >= tp_trigger_arr[:, None]
        any_hit_arr = sl_hit_arr | tp_hit_arr
        # COLLECT THE PAIRS WITH AT LEAST ONE HIT AND THE FIRST HIT BAR
        has_hit_arr = any_hit_arr.any(axis=1)
        first_hit_arr = any_hit_arr.argmax(axis=1)
        # ITERATE OVER THE PAIRS WITH A HIT
        for pair_idx in np.flatnonzero(has_hit_arr):
            # COLLECT THE FIRST HIT BAR AND ITS OPEN
            bar_idx = first_hit_arr[pair_idx]
            bar_open = open_arr_in[bar_idx]
            # IF THE BAR OPENS AT OR BELOW THE STOP LOSS (GAP THROUGH THE STOP)
            if bar_open <= stop_loss_arr[pair_idx]:
                exit_price, exit_reason = bar_open, config.EXIT_REASON_SL
            # IF THE BAR OPENS AT OR ABOVE THE TAKE PROFIT TRIGGER (GAP THROUGH THE TARGET)
            elif bar_open >= tp_trigger_arr[pair_idx]:
                exit_price, exit_reason = bar_open, config.EXIT_REASON_TP
            # IF THE STOP LOSS IS HIT DURING THE BAR (STOP LOSS PRIORITY)
            elif sl_hit_arr[pair_idx, bar_idx]:
                exit_price, exit_reason = stop_loss_arr[pair_idx], config.EXIT_REASON_SL
            # IF ONLY THE TAKE PROFIT IS HIT DURING THE BAR
            else:
                exit_price, exit_reason = take_profit_arr[pair_idx], config.EXIT_REASON_TP
            # SET THE OUTPUT VALUES
            exit_offset_arr[pair_idx] = bar_idx
            exit_price_arr[pair_idx] = exit_price
            exit_reason_arr[pair_idx] = exit_reason
        # IF THE HOLDING WINDOW IS COMPLETE
        if horizon_complete_bool_in:
            # COLLECT THE PAIRS WITHOUT A HIT
            no_hit_arr = ~has_hit_arr
            # SET THE TIME LIMIT EXIT AT THE CLOSE OF THE LAST BAR
            exit_offset_arr[no_hit_arr] = bar_count - 1
            exit_price_arr[no_hit_arr] = close_arr_in[-1]
            exit_reason_arr[no_hit_arr] = config.EXIT_REASON_TL
    # RETURN THE DICTIONARY
    return {"exit_offset_arr": exit_offset_arr,
            "exit_price_arr": exit_price_arr,
            "exit_reason_arr": exit_reason_arr}

# FUNCTION: RESOLVE THE TRADE OUTCOMES OF AN ENTRY FOR A LIST OF DELTAS
def resolve_entry_trade_dict(ohlcv_array_dict_in, entry_idx_in, delta_arr_in, rr_ratio_float_in=config.RR_RATIO):
    """
    Resolves the exits of an entry at the open of bar entry_idx_in for one or many deltas.

    Args:
        ohlcv_array_dict_in (dict): Output of get_ohlcv_array_dict
        entry_idx_in (int): Bar index of the entry bar
        delta_arr_in (float | array-like): Take profit distance(s) as a fraction of the entry price
        rr_ratio_float_in (float): Stop loss distance / take profit distance

    Returns:
        dict: {
            "entry_idx", "entry_price" (raw open), "horizon_complete",
            "stop_loss_arr", "take_profit_arr",
            "exit_idx_arr" (global bar index, -1 if unresolved), "exit_price_arr", "exit_reason_arr",
            "exit_bar_count_arr" (bars from the entry bar to the exit bar, -1 if unresolved)
        }
    """
    # COLLECT THE ENTRY PRICE (OPEN OF THE ENTRY BAR)
    entry_price = float(ohlcv_array_dict_in["open_arr"][entry_idx_in])
    # COLLECT THE HOLDING WINDOW
    horizon_dict = get_horizon_window_dict(ohlcv_array_dict_in, entry_idx_in)
    # DEFINE THE ACTIVE WINDOW SLICE
    active_slice = slice(horizon_dict["active_start_idx"], horizon_dict["horizon_end_idx"] + 1)
    # CALCULATE THE BARRIER PRICES
    barrier_dict = get_barrier_price_dict(entry_price, delta_arr_in, rr_ratio_float_in)
    # RESOLVE THE EXITS
    exit_dict = resolve_barrier_exit_dict(ohlcv_array_dict_in["open_arr"][active_slice],
                                          ohlcv_array_dict_in["high_arr"][active_slice],
                                          ohlcv_array_dict_in["low_arr"][active_slice],
                                          ohlcv_array_dict_in["close_arr"][active_slice],
                                          barrier_dict["stop_loss_arr"],
                                          barrier_dict["take_profit_arr"],
                                          horizon_dict["horizon_complete"])
    # CONVERT THE OFFSETS TO GLOBAL BAR INDEXES
    resolved_arr = exit_dict["exit_offset_arr"] >= 0
    exit_idx_arr = np.where(resolved_arr, exit_dict["exit_offset_arr"] + horizon_dict["active_start_idx"], -1)
    # RETURN THE DICTIONARY
    return {"entry_idx": int(entry_idx_in),
            "entry_price": entry_price,
            "horizon_complete": horizon_dict["horizon_complete"],
            "stop_loss_arr": barrier_dict["stop_loss_arr"],
            "take_profit_arr": barrier_dict["take_profit_arr"],
            "exit_idx_arr": exit_idx_arr,
            "exit_price_arr": exit_dict["exit_price_arr"],
            "exit_reason_arr": exit_dict["exit_reason_arr"],
            "exit_bar_count_arr": np.where(resolved_arr, exit_idx_arr - int(entry_idx_in), -1)}

"""
Costs, Fees And Returns
"""

# FUNCTION: CALCULATE THE FEE OF ONE ORDER SIDE
def calculate_side_fee(share_count_int_in, share_price_float_in,
                       fee_per_share_in=config.FEE_PER_SHARE_PER_SIDE,
                       fee_minimum_in=config.FEE_MINIMUM_PER_SIDE,
                       fee_maximum_pct_in=config.FEE_MAXIMUM_PCT_PER_SIDE):
    """
    Calculates the IBKR fixed fee of one order side (a buy or a sell).

    Same rule as calculate_transaction_fee of the previous trading_simulation.py, applied per side so that the sell side uses the sell price:
    fee = shares * fee_per_share, at least fee_minimum, at most fee_maximum_pct of the side's trade value
    (the minimum takes precedence, as in the original function).

    Args:
        share_count_int_in (int): Number of shares in the order
        share_price_float_in (float): Fill price of the order
        fee_per_share_in (float): Fee per share
        fee_minimum_in (float): Minimum fee per order
        fee_maximum_pct_in (float): Maximum fee as a fraction of the trade value

    Returns:
        float: Fee in dollars (0 if no shares)
    """
    # IF THERE ARE NO SHARES
    if share_count_int_in <= 0:
        # RETURN NO FEE
        return 0.0
    # CALCULATE THE PER SHARE FEE TOTAL
    fee = share_count_int_in * fee_per_share_in
    # CALCULATE THE MAXIMUM FEE
    maximum_fee = share_count_int_in * share_price_float_in * fee_maximum_pct_in
    # IF THE FEE IS BELOW THE MINIMUM
    if fee < fee_minimum_in:
        # SET THE MINIMUM FEE
        fee = fee_minimum_in
    # IF THE FEE IS ABOVE THE MAXIMUM
    elif fee > maximum_fee:
        # SET THE MAXIMUM FEE
        fee = maximum_fee
    # RETURN THE FEE
    return round(fee, 6)

# FUNCTION: GET THE AFFORDABLE SHARE COUNT
def get_affordable_share_count(cash_float_in, entry_fill_price_float_in, fee_per_share_in=config.FEE_PER_SHARE_PER_SIDE):
    """
    Finds the largest whole number of shares whose cost plus buy fee fits within the available cash.

    "Optimal number of shares" (decided 2026-10-01): the whole account is invested in every trade (compounding).

    Args:
        cash_float_in (float): Available cash
        entry_fill_price_float_in (float): Entry fill price per share (open + entry slippage)
        fee_per_share_in (float): Fee per share (used for the first estimate)

    Returns:
        int: Share count (0 if nothing is affordable)
    """
    # IF THE PRICE IS NOT POSITIVE
    if entry_fill_price_float_in <= 0:
        # RETURN ZERO SHARES
        return 0
    # ESTIMATE THE SHARE COUNT
    share_count = int(np.floor(cash_float_in / (entry_fill_price_float_in + fee_per_share_in)))
    # WHILE THE COST PLUS FEE IS ABOVE THE CASH
    while share_count > 0 and share_count * entry_fill_price_float_in + calculate_side_fee(share_count, entry_fill_price_float_in) > cash_float_in:
        # REDUCE THE SHARE COUNT
        share_count -= 1
    # RETURN THE SHARE COUNT
    return share_count

# FUNCTION: GET THE EXIT SLIPPAGE OF AN EXIT REASON
def get_exit_slippage_arr(exit_reason_arr_in,
                          market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                          limit_exit_slippage_in=config.LIMIT_EXIT_SLIPPAGE_PER_SHARE):
    """
    Returns the per share exit slippage of each exit reason (TP = limit order, every other exit = market order).

    Args:
        exit_reason_arr_in (array-like): Exit reasons
        market_exit_slippage_in (float): Slippage of market exits (SL, TL, END)
        limit_exit_slippage_in (float): Slippage of limit exits (TP)

    Returns:
        np.ndarray: Slippage per share
    """
    # CONVERT THE EXIT REASONS TO AN ARRAY
    exit_reason_arr = np.atleast_1d(np.asarray(exit_reason_arr_in, dtype=object))
    # RETURN THE SLIPPAGE ARRAY
    return np.where(exit_reason_arr == config.EXIT_REASON_TP, limit_exit_slippage_in, market_exit_slippage_in)

# FUNCTION: GET THE NET RETURN PER SHARE OF ONE OR MANY TRADES
def get_net_return_arr(entry_price_arr_in, exit_price_arr_in, exit_reason_arr_in,
                       entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                       market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                       limit_exit_slippage_in=config.LIMIT_EXIT_SLIPPAGE_PER_SHARE,
                       fee_per_share_in=config.FEE_PER_SHARE_PER_SIDE):
    """
    Calculates the net return (fraction of the entry fill) of trades using per share costs.

    Per share approximation used by labels and the signal check: the fee is fee_per_share on each side, which is exact
    whenever the order is large enough that the minimum fee does not bind (>= 200 shares at $0.005) and the 1% cap does not bind.
    The simulator uses exact order fees instead (calculate_side_fee).

    Args:
        entry_price_arr_in (array-like): Raw entry prices (open of the entry bar)
        exit_price_arr_in (array-like): Raw exit prices (NaN for unresolved trades)
        exit_reason_arr_in (array-like): Exit reasons
        entry_slippage_in, market_exit_slippage_in, limit_exit_slippage_in (float): Slippage per share
        fee_per_share_in (float): Fee per share per side

    Returns:
        np.ndarray: Net return per trade (NaN for unresolved trades)
    """
    # CALCULATE THE ENTRY FILL PRICE
    entry_fill_arr = np.asarray(entry_price_arr_in, dtype=float) + entry_slippage_in
    # CALCULATE THE EXIT FILL PRICE
    exit_fill_arr = np.asarray(exit_price_arr_in, dtype=float) - get_exit_slippage_arr(exit_reason_arr_in, market_exit_slippage_in, limit_exit_slippage_in)
    # RETURN THE NET RETURN
    return (exit_fill_arr - entry_fill_arr - 2 * fee_per_share_in) / entry_fill_arr

# FUNCTION: GET THE BREAKEVEN TAKE PROFIT RATE
def get_breakeven_tp_rate_arr(entry_price_arr_in, delta_float_in, rr_ratio_float_in=config.RR_RATIO,
                              entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                              market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                              limit_exit_slippage_in=config.LIMIT_EXIT_SLIPPAGE_PER_SHARE,
                              fee_per_share_in=config.FEE_PER_SHARE_PER_SIDE):
    """
    Calculates the take profit rate needed to break even after costs, assuming exits fill exactly at the barriers.

    win  = (TP - limit_slippage) - (entry + entry_slippage) - 2 * fee
    loss = (entry + entry_slippage) - (SL - market_slippage) + 2 * fee
    breakeven TP rate = loss / (win + loss)    (1.0 if a win cannot cover its costs)

    Note: gaps through the stop loss make real losses larger, and time limit exits are ignored, so this is an optimistic
    (lower) breakeven.

    Args:
        entry_price_arr_in (array-like): Entry prices
        delta_float_in (float): Take profit distance as a fraction of the entry price
        rr_ratio_float_in (float): Stop loss distance / take profit distance
        entry_slippage_in, market_exit_slippage_in, limit_exit_slippage_in (float): Slippage per share
        fee_per_share_in (float): Fee per share per side

    Returns:
        np.ndarray: Breakeven take profit rate per entry price
    """
    # CONVERT THE ENTRY PRICES TO AN ARRAY
    entry_price_arr = np.atleast_1d(np.asarray(entry_price_arr_in, dtype=float))
    # CALCULATE THE BARRIER PRICES
    take_profit_arr = np.round(entry_price_arr * (1 + delta_float_in), config.SLTP_PRICE_DECIMALS)
    stop_loss_arr = np.round(entry_price_arr * (1 - delta_float_in * rr_ratio_float_in), config.SLTP_PRICE_DECIMALS)
    # CALCULATE THE ENTRY FILL PRICE
    entry_fill_arr = entry_price_arr + entry_slippage_in
    # CALCULATE THE WIN AND LOSS PER SHARE
    win_arr = (take_profit_arr - limit_exit_slippage_in) - entry_fill_arr - 2 * fee_per_share_in
    loss_arr = entry_fill_arr - (stop_loss_arr - market_exit_slippage_in) + 2 * fee_per_share_in
    # RETURN THE BREAKEVEN RATE (1.0 WHEN A WIN CANNOT COVER ITS COSTS)
    return np.where(win_arr > 0, loss_arr / (win_arr + loss_arr), 1.0)

# FUNCTION: GET THE EXPECTED NET RETURN OF A TAKE PROFIT PROBABILITY
def get_expected_net_return_arr(tp_proba_arr_in, price_arr_in, delta_float_in, rr_ratio_float_in=config.RR_RATIO,
                                entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                                market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                                limit_exit_slippage_in=config.LIMIT_EXIT_SLIPPAGE_PER_SHARE,
                                fee_per_share_in=config.FEE_PER_SHARE_PER_SIDE):
    """
    Calculates the expected net return of entering at price_arr_in when the take profit is hit with probability p
    and the stop loss otherwise (time limit exits are treated as stop losses: conservative).

    IMPORTANT: at decision time the entry open is unknown. Callers must pass a price known at the decision bar
    (the decision bar's close), never the entry open.

    Args:
        tp_proba_arr_in (array-like): Probability of a take profit exit
        price_arr_in (array-like): Price known at decision time (decision bar close)
        delta_float_in (float): Take profit distance
        rr_ratio_float_in (float): Stop loss distance / take profit distance
        entry_slippage_in, market_exit_slippage_in, limit_exit_slippage_in (float): Slippage per share
        fee_per_share_in (float): Fee per share per side

    Returns:
        np.ndarray: Expected net return (fraction of the entry fill)
    """
    # CONVERT THE INPUTS TO ARRAYS
    tp_proba_arr = np.asarray(tp_proba_arr_in, dtype=float)
    price_arr = np.asarray(price_arr_in, dtype=float)
    # CALCULATE THE BARRIER PRICES
    take_profit_arr = np.round(price_arr * (1 + delta_float_in), config.SLTP_PRICE_DECIMALS)
    stop_loss_arr = np.round(price_arr * (1 - delta_float_in * rr_ratio_float_in), config.SLTP_PRICE_DECIMALS)
    # CALCULATE THE ENTRY FILL PRICE
    entry_fill_arr = price_arr + entry_slippage_in
    # CALCULATE THE WIN AND LOSS RETURNS
    win_return_arr = ((take_profit_arr - limit_exit_slippage_in) - entry_fill_arr - 2 * fee_per_share_in) / entry_fill_arr
    loss_return_arr = ((stop_loss_arr - market_exit_slippage_in) - entry_fill_arr - 2 * fee_per_share_in) / entry_fill_arr
    # RETURN THE EXPECTED NET RETURN
    return tp_proba_arr * win_return_arr + (1 - tp_proba_arr) * loss_return_arr

# FUNCTION: GET THE RESULT LABEL OF A TRADE
def get_trade_result_str(net_profit_float_in, tolerance_float_in=config.RESULT_NULL_TOLERANCE):
    """
    Labels a trade by its net profit after costs: WIN (> 0), LOSS (< 0) or NULL (zero within the tolerance).

    Args:
        net_profit_float_in (float): Net profit in dollars after all costs
        tolerance_float_in (float): Absolute profit treated as zero

    Returns:
        str: "WIN", "LOSS" or "NULL"
    """
    # IF THE PROFIT IS ZERO WITHIN THE TOLERANCE
    if abs(net_profit_float_in) < tolerance_float_in:
        # RETURN NULL
        return config.RESULT_NULL
    # RETURN WIN OR LOSS
    return config.RESULT_WIN if net_profit_float_in > 0 else config.RESULT_LOSS
