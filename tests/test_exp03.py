"""
Workspace Tests: exp03_ath_exit ("sell at strength")

Run from the workspace root:   python tests/test_exp03.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified:
    1. The 15 rule candidates (3 thresholds x 5 buy-backs), unique and ordered.
    2. Rule mechanics on synthetic data: every exit happens on a decision within x of the all-time high; dip buy-backs
       only when the decision close is d below the sale price; delay buy-backs after exactly n cash decisions; forced
       buy-backs after MAX_CASH_SESSIONS; a rule that never fires equals buy-and-hold.
    3. Random baselines: the matched probabilities, and a random exit signal with probability 0 equals buy-and-hold.
    4. Walk-forward: 15 validation candidates per fold, pooled selection with its tie-breaks, and the prior-only runner
       (window "valid") reproduces the validation candidate exactly, with every baseline family present.
    5. Exploration table: one row per (event, horizon); diff = event mean - all-day mean.
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
from experiments.exp03_ath_exit import config as exp_config
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.core.reentry_simulation import get_buy_and_hold_result_dict
from experiments.exp03_ath_exit.rules import get_rule_candidate_list, simulate_rule_dict, get_rule_metric_dict, get_random_exit_signal_arr, \
                                             get_random_baseline_probability_dict, get_event_forward_pdf, get_ath_exit_signal_arr
from experiments.exp03_ath_exit.walk_forward import get_fold_pdf, run_validation_candidate_pdf, get_pooled_selection_pdf, run_window_with_baseline_dict
from synthetic_data import get_synthetic_ohlcv_pdf

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: TEST THE RULE CANDIDATES
def test_candidates():
    # COLLECT THE CANDIDATES
    candidate_list = get_rule_candidate_list()
    # ASSERT 3 x 5 UNIQUE RULES IN A FIXED ORDER
    assert len(candidate_list) == 15 and len({(c["ath_within"], c["rule"]) for c in candidate_list}) == 15
    assert [c["rule_order"] for c in candidate_list] == list(range(15))
    assert {c["rule"] for c in candidate_list} == {"delay_5", "delay_20", "delay_60", "dip_2pct", "dip_5pct"}
    passed("rule candidates (3 thresholds x 5 buy-backs, unique, ordered)")

# FUNCTION: TEST THE RULE MECHANICS
def test_rule_mechanics(ohlcv_array_dict_in, daily_pdf_in):
    # DEFINE A LONG WINDOW AND THE ARRAYS
    date1, date2 = daily_pdf_in["date"].iloc[260], daily_pdf_in["date"].iloc[-1]
    ts_session_dict = {ts: idx for idx, ts in enumerate(daily_pdf_in["decision_ts"])}
    decision_close_arr = daily_pdf_in["decision_close"].to_numpy(dtype=float)
    exit_count_total = 0
    # ITERATE OVER THE RULES OF THE WIDEST THRESHOLD
    for candidate_dict in [c for c in get_rule_candidate_list() if c["ath_within"] == 0.02]:
        # SIMULATE THE RULE
        simulation_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, date1, date2, candidate_dict)
        transaction_pdf, episode_pdf = simulation_dict["transaction_pdf"], simulation_dict["episode_pdf"]
        signal_exit_pdf = transaction_pdf[transaction_pdf["exit_reason"] == "SIGNAL"]
        exit_count_total += len(signal_exit_pdf)
        # EVERY EXIT IS DECIDED ON A SESSION WITHIN THE THRESHOLD OF THE ATH (DECISION BAR = THE BAR BEFORE THE 15:59 FILL)
        for sell_idx in signal_exit_pdf["sell_idx"]:
            session_idx = ts_session_dict[ohlcv_array_dict_in["timestamp_index"][sell_idx - 1]]
            assert daily_pdf_in["ath_drawdown_pct"].iloc[session_idx] >= -candidate_dict["ath_within"]
        # BUY-BACK RULES
        closed_pdf = episode_pdf[episode_pdf["reentry_reason"] != "window_end"]
        if candidate_dict["buyback_type"] == "delay":
            assert (closed_pdf.loc[closed_pdf["reentry_reason"] == "delay", "cash_session_count"] == int(candidate_dict["buyback_value"])).all()
        else:
            for _, episode_row in closed_pdf[closed_pdf["reentry_reason"] == "dip"].iterrows():
                session_idx = ts_session_dict[episode_row["reentry_ts"] - pd.Timedelta(minutes=1)]
                assert decision_close_arr[session_idx] <= episode_row["exit_fill_price"] * (1 - candidate_dict["buyback_value"]) + 1e-9
        assert (closed_pdf.loc[closed_pdf["reentry_reason"] == "forced", "cash_session_count"] == exp_config.MAX_CASH_SESSIONS).all()
    assert exit_count_total > 0
    # A RULE THAT NEVER FIRES EQUALS BUY AND HOLD
    never_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, date1, date2, get_rule_candidate_list()[0], exit_signal_arr_in=np.zeros(len(daily_pdf_in), dtype=bool))
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, date1, date2)
    assert np.isclose(never_dict["metric_dict"]["total_return"], buy_hold_dict["metric_dict"]["total_return"], atol=1e-10)
    # THE METRIC ROW
    metric_dict = get_rule_metric_dict(simulation_dict, buy_hold_dict["metric_dict"]["total_return"])
    assert np.isclose(metric_dict["excess_return"], simulation_dict["metric_dict"]["total_return"] - buy_hold_dict["metric_dict"]["total_return"])
    passed(f"rule mechanics (exits within the ATH threshold, dip / delay / forced buy-backs, never-firing rule == buy-and-hold; {exit_count_total} exits)")

# FUNCTION: TEST THE RANDOM BASELINES
def test_random_baselines(ohlcv_array_dict_in, daily_pdf_in):
    # SIMULATE A RULE AND MATCH THE PROBABILITIES
    date1, date2 = daily_pdf_in["date"].iloc[260], daily_pdf_in["date"].iloc[-1]
    candidate_dict = [c for c in get_rule_candidate_list() if c["ath_within"] == 0.02 and c["rule"] == "delay_5"][0]
    simulation_dict = simulate_rule_dict(ohlcv_array_dict_in, daily_pdf_in, date1, date2, candidate_dict)
    probability_dict = get_random_baseline_probability_dict(simulation_dict)
    # ASSERT THE PROBABILITIES ARE IN (0, 1] AND THE BUY-BACK PROBABILITY MATCHES THE MEAN CASH DECISIONS
    assert 0 < probability_dict["exit_probability"] <= 1 and 0 < probability_dict["buyback_probability"] <= 1
    assert np.isclose(probability_dict["buyback_probability"], 1 / simulation_dict["episode_pdf"]["cash_session_count"].mean())
    # A RANDOM EXIT WITH PROBABILITY 0 NEVER EXITS (= BUY AND HOLD), PROBABILITY 1 EXITS ON EVERY INVESTED DECISION
    assert not get_random_exit_signal_arr(100, 0.0, 1).any() and get_random_exit_signal_arr(100, 1.0, 1).all()
    passed(f"random baselines (exit probability {probability_dict['exit_probability']:.3f}, buy-back probability {probability_dict['buyback_probability']:.3f})")

# FUNCTION: TEST THE WALK-FORWARD
def test_walk_forward(ohlcv_array_dict_in, daily_pdf_in):
    # BUILD A SHORT SCHEDULE (1-YEAR FIXED WINDOW TO FIT THE SYNTHETIC DATA)
    fold_pdf = get_fold_pdf(ohlcv_array_dict_in["session_date_list"], max_fold_count_in=3, train_years_in=1)
    assert len(fold_pdf) == 3
    # RUN THE VALIDATION CANDIDATES
    candidate_pdf = pd.concat([run_validation_candidate_pdf(row, daily_pdf_in, ohlcv_array_dict_in) for _, row in fold_pdf.iterrows()], ignore_index=True)
    assert len(candidate_pdf) == 3 * 15 and np.allclose(candidate_pdf["valid_excess_return"], candidate_pdf["valid_total_return"] - candidate_pdf["valid_buy_hold_total_return"], atol=1e-7)
    # SELECT ONE RULE PER FOLD
    selection_pdf = get_pooled_selection_pdf(candidate_pdf)
    assert len(selection_pdf) == 3 and (selection_pdf["pooled_quarter_count"].tolist() == [1, 2, 3])
    # TIE-BREAK: WHEN EVERY RULE TIES, THE TIGHTEST THRESHOLD AND THE FIRST RULE WIN
    tie_pdf = candidate_pdf.assign(valid_excess_return=0.0)
    tie_row = get_pooled_selection_pdf(tie_pdf).iloc[0]
    assert tie_row["ath_within"] == min(exp_config.ATH_WITHIN_LIST) and tie_row["rule_order"] == 0
    # THE PRIOR-ONLY RUNNER REPRODUCES EVERY CANDIDATE OF THE LAST FOLD
    last_fold_row = fold_pdf.iloc[-1]
    for _, candidate_row in candidate_pdf[candidate_pdf["fold_id"] == last_fold_row["fold_id"]].iterrows():
        valid_dict = run_window_with_baseline_dict(last_fold_row, candidate_row, daily_pdf_in, ohlcv_array_dict_in, "valid", alert_in=False)
        assert np.isclose(valid_dict["metric_dict"]["total_return"], candidate_row["valid_total_return"])
    baseline_name_list = valid_dict["baseline_pdf"]["baseline"].tolist()
    assert {"model", "buy_hold", f"trend_ma{exp_config.TREND_RULE_MA_SESSIONS}"} <= set(baseline_name_list)
    assert sum(name.startswith("random_buyback_") for name in baseline_name_list) == exp_config.RANDOM_RUN_COUNT
    assert sum(name.startswith("random_exit_") for name in baseline_name_list) == exp_config.RANDOM_RUN_COUNT
    passed(f"walk-forward (15 rules x 3 folds, pooled selection and tie-breaks, prior-only runner == candidates, {len(baseline_name_list)} baseline rows)")

# FUNCTION: TEST THE EXPLORATION TABLE
def test_exploration(daily_pdf_in):
    # DEFINE TWO EVENTS
    ath_dist_arr = daily_pdf_in["ath_drawdown_pct"].to_numpy(dtype=float)
    event_dict = {"ATH within 1%": ath_dist_arr >= -0.01, "ATH within 2%": ath_dist_arr >= -0.02}
    # BUILD THE TABLE
    forward_pdf = get_event_forward_pdf(daily_pdf_in, event_dict, str(daily_pdf_in["date"].iloc[-80]), [1, 20], iteration_count_in=200)
    # ASSERT THE SHAPE AND THE DIFFERENCE
    assert len(forward_pdf) == 4 and np.allclose(forward_pdf["diff"], forward_pdf["event_mean_log_return"] - forward_pdf["all_mean_log_return"])
    assert (forward_pdf["diff_ci_low"] <= forward_pdf["diff_ci_high"]).all() and (forward_pdf["episode_count"] >= 1).all()
    assert (get_ath_exit_signal_arr(daily_pdf_in, 0.01) == event_dict["ATH within 1%"]).all()
    passed("exploration table (event vs all-day forward returns, bootstrap interval, episode count)")

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
    test_candidates()
    test_rule_mechanics(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_random_baselines(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_walk_forward(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_exploration(synthetic_daily_pdf)
    print("\nAll exp03 tests passed ✅")
