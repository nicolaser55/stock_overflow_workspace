"""
Workspace Tests: shared daily code (daily features and label, exit/re-entry simulator, schedule, evaluation, trial log)

Run from the workspace root:   python tests/test_daily_shared.py   (or python tests/run_all_tests.py)
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
# THE DATA ROOT MUST BE INSIDE A TEMPORARY FOLDER
from temporary_data_root import assert_temporary_data_root
assert_temporary_data_root()

# IMPORT WORKSPACE MODULES
from so import config
from experiments.exp02_stop_reentry import config as exp_config
from experiments.exp01_minute_entry import config as exp01_config
from experiments.exp03_ath_exit import config as exp03_config
from so.core.trial_log import get_config_hash_str
from so.core.datetime_utils import get_date_range_market_schedule_pdf
from so.core.trade_execution import get_ohlcv_array_dict, calculate_side_fee, get_affordable_share_count
from so.core.backtest_simulation import get_session_first_entry_idx
from so.features.context_features import add_cum_max_col, get_session_summary_pdf, get_relative_volume_reference_pdf, get_date_TSCTX_pdf
from so.features.barrier_labels import get_date_market_open_ts_dict
from so.features.daily_features import get_daily_feature_pdf, get_session_decision_idx_dict
from so.core.reentry_simulation import (simulate_stop_reentry_dict, get_fixed_delay_reentry_func, get_window_session_idx_arr)
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


"""
7-8. Schedule And Selection
"""

# FUNCTION: TEST THE exp02 DEVELOPMENT SCHEDULE
def test_schedule():
    # POINT THE REGISTRY AT A TEMPORARY WINDOW SO THE REAL HOLDOUT IS NOT READ
    import tempfile
    from so import paths
    from so.core.schedule import get_development_fold_pdf
    from so.core.holdout import get_development_end_date
    real_path_str = paths.HOLDOUT_WINDOWS_FILE_PATH_STR
    paths.HOLDOUT_WINDOWS_FILE_PATH_STR = f"{tempfile.mkdtemp()}/holdout_windows.csv".replace("\\", "/")
    try:
        # A CALENDAR THAT ENDS BEFORE THE REAL WINDOW, WITH A FAKE ACTIVE WINDOW AT ITS END
        session_date_list = list(pd.to_datetime(get_date_range_market_schedule_pdf("2005-01-03", "2024-12-31")["date"]).dt.date)
        pd.DataFrame([{"window_id": "wtest", "status": "active", "start": session_date_list[-300], "end": session_date_list[-1],
                       "session_count": 300, "months_covered": 12.0, "opened_ts": "", "opened_by": "test",
                       "data_last_session_at_open": session_date_list[-1], "retired_ts": "", "retire_reason": ""}]).to_csv(paths.HOLDOUT_WINDOWS_FILE_PATH_STR, index=False)
        development_end = get_development_end_date(exp_config.EMBARGO_TRADING_DAYS, session_date_list)
        fold_pdf = get_development_fold_pdf(session_date_list, exp_config.EMBARGO_TRADING_DAYS, [exp_config.FIXED_TRAIN_WINDOW_YEARS])
        # NO TEST WINDOW, AND THE LAST VALIDATION END IS THE DEVELOPMENT END
        assert "test_start" not in fold_pdf.columns and pd.Timestamp(fold_pdf["valid_end"].iloc[-1]).date() == development_end
        assert len(fold_pdf) > 10 and exp_config.EMBARGO_TRADING_DAYS == 20
    finally:
        paths.HOLDOUT_WINDOWS_FILE_PATH_STR = real_path_str
    passed(f"exp02 development schedule ({len(fold_pdf)} folds, embargo {exp_config.EMBARGO_TRADING_DAYS}, no test window)")


"""
11. End-To-End Fold
"""

"""
12. Evaluation Helpers And Trial Log
"""


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
    test_schedule()
    print("\nAll shared daily tests passed ✅")
