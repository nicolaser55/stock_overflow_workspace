"""
Workspace Tests: exp07_warning_lights_exit

Run from the workspace root:   python tests/test_exp07.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic data):
    1. The 3 candidates (k = 3, 4, 5), ordered.
    2. Lights by hand from the features (a missing feature is off); the count is their sum; no look-ahead (lights on
       truncated data equal the lights on the full data).
    3. Mechanics: every exit happens on a decision with at least k lights on and every re-entry on a decision with fewer
       than k - 1; between an exit and its re-entry no decision has fewer than k - 1 lights (the first one re-enters).
    4. Candidate paths chain to their totals; ties select k = 5; period f's choice governs f + 1; both random families exist.
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
from experiments.exp07_warning_lights_exit import config as exp_config
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.core.continuous_replay import simulate_continuous_replay_dict
from so.core.replay_walk_forward import run_candidate_replay_dict, run_prior_only_replay_dict
from experiments.exp07_warning_lights_exit.rules import get_schedule_tuple, get_rule_candidate_list, get_light_pdf, get_rule_builder_func
from synthetic_data import get_synthetic_ohlcv_pdf

# DEFINE THE UNTOUCHED START USED BY THE TESTS (AFTER THE SYNTHETIC DATA)
TEST_UNTOUCHED_START_STR = "2030-01-01"
# DEFINE THE KEYS AND TIE-BREAKS OF THE SELECTION (AS THE NOTEBOOK)
KEY_COL_STR_LIST = ["light_k"]
TIE_BREAK_LIST = [("light_k", False)]

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: TEST THE CANDIDATES
def test_candidates():
    # ASSERT k = 3, 4, 5 IN ORDER
    assert get_rule_candidate_list() == [{"light_k": 3}, {"light_k": 4}, {"light_k": 5}]
    passed("candidates (k = 3, 4, 5)")

# FUNCTION: TEST THE LIGHTS
def test_lights(ohlcv_pdf_in, daily_pdf_in):
    # LIGHTS BY HAND
    light_pdf = get_light_pdf(daily_pdf_in)
    hand_dict = {"below_ma200": daily_pdf_in["ma200_dist_pct"] < 0, "return_250d_negative": daily_pdf_in["return_250d"] < 0,
                 "volatility_rising": daily_pdf_in["volatility_ratio_20_60"] > 1.2, "ath_drawdown_10pct": daily_pdf_in["ath_drawdown_pct"] < -0.10,
                 "high60_stale": daily_pdf_in["sessions_since_high60"] > 20}
    for light_str, hand_series in hand_dict.items():
        assert (light_pdf[light_str].to_numpy() == hand_series.fillna(False).to_numpy(dtype=bool)).all(), light_str
    assert (light_pdf["light_count"] == light_pdf[list(hand_dict)].sum(axis=1)).all()
    # MISSING FEATURES ARE OFF (THE FIRST 250 SESSIONS HAVE NO 250-SESSION RETURN)
    assert not light_pdf["return_250d_negative"].iloc[:250].any()
    # NO LOOK-AHEAD: LIGHTS ON DATA TRUNCATED AFTER SESSION 600 EQUAL THE FULL-DATA LIGHTS UP TO SESSION 600
    truncated_pdf = ohlcv_pdf_in[ohlcv_pdf_in["date"] <= daily_pdf_in["date"].iloc[600]]
    truncated_light_pdf = get_light_pdf(get_daily_feature_pdf(get_ohlcv_array_dict(truncated_pdf)))
    assert truncated_light_pdf.drop(columns="date").equals(light_pdf.drop(columns="date").iloc[:601].reset_index(drop=True))
    passed(f"lights (by hand; missing = off; no look-ahead; max {int(light_pdf['light_count'].max())} lights on, {int((light_pdf['light_count'] >= 3).sum())} decisions with >= 3)")

# FUNCTION: TEST THE RULE MECHANICS
def test_mechanics(ohlcv_array_dict_in, daily_pdf_in):
    # REPLAY k = 3 OVER THE WHOLE DATA AFTER THE FIRST 260 SESSIONS
    light_count_arr = get_light_pdf(daily_pdf_in)["light_count"].to_numpy()
    rule_builder_func = get_rule_builder_func(daily_pdf_in)
    session_date_list = ohlcv_array_dict_in["session_date_list"]
    exit_total = 0
    for light_k in [3, 4]:
        exit_signal_arr, reentry_func, reason_str = rule_builder_func({"light_k": light_k})
        simulation_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, session_date_list[260], session_date_list[-1], TEST_UNTOUCHED_START_STR,
                                                          volatility_arr_in=np.full(len(daily_pdf_in), np.nan), reentry_func_in=reentry_func,
                                                          reentry_reason_str_in=reason_str, exit_signal_arr_in=exit_signal_arr, max_cash_sessions_in=None)
        transaction_pdf = simulation_dict["transaction_pdf"]
        bar_session_arr = ohlcv_array_dict_in["bar_session_idx_arr"]
        exit_session_arr = bar_session_arr[transaction_pdf.loc[transaction_pdf["exit_reason"] == "SIGNAL", "sell_idx"].to_numpy(dtype=int)]
        entry_session_arr = bar_session_arr[transaction_pdf.loc[transaction_pdf["entry_reason"] == "rule", "buy_idx"].to_numpy(dtype=int)]
        # EXITS WITH >= k LIGHTS, RE-ENTRIES WITH < k - 1, AND THE FIRST SUCH DECISION AFTER THE EXIT RE-ENTERS
        assert (light_count_arr[exit_session_arr] >= light_k).all() and (light_count_arr[entry_session_arr] < light_k - 1).all()
        for exit_session, entry_session in zip(exit_session_arr, entry_session_arr):
            assert (light_count_arr[exit_session + 1:entry_session] >= light_k - 1).all()
        exit_total += len(exit_session_arr)
    assert exit_total > 0
    passed(f"mechanics (exits at >= k lights, re-entries at the first decision with < k - 1; {exit_total} exits for k = 3, 4)")

# FUNCTION: TEST THE CANDIDATE PATHS AND THE PRIOR-ONLY PATH
def test_walk_forward(ohlcv_array_dict_in, daily_pdf_in):
    # REPLAY THE 3 CANDIDATES
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    candidate_list = get_rule_candidate_list()
    rule_builder_func = get_rule_builder_func(daily_pdf_in)
    replay_dict = run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_list, rule_builder_func, TEST_UNTOUCHED_START_STR, None, 2, alert_in=False)
    candidate_period_pdf, candidate_summary_pdf = replay_dict["candidate_period_pdf"], replay_dict["candidate_summary_pdf"]
    # ONE ROW PER (CANDIDATE, PERIOD); PERIODS CHAIN TO THE TOTAL
    assert len(candidate_period_pdf) == 3 * len(period_pdf)
    chained_arr = candidate_period_pdf.groupby("candidate_idx")["valid_total_return"].apply(lambda s: np.prod(1 + s) - 1).to_numpy()
    assert np.allclose(chained_arr, candidate_summary_pdf.sort_values("candidate_idx")["strategy_total_return"].to_numpy(), atol=1e-9)
    # TIES: EVERY SCORE EQUAL -> k = 5
    tie_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf.assign(valid_excess_return=0.0), candidate_list, rule_builder_func,
                                          KEY_COL_STR_LIST, TIE_BREAK_LIST, 4, TEST_UNTOUCHED_START_STR, None, 2, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    assert (tie_dict["selection_pdf"]["light_k"] == 5).all()
    # PRIOR-ONLY PATH: PERIOD f's CHOICE GOVERNS f + 1; BOTH RANDOM FAMILIES
    prior_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf, candidate_list, rule_builder_func, KEY_COL_STR_LIST, TIE_BREAK_LIST, 4,
                                            TEST_UNTOUCHED_START_STR, None, exp_config.RANDOM_RUN_COUNT, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    selection_pdf, period_candidate_dict = prior_dict["selection_pdf"], prior_dict["period_candidate_dict"]
    period_id_list = period_pdf["period_id"].tolist()
    assert all(period_candidate_dict[period_id_list[i + 1]] == int(selection_pdf.loc[selection_pdf["fold_id"] == period_id_list[i], "candidate_idx"].iloc[0]) for i in range(len(period_id_list) - 1))
    baseline_name_list = prior_dict["baseline_pdf"]["baseline"].tolist()
    assert sum(name.startswith("random_exit_") for name in baseline_name_list) == exp_config.RANDOM_RUN_COUNT
    assert sum(name.startswith("random_reentry_") for name in baseline_name_list) == exp_config.RANDOM_RUN_COUNT
    passed(f"walk-forward (3 x {len(period_pdf)} candidate periods chain to their totals; ties -> k = 5; prior-only f -> f + 1; {len(baseline_name_list)} baseline rows)")

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
    test_lights(synthetic_ohlcv_pdf, synthetic_daily_pdf)
    test_mechanics(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_walk_forward(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    print("\nAll exp07 tests passed ✅")
