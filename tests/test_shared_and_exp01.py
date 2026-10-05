"""
Workspace Tests

Run from the workspace root:   python tests/test_shared_and_exp01.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified:
    1. Function defaults in ohlcv_data_utils.py / tf_ohlcv_tools.py equal the constants of config.py.
    2. Every exit rule of trade_execution.resolve_barrier_exit_dict on hand-made bars.
    3. Holding window: entry day = day 1, time limit at the close of the 10th session, NA when the data ends.
    4. The TSBAR target matrix and the simulator produce the same trade for the same decision.
    5. No look-ahead: TSCTX rows are identical when computed on data truncated just after the row.
    6. Walk-forward schedule: embargo gaps and window lengths.
    7. Uniqueness weights, costs, breakeven and the signal check on planted / random signals.
    8. End-to-end fold run on synthetic data (fit -> policy -> simulation -> baselines).
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

# IMPORT WORKSPACE MODULES
from so import config
from so.features import ohlcv_data_utils
from so.features import tf_ohlcv_tools
from so.core.datetime_utils import get_date_range_market_schedule_pdf
from so.core.trade_execution import get_ohlcv_array_dict, resolve_barrier_exit_dict, resolve_entry_trade_dict, get_horizon_window_dict, \
                            calculate_side_fee, get_affordable_share_count, get_net_return_arr, get_breakeven_tp_rate_arr, \
                            get_expected_net_return_arr, get_trade_result_str
from so.features.barrier_labels import get_date_TSBAR_pdf, get_date_market_open_ts_dict, add_TSBAR_label_cols, parse_TSBAR_cell_pdf, get_delta_col_str
from so.features.context_features import add_cum_max_col, get_session_summary_pdf, get_relative_volume_reference_pdf, get_date_TSCTX_pdf
from experiments.exp01_minute_entry import config as exp_config
from experiments.exp01_minute_entry.model_dataset import apply_sampling_pdf, get_uniqueness_weight_arr, encode_feature_pdf
from so.core.backtest_simulation import simulate_decision_trading_dict, simulate_buy_and_hold_dict
from experiments.exp01_minute_entry.signal_check import get_signal_check_pdf, get_signal_check_verdict_dict
from so.core.schedule import get_walk_forward_fold_pdf
from experiments.exp01_minute_entry import walk_forward
from experiments.exp01_minute_entry.walk_forward import get_fold_pdf, run_walk_forward_fold_dict, run_window_with_baseline_dict, get_window_pdf
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
    assert exp_config.EMBARGO_TRADING_DAYS >= config.MAX_HOLD_TRADING_DAYS
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

# FUNCTION: TEST THE WALK-FORWARD SCHEDULE
def test_walk_forward_schedule():
    # BUILD A REAL CALENDAR FROM 2005 TO 2026
    session_date_list = list(pd.to_datetime(get_date_range_market_schedule_pdf("2005-01-03", "2026-08-13")["date"]).dt.date)
    fold_pdf = get_fold_pdf(session_date_list)
    # COLLECT THE SESSION POSITIONS
    position_dict = {d: i for i, d in enumerate(session_date_list)}
    # ITERATE OVER THE FOLDS
    for _, fold_row in fold_pdf.iterrows():
        # ASSERT THE EMBARGO GAPS (STRICTLY MORE THAN THE HOLDING PERIOD BETWEEN WINDOWS)
        assert position_dict[fold_row["valid_start"]] - position_dict[fold_row["train_end"]] - 1 == exp_config.EMBARGO_TRADING_DAYS
        assert position_dict[fold_row["test_start"]] - position_dict[fold_row["valid_end"]] - 1 == exp_config.EMBARGO_TRADING_DAYS
        assert fold_row["refit_end"] == fold_row["valid_end"]
        # ASSERT THE WINDOW ORDER
        for train_years in exp_config.TRAIN_WINDOW_YEARS_LIST:
            assert fold_row[f"train_start_{train_years}y"] < fold_row["train_end"] < fold_row["valid_start"] <= fold_row["valid_end"] < fold_row["test_start"] <= fold_row["test_end"]
    # ASSERT THE LATEST TEST WINDOW ENDS ON THE LAST SESSION AND IS ABOUT 3 MONTHS LONG
    assert fold_pdf["test_end"].iloc[-1] == session_date_list[-1]
    assert 55 <= position_dict[fold_pdf["test_end"].iloc[-1]] - position_dict[fold_pdf["test_start"].iloc[-1]] + 1 <= 70
    # ASSERT THE FIRST FOLD LEAVES 10 YEARS OF TRAINING DATA
    assert fold_pdf["train_start_10y"].iloc[0] >= session_date_list[0]
    passed(f"walk-forward schedule ({len(fold_pdf)} folds, first test {fold_pdf['test_start'].iloc[0]}, embargo {exp_config.EMBARGO_TRADING_DAYS} sessions)")

"""
7. Weights, Sampling And Signal Check
"""

# FUNCTION: TEST THE UNIQUENESS WEIGHTS
def test_uniqueness_weights(ohlcv_array_dict_in):
    # DEFINE THREE TRADES: TWO OVERLAPPING, ONE ALONE
    ts_index = ohlcv_array_dict_in["timestamp_index"]
    test_pdf = pd.DataFrame({"entry_ts": [ts_index[100], ts_index[100], ts_index[1000]], "exit_bar_count_0.0010": [9, 9, 9]})
    weight_arr = get_uniqueness_weight_arr(test_pdf, 0.001, ohlcv_array_dict_in)
    # ASSERT THE ISOLATED TRADE WEIGHS TWICE AS MUCH AS EACH OVERLAPPING TRADE
    assert np.isclose(weight_arr[2] / weight_arr[0], 2.0) and np.isclose(weight_arr.mean(), 1.0)
    passed("uniqueness weights")

# FUNCTION: TEST THE SIGNAL CHECK
def test_signal_check():
    # CREATE A RANDOM LABELED DATASET OVER TWO YEARS
    rng = np.random.default_rng(1)
    row_count = 20_000
    ts_series = pd.Series(pd.date_range("2020-01-01 10:00", periods=row_count, freq="47min", tz="America/New_York"))
    planted_arr = rng.random(row_count)
    # THE PLANTED FEATURE RAISES THE TP PROBABILITY TO 75% IN ITS TOP DECILE
    y_arr = (rng.random(row_count) < np.where(planted_arr > 0.9, 0.75, 0.45)).astype(float)
    test_pdf = pd.DataFrame({"decision_ts": ts_series, "entry_price": 700.0, "rsi": planted_arr * 100, "stoch_k": rng.random(row_count) * 100,
                             "y_tp_0.0050": y_arr, "net_return_0.0050": np.where(y_arr == 1, 0.0049, -0.0051)})
    train_pdf, valid_pdf = test_pdf.iloc[:14_000], test_pdf.iloc[14_000:]
    # RUN THE SIGNAL CHECK
    signal_pdf = get_signal_check_pdf(train_pdf, valid_pdf, ["rsi", "stoch_k"], [0.005], alert_in=False, iteration_count_in=300)
    verdict_dict = get_signal_check_verdict_dict(signal_pdf)
    # ASSERT THE PLANTED SIGNAL IS FOUND AND THE NOISE FEATURE IS NOT
    assert verdict_dict["verdict"] == "CONTINUE" and verdict_dict["signal_feature_list"] == ["rsi"]
    # ASSERT THE CHANCE COUNT AND THE DISTINCT BIN COUNT
    assert verdict_dict["expected_chance_signal_count"] == round(verdict_dict["test_count"] * 2 * 0.025 ** 2, 1)
    assert 1 <= verdict_dict["signal_bin_count"] <= verdict_dict["signal_count"]
    passed(f"signal check (planted signal found, noise rejected; {verdict_dict['test_count']} tests)")


# FUNCTION: TEST THAT MARKET DRIFT ALONE IS NOT A SIGNAL (BASE-RATE REFERENCE, NEW IN exp01 1.0)
def test_signal_check_drift_only():
    # CREATE A DATASET WHERE EVERY ROW HAS THE SAME 62% TP PROBABILITY (DRIFT), WELL ABOVE BREAK-EVEN, AND NO FEATURE EFFECT
    rng = np.random.default_rng(2)
    row_count = 20_000
    ts_series = pd.Series(pd.date_range("2020-01-01 10:00", periods=row_count, freq="47min", tz="America/New_York"))
    y_arr = (rng.random(row_count) < 0.62).astype(float)
    test_pdf = pd.DataFrame({"decision_ts": ts_series, "entry_price": 700.0, "rsi": rng.random(row_count) * 100,
                             "y_tp_0.0050": y_arr, "net_return_0.0050": np.where(y_arr == 1, 0.0049, -0.0051)})
    signal_pdf = get_signal_check_pdf(test_pdf.iloc[:14_000], test_pdf.iloc[14_000:], ["rsi"], [0.005], alert_in=False, iteration_count_in=300)
    verdict_dict = get_signal_check_verdict_dict(signal_pdf)
    # ASSERT EVERY TRAINING BIN IS ABOVE BREAK-EVEN (THE v1 CHECK WOULD HAVE PASSED THEM) BUT NONE IS A SIGNAL
    assert (signal_pdf["train_tp_rate_ci_low"] > signal_pdf["train_breakeven_tp_rate"]).sum() >= 8
    assert verdict_dict["verdict"] == "STOP" and verdict_dict["signal_count"] == 0
    passed(f"signal check ignores drift (bins above break-even: {int((signal_pdf['train_tp_rate_ci_low'] > signal_pdf['train_breakeven_tp_rate']).sum())}, signals: 0)")

# FUNCTION: TEST THE MONTH MINIMUM OF THE SIGNAL CHECK
def test_signal_check_month_minimum():
    # CREATE A DATASET WHOSE VALIDATION ROWS COVER ONLY TWO CALENDAR MONTHS, WITH A STRONG PLANTED SIGNAL
    rng = np.random.default_rng(3)
    train_ts = pd.Series(pd.date_range("2018-01-01 10:00", periods=14_000, freq="47min", tz="America/New_York"))
    valid_ts = pd.Series(pd.date_range("2021-03-01 10:00", periods=1_500, freq="47min", tz="America/New_York"))
    def make_pdf(ts_series_in):
        feature_arr = rng.random(len(ts_series_in))
        y_arr = (rng.random(len(ts_series_in)) < np.where(feature_arr > 0.9, 0.9, 0.45)).astype(float)
        return pd.DataFrame({"decision_ts": ts_series_in, "entry_price": 700.0, "rsi": feature_arr * 100, "y_tp_0.0050": y_arr,
                             "net_return_0.0050": np.where(y_arr == 1, 0.0049, -0.0051)})
    train_pdf, valid_pdf = make_pdf(train_ts), make_pdf(valid_ts)
    # ASSERT THE SIGNAL IS FOUND WITHOUT THE MINIMUM AND REJECTED WITH THE PROTOCOL MINIMUM (6 MONTHS)
    without_dict = get_signal_check_verdict_dict(get_signal_check_pdf(train_pdf, valid_pdf, ["rsi"], [0.005], alert_in=False, iteration_count_in=300, min_month_count_in=None))
    with_dict = get_signal_check_verdict_dict(get_signal_check_pdf(train_pdf, valid_pdf, ["rsi"], [0.005], alert_in=False, iteration_count_in=300))
    assert without_dict["signal_count"] > 0 and with_dict["signal_count"] == 0
    passed(f"signal check month minimum (validation of {valid_ts.dt.month.nunique()} months: signal without the minimum, none with {exp_config.SIGNAL_CHECK_MIN_MONTH_COUNT})")

"""
8. End-To-End Fold
"""

# FUNCTION: TEST AN END-TO-END FOLD ON SYNTHETIC DATA
def test_end_to_end_fold(ohlcv_pdf_in, ohlcv_array_dict_in, market_schedule_pdf_in):
    # DEFINE THE SCHEDULE DICTIONARIES
    date_market_open_ts_dict = get_date_market_open_ts_dict(market_schedule_pdf_in)
    date_market_schedule_dict = dict(zip(pd.to_datetime(market_schedule_pdf_in["date"]).dt.date,
                                         zip(market_schedule_pdf_in["market_open_ts"], market_schedule_pdf_in["market_close_ts"])))
    # PREPARE THE CONTEXT INPUTS
    data_pdf = add_cum_max_col(ohlcv_pdf_in.copy())
    summary_pdf = get_session_summary_pdf(data_pdf)
    reference_pdf = get_relative_volume_reference_pdf(data_pdf, date_market_open_ts_dict)
    # BUILD AN IN-MEMORY DATASET (TSBAR + TSCTX + A FEW RAW FEATURES)
    dataset_pdf_list = []
    for date_object in ohlcv_array_dict_in["session_date_list"]:
        TSBAR_pdf = get_date_TSBAR_pdf(ohlcv_array_dict_in, date_market_open_ts_dict, str(date_object), [0.001, 0.002, 0.005])
        TSCTX_pdf = get_date_TSCTX_pdf(data_pdf, summary_pdf, reference_pdf, date_market_schedule_dict, str(date_object))
        bar_pdf = data_pdf[data_pdf["date"] == date_object][["timestamp", "close"]]
        merged_pdf = TSBAR_pdf.merge(TSCTX_pdf.rename(columns={"timestamp": "decision_ts"}), on="decision_ts", how="left") \
                              .merge(bar_pdf.rename(columns={"timestamp": "decision_ts"}), on="decision_ts", how="left")
        merged_pdf["date"] = date_object
        dataset_pdf_list.append(merged_pdf)
    dataset_pdf = add_TSBAR_label_cols(pd.concat(dataset_pdf_list, ignore_index=True), [0.001, 0.002, 0.005], drop_cell_cols_in=True)
    # ASSERT THE INTERVAL SAMPLING KEEPS 10:00, 10:15, ...
    sampled_pdf = apply_sampling_pdf(dataset_pdf, "interval", 15)
    assert set(sampled_pdf["entry_ts"].dt.minute.unique()) <= {0, 15, 30, 45}
    # BUILD A SHORT SCHEDULE (1-YEAR TRAINING, 1-MONTH WINDOWS, TO FIT THE SYNTHETIC DATA)
    fold_pdf = get_walk_forward_fold_pdf(ohlcv_array_dict_in["session_date_list"], exp_config.EMBARGO_TRADING_DAYS, [1], test_window_months_in=1,
                                         validation_window_months_in=1, step_months_in=1, max_fold_count_in=1)
    assert len(fold_pdf) == 1
    # DEFINE THE FEATURES
    feature_col_str_list = ["minutes_since_open", "day_of_week", "intraday_return_pct", "overnight_gap_pct", "relative_volume"]
    # RUN THE FOLD (SMALL MODEL SETTINGS)
    original_param_dict = dict(exp_config.LGBM_PARAM_DICT)
    exp_config.LGBM_PARAM_DICT.update({"n_estimators": 30, "min_child_samples": 50})
    original_run_count = exp_config.RANDOM_BASELINE_RUN_COUNT
    exp_config.RANDOM_BASELINE_RUN_COUNT = 3
    try:
        result_dict = walk_forward.run_walk_forward_fold_dict(fold_pdf.iloc[0], sampled_pdf, dataset_pdf, ohlcv_array_dict_in, feature_col_str_list,
                                                              delta_list_in=[0.001, 0.002, 0.005], train_window_years_list_in=[1], ev_threshold_list_in=[-1.0, 0.0], alert_in=False)
    finally:
        exp_config.LGBM_PARAM_DICT.clear()
        exp_config.LGBM_PARAM_DICT.update(original_param_dict)
        exp_config.RANDOM_BASELINE_RUN_COUNT = original_run_count
    # ASSERT THE OUTPUTS
    assert len(result_dict["selection_pdf"]) == 2
    baseline_pdf = result_dict["baseline_metric_pdf"]
    assert {"model", "fixed_time"} <= set(baseline_pdf["baseline"])
    assert len(result_dict["cost_sensitivity_pdf"]) == len(config.COST_SENSITIVITY_SLIPPAGE_LIST)
    # ASSERT HIGHER SLIPPAGE NEVER IMPROVES THE SAME DECISIONS
    cost_return_arr = result_dict["cost_sensitivity_pdf"]["total_return"].to_numpy()
    assert all(np.diff(cost_return_arr) <= 1e-12)
    # ASSERT TRADES NEVER OVERLAP AND ALWAYS ENTER AFTER THE DECISION
    transaction_pdf = result_dict["test_transaction_pdf"]
    if len(transaction_pdf) > 1:
        assert (transaction_pdf["buy_idx"].iloc[1:].to_numpy() > transaction_pdf["sell_idx"].iloc[:-1].to_numpy()).all()
    if len(transaction_pdf) > 0:
        assert (transaction_pdf["buy_ts"] > transaction_pdf["decision_ts"]).all()
        assert (transaction_pdf["buy_ts"].dt.strftime("%H:%M") >= "10:00").all()
    # ASSERT THE PRIOR-ONLY PATH RUNNER REPRODUCES A VALIDATION CANDIDATE EXACTLY (SAME DECISIONS, SAME SIMULATOR)
    selection_row = result_dict["selection_pdf"].iloc[0]
    decision_pdf = result_dict["valid_decision_pdf_dict"][(int(selection_row["train_years"]), float(selection_row["ev_threshold"]))]
    window_dict = run_window_with_baseline_dict(decision_pdf, result_dict["valid_pdf"], ohlcv_array_dict_in, fold_pdf.iloc[0]["valid_start"], fold_pdf.iloc[0]["valid_end"])
    assert np.isclose(window_dict["metric_dict"]["total_return"], selection_row["valid_total_return"])
    assert np.isclose(window_dict["metric_dict"]["buy_hold_return"], selection_row["valid_buy_hold_total_return"])
    assert len(window_dict["baseline_pdf"]) == 1 + exp_config.RANDOM_BASELINE_RUN_COUNT + 1
    passed(f"end-to-end fold (validation candidates, test, {len(baseline_pdf)} baselines, cost sensitivity, no overlapping trades, prior-only runner == candidate)")

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
    test_walk_forward_schedule()
    test_uniqueness_weights(synthetic_ohlcv_array_dict)
    test_signal_check()
    test_signal_check_drift_only()
    test_signal_check_month_minimum()
    test_end_to_end_fold(synthetic_ohlcv_pdf, synthetic_ohlcv_array_dict, synthetic_market_schedule_pdf)
    synthetic_snapshot_pdf = test_snapshot_features(synthetic_ohlcv_pdf)
    test_plot_utils(synthetic_ohlcv_pdf, synthetic_ohlcv_array_dict, synthetic_TSBAR_pdf, synthetic_snapshot_pdf)
    test_bad_tick_rule(synthetic_ohlcv_pdf)
    print("\nAll tests passed ✅")
