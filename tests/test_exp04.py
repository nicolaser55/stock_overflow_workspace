"""
Workspace Tests: exp04_trend_exit and the shared continuous walk-forward (so.core.replay_walk_forward)

Run from the workspace root:   python tests/test_exp04.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic data):
    1. The 9 candidates (3 buffers x 3 confirmations), unique and ordered.
    2. Signals: x = 0, n = 1 is "below / above the average"; the n-consecutive rule by hand; no look-ahead (signals on
       truncated data equal the signals on the full data).
    3. Candidate (x = 0, n = 1) replayed continuously equals so.core.reentry_simulation.simulate_trend_rule_dict; every
       exit and re-entry happens on a session where its signal is true.
    4. Candidate paths: one row per (candidate, period), excess = total - buy-and-hold, period returns chain to the total.
    5. Prior-only path: with one candidate it equals that candidate replayed over the path span; both random families
       have RANDOM_RUN_COUNT runs; ties select the largest buffer and confirmation; period f's choice governs f + 1.
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
from experiments.exp04_trend_exit import config as exp_config
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.core.reentry_simulation import simulate_trend_rule_dict
from so.core.continuous_replay import simulate_continuous_replay_dict
from so.core.replay_walk_forward import run_candidate_replay_dict, run_prior_only_replay_dict
from experiments.exp04_trend_exit.rules import get_schedule_tuple, get_rule_candidate_list, get_trend_exit_signal_arr, get_trend_reentry_signal_arr, get_rule_builder_func
from synthetic_data import get_synthetic_ohlcv_pdf

# DEFINE THE UNTOUCHED START USED BY THE TESTS (AFTER THE SYNTHETIC DATA)
TEST_UNTOUCHED_START_STR = "2030-01-01"
# DEFINE THE KEYS AND TIE-BREAKS OF THE SELECTION (AS THE NOTEBOOK)
KEY_COL_STR_LIST = ["buffer", "confirmation"]
TIE_BREAK_LIST = [("buffer", False), ("confirmation", False)]

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: TEST THE CANDIDATES
def test_candidates():
    # COLLECT THE CANDIDATES
    candidate_list = get_rule_candidate_list()
    # ASSERT 3 x 3 UNIQUE CANDIDATES, BUFFER FIRST
    assert len(candidate_list) == 9 and len({(c["buffer"], c["confirmation"]) for c in candidate_list}) == 9
    assert candidate_list[0] == {"buffer": 0.0, "confirmation": 1} and candidate_list[-1] == {"buffer": 0.05, "confirmation": 10}
    passed("rule candidates (3 buffers x 3 confirmations, unique, ordered)")

# FUNCTION: TEST THE SIGNALS
def test_signals(ohlcv_pdf_in, daily_pdf_in):
    # x = 0, n = 1 IS BELOW / ABOVE THE AVERAGE
    ma_dist_arr = daily_pdf_in["ma200_dist_pct"].to_numpy(dtype=float)
    assert (get_trend_exit_signal_arr(daily_pdf_in, 0.0, 1) == (np.nan_to_num(ma_dist_arr, nan=0.0) < 0)).all()
    assert (get_trend_reentry_signal_arr(daily_pdf_in, 0.0) == (np.nan_to_num(ma_dist_arr, nan=0.0) > 0)).all()
    assert not get_trend_exit_signal_arr(daily_pdf_in, 0.0, 1)[:200].any()
    # n CONSECUTIVE DECISIONS BELOW -x, BY HAND
    below_arr = np.nan_to_num(ma_dist_arr, nan=0.0) < -0.03
    hand_arr = np.array([idx >= 4 and below_arr[idx - 4:idx + 1].all() for idx in range(len(below_arr))])
    assert (get_trend_exit_signal_arr(daily_pdf_in, 0.03, 5) == hand_arr).all() and hand_arr.sum() > 0
    # NO LOOK-AHEAD: SIGNALS ON DATA TRUNCATED AFTER SESSION 600 EQUAL THE FULL-DATA SIGNALS UP TO SESSION 600
    truncated_pdf = ohlcv_pdf_in[ohlcv_pdf_in["date"] <= daily_pdf_in["date"].iloc[600]]
    truncated_daily_pdf = get_daily_feature_pdf(get_ohlcv_array_dict(truncated_pdf))
    for buffer, confirmation in [(0.0, 1), (0.03, 5), (0.05, 10)]:
        assert (get_trend_exit_signal_arr(truncated_daily_pdf, buffer, confirmation) == get_trend_exit_signal_arr(daily_pdf_in, buffer, confirmation)[:601]).all()
        assert (get_trend_reentry_signal_arr(truncated_daily_pdf, buffer) == get_trend_reentry_signal_arr(daily_pdf_in, buffer)[:601]).all()
    passed(f"signals (x = 0, n = 1 == below / above the average; 5-consecutive rule by hand, {int(hand_arr.sum())} sessions; no look-ahead)")

# FUNCTION: TEST THE RULE MECHANICS
def test_mechanics(ohlcv_array_dict_in, daily_pdf_in):
    # REPLAY THE TEXTBOOK CANDIDATE AND THE SHARED TREND RULE OVER THE SAME SPAN
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    span_start, span_end = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    rule_builder_func = get_rule_builder_func(daily_pdf_in)
    exit_signal_arr, reentry_func, reason_str = rule_builder_func({"buffer": 0.0, "confirmation": 1})
    replay_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=np.full(len(daily_pdf_in), np.nan),
                                                  reentry_func_in=reentry_func, reentry_reason_str_in=reason_str, exit_signal_arr_in=exit_signal_arr, max_cash_sessions_in=None)
    trend_dict = simulate_trend_rule_dict(ohlcv_array_dict_in, daily_pdf_in, span_start, span_end)
    assert np.isclose(replay_dict["metric_dict"]["total_return"], trend_dict["metric_dict"]["total_return"]) and replay_dict["metric_dict"]["signal_exit_count"] > 0
    # EVERY EXIT AND RE-ENTRY OF A BUFFERED CANDIDATE HAPPENS ON A SESSION WITH ITS SIGNAL
    exit_signal_arr, reentry_func, reason_str = rule_builder_func({"buffer": 0.03, "confirmation": 5})
    buffered_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=np.full(len(daily_pdf_in), np.nan),
                                                    reentry_func_in=reentry_func, reentry_reason_str_in=reason_str, exit_signal_arr_in=exit_signal_arr, max_cash_sessions_in=None)
    transaction_pdf = buffered_dict["transaction_pdf"]
    bar_session_arr = ohlcv_array_dict_in["bar_session_idx_arr"]
    assert exit_signal_arr[bar_session_arr[transaction_pdf.loc[transaction_pdf["exit_reason"] == "SIGNAL", "sell_idx"].to_numpy()]].all()
    reentry_signal_arr = get_trend_reentry_signal_arr(daily_pdf_in, 0.03)
    assert reentry_signal_arr[bar_session_arr[transaction_pdf.loc[transaction_pdf["entry_reason"] == "rule", "buy_idx"].to_numpy()]].all()
    passed(f"rule mechanics (x = 0, n = 1 == shared trend rule, {replay_dict['metric_dict']['signal_exit_count']} exits; buffered exits / re-entries on their signals)")

# FUNCTION: TEST THE CANDIDATE PATHS AND THE PRIOR-ONLY PATH
def test_walk_forward(ohlcv_array_dict_in, daily_pdf_in):
    # REPLAY THE 9 CANDIDATES
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    candidate_list = get_rule_candidate_list()
    rule_builder_func = get_rule_builder_func(daily_pdf_in)
    replay_dict = run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_list, rule_builder_func, TEST_UNTOUCHED_START_STR, None, 2, alert_in=False)
    candidate_period_pdf, candidate_summary_pdf = replay_dict["candidate_period_pdf"], replay_dict["candidate_summary_pdf"]
    # ONE ROW PER (CANDIDATE, PERIOD); EXCESS = TOTAL - BUY AND HOLD; PERIODS CHAIN TO THE TOTAL
    assert len(candidate_period_pdf) == 9 * len(period_pdf)
    assert np.allclose(candidate_period_pdf["valid_excess_return"], candidate_period_pdf["valid_total_return"] - candidate_period_pdf["valid_buy_hold_total_return"])
    chained_arr = candidate_period_pdf.groupby("candidate_idx")["valid_total_return"].apply(lambda s: np.prod(1 + s) - 1).to_numpy()
    assert np.allclose(chained_arr, candidate_summary_pdf.sort_values("candidate_idx")["strategy_total_return"].to_numpy(), atol=1e-9)
    # TIES: EVERY SCORE EQUAL -> LARGEST BUFFER AND CONFIRMATION
    tie_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf.assign(valid_excess_return=0.0), candidate_list, rule_builder_func,
                                          KEY_COL_STR_LIST, TIE_BREAK_LIST, 4, TEST_UNTOUCHED_START_STR, None, 2, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    assert (tie_dict["selection_pdf"]["buffer"] == 0.05).all() and (tie_dict["selection_pdf"]["confirmation"] == 10).all()
    # PRIOR-ONLY PATH: PERIOD f's CHOICE GOVERNS f + 1; THE PATH STARTS AT THE SECOND PERIOD
    prior_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf, candidate_list, rule_builder_func, KEY_COL_STR_LIST, TIE_BREAK_LIST, 4,
                                            TEST_UNTOUCHED_START_STR, None, exp_config.RANDOM_RUN_COUNT, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    selection_pdf, period_candidate_dict = prior_dict["selection_pdf"], prior_dict["period_candidate_dict"]
    period_id_list = period_pdf["period_id"].tolist()
    assert all(period_candidate_dict[period_id_list[i + 1]] == int(selection_pdf.loc[selection_pdf["fold_id"] == period_id_list[i], "candidate_idx"].iloc[0]) for i in range(len(period_id_list) - 1))
    assert prior_dict["path_period_pdf"]["period_id"].tolist() == period_id_list[1:]
    baseline_name_list = prior_dict["baseline_pdf"]["baseline"].tolist()
    assert sum(name.startswith("random_exit_") for name in baseline_name_list) == exp_config.RANDOM_RUN_COUNT
    assert sum(name.startswith("random_reentry_") for name in baseline_name_list) == exp_config.RANDOM_RUN_COUNT
    # WITH ONE CANDIDATE THE PATH EQUALS THAT CANDIDATE REPLAYED OVER THE PATH SPAN
    single_list = [candidate_list[4]]
    single_replay_dict = run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf, single_list, rule_builder_func, TEST_UNTOUCHED_START_STR, None, 2, alert_in=False)
    single_prior_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, single_replay_dict["candidate_period_pdf"], single_list, rule_builder_func, KEY_COL_STR_LIST,
                                                   TIE_BREAK_LIST, 4, TEST_UNTOUCHED_START_STR, None, 2, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    exit_signal_arr, reentry_func, reason_str = rule_builder_func(single_list[0])
    path_start, path_end = single_prior_dict["path_period_pdf"]["period_start"].iloc[0], single_prior_dict["path_period_pdf"]["period_end"].iloc[-1]
    direct_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, path_start, path_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=np.full(len(daily_pdf_in), np.nan),
                                                  reentry_func_in=reentry_func, reentry_reason_str_in=reason_str, exit_signal_arr_in=exit_signal_arr, max_cash_sessions_in=None)
    assert np.isclose(single_prior_dict["simulation_dict"]["metric_dict"]["total_return"], direct_dict["metric_dict"]["total_return"])
    assert np.isclose(single_prior_dict["summary_dict"]["strategy_total_return"], direct_dict["metric_dict"]["total_return"], atol=1e-8)
    passed(f"walk-forward (9 x {len(period_pdf)} candidate periods chain to their totals; ties -> x 5%, n 10; prior-only f -> f + 1; "
           f"single candidate == direct replay; {len(baseline_name_list)} baseline rows)")

"""
Runner
"""

# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    # GENERATE THE SYNTHETIC DATA (ABOUT 3.5 YEARS)
    print("Generating synthetic data...")
    synthetic_ohlcv_pdf = get_synthetic_ohlcv_pdf("2021-01-04", "2024-06-28", minute_vol_in=0.0006, seed_in=31)
    synthetic_ohlcv_array_dict = get_ohlcv_array_dict(synthetic_ohlcv_pdf)
    synthetic_daily_pdf = get_daily_feature_pdf(synthetic_ohlcv_array_dict)
    # RUN THE TESTS
    test_candidates()
    test_signals(synthetic_ohlcv_pdf, synthetic_daily_pdf)
    test_mechanics(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_walk_forward(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    print("\nAll exp04 tests passed ✅")
