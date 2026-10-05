import pandas as pd
import numpy as np
from datetime import timedelta
# IMPORT EXPERIMENT CONFIGURATION
from so import config
# IMPORT TRADE EXECUTION FUNCTIONS (single source of truth for the exit rules and costs)
from so.core.trade_execution import get_ts_bar_idx_arr, \
                            resolve_entry_trade_dict, \
                            calculate_side_fee, \
                            get_affordable_share_count, \
                            get_exit_slippage_arr, \
                            get_trade_result_str

"""
Backtest Simulation

Replaces the intraday TradingAgent loop (trading_simulation.py of the previous workspace, not included here) for the
redesigned experiment:
    - one position at a time, long only, the whole account is invested in every trade (compounding);
    - a decision at bar t enters at the open of bar t+1 of the same session;
    - exits follow trade_execution.resolve_entry_trade_dict (identical to the TSBAR target matrix);
    - positions can be held across sessions up to MAX_HOLD_TRADING_DAYS;
    - slippage and IBKR fixed fees per side are charged; idle cash earns CASH_INTEREST_RATE (0).

Decision DataFrame format (input of every simulation):
    decision_ts (timestamp), buy_flag (bool), delta (float)
"""

# FUNCTION: SIMULATE TRADING FROM A DECISION DATAFRAME
def simulate_decision_trading_dict(decision_pdf_in, ohlcv_array_dict_in, initial_capital_in=config.INITIAL_CAPITAL,
                                   rr_ratio_float_in=config.RR_RATIO,
                                   entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                                   market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE,
                                   limit_exit_slippage_in=config.LIMIT_EXIT_SLIPPAGE_PER_SHARE,
                                   alert_in=False):
    """
    Simulates a single-position, compounding account that follows the buy decisions of decision_pdf_in.

    Buy decisions are skipped while a position is open. A position closed on bar j (intrabar or at its close) allows a
    new decision on bar j (entry at the open of bar j+1). If the data ends before a trade is resolved, the position is
    closed at the close of the last bar of the data with exit reason "END".

    Args:
        decision_pdf_in (pd.DataFrame): Columns decision_ts, buy_flag, delta
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict (complete data)
        initial_capital_in (float): Starting cash
        rr_ratio_float_in (float): Stop loss distance / take profit distance
        entry_slippage_in (float): Dollars per share added to the entry open
        market_exit_slippage_in (float): Dollars per share subtracted on SL / TL / END exits
        limit_exit_slippage_in (float): Dollars per share subtracted on TP exits
        alert_in (bool): Display every trade

    Returns:
        dict: {"transaction_pdf": one row per trade, "skipped_decision_count": buys ignored because a position was open}
    """
    # COLLECT THE BUY DECISIONS SORTED BY TIME
    buy_pdf = decision_pdf_in[decision_pdf_in["buy_flag"].astype(bool)].sort_values("decision_ts").reset_index(drop=True)
    # COLLECT THE DECISION BAR INDEXES
    decision_idx_arr = get_ts_bar_idx_arr(ohlcv_array_dict_in, buy_pdf["decision_ts"]) if not buy_pdf.empty else np.array([], dtype=int)
    # DEFINE THE LAST BAR INDEX OF THE DATA
    last_bar_idx = len(ohlcv_array_dict_in["close_arr"]) - 1
    # DEFINE THE ACCOUNT STATE
    cash, next_free_idx, skipped_decision_count = float(initial_capital_in), -1, 0
    # LIST TO HOLD THE TRANSACTIONS
    transaction_dict_list = []
    # ITERATE OVER THE BUY DECISIONS
    for row_idx, decision_idx in enumerate(decision_idx_arr):
        # IF THE DECISION BAR IS NOT IN THE DATA OR IT IS THE LAST BAR OF THE DATA
        if decision_idx < 0 or decision_idx >= last_bar_idx:
            # SKIP THE DECISION
            continue
        # IF A POSITION IS STILL OPEN AT THE DECISION BAR
        if decision_idx < next_free_idx:
            # COUNT AND SKIP THE DECISION
            skipped_decision_count += 1
            continue
        # DEFINE THE ENTRY BAR
        entry_idx = decision_idx + config.DECISION_TO_ENTRY_BAR_OFFSET
        # IF THE ENTRY BAR IS IN ANOTHER SESSION (A LAST-BAR SIGNAL CANNOT BUY AT THE NEXT OPEN)
        if ohlcv_array_dict_in["bar_session_idx_arr"][entry_idx] != ohlcv_array_dict_in["bar_session_idx_arr"][decision_idx]:
            # SKIP THE DECISION
            continue
        # COLLECT THE DELTA
        delta = float(buy_pdf.loc[row_idx, "delta"])
        # RESOLVE THE TRADE (SAME FUNCTION AS THE TSBAR TARGET MATRIX)
        trade_dict = resolve_entry_trade_dict(ohlcv_array_dict_in, entry_idx, [delta], rr_ratio_float_in)
        # COLLECT THE EXIT
        exit_idx = int(trade_dict["exit_idx_arr"][0])
        exit_price = float(trade_dict["exit_price_arr"][0])
        exit_reason = trade_dict["exit_reason_arr"][0]
        # IF THE TRADE IS UNRESOLVED BECAUSE THE DATA ENDS
        if exit_reason == config.EXIT_REASON_NA:
            # CLOSE AT THE LAST BAR OF THE DATA
            exit_idx, exit_price, exit_reason = last_bar_idx, float(ohlcv_array_dict_in["close_arr"][last_bar_idx]), config.EXIT_REASON_END
        # CALCULATE THE ENTRY FILL PRICE AND THE SHARE COUNT
        entry_fill_price = trade_dict["entry_price"] + entry_slippage_in
        share_count = get_affordable_share_count(cash, entry_fill_price)
        # IF NO SHARE IS AFFORDABLE
        if share_count <= 0:
            # DISPLAY INFORMATION
            print(f"⚠️ No affordable shares at {buy_pdf.loc[row_idx, 'decision_ts']} (cash: {cash:.2f})") if alert_in else None
            # STOP THE SIMULATION
            break
        # CALCULATE THE EXIT FILL PRICE
        exit_fill_price = exit_price - float(get_exit_slippage_arr([exit_reason], market_exit_slippage_in, limit_exit_slippage_in)[0])
        # CALCULATE THE FEES
        buy_fee = calculate_side_fee(share_count, entry_fill_price)
        sell_fee = calculate_side_fee(share_count, exit_fill_price)
        # CALCULATE THE NET PROFIT
        net_profit = share_count * (exit_fill_price - entry_fill_price) - buy_fee - sell_fee
        # UPDATE THE CASH
        cash_before = cash
        cash = cash + net_profit
        # DEFINE THE TRANSACTION DICTIONARY
        transaction_dict = {
            "transaction_id": len(transaction_dict_list),
            "decision_ts": buy_pdf.loc[row_idx, "decision_ts"],
            "buy_ts": ohlcv_array_dict_in["timestamp_index"][entry_idx],
            "buy_open_price": trade_dict["entry_price"],
            "buy_fill_price": round(entry_fill_price, 6),
            "share_count": share_count,
            "delta": delta,
            "SL_price": float(trade_dict["stop_loss_arr"][0]),
            "TP_price": float(trade_dict["take_profit_arr"][0]),
            "sell_ts": ohlcv_array_dict_in["timestamp_index"][exit_idx],
            "sell_raw_price": round(exit_price, 6),
            "sell_fill_price": round(exit_fill_price, 6),
            "exit_reason": exit_reason,
            "buy_fee": buy_fee,
            "sell_fee": sell_fee,
            "net_profit": round(net_profit, 6),
            "net_profit_pct": round(net_profit / cash_before, 8),
            "result": get_trade_result_str(net_profit),
            "hold_bar_count": exit_idx - entry_idx,
            "buy_idx": entry_idx,
            "sell_idx": exit_idx,
            "equity_after": round(cash, 6),
        }
        # APPEND THE TRANSACTION
        transaction_dict_list.append(transaction_dict)
        # DISPLAY INFORMATION
        print(f"🛒 {transaction_dict['buy_ts']} -> 💰 {transaction_dict['sell_ts']}\t{exit_reason}\tnet: {net_profit:.2f}") if alert_in else None
        # SET THE NEXT FREE BAR (A NEW DECISION IS ALLOWED ON THE EXIT BAR)
        next_free_idx = exit_idx
    # RETURN THE DICTIONARY
    return {"transaction_pdf": pd.DataFrame(transaction_dict_list), "skipped_decision_count": skipped_decision_count}

