"""
Workspace Tests: exp06_capped_regret_reentry and the cooling-off option of so.core.reentry_simulation

Run from the workspace root:   python tests/test_exp06.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic data):
    1. The 12 candidates (2 exit signals x 3 buy-stops x 2 cooling-offs), unique and ordered.
    2. Simulator cooling-off: with an always-true exit signal and an always-true re-entry, a rule that sets
       exit_block_sessions = 5 exits again exactly 6 decisions after each re-entry; without the key it exits at the next
       decision (the original behaviour).
    3. Re-entry rule by hand: the buy-stop fires at S x (1 + b) and requests the cooling-off; the recovery needs a close
       below the average since the exit decision.
    4. Mechanics: trend_ma200 with an unreachable buy-stop equals exp04's textbook rule (x = 0, n = 1); every buy-stop
       re-entry has its close >= S x (1 + b); no signal exit within c decisions after a buy-stop re-entry.
    5. Candidate paths chain to their totals; ties select cooling 20, buy-stop 1%, trend_ma200; period f governs f + 1.
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
from experiments.exp06_capped_regret_reentry import config as exp_config
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.core.reentry_simulation import simulate_stop_reentry_dict
from so.core.continuous_replay import simulate_continuous_replay_dict
from so.core.replay_walk_forward import run_candidate_replay_dict, run_prior_only_replay_dict
from experiments.exp04_trend_exit.rules import get_rule_builder_func as get_exp04_rule_builder_func
from experiments.exp06_capped_regret_reentry.rules import get_schedule_tuple, get_rule_candidate_list, get_exit_signal_arr, get_capped_reentry_func, \
                                                         get_rule_builder_func, get_trigger_summary_dict
from synthetic_data import get_synthetic_ohlcv_pdf

# DEFINE THE UNTOUCHED START USED BY THE TESTS (AFTER THE SYNTHETIC DATA)
TEST_UNTOUCHED_START_STR = "2030-01-01"
# DEFINE THE KEYS AND TIE-BREAKS OF THE SELECTION (AS THE NOTEBOOK)
KEY_COL_STR_LIST = ["exit_signal", "buy_stop", "cooling"]
TIE_BREAK_LIST = [("cooling", False), ("buy_stop", True), ("exit_order", True)]

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: GET THE SESSION OF EVERY SIGNAL EXIT AND RULE RE-ENTRY OF A SIMULATION
def get_event_session_tuple(simulation_dict_in, ohlcv_array_dict_in):
    transaction_pdf = simulation_dict_in["transaction_pdf"]
    bar_session_arr = ohlcv_array_dict_in["bar_session_idx_arr"]
    exit_arr = bar_session_arr[transaction_pdf.loc[transaction_pdf["exit_reason"] == "SIGNAL", "sell_idx"].to_numpy(dtype=int)]
    entry_arr = bar_session_arr[transaction_pdf.loc[transaction_pdf["entry_reason"] == "rule", "buy_idx"].to_numpy(dtype=int)]
    return exit_arr, entry_arr

# FUNCTION: TEST THE CANDIDATES
def test_candidates():
    # COLLECT THE CANDIDATES
    candidate_list = get_rule_candidate_list()
    # ASSERT 2 x 3 x 2 UNIQUE CANDIDATES IN ORDER
    assert len(candidate_list) == 12 and len({(c["exit_signal"], c["buy_stop"], c["cooling"]) for c in candidate_list}) == 12
    assert candidate_list[0] == {"exit_signal": "trend_ma200", "exit_order": 0, "buy_stop": 0.01, "cooling": 0}
    assert candidate_list[-1] == {"exit_signal": "ath_1pct", "exit_order": 1, "buy_stop": 0.03, "cooling": 20}
    passed("candidates (2 exit signals x 3 buy-stops x 2 cooling-offs, unique, ordered)")

# FUNCTION: TEST THE COOLING-OFF OPTION OF THE SIMULATOR
def test_simulator_cooling(ohlcv_array_dict_in):
    # DEFINE A WINDOW, AN ALWAYS-TRUE EXIT AND ALWAYS-TRUE RE-ENTRIES WITH AND WITHOUT A COOLING-OFF
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    date1, date2 = ohlcv_array_dict_in["session_date_list"][300], ohlcv_array_dict_in["session_date_list"][400]
    exit_arr = np.ones(session_count, dtype=bool)
    def cooling_func(session_idx, cash_session_count, episode_dict):
        episode_dict["exit_block_sessions"] = 5
        return True
    plain_func = lambda session_idx, cash_session_count, episode_dict: True
    # SIMULATE BOTH
    cooling_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1, date2, np.full(session_count, np.nan), None, cooling_func, "rule", exit_signal_arr_in=exit_arr)
    plain_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, date1, date2, np.full(session_count, np.nan), None, plain_func, "rule", exit_signal_arr_in=exit_arr)
    # WITH THE COOLING-OFF: THE NEXT EXIT IS 6 DECISIONS AFTER EACH RE-ENTRY
    exit_arr_c, entry_arr_c = get_event_session_tuple(cooling_dict, ohlcv_array_dict_in)
    assert len(entry_arr_c) > 5 and all(exit_arr_c[i + 1] - entry_arr_c[i] == 6 for i in range(len(entry_arr_c)) if i + 1 < len(exit_arr_c))
    # WITHOUT THE KEY: THE NEXT EXIT IS AT THE NEXT DECISION
    exit_arr_p, entry_arr_p = get_event_session_tuple(plain_dict, ohlcv_array_dict_in)
    assert all(exit_arr_p[i + 1] - entry_arr_p[i] == 1 for i in range(len(entry_arr_p)) if i + 1 < len(exit_arr_p))
    passed(f"simulator cooling-off (block 5 -> next exit 6 decisions after the re-entry, {len(entry_arr_c)} re-entries; absent key -> next decision)")

# FUNCTION: TEST THE RE-ENTRY RULE BY HAND
def test_reentry_rule():
    # BUILD A SMALL DAILY TABLE: SALE AT SESSION 2 (FILL 100), FIRST CASH DECISION 3
    daily_pdf = pd.DataFrame({"decision_close": [100, 100, 100, 101, 102.5, 99, 99, 103],
                              "ma200_dist_pct": [0.02, 0.02, 0.01, 0.01, 0.01, -0.01, 0.005, 0.02]})
    reentry_func = get_capped_reentry_func(daily_pdf, 0.02, 20)
    # NO TRIGGER AT 101 (BELOW THE BUY-STOP, NEVER BELOW THE AVERAGE)
    episode_dict = {"exit_fill_price": 100.0, "first_cash_session_idx": 3}
    assert not reentry_func(3, 1, episode_dict)
    # BUY-STOP AT 102.5 >= 102: REQUESTS THE COOLING-OFF
    assert reentry_func(4, 2, episode_dict) and episode_dict["reentry_trigger"] == "buy_stop" and episode_dict["exit_block_sessions"] == 20
    # RECOVERY: BELOW AT 5, ABOVE AT 6 (CLOSE 99 < 102)
    episode_dict = {"exit_fill_price": 100.0, "first_cash_session_idx": 3}
    assert not reentry_func(5, 3, episode_dict)
    assert reentry_func(6, 4, episode_dict) and episode_dict["reentry_trigger"] == "recovery" and episode_dict["exit_block_sessions"] == 0
    # AN EXIT DECISION BELOW THE AVERAGE ARMS THE RECOVERY AT ONCE (THE TREND EXIT CASE)
    episode_dict = {"exit_fill_price": 100.0, "first_cash_session_idx": 6}
    assert reentry_func(6, 1, episode_dict) and episode_dict["reentry_trigger"] == "recovery"
    passed("re-entry rule by hand (buy-stop at S x 1.02 with cooling 20; recovery only after a close below the average)")

# FUNCTION: TEST THE RULE MECHANICS
def test_mechanics(ohlcv_array_dict_in, daily_pdf_in):
    # DEFINE A SPAN
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    span_start, span_end = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    nan_arr = np.full(len(daily_pdf_in), np.nan)
    # TREND EXIT WITH AN UNREACHABLE BUY-STOP == exp04's TEXTBOOK RULE
    exit_arr = get_exit_signal_arr(daily_pdf_in, "trend_ma200")
    capped_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=nan_arr, reentry_func_in=get_capped_reentry_func(daily_pdf_in, 10.0, 0),
                                                  reentry_reason_str_in="rule", exit_signal_arr_in=exit_arr, max_cash_sessions_in=None)
    exp04_exit_arr, exp04_reentry_func, _ = get_exp04_rule_builder_func(daily_pdf_in)({"buffer": 0.0, "confirmation": 1})
    exp04_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=nan_arr, reentry_func_in=exp04_reentry_func,
                                                 reentry_reason_str_in="rule", exit_signal_arr_in=exp04_exit_arr, max_cash_sessions_in=None)
    assert np.isclose(capped_dict["metric_dict"]["total_return"], exp04_dict["metric_dict"]["total_return"]) and exp04_dict["metric_dict"]["signal_exit_count"] > 0
    # BUY-STOP RE-ENTRIES AND THE COOLING-OFF, FOR BOTH EXIT SIGNALS
    decision_close_arr = daily_pdf_in["decision_close"].to_numpy(dtype=float)
    stop_total = 0
    for exit_signal_str in ["trend_ma200", "ath_1pct"]:
        simulation_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=nan_arr,
                                                          reentry_func_in=get_capped_reentry_func(daily_pdf_in, 0.01, 20), reentry_reason_str_in="rule",
                                                          exit_signal_arr_in=get_exit_signal_arr(daily_pdf_in, exit_signal_str), max_cash_sessions_in=None)
        episode_pdf = simulation_dict["episode_pdf"]
        exit_session_arr, entry_session_arr = get_event_session_tuple(simulation_dict, ohlcv_array_dict_in)
        closed_pdf = episode_pdf[episode_pdf["reentry_reason"] != "window_end"].reset_index(drop=True)
        assert len(closed_pdf) == len(entry_session_arr)
        for episode_idx, episode_row in closed_pdf.iterrows():
            if episode_row["reentry_trigger"] == "buy_stop":
                stop_total += 1
                assert decision_close_arr[entry_session_arr[episode_idx]] >= episode_row["exit_fill_price"] * 1.01
                later_exit_arr = exit_session_arr[exit_session_arr > entry_session_arr[episode_idx]]
                assert len(later_exit_arr) == 0 or later_exit_arr[0] - entry_session_arr[episode_idx] > 20
        summary_dict = get_trigger_summary_dict(simulation_dict)
        assert summary_dict["buy_stop_count"] + summary_dict["recovery_count"] + summary_dict["open_count"] == summary_dict["episode_count"]
    assert stop_total > 0
    passed(f"mechanics (unreachable buy-stop == exp04 textbook rule; {stop_total} buy-stop re-entries at >= S x 1.01, none followed by an exit within 20 decisions)")

# FUNCTION: TEST THE CANDIDATE PATHS AND THE PRIOR-ONLY PATH
def test_walk_forward(ohlcv_array_dict_in, daily_pdf_in):
    # REPLAY THE 12 CANDIDATES
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    candidate_list = get_rule_candidate_list()
    rule_builder_func = get_rule_builder_func(daily_pdf_in)
    replay_dict = run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_list, rule_builder_func, TEST_UNTOUCHED_START_STR, None, 2, alert_in=False)
    candidate_period_pdf, candidate_summary_pdf = replay_dict["candidate_period_pdf"], replay_dict["candidate_summary_pdf"]
    # ONE ROW PER (CANDIDATE, PERIOD); PERIODS CHAIN TO THE TOTAL
    assert len(candidate_period_pdf) == 12 * len(period_pdf)
    chained_arr = candidate_period_pdf.groupby("candidate_idx")["valid_total_return"].apply(lambda s: np.prod(1 + s) - 1).to_numpy()
    assert np.allclose(chained_arr, candidate_summary_pdf.sort_values("candidate_idx")["strategy_total_return"].to_numpy(), atol=1e-9)
    # TIES: EVERY SCORE EQUAL -> COOLING 20, BUY-STOP 1%, TREND EXIT
    tie_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf.assign(valid_excess_return=0.0), candidate_list, rule_builder_func,
                                          KEY_COL_STR_LIST, TIE_BREAK_LIST, 4, TEST_UNTOUCHED_START_STR, None, 2, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    tie_selection_pdf = tie_dict["selection_pdf"]
    assert (tie_selection_pdf["cooling"] == 20).all() and (tie_selection_pdf["buy_stop"] == 0.01).all() and (tie_selection_pdf["exit_signal"] == "trend_ma200").all()
    # PRIOR-ONLY PATH: PERIOD f's CHOICE GOVERNS f + 1
    prior_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf, candidate_list, rule_builder_func, KEY_COL_STR_LIST, TIE_BREAK_LIST, 4,
                                            TEST_UNTOUCHED_START_STR, None, exp_config.RANDOM_RUN_COUNT, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    selection_pdf, period_candidate_dict = prior_dict["selection_pdf"], prior_dict["period_candidate_dict"]
    period_id_list = period_pdf["period_id"].tolist()
    assert all(period_candidate_dict[period_id_list[i + 1]] == int(selection_pdf.loc[selection_pdf["fold_id"] == period_id_list[i], "candidate_idx"].iloc[0]) for i in range(len(period_id_list) - 1))
    assert sum(name.startswith("random_exit_") for name in prior_dict["baseline_pdf"]["baseline"]) == exp_config.RANDOM_RUN_COUNT
    passed(f"walk-forward (12 x {len(period_pdf)} candidate periods chain to their totals; ties -> c 20, b 1%, trend; prior-only f -> f + 1)")

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
    test_simulator_cooling(synthetic_ohlcv_array_dict)
    test_reentry_rule()
    test_mechanics(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_walk_forward(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    print("\nAll exp06 tests passed ✅")
