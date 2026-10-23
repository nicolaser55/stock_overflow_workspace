"""
Workspace Tests

Run from the workspace root:   python tests/test_pipeline_shared.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified:
    1. Function defaults in ohlcv_data_utils.py / tf_ohlcv_tools.py equal the constants of config.py.
    2. Every exit rule of trade_execution.resolve_barrier_exit_dict on hand-made bars.
    3. Holding window: entry day = day 1, time limit at the close of the 10th session, NA when the data ends.
    4. The TSBAR target matrix and the simulator produce the same trade for the same decision.
    5. No look-ahead: TSCTX rows are identical when computed on data truncated just after the row.
    6. Costs and breakeven.
    9. Snapshot features (steps 01-03): snapshot k only contains bars 0..k, confirmed swings never change, TSIND has 43
       fields, TSSEG rows are complete.
   10. Plot / buy evaluation utilities run without errors (figures are built but not displayed).
   11. Bad tick rule (so/core/bad_ticks.py): planted wicks are found and cut to the body, fast real moves are kept,
       neighbours are taken within the session only, and the rule is idempotent.
"""

import os
import sys
import inspect
import warnings
import numpy as np
import pandas as pd

# ADD THE WORKSPACE ROOT TO THE PATH
WORKSPACE_PATH_STR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, WORKSPACE_PATH_STR)
sys.path.insert(0, os.path.join(WORKSPACE_PATH_STR, "tests"))
# IGNORE WARNINGS FROM LIBRARIES
warnings.filterwarnings("ignore")
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()

# IMPORT WORKSPACE MODULES
from so import config
from so.features import ohlcv_data_utils
from so.features import tf_ohlcv_tools
from so.core.datetime_utils import get_date_range_market_schedule_pdf
from so.core.trade_execution import get_ohlcv_array_dict, resolve_barrier_exit_dict, resolve_entry_trade_dict, get_horizon_window_dict, \
                            calculate_side_fee, get_affordable_share_count, get_net_return_arr, get_breakeven_tp_rate_arr, \
                            get_expected_net_return_arr, get_trade_result_str
from so.features.barrier_labels import get_date_TSBAR_pdf, get_date_market_open_ts_dict, add_TSBAR_label_cols, parse_TSBAR_cell_pdf, get_delta_col_str, format_TSBAR_pdf
from so.features.context_features import add_cum_max_col, get_session_summary_pdf, get_relative_volume_reference_pdf, get_date_TSCTX_pdf
from so.core.backtest_simulation import simulate_decision_trading_dict, simulate_buy_and_hold_dict
from so.core.schedule import get_walk_forward_fold_pdf
from synthetic_data import get_synthetic_ohlcv_pdf
import plotly.graph_objects as go
from so.features.ohlcv_data_utils import ohlcv_pdf_to_PA_tf_ohlcv_pdf_list
from so.features.snapshot_features import validate_extremas_ohlcv_pdf_list, get_date_TSIND_pdf, get_date_TSSEG_pdf
from so.features import plot_ohlcv_utils
from so.features import buy_eval_utils
from so.core.bad_ticks import get_bad_tick_pdf

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

"""
1. Configuration Consistency
"""

