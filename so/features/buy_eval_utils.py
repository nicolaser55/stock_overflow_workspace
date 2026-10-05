import pandas as pd
import numpy as np
import plotly.graph_objects as go
# IMPORT EXPERIMENT CONFIGURATION
from so import config
# IMPORT MARKET DATETIME FUNCTIONS
from so.core.datetime_utils import get_date_pdf
# IMPORT DATA QUALITY FUNCTIONS
from so.core.data_quality import pdf_is_empty
# IMPORT PLOT OHLCV FUNCTIONS
from so.features.plot_ohlcv_utils import fig_add_ohlcv, \
                                fig_add_buy_marker, \
                                fig_add_stop_loss_line, \
                                fig_add_take_profit_line, \
                                fig_add_SLTP_vertical_line
# IMPORT TRADE EXECUTION FUNCTIONS
from so.core.trade_execution import get_ts_bar_idx_arr, get_barrier_price_dict
# IMPORT BARRIER LABEL FUNCTIONS
from so.features.barrier_labels import get_delta_col_str, parse_TSBAR_cell_pdf, add_TSBAR_label_cols

"""
Buy Evaluation Utilities

Previews of buy decisions and their SL / TP boundaries on the TSBAR target (step05).

Rewritten 2026-10 for the new target. The previous version read the abandoned TSSLTP (previous workspace step03) and buy limit label
(previous workspace step11) tables, used its own delta lists (0.01%-0.30%, 0.35%-0.60%, 0.90%) and drew buys at the current bar's average
price. Here:
    - an "ideal" buy at a delta is a decision row whose trade at that delta exits with a take profit (y_tp = 1);
    - a "pred" buy is a decision of a model or rule (decision_ts -> 1);
    - buys are drawn at the ENTRY (open of the bar after the decision), and SL / TP lines run from the entry to the exit,
      exactly as trade_execution resolves them.
"""

# FUNCTION: GET THE TRADES OF A DATE AT A DELTA
def get_date_TSBAR_trade_pdf(date_TSBAR_pdf_in, delta_float_in, ohlcv_array_dict_in):
    """
    Expands the TSBAR rows of a date into one trade per decision row at one delta.

    Args:
        date_TSBAR_pdf_in (pd.DataFrame): TSBAR rows of one date (barrier_labels.format_TSBAR_pdf applied)
        delta_float_in (float): Delta
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict (to convert bar counts to timestamps)

    Returns:
        pd.DataFrame: decision_ts, entry_ts, entry_price, SL_price, TP_price, exit_ts, exit_price, exit_reason,
                      exit_bar_count, y_tp, net_return
    """
    # DEFINE THE DELTA COLUMN
    delta_col_str = get_delta_col_str(delta_float_in)
    # PARSE THE CELLS
    cell_pdf = parse_TSBAR_cell_pdf(date_TSBAR_pdf_in[delta_col_str])
    # PARSE THE LABELS (NET RETURN AND TAKE PROFIT FLAG)
    label_pdf = add_TSBAR_label_cols(date_TSBAR_pdf_in[["entry_price", delta_col_str]], [delta_float_in])
    # CALCULATE THE BARRIER PRICES OF EVERY ROW
    barrier_price_list = [get_barrier_price_dict(entry_price, delta_float_in, date_TSBAR_pdf_in["rr_ratio"].iloc[0]) for entry_price in date_TSBAR_pdf_in["entry_price"]]
    # COLLECT THE EXIT BAR INDEXES
    entry_idx_arr = get_ts_bar_idx_arr(ohlcv_array_dict_in, date_TSBAR_pdf_in["entry_ts"])
    exit_idx_arr = np.where(cell_pdf["exit_bar_count"].to_numpy() >= 0, entry_idx_arr + cell_pdf["exit_bar_count"].to_numpy(), -1)
    # RETURN THE TRADE DATAFRAME
    return pd.DataFrame({
        "decision_ts": date_TSBAR_pdf_in["decision_ts"].to_numpy(),
        "entry_ts": date_TSBAR_pdf_in["entry_ts"].to_numpy(),
        "entry_price": date_TSBAR_pdf_in["entry_price"].to_numpy(),
        "SL_price": [barrier_dict["stop_loss_arr"][0] for barrier_dict in barrier_price_list],
        "TP_price": [barrier_dict["take_profit_arr"][0] for barrier_dict in barrier_price_list],
        "exit_ts": [ohlcv_array_dict_in["timestamp_index"][idx] if idx >= 0 else pd.NaT for idx in exit_idx_arr],
        "exit_price": cell_pdf["exit_price"].to_numpy(),
        "exit_reason": cell_pdf["exit_reason"].to_numpy(),
        "exit_bar_count": cell_pdf["exit_bar_count"].to_numpy(),
        "y_tp": label_pdf[f"y_tp_{delta_col_str}"].to_numpy(),
        "net_return": label_pdf[f"net_return_{delta_col_str}"].to_numpy(),
    })

