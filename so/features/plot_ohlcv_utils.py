import pandas as pd
import numpy as np
import webcolors
import plotly.graph_objects as go
# IMPORT DATA QUALITY FUNCTIONS
from so.core.data_quality import get_col_histogram_pdf
# IMPORT TRADE EXECUTION FUNCTIONS (SAME EXIT RULES AS THE TARGET MATRIX AND THE SIMULATOR)
from so.core.trade_execution import resolve_barrier_exit_dict

# FUNCTION: PLOT THE BIN GROUPS DATAFRAME
def plot_col_histogram(pdf_in, col_str_in, title_str_in="", width_in=1100, height_in=500):
    # GET THE MEAN AND MEDIAN OF THE COLUMN
    avg = pdf_in[col_str_in].mean()
    med = pdf_in[col_str_in].median()
    # GET HISTOGRAM OF COLUMN
    hist_pdf = get_col_histogram_pdf(pdf_in, col_str_in)
    # DEFINE THE BUFFER
    val_range = hist_pdf[col_str_in].max() - hist_pdf[col_str_in].min()
    # DEFINE THE BUFFER AS 10% OF THE VALUE RANGE
    buffer = val_range * 0.1
    # COLLECT THE MINIMUM AND MAXIMUM PCT BINS
    min_bin = hist_pdf[col_str_in].min() - buffer if hist_pdf[col_str_in].min() < 0 else 0
    max_bin = hist_pdf[col_str_in].max() + buffer if hist_pdf[col_str_in].max() > 0 else 0
    # COLLECT THE MINIMUM AND MAXIMUM SEGMENT COUNTS
    min_count = 0
    max_count = hist_pdf["count"].max() * 1.2
    # CREATE A FIGURE
    fig = go.Figure()
    # ADD A VERTICAL RECTANGLE TO THE FIGURE (HIGLIGHT NEGATIVE BINS)
    fig.add_trace(go.Scatter(x=[0, min_bin, min_bin, 0, 0],
                            y=[min_count, min_count, max_count, max_count, min_count],
                            mode="lines",
                            fill="toself",
                            fillcolor="red",
                            opacity=0.1,
                            line=dict(color="red", width=0),
                            name="Negative Bins"))
    # ADD A VERTICAL RECTANGLE TO THE FIGURE (HIGLIGHT POSITIVE BINS)
    fig.add_trace(go.Scatter(x=[0, max_bin, max_bin, 0, 0],
                            y=[min_count, min_count, max_count, max_count, min_count],
                            mode="lines",
                            fill="toself",
                            fillcolor="lime",
                            opacity=0.1,
                            line=dict(color="green", width=0),
                            name="Positive Bins"))
    # ADD THE SEGMENT COUNT TO PCT BIN BARS
    fig.add_trace(go.Bar(x=hist_pdf[col_str_in],
                         y=hist_pdf["count"],
                         marker_color='#4287f5',
                         marker_line_width=0,
                         name=f"{col_str_in} Count",
                         text=hist_pdf["count"],
                         textposition="outside",
                         textfont=dict(
                             family="Arial",
                             size=30,
                             color="white")))
    # ADD AN AVERAGE AND MEDIAN LINE
    fig.add_trace(go.Scatter(x=[avg, avg],
                            y=[0, max_count],
                            mode="lines",
                            line=dict(color="yellow", width=1),
                            name=f"Average: {avg:.6f}"))
    fig.add_trace(go.Scatter(x=[med, med],
                            y=[0, max_count],
                            mode="lines",
                            line=dict(color="white", width=1),
                            name=f"Median: {med:.6f}"))
    # UPDATE LAYOUT
    fig.update_layout(
        title=f"Distribution of '{col_str_in}' {title_str_in}",
        yaxis_title="Frequency", 
        xaxis_title=f"{col_str_in}",
        showlegend=True,
        template="plotly_dark",
        xaxis=dict(
            showgrid=True,
            gridwidth=1,
            tickangle=45
        ),
        yaxis=dict(
            showgrid=True,
            gridwidth=1,
        ),
        yaxis_range=[min_count, max_count],
        width=width_in,
        height=height_in,
        font=dict(color="white"),
    )
    # SHOW THE FIGURE
    fig.show()

# FUNCTION: CONVERT NAMED COLOR TO RGBA
def css_color_to_rgba(color_name_str_in, alpha=1.0):
    # COLLECT THE RGB OF THE COLOR
    rgb = webcolors.name_to_rgb(color_name_str_in)
    # RETURN STRING OF RGBA
    return f"rgba({rgb.red}, {rgb.green}, {rgb.blue}, {alpha})"

# FUNCTION: CONVERT HEX COLOR TO RGBA
def hex_to_rgba(hex_color, alpha=1.0):
    # REMOVE THE HASH FROM THE HEX COLOR
    hex_color = hex_color.lstrip("#")
    # GET THE LENGTH OF THE HEX COLOR
    lv = len(hex_color)
    # IF THE LENGTH OF THE HEX COLOR IS 6
    if lv == 6:
        # COLLECT THE RGB VALUES
        r, g, b = tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    # IF THE LENGTH OF THE HEX COLOR IS 3
    elif lv == 3:  # e.g. '#f00'
        r, g, b = tuple(int(hex_color[i] * 2, 16) for i in range(3))
    # IF THE HEX COLOR IS INVALID
    else:
        # RAISE AN ERROR
        raise ValueError("Invalid HEX color format.")
    # RETURN THE RGBA COLOR
    return f"rgba({r}, {g}, {b}, {alpha})"

# FUNCTION: GET THE ROW AND COLUMN KEYWORD DICTIONARY OF A TRACE
def get_row_col_dict(fig_in, row_in=None, col_in=None):
    """
    Returns the add_trace keyword arguments that place a trace in a subplot.

    (Replaces the previous row/col tuple helper: '"grid" in fig.layout' is always True in plotly, so it always returned
    None and every trace landed in the first subplot; its (1, 1) branch would have raised an error on a plain figure.)

    Args:
        fig_in (go.Figure): Figure (plain or created with make_subplots)
        row_in (int | None): Subplot row (None -> default axes, i.e. the first subplot)
        col_in (int | None): Subplot column (defaults to 1 when a row is given)

    Returns:
        dict: {} for plain figures or when no row is given, otherwise {"row": row_in, "col": col_in}
    """
    # IF THE FIGURE IS NOT A SUBPLOT FIGURE OR NO ROW IS GIVEN
    if getattr(fig_in, "_grid_ref", None) is None or row_in is None:
        # RETURN NO PLACEMENT ARGUMENTS
        return {}
    # RETURN THE PLACEMENT ARGUMENTS
    return {"row": row_in, "col": col_in if col_in is not None else 1}