# FUNCTION: TEST THE FUNCTION DEFAULTS AGAINST THE CONFIGURATION
def test_config_defaults():
    # DEFINE THE EXPECTED DEFAULTS (FUNCTION, PARAMETER, CONFIG VALUE)
    expected_list = [
        (ohlcv_data_utils.add_atr_col, "period", config.PA_ATR_PERIOD),
        (ohlcv_data_utils.add_smooth_price_col, "window_in", config.PA_SMOOTH_WINDOW),
        (ohlcv_data_utils.add_minima_col, "order_in", config.PA_EXTREMA_ORDER),
        (ohlcv_data_utils.add_maxima_col, "order_in", config.PA_EXTREMA_ORDER),
        (ohlcv_data_utils.add_extremas_cols, "order_in", config.PA_EXTREMA_ORDER),
        (ohlcv_data_utils.add_composite_price_col, "bias_float_in", config.PA_COMPOSITE_BIAS),
        (ohlcv_data_utils.add_trend_col, "slope_limit_in", config.PA_TREND_SLOPE_LIMIT),
        (tf_ohlcv_tools.add_SO_cols, "k_window", config.STOCH_K_WINDOW),
        (tf_ohlcv_tools.add_SO_cols, "d_window", config.STOCH_D_WINDOW),
        (tf_ohlcv_tools.add_MACD_cols, "fast_span_in", config.MACD_FAST_SPAN),
        (tf_ohlcv_tools.add_MACD_cols, "slow_span_in", config.MACD_SLOW_SPAN),
        (tf_ohlcv_tools.add_MACD_cols, "signal_span_in", config.MACD_SIGNAL_SPAN),
        (tf_ohlcv_tools.add_RSI_col, "window_in", config.RSI_WINDOW),
        (tf_ohlcv_tools.add_BB_cols, "window_in", config.BB_WINDOW),
        (tf_ohlcv_tools.add_DC_cols, "window_in", config.DC_WINDOW),
    ]
    # ITERATE OVER THE EXPECTED DEFAULTS
    for func, param_str, expected in expected_list:
        # COLLECT THE DEFAULT
        default = inspect.signature(func).parameters[param_str].default
        # ASSERT THE DEFAULT
        assert default == expected, f"{func.__name__}.{param_str} = {default} != {expected}"
    # ASSERT THE ORIGINAL VALUES ARE UNCHANGED (THE EXISTING STEP00 PA CACHE AND TSIND FILES WERE BUILT WITH THEM)
    assert (config.PA_ATR_PERIOD, config.PA_SMOOTH_WINDOW, config.PA_EXTREMA_ORDER, config.PA_COMPOSITE_BIAS, config.PA_TREND_SLOPE_LIMIT) == (10, 4, 3, 0.4, 0.01)
    assert (config.STOCH_K_WINDOW, config.STOCH_D_WINDOW, config.RSI_WINDOW, config.BB_WINDOW, config.DC_WINDOW) == (14, 3, 14, 20, 20)
    # ASSERT THE EMBARGO COVERS THE HOLDING PERIOD
    from experiments.exp01_minute_entry import config as exp01_config
    assert exp01_config.EMBARGO_TRADING_DAYS >= config.MAX_HOLD_TRADING_DAYS
    # ASSERT EVERY CATEGORICAL FEATURE HAS LEVELS
    for col_str in config.get_feature_col_str_list(["categorical"]):
        assert col_str in config.CATEGORY_LEVEL_DICT, f"{col_str} has no category levels"
    passed("config defaults and constraints")

"""
2. Exit Rules
"""

# FUNCTION: RESOLVE ONE BARRIER PAIR ON HAND-MADE BARS
def resolve_one(bar_list_in, stop_loss_in, take_profit_in, complete_in=True):
    # CONVERT THE BARS (open, high, low, close) TO ARRAYS
    bar_arr = np.array(bar_list_in, dtype=float)
    # RESOLVE THE EXIT
    exit_dict = resolve_barrier_exit_dict(bar_arr[:, 0], bar_arr[:, 1], bar_arr[:, 2], bar_arr[:, 3], [stop_loss_in], [take_profit_in], complete_in)
    # RETURN THE OFFSET, PRICE AND REASON
    return int(exit_dict["exit_offset_arr"][0]), float(exit_dict["exit_price_arr"][0]), exit_dict["exit_reason_arr"][0]