# FUNCTION: GET THE IDEAL BUY DATA
def get_date_ideal_ts_BS_data_pdf(date_trade_pdf_in):
    """
    Returns the "ideal" buys of a date: decision rows whose trade exits with a take profit.

    Args:
        date_trade_pdf_in (pd.DataFrame): Output of get_date_TSBAR_trade_pdf

    Returns:
        pd.DataFrame: Columns timestamp (decision_ts), ideal_buy (1 / 0)
    """
    # RETURN THE DATAFRAME
    return pd.DataFrame({"timestamp": date_trade_pdf_in["decision_ts"], "ideal_buy": (date_trade_pdf_in["y_tp"] == 1).astype(int)})

# FUNCTION: GET THE PRED BUY DATA
def get_date_pred_ts_BS_data_pdf(ts_BS_dict_in):
    """
    Converts a decision dictionary (decision_ts -> 1 / 0) into a DataFrame.

    Args:
        ts_BS_dict_in (dict): Decision timestamp -> buy flag

    Returns:
        pd.DataFrame: Columns timestamp, pred_buy
    """
    # RETURN THE DATAFRAME
    return pd.DataFrame(list(ts_BS_dict_in.items()), columns=["timestamp", "pred_buy"])

# FUNCTION: PLOT THE IDEAL AND PREDICTED BUYS WITH THEIR SLTP BOUNDARIES
def plot_ideal_pred_buy_data(ohlcv_pdf_in, date_TSBAR_pdf_in, ohlcv_array_dict_in, delta_float_in, date_str_in,
                             ts_BS_dict_in=None, ideal_line_bool_in=False, width_in=1100, height_in=700):
    """
    Plots a date's candles with the ideal buys (take profit trades at the delta) and the predicted buys.

    Ideal buys are drawn as markers at the entry (with their SL / TP lines if ideal_line_bool_in, which gets crowded
    because roughly half of the minutes can be ideal). Predicted buys are drawn with their SL / TP lines from the entry
    to the exit and a vertical SL-TP bar at the entry.

    Args:
        ohlcv_pdf_in (pd.DataFrame): Complete minute OHLCV data with a date column
        date_TSBAR_pdf_in (pd.DataFrame): TSBAR rows of the date (format_TSBAR_pdf applied)
        ohlcv_array_dict_in (dict): Output of trade_execution.get_ohlcv_array_dict
        delta_float_in (float): Delta
        date_str_in (str): Date 'YYYY-MM-DD'
        ts_BS_dict_in (dict | None): Decision timestamp -> 1 for predicted buys
        ideal_line_bool_in (bool): Draw the SL / TP lines of the ideal buys
        width_in, height_in (int): Figure size
    """
    # COLLECT THE OHLCV DATA
    date_ohlcv_pdf = get_date_pdf(ohlcv_pdf_in, date_str_in)
    # IF THE OHLCV DATAFRAME IS EMPTY
    if pdf_is_empty(date_ohlcv_pdf):
        # EXIT FUNCTION
        return
    # CALL FUNCTION TO GET THE TRADES OF THE DATE AT THE DELTA
    date_trade_pdf = get_date_TSBAR_trade_pdf(date_TSBAR_pdf_in, delta_float_in, ohlcv_array_dict_in)
    # CREATE THE IDEAL AND PRED BUY DICTIONARIES
    date_ideal_ts_BS_data_pdf = get_date_ideal_ts_BS_data_pdf(date_trade_pdf)
    date_pred_ts_BS_data_pdf = get_date_pred_ts_BS_data_pdf(ts_BS_dict_in or {})
    ideal_ts_buy_dict = dict(zip(date_ideal_ts_BS_data_pdf.timestamp, date_ideal_ts_BS_data_pdf.ideal_buy))
    pred_ts_buy_dict = dict(zip(date_pred_ts_BS_data_pdf.timestamp, date_pred_ts_BS_data_pdf.pred_buy))
    # CREATE A FIGURE
    fig = go.Figure()
    # ADD THE OHLCV DATA TO THE FIGURE
    fig_add_ohlcv(fig, date_ohlcv_pdf, opacity_in=0.25)
    # ITERATE OVER THE TRADES
    for idx, trade_row in date_trade_pdf.iterrows():
        # COLLECT THE IDEAL AND PRED BUY VALUES
        ideal_buy = ideal_ts_buy_dict.get(trade_row.decision_ts, 0)
        pred_buy = pred_ts_buy_dict.get(trade_row.decision_ts, 0)
        # DEFINE THE END OF THE SL / TP LINES (EXIT, OR THE LAST BAR OF THE DATE IF UNRESOLVED)
        line_end_ts = trade_row.exit_ts if pd.notna(trade_row.exit_ts) else date_ohlcv_pdf["timestamp"].iloc[-1]
        # IF THE IDEAL BUY IS 1
        if ideal_buy == 1:
            # ADD AN IDEAL BUY MARKER AT THE ENTRY
            fig_add_buy_marker(fig, trade_row.entry_price, trade_row.entry_ts, f"Ideal: {idx}", color_str_in="lime", symbol_str_in="circle")
            # IF THE IDEAL LINES MUST BE DRAWN
            if ideal_line_bool_in:
                # ADD THE STOP LOSS AND TAKE PROFIT LINES
                fig_add_stop_loss_line(fig, trade_row.SL_price, trade_row.entry_ts, line_end_ts, f"Ideal: {idx}", dash_str_in="solid")
                fig_add_take_profit_line(fig, trade_row.TP_price, trade_row.entry_ts, line_end_ts, f"Ideal: {idx}", dash_str_in="solid")
        # IF THE PRED BUY IS 1
        if pred_buy == 1:
            # ADD THE PRED BUY MARKER AT THE ENTRY
            fig_add_buy_marker(fig, trade_row.entry_price, trade_row.entry_ts, f"Pred: {idx} ({trade_row.exit_reason})", color_str_in="darkcyan", symbol_str_in="diamond-open-dot")
            # ADD THE STOP LOSS AND TAKE PROFIT LINES
            fig_add_stop_loss_line(fig, trade_row.SL_price, trade_row.entry_ts, line_end_ts, f"Pred: {idx}", dash_str_in="dash")
            fig_add_take_profit_line(fig, trade_row.TP_price, trade_row.entry_ts, line_end_ts, f"Pred: {idx}", dash_str_in="dash")
            # ADD THE VERTICAL SLTP LINE AT THE ENTRY
            fig_add_SLTP_vertical_line(fig, trade_row.entry_ts, trade_row.SL_price, trade_row.TP_price, f"Pred: {idx}", color_str_in="cyan", dash_str_in="dash", width_in=1)
    # UPDATE LAYOUT
    fig.update_layout(
        title=f"Ideal Buy Vs Pred Buy Comparison ({date_str_in}, delta {delta_float_in:.2%})",
        yaxis_title="Price",
        xaxis_title="Time",
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        width=width_in,
        height=height_in,
        font=dict(color="white")
    )
    # DISPLAY FIGURE
    fig.show()

