import numpy as np
from numba import njit

"""
Compiled Engine Kernels (infrastructure step 4b-2a)

Numba loops for the trailing-stop and barrier engines. The Python engines call these with one session (or one
active window) of price arrays. Integer reason codes: 0 = no hit, 1 = stop / stop-loss, 2 = take-profit, 3 = time
limit. The engines map those codes back to the old simulator's strings.
"""

# NO BARRIER OR STOP WAS HIT
REASON_NONE_INT = 0
# TRAILING STOP OR STOP-LOSS
REASON_STOP_INT = 1
# TAKE-PROFIT
REASON_TP_INT = 2
# TIME-LIMIT EXIT AT THE LAST BAR OF THE HOLDING WINDOW
REASON_TL_INT = 3


# FUNCTION: FIND THE FIRST TRAILING-STOP HIT ON A RANGE OF BARS
@njit(cache=False)
def get_trailing_stop_hit_tuple(open_arr_in, low_arr_in, close_arr_in, highest_close_in, stop_in,
                                trail_multiple_in, volatility_in):
    """
    Same stop as so.core.reentry_simulation.check_stop: never moves down; fill at the open on a gap, otherwise at
    the stop. When k or volatility is not finite, only the highest close is updated.

    Args:
        open_arr_in, low_arr_in, close_arr_in (np.ndarray): Range prices
        highest_close_in (float): Highest close before the first bar
        stop_in (float): Stop before the first bar
        trail_multiple_in (float): k
        volatility_in (float): Daily volatility of this session

    Returns:
        tuple: hit (0/1), offset, raw_price, stop_price, new_highest_close, new_stop
    """
    # EMPTY RANGE LEAVES THE STATE UNCHANGED
    bar_count = len(close_arr_in)
    if bar_count == 0:
        return (0, -1, np.nan, np.nan, highest_close_in, stop_in)
    # NO STOP: TRACK THE HIGHEST CLOSE ONLY
    if not np.isfinite(trail_multiple_in) or not np.isfinite(volatility_in):
        new_highest = highest_close_in
        for bar_idx in range(bar_count):
            if close_arr_in[bar_idx] > new_highest:
                new_highest = close_arr_in[bar_idx]
        return (0, -1, np.nan, np.nan, new_highest, stop_in)
    # WALK ONE BAR AT A TIME; THE STOP USES THE HIGHEST CLOSE BEFORE THIS BAR
    highest_close = highest_close_in
    stop_price = stop_in
    for bar_idx in range(bar_count):
        candidate_stop = highest_close * (1.0 - trail_multiple_in * volatility_in)
        if candidate_stop > stop_price:
            stop_price = candidate_stop
        if low_arr_in[bar_idx] <= stop_price:
            raw_price = open_arr_in[bar_idx] if open_arr_in[bar_idx] <= stop_price else stop_price
            return (1, bar_idx, raw_price, stop_price, highest_close, stop_price)
        if close_arr_in[bar_idx] > highest_close:
            highest_close = close_arr_in[bar_idx]
    return (0, -1, np.nan, np.nan, highest_close, stop_price)


# FUNCTION: FIND THE FIRST BARRIER EXIT ON A RANGE OF BARS
@njit(cache=False)
def get_barrier_exit_tuple(open_arr_in, high_arr_in, low_arr_in, close_arr_in, stop_loss_in, take_profit_in,
                           tp_through_in, horizon_complete_in):
    """
    Same order as so.core.trade_execution.resolve_barrier_exit_dict: gap SL, gap TP, SL during the bar, TP during
    the bar. SL wins on the same bar. A complete horizon with no hit is a time-limit exit at the last close.

    Args:
        open_arr_in, high_arr_in, low_arr_in, close_arr_in (np.ndarray): Active-window prices
        stop_loss_in, take_profit_in (float): Barrier prices
        tp_through_in (float): Extra distance the high must trade through TP
        horizon_complete_in (int): 1 if this range includes the last bar of the holding window

    Returns:
        tuple: offset (-1 if unresolved), raw_price, reason_code
    """
    # EMPTY RANGE IS UNRESOLVED
    bar_count = len(open_arr_in)
    if bar_count == 0:
        return (-1, np.nan, REASON_NONE_INT)
    # THE TRIGGER IS ROUNDED THE SAME WAY AS THE OLD RESOLVER
    tp_trigger = np.round(take_profit_in + tp_through_in, 6)
    for bar_idx in range(bar_count):
        bar_open = open_arr_in[bar_idx]
        if bar_open <= stop_loss_in:
            return (bar_idx, bar_open, REASON_STOP_INT)
        if bar_open >= tp_trigger:
            return (bar_idx, bar_open, REASON_TP_INT)
        if low_arr_in[bar_idx] <= stop_loss_in:
            return (bar_idx, stop_loss_in, REASON_STOP_INT)
        if high_arr_in[bar_idx] >= tp_trigger:
            return (bar_idx, take_profit_in, REASON_TP_INT)
    # TIME LIMIT ONLY WHEN THE HOLDING WINDOW IS COMPLETE
    if int(horizon_complete_in) == 1:
        return (bar_count - 1, close_arr_in[bar_count - 1], REASON_TL_INT)
    return (-1, np.nan, REASON_NONE_INT)
