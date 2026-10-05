"""
Workspace Tests: exp02_stop_reentry (and the shared daily features, exit/re-entry simulator, evaluation and trial log)

Run from the workspace root:   python tests/test_exp02.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises. Takes a few minutes.)

What is verified:
    1. Configuration: every experiment has a distinct name and a deterministic hash that changes with its constants;
       the exp02 embargo covers the label horizon; the trial log writes the experiment name, version and hash.
    2. Daily features equal the TSCTX values at the decision bar where the definitions are shared.
    3. No look-ahead: changing every bar after the decision bar of a session never changes its features (or earlier ones).
    4. The 20-session label equals a hand calculation.
    5. The vectorized simulator equals a slow bar-by-bar reference implementation (every transaction identical).
    6. Simulator rules: no stop = buy-and-hold exactly; fixed delays; forced re-entry; oracle picks the lowest fill;
       no entry on the last session; the trend rule follows its signal.
    7. Walk-forward v2 schedule: 20-session embargo, "all" training window.
    8. Pooled selection: rolling mean over folds and tie-breaks.
    9. Daily signal check: a planted signal is found on both sides, noise is rejected; the optional month minimum
       rejects a degenerate one-month validation bin.
   10. Success criteria and the monthly bootstrap on hand-made returns.
   11. End-to-end fold on synthetic data (validation candidates -> pooled selection -> test with baselines), and the
       prior-only runner (window "valid") reproduces the validation candidate exactly.
   12. Evaluation helpers: generic pooled selection, prior-only path, window summary and MDE, baseline summary.
"""

import os
import sys
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
import tempfile
from experiments.exp02_stop_reentry import config as exp_config
from experiments.exp01_minute_entry import config as exp01_config
from experiments.exp03_ath_exit import config as exp03_config
from so.core.trial_log import get_config_hash_str, log_trial_dict, log_trial_pdf, read_trial_log_pdf, get_trial_count_pdf
from so.core.datetime_utils import get_date_range_market_schedule_pdf
from so.core.trade_execution import get_ohlcv_array_dict, calculate_side_fee, get_affordable_share_count
from so.core.backtest_simulation import get_session_first_entry_idx
from so.features.context_features import add_cum_max_col, get_session_summary_pdf, get_relative_volume_reference_pdf, get_date_TSCTX_pdf
from so.features.barrier_labels import get_date_market_open_ts_dict
from so.features.daily_features import get_daily_feature_pdf, get_session_decision_idx_dict
from so.core.reentry_simulation import simulate_stop_reentry_dict, get_fixed_delay_reentry_func, get_oracle_reentry_func, \
                                    get_window_session_idx_arr, get_buy_and_hold_result_dict, simulate_trend_rule_dict
from experiments.exp02_stop_reentry.walk_forward import get_fold_pdf, get_pooled_selection_pdf, run_validation_candidate_pdf, run_window_with_baseline_dict
from so.core.evaluation import get_chained_daily_return_pdf, get_excess_return_bootstrap_dict, get_success_criteria_dict, get_prior_only_pdf, \
                               get_window_return_summary_dict, get_candidate_summary_pdf, get_baseline_summary_pdf, get_mde_float
from so.core.evaluation import get_pooled_selection_pdf as get_generic_pooled_selection_pdf
from experiments.exp02_stop_reentry.signal_check import get_daily_signal_check_pdf, get_daily_signal_check_verdict_dict
from synthetic_data import get_synthetic_ohlcv_pdf

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

"""
1. Configuration
"""

# FUNCTION: TEST THE CONFIGURATION
def test_config():
    # EVERY EXPERIMENT HAS ITS OWN NAME AND A DETERMINISTIC, DISTINCT HASH
    config_list = [exp01_config, exp_config, exp03_config]
    assert len({module.EXPERIMENT_NAME for module in config_list}) == 3
    hash_list = [get_config_hash_str(module) for module in config_list]
    assert len(set(hash_list)) == 3 and hash_list == [get_config_hash_str(module) for module in config_list] and all(len(h) == 10 for h in hash_list)
    # CHANGING AN EXPERIMENT CONSTANT CHANGES ITS HASH (AND ONLY ITS HASH)
    original_value = exp_config.MAX_CASH_SESSIONS
    exp_config.MAX_CASH_SESSIONS = original_value + 1
    try:
        assert get_config_hash_str(exp_config) != hash_list[1] and get_config_hash_str(exp01_config) == hash_list[0]
    finally:
        exp_config.MAX_CASH_SESSIONS = original_value
    assert get_config_hash_str(exp_config) == hash_list[1]
    # THE EMBARGO MUST COVER THE LABEL HORIZON
    assert exp_config.EMBARGO_TRADING_DAYS >= config.LABEL_HORIZON_SESSIONS
    passed(f"configuration (3 experiments, distinct hashes {hash_list}, embargo {exp_config.EMBARGO_TRADING_DAYS} >= horizon {config.LABEL_HORIZON_SESSIONS})")

"""
2-4. Daily Features And Label
"""

