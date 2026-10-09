"""
Workspace Tests: exp13_e1m1_robustness

Run from the workspace root:   python tests/test_exp13.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic SPY bars and the synthetic VIX table of tests/test_exp12.py):
    1. The configuration: 36 grid variants containing E1M1 (0.85 / 200 / on), the expected trials (81) within the budget.
    2. The average distances: the 200-session distance recomputed equals so.features.daily_features's ma200_dist_pct.
    3. The variant builder at 0.85 / 200 / on trades exactly as exp12's frozen E1M1; other variants use their own
       average and ratio; without the fresh-signal rule an M1 re-entry can be followed at once by a new exit.
    4. Delayed execution: on a fixed rule every trade happens exactly one session later; on E1M1 every delayed M1
       re-entry satisfies the fade at the previous session with the maximum starting at the original exit decision.
    5. The VIX shift: features rolled by k in the share range, dates in place, deterministic per run (exp08's formula).
    6. The null summary by hand (p, rank, percentiles).
    7. Parallel null runs equal sequential runs (VIX placebo and both random families), whatever the chunks.
    8. The random families follow so.core.replay_walk_forward's convention (run 0 by hand).
    9. Reports: the stress scorecard (VIX maximum, lowest close after an M1 re-entry), the sub-span log excess sums to
       the total, the split by re-entry reason multiplies to the product of S/R, the verdict rule by hand.
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
from experiments.exp13_e1m1_robustness import config as exp_config
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.core.reentry_simulation import get_buy_and_hold_result_dict, get_random_reentry_func
from so.core.continuous_replay import get_episode_scorecard_pdf
from so.core.replay_walk_forward import get_path_random_probability_dict
from experiments.exp12_vix_fear_reentry.rules import get_rule_candidate_list, get_m1_trigger_bool, get_vix_scorecard_pdf
from experiments.exp13_e1m1_robustness.robustness import get_ma_dist_arr, add_ma_dist_col_pdf, get_frozen_rule_tuple, get_variant_rule_tuple, \
    get_delayed_rule_tuple, replay_rule_dict, get_path_metric_dict, get_stress_scorecard_pdf, get_shifted_vix_feature_pdf, run_vix_placebo_run_list, \
    run_random_family_run_list, run_parallel_null_pdf, get_null_summary_dict, get_span_log_excess_pdf, get_reason_split_pdf, get_verdict_dict, \
    get_stress_start_date, get_year_period_pdf
from synthetic_data import get_synthetic_ohlcv_pdf
from test_exp12 import get_synthetic_vix_feature_pdf, get_trade_session_tuple

# DEFINE THE FIRST REPLAYED SESSION (AFTER THE 250-SESSION FEATURES EXIST)
FIRST_REPLAY_SESSION_IDX = 260

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: GET THE REPLAY WINDOW OF THE SYNTHETIC DATA
def get_window_tuple(ohlcv_array_dict_in):
    session_date_list = ohlcv_array_dict_in["session_date_list"]
    return session_date_list[FIRST_REPLAY_SESSION_IDX], session_date_list[-1]

# FUNCTION: COLLECT THE TRADES OF A SIMULATION (SESSION OF EVERY SIGNAL EXIT AND RULE RE-ENTRY)
def get_trade_list(simulation_dict_in, ohlcv_array_dict_in):
    exit_arr, entry_arr = get_trade_session_tuple(simulation_dict_in, ohlcv_array_dict_in)
    return exit_arr.tolist(), entry_arr.tolist()

"""
Tests
"""

# TEST 1: THE CONFIGURATION
def test_config():
    grid_list = [(r, n, f) for r in exp_config.FADE_RATIO_LIST for n in exp_config.MA_LENGTH_LIST for f in exp_config.FRESH_EXIT_BOOL_LIST]
    assert len(grid_list) == 36 and len(set(grid_list)) == 36
    assert (exp_config.FROZEN_M1_FADE_RATIO, exp_config.FROZEN_MA_LENGTH, exp_config.FROZEN_FRESH_EXIT_BOOL) in grid_list
    assert exp_config.FROZEN_MA_DIST_COL_STR == f"ma{exp_config.FROZEN_MA_LENGTH}_dist_pct"
    assert sum(exp_config.EXPECTED_STEP_TRIAL_COUNT_DICT.values()) == 81 <= exp_config.TRIAL_BUDGET
    assert exp_config.DEV_END_DATE_STR < exp_config.UNTOUCHED_START_DATE_STR and exp_config.STRESS_DATA_CUTOFF_DATE_STR < exp_config.DEV_START_DATE_STR
    passed("config (36 variants with E1M1 = 0.85 / 200 / on; 81 expected trials <= budget 150; spans before the untouched window)")

# TEST 2: THE AVERAGE DISTANCES
def test_ma_dist(daily_pdf_in):
    recomputed_arr, existing_arr = get_ma_dist_arr(daily_pdf_in, 200), daily_pdf_in["ma200_dist_pct"].to_numpy(dtype=float)
    assert np.array_equal(np.isnan(recomputed_arr), np.isnan(existing_arr)) and np.array_equal(recomputed_arr[~np.isnan(existing_arr)], existing_arr[~np.isnan(existing_arr)])
    for ma_length in [150, 250]:
        assert int(np.isnan(daily_pdf_in[f"ma{ma_length}_dist_pct"].to_numpy(dtype=float)).sum()) == ma_length
    passed("ma distances (200 recomputed = daily_features's ma200_dist_pct; 150 / 250 NaN for their first n sessions)")

# TEST 3: THE VARIANT BUILDER
def test_variants(ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in):
    date1, date2 = get_window_tuple(ohlcv_array_dict_in)
    frozen_sim = replay_rule_dict(ohlcv_array_dict_in, get_frozen_rule_tuple(daily_pdf_in, vix_feature_pdf_in), date1, date2)
    variant_sim = replay_rule_dict(ohlcv_array_dict_in, get_variant_rule_tuple(daily_pdf_in, vix_feature_pdf_in, 0.85, 200, True), date1, date2)
    # THE FROZEN POINT TRADES EXACTLY AS exp12's E1M1
    assert get_trade_list(frozen_sim, ohlcv_array_dict_in) == get_trade_list(variant_sim, ohlcv_array_dict_in)
    assert frozen_sim["metric_dict"]["total_return"] == variant_sim["metric_dict"]["total_return"]
    assert frozen_sim["episode_pdf"]["reentry_trigger"].tolist() == variant_sim["episode_pdf"]["reentry_trigger"].tolist()
    # ANOTHER AVERAGE: EVERY SIGNAL EXIT IS BELOW ITS OWN AVERAGE
    ma150_sim = replay_rule_dict(ohlcv_array_dict_in, get_variant_rule_tuple(daily_pdf_in, vix_feature_pdf_in, 0.85, 150, True), date1, date2)
    exit_list, _ = get_trade_list(ma150_sim, ohlcv_array_dict_in)
    assert len(exit_list) > 0 and all(daily_pdf_in["ma150_dist_pct"].iloc[s] < 0 for s in exit_list)
    # ANOTHER RATIO: EVERY M1 RE-ENTRY SATISFIES ITS OWN RATIO
    level_arr = vix_feature_pdf_in["vix_level_prev"].to_numpy(dtype=float)
    ratio_sim = replay_rule_dict(ohlcv_array_dict_in, get_variant_rule_tuple(daily_pdf_in, vix_feature_pdf_in, 0.95, 200, True), date1, date2)
    ratio_exit_list, ratio_entry_list = get_trade_list(ratio_sim, ohlcv_array_dict_in)
    trigger_list = ratio_sim["episode_pdf"]["reentry_trigger"].tolist()
    m1_count = 0
    for exit_session, entry_session, trigger_str in zip(ratio_exit_list, ratio_entry_list, trigger_list):
        if trigger_str == "M1":
            assert get_m1_trigger_bool(level_arr, exit_session, entry_session, 0.95)
            m1_count += 1
    # WITHOUT THE FRESH-SIGNAL RULE: SOME M1 RE-ENTRY IS FOLLOWED BY AN EXIT AT THE NEXT DECISION (SIGNAL STILL ON)
    off_sim = replay_rule_dict(ohlcv_array_dict_in, get_variant_rule_tuple(daily_pdf_in, vix_feature_pdf_in, 0.85, 200, False), date1, date2)
    off_exit_list, off_entry_list = get_trade_list(off_sim, ohlcv_array_dict_in)
    off_trigger_list = off_sim["episode_pdf"]["reentry_trigger"].tolist()
    assert any(trigger_str == "M1" and entry_session + 1 in off_exit_list for entry_session, trigger_str in zip(off_entry_list, off_trigger_list))
    assert "require_fresh_exit" not in off_sim["episode_pdf"].columns or not off_sim["episode_pdf"]["require_fresh_exit"].fillna(False).any()
    passed(f"variants (0.85 / 200 / on = frozen E1M1 trade for trade; 150-session exits below their average; {m1_count} M1 re-entries at ratio 0.95; fresh off re-exits at once)")

# TEST 4: DELAYED EXECUTION
def test_delay(ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in):
    date1, date2 = get_window_tuple(ohlcv_array_dict_in)
    session_count = len(daily_pdf_in)
    # A FIXED RULE: EXIT SIGNAL ON SESSIONS 300-305 AND 500-510, RE-ENTRY ON SESSIONS 320 AND 530
    exit_arr = np.zeros(session_count, dtype=bool)
    exit_arr[300:306], exit_arr[500:511] = True, True
    fixed_rule_tuple = (exit_arr, lambda s, c, ep: s in (320, 530), "rule")
    base_exit_list, base_entry_list = get_trade_list(replay_rule_dict(ohlcv_array_dict_in, fixed_rule_tuple, date1, date2), ohlcv_array_dict_in)
    delayed_exit_list, delayed_entry_list = get_trade_list(replay_rule_dict(ohlcv_array_dict_in, get_delayed_rule_tuple(fixed_rule_tuple, 1), date1, date2), ohlcv_array_dict_in)
    assert base_exit_list == [300, 500] and base_entry_list == [320, 530]
    assert delayed_exit_list == [s + 1 for s in base_exit_list] and delayed_entry_list == [s + 1 for s in base_entry_list]
    # THE FROZEN E1M1 DELAYED: EVERY EXIT FOLLOWS A SIGNAL OF THE PREVIOUS SESSION, EVERY M1 RE-ENTRY THE FADE OF THE PREVIOUS SESSION
    frozen_rule_tuple = get_frozen_rule_tuple(daily_pdf_in, vix_feature_pdf_in)
    delayed_sim = replay_rule_dict(ohlcv_array_dict_in, get_delayed_rule_tuple(frozen_rule_tuple, 1), date1, date2)
    exit_list, entry_list = get_trade_list(delayed_sim, ohlcv_array_dict_in)
    level_arr = vix_feature_pdf_in["vix_level_prev"].to_numpy(dtype=float)
    assert len(exit_list) > 0 and all(frozen_rule_tuple[0][s - 1] for s in exit_list)
    m1_count = 0
    for exit_session, entry_session, trigger_str in zip(exit_list, entry_list, delayed_sim["episode_pdf"]["reentry_trigger"].tolist()):
        if trigger_str == "M1":
            assert get_m1_trigger_bool(level_arr, exit_session - 1, entry_session - 1)
            m1_count += 1
    assert m1_count > 0
    passed(f"delay (fixed rule: every trade one session later; delayed E1M1: {len(exit_list)} exits on the previous session's signal, {m1_count} M1 re-entries on the previous session's fade)")

# TEST 5: THE VIX SHIFT
def test_shift(vix_feature_pdf_in):
    shifted_pdf, shift_int = get_shifted_vix_feature_pdf(vix_feature_pdf_in, 3)
    shifted_again_pdf, shift_again_int = get_shifted_vix_feature_pdf(vix_feature_pdf_in, 3)
    row_count = len(vix_feature_pdf_in)
    assert shift_int == shift_again_int and shifted_pdf.equals(shifted_again_pdf)
    assert round(exp_config.NULL_SHIFT_SHARE_RANGE[0] * row_count) <= shift_int <= round(exp_config.NULL_SHIFT_SHARE_RANGE[1] * row_count)
    assert shift_int == int(round(np.random.default_rng(exp_config.NULL_SEED + 3).uniform(*exp_config.NULL_SHIFT_SHARE_RANGE) * row_count))
    assert shifted_pdf["date"].equals(vix_feature_pdf_in["date"]) and shifted_pdf["session_idx"].equals(vix_feature_pdf_in["session_idx"])
    for col_str in ["vix_level_prev", "vix_term_prev", "vix_pct250_prev"]:
        assert np.array_equal(shifted_pdf[col_str].to_numpy(), np.roll(vix_feature_pdf_in[col_str].to_numpy(), shift_int), equal_nan=True)
    assert get_shifted_vix_feature_pdf(vix_feature_pdf_in, 4)[1] != shift_int
    passed(f"shift (run 3: k = {shift_int} of {row_count} rows, in the share range, features rolled together, dates in place, deterministic)")

# TEST 6: THE NULL SUMMARY
def test_null_summary():
    summary_dict = get_null_summary_dict(np.array([1.0, 2.0, 3.0, 4.0]), 3.0)
    assert summary_dict["p_value"] == (1 + 2) / 5 and summary_dict["real_rank"] == 2 and summary_dict["runs_at_or_above_real"] == 2
    assert summary_dict["null_median"] == 2.5 and np.isclose(summary_dict["null_p05"], np.percentile([1, 2, 3, 4], 5))
    assert get_null_summary_dict(np.zeros(999), 1.0)["p_value"] == 1 / 1000 and get_null_summary_dict(np.zeros(999), 1.0)["real_rank"] == 1
    passed("null summary (p = (1 + runs >= real) / (runs + 1); rank 1 = highest)")

# TEST 7 AND 8: PARALLEL = SEQUENTIAL; THE RANDOM FAMILIES' CONVENTION
def test_nulls(ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in):
    date1, date2 = get_window_tuple(ohlcv_array_dict_in)
    common_dict = {"ohlcv_array_dict_in": ohlcv_array_dict_in, "daily_pdf_in": daily_pdf_in, "vix_feature_pdf_in": vix_feature_pdf_in, "date1_in": date1, "date2_in": date2}
    # VIX PLACEBO: PARALLEL (2 PROCESSES, 3 CHUNKS) = SEQUENTIAL (1 CHUNK)
    candidate_list = get_rule_candidate_list()
    sequential_pdf = run_parallel_null_pdf(run_vix_placebo_run_list, 3, 1, 1, candidate_dict_list_in=candidate_list, **common_dict)
    parallel_pdf = run_parallel_null_pdf(run_vix_placebo_run_list, 3, 2, 3, candidate_dict_list_in=candidate_list, **common_dict)
    assert sequential_pdf.equals(parallel_pdf) and len(sequential_pdf) == 3
    assert np.allclose(sequential_pdf["max_total"], sequential_pdf[[f"total_{c['candidate_name']}" for c in candidate_list]].max(axis=1))
    # RANDOM FAMILIES: PARALLEL = SEQUENTIAL, AND RUN 0 BY HAND (so.core.replay_walk_forward's SEEDS)
    frozen_rule_tuple = get_frozen_rule_tuple(daily_pdf_in, vix_feature_pdf_in)
    probability_dict = get_path_random_probability_dict(replay_rule_dict(ohlcv_array_dict_in, frozen_rule_tuple, date1, date2))
    for family_str in ["random_exit", "random_reentry"]:
        sequential_pdf = run_parallel_null_pdf(run_random_family_run_list, 3, 1, 1, family_str_in=family_str, probability_dict_in=probability_dict, **common_dict)
        parallel_pdf = run_parallel_null_pdf(run_random_family_run_list, 3, 2, 2, family_str_in=family_str, probability_dict_in=probability_dict, **common_dict)
        assert sequential_pdf.equals(parallel_pdf)
        if family_str == "random_exit":
            random_exit_arr = np.random.default_rng(config.RANDOM_SEED + exp_config.RANDOM_EXIT_SEED_OFFSET).random(len(daily_pdf_in)) < probability_dict["exit_probability"]
            by_hand = replay_rule_dict(ohlcv_array_dict_in, (random_exit_arr, frozen_rule_tuple[1], "rule"), date1, date2)["metric_dict"]["total_return"]
        else:
            by_hand = replay_rule_dict(ohlcv_array_dict_in, (frozen_rule_tuple[0], get_random_reentry_func(probability_dict["reentry_probability"], config.RANDOM_SEED), "random"),
                                       date1, date2)["metric_dict"]["total_return"]
        assert sequential_pdf["total_return"].iloc[0] == by_hand
    passed("nulls (VIX placebo and both random families: parallel = sequential; max over the six; run 0 = so.core.replay_walk_forward's seeds)")

# TEST 9: REPORTS AND VERDICT
def test_reports(ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in):
    date1, date2 = get_window_tuple(ohlcv_array_dict_in)
    simulation_dict = replay_rule_dict(ohlcv_array_dict_in, get_frozen_rule_tuple(daily_pdf_in, vix_feature_pdf_in), date1, date2)
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, date1, date2)
    # THE STRESS SCORECARD
    scorecard_pdf = get_stress_scorecard_pdf(simulation_dict, ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in)
    assert len(scorecard_pdf) == len(simulation_dict["episode_pdf"]) > 0
    finite_pdf = scorecard_pdf.dropna(subset=["vix_at_exit", "vix_at_reentry"])
    assert (finite_pdf["vix_max_out"] >= finite_pdf[["vix_at_exit", "vix_at_reentry"]].max(axis=1) - 1e-12).all()
    m1_pdf = scorecard_pdf[scorecard_pdf["reentry_trigger"] == "M1"]
    assert len(m1_pdf) > 0 and (m1_pdf["drawdown_to_low_pct"] <= 0).all() and scorecard_pdf.loc[scorecard_pdf["reentry_trigger"] != "M1", "drawdown_to_low_pct"].isna().all()
    position_dict = {date: idx for idx, date in enumerate(daily_pdf_in["date"].tolist())}
    first_m1_pos = int(np.flatnonzero((scorecard_pdf["reentry_trigger"] == "M1").to_numpy())[0])
    first_row = scorecard_pdf.iloc[first_m1_pos]
    next_idx = position_dict[scorecard_pdf["exit_date"].iloc[first_m1_pos + 1]] if first_m1_pos + 1 < len(scorecard_pdf) else len(daily_pdf_in) - 1
    assert first_row["lowest_close_to_next_exit"] == daily_pdf_in["session_close"].iloc[position_dict[first_row["reentry_date"]]:next_idx + 1].min()
    # THE SUB-SPANS SUM TO THE TOTAL LOG EXCESS
    session_date_list = ohlcv_array_dict_in["session_date_list"]
    split_date = session_date_list[(FIRST_REPLAY_SESSION_IDX + len(session_date_list)) // 2]
    span_pdf = get_span_log_excess_pdf(simulation_dict["daily_equity_pdf"], buy_hold_dict["daily_equity_pdf"],
                                       [(str(date1), str(split_date)), (str(session_date_list[session_date_list.index(split_date) + 1]), str(date2))])
    total_log_excess = np.log(simulation_dict["daily_equity_pdf"]["equity"].iloc[-1] / buy_hold_dict["daily_equity_pdf"]["equity"].iloc[-1])
    assert np.isclose(span_pdf["log_excess"].sum(), total_log_excess, atol=1e-9) and span_pdf["session_count"].sum() == len(simulation_dict["daily_equity_pdf"])
    # THE SPLIT BY RE-ENTRY REASON MULTIPLIES TO THE PRODUCT OF S / R
    split_pdf = get_reason_split_pdf(get_vix_scorecard_pdf(get_episode_scorecard_pdf(simulation_dict, ohlcv_array_dict_in), simulation_dict, vix_feature_pdf_in))
    metric_dict = get_path_metric_dict(simulation_dict, buy_hold_dict, get_year_period_pdf(session_date_list, date1, date2), ohlcv_array_dict_in)
    assert np.isclose(split_pdf["product_s_over_r"].prod(), metric_dict["product_s_over_r"]) and split_pdf["episode_count"].sum() == metric_dict["episode_count"]
    assert metric_dict["beats_buy_hold"] == (metric_dict["total_return"] > metric_dict["buy_hold_total_return"]) and metric_dict["log_excess_ci_low_1m"] <= metric_dict["log_excess_ci_high_1m"]
    # THE STRESS START: THE FIRST SESSION WITH BOTH VALUES
    start_date = get_stress_start_date(daily_pdf_in, vix_feature_pdf_in, str(session_date_list[0]))
    start_idx = position_dict[start_date]
    assert np.isfinite(daily_pdf_in["ma200_dist_pct"].iloc[start_idx]) and np.isfinite(vix_feature_pdf_in["vix_level_prev"].iloc[start_idx])
    assert not any(np.isfinite(daily_pdf_in["ma200_dist_pct"].iloc[i]) and np.isfinite(vix_feature_pdf_in["vix_level_prev"].iloc[i]) for i in range(start_idx))
    # THE VERDICT RULE BY HAND
    passing_dict = get_verdict_dict(1.0, 1.0, 24, 18, 0.05, 1.01, 2.4, 2.4, 2.35)
    assert passing_dict["verdict_str"] == "ROBUST CANDIDATE PENDING REVIEW" and passing_dict["failed_list"] == []
    for argument_idx, failing_value in [(0, 0.99), (2, 23), (3, 17), (4, 0.051), (5, 1.0), (6, 2.35), (7, 2.3)]:
        argument_list = [1.0, 1.0, 24, 18, 0.05, 1.01, 2.4, 2.4, 2.35]
        argument_list[argument_idx] = failing_value
        failing_dict = get_verdict_dict(*argument_list)
        assert failing_dict["verdict_str"] == "E1M1 IS NOT ROBUST" and len(failing_dict["failed_list"]) == 1
    passed(f"reports (stress scorecard with {len(m1_pdf)} M1 re-entries; halves sum to the total; reason split = product of S/R; stress start; verdict R1-R5 by hand)")

"""
Runner
"""

# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    # GENERATE THE SYNTHETIC DATA (ABOUT 3.5 YEARS) AND AN ALIGNED SYNTHETIC VIX TABLE
    print("Generating synthetic data...")
    synthetic_ohlcv_pdf = get_synthetic_ohlcv_pdf("2021-01-04", "2024-06-28", minute_vol_in=0.0006, seed_in=31)
    synthetic_ohlcv_array_dict = get_ohlcv_array_dict(synthetic_ohlcv_pdf)
    synthetic_daily_pdf = add_ma_dist_col_pdf(get_daily_feature_pdf(synthetic_ohlcv_array_dict))
    synthetic_vix_feature_pdf = get_synthetic_vix_feature_pdf(synthetic_daily_pdf)
    # RUN THE TESTS
    test_config()
    test_ma_dist(synthetic_daily_pdf)
    test_variants(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_feature_pdf)
    test_delay(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_feature_pdf)
    test_shift(synthetic_vix_feature_pdf)
    test_null_summary()
    test_nulls(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_feature_pdf)
    test_reports(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_feature_pdf)
    print("\nAll exp13 tests passed ✅")
