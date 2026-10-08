"""
Workspace Tests: continuous replay, episode scorecard, log-excess bootstrap and fractional exposure (roadmap Step 0)

Run from the workspace root:   python tests/test_continuous_replay.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic data):
    1. The untouched-data guard refuses a window ending on or after the untouched start.
    2. Replay periods tile the replay span (consecutive, non-overlapping, every session once).
    3. A continuous replay with no exit equals buy-and-hold over the whole span (daily equity).
    4. The state carries across a period boundary (one episode from one period into the next), and the period returns
       chain exactly to the total return.
    5. Episode scorecard: S / R equals the share ratio (up to whole shares and fees), log share gain = log(S / R),
       declines are <= 0, costs > 0.
    6. Rule switching: all sessions on one candidate = that candidate alone; exits only on sessions of an exiting
       candidate; the prior-only mapping gives period f's selection to period f + 1.
    7. Log-excess bootstrap: hand calculation, zero excess gives a zero interval, the interval contains the estimate.
    8. Fractional exposure: w = 1 equals buy-and-hold, w = 0 equals cash, rebalances only outside the dead band.
    9. Replay summary of a no-exit path: zero excess, fully invested.
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
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.core.schedule import get_walk_forward_fold_pdf
from so.core.evaluation import get_chained_daily_return_pdf
from so.core.reentry_simulation import get_buy_and_hold_result_dict, get_fixed_delay_reentry_func, simulate_stop_reentry_dict
from so.core.continuous_replay import check_replay_window_bool, get_replay_period_pdf, simulate_continuous_replay_dict, get_session_assignment_arr, \
                                      get_prior_only_period_candidate_dict, get_switching_rule_dict, get_period_return_pdf, get_episode_scorecard_pdf, \
                                      get_log_excess_bootstrap_dict, get_replay_summary_dict
from so.core.fractional_exposure import simulate_fractional_exposure_dict
from synthetic_data import get_synthetic_ohlcv_pdf

# DEFINE THE UNTOUCHED START USED BY THE TESTS (AFTER THE SYNTHETIC DATA)
TEST_UNTOUCHED_START_STR = "2030-01-01"

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: GET THE REPLAY SPAN OF THE SYNTHETIC DATA
def get_span_tuple(ohlcv_array_dict_in):
    # BUILD A SHORT SCHEDULE (1-YEAR WINDOW) AND ITS PERIODS
    fold_pdf = get_walk_forward_fold_pdf(ohlcv_array_dict_in["session_date_list"], 20, [1], max_fold_count_in=6)
    period_pdf = get_replay_period_pdf(fold_pdf, ohlcv_array_dict_in["session_date_list"])
    # RETURN THE SCHEDULE, THE PERIODS AND THE SPAN
    return fold_pdf, period_pdf, period_pdf["period_start"].iloc[0], period_pdf["period_end"].iloc[-1]

# FUNCTION: TEST THE GUARD
def test_guard():
    # A WINDOW BEFORE THE UNTOUCHED START IS ALLOWED
    assert check_replay_window_bool("2026-04-15", "2026-05-14")
    # A WINDOW ENDING ON OR AFTER IT IS REFUSED
    for date_str in ["2026-05-14", "2026-08-13"]:
        try:
            check_replay_window_bool(date_str, "2026-05-14")
            raise AssertionError("guard did not refuse the window")
        except ValueError:
            pass
    passed("untouched-data guard (2026-04-15 allowed; 2026-05-14 and 2026-08-13 refused)")

# FUNCTION: TEST THE REPLAY PERIODS
def test_periods(ohlcv_array_dict_in):
    # BUILD THE PERIODS
    fold_pdf, period_pdf, span_start, span_end = get_span_tuple(ohlcv_array_dict_in)
    session_date_arr = np.array(ohlcv_array_dict_in["session_date_list"])
    span_date_arr = session_date_arr[(session_date_arr >= span_start) & (session_date_arr <= span_end)]
    # EVERY SESSION OF THE SPAN IS IN EXACTLY ONE PERIOD
    assert period_pdf["session_count"].sum() == len(span_date_arr) and len(period_pdf) == len(fold_pdf)
    # CONSECUTIVE: EACH PERIOD STARTS ON THE SESSION AFTER THE PREVIOUS PERIOD'S END
    for row_idx in range(1, len(period_pdf)):
        previous_end_pos = int(np.flatnonzero(session_date_arr == period_pdf["period_end"].iloc[row_idx - 1])[0])
        assert session_date_arr[previous_end_pos + 1] == period_pdf["period_start"].iloc[row_idx]
    # THE LAST PERIOD ENDS AT THE LAST VALIDATION END (OR THE SESSION BEFORE IT)
    assert span_end <= pd.to_datetime(fold_pdf["valid_end"].iloc[-1]).date()
    passed(f"replay periods tile the span ({len(period_pdf)} periods, {len(span_date_arr)} sessions, consecutive, no overlap)")

# FUNCTION: TEST THAT A REPLAY WITHOUT EXITS EQUALS BUY AND HOLD
def test_no_exit_equals_buy_hold(ohlcv_array_dict_in, daily_pdf_in):
    # SIMULATE A REPLAY THAT NEVER EXITS AND BUY AND HOLD
    _, period_pdf, span_start, span_end = get_span_tuple(ohlcv_array_dict_in)
    replay_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=np.full(len(daily_pdf_in), np.nan),
                                                  exit_signal_arr_in=np.zeros(len(daily_pdf_in), dtype=bool), max_cash_sessions_in=None)
    buy_hold_dict = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end)
    # ASSERT THE DAILY EQUITY IS IDENTICAL
    assert len(replay_dict["daily_equity_pdf"]) == len(buy_hold_dict["daily_equity_pdf"])
    assert np.allclose(replay_dict["daily_equity_pdf"]["equity"], buy_hold_dict["daily_equity_pdf"]["equity"], atol=1e-6)
    # THE GUARD APPLIES TO THE REPLAY
    try:
        simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, str(span_end), volatility_arr_in=np.full(len(daily_pdf_in), np.nan))
        raise AssertionError("replay did not apply the guard")
    except ValueError:
        pass
    passed(f"continuous replay with no exit == buy-and-hold over {len(buy_hold_dict['daily_equity_pdf'])} sessions (guard applied)")

# FUNCTION: TEST THAT THE STATE CARRIES ACROSS A PERIOD BOUNDARY
def test_state_carries(ohlcv_array_dict_in, daily_pdf_in):
    # DEFINE AN EXIT 5 SESSIONS BEFORE THE END OF THE SECOND PERIOD AND A RE-ENTRY AT THE 15TH CASH DECISION
    _, period_pdf, span_start, span_end = get_span_tuple(ohlcv_array_dict_in)
    date_session_dict = ohlcv_array_dict_in["date_session_idx_dict"]
    exit_session_idx = date_session_dict[period_pdf["period_end"].iloc[1]] - 5
    exit_signal_arr = np.zeros(len(daily_pdf_in), dtype=bool)
    exit_signal_arr[exit_session_idx] = True
    replay_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=np.full(len(daily_pdf_in), np.nan),
                                                  reentry_func_in=get_fixed_delay_reentry_func(15), reentry_reason_str_in="delay", exit_signal_arr_in=exit_signal_arr)
    # ONE EPISODE, FROM THE SECOND PERIOD INTO THE THIRD
    episode_pdf = replay_dict["episode_pdf"]
    assert len(episode_pdf) == 1 and episode_pdf["cash_session_count"].iloc[0] == 15 and episode_pdf["reentry_reason"].iloc[0] == "delay"
    assert period_pdf["period_start"].iloc[1] <= episode_pdf["exit_ts"].iloc[0].date() <= period_pdf["period_end"].iloc[1]
    assert period_pdf["period_start"].iloc[2] <= episode_pdf["reentry_ts"].iloc[0].date() <= period_pdf["period_end"].iloc[2]
    # THE PERIOD RETURNS CHAIN TO THE TOTAL RETURN, AND BOTH PERIODS SHOW TIME IN CASH
    period_return_pdf = get_period_return_pdf(replay_dict["daily_equity_pdf"], period_pdf)
    assert np.isclose(np.prod(1 + period_return_pdf["total_return"]) - 1, replay_dict["metric_dict"]["total_return"], atol=1e-9)
    assert period_return_pdf["in_market_pct"].iloc[1] < 1 and period_return_pdf["in_market_pct"].iloc[2] < 1 and period_return_pdf["in_market_pct"].iloc[0] == 1
    passed("state carries across a period boundary (one 15-decision episode from period 2 into period 3; period returns chain to the total)")

# FUNCTION: TEST THE EPISODE SCORECARD
def test_scorecard(ohlcv_array_dict_in, daily_pdf_in):
    # SIMULATE RANDOM EXITS WITH A 3-DECISION BUY-BACK
    _, _, span_start, span_end = get_span_tuple(ohlcv_array_dict_in)
    exit_signal_arr = np.random.default_rng(3).random(len(daily_pdf_in)) < 0.03
    replay_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=np.full(len(daily_pdf_in), np.nan),
                                                  reentry_func_in=get_fixed_delay_reentry_func(3), reentry_reason_str_in="delay", exit_signal_arr_in=exit_signal_arr)
    scorecard_pdf = get_episode_scorecard_pdf(replay_dict, ohlcv_array_dict_in)
    closed_pdf = scorecard_pdf[~scorecard_pdf["open_at_end"]]
    assert len(closed_pdf) >= 5 and len(scorecard_pdf) == len(replay_dict["episode_pdf"])
    # S / R EQUALS THE SHARE RATIO UP TO WHOLE SHARES, FEES AND THE CASH LEFT OVER (AT MOST A FEW SHARES)
    share_gap_arr = (closed_pdf["shares_after"] - closed_pdf["shares_before"] * closed_pdf["s_over_r"]).abs()
    assert (share_gap_arr <= 3).all(), share_gap_arr.max()
    # LOG SHARE GAIN, DECLINES AND COSTS
    assert np.allclose(scorecard_pdf["log_share_gain"], np.log(scorecard_pdf["s_over_r"]))
    assert (scorecard_pdf["max_decline_out_pct"] <= 0).all() and (closed_pdf["cost_paid"] > 0).all() and (closed_pdf["sessions_out"] == 3).all()
    # A ROUND TRIP WITH NO PRICE CHANGE LOSES EXACTLY THE COSTS: S / R x (1 + BUY-AND-HOLD CHANGE) < 1 BY THE SLIPPAGE ONLY
    slippage_factor_arr = closed_pdf["s_over_r"] * (1 + closed_pdf["buy_hold_return_out"])
    assert (slippage_factor_arr < 1).all() and (slippage_factor_arr > 0.999).all()
    passed(f"episode scorecard ({len(scorecard_pdf)} episodes; S/R == share ratio within {share_gap_arr.max():.1f} shares; costs and declines consistent)")

# FUNCTION: TEST THE RULE SWITCHING AND THE PRIOR-ONLY MAPPING
def test_switching(ohlcv_array_dict_in, daily_pdf_in):
    # DEFINE TWO CANDIDATES: NEVER EXIT (0) AND EXIT ON RANDOM DAYS WITH A 2-DECISION BUY-BACK (1)
    _, period_pdf, span_start, span_end = get_span_tuple(ohlcv_array_dict_in)
    session_count = len(daily_pdf_in)
    exit_arr_list = [np.zeros(session_count, dtype=bool), np.random.default_rng(5).random(session_count) < 0.05]
    reentry_list = [get_fixed_delay_reentry_func(1), get_fixed_delay_reentry_func(2)]
    simulation_kwargs = {"volatility_arr_in": np.full(session_count, np.nan), "reentry_reason_str_in": "rule"}
    # ALL SESSIONS ON CANDIDATE 1 == CANDIDATE 1 ALONE
    all_one_dict = get_switching_rule_dict(np.ones(session_count, dtype=int), exit_arr_list, reentry_list)
    switch_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, exit_signal_arr_in=all_one_dict["exit_signal_arr"],
                                                  reentry_func_in=all_one_dict["reentry_func"], **simulation_kwargs)
    alone_dict = simulate_stop_reentry_dict(ohlcv_array_dict_in, span_start, span_end, exit_signal_arr_in=exit_arr_list[1], reentry_func_in=reentry_list[1], **simulation_kwargs)
    assert np.isclose(switch_dict["metric_dict"]["total_return"], alone_dict["metric_dict"]["total_return"]) and switch_dict["metric_dict"]["signal_exit_count"] > 0
    # PRIOR-ONLY MAPPING: SELECTION AT PERIOD f GOVERNS PERIOD f + 1
    selection_pdf = pd.DataFrame({"fold_id": period_pdf["period_id"], "candidate_idx": [0, 1] * (len(period_pdf) // 2) + [0] * (len(period_pdf) % 2)})
    period_candidate_dict = get_prior_only_period_candidate_dict(selection_pdf, period_pdf, "candidate_idx")
    period_id_list = period_pdf["period_id"].tolist()
    assert period_id_list[0] not in period_candidate_dict and all(period_candidate_dict[period_id_list[i + 1]] == selection_pdf["candidate_idx"].iloc[i] for i in range(len(period_id_list) - 1))
    # MIXED ASSIGNMENT: EVERY EXIT IS DECIDED ON A SESSION OF CANDIDATE 1
    assignment_arr = get_session_assignment_arr(ohlcv_array_dict_in["session_date_list"], period_pdf, period_candidate_dict)
    mixed_dict = get_switching_rule_dict(assignment_arr, exit_arr_list, reentry_list)
    mixed_sim_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, exit_signal_arr_in=mixed_dict["exit_signal_arr"],
                                                     reentry_func_in=mixed_dict["reentry_func"], **simulation_kwargs)
    signal_pdf = mixed_sim_dict["transaction_pdf"][mixed_sim_dict["transaction_pdf"]["exit_reason"] == "SIGNAL"]
    exit_session_arr = ohlcv_array_dict_in["bar_session_idx_arr"][signal_pdf["sell_idx"].to_numpy()]
    assert len(exit_session_arr) > 0 and (assignment_arr[exit_session_arr] == 1).all() and (assignment_arr[assignment_arr >= 0] >= 0).all()
    passed(f"rule switching (single candidate reproduced; {len(exit_session_arr)} exits all on candidate-1 sessions; prior-only mapping f -> f + 1)")

# FUNCTION: TEST THE LOG EXCESS BOOTSTRAP
def test_log_excess_bootstrap():
    # DEFINE TWO DAILY RETURN SERIES OVER 3 YEARS (STRATEGY = BUY AND HOLD + A SMALL DAILY EDGE)
    date_index = pd.bdate_range("2020-01-01", "2022-12-30")
    rng = np.random.default_rng(1)
    buy_hold_arr = rng.normal(0.0004, 0.01, len(date_index))
    strategy_arr = (1 + buy_hold_arr) * np.exp(rng.normal(0.0001, 0.002, len(date_index))) - 1
    strategy_pdf, buy_hold_pdf = pd.DataFrame({"date": date_index.date, "daily_return": strategy_arr}), pd.DataFrame({"date": date_index.date, "daily_return": buy_hold_arr})
    # HAND CALCULATION: 12 x MEAN MONTHLY LOG EXCESS
    month_arr = pd.Series(pd.to_datetime(date_index).to_period("M"))
    hand_value = 12 * pd.Series(np.log1p(strategy_arr) - np.log1p(buy_hold_arr)).groupby(month_arr).sum().mean()
    for block_month_count in [1, 6]:
        bootstrap_dict = get_log_excess_bootstrap_dict(strategy_pdf, buy_hold_pdf, block_month_count, iteration_count_in=500)
        assert np.isclose(bootstrap_dict["annualized_log_excess"], hand_value) and bootstrap_dict["month_count"] == 36
        assert bootstrap_dict["ci_low"] <= bootstrap_dict["annualized_log_excess"] <= bootstrap_dict["ci_high"]
    # ZERO EXCESS GIVES A ZERO INTERVAL
    zero_dict = get_log_excess_bootstrap_dict(buy_hold_pdf, buy_hold_pdf, 6, iteration_count_in=200)
    assert zero_dict["annualized_log_excess"] == 0 and zero_dict["ci_low"] == 0 and zero_dict["ci_high"] == 0 and not zero_dict["supported"]
    passed(f"annualized log-excess bootstrap (hand value {hand_value:.4f}/yr reproduced with 1- and 6-month blocks; zero excess -> [0, 0])")

# FUNCTION: TEST THE FRACTIONAL EXPOSURE SIMULATOR
def test_fractional(ohlcv_array_dict_in, daily_pdf_in):
    # DEFINE THE SPAN AND BUY AND HOLD
    _, _, span_start, span_end = get_span_tuple(ohlcv_array_dict_in)
    session_count = len(daily_pdf_in)
    buy_hold_equity_pdf = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end)["daily_equity_pdf"]
    # w = 1 EQUALS BUY AND HOLD
    full_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, span_start, span_end, np.ones(session_count), 0.2, 1.0)
    assert np.allclose(full_dict["daily_equity_pdf"]["equity"], buy_hold_equity_pdf["equity"], atol=1e-6) and full_dict["metric_dict"]["rebalance_count"] == 0
    # w = 0 EQUALS CASH
    cash_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, span_start, span_end, np.zeros(session_count), 0.2, 0.0)
    assert np.allclose(cash_dict["daily_equity_pdf"]["equity"], config.INITIAL_CAPITAL) and cash_dict["metric_dict"]["trade_count"] == 0
    # A TARGET ALTERNATING BETWEEN 0.3 AND 0.9 EVERY 40 SESSIONS: REBALANCES ONLY OUTSIDE THE DEAD BAND
    target_arr = np.where((np.arange(session_count) // 40) % 2 == 0, 0.3, 0.9)
    switch_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, span_start, span_end, target_arr, 0.2, 0.9)
    rebalance_pdf = switch_dict["trade_pdf"][switch_dict["trade_pdf"]["reason"] == "rebalance"]
    assert len(rebalance_pdf) > 3 and ((rebalance_pdf["target_weight"] - rebalance_pdf["weight_before"]).abs() > 0.2).all()
    assert 0.3 < switch_dict["metric_dict"]["mean_weight"] < 0.9 and switch_dict["metric_dict"]["cost_paid"] > 0
    # THE SAME TARGETS WITH A WIDE DEAD BAND NEVER REBALANCE
    wide_dict = simulate_fractional_exposure_dict(ohlcv_array_dict_in, span_start, span_end, target_arr, 0.7, 0.9)
    assert wide_dict["metric_dict"]["rebalance_count"] == 0
    passed(f"fractional exposure (w = 1 == buy-and-hold, w = 0 == cash, {len(rebalance_pdf)} rebalances all outside the 20-point band, mean weight {switch_dict['metric_dict']['mean_weight']:.2f})")

# FUNCTION: TEST THE REPLAY SUMMARY
def test_summary(ohlcv_array_dict_in, daily_pdf_in):
    # SUMMARIZE A NO-EXIT PATH AGAINST BUY AND HOLD
    _, period_pdf, span_start, span_end = get_span_tuple(ohlcv_array_dict_in)
    replay_dict = simulate_continuous_replay_dict(ohlcv_array_dict_in, span_start, span_end, TEST_UNTOUCHED_START_STR, volatility_arr_in=np.full(len(daily_pdf_in), np.nan))
    buy_hold_equity_pdf = get_buy_and_hold_result_dict(ohlcv_array_dict_in, span_start, span_end)["daily_equity_pdf"]
    summary_dict = get_replay_summary_dict(replay_dict["daily_equity_pdf"], buy_hold_equity_pdf, period_pdf, 6, {"cash": 0.0})
    # ASSERT ZERO EXCESS AND FULL TIME IN THE MARKET
    assert abs(summary_dict["excess_total_return"]) < 1e-9 and summary_dict["in_market_pct"] == 1.0 and not summary_dict["primary_success"]
    assert summary_dict["period_window_count"] == len(period_pdf) and summary_dict["period_windows_beating_buy_hold"] == 0
    assert abs(summary_dict["log_excess_annualized_log_excess"]) < 1e-9 and np.isclose(summary_dict["period_chained_return"], summary_dict["strategy_total_return"])
    passed(f"replay summary (no-exit path: zero excess, in market 100%, {summary_dict['period_window_count']} periods)")

"""
Runner
"""

# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    # GENERATE THE SYNTHETIC DATA (ABOUT 3.5 YEARS)
    print("Generating synthetic data...")
    synthetic_ohlcv_pdf = get_synthetic_ohlcv_pdf("2021-01-04", "2024-06-28", minute_vol_in=0.0006, seed_in=21)
    synthetic_ohlcv_array_dict = get_ohlcv_array_dict(synthetic_ohlcv_pdf)
    synthetic_daily_pdf = get_daily_feature_pdf(synthetic_ohlcv_array_dict)
    # RUN THE TESTS
    test_guard()
    test_periods(synthetic_ohlcv_array_dict)
    test_no_exit_equals_buy_hold(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_state_carries(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_scorecard(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_switching(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_log_excess_bootstrap()
    test_fractional(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    test_summary(synthetic_ohlcv_array_dict, synthetic_daily_pdf)
    print("\nAll continuous replay tests passed ✅")