# FUNCTION: TEST THE DAILY FEATURES AGAINST TSCTX
def test_daily_features_vs_tsctx(ohlcv_pdf_in, ohlcv_array_dict_in, daily_pdf_in):
    # BUILD THE TSCTX INPUTS
    schedule_pdf = get_date_range_market_schedule_pdf(str(ohlcv_pdf_in["date"].min()), str(ohlcv_pdf_in["date"].max()))
    data_pdf = add_cum_max_col(ohlcv_pdf_in.copy())
    summary_pdf = get_session_summary_pdf(data_pdf)
    reference_pdf = get_relative_volume_reference_pdf(data_pdf, get_date_market_open_ts_dict(schedule_pdf))
    schedule_dict = dict(zip(pd.to_datetime(schedule_pdf["date"]).dt.date, zip(schedule_pdf["market_open_ts"], schedule_pdf["market_close_ts"])))
    # ITERATE OVER SAMPLE SESSIONS
    for session_idx in [25, 130, 400, len(daily_pdf_in) - 1]:
        # GET THE TSCTX ROW OF THE DECISION BAR
        row = daily_pdf_in.iloc[session_idx]
        TSCTX_pdf = get_date_TSCTX_pdf(data_pdf, summary_pdf, reference_pdf, schedule_dict, str(row["date"]))
        TSCTX_row = TSCTX_pdf[TSCTX_pdf["timestamp"] == row["decision_ts"]].iloc[0]
        # COMPARE THE SHARED DEFINITIONS
        for col_str in ["prev_day_return_pct", "prev_day_range_pct", "intraday_return_pct", "daily_volatility", "ath_drawdown_pct"]:
            assert np.isclose(row[col_str], TSCTX_row[col_str], atol=1e-7, equal_nan=True), (session_idx, col_str, row[col_str], TSCTX_row[col_str])
    passed("daily features equal TSCTX at the decision bar (5 shared definitions)")

# FUNCTION: TEST THAT FUTURE BARS NEVER CHANGE THE FEATURES
def test_daily_no_lookahead(ohlcv_pdf_in, daily_pdf_in, session_idx_in=400):
    # COLLECT THE FILL BAR OF THE SESSION (FIRST BAR AFTER THE DECISION)
    ohlcv_array_dict = get_ohlcv_array_dict(ohlcv_pdf_in)
    fill_idx = int(get_session_decision_idx_dict(ohlcv_array_dict)["fill_idx_arr"][session_idx_in])
    # PERTURB EVERY BAR FROM THE FILL BAR ON (SCALE PRICES, CHANGE VOLUMES)
    perturbed_pdf = ohlcv_pdf_in.sort_values("timestamp").reset_index(drop=True).copy()
    rng = np.random.default_rng(1)
    factor_arr = 1 + rng.normal(0, 0.02, len(perturbed_pdf) - fill_idx)
    for col_str in ["open", "high", "low", "close"]:
        perturbed_pdf.loc[fill_idx:, col_str] = (perturbed_pdf.loc[fill_idx:, col_str].to_numpy() * factor_arr).round(2)
    perturbed_pdf.loc[fill_idx:, "high"] = perturbed_pdf.loc[fill_idx:, ["open", "high", "low", "close"]].max(axis=1)
    perturbed_pdf.loc[fill_idx:, "low"] = perturbed_pdf.loc[fill_idx:, ["open", "high", "low", "close"]].min(axis=1)
    # RECOMPUTE THE FEATURES
    perturbed_daily_pdf = get_daily_feature_pdf(get_ohlcv_array_dict(perturbed_pdf))
    # THE FEATURES OF EVERY SESSION UP TO session_idx_in MUST BE IDENTICAL
    for col_str in config.DAILY_FEATURE_COL_STR_LIST:
        pd.testing.assert_series_equal(daily_pdf_in[col_str].iloc[:session_idx_in + 1], perturbed_daily_pdf[col_str].iloc[:session_idx_in + 1], check_names=False)
    # AND THE NEXT SESSION MUST CHANGE (THE PERTURBATION IS VISIBLE TO LATER ROWS)
    assert not np.isclose(daily_pdf_in["return_5d"].iloc[session_idx_in + 1], perturbed_daily_pdf["return_5d"].iloc[session_idx_in + 1])
    passed(f"no look-ahead in the daily features (all {len(config.DAILY_FEATURE_COL_STR_LIST)} features unchanged by bars after the decision)")

# FUNCTION: TEST THE LABEL BY HAND
def test_daily_label(ohlcv_array_dict_in, daily_pdf_in, session_idx_in=300):
    # COLLECT THE ENTRY AND EXIT PRICES
    fill_idx = int(daily_pdf_in["fill_idx"].iloc[session_idx_in])
    exit_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx_in + config.LABEL_HORIZON_SESSIONS])
    entry_fill = ohlcv_array_dict_in["open_arr"][fill_idx] + config.ENTRY_SLIPPAGE_PER_SHARE
    exit_fill = ohlcv_array_dict_in["close_arr"][exit_idx] - config.MARKET_EXIT_SLIPPAGE_PER_SHARE
    expected_return = (exit_fill - entry_fill - 2 * config.FEE_PER_SHARE_PER_SIDE) / entry_fill
    # ASSERT THE LABEL
    assert np.isclose(daily_pdf_in["fwd_net_return_20d"].iloc[session_idx_in], expected_return, atol=1e-9)
    assert daily_pdf_in["y_fwd_positive"].iloc[session_idx_in] == float(expected_return > 0)
    # THE FILL BAR IS THE BAR AFTER THE DECISION BAR (15:58 -> 15:59 ON A FULL DAY)
    assert daily_pdf_in["decision_ts"].iloc[session_idx_in].strftime("%H:%M") in ["15:58", "12:58"]
    # THE LAST HORIZON SESSIONS HAVE NO LABEL
    assert daily_pdf_in["y_fwd_positive"].iloc[-config.LABEL_HORIZON_SESSIONS:].isna().all()
    assert daily_pdf_in["y_fwd_positive"].iloc[-config.LABEL_HORIZON_SESSIONS - 1:-config.LABEL_HORIZON_SESSIONS].notna().all()
    passed("20-session label (hand calculation, decision 15:58 -> fill 15:59, unresolved tail is NaN)")