# FUNCTION: TEST THE EXIT RULES
def test_exit_rules():
    # DEFINE THE BARRIERS (SL 99.00, TP 101.00 -> TP TRIGGER 101.01)
    SL, TP = 99.00, 101.00
    # STOP LOSS HIT DURING THE BAR -> FILL AT SL
    assert resolve_one([(100, 100.2, 99.5, 100), (100, 100.1, 98.9, 99.2)], SL, TP) == (1, 99.00, "SL")
    # GAP BELOW THE STOP LOSS -> FILL AT THE OPEN
    assert resolve_one([(100, 100.2, 99.5, 100), (98.5, 99.0, 98.2, 98.8)], SL, TP) == (1, 98.5, "SL")
    # TOUCHING THE TAKE PROFIT IS NOT ENOUGH; ONE TICK THROUGH FILLS AT TP
    assert resolve_one([(100, 101.00, 99.5, 100.9), (100.9, 101.01, 100.5, 101)], SL, TP) == (1, 101.00, "TP")
    # GAP ABOVE THE TAKE PROFIT TRIGGER -> FILL AT THE OPEN
    assert resolve_one([(100, 100.5, 99.5, 100.4), (101.50, 101.8, 101.2, 101.6)], SL, TP) == (1, 101.50, "TP")
    # OPEN EXACTLY AT TP (NOT THROUGH) THEN TRADES THROUGH -> FILL AT TP
    assert resolve_one([(101.00, 101.05, 100.9, 101.0)], SL, TP) == (0, 101.00, "TP")
    # BOTH HIT ON THE SAME BAR WITH THE OPEN BETWEEN -> STOP LOSS PRIORITY
    assert resolve_one([(100, 101.5, 98.5, 100)], SL, TP) == (0, 99.00, "SL")
    # NO HIT, COMPLETE WINDOW -> TIME LIMIT AT THE LAST CLOSE
    assert resolve_one([(100, 100.5, 99.5, 100.2), (100.2, 100.6, 99.8, 100.3)], SL, TP, True) == (1, 100.3, "TL")
    # NO HIT, INCOMPLETE WINDOW -> UNRESOLVED
    offset, price, reason = resolve_one([(100, 100.5, 99.5, 100.2)], SL, TP, False)
    assert offset == -1 and np.isnan(price) and reason == "NA"
    # NO ACTIVE BARS -> UNRESOLVED
    exit_dict = resolve_barrier_exit_dict(np.array([]), np.array([]), np.array([]), np.array([]), [SL], [TP], False)
    assert exit_dict["exit_reason_arr"][0] == "NA"
    # SEVERAL DELTAS AT ONCE ARE RESOLVED INDEPENDENTLY
    bar_arr = np.array([(100, 100.6, 99.7, 100.5), (100.5, 102.2, 100.4, 102)], dtype=float)
    exit_dict = resolve_barrier_exit_dict(bar_arr[:, 0], bar_arr[:, 1], bar_arr[:, 2], bar_arr[:, 3], [99.8, 99.0], [100.2, 101.0], True)
    assert list(exit_dict["exit_reason_arr"]) == ["SL", "TP"] and list(exit_dict["exit_offset_arr"]) == [0, 1]
    passed("exit rules (SL, gap SL, TP through, gap TP, priority, time limit, NA)")

"""
3. Holding Window, Labels And Simulator Consistency
"""

# FUNCTION: TEST THE HOLDING WINDOW
def test_horizon_window(ohlcv_array_dict_in):
    # DEFINE AN ENTRY ON THE FIRST SESSION AT 10:00
    entry_idx = ohlcv_array_dict_in["session_start_idx_arr"][0] + 30
    horizon_dict = get_horizon_window_dict(ohlcv_array_dict_in, entry_idx)
    # ASSERT THE ACTIVE WINDOW STARTS AFTER THE ENTRY BAR AND ENDS AT THE LAST BAR OF SESSION 10
    assert horizon_dict["active_start_idx"] == entry_idx + 1
    assert horizon_dict["horizon_end_idx"] == ohlcv_array_dict_in["session_end_idx_arr"][config.MAX_HOLD_TRADING_DAYS - 1]
    assert horizon_dict["horizon_complete"]
    # DEFINE AN ENTRY IN THE LAST SESSION -> INCOMPLETE
    last_entry_idx = ohlcv_array_dict_in["session_start_idx_arr"][-1] + 30
    assert not get_horizon_window_dict(ohlcv_array_dict_in, last_entry_idx)["horizon_complete"]
    passed("holding window (entry day = day 1, last-session entries incomplete)")