# FUNCTION: PLOT THE EXIT REASONS OF A DATE PER DELTA
def plot_date_delta_exit_reason(label_pdf_in, delta_list_in, title_str_in, width_in=1100, height_in=600):
    """
    Plots, for every decision row (x) and delta (y), how the trade exits (TP / SL / TL / NA).
    (Replaces the commented plot_date_ts_delta_SLTP_pattern of the previous version.)

    Args:
        label_pdf_in (pd.DataFrame): TSBAR rows with label columns (barrier_labels.add_TSBAR_label_cols)
        delta_list_in (list[float]): Deltas to plot
        title_str_in (str): Chart title
        width_in, height_in (int): Figure size
    """
    # CREATE A FIGURE
    fig = go.Figure()
    # DEFINE THE MARKER DICTIONARY
    marker_dict = {"SL": "red", "TP": "green", "TL": "orange", "NA": "grey"}
    # ITERATE OVER THE EXIT REASONS
    for reason_str, color_str in marker_dict.items():
        # LISTS TO HOLD THE POINTS
        x_list, y_list = [], []
        # ITERATE OVER THE DELTAS
        for delta in delta_list_in:
            # COLLECT THE ROWS WITH THE EXIT REASON
            reason_mask = label_pdf_in[f"exit_reason_{get_delta_col_str(delta)}"] == reason_str
            x_list += label_pdf_in.loc[reason_mask, "decision_ts"].tolist()
            y_list += [delta] * int(reason_mask.sum())
        # ADD THE POINTS
        fig.add_trace(go.Scatter(x=x_list, y=y_list, mode="markers", name=reason_str, marker=dict(color=color_str, size=4, symbol="square")))
    # UPDATE LAYOUT
    fig.update_layout(title=title_str_in, xaxis_title="Decision Timestamp", yaxis_title="Delta", template="plotly_dark",
                      width=width_in, height=height_in, font=dict(color="white"), yaxis_tickformat=".2%")
    # DISPLAY FIGURE
    fig.show()