"""
5-6. Simulator
"""

# FUNCTION: SLOW BAR-BY-BAR REFERENCE SIMULATION (FIXED-DELAY RE-ENTRY)
def reference_simulation_list(ohlcv_array_dict_in, date1_in, date2_in, volatility_arr_in, stop_k_in, delay_in, max_cash_in):
    # COLLECT THE ARRAYS
    open_arr, low_arr, close_arr = ohlcv_array_dict_in["open_arr"], ohlcv_array_dict_in["low_arr"], ohlcv_array_dict_in["close_arr"]
    idx_dict = get_session_decision_idx_dict(ohlcv_array_dict_in)
    session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1_in, date2_in)
    # DEFINE THE STATE
    state = {"cash": config.INITIAL_CAPITAL, "shares": 0, "invested": False, "entry_idx": -1, "buy_fill": 0.0, "buy_fee": 0.0,
             "highest": -np.inf, "stop": -np.inf, "count": 0, "in_episode": False}
    trade_list = []
    # BUY / SELL HELPERS
    def buy(bar_idx):
        fill = open_arr[bar_idx] + config.ENTRY_SLIPPAGE_PER_SHARE
        shares = get_affordable_share_count(state["cash"], fill)
        fee = calculate_side_fee(shares, fill)
        state.update({"cash": state["cash"] - shares * fill - fee, "shares": shares, "invested": True, "entry_idx": bar_idx,
                      "buy_fill": fill, "buy_fee": fee, "highest": -np.inf, "stop": -np.inf, "count": 0, "in_episode": False})
    def sell(bar_idx, raw_price, reason):
        fill = raw_price - config.MARKET_EXIT_SLIPPAGE_PER_SHARE
        fee = calculate_side_fee(state["shares"], fill)
        state["cash"] += state["shares"] * fill - fee
        trade_list.append((state["entry_idx"], int(bar_idx), round(raw_price, 6), reason))
        state.update({"shares": 0, "invested": False, "count": 0, "in_episode": reason != "END"})
    # START INVESTED
    buy(get_session_first_entry_idx(ohlcv_array_dict_in, int(session_idx_arr[0])))
    # ITERATE OVER THE SESSIONS AND BARS
    for session_pos, session_idx in enumerate(session_idx_arr):
        is_last = session_pos == len(session_idx_arr) - 1
        volatility = volatility_arr_in[session_idx]
        for bar_idx in range(ohlcv_array_dict_in["session_start_idx_arr"][session_idx], ohlcv_array_dict_in["session_end_idx_arr"][session_idx] + 1):
            # STOP CHECK (FROM THE BAR AFTER THE ENTRY)
            if state["invested"] and bar_idx > state["entry_idx"] and np.isfinite(volatility):
                stop = max(state["stop"], state["highest"] * (1 - stop_k_in * volatility))
                if low_arr[bar_idx] <= stop:
                    sell(bar_idx, open_arr[bar_idx] if open_arr[bar_idx] <= stop else stop, "STOP")
                else:
                    state["stop"] = stop
            # HIGHEST CLOSE AFTER THE BAR
            if state["invested"]:
                state["highest"] = max(state["highest"], close_arr[bar_idx])
            # DECISION
            if bar_idx == idx_dict["decision_idx_arr"][session_idx] and not state["invested"] and state["in_episode"]:
                state["count"] += 1
                if not is_last and (state["count"] >= delay_in or state["count"] >= max_cash_in):
                    buy(int(idx_dict["fill_idx_arr"][session_idx]))
    # CLOSE AT THE END
    if state["invested"]:
        end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][session_idx_arr[-1]])
        sell(end_idx, close_arr[end_idx], "END")
    return trade_list