# FUNCTION: TEST THE TSBAR / SIMULATOR CONSISTENCY
def test_label_simulator_consistency(ohlcv_pdf_in, ohlcv_array_dict_in, date_market_open_ts_dict_in):
    # GENERATE THE TSBAR ROWS OF THE THIRD SESSION
    date_str = str(ohlcv_array_dict_in["session_date_list"][2])
    TSBAR_pdf = get_date_TSBAR_pdf(ohlcv_array_dict_in, date_market_open_ts_dict_in, date_str)
    # ASSERT THE DECISION WINDOW (09:59 -> SECOND-TO-LAST BAR) AND THE ENTRY OFFSET
    assert TSBAR_pdf["decision_ts"].iloc[0].strftime("%H:%M") == "09:59"
    assert TSBAR_pdf["entry_ts"].iloc[0].strftime("%H:%M") == "10:00"
    assert (TSBAR_pdf["entry_ts"] > TSBAR_pdf["decision_ts"]).all()
    session_last_ts = ohlcv_array_dict_in["timestamp_index"][ohlcv_array_dict_in["session_end_idx_arr"][2]]
    assert TSBAR_pdf["entry_ts"].iloc[-1] == session_last_ts
    # ASSERT THE ENTRY PRICE IS THE OPEN OF THE ENTRY BAR
    entry_open_dict = dict(zip(ohlcv_pdf_in["timestamp"], ohlcv_pdf_in["open"]))
    assert np.allclose(TSBAR_pdf["entry_price"], TSBAR_pdf["entry_ts"].map(entry_open_dict))
    # ITERATE OVER A FEW DECISIONS AND DELTAS
    for row_idx in [0, 37, 150, len(TSBAR_pdf) - 1]:
        for delta in [0.0005, 0.002, 0.01]:
            # SIMULATE A BUY AT THE DECISION
            decision_pdf = pd.DataFrame({"decision_ts": [TSBAR_pdf["decision_ts"].iloc[row_idx]], "buy_flag": [True], "delta": [delta]})
            transaction_pdf = simulate_decision_trading_dict(decision_pdf, ohlcv_array_dict_in)["transaction_pdf"]
            # PARSE THE TSBAR CELL
            cell_pdf = parse_TSBAR_cell_pdf(TSBAR_pdf[get_delta_col_str(delta)].iloc[[row_idx]])
            # ASSERT THE SAME EXIT
            assert transaction_pdf["exit_reason"].iloc[0] == cell_pdf["exit_reason"].iloc[0]
            assert np.isclose(transaction_pdf["sell_raw_price"].iloc[0], cell_pdf["exit_price"].iloc[0])
            assert transaction_pdf["hold_bar_count"].iloc[0] == cell_pdf["exit_bar_count"].iloc[0]
    passed("TSBAR target matrix == simulator (decision window, entry at next open, same exits)")
    # RETURN THE TSBAR ROWS
    return TSBAR_pdf

# FUNCTION: TEST THE LABEL COLUMNS
def test_label_cols(TSBAR_pdf_in):
    # PARSE THE LABELS
    label_pdf = add_TSBAR_label_cols(TSBAR_pdf_in, [0.001, 0.005], drop_cell_cols_in=True)
    # ASSERT THE LABEL COLUMNS
    for delta_col_str in ["0.0010", "0.0050"]:
        assert set(label_pdf[f"y_tp_{delta_col_str}"].dropna().unique()) <= {0.0, 1.0}
        tp_mask = label_pdf[f"exit_reason_{delta_col_str}"] == "TP"
        assert (label_pdf.loc[tp_mask, f"y_tp_{delta_col_str}"] == 1).all()
    # ASSERT THE RAW CELLS WERE DROPPED
    assert "0.0010" not in label_pdf.columns
    passed("label columns (y_tp, net_return, exit_bar_count, exit_reason)")

"""
4. Costs
"""

