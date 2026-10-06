"""
Workspace Tests: exp01 step 04 (multivariate signal check, diagnostic; PROTOCOL.md §13.3)

Run from the workspace root:   python tests/test_exp01_step04.py   (or python tests/run_all_tests.py)
(Plain asserts, no test framework required. Every test prints ✅ or raises.)

What is verified (synthetic data):
    1. Planted interaction: the TP probability (0.45 otherwise) is raised by 0.40 only when feature A AND feature B are
       both in their top 25%, and lowered by 0.25 x 0.40 / 0.75 = 0.133 when exactly one of them is. A feature alone then
       has a TP rate of 0.45 in its top 25% and 0.417 below (a small marginal effect, about 0.03). The multivariate check
       (real mean AUC above every one of 19 null runs) must detect it; the univariate step 02 check on the same data is
       reported (with these fixed seeds it stops).
    2. Pure noise: no information.
    3. The null shift keeps the labels in place and every feature row intact (the features of a row move together).
    4. Parallel null runs = sequential null runs (fixed LightGBM threads).
    5. The untouched-data assertion raises on a row dated 2026-05-14 (and on any row after the last validation date).
    6. Building blocks: the AUC with unit weights equals scikit-learn's; the top-decile interval equals the one of
       so.core.signal_bins (same bootstrap draws); a tie with the null is no information; the windows are step 02's.
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
from sklearn.metrics import roc_auc_score
from so.core.signal_bins import get_block_id_arr, get_bootstrap_bin_stat_pdf
from experiments.exp01_minute_entry import config as exp_config
from experiments.exp01_minute_entry.signal_check import get_signal_check_pdf, get_signal_check_verdict_dict, get_null_signal_count_pdf, \
                                                         get_session_shifted_feature_pdf
from experiments.exp01_minute_entry.multivariate_check import get_schedule_tuple, get_check_window_dict, check_last_date_bool, \
                                                               get_weighted_auc_arr, get_top_mask_arr, get_distance_metric_dict, run_model_check_dict, \
                                                               get_null_run_dict, get_null_run_pdf_tuple, get_multivariate_verdict_dict, \
                                                               get_calibration_pdf, get_feature_importance_pdf

# DEFINE THE FEATURES AND DISTANCES OF THE SYNTHETIC DATA
FEATURE_LIST = ["rsi", "stoch_k", "relative_volume", "daily_volatility"]
DELTA_LIST = [0.005, 0.01]

# FUNCTION: PRINT A PASSED TEST
def passed(name_str_in):
    """
    Prints a passed test.

    Args:
        name_str_in (str): Test name

    Returns:
        None
    """
    # DISPLAY INFORMATION
    print(f"✅ {name_str_in}")

# FUNCTION: GET A SYNTHETIC LABELED DATASET
def get_synthetic_window_tuple(raise_float_in, seed_in, row_count_in=20_000, high_share_in=0.25, train_share_in=0.7):
    """
    Builds a labeled dataset whose TP probability depends only on the interaction of rsi (A) and stoch_k (B).

    Args:
        raise_float_in (float): TP probability added when A and B are both high (0 = pure noise)
        seed_in (int): Random seed
        row_count_in (int): Rows
        high_share_in (float): Share of rows where a feature is "high"
        train_share_in (float): Share of rows in the training window

    Returns:
        tuple: (train_pdf, valid_pdf)
    """
    # CREATE THE FEATURES
    rng = np.random.default_rng(seed_in)
    ts_series = pd.Series(pd.date_range("2020-01-01 10:00", periods=row_count_in, freq="47min", tz="America/New_York"))
    a_arr, b_arr = rng.random(row_count_in), rng.random(row_count_in)
    # RAISE THE TP PROBABILITY WHEN BOTH ARE HIGH, LOWER IT WHEN EXACTLY ONE IS (A FEATURE'S HIGH ROWS ALONE STAY AT 0.45)
    a_high_arr, b_high_arr = a_arr > 1 - high_share_in, b_arr > 1 - high_share_in
    prob_arr = 0.45 + raise_float_in * (a_high_arr & b_high_arr) - high_share_in * raise_float_in / (1 - high_share_in) * (a_high_arr ^ b_high_arr)
    data_dict = {"decision_ts": ts_series, "entry_price": 700.0, "rsi": a_arr * 100, "stoch_k": b_arr * 100,
                 "relative_volume": rng.random(row_count_in), "daily_volatility": rng.random(row_count_in)}
    # DRAW THE LABELS OF EVERY DISTANCE
    for delta in DELTA_LIST:
        y_arr = (rng.random(row_count_in) < prob_arr).astype(float)
        data_dict[f"y_tp_{delta:.4f}"] = y_arr
        data_dict[f"net_return_{delta:.4f}"] = np.where(y_arr == 1, delta - 0.0001, -delta - 0.0001)
    # SPLIT THE WINDOWS
    data_pdf = pd.DataFrame(data_dict)
    split_int = int(row_count_in * train_share_in)
    return data_pdf.iloc[:split_int].reset_index(drop=True), data_pdf.iloc[split_int:].reset_index(drop=True)

# FUNCTION: RUN THE MULTIVARIATE CHECK ON SYNTHETIC WINDOWS
def get_synthetic_verdict_dict(train_pdf_in, valid_pdf_in, run_count_in=exp_config.SIGNAL_CHECK_NULL_RUN_COUNT):
    """
    Runs the real check and the null runs (no sample weights: the synthetic rows have no bars).

    Args:
        train_pdf_in, valid_pdf_in (pd.DataFrame): Synthetic windows
        run_count_in (int): Null runs

    Returns:
        dict: real (output of run_model_check_dict), verdict (output of get_multivariate_verdict_dict)
    """
    # RUN THE REAL CHECK AND THE NULL RUNS
    real_dict = run_model_check_dict(train_pdf_in, valid_pdf_in, FEATURE_LIST, None, DELTA_LIST, "none", iteration_count_in=200)
    null_summary_pdf, _ = get_null_run_pdf_tuple(train_pdf_in, valid_pdf_in, FEATURE_LIST, None, DELTA_LIST, run_count_in=run_count_in,
                                                 sample_weight_mode_str_in="none")
    # RETURN THE RESULTS
    return {"real": real_dict, "verdict": get_multivariate_verdict_dict(real_dict["metric_pdf"], null_summary_pdf)}

# FUNCTION: TEST THE PLANTED INTERACTION (MULTIVARIATE FINDS IT, UNIVARIATE REPORTED)
def test_planted_interaction():
    # BUILD THE WINDOWS
    train_pdf, valid_pdf = get_synthetic_window_tuple(0.40, 5)
    # ASSERT A SINGLE FEATURE'S TOP DECILE IS CLOSE TO THE REST'S TP RATE (SMALL MARGINAL EFFECT, ABOUT 0.03 BY CONSTRUCTION)
    top_decile_mask = train_pdf["rsi"] > train_pdf["rsi"].quantile(0.9)
    marginal_lift = train_pdf.loc[top_decile_mask, "y_tp_0.0050"].mean() - train_pdf.loc[~top_decile_mask, "y_tp_0.0050"].mean()
    assert abs(marginal_lift) < 0.06
    # RUN THE MULTIVARIATE CHECK
    result_dict = get_synthetic_verdict_dict(train_pdf, valid_pdf)
    verdict_dict = result_dict["verdict"]
    # ASSERT THE INTERACTION IS DETECTED ABOVE EVERY NULL RUN
    assert verdict_dict["information"] and verdict_dict["real_mean_auc"] > verdict_dict["null_max_mean_auc"]
    assert np.isclose(verdict_dict["null_p_value"], 1 / 20) and verdict_dict["outcome"] in ["B", "C"]
    # RUN THE UNIVARIATE STEP 02 CHECK ON THE SAME DATA (REPORTED)
    univariate_dict = get_signal_check_verdict_dict(get_signal_check_pdf(train_pdf, valid_pdf, FEATURE_LIST, DELTA_LIST, alert_in=False, iteration_count_in=300),
                                                    get_null_signal_count_pdf(train_pdf, valid_pdf, FEATURE_LIST, DELTA_LIST, iteration_count_in=300))
    # ASSERT THE UNIVARIATE CHECK IS SILENT OR WEAKER (NOT ABOVE EVERY NULL RUN) ON THIS DATA
    assert univariate_dict["verdict"] == "STOP"
    # ASSERT THE DESCRIPTIVE TABLES: THE TWO PLANTED FEATURES LEAD THE IMPORTANCE, THE CALIBRATION TABLE HAS EVERY ROW
    importance_pdf = get_feature_importance_pdf(result_dict["real"]["model_dict"], FEATURE_LIST)
    assert set(importance_pdf["feature"].iloc[:2]) == {"rsi", "stoch_k"} and np.isclose(importance_pdf["mean_gain_share"].sum(), 1.0)
    calibration_pdf = get_calibration_pdf(valid_pdf, result_dict["real"]["proba_pdf"], DELTA_LIST)
    assert len(calibration_pdf) == exp_config.MULTIVARIATE_CHECK_CALIBRATION_BIN_COUNT and calibration_pdf["row_count"].sum() == len(valid_pdf) * len(DELTA_LIST)
    assert calibration_pdf["observed_tp_rate"].iloc[-1] > calibration_pdf["observed_tp_rate"].iloc[0]
    passed(f"planted interaction (multivariate: mean AUC {verdict_dict['real_mean_auc']:.4f} vs null max {verdict_dict['null_max_mean_auc']:.4f}, "
           f"p = {verdict_dict['null_p_value']:.2f}, outcome {verdict_dict['outcome']}; univariate step 02 on the same data: {univariate_dict['signal_bin_count']} "
           f"signal bins vs null max {univariate_dict['null_max_signal_bin_count']}, p = {univariate_dict['null_p_value']:.2f}, {univariate_dict['verdict']}; "
           f"marginal top-decile lift of A {marginal_lift:+.3f})")

# FUNCTION: TEST PURE NOISE
def test_pure_noise():
    # BUILD THE WINDOWS WITHOUT ANY EFFECT
    train_pdf, valid_pdf = get_synthetic_window_tuple(0.0, 11)
    # RUN THE CHECK
    verdict_dict = get_synthetic_verdict_dict(train_pdf, valid_pdf)["verdict"]
    # ASSERT NO INFORMATION
    assert not verdict_dict["information"] and verdict_dict["outcome"] == "A" and verdict_dict["null_p_value"] > 0.05
    passed(f"pure noise (mean AUC {verdict_dict['real_mean_auc']:.4f} vs null max {verdict_dict['null_max_mean_auc']:.4f}, p = {verdict_dict['null_p_value']:.2f}, outcome A)")

# FUNCTION: TEST THAT THE NULL SHIFT KEEPS THE LABELS AND THE FEATURE ROWS
def test_null_shift_keeps_rows():
    # BUILD THE WINDOWS
    train_pdf, valid_pdf = get_synthetic_window_tuple(0.40, 5)
    # SHIFT AS NULL RUN 3 DOES (SAME SEEDING, TRAINING FIRST)
    rng = np.random.default_rng([exp_config.config.RANDOM_SEED, 3])
    shifted_train_pdf = get_session_shifted_feature_pdf(train_pdf, FEATURE_LIST, rng)
    shifted_valid_pdf = get_session_shifted_feature_pdf(valid_pdf, FEATURE_LIST, rng)
    # ASSERT THE LABELS, PRICES AND TIMES STAY IN PLACE
    for shifted_pdf, window_pdf in [(shifted_train_pdf, train_pdf), (shifted_valid_pdf, valid_pdf)]:
        for col_str in ["decision_ts", "entry_price", "y_tp_0.0050", "net_return_0.0050", "y_tp_0.0100"]:
            assert shifted_pdf[col_str].equals(window_pdf[col_str])
        # ASSERT EVERY FEATURE ROW IS INTACT (A ROW'S FEATURES MOVE TOGETHER) AND THE LINK IS BROKEN
        assert sorted(map(tuple, shifted_pdf[FEATURE_LIST].to_numpy())) == sorted(map(tuple, window_pdf[FEATURE_LIST].to_numpy()))
        assert not np.array_equal(shifted_pdf["rsi"].to_numpy(), window_pdf["rsi"].to_numpy())
    # ASSERT THE NULL RUN REPORTS THE SAME SHIFTS
    null_dict = get_null_run_dict(train_pdf, valid_pdf, FEATURE_LIST, None, DELTA_LIST, 3, sample_weight_mode_str_in="none")
    assert null_dict["summary_dict"]["train_shift_session_count"] == shifted_train_pdf.attrs["null_shift_session_count"]
    assert null_dict["summary_dict"]["valid_shift_session_count"] == shifted_valid_pdf.attrs["null_shift_session_count"]
    passed("null shift (labels, prices and times in place; feature rows intact; same shifts as null run 3)")

# FUNCTION: TEST THAT PARALLEL NULL RUNS EQUAL SEQUENTIAL ONES
def test_parallel_equals_sequential():
    # BUILD THE WINDOWS
    train_pdf, valid_pdf = get_synthetic_window_tuple(0.40, 5)
    # RUN 3 NULL RUNS SEQUENTIALLY AND IN 3 PROCESSES
    sequential_tuple = get_null_run_pdf_tuple(train_pdf, valid_pdf, FEATURE_LIST, None, DELTA_LIST, run_count_in=3, job_count_in=1, sample_weight_mode_str_in="none")
    parallel_tuple = get_null_run_pdf_tuple(train_pdf, valid_pdf, FEATURE_LIST, None, DELTA_LIST, run_count_in=3, job_count_in=3, sample_weight_mode_str_in="none")
    # ASSERT IDENTICAL RESULTS
    assert sequential_tuple[0].equals(parallel_tuple[0]) and sequential_tuple[1].equals(parallel_tuple[1])
    assert sequential_tuple[0]["mean_auc"].nunique() == 3
    passed(f"parallel null runs = sequential (3 runs, mean AUCs {sequential_tuple[0]['mean_auc'].round(4).tolist()})")

# FUNCTION: TEST THE UNTOUCHED-DATA ASSERTION
def test_untouched_assertion():
    # DEFINE ROWS UP TO THE LAST VALIDATION DATE
    ok_series = pd.Series(pd.to_datetime(["2026-04-28 15:58", "2026-04-29 15:58"]).tz_localize("America/New_York"))
    assert check_last_date_bool([ok_series], "2026-04-29")
    # ASSERT A ROW DATED 2026-05-14 RAISES (AND A ROW AFTER THE LAST VALIDATION DATE)
    for bad_str in ["2026-05-14 09:59", "2026-04-30 10:00"]:
        bad_series = pd.concat([ok_series, pd.Series(pd.to_datetime([bad_str]).tz_localize("America/New_York"))], ignore_index=True)
        try:
            check_last_date_bool([bad_series], "2026-04-29")
            raise AssertionError(f"a row dated {bad_str} was accepted")
        except ValueError:
            pass
    # ASSERT A LAST VALIDATION DATE IN THE UNTOUCHED WINDOW RAISES; PLAIN DATES ARE CHECKED TOO
    for args_tuple in [([ok_series], "2026-05-14"), ([pd.Series([pd.Timestamp("2026-05-14").date()])], "2026-04-29")]:
        try:
            check_last_date_bool(*args_tuple)
            raise AssertionError("an untouched date was accepted")
        except ValueError:
            pass
    passed("untouched-data assertion (a row dated 2026-05-14 or after the last validation date raises)")

# FUNCTION: TEST THE BUILDING BLOCKS
def test_building_blocks():
    # ASSERT THE AUC WITH UNIT WEIGHTS EQUALS SCIKIT-LEARN'S (WITH TIED SCORES)
    rng = np.random.default_rng(2)
    y_arr, score_arr = (rng.random(3000) < 0.5).astype(float), np.round(rng.random(3000), 2)
    auc = get_weighted_auc_arr(y_arr, score_arr, np.zeros(3000, dtype=int), np.ones((1, 1)))[0]
    assert np.isclose(auc, roc_auc_score(y_arr, score_arr))
    # ASSERT BLOCK WEIGHTS EQUAL REPEATED ROWS (BLOCK 1 COUNTED TWICE)
    block_arr = (np.arange(3000) >= 1500).astype(int)
    repeat_idx_arr = np.r_[np.arange(3000), np.arange(1500, 3000)]
    assert np.isclose(get_weighted_auc_arr(y_arr, score_arr, block_arr, np.array([[1.0, 2.0]]))[0], roc_auc_score(y_arr[repeat_idx_arr], score_arr[repeat_idx_arr]))
    # ASSERT THE TOP-DECILE INTERVAL EQUALS so.core.signal_bins (SAME DRAWS)
    train_pdf, valid_pdf = get_synthetic_window_tuple(0.40, 5)
    score_series = pd.Series(np.random.default_rng(4).random(len(valid_pdf)), index=valid_pdf.index)
    metric_dict = get_distance_metric_dict(valid_pdf, score_series, 0.005, iteration_count_in=300)
    top_mask_arr = get_top_mask_arr(score_series.to_numpy())
    bin_stat_pdf = get_bootstrap_bin_stat_pdf(pd.Series(np.where(top_mask_arr, "top", "rest")), get_block_id_arr(valid_pdf["decision_ts"], "week"),
                                              valid_pdf["y_tp_0.0050"].to_numpy(), valid_pdf["net_return_0.0050"].to_numpy(), np.full(len(valid_pdf), 0.5),
                                              iteration_count_in=300).set_index("bin")
    assert np.isclose(metric_dict["top_tp_rate_ci_low"], bin_stat_pdf.loc["top", "tp_rate_ci_low"]) and np.isclose(metric_dict["top_tp_rate"], bin_stat_pdf.loc["top", "tp_rate"])
    assert metric_dict["top_row_count"] == round(0.1 * len(valid_pdf)) and np.isclose(metric_dict["top_lift"], metric_dict["top_tp_rate"] - metric_dict["base_rate"])
    # ASSERT A TIE WITH THE NULL IS NO INFORMATION
    metric_pdf = pd.DataFrame({"delta": [0.005], "auc": [0.55], "clears_breakeven": [True]})
    tie_dict = get_multivariate_verdict_dict(metric_pdf, pd.DataFrame({"run_id": [0, 1], "mean_auc": [0.50, 0.55]}))
    assert not tie_dict["information"] and tie_dict["outcome"] == "A" and np.isclose(tie_dict["null_p_value"], 2 / 3)
    assert get_multivariate_verdict_dict(metric_pdf, pd.DataFrame({"run_id": [0, 1], "mean_auc": [0.50, 0.54]}))["outcome"] == "C"
    # ASSERT THE WINDOWS ARE STEP 02'S (TRAINING OF THE FIRST POOLED FOLD, THE LAST 4 VALIDATION QUARTERS)
    session_date_list = list(pd.bdate_range("2008-01-02", "2021-06-30").date)
    fold_pdf, pooled_fold_pdf = get_schedule_tuple(session_date_list)
    window_dict = get_check_window_dict(pooled_fold_pdf)
    assert pooled_fold_pdf.equals(fold_pdf.iloc[-4:]) and window_dict["train_years"] == 10
    assert window_dict["train_start"] == pooled_fold_pdf.iloc[0]["train_start_10y"] and window_dict["valid_end"] == fold_pdf.iloc[-1]["valid_end"]
    passed("building blocks (AUC = scikit-learn with ties and block weights; top-decile interval = signal_bins; ties are no information; step 02 windows)")

# RUN THE TESTS
if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    test_planted_interaction()
    test_pure_noise()
    test_null_shift_keeps_rows()
    test_parallel_equals_sequential()
    test_untouched_assertion()
    test_building_blocks()
    print("\nAll exp01 step 04 tests passed ✅")