# FUNCTION: TEST THE SIMULATOR AGAINST THE REFERENCE
def test_simulator_reference(ohlcv_array_dict_in, daily_pdf_in):
    # COLLECT THE VOLATILITY AND A ONE-YEAR WINDOW
    volatility_arr = daily_pdf_in["daily_volatility"].to_numpy(dtype=float)
    date1, date2 = daily_pdf_in["date"].iloc[260], daily_pdf_in["date"].iloc[520]
    stop_total = 0
    # ITERATE OVER STOP MULTIPLIERS AND DELAYS (k = 1 MAKES MANY STOPS; delay 99 WITH max 60 TESTS THE FORCED RE-ENTRY)
    for stop_k, delay in [(1.0, 1), (1.5, 5), (2.0, 99), (3.0, 20)]:
        # RUN BOTH IMPLEMENTATIONS
        reference_list = reference_simulation_list(ohlcv_array_dict_in, date1, date2, volatility_arr, stop_k, delay, exp_config.MAX_CASH_SESSIONS)
        simulation_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1, date2, volatility_arr, stop_k, get_fixed_delay_reentry_func(delay), "delay",
                                                     max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
        transaction_pdf = simulation_dict["transaction_pdf"]
        simulated_list = list(zip(transaction_pdf["buy_idx"], transaction_pdf["sell_idx"], transaction_pdf["sell_raw_price"].round(6), transaction_pdf["exit_reason"]))
        # ASSERT IDENTICAL TRANSACTIONS
        assert simulated_list == reference_list, (stop_k, delay, simulated_list[:5], reference_list[:5])
        stop_total += int((transaction_pdf["exit_reason"] == "STOP").sum())
        # EVERY STOP FILL IS AT OR BELOW ITS STOP; EVERY EPISODE RE-ENTERED BY THE RULE WAITED EXACTLY delay DECISIONS
        stop_pdf = transaction_pdf[transaction_pdf["exit_reason"] == "STOP"]
        assert (stop_pdf["sell_raw_price"] <= stop_pdf["SL_price"] + 1e-9).all()
        episode_pdf = simulation_dict["episode_pdf"]
        if not episode_pdf.empty:
            assert (episode_pdf.loc[episode_pdf["reentry_reason"] == "delay", "cash_session_count"] == delay).all()
            assert (episode_pdf.loc[episode_pdf["reentry_reason"] == "forced", "cash_session_count"] == exp_config.MAX_CASH_SESSIONS).all()
        # THE LAST TRANSACTION ENDS AT THE LAST CLOSE OF THE WINDOW; NO ENTRY ON THE LAST SESSION
        last_end_idx = int(ohlcv_array_dict_in["session_end_idx_arr"][get_window_session_idx_arr(ohlcv_array_dict_in, date1, date2)[-1]])
        last_start_idx = int(ohlcv_array_dict_in["session_start_idx_arr"][get_window_session_idx_arr(ohlcv_array_dict_in, date1, date2)[-1]])
        assert (transaction_pdf["buy_idx"] < last_start_idx).all()
        if transaction_pdf["exit_reason"].iloc[-1] == "END":
            assert transaction_pdf["sell_idx"].iloc[-1] == last_end_idx
        # THE FINAL EQUITY EQUALS THE CASH AFTER THE LAST TRANSACTION
        assert np.isclose(simulation_dict["daily_equity_pdf"]["equity"].iloc[-1], transaction_pdf["equity_after"].iloc[-1], atol=1e-4)
    assert stop_total > 10
    passed(f"vectorized simulator == bar-by-bar reference ({stop_total} stops, delays 1/5/20, forced re-entry, END exits)")

# FUNCTION: TEST THE SIMULATOR SPECIAL CASES
def test_simulator_rules(ohlcv_array_dict_in, daily_pdf_in):
    # COLLECT THE VOLATILITY AND A WINDOW
    volatility_arr = daily_pdf_in["daily_volatility"].to_numpy(dtype=float)
    date1, date2 = daily_pdf_in["date"].iloc[300], daily_pdf_in["date"].iloc[480]
    # NO STOP = BUY AND HOLD EXACTLY
    no_stop_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1, date2, volatility_arr, None, None)
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, date1, date2)
    assert np.isclose(no_stop_dict["metric_dict"]["total_return"], buy_hold_dict["metric_dict"]["total_return"], atol=1e-10)
    assert np.allclose(no_stop_dict["daily_equity_pdf"]["equity"], buy_hold_dict["daily_equity_pdf"]["equity"], atol=1e-6)
    # ORACLE: EVERY RE-ENTRY IS AT THE LOWEST FILL OPEN OF ITS ALLOWED DECISIONS
    window_session_idx_arr = get_window_session_idx_arr(ohlcv_array_dict_in, date1, date2)
    oracle_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1, date2, volatility_arr, 1.0,
                                             get_oracle_reentry_func(ohlcv_array_dict_in, window_session_idx_arr, exp_config.MAX_CASH_SESSIONS), "oracle",
                                             max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)
    fill_idx_arr = get_session_decision_idx_dict(ohlcv_array_dict_in)["fill_idx_arr"]
    oracle_pdf = oracle_dict["episode_pdf"][oracle_dict["episode_pdf"]["reentry_reason"] == "oracle"]
    assert len(oracle_pdf) > 0
    assert (oracle_pdf["share_gain_pct"].mean() > simulate_stop_reentry_dict(ohlcv_array_dict_in, date1, date2, volatility_arr, 1.0,
                                                                               get_fixed_delay_reentry_func(1), "delay", max_cash_sessions_in=exp_config.MAX_CASH_SESSIONS)["episode_pdf"]["share_gain_pct"].mean())
    for first_cash_session_idx, reentry_ts in zip(oracle_pdf["first_cash_session_idx"], oracle_pdf["reentry_ts"]):
        candidate_arr = np.arange(first_cash_session_idx, min(first_cash_session_idx + exp_config.MAX_CASH_SESSIONS, window_session_idx_arr[-1]))
        reentry_session_idx = ohlcv_array_dict_in["date_session_idx_dict"][reentry_ts.date()]
        assert ohlcv_array_dict_in["open_arr"][fill_idx_arr[reentry_session_idx]] == ohlcv_array_dict_in["open_arr"][fill_idx_arr[candidate_arr]].min()
    # TREND RULE: EXITS ONLY WHEN THE DECISION CLOSE IS BELOW THE MOVING AVERAGE, ENTRIES ONLY WHEN ABOVE
    trend_dict = simulate_trend_rule_dict(ohlcv_array_dict_in, daily_pdf_in, date1, date2, "ma50_dist_pct")
    trend_pdf = trend_dict["transaction_pdf"]
    ts_session_dict = {ts: idx for idx, ts in enumerate(daily_pdf_in["decision_ts"])}
    for _, row in trend_pdf[trend_pdf["exit_reason"] == "SIGNAL"].iterrows():
        decision_ts = ohlcv_array_dict_in["timestamp_index"][row["sell_idx"] - 1]
        assert daily_pdf_in["ma50_dist_pct"].iloc[ts_session_dict[decision_ts]] < 0
    for decision_ts in trend_pdf.loc[trend_pdf["entry_reason"] == "rule", "decision_ts"]:
        assert daily_pdf_in["ma50_dist_pct"].iloc[ts_session_dict[decision_ts]] > 0
    assert (trend_pdf["exit_reason"] == "SIGNAL").sum() > 0
    passed("simulator rules (no stop == buy-and-hold, oracle beats delay-1, trend rule follows its signal)")