# FUNCTION: TEST THE COST FUNCTIONS
def test_costs():
    # SIDE FEE: MINIMUM, PER SHARE, MAXIMUM
    assert calculate_side_fee(10, 500) == 1.0
    assert calculate_side_fee(1000, 500) == 5.0
    assert calculate_side_fee(1000, 0.1) == 1.0  # the minimum takes precedence over the 1% cap (as in the original function)
    # AFFORDABLE SHARES INCLUDE THE BUY FEE
    share_count = get_affordable_share_count(10_000, 500.01)
    assert share_count * 500.01 + calculate_side_fee(share_count, 500.01) <= 10_000
    assert (share_count + 1) * 500.01 + calculate_side_fee(share_count + 1, 500.01) > 10_000
    # NET RETURN OF A TP AND AN SL AT $100 WITH A 1% DELTA
    net_return_arr = get_net_return_arr([100.0, 100.0], [101.0, 99.0], ["TP", "SL"])
    assert np.isclose(net_return_arr[0], (101.0 - 100.01 - 0.01) / 100.01)
    assert np.isclose(net_return_arr[1], (99.0 - 0.01 - 100.01 - 0.01) / 100.01)
    # BREAKEVEN RATE MATCHES THE HAND CALCULATION ($700, 0.10% -> about 51.8%)
    assert abs(get_breakeven_tp_rate_arr([700.0], 0.001)[0] - 0.5177) < 0.001
    # THE EXPECTED RETURN AT THE BREAKEVEN PROBABILITY IS ABOUT ZERO
    p_star = get_breakeven_tp_rate_arr([700.0], 0.001)[0]
    assert abs(get_expected_net_return_arr([p_star], [700.0], 0.001)[0]) < 1e-6
    # RESULT LABELS
    assert get_trade_result_str(0.001) == "NULL" and get_trade_result_str(1.0) == "WIN" and get_trade_result_str(-1.0) == "LOSS"
    passed("costs (fees, share count, net return, breakeven, expected return, NULL result)")

"""
5. Context Features (No Look-Ahead)
"""

# FUNCTION: TEST THE CONTEXT FEATURES
def test_context_no_lookahead(ohlcv_pdf_in, market_schedule_pdf_in):
    # DEFINE THE SCHEDULE DICTIONARIES
    date_market_open_ts_dict = get_date_market_open_ts_dict(market_schedule_pdf_in)
    date_market_schedule_dict = dict(zip(pd.to_datetime(market_schedule_pdf_in["date"]).dt.date,
                                         zip(market_schedule_pdf_in["market_open_ts"], market_schedule_pdf_in["market_close_ts"])))
    # DEFINE THE TEST DATE AND THE CUT TIMESTAMP (MIDDAY)
    date_object = sorted(ohlcv_pdf_in["date"].unique())[25]
    cut_ts = ohlcv_pdf_in[ohlcv_pdf_in["date"] == date_object]["timestamp"].iloc[150]
    # COMPUTE THE FEATURES ON THE FULL DATA AND ON THE TRUNCATED DATA
    feature_pdf_list = []
    for data_pdf in [ohlcv_pdf_in, ohlcv_pdf_in[ohlcv_pdf_in["timestamp"] <= cut_ts]]:
        data_pdf = add_cum_max_col(data_pdf.copy())
        summary_pdf = get_session_summary_pdf(data_pdf)
        reference_pdf = get_relative_volume_reference_pdf(data_pdf, date_market_open_ts_dict)
        feature_pdf_list.append(get_date_TSCTX_pdf(data_pdf, summary_pdf, reference_pdf, date_market_schedule_dict, str(date_object)))
    # ASSERT THE ROWS UP TO THE CUT ARE IDENTICAL
    full_pdf = feature_pdf_list[0][feature_pdf_list[0]["timestamp"] <= cut_ts].reset_index(drop=True)
    truncated_pdf = feature_pdf_list[1].reset_index(drop=True)
    pd.testing.assert_frame_equal(full_pdf, truncated_pdf)
    # ASSERT THE TIME FEATURES
    assert full_pdf["minutes_since_open"].iloc[0] == 0
    assert feature_pdf_list[0]["minutes_to_close"].iloc[-1] == 0
    passed("context features have no look-ahead (identical on truncated data)")
    # RETURN THE FULL FEATURES
    return feature_pdf_list[0]

"""
6. Walk-Forward Schedule
"""


"""
7. Weights, Sampling And Signal Check
"""







"""
8. End-To-End Fold
"""


"""
9. Snapshot Features (steps 01-03)
"""

