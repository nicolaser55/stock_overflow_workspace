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