"""
7-8. Schedule And Selection
"""

# FUNCTION: TEST THE exp02 SCHEDULE
def test_schedule():
    # BUILD THE SCHEDULE ON THE REAL CALENDAR
    session_date_list = list(pd.to_datetime(get_date_range_market_schedule_pdf("2005-01-03", "2026-08-13")["date"]).dt.date)
    fold_pdf = get_fold_pdf(session_date_list)
    session_pos_dict = {date_object: idx for idx, date_object in enumerate(session_date_list)}
    # ASSERT THE GAPS
    for _, row in fold_pdf.iterrows():
        assert session_pos_dict[row["valid_start"]] - session_pos_dict[row["train_end"]] - 1 >= exp_config.EMBARGO_TRADING_DAYS
        assert session_pos_dict[row["test_start"]] - session_pos_dict[row["valid_end"]] - 1 >= exp_config.EMBARGO_TRADING_DAYS
        assert row["train_start_all"] == session_date_list[0] and row["refit_end"] == row["valid_end"]
    passed(f"exp02 schedule ({len(fold_pdf)} folds, first test {fold_pdf['test_start'].iloc[0]}, embargo {exp_config.EMBARGO_TRADING_DAYS} sessions, 'all' window)")

# FUNCTION: TEST THE POOLED SELECTION
def test_pooled_selection():
    # BUILD A TOY CANDIDATE TABLE: CANDIDATE A IS BEST ON AVERAGE, CANDIDATE B WINS ONLY THE LAST FOLD
    row_list = []
    for fold_id in range(6):
        row_list.append({"fold_id": fold_id, "train_window": "10y", "stop_k": 3, "threshold_offset": 0.0, "valid_excess_return": 0.01})
        row_list.append({"fold_id": fold_id, "train_window": "10y", "stop_k": 4, "threshold_offset": 0.0, "valid_excess_return": 0.05 if fold_id == 5 else -0.02})
        row_list.append({"fold_id": fold_id, "train_window": "all", "stop_k": 5, "threshold_offset": 0.05, "valid_excess_return": 0.01})
    selection_pdf = get_pooled_selection_pdf(pd.DataFrame(row_list))
    last_row = selection_pdf[selection_pdf["fold_id"] == 5].iloc[0]
    # POOLED MEAN OF B AT FOLD 5 = (-0.02 x 3 + 0.05) / 4 = -0.0025 < 0.01, SO B IS NOT SELECTED; A AND C TIE -> LARGER k (C)
    assert last_row["stop_k"] == 5 and np.isclose(last_row["pooled_valid_excess_return"], 0.01) and last_row["pooled_quarter_count"] == 4
    # FOLD 0 POOLS ONE QUARTER ONLY
    assert selection_pdf[selection_pdf["fold_id"] == 0]["pooled_quarter_count"].iloc[0] == 1
    passed("pooled selection (4-quarter mean, single-quarter luck rejected, tie-break larger k)")

"""
9-10. Signal Check And Statistics
"""