# FUNCTION: ADD OHLCV TO FIGURE
def fig_add_ohlcv(fig_in, ohlcv_pdf_in, opacity_in=1, row_in=None, col_in=None):
    # ADD CANDLESTICK CHART
    fig_in.add_trace(go.Candlestick(
        x=ohlcv_pdf_in["timestamp"],
        open=ohlcv_pdf_in["open"], 
        high=ohlcv_pdf_in["high"],
        low=ohlcv_pdf_in["low"],
        close=ohlcv_pdf_in["close"],
        name="Price",
        opacity=opacity_in
    ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD AVERAGE PRICE TO FIGURE
def fig_add_avg_price(fig_in, ohlcv_pdf_in, row_in=None, col_in=None):
    # ADD AVERAGE PRICE
    fig_in.add_trace(go.Scatter(
        x=ohlcv_pdf_in["timestamp"],
        y=ohlcv_pdf_in["avg_price"],
        mode="lines",
        line=dict(color="yellow", width=1),
        name="Average Price"
    ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD MINIMA TO FIGURE
def fig_add_minima(fig_in, ohlcv_pdf_in, row_in=None, col_in=None):
    # ADD MINIMA MARKERS (WITH BUFFER)
    fig_in.add_trace(go.Scatter(
        x=ohlcv_pdf_in["timestamp"],
        y=ohlcv_pdf_in["minima"] - (ohlcv_pdf_in.high - ohlcv_pdf_in.low) * 0.1,
        mode="markers",
        line=dict(color="green", width=1),
        marker=dict(size=10, symbol="arrow-down"),
        name="Minima"
    ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD MAXIMA TO FIGURE
def fig_add_maxima(fig_in, ohlcv_pdf_in, row_in=None, col_in=None):
    # ADD MAXIMA MARKERS (WITH BUFFER)
    fig_in.add_trace(go.Scatter(
        x=ohlcv_pdf_in["timestamp"],
        y=ohlcv_pdf_in["maxima"] + (ohlcv_pdf_in.high - ohlcv_pdf_in.low) * 0.1,
        mode="markers",
        line=dict(color="red", width=1),
        marker=dict(size=10, symbol="arrow-up"),
        name="Maxima"
    ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD EXTREMAS
def fig_add_extremas(fig_in, ohlcv_pdf_in, row_in=None, col_in=None):
    # ADD MINIMA
    fig_add_minima(fig_in, ohlcv_pdf_in, row_in=row_in, col_in=col_in)
    # ADD MAXIMA
    fig_add_maxima(fig_in, ohlcv_pdf_in, row_in=row_in, col_in=col_in)

# ADD EXTREMAS PRICE PATTERN
def fig_add_extremas_pp(fig_in, ohlcv_pdf_in, row_in=None, col_in=None):
    # ADD PRICE PATTERN
    fig_in.add_trace(go.Scatter(
        x=ohlcv_pdf_in["timestamp"],
        y=ohlcv_pdf_in["extremas_pp"],
        mode="lines",
        name="Extremas Price Pattern",
        line=dict(color="cyan", width=1)
    ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD DERIVED PRICE
def fig_add_composite_price(fig_in, ohlcv_pdf_in, row_in=None, col_in=None):
    fig_in.add_trace(go.Scatter(
        x=ohlcv_pdf_in["timestamp"],
        y=ohlcv_pdf_in["composite_price"],
        mode="lines",
        name="Composite Price",
        line=dict(color="white", width=2, dash="dot"),
    ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD SUPPORT TREND LINE TO FIGURE
def fig_add_support_col(fig_in, ohlcv_pdf_in, opacity_in=0.15, row_in=None, col_in=None):
    # COLLECT THE SUPPORT LINE TOP AND BOTTOM VALUES
    support_pdf = ohlcv_pdf_in[ohlcv_pdf_in.support.notna()]
    # IF THE SUPPORT DATAFRAME IS NOT EMPTY
    if not support_pdf.empty:
        # IF THE SUPPORT BOTTOM AND TOP ARE IN THE DATAFRAME
        if all(["sup_bot" in support_pdf.columns, "sup_top" in support_pdf.columns]):
            # COLLECT THE START AND END TIMESTAMPS
            start_ts, end_ts = support_pdf.timestamp.iloc[0], support_pdf.timestamp.iloc[-1]
            # COLLECT THE BOTTOM AND TOP START AND END PRICES
            bot_start_p, bot_end_p = support_pdf.sup_bot.iloc[0], support_pdf.sup_bot.iloc[-1]
            top_start_p, top_end_p = support_pdf.sup_top.iloc[0], support_pdf.sup_top.iloc[-1]
            # ADD THE SUPPORT BUFFERED RECTANGLE
            fig_in.add_trace(go.Scatter(
                x=[start_ts, end_ts, end_ts, start_ts, start_ts],
                y=[top_start_p, top_end_p, bot_end_p, bot_start_p, top_start_p],
                mode="lines",
                line=dict(color="green", width=1),
                fill="toself",
                fillcolor=f"rgba(0,255,0,{opacity_in})",
                opacity=1,
                legendgroup="support",
                showlegend=False,
            ), **get_row_col_dict(fig_in, row_in, col_in))
        # ADD SUPPORT TREND LINE
        fig_in.add_trace(go.Scatter(
            x=ohlcv_pdf_in["timestamp"],
            y=ohlcv_pdf_in["support"],
            mode="lines",
            line=dict(color="green", width=2, dash="dash"),
            legendgroup="support",
            showlegend=True,
            name="Support",
            text=f"Support"
        ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD SUPPORT AREA TO FIGURE
def fig_add_support_area(fig_in, start_ts, end_ts, top_p, bot_p, id_in, opacity_in=0.15, row_in=None, col_in=None):
    # ADD THE SUPPORT AREA BUFFERED RECTANGLE
    fig_in.add_trace(go.Scatter(
        x=[start_ts, end_ts, end_ts, start_ts, start_ts],
        y=[top_p, top_p, bot_p, bot_p, top_p],
        mode="lines",
        line=dict(color="green", width=1),
        name=f"Support Level: {id_in}",
        text=f"Support Level: {id_in}",
        legendgroup=f"support {id_in}",
        showlegend=False,
        fill="toself",
        fillcolor=f"rgba(0,255,0,{opacity_in})",
        opacity=1,
    ), **get_row_col_dict(fig_in, row_in, col_in))
    # CALCULATE THE MID PRICE
    mid_p = (top_p + bot_p) / 2
    # ADD A SUPPORT MIDDLE LINE
    fig_in.add_trace(go.Scatter(
        x=[start_ts, end_ts],
        y=[mid_p, mid_p],
        mode="lines",
        legendgroup=f"support {id_in}",
        showlegend=True,
        line=dict(color="green", width=2, dash="dash"),
        name=f"Support Level: {id_in}",
    ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD RESISTANCE TREND LINE TO FIGURE
def fig_add_resistance_col(fig_in, ohlcv_pdf_in, opacity_in=0.15, row_in=None, col_in=None):
    # COLLECT THE SUPPORT LINE TOP AND BOTTOM VALUES
    resistance_pdf = ohlcv_pdf_in[ohlcv_pdf_in.resistance.notna()]
    # IF THE RESISTANCE DATAFRAME IS NOT EMPTY
    if not resistance_pdf.empty:
        # IF THE RESISTANCE BOTTOM AND TOP ARE IN THE DATAFRAME
        if all(["res_bot" in resistance_pdf.columns, "res_top" in resistance_pdf.columns]):
            # COLLECT THE START AND END TIMESTAMPS
            start_ts, end_ts = resistance_pdf.timestamp.iloc[0], resistance_pdf.timestamp.iloc[-1]
            # COLLECT THE BOTTOM AND TOP START AND END PRICES
            bot_start_p, bot_end_p = resistance_pdf.res_bot.iloc[0], resistance_pdf.res_bot.iloc[-1]
            top_start_p, top_end_p = resistance_pdf.res_top.iloc[0], resistance_pdf.res_top.iloc[-1]
            # ADD THE RESISTANCE BUFFERED RECTANGLE
            fig_in.add_trace(go.Scatter(
                x=[start_ts, end_ts, end_ts, start_ts, start_ts],
                y=[top_start_p, top_end_p, bot_end_p, bot_start_p, top_start_p],
                mode="lines",
                line=dict(color="red", width=1),
                fill="toself",
                fillcolor=f"rgba(255,0,0,{opacity_in})",
                opacity=1,
                legendgroup="resistance",
                showlegend=False,
            ), **get_row_col_dict(fig_in, row_in, col_in))
        # ADD SUPPORT TREND LINE
        fig_in.add_trace(go.Scatter(
            x=ohlcv_pdf_in["timestamp"],
            y=ohlcv_pdf_in["resistance"],
            mode="lines",
            line=dict(color="red", width=2, dash="dash"),
            legendgroup="resistance",
            name="Resistance",
            text=f"Resistance"
        ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD RESISTANCE AREA TO FIGURE
def fig_add_resistance_area(fig_in, start_ts, end_ts, top_p, bot_p, id_in, opacity_in=0.15, row_in=None, col_in=None):
    # ADD THE RESISTANCE LEVEL BUFFERED RECTANGLE
    fig_in.add_trace(go.Scatter(
        x=[start_ts, end_ts, end_ts, start_ts, start_ts],
        y=[top_p, top_p, bot_p, bot_p, top_p],
        mode="lines",
        line=dict(color="red", width=1),
        name=f"Resistance Level: {id_in}",
        text=f"Resistance Level: {id_in}",
        legendgroup=f"resistance {id_in}",
        showlegend=False,
        fill="toself",
        fillcolor=f"rgba(255,0,0,{opacity_in})",
        opacity=1,
    ), **get_row_col_dict(fig_in, row_in, col_in))
    # CALCULATE THE MID PRICE
    mid_p = (top_p + bot_p) / 2
    # ADD A RESISTANCE MIDDLE LINE
    fig_in.add_trace(go.Scatter(
        x=[start_ts, end_ts],
        y=[mid_p, mid_p],
        mode="lines",
        legendgroup=f"resistance {id_in}",
        showlegend=True,
        line=dict(color="red", width=2, dash="dash"),
        name=f"Resistance Level: {id_in}",
    ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD BUY MARKER
def fig_add_buy_order_marker(fig_in, buy_order_price_in, ts_in, id_in, legend_group_in=None, color_str_in="white", symbol_str_in="diamond-dot", row_in=None, col_in=None):
    # PRE-DEFINE LEGEND GROU
    legend_group_str = f"buy order {id_in}" if legend_group_in is None else legend_group_in
    # PLOT BUY ORDER MARKER
    fig_in.add_trace(go.Scatter(x=[ts_in],
                                y=[buy_order_price_in],
                                mode="markers",
                                name=f"{id_in} | Buy Order",
                                text=f"{id_in} | Buy Order",
                                legendgroup=legend_group_str,
                                showlegend=True,
                                marker=dict(color=color_str_in, size=10, symbol=symbol_str_in)
                                ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD BUY MARKER
def fig_add_buy_order_line(fig_in, ts_in):
    # PLOT A VERTICAL LINE
    fig_in.add_vline(x=ts_in, line_width=1, line_dash="dash", line_color="white")

# FUNCTION: ADD BUY MARKER
def fig_add_buy_marker(fig_in, buy_price_in, ts_in, id_in, legend_group_in=None, color_str_in="yellow", symbol_str_in="diamond-dot", row_in=None, col_in=None):
    # PRE-DEFINE LEGEND GROU
    legend_group_str = f"buy {id_in}" if legend_group_in is None else legend_group_in
    # PLOT BUY PRICE MARKER
    fig_in.add_trace(go.Scatter(x=[ts_in],
                                y=[buy_price_in],
                                mode="markers",
                                name=f"{id_in} | Buy Price (${buy_price_in:.2f})",
                                text=f"{id_in} | Buy Price (${buy_price_in:.2f})",
                                legendgroup=legend_group_str,
                                showlegend=True,
                                marker=dict(color=color_str_in, size=10, symbol=symbol_str_in)
                                ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD VERTICAL SLTP LINE
def fig_add_SLTP_vertical_line(fig_in, buy_ts_in, SL_price_in, TP_price_in, id_in, legend_group_in=None, color_str_in="purple", dash_str_in="solid", width_in=0.5, row_in=None, col_in=None):
    # PRE-DEFINE LEGEND GROUP
    legend_group_str = f"buy {id_in}" if legend_group_in is None else legend_group_in
    # CREATE A TRACE FOR THE CURRENT PRICE
    fig_in.add_trace(go.Scatter(x=[buy_ts_in, buy_ts_in],
                                y=[SL_price_in, TP_price_in],
                                mode="lines",
                                name=f"CS: {id_in}",
                                text=f"CS: {id_in}",
                                legendgroup=legend_group_str,
                                showlegend=False,
                                line=dict(color=color_str_in, dash=dash_str_in, width=width_in)
                                ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD SELL MARKER
def fig_add_sell_marker(fig_in, sell_price_in, ts_in, action_str_in, id_in, row_in=None, col_in=None):
    # DICTIONARY TO DEFINE STOP LOSS, TAKE PROFIT AND TIME LIMIT COLORS AND SYMBOLS
    action_color_dict = {"stop_loss": "crimson", "take_profit": "lime", "time_limit": "orange"}
    action_symbol_dict = {"stop_loss": "x", "take_profit": "cross", "time_limit": "square"}
    # PLOT SELL PRICE MARKER
    fig_in.add_trace(go.Scatter(x=[ts_in],
                                y=[sell_price_in],
                                mode="markers",
                                name=f"{id_in} | Sell Price (${sell_price_in:.2f})",
                                text=f"{id_in} | Sell Price (${sell_price_in:.2f})",
                                legendgroup=f"sell {id_in}",
                                showlegend=True,
                                marker=dict(color=action_color_dict[action_str_in],
                                size=10,
                                symbol=action_symbol_dict[action_str_in])
                                ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD STOP LOSS LINE
def fig_add_stop_loss_line(fig_in, stop_loss_price_in, ts1_in, ts2_in, id_in, dash_str_in="solid", row_in=None, col_in=None):
    # PLOT STOP LOSS LINE
    fig_in.add_trace(go.Scatter(x=[ts1_in, ts2_in],
                                y=[stop_loss_price_in, stop_loss_price_in],
                                mode="lines",
                                name=f"{id_in} | SL Price (${stop_loss_price_in:.2f})",
                                text=f"{id_in} | SL Price (${stop_loss_price_in:.2f})",
                                legendgroup=f"stop_loss {id_in}",
                                line=dict(color="red", dash=dash_str_in, width=2)
                                ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD TAKE PROFIT LINE
def fig_add_take_profit_line(fig_in, take_profit_price_in, ts1_in, ts2_in, id_in, dash_str_in="solid", row_in=None, col_in=None):
    # PLOT TAKE PROFIT LINE
    fig_in.add_trace(go.Scatter(x=[ts1_in, ts2_in],
                                y=[take_profit_price_in, take_profit_price_in],
                                mode="lines",
                                name=f"{id_in} | TP Price (${take_profit_price_in:.2f})",
                                text=f"{id_in} | TP Price (${take_profit_price_in:.2f})",
                                legendgroup=f"take_profit {id_in}",
                                line=dict(color="green", dash=dash_str_in, width=2)
                                ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: ADD SLTP BOX
def fig_add_SLTP_box(fig_in, buy_ts_in, buy_price_in, sell_ts_in, stop_loss_price_in, take_profit_price_in, id_in, row_in=None, col_in=None):
    # ADD STOP LOSS RECTANGLE
    fig_in.add_trace(go.Scatter(x=[buy_ts_in, buy_ts_in, sell_ts_in, sell_ts_in, buy_ts_in],
                                y=[buy_price_in, stop_loss_price_in, stop_loss_price_in, buy_price_in, buy_price_in],
                                mode="lines",
                                line=dict(color="white", width=2, dash="solid"),
                                fill="toself",
                                name=f"{id_in} | SL Area",
                                text=f"{id_in} | SL Area",
                                legendgroup=f"stop_loss {id_in}",
                                showlegend=True,
                                fillcolor="red",
                                opacity=0.15
                                ), **get_row_col_dict(fig_in, row_in, col_in))

    # ADD TAKE PROFIT RECTANGLE
    fig_in.add_trace(go.Scatter(x=[buy_ts_in, buy_ts_in, sell_ts_in, sell_ts_in, buy_ts_in],
                                y=[buy_price_in, take_profit_price_in, take_profit_price_in, buy_price_in, buy_price_in],
                                mode="lines",
                                line=dict(color="white", width=2, dash="solid"),
                                fill="toself",
                                name=f"{id_in} | TP Area",
                                text=f"{id_in} | TP Area",
                                legendgroup=f"take_profit {id_in}",
                                showlegend=True,
                                fillcolor="green",
                                opacity=0.15
                                ), **get_row_col_dict(fig_in, row_in, col_in))

# FUNCTION: FIG ADD TRANSACTION
def fig_add_transaction(fig_in, buy_ts_in, buy_price_in, sell_ts_in, sell_price_in, stop_loss_in, take_profit_in, id_in, buy_order_ts_in=pd.NaT, exit_reason_str_in=None, row_in=None, col_in=None):
    """
    Draws one trade: (optional) decision / order marker, buy marker, sell marker, SL and TP lines and areas.

    Args:
        exit_reason_str_in (str | None): "TP", "SL", "TL" or "END" (trade_execution exit reasons). When None, the action
                                         is inferred from the sign of the trade (previous behavior).
    """
    # DEFINE THE EXIT REASON TO ACTION DICTIONARY
    exit_reason_action_dict = {"TP": "take_profit", "SL": "stop_loss", "TL": "time_limit", "END": "time_limit"}
    # DEFINE ACTION STRING (FROM THE EXIT REASON WHEN GIVEN, OTHERWISE FROM THE SIGN OF THE TRADE)
    action_str = exit_reason_action_dict.get(exit_reason_str_in, "take_profit" if sell_price_in > buy_price_in else "stop_loss")
    # ACTION COLOR DICT
    action_color_dict = {"stop_loss": "red", "take_profit": "green", "time_limit": "orange"}
    # IF THE BUY ORDER TIMESTAMP IS NOT NULL
    if not pd.isna(buy_order_ts_in):
        # ADD ORDER PRICE
        fig_add_buy_order_marker(fig_in, buy_price_in, buy_order_ts_in, id_in, row_in=row_in, col_in=col_in)
        # ADD BUY ORDER LINE
        fig_add_buy_order_line(fig_in, buy_order_ts_in)
    # ADD BUY PRICE
    fig_add_buy_marker(fig_in, buy_price_in, buy_ts_in, id_in, row_in=row_in, col_in=col_in)
    # ADD SELL PRICE
    fig_add_sell_marker(fig_in, sell_price_in, sell_ts_in, action_str, id_in, row_in=row_in, col_in=col_in)
    # ADD STOP LOSS LINE
    fig_add_stop_loss_line(fig_in, stop_loss_in, buy_ts_in, sell_ts_in, id_in, row_in=row_in, col_in=col_in)
    # ADD TAKE PROFIT LINE
    fig_add_take_profit_line(fig_in, take_profit_in, buy_ts_in, sell_ts_in, id_in, row_in=row_in, col_in=col_in)
    # ADD SLTP BOX
    fig_add_SLTP_box(fig_in, buy_ts_in, buy_price_in, sell_ts_in, stop_loss_in, take_profit_in, id_in, row_in=row_in, col_in=col_in)
    # ADD A RECTANGLE TO MAKE STOP LOSS OR TAKE PROFIT VISIBLE
    fig_in.add_vrect(x0=buy_ts_in,
                    x1=sell_ts_in,
                    line_color=action_color_dict[action_str],
                    opacity=1,
                    layer="below",
                    line_width=1,
                    line_dash="dot")

# FUNCTION: PLOT TREND LINES
def plot_ohlcv_minimas(ohlcv_pdf_in, title_str_in="", width_in=1000, height_in=500):
    """
    Plot OHLCV data with trend lines and contact points
    
    Args:
        df: DataFrame containing OHLCV data with trend lines and contact points
        title: Title for the plot (default: "Price Chart with Trend Lines")
    """
    # CREATE A FIGURE
    fig = go.Figure()
    # ADD CANDLESTICK CHART
    fig_add_ohlcv(fig, ohlcv_pdf_in, opacity_in=0.2)
    # PLOT THE LOW PRICE
    fig.add_trace(go.Scatter(
        x=ohlcv_pdf_in["timestamp"],
        y=ohlcv_pdf_in["low"],
        mode="lines",
        line=dict(color="red", width=1),
        name="Low Price"
        ), **get_row_col_dict(fig))

    # ADD MINIMA
    fig_add_minima(fig, ohlcv_pdf_in)
    # UPDATE LAYOUT
    fig.update_layout(
        title=f"{title_str_in} OHLCV Price Chart Minimas",
        yaxis_title="Price",
        xaxis_title="Time",
        showlegend=True,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        width=width_in,
        height=height_in,
        font=dict(color="white")
    )
    # DISPLAY FIGURE
    fig.show()

# FUNCTION: PLOT TREND LINES
def plot_ohlcv_maximas(ohlcv_pdf_in, title_str_in="", width_in=1000, height_in=500):
    """
    Plot OHLCV data with trend lines and contact points
    
    Args:
        df: DataFrame containing OHLCV data with trend lines and contact points
        title: Title for the plot (default: "Price Chart with Trend Lines")
    """
    # CREATE A FIGURE
    fig = go.Figure()
    # ADD CANDLESTICK CHART
    fig_add_ohlcv(fig, ohlcv_pdf_in, opacity_in=0.2)
    # PLOT THE LOW PRICE
    fig.add_trace(go.Scatter(
        x=ohlcv_pdf_in["timestamp"],
        y=ohlcv_pdf_in["high"],
        mode="lines",
        line=dict(color="green", width=1),
        name="High Price"
        ), **get_row_col_dict(fig))
    
    # ADD MAXIMA
    fig_add_maxima(fig, ohlcv_pdf_in)
    # UPDATE LAYOUT
    fig.update_layout(
        title=f"{title_str_in} OHLCV Price Chart Maximas",
        yaxis_title="Price",
        xaxis_title="Time",
        showlegend=True,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        width=width_in,
        height=height_in,
        font=dict(color="white")
    )
    # DISPLAY FIGURE
    fig.show()

# FUNCTION: PLOT TREND LINES
def plot_ohlcv_extremas(ohlcv_pdf_in, title_str_in="", width_in=1000, height_in=500):
    """
    Plot OHLCV data with trend lines and contact points
    
    Args:
        df: DataFrame containing OHLCV data with trend lines and contact points
        title: Title for the plot (default: "Price Chart with Trend Lines")
    """
    # CREATE A FIGURE
    fig = go.Figure()
    # ADD CANDLESTICK CHART
    fig_add_ohlcv(fig, ohlcv_pdf_in, opacity_in=0.2)
    # ADD MINIMA
    fig_add_minima(fig, ohlcv_pdf_in)
    # ADD MAXIMA
    fig_add_maxima(fig, ohlcv_pdf_in)
    # UPDATE LAYOUT
    fig.update_layout(
        title=f"{title_str_in} OHLCV Price Chart Extremas",
        yaxis_title="Price",
        xaxis_title="Time",
        showlegend=True,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        width=width_in,
        height=height_in,
        font=dict(color="white")
    )
    # DISPLAY FIGURE
    fig.show()

# FUNCTION: PLOT TREND LINES
def plot_ohlcv(ohlcv_pdf_in, SLTP_dict_in={}, title_str_in="", width_in=1200, height_in=700):
    """
    Plot OHLCV data with trend lines and contact points
    
    Args:
        df: DataFrame containing OHLCV data with trend lines and contact points
        title: Title for the plot (default: "Price Chart with Trend Lines")
    """
    # CREATE A FIGURE
    fig = go.Figure()
    # # ADD CANDLESTICK CHART
    fig_add_ohlcv(fig, ohlcv_pdf_in)
    # IF THE AVERAGE PRICE IS IN COLUMNS
    if "avg_price" in ohlcv_pdf_in.columns:
        # ADD AVERAGE PRICE
        fig_add_avg_price(fig, ohlcv_pdf_in)
    # IF THE MINIMA IS IN COLUMNS   
    if "minima" in ohlcv_pdf_in.columns:
        # ADD MINIMA
        fig_add_minima(fig, ohlcv_pdf_in)
    # IF THE MAXIMA IS IN COLUMNS   
    if "maxima" in ohlcv_pdf_in.columns:
        # ADD MAXIMA
        fig_add_maxima(fig, ohlcv_pdf_in)
    # IF THE PRICE PATTERN IS IN COLUMNS
    if "extremas_pp" in ohlcv_pdf_in.columns:
        # ADD EXTREMAS PRICE PATTERN
        fig_add_extremas_pp(fig, ohlcv_pdf_in)
    # IF THE DERIVED PRICE IS IN COLUMNS
    if "composite_price" in ohlcv_pdf_in.columns:
        # ADD COMPOSITE PRICE
        fig_add_composite_price(fig, ohlcv_pdf_in)
    # IF THE SUPPORT LINE PRICE IS IN COLUMNS
    if "support" in ohlcv_pdf_in.columns:
        # ADD SUPPORT TREND LINE
        fig_add_support_col(fig, ohlcv_pdf_in)
    # IF THE RESISTANCE LINE PRICE IS IN COLUMNS
    if "resistance" in ohlcv_pdf_in.columns:
        # ADD RESISTANCE TREND PRICE
        fig_add_resistance_col(fig, ohlcv_pdf_in)
    # IF THERE IS A BUY ORDER
    if pd.notna(SLTP_dict_in.get("buy_ts")):
        # COLLECT THE BUY ORDER TS
        buy_order_ts = SLTP_dict_in["buy_order_ts"]
        # COLLECT THE SLTP INFORMATION
        buy_ts = SLTP_dict_in["buy_ts"]
        buy_price = SLTP_dict_in["buy_price"]
        stop_loss = SLTP_dict_in["stop_loss"]
        take_profit = SLTP_dict_in["take_profit"]
        # COLLECT THE BARS AFTER THE BUY BAR (THE SL AND TP ARE ACTIVE FROM THE BAR AFTER THE ENTRY BAR)
        active_pdf = ohlcv_pdf_in[ohlcv_pdf_in["timestamp"] > buy_ts]
        # RESOLVE THE EXIT WITH THE SHARED EXECUTION RULES (REPLACES trading_simulation.get_SLTP_sell_dict)
        exit_dict = resolve_barrier_exit_dict(active_pdf["open"].to_numpy(dtype=float), active_pdf["high"].to_numpy(dtype=float),
                                              active_pdf["low"].to_numpy(dtype=float), active_pdf["close"].to_numpy(dtype=float),
                                              [stop_loss], [take_profit], False)
        # COLLECT THE EXIT OFFSET AND REASON
        exit_offset, exit_reason = int(exit_dict["exit_offset_arr"][0]), exit_dict["exit_reason_arr"][0]
        # IF THE TRADE IS RESOLVED INSIDE THE FRAME
        if exit_offset >= 0:
            # COLLECT SELL TIMESTAMP AND PRICE
            sell_ts, sell_price = active_pdf["timestamp"].iloc[exit_offset], float(exit_dict["exit_price_arr"][0])
        # IF THE TRADE IS STILL OPEN AT THE END OF THE FRAME
        else:
            # DRAW THE TRADE UNTIL THE LAST BAR (MARKED AS "END")
            sell_ts, sell_price, exit_reason = ohlcv_pdf_in["timestamp"].iloc[-1], float(ohlcv_pdf_in["close"].iloc[-1]), "END"
        # FIG ADD TRANSACTION
        fig_add_transaction(fig, buy_ts, buy_price, sell_ts, sell_price, stop_loss, take_profit, 0, buy_order_ts, exit_reason)
    # UPDATE LAYOUT
    fig.update_layout(
        title=f"{title_str_in} Price Chart ",
        yaxis_title="Price",
        xaxis_title="Time",
        showlegend=True,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        width=width_in,
        height=height_in,
        font=dict(color="white"),
    )
    # DISPLAY FIGURE
    fig.show()

# FUNCTION: PLOT PRICE ACTION MARKET STRUCTURE OVER TIME
def plot_animated_ohlcv_PA(ohlcv_pdf_list_in, frame_duration=500, title_str_in="Price Pattern Over Time", width_in=1200, height_in=700):
    """
    Plot trend lines over time with an animated slider
    
    Args:
        ohlcv_pdf_in: DataFrame containing trend lines
        frame_duration: Duration between each candle in milliseconds (default: 1100)
        title: Title for the plot (default: "Trend Lines Over Time")
        width_in: Width of the plot (default: 1200)
        height_in: Height of the plot (default: 700)
    """
    # COPY THE DATAFRAME LIST
    tf_ohlcv_pdf_list = list(ohlcv_pdf_list_in)
    # SELECT THE LAST DATAFRAME IN THE LIST
    ohlcv_pdf = ohlcv_pdf_list_in[-1]
    # CREATE FIGURE
    fig = go.Figure()
    # CREATE FRAMES
    frames = [
        go.Frame(
            data=[
                go.Candlestick(
                    x=tf_ohlcv_pdf["timestamp"],
                    open=tf_ohlcv_pdf["open"], 
                    high=tf_ohlcv_pdf["high"],
                    low=tf_ohlcv_pdf["low"],
                    close=tf_ohlcv_pdf["close"],
                    name="Price"
                ),
                go.Scatter(
                    x=tf_ohlcv_pdf["timestamp"],
                    y=tf_ohlcv_pdf["avg_price"],
                    mode="lines",
                    line=dict(color="yellow", width=2),
                    name="Average Price"
                ),
                go.Scatter(
                    x=tf_ohlcv_pdf["timestamp"],
                    y=tf_ohlcv_pdf["extremas_pp"],
                    mode="lines", 
                    line=dict(color="cyan", width=2),
                    name="Linear Price Pattern"
                ),
                go.Scatter(
                    x=tf_ohlcv_pdf[tf_ohlcv_pdf["trend"] == -1]["timestamp"],
                    y=tf_ohlcv_pdf[tf_ohlcv_pdf["trend"] == -1]["composite_price"],
                    mode="markers", 
                    marker=dict(color="red", size=10, symbol="circle"),
                    name="Bearish"
                ),
                go.Scatter(
                    x=tf_ohlcv_pdf[tf_ohlcv_pdf["trend"] == 0]["timestamp"],
                    y=tf_ohlcv_pdf[tf_ohlcv_pdf["trend"] == 0]["composite_price"],
                    mode="markers", 
                    marker=dict(color="blue", size=10, symbol="circle"),
                    name="Consolidation"
                ),
                go.Scatter(
                    x=tf_ohlcv_pdf[tf_ohlcv_pdf["trend"] == 1]["timestamp"],
                    y=tf_ohlcv_pdf[tf_ohlcv_pdf["trend"] == 1]["composite_price"],
                    mode="markers", 
                    marker=dict(color="green", size=10, symbol="circle"),
                    name="Bullish"
                ),
                go.Scatter(
                    x=tf_ohlcv_pdf[tf_ohlcv_pdf["minima"].notna()]["timestamp"],
                    y=tf_ohlcv_pdf[tf_ohlcv_pdf["minima"].notna()]["minima"],
                    mode="markers",
                    name="Local Minima",
                    marker=dict(color="green", size=10, symbol="triangle-down")
                ),
                go.Scatter(
                    x=tf_ohlcv_pdf[tf_ohlcv_pdf["maxima"].notna()]["timestamp"],
                    y=tf_ohlcv_pdf[tf_ohlcv_pdf["maxima"].notna()]["maxima"],
                    mode="markers",
                    name="Local Maxima",
                    marker=dict(color="red", size=10, symbol="triangle-up")
                )
            ],
            name=str(idx)
        ) for idx, tf_ohlcv_pdf in enumerate(tf_ohlcv_pdf_list)
    ]

    # ADD CANDLESTICKS
    fig.add_trace(
    go.Candlestick(
                    x=ohlcv_pdf["timestamp"],
                    open=ohlcv_pdf["open"], 
                    high=ohlcv_pdf["high"],
                    low=ohlcv_pdf["low"],
                    close=ohlcv_pdf["close"],
                    name="Price"
                ))
    # ADD INITIAL TRACES
    fig.add_trace(
        go.Scatter(x=ohlcv_pdf["timestamp"],
                    y=ohlcv_pdf["avg_price"],
                    mode="lines",
                    line=dict(color="yellow", width=2),
                    name="Average Price"))
    fig.add_trace(
        go.Scatter(
            x=ohlcv_pdf["timestamp"],
            y=ohlcv_pdf["extremas_pp"],
            mode="lines", 
            line=dict(color="cyan", width=2),
            name="Linear Price Pattern"))
    fig.add_trace(
        go.Scatter(x=ohlcv_pdf[ohlcv_pdf["trend"] == -1]["timestamp"],
                    y=ohlcv_pdf[ohlcv_pdf["trend"] == -1]["composite_price"],
                    mode="markers",
                    marker=dict(color="red", size=10, symbol="circle"),
                    name="Bearish"))
    fig.add_trace(
        go.Scatter(x=ohlcv_pdf[ohlcv_pdf["trend"] == 0]["timestamp"],
                    y=ohlcv_pdf[ohlcv_pdf["trend"] == 0]["composite_price"],
                    mode="markers",
                    marker=dict(color="blue", size=10, symbol="circle"),
                    name="Consolidation"))
    fig.add_trace(
        go.Scatter(x=ohlcv_pdf[ohlcv_pdf["trend"] == 1]["timestamp"],
                    y=ohlcv_pdf[ohlcv_pdf["trend"] == 1]["composite_price"],
                    mode="markers",
                    marker=dict(color="green", size=10, symbol="circle"),
                    name="Bullish"))
    fig.add_trace(
        go.Scatter(x=ohlcv_pdf[ohlcv_pdf["minima"].notna()]["timestamp"],
                    y=ohlcv_pdf[ohlcv_pdf["minima"].notna()]["minima"],
                    mode="markers", name="Local Minima",
                    marker=dict(color="green", size=10, symbol="triangle-down")))
    fig.add_trace(
        go.Scatter(x=ohlcv_pdf[ohlcv_pdf["maxima"].notna()]["timestamp"],
                    y=ohlcv_pdf[ohlcv_pdf["maxima"].notna()]["maxima"],
                    mode="markers", name="Local Maxima",
                    marker=dict(color="red", size=10, symbol="triangle-up")))
    
    # ADD FRAMES TO THE FIGURE
    fig.frames = frames

    # ADD SLIDER
    sliders = [{
        "currentvalue": {"prefix": "Time: ", "xanchor": "right"},
        "pad": {"t": 50},
        "len": 0.9,
        "x": 0.1,
        "y": 0,
        "active": 0,
        "steps": [
            {
                "args": [
                    [str(idx)],
                    {"frame": {"duration": frame_duration,
                                "redraw": True},
                    "mode": "immediate",
                    "transition": {"duration": 0}
                    }
                ],
                "label": tf_ohlcv_pdf_list[idx]["timestamp"].iloc[-1].strftime("%H:%M"),
                "method": "animate"
            } for idx in range(len(tf_ohlcv_pdf_list))
        ]
    }]
    # CALCULATE Y-AXIS RANGE
    y_min = ohlcv_pdf["low"].min() * 0.999
    y_max = ohlcv_pdf["high"].max() * 1.001
    # UPDATE LAYOUT
    fig.update_layout(
        title=title_str_in,
        yaxis_title="Price",
        xaxis_title="Time",
        template="plotly_dark",
        width=width_in,
        height=height_in,
        font=dict(color="white"),
        xaxis_rangeslider_visible=False,
        yaxis=dict(range=[y_min, y_max]),
        xaxis=dict(range=[ohlcv_pdf["timestamp"].iloc[0], ohlcv_pdf["timestamp"].iloc[-1]]),
        sliders=sliders,
        updatemenus=[{
            "type": "buttons",
            "showactive": False,
            "y": 0,
            "x": 0.1,
            "xanchor": "right",
            "yanchor": "top",
            "pad": {"t": 50, "r": 10},
            "buttons": [
                {
                    "label": "▶️",
                    "method": "animate",
                    "args": [None, {
                        "frame": {"duration": frame_duration, "redraw": True},
                        "fromcurrent": True,  # Ensure animation starts from slider position
                        "transition": {"duration": 0}
                    }]
                },
                {
                    "label": "⏸️",
                    "method": "animate",
                    "args": [[None], {
                        "frame": {"duration": 0, "redraw": False},
                        "mode": "immediate",
                        "transition": {"duration": 0}
                    }]
                },
                {
                    "label": "🔄",
                    "method": "animate",
                    "args": [[str(0)], {  # Reset animation and slider
                        "frame": {"duration": 0, "redraw": True},
                        "mode": "immediate",
                        "transition": {"duration": 0}
                    }]
                }
            ]
        }]
    )
    # UPDATE SLIDER ACTIVE POSITION TO SYNC WITH RESET BUTTON
    fig.update_layout(
        sliders=[{
            **sliders[0],
            "active": 0  # Ensure slider starts at position 0
        }]
    )
    # DISPLAY THE FIGURE
    fig.show()

# FUNCTION: PLOT CONSOLIDATION CLUSTERS
def plot_ohlcv_market_structure(ohlcv_pdf_in, width_in=1200, height_in=700):
    # CREATE A FIGURE
    fig = go.Figure()
    # # ADD CANDLESTICK CHART
    fig_add_ohlcv(fig, ohlcv_pdf_in)
    # ADD THE EXTREMAS PRICE PATTERN
    fig_add_composite_price(fig, ohlcv_pdf_in)
    # DEFINE THE TREND COLOR NAME DICTIONARY
    trend_color_name_dict = {
        -1: {"color": "red", "name": "Bearish"},
        0: {"color": "blue", "name": "Consolidation"},
        1: {"color": "green", "name": "Bullish"},
    }
    # CALCULATE THE PERIOD
    period_seconds_duration = (ohlcv_pdf_in.timestamp.iloc[1] - ohlcv_pdf_in.timestamp.iloc[0]).total_seconds()
    # ITERATE OVER THE TRENDS
    for (segment, trend), ohlcv_pdf in ohlcv_pdf_in.groupby(["segment", "trend"]):
        # COLLECT THE TREND COLOR
        trend_color = trend_color_name_dict[trend]["color"]
        # COLLLECT THE TREND NAME
        trend_name = trend_color_name_dict[trend]["name"]
        # DUPLICATE THE LAST ROW OF THE DATAFRAME AND ADD TO DATAFRAME
        ohlcv_pdf.loc[ohlcv_pdf.index[-1] + 1] = ohlcv_pdf.iloc[-1]
        # DUPLICATE THE FIRST ROW OF THE DATAFRAME AND ADD TO DATAFRAME
        ohlcv_pdf.loc[ohlcv_pdf.index[0] - 1] = ohlcv_pdf.iloc[0]
        # SORT DATAFRAME VALUES BY INDEX
        ohlcv_pdf = ohlcv_pdf.sort_index()
        # DECREASE THE VALUE OF THE TIMESTAMP OF THE FIRST ROW BY 30 SECONDS
        ohlcv_pdf.loc[ohlcv_pdf.index[0], "timestamp"] = ohlcv_pdf.loc[ohlcv_pdf.index[0], "timestamp"] - pd.Timedelta(seconds=period_seconds_duration/2)
        # INCREASE THE VALUE OF THE TIMESTAMP OF THE LAST ROW BY 30 SECONDS
        ohlcv_pdf.loc[ohlcv_pdf.index[-1], "timestamp"] = ohlcv_pdf.loc[ohlcv_pdf.index[-1], "timestamp"] + pd.Timedelta(seconds=period_seconds_duration/2)
        # ADD LINE TO THE LOW OF THE SEGMENT
        fig.add_trace(go.Scatter(x=ohlcv_pdf.timestamp,
                                    y=ohlcv_pdf.low,
                                    mode="lines",
                                    legendgroup=f"{trend} {int(segment)}",
                                    showlegend=False,
                                    line=dict(color=trend_color, width=2)))
        # ADD LINE TO THE HIGH OF THE SEGMENT
        fig.add_trace(go.Scatter(x=ohlcv_pdf.timestamp,
                                    y=ohlcv_pdf.high,
                                    mode="lines",
                                    legendgroup=f"{trend} {int(segment)}",
                                    showlegend=False,
                                    line=dict(color=trend_color, width=2)))
        # FILL THE SPACE BETWEEN THE LOW AND HIGH OF THE SEGMENT
        fig.add_trace(go.Scatter(x=ohlcv_pdf.timestamp,
                                    y=ohlcv_pdf.low,
                                    name= f"{trend_name} {int(segment)}",
                                    text=f"{trend_name} {int(segment)}",
                                    legendgroup=f"{trend} {int(segment)}",
                                    fill="tonexty",
                                    mode= 'none',
                                    showlegend=True,
                                    fillcolor=css_color_to_rgba(trend_color, 0.5)))
    # ADD THE MINIMAS PRICE PATTERN
    fig_add_minima(fig, ohlcv_pdf_in)
    # ADD THE MAXIMAS PRICE PATTERN
    fig_add_maxima(fig, ohlcv_pdf_in)
    # UPDATE LAYOUT
    fig.update_layout(
        title="Market Structure Price Chart",
        xaxis_title="Timestamp",
        yaxis_title="Price",
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        width=width_in,
        height=height_in,
    )
    # DISPLAY THE FIGURE
    fig.show()

# FUNCTION: PLOT PATTERN INSTANCES OVER TIME
def plot_buy_sell_ohlcv(ohlcv_pdf_in, ts_buy_sell_pdf_in, title_str_in, width_in=1100, height_in=700, order_ts_in=pd.NaT):
    """
    Plot buy/sell signals on OHLCV candlestick chart with transaction details.
    
    Args:
        ohlcv_pdf_in (pd.DataFrame): OHLCV price data
        buy_sell_signal_pdf_in (pd.DataFrame): Buy/sell signals with transaction details
        title_str_in (str): Chart title
    """
    # IF THE DATAFRAME IS EMPTY
    if ts_buy_sell_pdf_in.empty:
        # DISPLAY INFORMATION
        print("Buy/Sell Signal Dataframe is empty")
        # RETURN NONE
        return
    # CREATE FIGURE
    fig = go.Figure()
    # ADD CANDLESTICK CHART
    fig_add_ohlcv(fig, ohlcv_pdf_in)
    # ITERATE OVER TRANSACTION GROUPS
    for transaction_id, transaction_pdf in ts_buy_sell_pdf_in.groupby("transaction_id"):
        # VALIDATE TRANSACTION HAS BOTH BUY AND SELL SIGNALS
        if len(transaction_pdf) < 2:
            # RAISE ERROR
            raise ValueError(f"Warning: Transaction {transaction_id} incomplete - skipping")
        # SORT BY TIMESTAMP TO ENSURE BUY COMES BEFORE SELL
        transaction_pdf = transaction_pdf.sort_values('timestamp')
        # EXTRACT BUY AND SELL DATA
        buy_order_row = transaction_pdf[transaction_pdf.signal == "order"].iloc[0]
        buy_row = transaction_pdf[transaction_pdf.signal == "buy"].iloc[0]
        sell_row = transaction_pdf[transaction_pdf.signal == "sell"].iloc[0]
        # VALIDATE BUY/SELL ORDER
        if buy_row["signal"] != "buy" or sell_row["signal"] != "sell":
            # RAISE ERROR
            raise ValueError(f"Warning: Transaction {transaction_id} has incorrect signal order - skipping")
        # EXTRACT TRANSACTION DETAILS
        order_ts = buy_order_row["timestamp"]
        buy_price = buy_row["price"]
        sell_price = sell_row["price"]
        buy_ts = buy_row["timestamp"]
        sell_ts = sell_row["timestamp"]
        stop_loss = sell_row["SL_price"]
        take_profit = sell_row["TP_price"]
        # ADD TRANSACTION TO FIGURE
        fig_add_transaction(fig, buy_ts, buy_price, sell_ts, sell_price, stop_loss, take_profit, transaction_id, order_ts)
    # UPDATE LAYOUT WITH IMPROVED STYLING
    fig.update_layout(
        title={
            'text': f"{title_str_in} Simulated Trade",
            'x': 0.5,
            'xanchor': 'center'
        },
        yaxis_title="Price ($)",
        xaxis_title='Time',
        showlegend=True,
        xaxis_rangeslider_visible=False,
        template='plotly_dark',
        width=width_in,
        height=height_in,
        font=dict(color='white', size=12),
        hoverlabel=dict(font_size=12),
    )
    # SHOW PLOT
    fig.show()

# FUNCTION: PLOT THE SIMULATED TRANSACTIONS OF THE BACKTEST SIMULATOR
def plot_transaction_ohlcv(ohlcv_pdf_in, transaction_pdf_in, title_str_in="", width_in=1100, height_in=700):
    """
    Plots the trades of backtest_simulation.simulate_decision_trading_dict on a candlestick chart:
    decision marker (white, at the decision bar), buy marker (at the entry fill), sell marker coloured by exit reason,
    SL / TP lines and areas from the entry to the exit.

    Args:
        ohlcv_pdf_in (pd.DataFrame): OHLCV bars covering the trades (trades can span several sessions)
        transaction_pdf_in (pd.DataFrame): transaction_pdf of a simulation (decision_ts, buy_ts, buy_fill_price, sell_ts,
                                           sell_fill_price, SL_price, TP_price, exit_reason, transaction_id)
        title_str_in (str): Chart title prefix
        width_in, height_in (int): Figure size
    """
    # IF THE DATAFRAME IS EMPTY
    if transaction_pdf_in is None or transaction_pdf_in.empty:
        # DISPLAY INFORMATION
        print("Transaction Dataframe is empty")
        # RETURN NONE
        return
    # CREATE FIGURE
    fig = go.Figure()
    # ADD CANDLESTICK CHART
    fig_add_ohlcv(fig, ohlcv_pdf_in, opacity_in=0.5)
    # ITERATE OVER THE TRANSACTIONS
    for _, transaction_row in transaction_pdf_in.iterrows():
        # ADD THE TRANSACTION TO THE FIGURE
        fig_add_transaction(fig,
                            transaction_row["buy_ts"],
                            transaction_row["buy_fill_price"],
                            transaction_row["sell_ts"],
                            transaction_row["sell_fill_price"],
                            transaction_row["SL_price"],
                            transaction_row["TP_price"],
                            transaction_row["transaction_id"],
                            transaction_row.get("decision_ts", pd.NaT),
                            transaction_row.get("exit_reason", None))
    # UPDATE LAYOUT
    fig.update_layout(
        title=f"{title_str_in} Simulated Trades",
        yaxis_title="Price ($)",
        xaxis_title="Time",
        showlegend=True,
        xaxis_rangeslider_visible=False,
        template="plotly_dark",
        width=width_in,
        height=height_in,
        font=dict(color="white", size=12),
    )
    # SHOW PLOT
    fig.show()
