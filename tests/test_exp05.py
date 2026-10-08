"""
Workspace Tests: exp05_vol_scaled_exposure

Run from the workspace root:   python tests/test_exp05.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic data):
    1. The 4 candidates (2 floors x 2 target quantiles), unique and ordered.
    2. Target volatility: the quantile of the values before the period start (by hand); the session before the first
       period gets the first target; changing later volatility values does not change a period's target (no look-ahead).
    3. Weights: w = min(1, max(floor, target / volatility)) by hand; 1 where the volatility is missing.
    4. A weight path of 1 equals buy-and-hold; a path of the floor holds about the floor.
    5. Candidate paths: one row per (candidate, period), period returns chain to the total; prior-only: ties select the
       highest floor and quantile, period f's choice governs f + 1, a single candidate equals its direct replay, the
       constant-exposure and RANDOM_RUN_COUNT random-shift baselines exist, shifts lie in the allowed range.
    6. Signal check: forward volatility by hand; a persistent volatility regime passes, the bin table covers every row.
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
from experiments.exp05_vol_scaled_exposure import config as exp_config
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.core.reentry_simulation import get_buy_and_hold_result_dict
from experiments.exp05_vol_scaled_exposure.exposure import get_schedule_tuple, get_rule_candidate_list, get_target_volatility_arr, get_weight_arr, \
                                                           get_weight_builder_func, simulate_weight_path_dict, run_candidate_exposure_dict, \
                                                           run_prior_only_exposure_dict, get_forward_volatility_arr, get_volatility_signal_check_dict, \
                                                           get_volatility_bin_return_pdf
from synthetic_data import get_synthetic_ohlcv_pdf

# DEFINE THE UNTOUCHED START USED BY THE TESTS (AFTER THE SYNTHETIC DATA)
TEST_UNTOUCHED_START_STR = "2030-01-01"

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: TEST THE CANDIDATES
def test_candidates():
    # COLLECT THE CANDIDATES
    candidate_list = get_rule_candidate_list()
    # ASSERT 2 x 2 UNIQUE CANDIDATES, FLOOR FIRST
    assert len(candidate_list) == 4 and len({(c["floor"], c["target_quantile"]) for c in candidate_list}) == 4
    assert candidate_list[0] == {"floor": 0.3, "target_quantile": 0.5} and candidate_list[-1] == {"floor": 0.5, "target_quantile": 0.75}
    passed("candidates (2 floors x 2 target quantiles, unique, ordered)")

# FUNCTION: TEST THE TARGETS AND THE WEIGHTS
def test_weights(ohlcv_array_dict_in, daily_pdf_in):
    # BUILD THE PERIODS AND THE TARGETS
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    target_arr = get_target_volatility_arr(daily_pdf_in, period_pdf, 0.75)
    date_arr = np.array(daily_pdf_in["date"].tolist())
    volatility_arr = daily_pdf_in["daily_volatility"].to_numpy(dtype=float)
    # BY HAND: THE THIRD PERIOD
    period_row = period_pdf.iloc[2]
    history_arr = volatility_arr[(date_arr < period_row["period_start"]) & np.isfinite(volatility_arr)]
    in_period_arr = (date_arr >= period_row["period_start"]) & (date_arr <= period_row["period_end"])
    assert np.allclose(target_arr[in_period_arr], np.quantile(history_arr, 0.75))
    # THE SESSION BEFORE THE FIRST PERIOD HAS THE FIRST TARGET; EARLIER SESSIONS HAVE NONE
    first_idx = int(np.flatnonzero(date_arr == period_pdf["period_start"].iloc[0])[0])
    assert target_arr[first_idx - 1] == target_arr[first_idx] and np.isnan(target_arr[:first_idx - 1]).all()
    # NO LOOK-AHEAD: CHANGING THE VOLATILITY FROM THE THIRD PERIOD ON DOES NOT CHANGE THE THIRD PERIOD'S TARGET
    changed_pdf = daily_pdf_in.copy()
    changed_pdf.loc[date_arr >= period_row["period_start"], "daily_volatility"] *= 10
    assert np.allclose(get_target_volatility_arr(changed_pdf, period_pdf, 0.75)[in_period_arr], target_arr[in_period_arr])
    # WEIGHTS BY HAND
    weight_arr = get_weight_arr(daily_pdf_in, target_arr, 0.3)
    valid_arr = np.isfinite(target_arr) & np.isfinite(volatility_arr)
    assert np.allclose(weight_arr[valid_arr], np.minimum(1, np.maximum(0.3, target_arr[valid_arr] / volatility_arr[valid_arr])))
    assert (weight_arr[~valid_arr] == 1).all() and weight_arr.min() >= 0.3 and (weight_arr[valid_arr] < 1).any()
    missing_pdf = daily_pdf_in.assign(daily_volatility=np.nan)
    assert (get_weight_arr(missing_pdf, target_arr, 0.3) == 1).all()
    passed(f"targets and weights (quantile of the earlier values by hand; no look-ahead; w by hand, {int((weight_arr[valid_arr] < 1).sum())} sessions below 1)")

# FUNCTION: TEST THE WEIGHT PATH SIMULATION
def test_weight_path(ohlcv_array_dict_in, daily_pdf_in):
    # DEFINE A SPAN
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    span_start, span_end = period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]
    session_count = len(daily_pdf_in)
    # A PATH OF 1 EQUALS BUY AND HOLD
    one_dict = simulate_weight_path_dict(ohlcv_array_dict_in, span_start, span_end, np.ones(session_count), TEST_UNTOUCHED_START_STR)
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end)
    assert np.isclose(one_dict["metric_dict"]["total_return"], buy_hold_dict["metric_dict"]["total_return"], atol=1e-6)
    # A PATH OF 0.4 STARTS AT 0.4 AND STAYS NEAR IT (DEAD BAND)
    floor_dict = simulate_weight_path_dict(ohlcv_array_dict_in, span_start, span_end, np.full(session_count, 0.4), TEST_UNTOUCHED_START_STR)
    assert abs(floor_dict["metric_dict"]["mean_weight"] - 0.4) < exp_config.DEAD_BAND
    # THE GUARD REFUSES A SPAN ENDING ON OR AFTER THE UNTOUCHED START
    try:
        simulate_weight_path_dict(ohlcv_array_dict_in, span_start, span_end, np.ones(session_count), str(span_end))
        raise AssertionError("guard did not fire")
    except ValueError:
        pass
    passed(f"weight path (w = 1 == buy-and-hold; w = 0.4 holds {floor_dict['metric_dict']['mean_weight']:.1%}; guard)")

# FUNCTION: TEST THE CANDIDATE PATHS AND THE PRIOR-ONLY PATH
def test_walk_forward(ohlcv_array_dict_in, daily_pdf_in):
    # REPLAY THE 4 CANDIDATES
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    candidate_list = get_rule_candidate_list()
    weight_builder_func = get_weight_builder_func(daily_pdf_in, period_pdf)
    replay_dict = run_candidate_exposure_dict(ohlcv_array_dict_in, period_pdf, candidate_list, weight_builder_func, TEST_UNTOUCHED_START_STR, 2, alert_in=False)
    candidate_period_pdf, candidate_summary_pdf = replay_dict["candidate_period_pdf"], replay_dict["candidate_summary_pdf"]
    # ONE ROW PER (CANDIDATE, PERIOD); PERIODS CHAIN TO THE TOTAL
    assert len(candidate_period_pdf) == 4 * len(period_pdf)
    chained_arr = candidate_period_pdf.groupby("candidate_idx")["valid_total_return"].apply(lambda s: np.prod(1 + s) - 1).to_numpy()
    assert np.allclose(chained_arr, candidate_summary_pdf.sort_values("candidate_idx")["strategy_total_return"].to_numpy(), atol=1e-9)
    assert (candidate_period_pdf["valid_mean_weight"] <= 1 + 1e-9).all()
    # TIES: EVERY SCORE EQUAL -> HIGHEST FLOOR AND QUANTILE
    tie_dict = run_prior_only_exposure_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf.assign(valid_excess_return=0.0), candidate_list, weight_builder_func,
                                            TEST_UNTOUCHED_START_STR, random_run_count_in=2, random_shift_min_in=20, block_month_count_in=2)
    assert (tie_dict["selection_pdf"]["floor"] == 0.5).all() and (tie_dict["selection_pdf"]["target_quantile"] == 0.75).all()
    # PRIOR-ONLY PATH: PERIOD f's CHOICE GOVERNS f + 1; BASELINES
    prior_dict = run_prior_only_exposure_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf, candidate_list, weight_builder_func, TEST_UNTOUCHED_START_STR,
                                              random_shift_min_in=20, block_month_count_in=2)
    selection_pdf, period_candidate_dict = prior_dict["selection_pdf"], prior_dict["period_candidate_dict"]
    period_id_list = period_pdf["period_id"].tolist()
    assert all(period_candidate_dict[period_id_list[i + 1]] == int(selection_pdf.loc[selection_pdf["fold_id"] == period_id_list[i], "candidate_idx"].iloc[0]) for i in range(len(period_id_list) - 1))
    baseline_pdf = prior_dict["baseline_pdf"]
    shift_arr = baseline_pdf.loc[baseline_pdf["baseline"].str.startswith("random_shift_"), "shift_sessions"].to_numpy()
    window_count = int(np.isfinite(prior_dict["weight_arr"]).sum())
    assert len(shift_arr) == exp_config.RANDOM_RUN_COUNT and (shift_arr >= 20).all() and (shift_arr < window_count - 20).all()
    assert (baseline_pdf["baseline"] == "constant_exposure").sum() == 1
    assert np.isclose(prior_dict["baseline_summary_dict"]["constant_exposure_weight"], prior_dict["simulation_dict"]["metric_dict"]["mean_weight"])
    # WITH ONE CANDIDATE THE PATH EQUALS THAT CANDIDATE REPLAYED OVER THE PATH SPAN
    single_list = [candidate_list[1]]
    single_replay_dict = run_candidate_exposure_dict(ohlcv_array_dict_in, period_pdf, single_list, weight_builder_func, TEST_UNTOUCHED_START_STR, 2, alert_in=False)
    single_prior_dict = run_prior_only_exposure_dict(ohlcv_array_dict_in, period_pdf, single_replay_dict["candidate_period_pdf"], single_list, weight_builder_func,
                                                     TEST_UNTOUCHED_START_STR, random_run_count_in=2, random_shift_min_in=20, block_month_count_in=2)
    path_start, path_end = single_prior_dict["path_period_pdf"]["period_start"].iloc[0], single_prior_dict["path_period_pdf"]["period_end"].iloc[-1]
    direct_dict = simulate_weight_path_dict(ohlcv_array_dict_in, path_start, path_end, weight_builder_func(single_list[0]), TEST_UNTOUCHED_START_STR)
    assert np.isclose(single_prior_dict["simulation_dict"]["metric_dict"]["total_return"], direct_dict["metric_dict"]["total_return"])
    assert np.isclose(single_prior_dict["summary_dict"]["strategy_total_return"], direct_dict["metric_dict"]["total_return"], atol=1e-8)
    passed(f"walk-forward (4 x {len(period_pdf)} candidate periods chain to their totals; ties -> floor 50%, q 75%; prior-only f -> f + 1; "
           f"single candidate == direct replay; {len(baseline_pdf)} baseline rows)")

# FUNCTION: TEST THE SIGNAL CHECK
def test_signal_check():
    # BUILD A DAILY TABLE WITH PERSISTENT VOLATILITY REGIMES (0.5% AND 2% DAILY, 120-SESSION BLOCKS)
    rng = np.random.default_rng(5)
    session_count = 1500
    date_list = list(pd.bdate_range("2010-01-04", periods=session_count).date)
    regime_arr = np.where((np.arange(session_count) // 120) % 2 == 0, 0.005, 0.02)
    close_arr = 100 * np.exp(np.cumsum(rng.normal(0, regime_arr)))
    daily_pdf = pd.DataFrame({"date": date_list, "session_close": close_arr, "fill_open": close_arr})
    daily_return_series = daily_pdf["session_close"] / daily_pdf["session_close"].shift(1) - 1
    daily_pdf["daily_volatility"] = daily_return_series.rolling(20, min_periods=20).std().shift(1)
    # FORWARD VOLATILITY BY HAND (SESSION 100: RETURNS OF SESSIONS 101..120)
    forward_arr = get_forward_volatility_arr(daily_pdf, 20)
    assert np.isclose(forward_arr[100], np.std(daily_return_series.iloc[101:121].to_numpy(), ddof=1)) and np.isnan(forward_arr[-20:]).all()
    # THE PERSISTENT REGIME PASSES
    check_dict = get_volatility_signal_check_dict(daily_pdf, date_list[0], date_list[-1], 20, 200, 6)
    assert check_dict["passed"] and check_dict["spearman"] > 0.5 and check_dict["ci_low"] <= check_dict["spearman"] <= check_dict["ci_high"]
    # THE BIN TABLE COVERS EVERY ROW WITH A FORWARD RETURN
    bin_pdf = get_volatility_bin_return_pdf(daily_pdf, date_list[0], date_list[-1], 20, 5)
    expected_count = int((np.isfinite(daily_pdf["daily_volatility"].to_numpy()) & (np.arange(session_count) < session_count - 20)).sum())
    assert len(bin_pdf) == 5 and int(bin_pdf["row_count"].sum()) == expected_count
    passed(f"signal check (forward volatility by hand; regime series: Spearman {check_dict['spearman']:.2f} [{check_dict['ci_low']:.2f}, {check_dict['ci_high']:.2f}] passes; 5 bins)")

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
    test_weights(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_weight_path(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_walk_forward(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_signal_check()
    print("\nAll exp05 tests passed ✅")