# FUNCTION: TEST THE SNAPSHOT FEATURES ON THE FIRST BARS OF A SESSION
def test_snapshot_features(ohlcv_pdf_in, bar_count_in=60):
    # KEEP THE FIRST BARS OF THE FIRST SESSION (FULL SESSIONS TAKE ABOUT 15 SECONDS PER STEP)
    date_object = ohlcv_pdf_in["date"].iloc[0]
    session_pdf = ohlcv_pdf_in[ohlcv_pdf_in["date"] == date_object].head(bar_count_in).reset_index(drop=True)
    # GENERATE THE SNAPSHOTS
    snapshot_pdf_list = ohlcv_pdf_to_PA_tf_ohlcv_pdf_list(session_pdf, alert_in=False)
    # ASSERT ONE SNAPSHOT PER BAR, AND SNAPSHOT K ENDS AT BAR K (NO LATER BARS)
    assert len(snapshot_pdf_list) == bar_count_in
    for k, snapshot_pdf in enumerate(snapshot_pdf_list):
        assert len(snapshot_pdf) == k + 1
        assert snapshot_pdf["timestamp"].iloc[-1] == session_pdf["timestamp"].iloc[k]
    # ASSERT CONFIRMED SWINGS NEVER CHANGE
    assert validate_extremas_ohlcv_pdf_list(snapshot_pdf_list, alert_in=False)
    # GENERATE THE TSIND ROWS
    TSIND_pdf = get_date_TSIND_pdf(session_pdf, str(date_object), [snapshot_pdf.copy() for snapshot_pdf in snapshot_pdf_list])
    assert TSIND_pdf.shape == (bar_count_in, 43)
    assert (TSIND_pdf["timestamp"].to_numpy() == session_pdf["timestamp"].to_numpy()).all()
    # ASSERT THE LAGGED PRICE-ACTION FIELDS EQUAL ROW -2 OF THE SNAPSHOT
    k = bar_count_in - 1
    lag_value = snapshot_pdf_list[k]["smooth_price"].iloc[-2]
    assert (np.isnan(lag_value) and np.isnan(TSIND_pdf["smooth_price"].iloc[k])) or np.isclose(lag_value, TSIND_pdf["smooth_price"].iloc[k])
    # GENERATE THE TSSEG ROWS
    ts_cum_max_dict = dict(zip(session_pdf["timestamp"], session_pdf["high"].cummax()))
    TSSEG_pdf = get_date_TSSEG_pdf(session_pdf, ts_cum_max_dict, str(date_object), [snapshot_pdf.copy() for snapshot_pdf in snapshot_pdf_list])
    assert len(TSSEG_pdf) == bar_count_in
    assert (TSSEG_pdf["seg_cs_count"] >= 0).all()
    assert TSSEG_pdf["seg"].is_monotonic_increasing
    passed(f"snapshot features (snapshot k = bars 0..k, swings never change, TSIND {TSIND_pdf.shape[1]} fields, TSSEG {TSSEG_pdf.shape[1]} fields)")
    # RETURN THE LAST SNAPSHOT (USED BY THE PLOT TEST)
    return snapshot_pdf_list[-1]

"""
10. Plot And Buy Evaluation Utilities
"""

