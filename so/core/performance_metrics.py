import pandas as pd
import numpy as np
# IMPORT EXPERIMENT CONFIGURATION
from so import config

"""
Performance Metrics

Primary success metric (decided 2026-10-01): total return after costs, compared with buy-and-hold over the same period.
Secondary metrics: Sharpe ratio and maximum drawdown (daily mark-to-market equity), plus trade statistics.
Cash earns no interest (config.CASH_INTEREST_RATE = 0), so the Sharpe ratio uses a zero risk-free rate.
"""

# FUNCTION: CALCULATE THE SHARPE RATIO OF A DAILY EQUITY CURVE
def get_sharpe_ratio(daily_equity_pdf_in, initial_capital_in=config.INITIAL_CAPITAL, trading_days_per_year_in=config.TRADING_DAYS_PER_YEAR):
    """
    Calculates the annualized Sharpe ratio of daily equity returns (risk-free rate = CASH_INTEREST_RATE).

    Args:
        daily_equity_pdf_in (pd.DataFrame): Columns date, equity
        initial_capital_in (float): Equity before the first session (first daily return uses it)
        trading_days_per_year_in (int): Annualization factor

    Returns:
        float: Sharpe ratio (NaN if fewer than 2 sessions or zero volatility)
    """
    # IF THERE ARE FEWER THAN 2 SESSIONS
    if daily_equity_pdf_in is None or len(daily_equity_pdf_in) < 2:
        # RETURN NAN
        return np.nan
    # CALCULATE THE DAILY RETURNS (FIRST RETURN RELATIVE TO THE INITIAL CAPITAL)
    equity_arr = np.concatenate([[initial_capital_in], daily_equity_pdf_in["equity"].to_numpy(dtype=float)])
    daily_return_arr = equity_arr[1:] / equity_arr[:-1] - 1
    # SUBTRACT THE DAILY RISK-FREE RATE
    excess_return_arr = daily_return_arr - config.CASH_INTEREST_RATE / trading_days_per_year_in
    # CALCULATE THE STANDARD DEVIATION
    std = excess_return_arr.std(ddof=1)
    # RETURN THE SHARPE RATIO
    return float(excess_return_arr.mean() / std * np.sqrt(trading_days_per_year_in)) if std > 0 else np.nan

# FUNCTION: CALCULATE THE MAXIMUM DRAWDOWN OF A DAILY EQUITY CURVE
def get_max_drawdown(daily_equity_pdf_in, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Calculates the maximum drawdown (most negative equity / running peak - 1) of the daily equity curve.

    Args:
        daily_equity_pdf_in (pd.DataFrame): Columns date, equity
        initial_capital_in (float): Equity before the first session

    Returns:
        float: Maximum drawdown (<= 0; NaN if the curve is empty)
    """
    # IF THE CURVE IS EMPTY
    if daily_equity_pdf_in is None or daily_equity_pdf_in.empty:
        # RETURN NAN
        return np.nan
    # PREPEND THE INITIAL CAPITAL
    equity_arr = np.concatenate([[initial_capital_in], daily_equity_pdf_in["equity"].to_numpy(dtype=float)])
    # RETURN THE MAXIMUM DRAWDOWN
    return float((equity_arr / np.maximum.accumulate(equity_arr) - 1).min())

# FUNCTION: GET THE PERFORMANCE METRIC DICTIONARY OF A SIMULATION
def get_performance_metric_dict(transaction_pdf_in, daily_equity_pdf_in, window_bar_count_in=np.nan, initial_capital_in=config.INITIAL_CAPITAL):
    """
    Summarizes a simulation.

    Args:
        transaction_pdf_in (pd.DataFrame): Transactions of the simulation
        daily_equity_pdf_in (pd.DataFrame): Daily equity curve of the simulation
        window_bar_count_in (int | float): Number of bars in the evaluation window (for the exposure)
        initial_capital_in (float): Starting cash

    Returns:
        dict: total_return, sharpe_ratio, max_drawdown, trade_count, win/loss/null counts, TP/SL/TL/END rates,
              mean_trade_return, exposure_pct, final_equity
    """
    # DEFINE THE TRANSACTION FLAG
    has_transactions = transaction_pdf_in is not None and not transaction_pdf_in.empty
    # CALCULATE THE FINAL EQUITY (REALIZED)
    final_equity = initial_capital_in + (transaction_pdf_in["net_profit"].sum() if has_transactions else 0.0)
    # COLLECT THE TRADE COUNT
    trade_count = len(transaction_pdf_in) if has_transactions else 0
    # DEFINE THE RATE FUNCTION
    def get_rate(col_str, value_str):
        return float((transaction_pdf_in[col_str] == value_str).mean()) if has_transactions else np.nan
    # RETURN THE METRIC DICTIONARY
    return {
        "total_return": round(final_equity / initial_capital_in - 1, 8),
        "sharpe_ratio": get_sharpe_ratio(daily_equity_pdf_in, initial_capital_in),
        "max_drawdown": get_max_drawdown(daily_equity_pdf_in, initial_capital_in),
        "trade_count": trade_count,
        "win_count": int((transaction_pdf_in["result"] == config.RESULT_WIN).sum()) if has_transactions else 0,
        "loss_count": int((transaction_pdf_in["result"] == config.RESULT_LOSS).sum()) if has_transactions else 0,
        "null_count": int((transaction_pdf_in["result"] == config.RESULT_NULL).sum()) if has_transactions else 0,
        "tp_rate": get_rate("exit_reason", config.EXIT_REASON_TP),
        "sl_rate": get_rate("exit_reason", config.EXIT_REASON_SL),
        "tl_rate": get_rate("exit_reason", config.EXIT_REASON_TL),
        "end_rate": get_rate("exit_reason", config.EXIT_REASON_END),
        "mean_trade_return": float(transaction_pdf_in["net_profit_pct"].mean()) if has_transactions else np.nan,
        "exposure_pct": float(transaction_pdf_in["hold_bar_count"].sum() / window_bar_count_in) if has_transactions and window_bar_count_in > 0 else np.nan,
        "final_equity": round(final_equity, 6),
    }