# FUNCTION: GET THE DAILY EQUITY CURVE OF A SIMULATION
def get_daily_equity_pdf(transaction_pdf_in, ohlcv_array_dict_in, date1_str_in, date2_str_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Marks the account to market at the close of every session from date1 to the later of date2 and the last exit.

    Open positions are valued at the session close minus the entry cost and the buy fee (sell costs are only charged
    when the position is actually closed).

    Args:
        transaction_pdf_in (pd.DataFrame): Output transaction_pdf of a simulation
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        date1_str_in (str): First session (inclusive)
        date2_str_in (str): Last session of the evaluation window (inclusive)
        initial_capital_in (float): Starting cash

    Returns:
        pd.DataFrame: Columns date, equity, in_position
    """
    # COLLECT THE SESSION DATES
    session_date_list = ohlcv_array_dict_in["session_date_list"]
    # CONVERT THE DATE BOUNDS
    date1_object, date2_object = pd.to_datetime(date1_str_in).date(), pd.to_datetime(date2_str_in).date()
    # IF THERE ARE TRANSACTIONS
    if transaction_pdf_in is not None and not transaction_pdf_in.empty:
        # EXTEND THE LAST DATE TO THE LAST EXIT
        date2_object = max(date2_object, pd.Timestamp(transaction_pdf_in["sell_ts"].max()).date())
    # COLLECT THE SESSION POSITIONS IN THE RANGE
    session_idx_list = [idx for idx, date_object in enumerate(session_date_list) if date1_object <= date_object <= date2_object]
    # COLLECT THE TRANSACTION ARRAYS
    has_transactions = transaction_pdf_in is not None and not transaction_pdf_in.empty
    buy_idx_arr = transaction_pdf_in["buy_idx"].to_numpy() if has_transactions else np.array([], dtype=int)
    sell_idx_arr = transaction_pdf_in["sell_idx"].to_numpy() if has_transactions else np.array([], dtype=int)
    net_profit_arr = transaction_pdf_in["net_profit"].to_numpy() if has_transactions else np.array([])
    # LIST TO HOLD THE EQUITY ROWS
    equity_dict_list = []
    # ITERATE OVER THE SESSIONS
    for session_idx in session_idx_list:
        # COLLECT THE LAST BAR OF THE SESSION
        end_idx = ohlcv_array_dict_in["session_end_idx_arr"][session_idx]
        # CALCULATE THE REALIZED CASH (TRADES CLOSED AT OR BEFORE THE SESSION CLOSE)
        cash = initial_capital_in + net_profit_arr[sell_idx_arr <= end_idx].sum()
        # FIND A TRADE OPEN AT THE SESSION CLOSE
        open_mask = (buy_idx_arr <= end_idx) & (sell_idx_arr > end_idx)
        # PRE-DEFINE THE UNREALIZED PROFIT
        unrealized_profit, in_position = 0.0, False
        # IF A TRADE IS OPEN
        if open_mask.any():
            # COLLECT THE OPEN TRADE
            open_row = transaction_pdf_in.loc[open_mask].iloc[0]
            # CALCULATE THE UNREALIZED PROFIT AT THE SESSION CLOSE
            unrealized_profit = open_row["share_count"] * (ohlcv_array_dict_in["close_arr"][end_idx] - open_row["buy_fill_price"]) - open_row["buy_fee"]
            in_position = True
        # APPEND THE EQUITY ROW
        equity_dict_list.append({"date": session_date_list[session_idx], "equity": round(cash + unrealized_profit, 6), "in_position": in_position})
    # RETURN DATAFRAME
    return pd.DataFrame(equity_dict_list)

# FUNCTION: GET THE FIRST ENTRY BAR OF A SESSION
def get_session_first_entry_idx(ohlcv_array_dict_in, session_idx_in, start_delay_minutes_in=config.TRADING_START_DELAY_MINUTES):
    """
    Finds the first bar of a session whose timestamp is at or after 09:30 + the start delay (10:00 by default).

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        session_idx_in (int): Session position
        start_delay_minutes_in (int): Minutes after the 09:30 open

    Returns:
        int: Bar index (-1 if the session has no such bar)
    """
    # COLLECT THE SESSION BARS
    start_idx = ohlcv_array_dict_in["session_start_idx_arr"][session_idx_in]
    end_idx = ohlcv_array_dict_in["session_end_idx_arr"][session_idx_in]
    session_ts_index = ohlcv_array_dict_in["timestamp_index"][start_idx:end_idx + 1]
    # CALCULATE THE FIRST ALLOWED ENTRY TIMESTAMP
    first_entry_ts = session_ts_index[0].normalize() + timedelta(hours=9, minutes=30 + start_delay_minutes_in)
    # COLLECT THE ALLOWED BARS
    allowed_idx_arr = np.flatnonzero(session_ts_index >= first_entry_ts)
    # RETURN THE FIRST ALLOWED BAR
    return int(start_idx + allowed_idx_arr[0]) if len(allowed_idx_arr) > 0 else -1

# FUNCTION: SIMULATE BUY AND HOLD OVER A WINDOW
def simulate_buy_and_hold_dict(ohlcv_array_dict_in, date1_str_in, date2_str_in, initial_capital_in=config.INITIAL_CAPITAL,
                               entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                               market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
    """
    Simulates the buy-and-hold benchmark: buy at the first allowed entry of the first session (10:00 open), sell at the
    close of the last bar of the last session, with the same slippage and fees as the model. Dividends are ignored
    (decided 2026-10-01; this understates buy-and-hold).

    Args:
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        date1_str_in (str): First session (inclusive)
        date2_str_in (str): Last session (inclusive)
        initial_capital_in (float): Starting cash
        entry_slippage_in (float): Dollars per share added to the entry open
        market_exit_slippage_in (float): Dollars per share subtracted on the exit

    Returns:
        dict: {"transaction_pdf": one row, "daily_equity_pdf": daily equity curve}
    """
    # CONVERT THE DATE BOUNDS
    date1_object, date2_object = pd.to_datetime(date1_str_in).date(), pd.to_datetime(date2_str_in).date()
    # COLLECT THE SESSION POSITIONS IN THE RANGE
    session_idx_list = [idx for idx, date_object in enumerate(ohlcv_array_dict_in["session_date_list"]) if date1_object <= date_object <= date2_object]
    # IF THERE ARE NO SESSIONS
    if not session_idx_list:
        # RETURN EMPTY RESULTS
        return {"transaction_pdf": pd.DataFrame(), "daily_equity_pdf": pd.DataFrame()}
    # COLLECT THE ENTRY AND EXIT BARS
    entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, session_idx_list[0])
    exit_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx_list[-1]])
    # CALCULATE THE FILL PRICES
    entry_fill_price = ohlcv_array_dict_in["open_arr"][entry_idx] + entry_slippage_in
    exit_fill_price = ohlcv_array_dict_in["close_arr"][exit_idx] - market_exit_slippage_in
    # CALCULATE THE SHARE COUNT AND FEES
    share_count = get_affordable_share_count(initial_capital_in, entry_fill_price)
    buy_fee = calculate_side_fee(share_count, entry_fill_price)
    sell_fee = calculate_side_fee(share_count, exit_fill_price)
    # CALCULATE THE NET PROFIT
    net_profit = share_count * (exit_fill_price - entry_fill_price) - buy_fee - sell_fee
    # DEFINE THE TRANSACTION DATAFRAME
    transaction_pdf = pd.DataFrame([{
        "transaction_id": 0,
        "decision_ts": ohlcv_array_dict_in["timestamp_index"][entry_idx - 1],
        "buy_ts": ohlcv_array_dict_in["timestamp_index"][entry_idx],
        "buy_open_price": ohlcv_array_dict_in["open_arr"][entry_idx],
        "buy_fill_price": round(entry_fill_price, 6),
        "share_count": share_count,
        "delta": np.nan,
        "SL_price": np.nan,
        "TP_price": np.nan,
        "sell_ts": ohlcv_array_dict_in["timestamp_index"][exit_idx],
        "sell_raw_price": ohlcv_array_dict_in["close_arr"][exit_idx],
        "sell_fill_price": round(exit_fill_price, 6),
        "exit_reason": "BH",
        "buy_fee": buy_fee,
        "sell_fee": sell_fee,
        "net_profit": round(net_profit, 6),
        "net_profit_pct": round(net_profit / initial_capital_in, 8),
        "result": get_trade_result_str(net_profit),
        "hold_bar_count": exit_idx - entry_idx,
        "buy_idx": entry_idx,
        "sell_idx": exit_idx,
        "equity_after": round(initial_capital_in + net_profit, 6),
    }])
    # CALCULATE THE DAILY EQUITY CURVE
    daily_equity_pdf = get_daily_equity_pdf(transaction_pdf, ohlcv_array_dict_in, date1_str_in, date2_str_in, initial_capital_in)
    # RETURN THE DICTIONARY
    return {"transaction_pdf": transaction_pdf, "daily_equity_pdf": daily_equity_pdf}