# FUNCTION: TEST THE PLOT AND BUY EVALUATION UTILITIES (FIGURES ARE BUILT, NOT DISPLAYED)
def test_plot_utils(ohlcv_pdf_in, ohlcv_array_dict_in, TSBAR_pdf_in, snapshot_pdf_in):
    # DISABLE FIGURE DISPLAY AND COUNT THE FIGURES
    shown_list = []
    original_show = go.Figure.show
    go.Figure.show = lambda self, *args, **kwargs: shown_list.append(self)
    try:
        # COLLECT THE SESSION OF THE TSBAR ROWS
        date_object = TSBAR_pdf_in["decision_ts"].iloc[0].date()
        session_pdf = ohlcv_pdf_in[ohlcv_pdf_in["date"] == date_object]
        # SNAPSHOT PLOTS (STEP 00)
        plot_ohlcv_utils.plot_ohlcv_extremas(snapshot_pdf_in, "test")
        plot_ohlcv_utils.plot_ohlcv(snapshot_pdf_in, {}, "test")
        plot_ohlcv_utils.plot_ohlcv_market_structure(snapshot_pdf_in)
        # SUBPLOT ROW / COLUMN ROUTING (A PLAIN FIGURE MUST IGNORE ROW / COLUMN, A SUBPLOT FIGURE MUST USE THEM)
        from plotly.subplots import make_subplots
        plain_fig = go.Figure()
        plot_ohlcv_utils.fig_add_ohlcv(plain_fig, session_pdf, row_in=1, col_in=1)
        subplot_fig = make_subplots(rows=2, cols=1)
        plot_ohlcv_utils.fig_add_ohlcv(subplot_fig, session_pdf, row_in=2, col_in=1)
        assert subplot_fig.data[0].yaxis == "y2"
        # TRADES OF THE TSBAR ROWS AT ONE DELTA
        trade_pdf = buy_eval_utils.get_date_TSBAR_trade_pdf(TSBAR_pdf_in, 0.002, ohlcv_array_dict_in)
        assert len(trade_pdf) == len(TSBAR_pdf_in)
        # ASSERT EVERY RESOLVED EXIT IS AFTER THE ENTRY (SL / TP ARE ACTIVE FROM THE BAR AFTER THE ENTRY)
        resolved_pdf = trade_pdf[trade_pdf["exit_ts"].notna()]
        assert (resolved_pdf["exit_ts"] > resolved_pdf["entry_ts"]).all()
        assert set(trade_pdf["y_tp"].dropna().unique()) <= {0, 1}
        # IDEAL VS PRED (EVERY 30 MINUTES)
        ts_BS_dict = {ts: 1 for ts in TSBAR_pdf_in["decision_ts"] if ts.minute in (0, 30)}
        stat_dict = buy_eval_utils.get_ideal_vs_pred_dict(trade_pdf, ts_BS_dict)
        assert stat_dict["pred_count"] == len(ts_BS_dict)
        assert np.isclose(stat_dict["ideal_rate"], trade_pdf["y_tp"].dropna().mean())
        buy_eval_utils.plot_ideal_pred_buy_data(session_pdf, TSBAR_pdf_in, ohlcv_array_dict_in, 0.002, str(date_object), ts_BS_dict)
        # SIMULATED TRADES
        decision_pdf = pd.DataFrame({"decision_ts": list(ts_BS_dict), "buy_flag": True, "delta": 0.002})
        transaction_pdf = simulate_decision_trading_dict(decision_pdf, ohlcv_array_dict_in)["transaction_pdf"]
        plot_ohlcv_utils.plot_transaction_ohlcv(ohlcv_pdf_in[ohlcv_pdf_in["timestamp"] <= transaction_pdf["sell_ts"].max()].tail(2000), transaction_pdf, "test")
    finally:
        # RESTORE FIGURE DISPLAY
        go.Figure.show = original_show
    # ASSERT EVERY PLOT PRODUCED A FIGURE
    assert len(shown_list) == 5, len(shown_list)
    passed(f"plot / buy evaluation utilities ({len(shown_list)} figures built, subplot routing, ideal vs pred statistics)")

