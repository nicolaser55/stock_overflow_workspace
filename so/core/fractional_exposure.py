import pandas as pd
import numpy as np
# IMPORT THE SHARED CONFIGURATION (COSTS, CAPITAL)
from so import config
# IMPORT TRADE EXECUTION FUNCTIONS (FEES AND SHARE COUNT)
from so.core.trade_execution import calculate_side_fee, get_affordable_share_count
# IMPORT BACKTEST FUNCTIONS (FIRST ENTRY BAR)
from so.core.backtest_simulation import get_session_first_entry_idx
# IMPORT PERFORMANCE METRICS
from so.core.performance_metrics import get_sharpe_ratio, get_max_drawdown
# IMPORT DAILY FEATURE FUNCTIONS (DECISION AND FILL BARS)
from so.features.daily_features import get_session_decision_idx_dict
# IMPORT THE WINDOW SESSION LOOKUP
from so.core.reentry_simulation import get_window_session_idx_arr

"""
Fractional Exposure Simulation (roadmap Step 0, for exp05_vol_scaled_exposure)

The account holds a fraction w in [0, 1] of its equity in SPY and the rest in cash (0% interest). Long only, unlevered:
w never exceeds 1.

    Start         at the 10:00 open of the first session, buy the shares of initial_weight_in (as buy-and-hold does
                  with w = 1)
    Decision      at the 15:58 decision bar of every session except the last: current weight
                  w_now = shares x decision close / (cash + shares x decision close); target w* = target_weight_arr_in of
                  the session (NaN = keep the position)
    Rebalance     only if |w* - w_now| > dead_band_in, at the 15:59 open (fill bar): the target share count is
                  floor(w* x equity at the fill open / fill price); w* >= 1 buys every affordable share, w* <= 0 sells
                  everything. Buys pay ENTRY_SLIPPAGE_PER_SHARE, sells MARKET_EXIT_SLIPPAGE_PER_SHARE, every order pays
                  the IBKR fixed fee of so.core.trade_execution
    End           every share is sold at the last close of the window (market exit slippage and fee)

Daily equity = cash + shares x session close (the same marking as so.core.backtest_simulation.get_daily_equity_pdf), so
w = 1 throughout reproduces buy-and-hold exactly and w = 0 throughout stays at the initial capital.
"""