# FUNCTION: TEST THE DAILY SIGNAL CHECK
def test_daily_signal_check():
    # BUILD TOY DAILY ROWS (6 YEARS): FEATURE "planted" RAISES OR LOWERS THE PROBABILITY BY MONTH, "noise" DOES NOTHING
    rng = np.random.default_rng(3)
    date_arr = pd.bdate_range("2010-01-01", "2015-12-31").date
    month_effect_arr = rng.normal(0, 1, len(date_arr) // 21 + 2)[np.arange(len(date_arr)) // 21]
    planted_arr = month_effect_arr + rng.normal(0, 0.3, len(date_arr))
    probability_arr = np.clip(0.6 + 0.2 * np.tanh(planted_arr), 0.05, 0.95)
    y_arr = (rng.random(len(date_arr)) < probability_arr).astype(float)
    toy_pdf = pd.DataFrame({"date": date_arr, "planted": planted_arr, "noise": rng.normal(0, 1, len(date_arr)),
                            "y_fwd_positive": y_arr, "fwd_net_return_20d": np.where(y_arr == 1, 0.01, -0.01)})
    train_pdf, valid_pdf = toy_pdf[toy_pdf["date"] < pd.Timestamp("2014-01-01").date()], toy_pdf[toy_pdf["date"] >= pd.Timestamp("2014-01-01").date()]
    # RUN THE CHECK
    result_pdf = get_daily_signal_check_pdf(train_pdf, valid_pdf, ["planted", "noise"], alert_in=False, iteration_count_in=300)
    verdict_dict = get_daily_signal_check_verdict_dict(result_pdf)
    planted_pdf = result_pdf[result_pdf["feature"] == "planted"]
    # THE PLANTED FEATURE MUST SHOW SIGNALS ON BOTH SIDES; THE NOISE FEATURE NONE
    assert (planted_pdf["signal"] & planted_pdf["train_above"]).any() and (planted_pdf["signal"] & planted_pdf["train_below"]).any()
    assert not result_pdf[result_pdf["feature"] == "noise"]["signal"].any()
    assert verdict_dict["verdict"] == "CONTINUE" and verdict_dict["signal_feature_list"] == ["planted"]
    passed(f"daily signal check (planted signal found above and below the base rate, noise rejected; {verdict_dict['test_count']} tests)")
    # DEGENERATE VALIDATION BIN: ALL ROWS OF THE TOP BIN IN ONE MONTH AND ALL POSITIVE -> INTERVAL [1, 1]
    top_edge = np.quantile(train_pdf["planted"], 0.8)
    month_pdf = valid_pdf[pd.to_datetime(valid_pdf["date"]).dt.to_period("M") == pd.Period("2014-03", "M")]
    degenerate_valid_pdf = pd.concat([valid_pdf[valid_pdf["planted"] <= top_edge], month_pdf.assign(planted=top_edge + 1.0, y_fwd_positive=1.0)], ignore_index=True)
    loose_pdf = get_daily_signal_check_pdf(train_pdf, degenerate_valid_pdf, ["planted"], min_month_count_in=None, alert_in=False, iteration_count_in=300)
    strict_pdf = get_daily_signal_check_pdf(train_pdf, degenerate_valid_pdf, ["planted"], min_month_count_in=6, alert_in=False, iteration_count_in=300)
    top_bin_str = [bin_str for bin_str in loose_pdf["bin"] if bin_str.endswith("inf]") and not bin_str.startswith("(-inf")][0]
    assert loose_pdf.loc[loose_pdf["bin"] == top_bin_str, "valid_above"].iloc[0] and loose_pdf.loc[loose_pdf["bin"] == top_bin_str, "valid_month_count"].iloc[0] == 1
    assert not strict_pdf.loc[strict_pdf["bin"] == top_bin_str, "valid_above"].iloc[0]
    assert exp_config.DAILY_SIGNAL_CHECK_MIN_MONTH_COUNT == 6
    passed("daily signal check month minimum (a one-month validation bin passes without it, is rejected with the protocol minimum of 6)")

# FUNCTION: TEST THE SUCCESS CRITERIA AND THE BOOTSTRAP
def test_success_criteria():
    # BUILD TWO YEARS OF DAILY RETURNS
    rng = np.random.default_rng(5)
    date_arr = pd.bdate_range("2020-01-01", "2021-12-31").date
    buy_hold_pdf = pd.DataFrame({"date": date_arr, "daily_return": rng.normal(0.0005, 0.01, len(date_arr))})
    # IDENTICAL RETURNS: ZERO EXCESS, NOT SUPPORTED, COMPARABLE, NO SECONDARY WIN
    same_dict = get_success_criteria_dict(buy_hold_pdf, buy_hold_pdf)
    bootstrap_dict = get_excess_return_bootstrap_dict(buy_hold_pdf, buy_hold_pdf, iteration_count_in=200)
    assert not same_dict["primary_success"] and same_dict["comparable_return"] and not same_dict["secondary_sharpe"]
    assert np.isclose(bootstrap_dict["excess_return"], 0) and not bootstrap_dict["supported"]
    # A STRATEGY THAT SKIPS EVERY DAY BELOW -1% (HINDSIGHT): PRIMARY SUCCESS, SUPPORTED, SMALLER DRAWDOWN
    strategy_pdf = buy_hold_pdf.assign(daily_return=np.where(buy_hold_pdf["daily_return"] < -0.01, 0.0, buy_hold_pdf["daily_return"]))
    better_dict = get_success_criteria_dict(strategy_pdf, buy_hold_pdf, {"fixed_delay_1": 0.0})
    assert better_dict["primary_success"] and better_dict["secondary_drawdown"] and better_dict["all_baselines_beaten"]
    assert get_excess_return_bootstrap_dict(strategy_pdf, buy_hold_pdf, iteration_count_in=200)["supported"]
    # NEGATIVE BUY-AND-HOLD: THE COMPARABLE FLOOR IS BUY-AND-HOLD - 10% OF ITS SIZE
    down_pdf = buy_hold_pdf.assign(daily_return=-0.001)
    assert np.isclose(get_success_criteria_dict(down_pdf, down_pdf)["comparable_floor"], ((1 - 0.001) ** len(date_arr) - 1) * 1.1)
    # CHAINING TWO WINDOWS OF ONE DAY EACH
    chained_pdf = get_chained_daily_return_pdf([pd.DataFrame({"date": [date_arr[0]], "equity": [110_000.0]}), pd.DataFrame({"date": [date_arr[1]], "equity": [99_000.0]})])
    assert np.allclose(chained_pdf["daily_return"], [0.10, -0.01])
    passed("success criteria and monthly bootstrap (primary, comparable floor, secondary, baselines, chaining)")

"""
11. End-To-End Fold
"""

# FUNCTION: TEST ONE FOLD END TO END
def test_end_to_end(ohlcv_array_dict_in, daily_pdf_in):
    # BUILD A SHORT SCHEDULE (1-YEAR FIXED WINDOW TO FIT THE SYNTHETIC DATA)
    fold_pdf = get_fold_pdf(ohlcv_array_dict_in["session_date_list"], max_fold_count_in=2, train_years_in=1)
    assert len(fold_pdf) == 2
    # RUN THE VALIDATION CANDIDATES OF BOTH FOLDS (SMALL GRID)
    candidate_pdf = pd.concat([run_validation_candidate_pdf(row, daily_pdf_in, ohlcv_array_dict_in, stop_k_list_in=[2, 4], offset_list_in=[0.0, 0.05])
                               for _, row in fold_pdf.iterrows()], ignore_index=True)
    assert len(candidate_pdf) == 2 * 2 * 2 * 2
    assert candidate_pdf["valid_logistic_auc"].notna().all()
    # SELECT AND TEST THE LAST FOLD
    selection_pdf = get_pooled_selection_pdf(candidate_pdf)
    test_dict = run_window_with_baseline_dict(fold_pdf.iloc[-1], selection_pdf.iloc[-1], daily_pdf_in, ohlcv_array_dict_in, "test", alert_in=False)
    baseline_set = set(test_dict["baseline_pdf"]["baseline"])
    assert {"model", "buy_hold", "fixed_delay_1", "fixed_delay_5", "fixed_delay_20", "trend_ma200"} <= baseline_set
    assert len(test_dict["cost_sensitivity_pdf"]) == len(config.COST_SENSITIVITY_SLIPPAGE_LIST)
    # EVERY TRADE IS INSIDE THE TEST WINDOW
    transaction_pdf = test_dict["transaction_pdf"]
    assert (transaction_pdf["buy_ts"].dt.date >= fold_pdf.iloc[-1]["test_start"]).all() and (transaction_pdf["sell_ts"].dt.date <= fold_pdf.iloc[-1]["test_end"]).all()
    # THE PRIOR-ONLY RUNNER (WINDOW "valid") REPRODUCES EVERY VALIDATION CANDIDATE OF THE LAST FOLD EXACTLY
    for _, candidate_row in candidate_pdf[candidate_pdf["fold_id"] == fold_pdf.iloc[-1]["fold_id"]].iterrows():
        valid_dict = run_window_with_baseline_dict(fold_pdf.iloc[-1], candidate_row, daily_pdf_in, ohlcv_array_dict_in, "valid", alert_in=False)
        assert np.isclose(valid_dict["metric_dict"]["total_return"], candidate_row["valid_total_return"]), (valid_dict["metric_dict"]["total_return"], candidate_row["valid_total_return"])
        assert np.isclose(valid_dict["metric_dict"]["buy_hold_total_return"], candidate_row["valid_buy_hold_total_return"])
    assert len([name for name in set(valid_dict["baseline_pdf"]["baseline"]) if name.startswith("random_")]) == exp_config.RANDOM_REENTRY_RUN_COUNT
    passed(f"end-to-end fold ({len(candidate_pdf)} validation candidates, pooled selection, test with {len(baseline_set)} baselines, prior-only runner == candidates)")


"""
12. Evaluation Helpers And Trial Log
"""

# FUNCTION: TEST THE EVALUATION HELPERS
def test_evaluation_helpers():
    # BUILD A TOY CANDIDATE TABLE (2 CANDIDATES, 5 FOLDS)
    candidate_pdf = pd.DataFrame([{"fold_id": f, "cand": c, "valid_total_return": r, "valid_buy_hold_total_return": 0.02, "valid_excess_return": r - 0.02}
                                  for f in range(5) for c, r in [("a", 0.03), ("b", 0.01 if f < 4 else 0.10)]])
    # SINGLE-QUARTER SELECTION PICKS "a" UNTIL FOLD 3 AND "b" AT FOLD 4; PRIOR-ONLY EVALUATES FOLDS 1..4 WITH THE PREVIOUS CHOICE
    selection_pdf = get_generic_pooled_selection_pdf(candidate_pdf, ["cand"], "valid_excess_return", 1, [("cand", True)])
    assert selection_pdf["cand"].tolist() == ["a", "a", "a", "a", "b"]
    prior_only_pdf = get_prior_only_pdf(candidate_pdf, selection_pdf, ["cand"])
    assert prior_only_pdf["fold_id"].tolist() == [1, 2, 3, 4] and prior_only_pdf["cand"].tolist() == ["a", "a", "a", "a"]
    assert (prior_only_pdf["selected_at_fold_id"] == prior_only_pdf["fold_id"] - 1).all()
    # WINDOW SUMMARY: CHAINING, BEAT COUNT, MDE = 2.8 x SD / sqrt(n)
    summary_dict = get_window_return_summary_dict([0.03, -0.01, 0.02, 0.0], [0.02, 0.02, 0.02, 0.02])
    excess_arr = np.array([0.01, -0.03, 0.0, -0.02])
    assert np.isclose(summary_dict["chained_return"], 1.03 * 0.99 * 1.02 - 1) and summary_dict["windows_beating_buy_hold"] == 1
    assert np.isclose(summary_dict["mde_per_window"], 2.8 * excess_arr.std(ddof=1) / 2) and np.isclose(summary_dict["mde_per_year"], 4 * summary_dict["mde_per_window"])
    assert np.isclose(get_mde_float(0.04, 44), 2.8 * 0.04 / np.sqrt(44))
    # CANDIDATE SUMMARY: ONE ROW PER CANDIDATE, BEST FIRST
    candidate_summary_pdf = get_candidate_summary_pdf(candidate_pdf, ["cand"])
    assert candidate_summary_pdf["cand"].tolist() == ["a", "b"] and candidate_summary_pdf["window_count"].tolist() == [5, 5]
    # BASELINE SUMMARY: CHAINED BASELINES AND THE SHARE OF RANDOM RUNS THE MODEL BEATS
    baseline_pdf = pd.DataFrame([{"fold_id": f, "baseline": b, "total_return": r} for f in range(2)
                                 for b, r in [("model", 0.02), ("buy_hold", 0.01), ("random_00", 0.0), ("random_01", 0.05)]])
    baseline_summary_pdf = get_baseline_summary_pdf(baseline_pdf).set_index("baseline")
    assert "model" not in baseline_summary_pdf.index and baseline_summary_pdf.loc["buy_hold", "model_beats"]
    assert np.isclose(baseline_summary_pdf.loc["random_* (median of runs)", "model_beats_random_run_share"], 0.5)
    passed("evaluation helpers (pooled selection, prior-only path, window summary and MDE, candidate and baseline summaries)")

# FUNCTION: TEST THE TRIAL LOG
def test_trial_log():
    # WRITE TO A TEMPORARY FILE
    with tempfile.TemporaryDirectory() as directory_str:
        file_path_str = f"{directory_str}/trial_log.csv".replace("\\", "/")
        fold_row = pd.Series({"fold_id": 3, "train_start_10y": pd.Timestamp("2010-01-04").date(), "train_start_all": pd.Timestamp("2005-01-03").date(),
                              "train_end": pd.Timestamp("2020-01-02").date(), "valid_start": pd.Timestamp("2020-02-03").date(), "valid_end": pd.Timestamp("2020-04-30").date(),
                              "test_start": pd.Timestamp("2020-06-01").date(), "test_end": pd.Timestamp("2020-08-31").date()})
        # ONE ENTRY, THEN A BATCH OF TWO
        row_dict = log_trial_dict(exp_config, "validation", {"train_window": "all", "stop_k": 4}, {"valid_total_return": np.float64(0.01)}, False, fold_row, file_path_str_in=file_path_str)
        batch_pdf = pd.DataFrame([{"fold_id": 3, "train_window": "10y", "stop_k": k, "valid_total_return": 0.0} for k in [3, 5]])
        log_trial_pdf(exp_config, "validation", batch_pdf, ["train_window", "stop_k"], ["valid_total_return"], False, pd.DataFrame([fold_row]), file_path_str_in=file_path_str)
        trial_log_pdf = read_trial_log_pdf(file_path_str, expand_metrics_bool_in=True)
    # ASSERT THE CONTENT
    assert len(trial_log_pdf) == 3 and (trial_log_pdf["experiment"] == exp_config.EXPERIMENT_NAME).all() and trial_log_pdf["trial_id"].is_unique
    assert (trial_log_pdf["config_hash"] == get_config_hash_str(exp_config)).all() and (trial_log_pdf["protocol_version"].astype(str) == exp_config.PROTOCOL_VERSION).all()
    assert str(row_dict["train_start"]) == "2005-01-03" and trial_log_pdf["train_start"].tolist()[1:] == ["2010-01-04", "2010-01-04"]
    assert not trial_log_pdf["test_window_touched"].any() and get_trial_count_pdf(trial_log_pdf)["trial_count"].sum() == 3
    passed("trial log (name, protocol version and hash per experiment, training start of the evaluated window, batch writes, unique ids)")

"""
Runner
"""

# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    # GENERATE THE SYNTHETIC DATA (ABOUT 3.5 YEARS)
    print("Generating synthetic data...")
    synthetic_ohlcv_pdf = get_synthetic_ohlcv_pdf("2021-01-04", "2024-06-28", minute_vol_in=0.0006, seed_in=11)
    synthetic_ohlcv_array_dict = get_ohlcv_array_dict(synthetic_ohlcv_pdf)
    synthetic_daily_pdf = get_daily_feature_pdf(synthetic_ohlcv_array_dict)
    # RUN THE TESTS
    test_config()
    test_daily_features_vs_tsctx(synthetic_ohlcv_pdf, synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_daily_no_lookahead(synthetic_ohlcv_pdf, synthetic_daily_pdf)
    test_daily_label(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_simulator_reference(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_simulator_rules(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_schedule()
    test_pooled_selection()
    test_daily_signal_check()
    test_success_criteria()
    test_end_to_end(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_evaluation_helpers()
    test_trial_log()
    print("\nAll exp02 tests passed ✅")