# FUNCTION: TEST THE BAD TICK RULE
def test_bad_tick_rule(ohlcv_pdf_in):
    """
    Plants bad wicks and real fast moves in synthetic bars and checks the rule of so/core/bad_ticks.py.

    Args:
        ohlcv_pdf_in (pd.DataFrame): Synthetic minute bars
    """
    # THE SYNTHETIC DATA HAS NO BAD TICKS
    assert get_bad_tick_pdf(ohlcv_pdf_in).empty
    # COPY TEN SESSIONS OF BARS
    test_pdf = ohlcv_pdf_in[ohlcv_pdf_in["date"].isin(sorted(ohlcv_pdf_in["date"].unique())[:10])].copy().reset_index(drop=True)
    session_first_idx_arr = test_pdf.index[test_pdf["date"].ne(test_pdf["date"].shift(1))].to_numpy()
    # PLANT A HIGH WICK 5% ABOVE THE BODY IN THE MIDDLE OF SESSION 1 (EXPECTED: FLAGGED, CUT TO THE BODY HIGH)
    high_idx = session_first_idx_arr[1] + 100
    test_pdf.loc[high_idx, "high"] = test_pdf.loc[high_idx, ["open", "close"]].max() * 1.05
    # PLANT A LOW WICK 4% BELOW THE BODY IN THE MIDDLE OF SESSION 2 (EXPECTED: FLAGGED, CUT TO THE BODY LOW)
    low_idx = session_first_idx_arr[2] + 200
    test_pdf.loc[low_idx, "low"] = test_pdf.loc[low_idx, ["open", "close"]].min() * 0.96
    # PLANT A REAL 5% DROP IN SESSION 3: THE BAR CLOSES 5% LOWER AND THE REST OF THE SESSION STAYS THERE (EXPECTED: KEPT)
    drop_idx = session_first_idx_arr[3] + 150
    session_end_idx = session_first_idx_arr[4] - 1
    test_pdf.loc[drop_idx + 1:session_end_idx, ["open", "high", "low", "close"]] *= 0.95
    test_pdf.loc[drop_idx, "close"] = test_pdf.loc[drop_idx + 1, "open"]
    test_pdf.loc[drop_idx, "low"] = test_pdf.loc[drop_idx, "close"] * 0.999
    # PLANT A SESSION GAP: SESSION 5 OPENS 6% ABOVE THE PREVIOUS CLOSE, WITH A BAD LOW WICK 5% BELOW ITS FIRST BAR
    # (EXPECTED: FLAGGED; THE PREVIOUS SESSION'S CLOSE MUST NOT BE USED AS A NEIGHBOUR, IT WOULD HIDE THE WICK)
    gap_idx = session_first_idx_arr[5]
    test_pdf.loc[gap_idx:session_first_idx_arr[6] - 1, ["open", "high", "low", "close"]] *= 1.06
    test_pdf.loc[gap_idx, "low"] = test_pdf.loc[gap_idx, ["open", "close"]].min() * 0.95
    # DETECT THE BAD TICKS
    bad_tick_pdf = get_bad_tick_pdf(test_pdf)
    flagged_set = set(zip(bad_tick_pdf["row_idx"], bad_tick_pdf["column"]))
    assert flagged_set == {(high_idx, "high"), (low_idx, "low"), (gap_idx, "low")}, flagged_set
    # THE NEW VALUES ARE THE BODY
    for _, row in bad_tick_pdf.iterrows():
        body_float = test_pdf.loc[row["row_idx"], ["open", "close"]].max() if row["column"] == "high" else test_pdf.loc[row["row_idx"], ["open", "close"]].min()
        assert np.isclose(row["new_value"], body_float)
    # THE SAME BAD LOW IS HIDDEN IF THE NEIGHBOUR IS TAKEN ACROSS SESSIONS (SANITY CHECK OF THE PLANTED CASE)
    previous_close_float = test_pdf.loc[gap_idx - 1, "close"]
    assert test_pdf.loc[gap_idx, "low"] > previous_close_float * 0.97
    # APPLY THE CORRECTIONS: THE RULE FINDS NOTHING ON A SECOND PASS (IDEMPOTENT)
    for _, row in bad_tick_pdf.iterrows():
        test_pdf.loc[row["row_idx"], row["column"]] = row["new_value"]
    assert get_bad_tick_pdf(test_pdf).empty
    # DISPLAY INFORMATION
    passed("bad tick rule (3 planted wicks cut to the body, a real 5% drop kept, neighbours within the session, idempotent)")




"""
Runner
"""

# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    # GENERATE THE SYNTHETIC DATA (ABOUT 16 MONTHS, INCLUDING HALF DAYS)
    print("Generating synthetic data...")
    synthetic_ohlcv_pdf = get_synthetic_ohlcv_pdf("2023-06-01", "2024-09-30")
    synthetic_ohlcv_array_dict = get_ohlcv_array_dict(synthetic_ohlcv_pdf)
    synthetic_market_schedule_pdf = get_date_range_market_schedule_pdf("2023-06-01", "2024-09-30")
    synthetic_date_market_open_ts_dict = get_date_market_open_ts_dict(synthetic_market_schedule_pdf)
    # RUN THE TESTS
    test_config_defaults()
    test_exit_rules()
    test_horizon_window(synthetic_ohlcv_array_dict)
    synthetic_TSBAR_pdf = test_label_simulator_consistency(synthetic_ohlcv_pdf, synthetic_ohlcv_array_dict, synthetic_date_market_open_ts_dict)
    test_label_cols(synthetic_TSBAR_pdf)
    test_costs()
    test_context_no_lookahead(synthetic_ohlcv_pdf, synthetic_market_schedule_pdf)
    synthetic_snapshot_pdf = test_snapshot_features(synthetic_ohlcv_pdf)
    test_plot_utils(synthetic_ohlcv_pdf, synthetic_ohlcv_array_dict, synthetic_TSBAR_pdf, synthetic_snapshot_pdf)
    test_bad_tick_rule(synthetic_ohlcv_pdf)
    print("\nAll tests passed ✅")