# FUNCTION: SIMULATE A FRACTIONAL EXPOSURE PATH OVER A WINDOW
def simulate_fractional_exposure_dict(ohlcv_array_dict_in, date1_in, date2_in, target_weight_arr_in, dead_band_in, initial_weight_in,
                                      initial_capital_in=config.INITIAL_CAPITAL,
                                      entry_slippage_in=config.ENTRY_SLIPPAGE_PER_SHARE,
                                      market_exit_slippage_in=config.MARKET_EXIT_SLIPPAGE_PER_SHARE):
    """
    Simulates the rules of the module docstring.

    Args:
        ohlcv_array_dict_in (dict): Output of so.core.trade_execution.get_ohlcv_array_dict
        date1_in, date2_in (datetime.date | str): Window bounds (inclusive)
        target_weight_arr_in (np.ndarray): Target weight decided at the decision bar, per session position (NaN = keep)
        dead_band_in (float): Rebalance only if the target differs from the current weight by more than this
        initial_weight_in (float): Weight bought at the 10:00 open of the first session (the decision of the session
            before the window, chosen by the caller)
        initial_capital_in (float): Starting cash
        entry_slippage_in, market_exit_slippage_in (float): Slippage per share of buys and sells

    Returns:
        dict: trade_pdf (one row per order), daily_equity_pdf (date, equity, in_position, weight), metric_dict
    """
    # COLLECT THE ARRAYS
    open_arr, close_arr, timestamp_index = ohlcv_array_dict_in["open_arr"], ohlcv_array_dict_in["close_arr"], ohlcv_array_dict_in["timestamp_index"]
    end_idx_arr = ohlcv_array_dict_in["session_end_idx_arr"]
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    decision_idx_arr, fill_idx_arr = idx_dict["decision_idx_arr"], idx_dict["fill_idx_arr"]
    # COLLECT THE WINDOW SESSIONS
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    # IF THE WINDOW IS EMPTY
    if len(window_session_idx_arr) == 0:
        # RETURN EMPTY RESULTS
        return {"trade_pdf": pd.DataFrame(), "daily_equity_pdf": pd.DataFrame(), "metric_dict": {}}
    # DEFINE THE STATE
    state_dict = {"cash": float(initial_capital_in), "share_count": 0}
    # LIST TO HOLD THE ORDERS AND THE EQUITY ROWS
    trade_dict_list, equity_dict_list = [], []

    # FUNCTION: MOVE TO A TARGET WEIGHT AT A BAR PRICE
    def rebalance(bar_idx, raw_price, target_weight, reason_str, weight_before):
        # CALCULATE THE EQUITY AT THE RAW PRICE
        equity = state_dict["cash"] + state_dict["share_count"] * raw_price
        # DEFINE THE TARGET SHARE COUNT (FULL WEIGHT BUYS EVERY AFFORDABLE SHARE; ZERO SELLS EVERYTHING)
        if target_weight >= 1:
            target_share_count = state_dict["share_count"] + get_affordable_share_count(state_dict["cash"], raw_price + entry_slippage_in)
        elif target_weight <= 0:
            target_share_count = 0
        else:
            target_share_count = int(np.floor(target_weight * equity / raw_price))
        # CALCULATE THE ORDER
        delta_share_count = target_share_count - state_dict["share_count"]
        # IF BUYING: LIMIT THE ORDER TO THE AFFORDABLE SHARES
        if delta_share_count > 0:
            fill_price = raw_price + entry_slippage_in
            delta_share_count = min(delta_share_count, get_affordable_share_count(state_dict["cash"], fill_price))
        else:
            fill_price = raw_price - market_exit_slippage_in
        # IF NOTHING IS TRADED
        if delta_share_count == 0:
            return
        # PAY OR RECEIVE THE CASH AND THE FEE
        fee = calculate_side_fee(abs(delta_share_count), fill_price)
        state_dict["cash"] -= delta_share_count * fill_price + fee
        state_dict["share_count"] += delta_share_count
        # RECORD THE ORDER
        trade_dict_list.append({"trade_ts": timestamp_index[bar_idx], "trade_idx": int(bar_idx), "reason": reason_str, "raw_price": float(raw_price),
                                "fill_price": round(float(fill_price), 6), "delta_share_count": int(delta_share_count), "share_count_after": int(state_dict["share_count"]),
                                "fee": fee, "slippage_cost": abs(delta_share_count) * abs(fill_price - raw_price),
                                "weight_before": float(weight_before), "target_weight": float(target_weight), "cash_after": round(state_dict["cash"], 6)})

    # BUY THE INITIAL WEIGHT AT THE FIRST ALLOWED BAR OF THE WINDOW (AS BUY-AND-HOLD)
    first_entry_idx = get_session_first_entry_idx(ohlcv_array_dict_in, int(window_session_idx_arr[0]))
    if initial_weight_in > 0:
        rebalance(first_entry_idx, open_arr[first_entry_idx], float(initial_weight_in), "window_start", 0.0)
    # ITERATE OVER THE WINDOW SESSIONS
    for session_pos, session_idx in enumerate(window_session_idx_arr):
        # COLLECT THE BARS
        decision_idx, fill_idx, end_idx = int(decision_idx_arr[session_idx]), int(fill_idx_arr[session_idx]), int(end_idx_arr[session_idx])
        is_last_session = session_pos == len(window_session_idx_arr) - 1
        # DECISION (NOT ON THE LAST SESSION)
        target_weight = float(target_weight_arr_in[session_idx])
        if not is_last_session and np.isfinite(target_weight):
            # CALCULATE THE CURRENT WEIGHT AT THE DECISION CLOSE
            decision_equity = state_dict["cash"] + state_dict["share_count"] * close_arr[decision_idx]
            weight_now = state_dict["share_count"] * close_arr[decision_idx] / decision_equity if decision_equity > 0 else 0.0
            # IF THE TARGET IS OUTSIDE THE DEAD BAND: REBALANCE AT THE FILL OPEN
            if abs(min(max(target_weight, 0.0), 1.0) - weight_now) > dead_band_in:
                rebalance(fill_idx, open_arr[fill_idx], min(max(target_weight, 0.0), 1.0), "rebalance", weight_now)
        # ON THE LAST SESSION: SELL EVERYTHING AT THE LAST CLOSE
        if is_last_session and state_dict["share_count"] > 0:
            rebalance(end_idx, close_arr[end_idx], 0.0, "END", state_dict["share_count"] * close_arr[end_idx] / (state_dict["cash"] + state_dict["share_count"] * close_arr[end_idx]))
        # MARK THE ACCOUNT TO MARKET AT THE SESSION CLOSE
        equity = state_dict["cash"] + state_dict["share_count"] * close_arr[end_idx]
        equity_dict_list.append({"date": ohlcv_array_dict_in["session_date_list"][session_idx], "equity": round(equity, 6),
                                 "in_position": state_dict["share_count"] > 0, "weight": state_dict["share_count"] * close_arr[end_idx] / equity if equity > 0 else 0.0})
    # CONVERT THE RESULTS
    trade_pdf, daily_equity_pdf = pd.DataFrame(trade_dict_list), pd.DataFrame(equity_dict_list)
    # CALCULATE THE METRICS (THE LAST SESSION EXCLUDED FROM THE MEAN WEIGHT: EVERYTHING IS SOLD AT ITS CLOSE)
    final_equity = float(daily_equity_pdf["equity"].iloc[-1])
    counted_weight_arr = daily_equity_pdf["weight"].to_numpy(dtype=float)[:-1] if len(daily_equity_pdf) > 1 else daily_equity_pdf["weight"].to_numpy(dtype=float)
    metric_dict = {"total_return": round(final_equity / initial_capital_in - 1, 8),
                   "sharpe_ratio": get_sharpe_ratio(daily_equity_pdf, initial_capital_in),
                   "max_drawdown": get_max_drawdown(daily_equity_pdf, initial_capital_in),
                   "final_equity": round(final_equity, 6),
                   "trade_count": int(len(trade_pdf)),
                   "rebalance_count": int((trade_pdf["reason"] == "rebalance").sum()) if not trade_pdf.empty else 0,
                   "mean_weight": float(counted_weight_arr.mean()),
                   "cost_paid": float((trade_pdf["fee"] + trade_pdf["slippage_cost"]).sum()) if not trade_pdf.empty else 0.0}
    # RETURN THE RESULTS
    return {"trade_pdf": trade_pdf, "daily_equity_pdf": daily_equity_pdf, "metric_dict": metric_dict}