# FUNCTION: GET IDEAL VS PREDICTED BUY STATISTICS
def get_ideal_vs_pred_dict(date_trade_pdf_in, ts_BS_dict_in):
    """
    Compares predicted buys with the ideal buys of a date at one delta.
    (Revives the commented get_ideal_vs_pred_dict of the previous version on the new target.)

    Note: these are per-row statistics that ignore the one-position-at-a-time constraint; use the simulator for
    trading performance.

    Args:
        date_trade_pdf_in (pd.DataFrame): Output of get_date_TSBAR_trade_pdf
        ts_BS_dict_in (dict): Decision timestamp -> 1 for predicted buys

    Returns:
        dict: row_count, ideal_count, ideal_rate (unconditional TP rate), pred_count, pred_TP_ratio (precision),
              pred_ideal_recall, pred_mean_net_return, all_mean_net_return
    """
    # KEEP THE RESOLVED ROWS
    resolved_pdf = date_trade_pdf_in[date_trade_pdf_in["y_tp"].notna()]
    # DEFINE THE PRED MASK
    pred_mask = resolved_pdf["decision_ts"].map(lambda ts: ts_BS_dict_in.get(ts, 0) == 1)
    # DEFINE THE IDEAL MASK
    ideal_mask = resolved_pdf["y_tp"] == 1
    # RETURN THE STATISTICS
    return {
        "row_count": len(resolved_pdf),
        "ideal_count": int(ideal_mask.sum()),
        "ideal_rate": float(ideal_mask.mean()) if len(resolved_pdf) else np.nan,
        "pred_count": int(pred_mask.sum()),
        "pred_TP_ratio": float(ideal_mask[pred_mask].mean()) if pred_mask.any() else np.nan,
        "pred_ideal_recall": float((pred_mask & ideal_mask).sum() / ideal_mask.sum()) if ideal_mask.any() else np.nan,
        "pred_mean_net_return": float(resolved_pdf.loc[pred_mask, "net_return"].mean()) if pred_mask.any() else np.nan,
        "all_mean_net_return": float(resolved_pdf["net_return"].mean()) if len(resolved_pdf) else np.nan,
    }
