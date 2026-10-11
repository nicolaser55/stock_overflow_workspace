"""
Workspace Tests: exp08_vix_signal_check (the gates of the VIX line)

Run from the workspace root:   python tests/test_exp08.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic SPY data, synthetic VIX feature columns):
    1. The schedule check rejects a schedule that is not the 44 quarters of exp02-exp07.
    2. Analysis rows: complete rows only, label end = date of session i + 20, training flag, validation folds.
    3. The null shift moves the six VIX columns together by k rows (k in the range, seed-reproducible) and nothing else.
    4. The null p-value and pass rule ((1 + #null >= real) / 20; pass only if real > null maximum).
    5. G1 and G2 detect a planted VIX feature (look-ahead planted on purpose) and beat their null; every G2 training
       label ends before its quarter; BASE and AUGMENTED use the same rows.
    6. G3: a VIX level equal to the forward volatility passes; a VIX level equal to daily_volatility gives D = 0 (fails).
    7. G4 by hand (training threshold, means of the top rows in both windows, pass rule) and the gate decisions.
    8. The term-structure episodes by hand.
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
from so.features.vix_features import get_vix_feature_col_list
from so.core.continuous_replay import get_replay_period_pdf
from experiments.exp04_trend_exit.rules import get_schedule_tuple
from experiments.exp02_stop_reentry import config as exp02_config
from experiments.exp05_vol_scaled_exposure.exposure import get_forward_volatility_arr
from experiments.exp08_vix_signal_check import config as exp_config
from experiments.exp08_vix_signal_check.gates import (check_schedule_dict, get_analysis_pdf, get_shifted_analysis_pdf, get_null_dict, run_g1_dict, run_g2_dict,
                                                      get_auc_interval_dict, run_g3_dict, run_g4_dict, get_gate_decision_dict, get_term_episode_pdf)
from synthetic_data import get_synthetic_ohlcv_pdf

# DEFINE THE VIX COLUMNS OF THE PRIMARY VARIANT
VIX_COL_STR_LIST = get_vix_feature_col_list("prev")

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    print(f"✅ {name_str_in}")

# FUNCTION: BUILD THE SYNTHETIC SETUP
def get_setup_dict():
    # BUILD THE SPY TABLE AND A SHORT SCHEDULE (2-YEAR WINDOW)
    daily_pdf = get_daily_feature_pdf(get_ohlcv_array_dict(get_synthetic_ohlcv_pdf("2011-01-03", "2016-12-30", minute_vol_in=0.0006, seed_in=21)))
    fold_pdf, _ = get_schedule_tuple(daily_pdf["date"].tolist(), 2)
    # BUILD NOISE VIX FEATURES
    rng = np.random.default_rng(3)
    noise_pdf = pd.DataFrame(rng.normal(size=(len(daily_pdf), 6)), columns=VIX_COL_STR_LIST)
    noise_pdf.insert(0, "session_idx", daily_pdf["session_idx"].to_numpy())
    noise_pdf["vix_level_prev"] = 15 + np.abs(noise_pdf["vix_level_prev"]) * 5
    # BUILD PLANTED VIX FEATURES (THE LEVEL AND THE FADE CARRY THE LABEL; LOOK-AHEAD ON PURPOSE)
    planted_pdf = noise_pdf.copy()
    y_arr = daily_pdf["y_fwd_positive"].to_numpy(dtype=float)
    planted_pdf["vix_level_prev"] = 20 - 6 * np.nan_to_num(y_arr, nan=0.5) + rng.normal(0, 1.5, len(daily_pdf))
    planted_pdf["vix_fade_prev"] = -0.3 + 0.2 * np.nan_to_num(y_arr, nan=0.5) + rng.normal(0, 0.05, len(daily_pdf))
    # RETURN THE SETUP
    return {"daily_pdf": daily_pdf, "fold_pdf": fold_pdf, "noise_pdf": noise_pdf, "planted_pdf": planted_pdf}

# FUNCTION: TEST THE SCHEDULE CHECK
def test_schedule_check(setup_dict_in):
    # A SYNTHETIC SCHEDULE IS NOT THE REAL ONE: THE CHECK RAISES
    try:
        check_schedule_dict(setup_dict_in["fold_pdf"])
        raise RuntimeError("the schedule check accepted a wrong schedule")
    except AssertionError:
        pass
    passed(f"schedule check (rejects a {len(setup_dict_in['fold_pdf'])}-fold synthetic schedule)")

# FUNCTION: TEST THE ANALYSIS ROWS
def test_analysis_rows(setup_dict_in):
    # BUILD THE ROWS WITH A MISSING VIX VALUE
    daily_pdf, fold_pdf = setup_dict_in["daily_pdf"], setup_dict_in["fold_pdf"]
    vix_pdf = setup_dict_in["noise_pdf"].copy()
    vix_pdf.loc[600, "vix_term_prev"] = np.nan
    analysis_pdf = get_analysis_pdf(daily_pdf, vix_pdf, fold_pdf, VIX_COL_STR_LIST, start_date_str_in="2011-06-01")
    # COMPLETE ROWS ONLY, FROM THE START TO THE LAST VALIDATION SESSION
    assert analysis_pdf[config.DAILY_FEATURE_COL_STR_LIST + VIX_COL_STR_LIST + ["y_fwd_positive"]].notna().all().all() and 600 not in set(analysis_pdf["session_idx"])
    assert analysis_pdf["date"].min() >= pd.Timestamp("2011-06-01").date() and analysis_pdf["date"].max() <= pd.to_datetime(fold_pdf["valid_end"].iloc[-1]).date()
    # THE LABEL END IS THE DATE OF SESSION i + 20
    session_date_series = pd.Series(daily_pdf["date"].to_numpy(), index=daily_pdf["session_idx"].to_numpy())
    assert (analysis_pdf["label_end_date"].to_numpy() == session_date_series.reindex(analysis_pdf["session_idx"].to_numpy() + 20).to_numpy()).all()
    # TRAINING FLAG AND VALIDATION FOLDS (A SESSION SHARED BY TWO QUARTERS BELONGS TO THE LATER ONE, AS THE REPLAY PERIODS)
    assert (analysis_pdf["is_train"] == (analysis_pdf["date"] <= pd.to_datetime(fold_pdf["train_end"].iloc[0]).date())).all()
    period_pdf = get_replay_period_pdf(fold_pdf, daily_pdf["date"].tolist())
    for _, period_row in period_pdf.iterrows():
        in_bool = (analysis_pdf["date"] >= period_row["period_start"]) & (analysis_pdf["date"] <= period_row["period_end"])
        assert (analysis_pdf.loc[in_bool, "valid_fold_id"] == period_row["period_id"]).all() and in_bool.sum() > 0
    assert int((analysis_pdf["valid_fold_id"] >= 0).sum()) == int(((analysis_pdf["date"] >= period_pdf["period_start"].iloc[0]) & (analysis_pdf["date"] <= period_pdf["period_end"].iloc[-1])).sum())
    assert not (analysis_pdf["is_train"] & (analysis_pdf["valid_fold_id"] >= 0)).any()
    passed(f"analysis rows ({len(analysis_pdf)} complete rows, label end = session i + 20, training flag, {len(fold_pdf)} validation folds)")

# FUNCTION: TEST THE NULL SHIFT AND THE p-VALUE
def test_null(setup_dict_in):
    # BUILD THE ROWS
    analysis_pdf = get_analysis_pdf(setup_dict_in["daily_pdf"], setup_dict_in["noise_pdf"], setup_dict_in["fold_pdf"], VIX_COL_STR_LIST, start_date_str_in="2011-06-01")
    row_count = len(analysis_pdf)
    # THE BLOCK MOVES TOGETHER BY k ROWS; NOTHING ELSE MOVES; SAME SEED = SAME SHIFT
    for run_idx in range(5):
        shifted_pdf, shift_int = get_shifted_analysis_pdf(analysis_pdf, VIX_COL_STR_LIST, run_idx)
        assert round(0.25 * row_count) <= shift_int <= round(0.75 * row_count)
        assert np.allclose(shifted_pdf[VIX_COL_STR_LIST].to_numpy(), np.roll(analysis_pdf[VIX_COL_STR_LIST].to_numpy(), shift_int, axis=0))
        other_col_list = [c for c in analysis_pdf.columns if c not in VIX_COL_STR_LIST]
        assert shifted_pdf[other_col_list].equals(analysis_pdf[other_col_list])
        assert get_shifted_analysis_pdf(analysis_pdf, VIX_COL_STR_LIST, run_idx)[1] == shift_int
    assert len({get_shifted_analysis_pdf(analysis_pdf, VIX_COL_STR_LIST, r)[1] for r in range(19)}) > 10
    # p = (1 + #null >= real) / 20; PASS ONLY IF REAL > NULL MAXIMUM (19 RUNS OF A CONSTANT STATISTIC)
    null_dict = get_null_dict(analysis_pdf, VIX_COL_STR_LIST, lambda p: 1.0, 1.0, alert_in=False)
    assert null_dict["p_value"] == 1.0 and not null_dict["passed"] and null_dict["null_ge_count"] == 19 and len(null_dict["shift_list"]) == 19
    null_dict = get_null_dict(analysis_pdf, VIX_COL_STR_LIST, lambda p: 1.0, 1.5, alert_in=False)
    assert null_dict["p_value"] == 1 / 20 and null_dict["passed"]
    passed("null (block shift by k in [25%, 75%] of the rows, reproducible; p = (1 + #null >= real) / 20; pass = real > null max)")

# FUNCTION: TEST G1 AND G2
def test_g1_g2(setup_dict_in):
    # BUILD THE ROWS WITH PLANTED AND NOISE FEATURES
    daily_pdf, fold_pdf = setup_dict_in["daily_pdf"], setup_dict_in["fold_pdf"]
    planted_analysis_pdf = get_analysis_pdf(daily_pdf, setup_dict_in["planted_pdf"], fold_pdf, VIX_COL_STR_LIST, start_date_str_in="2011-06-01")
    # G1 FINDS THE PLANTED FEATURES AND BEATS ITS NULL (5 RUNS FOR SPEED)
    g1_dict = run_g1_dict(planted_analysis_pdf, VIX_COL_STR_LIST)
    assert g1_dict["s1"] >= 2 and {p.split(" ")[0] for p in g1_dict["signal_pair_list"]} <= {"vix_level_prev", "vix_fade_prev"}
    g1_null_dict = get_null_dict(planted_analysis_pdf, VIX_COL_STR_LIST, lambda p: run_g1_dict(p, VIX_COL_STR_LIST)["s1"], g1_dict["s1"], run_count_in=5, alert_in=False)
    assert g1_null_dict["passed"]
    # G2: SAME ROWS FOR BOTH MODELS; THE PLANTED VIX RAISES THE AUC AND BEATS ITS NULL
    assert exp_config.LOGISTIC_C == exp02_config.LOGISTIC_C
    g2_dict = run_g2_dict(planted_analysis_pdf, fold_pdf, VIX_COL_STR_LIST)
    assert len(g2_dict["base_prediction_pdf"]) == int((planted_analysis_pdf["valid_fold_id"] >= 0).sum()) == len(g2_dict["augmented_prediction_pdf"])
    assert g2_dict["d_auc"] > 0.1 and g2_dict["auc_augmented"] > 0.7 and g2_dict["base_prediction_pdf"]["proba"].notna().all()
    g2_null_dict = get_null_dict(planted_analysis_pdf, VIX_COL_STR_LIST, lambda p: run_g2_dict(p, fold_pdf, VIX_COL_STR_LIST, base_prediction_pdf_in=g2_dict["base_prediction_pdf"])["d_auc"],
                                 g2_dict["d_auc"], run_count_in=5, alert_in=False)
    assert g2_null_dict["passed"] and g2_null_dict["null_max"] < 0.05
    # THE BASE PREDICTIONS DO NOT DEPEND ON THE VIX COLUMNS
    noise_analysis_pdf = get_analysis_pdf(daily_pdf, setup_dict_in["noise_pdf"], fold_pdf, VIX_COL_STR_LIST, start_date_str_in="2011-06-01")
    noise_g2_dict = run_g2_dict(noise_analysis_pdf, fold_pdf, VIX_COL_STR_LIST)
    assert np.allclose(noise_g2_dict["base_prediction_pdf"]["proba"].to_numpy(), g2_dict["base_prediction_pdf"]["proba"].to_numpy())
    assert abs(noise_g2_dict["d_auc"]) < 0.05
    # INTERVALS CONTAIN THE ESTIMATES
    interval_dict = get_auc_interval_dict(g2_dict["base_prediction_pdf"], g2_dict["augmented_prediction_pdf"], iteration_count_in=200)
    assert interval_dict["d_auc_ci_low"] <= g2_dict["d_auc"] <= interval_dict["d_auc_ci_high"] and interval_dict["d_auc_ci_low"] > 0
    # A TRAINING LABEL THAT ENDS INSIDE A QUARTER IS REFUSED
    bad_pdf = planted_analysis_pdf.copy()
    bad_pdf["label_end_date"] = bad_pdf["date"].shift(-60).fillna(bad_pdf["date"].iloc[-1])
    try:
        run_g2_dict(bad_pdf, fold_pdf, VIX_COL_STR_LIST)
        raise RuntimeError("a leaking training label was accepted")
    except AssertionError:
        pass
    passed(f"G1 (planted S1 = {g1_dict['s1']}, null max {g1_null_dict['null_max']:.0f}) and G2 (planted dAUC {g2_dict['d_auc']:.3f}, null max {g2_null_dict['null_max']:.3f}; noise dAUC {noise_g2_dict['d_auc']:.3f}; leak refused)")

# FUNCTION: TEST G3
def test_g3(setup_dict_in):
    # PLANT THE FORWARD VOLATILITY AS THE VIX LEVEL (LOOK-AHEAD ON PURPOSE): D > 0 AND PASS
    daily_pdf, fold_pdf = setup_dict_in["daily_pdf"], setup_dict_in["fold_pdf"]
    vix_pdf = setup_dict_in["noise_pdf"].copy()
    vix_pdf["vix_level_prev"] = get_forward_volatility_arr(daily_pdf, 20) * 1000
    analysis_pdf = get_analysis_pdf(daily_pdf, vix_pdf, fold_pdf, VIX_COL_STR_LIST, start_date_str_in="2011-06-01")
    g3_dict = run_g3_dict(analysis_pdf, daily_pdf, iteration_count_in=200)
    assert g3_dict["spearman_vix"] > 0.999 and g3_dict["passed"] and g3_dict["d"] > 0
    # THE LAST FORWARD SESSION IS 20 SESSIONS AFTER THE LAST VALIDATION ROW
    last_idx = int(analysis_pdf.loc[analysis_pdf["valid_fold_id"] >= 0, "session_idx"].max())
    assert g3_dict["last_forward_session_date"] == daily_pdf["date"].iloc[last_idx + 20]
    # A VIX LEVEL EQUAL TO daily_volatility GIVES D = 0 (FAILS)
    vix_pdf["vix_level_prev"] = daily_pdf["daily_volatility"].to_numpy() * 1600
    analysis_pdf = get_analysis_pdf(daily_pdf, vix_pdf, fold_pdf, VIX_COL_STR_LIST, start_date_str_in="2011-06-01")
    g3_dict = run_g3_dict(analysis_pdf, daily_pdf, iteration_count_in=200)
    assert abs(g3_dict["d"]) < 1e-12 and not g3_dict["passed"]
    passed("G3 (forward volatility planted: pass; VIX = daily_volatility: D = 0, fail)")

# FUNCTION: TEST G4, THE GATE DECISIONS AND THE EPISODES
def test_g4_gates_episodes(setup_dict_in):
    # G4 BY HAND
    daily_pdf, fold_pdf = setup_dict_in["daily_pdf"], setup_dict_in["fold_pdf"]
    analysis_pdf = get_analysis_pdf(daily_pdf, setup_dict_in["noise_pdf"], fold_pdf, VIX_COL_STR_LIST, start_date_str_in="2011-06-01")
    g4_dict = run_g4_dict(analysis_pdf)
    train_pdf, valid_pdf = analysis_pdf[analysis_pdf["is_train"]], analysis_pdf[analysis_pdf["valid_fold_id"] >= 0]
    threshold = np.quantile(train_pdf["vix_level_prev"], 0.8)
    assert np.isclose(g4_dict["threshold"], threshold)
    assert np.isclose(g4_dict["train_mean_fwd_return"], train_pdf.loc[train_pdf["vix_level_prev"] >= threshold, "fwd_net_return_20d"].mean())
    assert np.isclose(g4_dict["valid_mean_fwd_return"], valid_pdf.loc[valid_pdf["vix_level_prev"] >= threshold, "fwd_net_return_20d"].mean())
    assert g4_dict["passed"] == (g4_dict["train_mean_fwd_return"] < 0 and g4_dict["valid_mean_fwd_return"] < 0)
    assert g4_dict["train_ci_low"] <= g4_dict["train_mean_fwd_return"] <= g4_dict["train_ci_high"]
    # FORCE NEGATIVE RETURNS IN THE TOP ROWS: PASS
    negative_pdf = analysis_pdf.copy()
    negative_pdf.loc[negative_pdf["vix_level_prev"] >= threshold, "fwd_net_return_20d"] = -0.01
    assert run_g4_dict(negative_pdf)["passed"]
    # THE GATE DECISIONS
    assert get_gate_decision_dict(False, False, False, False) == {"exp09_runs": False, "exp10_runs": False, "exp11_runs": False, "vix_line_stops": True}
    assert get_gate_decision_dict(True, False, True, False) == {"exp09_runs": True, "exp10_runs": False, "exp11_runs": False, "vix_line_stops": False}
    assert get_gate_decision_dict(False, True, False, False) == {"exp09_runs": True, "exp10_runs": False, "exp11_runs": True, "vix_line_stops": False}
    assert get_gate_decision_dict(False, False, True, True) == {"exp09_runs": False, "exp10_runs": True, "exp11_runs": False, "vix_line_stops": False}
    # THE EPISODES BY HAND (TERM >= 1 ON SESSIONS 100-104 AND 300)
    term_series = pd.Series(np.full(len(daily_pdf), 0.9))
    term_series.iloc[100:105] = 1.05
    term_series.iloc[300] = 1.0
    episode_pdf = get_term_episode_pdf(daily_pdf, term_series, daily_pdf["date"].iloc[0], daily_pdf["date"].iloc[-1])
    assert len(episode_pdf) == 2 and episode_pdf["session_count"].tolist() == [5, 1] and episode_pdf["start_date"].iloc[0] == daily_pdf["date"].iloc[100]
    assert np.isclose(episode_pdf["spy_return_episode"].iloc[0], daily_pdf["session_close"].iloc[104] / daily_pdf["fill_open"].iloc[100] - 1)
    assert np.isclose(episode_pdf["spy_return_next_20"].iloc[0], daily_pdf["session_close"].iloc[124] / daily_pdf["session_close"].iloc[104] - 1)
    assert len(get_term_episode_pdf(daily_pdf, term_series, daily_pdf["date"].iloc[200], daily_pdf["date"].iloc[-1])) == 1
    passed("G4 by hand (training threshold, both windows, pass rule), gate decisions, term-structure episodes")

# RUN THE TESTS
if __name__ == "__main__":
    setup_dict = get_setup_dict()
    test_schedule_check(setup_dict)
    test_analysis_rows(setup_dict)
    test_null(setup_dict)
    test_g1_g2(setup_dict)
    test_g3(setup_dict)
    test_g4_gates_episodes(setup_dict)
    print("\nAll exp08 tests passed ✅")
