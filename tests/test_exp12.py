"""
Workspace Tests: exp12_vix_fear_reentry

Run from the workspace root:   python tests/test_exp12.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic SPY bars and a synthetic VIX table aligned with them):
    1. The 6 candidates (E1M1 ... E2M3) in a fixed order with unique tie ranks; the 2 unmodified exits.
    2. The base signals equal exp04's (x = 0, n = 1) and exp07's (k = 4) rules.
    3. M1, M2 and M3 by hand on small arrays, including NaN (M1: a NaN does not enter the maximum and a NaN now is False;
       M2: NaN is neither < 1 nor >= 1; M3: NaN does not suppress).
    4. The shared simulator's fresh-exit option: after a re-entry that sets require_fresh_exit while the exit signal is
       on, the next exit waits until the signal has been off once; without the key (or if the signal is off at the
       re-entry decision), the next "on" exits at once (the original behaviour).
    5. Mechanics of every candidate on a replay: every VIX-triggered re-entry satisfies its condition at its decision
       and no earlier cash decision of the episode satisfied it or the original rule; every original re-entry fires on
       the original signal; after a VIX re-entry the next exit follows an "off" decision; M3 never exits on a suppressed
       decision.
    6. No look-ahead: changing the VIX features after a session changes no trade decided up to that session.
    7. Walk-forward: candidate periods chain to their totals; ties select tie rank 0 (E2M3); period f's choice governs
       f + 1; the unmodified E1 / E2 paths equal exp04's and exp07's rule builders.
    8. Reports: the re-entry reasons, the concentration reports by hand, the yearly log excess sums to the total.
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
from experiments.exp12_vix_fear_reentry import config as exp_config
from so.core.trade_execution import get_ohlcv_array_dict
from so.features.daily_features import get_daily_feature_pdf
from so.features.vix_features import get_trailing_percentile_arr
from so.core.continuous_replay import simulate_continuous_replay_dict, get_episode_scorecard_pdf
from so.core.replay_walk_forward import run_candidate_replay_dict, run_prior_only_replay_dict
from experiments.exp04_trend_exit.rules import get_rule_builder_func as get_exp04_rule_builder_func
from experiments.exp07_warning_lights_exit.rules import get_rule_builder_func as get_exp07_rule_builder_func, get_light_pdf
from experiments.exp12_vix_fear_reentry.rules import get_schedule_tuple, get_rule_candidate_list, get_unmodified_candidate_list, get_base_signal_dict, \
    get_m3_suppress_arr, get_m1_trigger_bool, get_m2_trigger_bool, get_rule_builder_func, get_reentry_trigger_list, get_vix_scorecard_pdf, \
    get_concentration_dict, get_yearly_log_excess_pdf
from synthetic_data import get_synthetic_ohlcv_pdf

# DEFINE THE UNTOUCHED START USED BY THE TESTS (AFTER THE SYNTHETIC DATA)
TEST_UNTOUCHED_START_STR = "2030-01-01"
# DEFINE THE KEYS AND TIE-BREAKS OF THE SELECTION (AS THE NOTEBOOK)
KEY_COL_STR_LIST = ["exit_rule", "modification"]
TIE_BREAK_LIST = [("tie_order", True)]
# DEFINE THE FIRST REPLAYED SESSION (AFTER THE 250-SESSION FEATURES EXIST)
FIRST_REPLAY_SESSION_IDX = 260

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: BUILD A SYNTHETIC VIX TABLE THAT RISES WHEN SPY FALLS
def get_synthetic_vix_feature_pdf(daily_pdf_in, seed_in=5):
    """
    vix_level_prev = 100 x annualized trailing volatility x (1 + 2 x max(0, -20-session return)) + noise, shifted by
    one session (a _prev value); vix_term_prev = level / (0.8 x level + 4); vix_pct250_prev from the shared function;
    a few NaN values are planted.
    """
    # BUILD THE LEVEL
    rng = np.random.default_rng(seed_in)
    volatility_arr = np.nan_to_num(daily_pdf_in["daily_volatility"].to_numpy(dtype=float), nan=0.01)
    drop_arr = np.clip(-np.nan_to_num(daily_pdf_in["return_20d"].to_numpy(dtype=float), nan=0.0), 0, None)
    level_arr = 100 * volatility_arr * np.sqrt(252) * (1 + 6 * drop_arr) + rng.normal(0, 0.5, len(daily_pdf_in))
    level_arr = np.concatenate([[np.nan], np.clip(level_arr, 5, None)[:-1]])
    # PLANT A FEW MISSING VALUES
    level_arr[[300, 301, 450]] = np.nan
    # RETURN THE TABLE
    return pd.DataFrame({"session_idx": daily_pdf_in["session_idx"].to_numpy(), "date": daily_pdf_in["date"].to_numpy(),
                         "vix_level_prev": level_arr, "vix_term_prev": level_arr / (0.8 * level_arr + 4),
                         "vix_pct250_prev": get_trailing_percentile_arr(level_arr, 250)})

# FUNCTION: GET THE SESSION OF EVERY SIGNAL EXIT AND RULE RE-ENTRY OF A SIMULATION
def get_trade_session_tuple(simulation_dict_in, ohlcv_array_dict_in):
    # COLLECT THE TRANSACTIONS AND MAP THE BARS TO THEIR SESSIONS
    transaction_pdf, bar_session_arr = simulation_dict_in["transaction_pdf"], ohlcv_array_dict_in["bar_session_idx_arr"]
    exit_session_arr = bar_session_arr[transaction_pdf.loc[transaction_pdf["exit_reason"] == "SIGNAL", "sell_idx"].to_numpy(dtype=int)]
    entry_session_arr = bar_session_arr[transaction_pdf.loc[transaction_pdf["entry_reason"] == "rule", "buy_idx"].to_numpy(dtype=int)]
    return exit_session_arr, entry_session_arr

# FUNCTION: REPLAY ONE RULE FROM THE FIRST REPLAY SESSION TO THE END
def replay(ohlcv_array_dict_in, exit_arr_in, reentry_func_in):
    session_date_list = ohlcv_array_dict_in["session_date_list"]
    return simulate_continuous_replay_dict(ohlcv_array_dict_in, session_date_list[FIRST_REPLAY_SESSION_IDX], session_date_list[-1], TEST_UNTOUCHED_START_STR,
                                           volatility_arr_in=np.full(len(session_date_list), np.nan), reentry_func_in=reentry_func_in,
                                           reentry_reason_str_in="rule", exit_signal_arr_in=exit_arr_in, max_cash_sessions_in=None)

# FUNCTION: TEST THE CANDIDATES
def test_candidates():
    # 6 CANDIDATES IN ORDER, UNIQUE TIE RANKS, E2M3 FIRST ON TIES
    candidate_list = get_rule_candidate_list()
    assert [c["candidate_name"] for c in candidate_list] == ["E1M1", "E1M2", "E1M3", "E2M1", "E2M2", "E2M3"]
    assert sorted(c["tie_order"] for c in candidate_list) == list(range(6))
    assert min(candidate_list, key=lambda c: c["tie_order"])["candidate_name"] == "E2M3"
    # THE UNMODIFIED EXITS (E2 FIRST ON TIES)
    unmodified_list = get_unmodified_candidate_list()
    assert [c["candidate_name"] for c in unmodified_list] == ["E1none", "E2none"] and min(unmodified_list, key=lambda c: c["tie_order"])["exit_rule"] == "E2"
    passed("candidates (E1M1 ... E2M3, tie ranks 0-5 with E2M3 first; unmodified E1, E2)")

# FUNCTION: TEST THE BASE SIGNALS
def test_base_signals(daily_pdf_in):
    # E1 = BELOW / ABOVE THE 200-SESSION AVERAGE (NaN NEVER SIGNALS); E2 = AT LEAST 4 / FEWER THAN 3 LIGHTS
    signal_dict = get_base_signal_dict(daily_pdf_in)
    ma_arr = daily_pdf_in["ma200_dist_pct"].to_numpy(dtype=float)
    with np.errstate(invalid="ignore"):
        assert (signal_dict["E1"]["exit_arr"] == (ma_arr < 0)).all() and (signal_dict["E1"]["reentry_arr"] == (ma_arr > 0)).all()
    light_count_arr = get_light_pdf(daily_pdf_in)["light_count"].to_numpy()
    assert (signal_dict["E2"]["exit_arr"] == (light_count_arr >= 4)).all() and (signal_dict["E2"]["reentry_arr"] == (light_count_arr < 3)).all()
    passed(f"base signals (E1 = exp04 x = 0, n = 1; E2 = exp07 k = 4; {int(signal_dict['E1']['exit_arr'].sum())} / {int(signal_dict['E2']['exit_arr'].sum())} exit decisions)")

# FUNCTION: TEST M1, M2 AND M3 BY HAND
def test_modifications_by_hand():
    # M1: MAX OVER EXIT .. NOW = 30; 0.85 x 30 = 25.5
    level_arr = np.array([20.0, 30.0, np.nan, 26.0, 25.5, np.nan, 25.0])
    assert not get_m1_trigger_bool(level_arr, 0, 0)                       # 20 <= 0.85 x 20 is False
    assert not get_m1_trigger_bool(level_arr, 0, 2)                       # NaN now is False
    assert not get_m1_trigger_bool(level_arr, 0, 3)                       # 26 > 25.5
    assert get_m1_trigger_bool(level_arr, 0, 4)                           # 25.5 <= 25.5
    assert not get_m1_trigger_bool(level_arr, 0, 5)                       # NaN now
    assert not get_m1_trigger_bool(level_arr, 2, 3)                       # max over [NaN, 26] = 26: 26 > 22.1
    assert not get_m1_trigger_bool(np.array([np.nan, np.nan]), 0, 1)      # no maximum
    # M1: THE EXIT DECISION ITSELF ENTERS THE MAXIMUM
    assert get_m1_trigger_bool(np.array([40.0, 33.0]), 0, 1) and not get_m1_trigger_bool(np.array([40.0, 33.0]), 1, 1)
    # M2: < 1 NOW AND >= 1 AT LEAST ONCE FROM THE EXIT DECISION ON
    term_arr = np.array([0.95, 1.02, np.nan, 0.99, 1.00, 0.98])
    assert not get_m2_trigger_bool(term_arr, 0, 0)                        # never >= 1
    assert not get_m2_trigger_bool(term_arr, 0, 2)                        # NaN now
    assert get_m2_trigger_bool(term_arr, 0, 3)                            # 1.02 seen, 0.99 now
    assert not get_m2_trigger_bool(term_arr, 2, 3)                        # only NaN and 0.99 since the exit decision
    assert not get_m2_trigger_bool(term_arr, 0, 4)                        # 1.00 is not < 1
    assert get_m2_trigger_bool(term_arr, 2, 5)                            # 1.00 seen at 4, 0.98 now
    assert get_m2_trigger_bool(np.array([1.10, 0.90]), 0, 1)              # inverted at the exit decision itself
    # M3: SUPPRESSED WHEN TERM >= 1 OR PCT250 >= 0.9; NaN DOES NOT SUPPRESS
    feature_pdf = pd.DataFrame({"vix_term_prev": [1.0, 0.99, np.nan, 0.5, np.nan], "vix_pct250_prev": [0.1, 0.9, 0.95, 0.89, np.nan]})
    assert get_m3_suppress_arr(feature_pdf).tolist() == [True, True, True, False, False]
    passed("modifications by hand (M1 fade 0.85 with NaN rules; M2 inverted then < 1; M3 term >= 1 or pct250 >= 0.9, NaN not suppressed)")

# FUNCTION: TEST THE FRESH-EXIT OPTION OF THE SHARED SIMULATOR
def test_fresh_exit(ohlcv_array_dict_in):
    # EXIT SIGNAL ON AT 300-310, OFF AT 311-314, ON AGAIN FROM 315 TO 317
    session_count = len(ohlcv_array_dict_in["session_date_list"])
    exit_arr = np.zeros(session_count, dtype=bool)
    exit_arr[300:311] = True
    exit_arr[315:318] = True
    # FUNCTION: A RULE THAT BUYS BACK AT A GIVEN SESSION, WITH OR WITHOUT THE FRESH-EXIT KEY
    def get_rule(reentry_session_idx, fresh_bool):
        def reentry_func(session_idx, cash_session_count, episode_dict):
            if session_idx >= reentry_session_idx:
                if fresh_bool:
                    episode_dict["require_fresh_exit"] = True
                return True
            return False
        return reentry_func
    # WITHOUT THE KEY: SELL AT 300, BUY AT 303, SELL AGAIN AT 304 (ORIGINAL BEHAVIOUR)
    exit_session_arr, entry_session_arr = get_trade_session_tuple(replay(ohlcv_array_dict_in, exit_arr, get_rule(303, False)), ohlcv_array_dict_in)
    assert exit_session_arr[:2].tolist() == [300, 304] and entry_session_arr[0] == 303
    # WITH THE KEY: SELL AT 300, BUY AT 303, NO EXIT AT 304-310, THE SIGNAL IS OFF AT 311, THE FRESH SIGNAL AT 315 SELLS
    exit_session_arr, entry_session_arr = get_trade_session_tuple(replay(ohlcv_array_dict_in, exit_arr, get_rule(303, True)), ohlcv_array_dict_in)
    assert exit_session_arr[:2].tolist() == [300, 315] and entry_session_arr[0] == 303
    # WITH THE KEY BUT THE SIGNAL OFF AT THE RE-ENTRY DECISION (312): THE NEXT "ON" (315) SELLS AT ONCE
    exit_session_arr, entry_session_arr = get_trade_session_tuple(replay(ohlcv_array_dict_in, exit_arr, get_rule(312, True)), ohlcv_array_dict_in)
    assert exit_session_arr[:2].tolist() == [300, 315] and entry_session_arr[0] == 312
    # WITH THE KEY, RE-ENTRY AT 316 (SIGNAL ON): THE SIGNAL STAYS ON TO 317 AND NEVER COMES BACK -> NO SECOND EXIT
    exit_session_arr, entry_session_arr = get_trade_session_tuple(replay(ohlcv_array_dict_in, exit_arr, get_rule(316, True)), ohlcv_array_dict_in)
    assert exit_session_arr.tolist() == [300] and entry_session_arr[0] == 316
    passed("fresh exit (shared simulator: without the key 300 / 303 / 304; with it 300 / 303 / 315; off at re-entry -> next on sells)")

# FUNCTION: TEST THE MECHANICS OF EVERY CANDIDATE
def test_mechanics(ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in):
    # COLLECT THE SIGNALS AND THE FEATURES
    rule_builder_func = get_rule_builder_func(daily_pdf_in, vix_feature_pdf_in)
    signal_dict = get_base_signal_dict(daily_pdf_in)
    level_arr, term_arr = vix_feature_pdf_in["vix_level_prev"].to_numpy(dtype=float), vix_feature_pdf_in["vix_term_prev"].to_numpy(dtype=float)
    suppress_arr = get_m3_suppress_arr(vix_feature_pdf_in)
    count_dict = {}
    # ITERATE OVER THE CANDIDATES
    for candidate_dict in get_rule_candidate_list():
        exit_str, modification_str = candidate_dict["exit_rule"], candidate_dict["modification"]
        exit_arr, reentry_func, _ = rule_builder_func(candidate_dict)
        simulation_dict = replay(ohlcv_array_dict_in, exit_arr, reentry_func)
        exit_session_arr, entry_session_arr = get_trade_session_tuple(simulation_dict, ohlcv_array_dict_in)
        trigger_list = get_reentry_trigger_list(simulation_dict)
        original_arr, base_exit_arr = signal_dict[exit_str]["reentry_arr"], signal_dict[exit_str]["exit_arr"]
        # EVERY EXIT ON A (NOT SUPPRESSED) EXIT SIGNAL
        assert base_exit_arr[exit_session_arr].all()
        if modification_str == "M3":
            assert not suppress_arr[exit_session_arr].any()
        # EVERY CLOSED EPISODE: THE REASON MATCHES THE CONDITIONS AND NO EARLIER CASH DECISION MET ANY OF THEM
        for episode_pos, (exit_session, entry_session) in enumerate(zip(exit_session_arr, entry_session_arr)):
            trigger_str = trigger_list[episode_pos]
            def vix_bool(session_idx):
                return (modification_str == "M1" and get_m1_trigger_bool(level_arr, exit_session, session_idx)) or \
                       (modification_str == "M2" and get_m2_trigger_bool(term_arr, exit_session, session_idx))
            if trigger_str == "original rule":
                assert original_arr[entry_session]
            else:
                assert trigger_str == modification_str and vix_bool(entry_session) and not original_arr[entry_session]
            assert not any(original_arr[s] or vix_bool(s) for s in range(exit_session + 1, entry_session))
            # AFTER A VIX RE-ENTRY, THE NEXT EXIT FOLLOWS AN "OFF" DECISION OF THE EXIT SIGNAL
            if trigger_str in ["M1", "M2"] and episode_pos + 1 < len(exit_session_arr):
                next_exit = int(exit_session_arr[episode_pos + 1])
                if base_exit_arr[entry_session]:
                    assert not base_exit_arr[entry_session + 1:next_exit].all()
            count_dict[trigger_str] = count_dict.get(trigger_str, 0) + 1
    # THE SYNTHETIC DATA EXERCISES BOTH VIX TRIGGERS AND THE ORIGINAL RULE
    assert count_dict.get("M1", 0) > 0 and count_dict.get("M2", 0) > 0 and count_dict.get("original rule", 0) > 0, count_dict
    passed(f"mechanics (6 candidates; re-entry reasons {count_dict})")

# FUNCTION: TEST THAT LATER VIX VALUES CHANGE NO EARLIER DECISION
def test_no_look_ahead(ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in):
    # CHANGE EVERY VIX FEATURE AFTER SESSION 600
    cut_session_idx = 600
    changed_pdf = vix_feature_pdf_in.copy()
    for col_str in ["vix_level_prev", "vix_term_prev", "vix_pct250_prev"]:
        changed_pdf.loc[cut_session_idx + 1:, col_str] = changed_pdf.loc[cut_session_idx + 1:, col_str].to_numpy()[::-1] * 1.7
    # ITERATE OVER THE CANDIDATES: THE TRADES DECIDED UP TO SESSION 600 ARE IDENTICAL
    for candidate_dict in get_rule_candidate_list():
        trade_list = []
        for feature_pdf in [vix_feature_pdf_in, changed_pdf]:
            exit_arr, reentry_func, _ = get_rule_builder_func(daily_pdf_in, feature_pdf)(candidate_dict)
            exit_session_arr, entry_session_arr = get_trade_session_tuple(replay(ohlcv_array_dict_in, exit_arr, reentry_func), ohlcv_array_dict_in)
            trade_list.append((exit_session_arr[exit_session_arr <= cut_session_idx].tolist(), entry_session_arr[entry_session_arr <= cut_session_idx].tolist()))
        assert trade_list[0] == trade_list[1], candidate_dict
    passed("no look-ahead (VIX features changed after session 600: every trade decided up to 600 unchanged, 6 candidates)")

# FUNCTION: TEST THE WALK-FORWARD AND THE UNMODIFIED BASELINE
def test_walk_forward(ohlcv_array_dict_in, daily_pdf_in, vix_feature_pdf_in):
    # REPLAY THE 6 CANDIDATES
    _, period_pdf = get_schedule_tuple(ohlcv_array_dict_in["session_date_list"], train_years_in=1, max_fold_count_in=6)
    candidate_list = get_rule_candidate_list()
    rule_builder_func = get_rule_builder_func(daily_pdf_in, vix_feature_pdf_in)
    replay_dict = run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_list, rule_builder_func, TEST_UNTOUCHED_START_STR, None, 2, alert_in=False)
    candidate_period_pdf, candidate_summary_pdf = replay_dict["candidate_period_pdf"], replay_dict["candidate_summary_pdf"]
    # ONE ROW PER (CANDIDATE, PERIOD); PERIODS CHAIN TO THE TOTAL
    assert len(candidate_period_pdf) == 6 * len(period_pdf)
    chained_arr = candidate_period_pdf.groupby("candidate_idx")["valid_total_return"].apply(lambda s: np.prod(1 + s) - 1).to_numpy()
    assert np.allclose(chained_arr, candidate_summary_pdf.sort_values("candidate_idx")["strategy_total_return"].to_numpy(), atol=1e-9)
    # TIES: EVERY SCORE EQUAL -> TIE RANK 0 (E2M3)
    tie_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf.assign(valid_excess_return=0.0), candidate_list, rule_builder_func,
                                          KEY_COL_STR_LIST, TIE_BREAK_LIST, 4, TEST_UNTOUCHED_START_STR, None, 2, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    assert (tie_dict["selection_pdf"]["candidate_name"] == "E2M3").all()
    # PRIOR-ONLY PATH: PERIOD f's CHOICE GOVERNS f + 1; BOTH RANDOM FAMILIES
    prior_dict = run_prior_only_replay_dict(ohlcv_array_dict_in, period_pdf, candidate_period_pdf, candidate_list, rule_builder_func, KEY_COL_STR_LIST, TIE_BREAK_LIST, 4,
                                            TEST_UNTOUCHED_START_STR, None, exp_config.RANDOM_RUN_COUNT, exp_config.RANDOM_EXIT_SEED_OFFSET, 2)
    selection_pdf, period_candidate_dict = prior_dict["selection_pdf"], prior_dict["period_candidate_dict"]
    period_id_list = period_pdf["period_id"].tolist()
    assert all(period_candidate_dict[period_id_list[i + 1]] == int(selection_pdf.loc[selection_pdf["fold_id"] == period_id_list[i], "candidate_idx"].iloc[0]) for i in range(len(period_id_list) - 1))
    baseline_name_list = prior_dict["baseline_pdf"]["baseline"].tolist()
    assert sum(n.startswith("random_exit_") for n in baseline_name_list) == exp_config.RANDOM_RUN_COUNT == sum(n.startswith("random_reentry_") for n in baseline_name_list)
    # THE UNMODIFIED E1 / E2 PATHS EQUAL exp04's (x = 0, n = 1) AND exp07's (k = 4) RULE BUILDERS
    unmodified_dict = run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf, get_unmodified_candidate_list(), rule_builder_func, TEST_UNTOUCHED_START_STR, None, 2, alert_in=False)
    exp04_dict = run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf, [{"buffer": 0.0, "confirmation": 1}], get_exp04_rule_builder_func(daily_pdf_in), TEST_UNTOUCHED_START_STR, None, 2, alert_in=False)
    exp07_dict = run_candidate_replay_dict(ohlcv_array_dict_in, period_pdf, [{"light_k": 4}], get_exp07_rule_builder_func(daily_pdf_in), TEST_UNTOUCHED_START_STR, None, 2, alert_in=False)
    unmodified_summary_pdf = unmodified_dict["candidate_summary_pdf"]
    for exit_str, reference_dict in [("E1", exp04_dict), ("E2", exp07_dict)]:
        row = unmodified_summary_pdf[unmodified_summary_pdf["exit_rule"] == exit_str].iloc[0]
        assert row["strategy_total_return"] == reference_dict["candidate_summary_pdf"]["strategy_total_return"].iloc[0]
        assert row["exit_count"] == reference_dict["candidate_summary_pdf"]["exit_count"].iloc[0]
    passed(f"walk-forward (6 x {len(period_pdf)} candidate periods chain; ties -> E2M3; prior-only f -> f + 1; unmodified E1 / E2 = exp04 / exp07 exactly)")
    # RETURN THE PRIOR-ONLY PATH FOR THE REPORT TEST
    return prior_dict

# FUNCTION: TEST THE REPORTS
def test_reports(ohlcv_array_dict_in, vix_feature_pdf_in, prior_dict_in):
    # SCORECARD WITH THE REASONS AND THE VIX
    simulation_dict = prior_dict_in["simulation_dict"]
    scorecard_pdf = get_vix_scorecard_pdf(get_episode_scorecard_pdf(simulation_dict, ohlcv_array_dict_in), simulation_dict, vix_feature_pdf_in)
    if not scorecard_pdf.empty:
        assert set(scorecard_pdf["reentry_trigger"]) <= {"M1", "M2", "original rule", "end of data"}
        assert (scorecard_pdf["open_at_end"] == (scorecard_pdf["reentry_trigger"] == "end of data")).all()
        level_dict = dict(zip(vix_feature_pdf_in["date"], vix_feature_pdf_in["vix_level_prev"]))
        assert np.allclose(scorecard_pdf["vix_at_exit"].to_numpy(dtype=float), np.array([level_dict[d] for d in scorecard_pdf["exit_date"]], dtype=float), equal_nan=True)
    # CONCENTRATION BY HAND ON A SMALL SCORECARD (S/R = 1.2, 0.9, 1.05; EQUITY RATIO 1.1)
    small_scorecard_pdf = pd.DataFrame({"log_share_gain": np.log([1.2, 0.9, 1.05]), "s_over_r": [1.2, 0.9, 1.05],
                                        "exit_date": [pd.Timestamp(d).date() for d in ["2019-05-01", "2020-02-20", "2021-03-01"]],
                                        "reentry_date": [pd.Timestamp(d).date() for d in ["2019-06-01", "2020-04-15", "2021-04-01"]]})
    equity_pdf = pd.DataFrame({"date": [1, 2], "equity": [100.0, 110.0]})
    buy_hold_pdf = pd.DataFrame({"date": [1, 2], "equity": [100.0, 100.0]})
    concentration_dict = get_concentration_dict(small_scorecard_pdf, equity_pdf, buy_hold_pdf)
    assert np.isclose(concentration_dict["equity_ratio"], 1.1) and np.isclose(concentration_dict["product_s_over_r"], 1.2 * 0.9 * 1.05)
    assert np.isclose(concentration_dict["product_s_over_r_without_top1"], 0.9 * 1.05) and np.isclose(concentration_dict["equity_ratio_without_top1"], 1.1 / 1.2)
    assert np.isclose(concentration_dict["product_s_over_r_without_top2"], 0.9) and np.isclose(concentration_dict["equity_ratio_without_top2"], 1.1 / 1.2 / 1.05)
    assert concentration_dict["beats_buy_hold_without_top1"] is False and concentration_dict["window_episode_count"] == 1
    assert np.isclose(concentration_dict["window_share_of_log_excess"], np.log(0.9) / np.log(1.1))
    # THE YEARLY LOG EXCESS SUMS TO THE TOTAL LOG EXCESS OF THE PATH
    path_equity_pdf, buy_hold_equity_pdf = simulation_dict["daily_equity_pdf"], prior_dict_in["buy_hold_dict"]["daily_equity_pdf"]
    year_pdf = get_yearly_log_excess_pdf(path_equity_pdf, buy_hold_equity_pdf)
    assert np.isclose(year_pdf["log_excess"].sum(), np.log(path_equity_pdf["equity"].iloc[-1] / buy_hold_equity_pdf["equity"].iloc[-1]), atol=1e-9)
    passed(f"reports (scorecard reasons and VIX; concentration by hand; {len(year_pdf)} yearly log excesses sum to the total)")

"""
Runner
"""

# IF THE FILE IS RUN DIRECTLY
if __name__ == "__main__":
    # GENERATE THE SYNTHETIC DATA (ABOUT 3.5 YEARS) AND AN ALIGNED SYNTHETIC VIX TABLE
    print("Generating synthetic data...")
    synthetic_ohlcv_pdf = get_synthetic_ohlcv_pdf("2021-01-04", "2024-06-28", minute_vol_in=0.0006, seed_in=31)
    synthetic_ohlcv_array_dict = get_ohlcv_array_dict(synthetic_ohlcv_pdf)
    synthetic_daily_pdf = get_daily_feature_pdf(synthetic_ohlcv_array_dict)
    synthetic_vix_feature_pdf = get_synthetic_vix_feature_pdf(synthetic_daily_pdf)
    # RUN THE TESTS
    test_candidates()
    test_base_signals(synthetic_daily_pdf)
    test_modifications_by_hand()
    test_fresh_exit(synthetic_ohlcv_array_dict)
    test_mechanics(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_feature_pdf)
    test_no_look_ahead(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_feature_pdf)
    synthetic_prior_dict = test_walk_forward(synthetic_ohlcv_array_dict, synthetic_daily_pdf, synthetic_vix_feature_pdf)
    test_reports(synthetic_ohlcv_array_dict, synthetic_vix_feature_pdf, synthetic_prior_dict)
    print("\nAll exp12 tests passed ✅")
